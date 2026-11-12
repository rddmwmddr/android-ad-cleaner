"""开工认领：一条命令写认领评论、摘待办标签，仲裁只看票下的评论（#932）。

用法：

    python3 tool/claim.py 932
    python3 tool/claim.py 932 --release
    python3 tool/claim.py 932 --abandon [--restore ready-for-agent]

身份是 `sha1(<主机名>\0<worktree 绝对路径>)` 的前 8 位：同一 worktree 里恢复的会话仍认得出自己，
不同会话必然不同。主机名只进哈希，评论里只留那 8 位——公开 issue 上不出现本机主机名与目录。

认领记录是票下的一条评论，标签只是随附的可见信号。评论落在 `gh issue view --comments` 里，
实现会话本来就会读；标签不在那个载荷里，只靠标签的认领会被漏掉。

退出码：0 认领到手（含本会话已持有）；1 拒绝（票已关闭、票面读不出确定结局、本会话没有未收尾认领）；
2 被别人占；3 `gh` 调用失败（此时不改标签）。
"""
import hashlib
import json
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from gh import GhError, call, json_of, runner_for

from stale import STALE_LABEL     # 停摆标记只此一份；认领时要摘掉（#978）

from stdio import use_utf8_console

use_utf8_console()

CLAIMED = "认领中"
RELEASED = "认领结束"
ABANDONED = "认领放弃"
KINDS = (CLAIMED, RELEASED, ABANDONED)
IN_PROGRESS = "in-progress"
ROLE_LABELS = ("ready-for-agent", "ready-for-human", "needs-triage")
LABEL_KEY = "原标签："
RESTORE_KEY = "恢复："
EMPTY_LABELS = "（无）"
COMMAND = "python3 tool/claim.py"
STAMP = "%Y-%m-%d %H:%M"

EXIT_OK, EXIT_REFUSED, EXIT_TAKEN, EXIT_GH = 0, 1, 2, 3

USAGE = f"""用法：{COMMAND} <票号> [--release | --abandon [--restore <标签>]]

  <票号>        要认领的 issue 编号
  --release     合入后收尾：写收尾评论、摘 in-progress
  --abandon     放弃或改派：写放弃评论、摘 in-progress、恢复认领时的角色标签
  --restore     放弃时恢复的标签（可重复；不给就用认领评论里记下的）"""

ACTIONS = {"--release": "release", "--abandon": "abandon"}

HEADER = re.compile(r"^\*\*(?P<kind>" + "|".join(KINDS) + r")\*\*：(?P<rest>.*)$")
FIELD = re.compile(r"^(?P<name>session|host|branch|worktree) `(?P<value>[^`]*)`$")
TIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
COMMENT_URL = re.compile(r"(?:/issues/comments/|#issuecomment-)(\d+)")
ISSUE_URL = re.compile(r"github\.com/([^/]+/[^/]+)/issues/\d+")


class Unreadable(RuntimeError):
    """一条以固定前缀开头的评论，字段却读不全：不猜它算不算认领。"""


@dataclass(frozen=True)
class Record:
    kind: str
    session: str
    branch: str
    stamp: str
    labels: tuple
    url: str
    created: str

    @property
    def open(self):
        return self.kind == CLAIMED


@dataclass(frozen=True)
class Session:
    """一次认领的身份：`session` 是机器可比的键，`branch` 只写进评论给人看。"""
    session: str
    branch: str


def session_id(host, worktree):
    """身份键：主机名与 worktree 绝对路径的 sha1 前 8 位，主机名不进明文（#970）。"""
    digest = hashlib.sha1(f"{host}\x00{worktree}".encode("utf-8")).hexdigest()[:8]
    return digest


def git_text(*args, cwd=None):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip() or "git 调用失败")
    return done.stdout.strip()


def session_context(cwd=None, host=None):
    """Session：worktree 与分支取当前仓库，host 取 `hostname -s` 那个短名。

    macOS 的 `socket.gethostname()` 带 `.local` 后缀，不截掉就和手工认领写下的主机名对不上。
    """
    worktree = git_text("rev-parse", "--show-toplevel", cwd=cwd)
    branch = git_text("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    host = host or socket.gethostname().split(".")[0]
    return Session(session_id(host, worktree), branch)


def read_issue(number, runner):
    return json_of(runner, "issue", "view", str(number),
                   "--json", "number,state,labels,comments,url",
                   source=f"`gh issue view {number}`")


def label_names(issue):
    return [item.get("name", "") for item in issue.get("labels") or []]


def role_labels(issue):
    """票上挂着的待办池标签：认领时要摘掉的那几张。"""
    names = label_names(issue)
    return [name for name in ROLE_LABELS if name in names]


def parse_comment(comment):
    """认领评论 -> Record；不是认领评论返回 None；前缀对上但字段读不全抛 Unreadable。

    #970 之前的评论带 `host` 与 `worktree` 两个字段，用它们重算身份键；之后的评论只留
    `session`，直接用评论里的值。两种格式算出来的是同一个键，历史认领不必回填。
    """
    body = (comment.get("body") or "").strip()
    first = body.splitlines()[0] if body else ""
    match = HEADER.match(first)
    if not match:
        return None
    fields, stamp = {}, None
    for part in match.group("rest").split(" · "):
        found = FIELD.match(part.strip())
        if found:
            fields[found.group("name")] = found.group("value")
        elif TIME.match(part.strip()):
            stamp = part.strip()
    missing = [name for name in ("session", "branch") if name not in fields]
    if missing or stamp is None:
        where = comment.get("url") or "无链接"
        raise Unreadable(f"{where} 的认领评论读不全：缺 {'、'.join(missing) or '时间'}")
    created = (comment.get("createdAt") or "").strip()
    if not created:
        raise Unreadable(f"{comment.get('url') or '无链接'} 的认领评论没有 createdAt，判不了先后")
    host, worktree = fields.get("host", ""), fields.get("worktree", "")
    if "host" in fields or "worktree" in fields:
        if not (host and worktree):
            where = comment.get("url") or "无链接"
            raise Unreadable(f"{where} 的认领评论只写了 host 与 worktree 中的一个，判不了身份键")
        session = session_id(host, worktree)
    else:
        session = fields["session"]
    return Record(
        kind=match.group("kind"),
        session=session,
        branch=fields["branch"],
        stamp=stamp,
        labels=original_labels(body),
        url=comment.get("url") or "",
        created=created,
    )


def original_labels(body):
    """认领评论里的 `原标签：` 行；没写或写「（无）」时为空。"""
    for line in body.splitlines()[1:]:
        line = line.strip()
        if line.startswith(LABEL_KEY):
            raw = line[len(LABEL_KEY):].strip()
            if not raw or raw == EMPTY_LABELS:
                return ()
            return tuple(item.strip().strip("`") for item in re.split(r"[,，]", raw) if item.strip())
    return ()


def parse_records(comments):
    """按服务器时间排好的认领记录；一条读不全就整票拒绝。"""
    found = []
    for index, comment in enumerate(comments):
        record = parse_comment(comment)
        if record is not None:
            found.append((record.created, index, record))
    found.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in found]


def open_claims(records):
    """未收尾的认领：每个 session 只看它最后一条记录，最后一条仍是认领的才算。"""
    last = {}
    for record in records:
        last[record.session] = record
    return [record for record in records if last[record.session] is record and record.open]


def arbiter(records):
    """最早的那条未收尾认领赢；票上没有未收尾认领时返回 None。

    records 已按服务器时间升序，所以第一个命中就是最早的一条；同秒时取先写的那条。
    """
    pending = open_claims(records)
    return pending[0] if pending else None


def header(kind, who, now):
    return f"**{kind}**：session `{who.session}` · branch `{who.branch}` · {now.strftime(STAMP)}"


def claim_body(who, now, labels):
    kept = ", ".join(f"`{name}`" for name in labels) if labels else EMPTY_LABELS
    return "\n".join([header(CLAIMED, who, now), LABEL_KEY + kept])


def closing_body(kind, who, now, restored=()):
    lines = [header(kind, who, now)]
    if restored:
        lines.append(RESTORE_KEY + ", ".join(f"`{name}`" for name in restored))
    return "\n".join(lines)


def instant(created):
    """服务器时间戳 -> 带时区的 datetime；读不出来返回 None——不猜。"""
    try:
        value = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def local_stamp(created):
    """服务器时间戳 -> 本地墙钟，与评论正文里那串 `YYYY-MM-DD HH:MM` 同形。"""
    value = instant(created)
    return value.astimezone().strftime(STAMP) if value else None


def age_days(created, now):
    """认领距今天数；时间戳读不出来时返回 None——不猜。"""
    started = instant(created)
    if started is None:
        return None
    if now.tzinfo is None:
        now = now.astimezone()
    return max((now - started).days, 0)


def open_pr(branch, runner):
    """持有者分支上有没有开着的 PR；`gh` 失败时返回 None（只是旁证，不影响结局）。"""
    text, rc = call(runner, "pr", "list", "--head", branch, "--state", "open", "--json", "number")
    if rc != 0:
        return None
    try:
        return bool(json.loads(text))
    except ValueError:
        return None


def taken_message(number, owner, runner, now):
    days = age_days(owner.created, now)
    since = f"{days} 天前" if days is not None else "时间未知"
    stamp = local_stamp(owner.created) or owner.stamp
    pr = open_pr(owner.branch, runner)
    if pr is None:
        pr_line = "该分支的 PR 状态未知"
    else:
        pr_line = "该分支有开着的 PR" if pr else "该分支没有开着的 PR"
    return "\n".join([
        f"#{number} 已被 session `{owner.session}` 认领（{stamp}，{since}）",
        f"  branch `{owner.branch}`",
        f"  {pr_line}",
        f"  认领记录：{owner.url or '无链接'}",
        "  停下上报，不要另开 worktree 重做这张票。",
    ])


def post_comment(number, body, runner):
    """写一条评论 -> (评论 URL, None)；失败 -> (None, 原因)。"""
    text, rc = call(runner, "issue", "comment", str(number), "--body", body)
    if rc != 0:
        return None, f"写认领评论失败：{text}"
    return text, None


def set_labels(number, runner, add, remove):
    """加 / 摘标签，返回给人看的一小段；失败只记原因（advisory），认领记录以评论为准。"""
    add, remove = list(dict.fromkeys(add)), list(dict.fromkeys(remove))
    if not add and not remove:
        return ""
    args = ["issue", "edit", str(number)]
    for name in add:
        args += ["--add-label", name]
    for name in remove:
        args += ["--remove-label", name]
    text, rc = call(runner, *args)
    if rc != 0:
        return f"；标签没写成功（{text or 'gh 返回非零'}），认领记录以评论为准"
    return ""


def mark_claimed(number, issue, runner):
    """认领或 reaffirm 时把待办池标签换成 `in-progress`，顺带摘掉停摆标记。

    `stale` 表示「球在报告者那边」，认领之后就不成立了；`--abandon` 不把它加回来——
    票回到待办池，是否再次停摆由下一次扫描重新判。
    """
    remove = role_labels(issue)
    if STALE_LABEL in label_names(issue):
        remove.append(STALE_LABEL)
    return set_labels(number, runner, [IN_PROGRESS], remove)


def comment_id(url):
    found = COMMENT_URL.search(url or "")
    return found.group(1) if found else None


def repo_name(issue):
    found = ISSUE_URL.search(issue.get("url") or "")
    return found.group(1) if found else None


def withdraw(url, issue, runner):
    """撤回本会话刚写的认领评论（并发认领只留最早那条）；删不掉时把链接交给人。"""
    ident, repo = comment_id(url), repo_name(issue)
    if not ident or not repo:
        return f"；请手工删除刚写的认领评论 {url or '（无链接）'}"
    text, rc = call(runner, "api", "--method", "DELETE", f"repos/{repo}/issues/comments/{ident}")
    if rc != 0:
        return f"；撤回失败（{text or 'gh 返回非零'}），请手工删除 {url}"
    return ""


def finish(number, action, owner, mine, who, now, runner, restore):
    """收尾（--release）与放弃（--abandon）：都要求本会话持有，放弃还要恢复原标签。"""
    if not mine:
        return EXIT_REFUSED, f"#{number} 上没有本会话（{who.session}）的未收尾认领，不用收尾"
    if action == "release":
        body = closing_body(RELEASED, who, now)
        _, problem = post_comment(number, body, runner)
        if problem:
            return EXIT_GH, problem
        note = set_labels(number, runner, [], [IN_PROGRESS])
        return EXIT_OK, f"#{number} 的认领已收尾（{who.session}）" + note
    back = list(restore) if restore else list(owner.labels)
    body = closing_body(ABANDONED, who, now, back)
    _, problem = post_comment(number, body, runner)
    if problem:
        return EXIT_GH, problem
    note = set_labels(number, runner, back, [IN_PROGRESS])
    restored = f"，已恢复 {', '.join(back)}" if back else ""
    return EXIT_OK, f"#{number} 的认领已放弃（{who.session}）{restored}" + note


def command(number, action="claim", restore=(), runner=None, cwd=None, host=None, now=None):
    """整条命令的判定：返回 (退出码, 给人看的消息)。"""
    runner = runner or runner_for(cwd)
    now = now or datetime.now()
    try:
        who = session_context(cwd=cwd, host=host)
    except RuntimeError as error:
        return EXIT_REFUSED, f"读不到当前 worktree 与分支：{error}"
    try:
        issue = read_issue(number, runner)
    except GhError as error:
        return EXIT_GH, str(error)
    if action == "claim" and issue.get("state") != "OPEN":
        return EXIT_REFUSED, f"#{number} 已经是 {issue.get('state')}，不再认领"
    try:
        records = parse_records(issue.get("comments") or [])
    except Unreadable as error:
        return EXIT_REFUSED, (
            f"#{number} 的认领记录读不出确定结局：{error}。"
            f"先手工核对那条评论；票被卡住时可以 gh issue edit {number} --remove-label {IN_PROGRESS}"
        )
    owner = arbiter(records)
    mine = owner is not None and owner.session == who.session

    if action in ("release", "abandon"):
        return finish(number, action, owner, mine, who, now, runner, restore)
    if owner is not None and not mine:
        return EXIT_TAKEN, taken_message(number, owner, runner, now)
    if mine:
        return EXIT_OK, f"#{number} 已由本会话持有（{who.session}），不重复认领" \
            + mark_claimed(number, issue, runner)

    url, problem = post_comment(number, claim_body(who, now, role_labels(issue)), runner)
    if problem:
        return EXIT_GH, problem
    # 两路都读到空票时都会写出评论：重读一次，最早的那条赢，后写的撤回自己那条。
    # 同一 session 并发写了两条时赢家也是自己，只需把晚的那条撤掉，认领仍成立。
    try:
        again = read_issue(number, runner)
        fresh = parse_records(again.get("comments") or [])
        winner = arbiter(fresh)
    except (GhError, Unreadable) as error:
        return EXIT_GH, f"认领评论已写（{url}），但重读校验没做成：{error}；请人工核对持有者"
    if winner is not None and winner.session == who.session:
        ours = [record for record in fresh if record.open and record.session == who.session]
        if ours and ours[0].url != url:
            withdraw(url, again, runner)
        return EXIT_OK, f"#{number} 已认领（{who.session}）" + mark_claimed(number, issue, runner)
    note = withdraw(url, again, runner)
    holder = taken_message(number, winner, runner, now) if winner else f"#{number} 上没有可判定的认领记录"
    return EXIT_TAKEN, f"并发认领：{holder}\n已撤回本会话刚写的认领评论{note}"


def parse_args(argv):
    """命令行 -> (票号, 动作, 恢复标签)；不合规抛 ValueError（文案即用法）。"""
    number, action, restore, seen = None, "claim", [], None
    pending = list(argv)
    while pending:
        item = pending.pop(0)
        if item in ACTIONS:
            if seen:
                raise ValueError(f"只能给一个动作，收到 {seen} 与 {item}\n{USAGE}")
            seen, action = item, ACTIONS[item]
        elif item == "--restore":
            if not pending:
                raise ValueError(f"--restore 后面要跟标签名\n{USAGE}")
            restore.append(pending.pop(0))
        elif item.startswith("-"):
            raise ValueError(f"不认识的选项 {item}\n{USAGE}")
        elif number is not None:
            raise ValueError(f"一次只认领一张票，收到 {number} 与 {item}\n{USAGE}")
        elif not item.isdigit():
            raise ValueError(f"票号要是数字，收到 {item}\n{USAGE}")
        else:
            number = int(item)
    if number is None:
        raise ValueError(USAGE)
    if restore and action != "abandon":
        raise ValueError(f"--restore 只和 --abandon 一起用\n{USAGE}")
    return number, action, restore


def main(argv, runner=None, cwd=None, host=None, now=None):
    try:
        number, action, restore = parse_args(argv)
    except ValueError as error:
        print(error, file=sys.stderr)
        return EXIT_REFUSED
    code, message = command(number, action=action, restore=restore, runner=runner,
                            cwd=cwd, host=host, now=now)
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
