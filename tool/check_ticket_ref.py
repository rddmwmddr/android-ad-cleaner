"""票与改动之间要有可机器核对的连接：分支名与 PR 正文指到同一张票（#1001）。

用法（本地与 CI 是同一条命令）：

    python3 tool/check_ticket_ref.py <分支名> <PR 文本文件>

分支名要匹配「`-<票号>` 结尾」（约定见 `docs/agents/issue-tracker.md`），PR 文本里要有
`Refs #N` 或 `Closes #N`，且 N 与分支名里的数字一致。文本文件是 PR 标题与正文拼起来的那份：
标题里写 `Refs #N` 同样算数，核对的是「这次改动为哪张票做的」，不是哪一行写在哪。

退出码：0 合规，1 有违规（逐条说明哪一处对不上），2 参数或读文件出错。
"""
import re
import sys

from stdio import use_utf8_console

use_utf8_console()

BRANCH_TICKET = re.compile(r"-(\d+)$")
REFERENCE = re.compile(r"\b(?:Refs|Closes)\s+#(\d+)", re.IGNORECASE)


def branch_ticket(branch):
    """分支名结尾的票号；没有返回 None。"""
    match = BRANCH_TICKET.search(branch.strip())
    return match.group(1) if match else None


def referenced_tickets(text):
    """`Refs #N` / `Closes #N` 指到的票号集合。"""
    return {match.group(1) for match in REFERENCE.finditer(text)}


def problems(branch, text):
    """三种结局各有各的说法：分支名没票号、正文没引用、两边不是同一张。"""
    ticket = branch_ticket(branch)
    if ticket is None:
        return [f"分支名 {branch!r} 没有以 `-<票号>` 结尾，票与改动串不起来"]
    referenced = referenced_tickets(text)
    if not referenced:
        return ["PR 正文没有 `Refs #N` 或 `Closes #N`，看不出这次改动为哪张票做的"]
    if ticket not in referenced:
        listed = "、".join(f"#{item}" for item in sorted(referenced, key=int))
        return [f"分支名指的票是 #{ticket}，PR 正文引用的却是 {listed}，两处对不上"]
    return []


def main(argv):
    if len(argv) != 2:
        print("用法：python3 tool/check_ticket_ref.py <分支名> <PR 文本文件>", file=sys.stderr)
        return 2
    branch, path = argv
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as error:
        print(f"读不出 {path}：{error}", file=sys.stderr)
        return 2
    found = problems(branch, text)
    if not found:
        print(f"分支名与 PR 正文都指到 #{branch_ticket(branch)}")
        return 0
    print(f"分支名与 PR 正文对不上（{len(found)} 处）：")
    for line in found:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
