"""needs-info 停摆判定（#977）：算出今天哪些票该标 `stale`、哪些该摘，只打印、不写入。

用法：

    python3 tool/stale.py --dry-run
    python3 tool/stale.py --dry-run --days 12

判据（父票 #976）：最后一条评论不是报告者发的、且距今已满 N 天 → 加标；报告者回话后 → 摘标；
一条评论都没有时从票的 `createdAt` 起算。带 `in-progress` / `waiting-for-verify` 的票不参与。
已带 `stale` 的票不再进加标名单，所以同一张票重复扫描不会多出一条评论。

时间一律由调用方注入：判定函数不读真实时钟，回放才能用同一份代码跑不同天数。

写层见 #978：本脚本只读 `gh issue list`，任何参数都不会产生 `gh` 写操作。

退出码：0 算出结论；1 参数不合规；2 `gh` 调用失败（读不到票时给不出结论）。
"""
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass

STATE_LABEL = "needs-info"
STALE_LABEL = "stale"
SKIP_LABELS = ("in-progress", "waiting-for-verify")
DEFAULT_DAYS = 14
LIMIT = 1000
COMMENT_CAP = 100     # `gh issue list` 的 comments 字段只带前 100 条；到顶要另读一次
FIELDS = "number,title,createdAt,author,labels,comments"

MARK, UNMARK, KEEP, SKIP = "mark", "unmark", "keep", "skip"

EXIT_OK, EXIT_USAGE, EXIT_GH = 0, 1, 2

USAGE = """用法：python3 tool/stale.py [--dry-run] [--days N]

  --dry-run   只打印，不产生任何写操作（#978 上线前这也是唯一的行为）
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
    if last is None:
        # 没有任何评论：没人回过话，从票的 createdAt 起算
        since, who, replied = instant(issue.get("createdAt")), "", False
    else:
        since, who = last
        replied = (who == reporter) if who else None      # None = 末评作者读不出，不猜
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
    try:
        issues = read_open(runner or runner_for())
    except GhError as error:
        print(error, file=sys.stderr)
        return EXIT_GH
    except OSError as error:      # 没装 gh 或不在 PATH 上
        print(f"跑不了 gh：{error}", file=sys.stderr)
        return EXIT_GH
    now = now or datetime.now(timezone.utc)
    report = scan(issues, now, options.days)
    print(render(report, now, options.days))
    if not options.dry_run:
        print("本脚本只算不写：没有改动任何票（写层见 #978）。")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
