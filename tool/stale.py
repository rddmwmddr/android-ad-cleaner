"""needs-info 停摆判定与写入（#977 判定 / #978 写层）：给该停摆的票打 `stale` 并留一条说明，报告者回话后摘掉。

用法：

    python3 tool/stale.py
    python3 tool/stale.py --dry-run
    python3 tool/stale.py --dry-run --days 12

判据（父票 #976）：最后一条评论不是报告者发的、且距今已满 N 天 → 加标；报告者回话后 → 摘标；
一条评论都没有时从票的 `createdAt` 起算。带 `in-progress` / `waiting-for-verify` /
`blocked-on-device` 的票不参与——卡在一台维护者没有的机器上的票，等不到报告者回话不是停摆。
已带 `stale` 的票不再进加标名单，所以同一张票重复扫描不会多出一条评论。

动作只在状态跃迁时发生：加标新打上的那一次才写评论，摘标只摘标签不写评论。加标写入顺序是
先加标签后写评论——标签没加上就不写评论，否则下次扫描仍判成「该加」，会再留一条。

时间一律由调用方注入：判定函数不读真实时钟，回放才能用同一份代码跑不同天数。

退出码：0 算出结论且写入都成功；1 参数不合规；2 `gh` 读失败（读不到票时给不出结论）；
3 有票写失败（其余票照常写，失败逐张列出）。
"""
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from stdio import use_utf8_console

use_utf8_console()

STATE_LABEL = "needs-info"
STALE_LABEL = "stale"
BLOCKED_LABEL = "blocked-on-device"
SKIP_LABELS = ("in-progress", "waiting-for-verify", BLOCKED_LABEL)
DEFAULT_DAYS = 14
LIMIT = 1000
COMMENT_CAP = 100     # `gh issue list` 的 comments 字段只带前 100 条；到顶要另读一次
FIELDS = "number,title,createdAt,author,labels,comments"

MARK, UNMARK, KEEP, SKIP = "mark", "unmark", "keep", "skip"

EXIT_OK, EXIT_USAGE, EXIT_GH, EXIT_WRITE = 0, 1, 2, 3

# 评论文案只在这里拼：不 @ 任何人，也不给关票的承诺——是否关票由维护者按现有信息判断。
REPLY_HINT = "补齐后直接在本票回复；如果确实拿不到，说一声，我们会按现有信息评估后关票。"

USAGE = """用法：python3 tool/stale.py [--dry-run] [--days N]

  --dry-run   只打印，不产生任何写操作
  --days N    阈值天数，默认 14；历史回放时用 12"""


class GhError(RuntimeError):
    """`gh` 调用失败：读不到票时整条命令给不出结局。"""


class Unreadable(RuntimeError):
    """评论读不出确定的先后与作者：不猜，整票跳过。"""


@dataclass(frozen=True)
class Decision:
    """一张票的判定：`action` 是结论，`reason` 是给人看的一句话，其余是对账用的现场。"""
    number: int
    title: str
    action: str
    reason: str
    days: int = 0
    since: "datetime | None" = None      # 起算时刻；读不出来是 None
    last_author: str = ""
    stale: bool = False


@dataclass(frozen=True)
class Report:
    """整批票的结论：加标名单与摘标名单按票号升序，`decided` 含没有动作的票。"""
    mark: tuple
    unmark: tuple
    decided: tuple

    @property
    def skipped(self):
        return tuple(item for item in self.decided if item.action == SKIP)


@dataclass(frozen=True)
class Options:
    dry_run: bool
    days: int


def login(author):
    return str((author or {}).get("login") or "").lower()


def instant(text):
    """服务器时间戳 -> 带时区的 datetime；读不出来返回 None——不猜。"""
    try:
        value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def age_days(since, now):
    """起算到今天的整日数；未来时间戳按 0 算。"""
    if now.tzinfo is None:
        now = now.astimezone()
    return max((now - since).days, 0)


def last_comment(comments):
    """按服务器时间取最后一条评论 -> (时刻, 作者 login)；一条都没有返回 None。

    不依赖数组顺序：`gh` 现在按升序给，但判定不该押在这个约定上。判不出的两种情形抛
    `Unreadable`——有时间戳读不出，或同一时刻有多位作者（谁最后说的没有答案），都不猜。
    """
    timed = [(instant(item.get("createdAt")), login(item.get("author"))) for item in comments]
    if any(when is None for when, _ in timed):
        raise Unreadable("有评论读不出时间，判不了末评")
    if not timed:
        return None
    latest = max(when for when, _ in timed)
    speakers = {who for when, who in timed if when == latest}
    if len(speakers) > 1:
        raise Unreadable(f"{stamp(latest)} 有多位作者同时发言，判不了末评是谁")
    return latest, speakers.pop()


def stamp(value):
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else "时间未知"


def decide(issue, now, days=DEFAULT_DAYS):
    """一张票 -> Decision。纯函数：只读输入，不读时钟、不调 `gh`。"""
    number = issue.get("number")
    title = (issue.get("title") or "").strip()
    labels = {item.get("name", "") for item in issue.get("labels") or []}
    stale = STALE_LABEL in labels

    def no(action, reason, when=None, who="", age=0):
        return Decision(number, title, action, reason, age, when, who, stale)

    if STATE_LABEL not in labels:
        return no(SKIP, f"没有 {STATE_LABEL} 标签")
    blocked = [name for name in SKIP_LABELS if name in labels]
    if blocked:
        return no(SKIP, f"带 {blocked[0]}，不参与本机制")
    reporter = login(issue.get("author"))
    if not reporter:
        return no(SKIP, "读不出票的作者，判不了末评算不算报告者")

    try:
        last = last_comment(issue.get("comments") or [])
    except Unreadable as error:
        return no(SKIP, str(error))
    replied: bool | None                              # None = 末评作者读不出，不猜
    if last is None:
        # 没有任何评论：没人回过话，从票的 createdAt 起算
        since, who, replied = instant(issue.get("createdAt")), "", False
    else:
        since, who = last
        replied = (who == reporter) if who else None
    if since is None:
        return no(SKIP, "起算时间读不出来")

    age = age_days(since, now)
    basis = (f"票下没有评论，创建于 {stamp(since)}" if last is None
             else f"末评由 {who} 发在 {stamp(since)}")
    if replied is None:
        return no(KEEP, "末评作者读不出，判不了算不算报告者", since, who, age)
    if replied:
        if stale:
            return no(UNMARK, f"报告者已回话（{stamp(since)}）", since, who, age)
        return no(KEEP, f"末评由报告者发出（{stamp(since)}），球在维护者这边", since, who, age)
    if stale:
        return no(KEEP, f"已带 {STALE_LABEL}，{basis}，不动", since, who, age)
    if age >= days:
        return no(MARK, f"{basis}，已 {age} 天", since, who, age)
    return no(KEEP, f"{basis}，只过了 {age} 天（阈值 {days} 天）", since, who, age)


def scan(issues, now, days=DEFAULT_DAYS):
    """整批票 -> Report；名单按票号升序。"""
    decided = tuple(sorted((decide(issue, now, days) for issue in issues),
                           key=lambda item: item.number))
    return Report(mark=tuple(item for item in decided if item.action == MARK),
                  unmark=tuple(item for item in decided if item.action == UNMARK),
                  decided=decided)


def read_open(runner):
    """读 open 的 `needs-info` 票（含评论）-> gh 的 JSON 列表。

    `gh issue list` 的 comments 字段只带前 100 条（GraphQL `first: 100`），翻得完的只有
    `gh issue view`：到顶的票补读一次，否则末评会停在旧的那条，把还在等回应的票判成该标。
    """
    out, err, rc = runner("gh", "issue", "list", "--state", "open", "--label", STATE_LABEL,
                          "--limit", str(LIMIT), "--json", FIELDS)
    if rc != 0:
        raise GhError(f"读不到 open 的 {STATE_LABEL} 票：{(err or out).strip() or 'gh 返回非零'}")
    issues = payload(out, "`gh issue list`")
    if not isinstance(issues, list):
        raise GhError("`gh issue list` 的输出不是票的列表")
    return [top_up(issue, runner) if len(issue.get("comments") or []) >= COMMENT_CAP else issue
            for issue in issues]


def payload(text, source):
    try:
        return json.loads(text)
    except ValueError as error:
        raise GhError(f"{source} 的输出不是 JSON：{error}") from error


def top_up(issue, runner):
    """评论到顶的票：用 `gh issue view` 把评论补全再判定。"""
    number = issue.get("number")
    out, err, rc = runner("gh", "issue", "view", str(number), "--json", "comments")
    if rc != 0:
        raise GhError(f"补读 #{number} 的评论不全：{(err or out).strip() or 'gh 返回非零'}")
    comments = payload(out, f"`gh issue view {number}`").get("comments") or []
    return dict(issue, comments=comments)


def runner_for(cwd=None):
    """默认的 `gh` 执行器：签名 `(script, *args) -> (标准输出, 错误输出, 返回码)`。"""
    def run(script, *args):
        done = subprocess.run([script, *args], cwd=cwd, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        return done.stdout, done.stderr, done.returncode
    return run


def render(report, now, days):
    lines = [f"{STATE_LABEL} {len(report.decided)} 张，阈值 {days} 天，判定时刻 {stamp(now)}"]

    def block(name, items):
        lines.append(f"{name} {len(items)}：")
        for item in items:
            lines.append(f"  #{item.number}  {item.title}（{item.reason}）")

    block("加标", report.mark)
    block("摘标", report.unmark)
    kept = [item for item in report.decided if item.action == KEEP]
    lines.append(f"不动 {len(kept)}；跳过 {len(report.skipped)}"
                 + (f"（{'、'.join(sorted({item.reason for item in report.skipped}))}）"
                    if report.skipped else ""))
    return "\n".join(lines)


def comment_body(decision):
    """停摆说明：说清隔了多久、下一步该谁做什么。没有评论的票不说「上一次回复」。"""
    lead = (f"距上一次回复已 {decision.days} 天。" if decision.last_author
            else f"本票创建已 {decision.days} 天，还没有收到过回复。")
    return "\n\n".join([lead, REPLY_HINT])


def gh(runner, *args):
    """一次 `gh` 调用 -> (标准输出或错误文本, 返回码)；与 tool/claim.py 里那组同名 helper 同形。

    两份而不共用一份：claim 已经 import 本模块的 `STALE_LABEL`，反过来 import 就成环。
    """
    out, err, rc = runner("gh", *args)
    return (out if rc == 0 else (err or out)).strip(), rc


def set_labels(number, runner, add, remove):
    """加 / 摘标签 -> 失败原因或 None。"""
    if not add and not remove:
        return None
    args = ["issue", "edit", str(number)]
    for name in add:
        args += ["--add-label", name]
    for name in remove:
        args += ["--remove-label", name]
    text, rc = gh(runner, *args)
    return None if rc == 0 else f"改标签失败：{text or 'gh 返回非零'}"


def post_comment(number, body, runner):
    """写一条评论 -> 失败原因或 None。"""
    text, rc = gh(runner, "issue", "comment", str(number), "--body", body)
    return None if rc == 0 else f"写评论失败：{text or 'gh 返回非零'}"


def apply_one(decision, runner):
    """执行一条判定 -> (动作说明, 失败原因或 None)；只处理 MARK 与 UNMARK。"""
    if decision.action == MARK:
        # 先加标签再写评论：标签一旦加上，下次扫描就判成 KEEP，不会为这张票再写一条评论
        problem = set_labels(decision.number, runner, [STALE_LABEL], [])
        if problem:
            return "", problem
        problem = post_comment(decision.number, comment_body(decision), runner)
        if problem:
            # 评论没写成就把标签退回：留着它这张票永远不会再被补一句说明。
            # 退回失败时由下面那条失败上报兜着，不会静默。
            set_labels(decision.number, runner, [], [STALE_LABEL])
            return "", problem
        return "加标+评论", None
    if decision.action == UNMARK:
        return "摘标", set_labels(decision.number, runner, [], [STALE_LABEL])
    return "", None


def apply_report(report, runner):
    """按判定写入 -> (成功 [(票号, 动作)], 失败 [(票号, 原因)])；一张失败不影响其余。"""
    done, failed = [], []
    for decision in report.mark + report.unmark:
        note, problem = apply_one(decision, runner)
        if problem:
            failed.append((decision.number, problem))
        else:
            done.append((decision.number, note))
    return done, failed


def render_writes(done, failed):
    lines = [f"写入 {len(done)}："] + [f"  #{number}  {note}" for number, note in done]
    if failed:
        lines.append(f"失败 {len(failed)}：")
        lines += [f"  #{number}  {problem}" for number, problem in failed]
    return "\n".join(lines)


def parse_args(argv):
    """命令行 -> Options；不合规抛 ValueError（文案即用法）。"""
    options, pending = Options(dry_run=False, days=DEFAULT_DAYS), list(argv)
    while pending:
        item = pending.pop(0)
        if item == "--dry-run":
            options = Options(True, options.days)
        elif item == "--days":
            if not pending:
                raise ValueError(f"--days 后面要跟天数\n{USAGE}")
            raw = pending.pop(0)
            if not raw.isdigit() or int(raw) < 1:
                raise ValueError(f"--days 要是正整数，收到 {raw}\n{USAGE}")
            options = Options(options.dry_run, int(raw))
        else:
            raise ValueError(f"不认识的参数 {item}\n{USAGE}")
    return options


def main(argv, runner=None, now=None):
    try:
        options = parse_args(argv)
    except ValueError as error:
        print(error, file=sys.stderr)
        return EXIT_USAGE
    runner = runner or runner_for()
    try:
        issues = read_open(runner)
    except GhError as error:
        print(error, file=sys.stderr)
        return EXIT_GH
    except OSError as error:      # 没装 gh 或不在 PATH 上
        print(f"跑不了 gh：{error}", file=sys.stderr)
        return EXIT_GH
    now = now or datetime.now(timezone.utc)
    report = scan(issues, now, options.days)
    print(render(report, now, options.days))
    if options.dry_run:
        print("--dry-run：只算不写，没有改动任何票。")
        return EXIT_OK
    done, failed = apply_report(report, runner)
    print(render_writes(done, failed))
    return EXIT_WRITE if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
