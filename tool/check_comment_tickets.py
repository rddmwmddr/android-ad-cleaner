"""新写的注释、docstring 与文档行里挂的票号要与这次 PR 有关（#1001）。

用法（本地与 CI 是同一条命令）：

    python3 tool/check_comment_tickets.py <base>..<head> <PR 文本文件>

取 `git diff` 的新增行，抽出其中的 `#<数字>`；每个都要出现在 PR 标题或正文引用的票号里。
只为 `base..head` 判，main 上的历史不因这条检查翻旧账。

两种豁免：该行含「沿用」（规则本身允许「沿用 #xxx 的做法」这种明确引用），
以及新增行落在 `docs/adr/`（ADR 记的就是当时引用了哪张票）。

退出码：0 合规，1 有违规（逐条点名文件、行号与票号），2 参数或 git 出错。
"""
import re
import sys

from commits import git, use_utf8_console

use_utf8_console()

# `#` 前面是字母或数字的是 URL 片段与实体，`&#123;` 同理：都不是票号。
TICKET = re.compile(r"(?<![\w#&])#(\d+)\b")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
EXEMPT_DIR = "docs/adr/"
EXEMPT_WORD = "沿用"


def added_lines(rev_range, run=git):
    """`[(路径, 行号, 文本)]`：diff 的新增行，行号取新文件里的那一列。"""
    path, lineno = None, 0
    for line in run("diff", "--unified=0", "--no-color", rev_range).splitlines():
        if line.startswith("diff --git "):
            path, lineno = None, 0
        elif line.startswith("+++ "):
            name = line[4:].strip()
            path = None if name == "/dev/null" else (name[2:] if name.startswith("b/") else name)
        elif line.startswith("@@ "):
            match = HUNK.match(line)
            lineno = int(match.group(1)) if match else 0
        elif path and line.startswith("+"):
            yield path, lineno, line[1:]
            lineno += 1


def tickets_in(text):
    """文本里出现的票号集合。"""
    return {match.group(1) for match in TICKET.finditer(text)}


def problems(rev_range, pr_text, run=git):
    """新增行里每个票号都要在 PR 引用的集合里；返回逐条说明，空表示合规。"""
    allowed = tickets_in(pr_text)
    described = "、".join(f"#{item}" for item in sorted(allowed, key=int)) or "无"
    found = []
    for path, lineno, line in added_lines(rev_range, run):
        if path.startswith(EXEMPT_DIR) or EXEMPT_WORD in line:
            continue
        for match in TICKET.finditer(line):
            ticket = match.group(1)
            if ticket not in allowed:
                found.append(f"{path}:{lineno}: #{ticket} 不在 PR 引用的票号里（引用的是 {described}）")
    return found


def main(argv):
    if len(argv) != 2:
        print("用法：python3 tool/check_comment_tickets.py <base>..<head> <PR 文本文件>", file=sys.stderr)
        return 2
    rev_range, path = argv
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        found = problems(rev_range, text)
    except OSError as error:
        print(f"读不出 {path}：{error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 2
    if not found:
        print(f"{rev_range} 的新增行里的票号都在 PR 引用的范围内")
        return 0
    print(f"{rev_range} 有 {len(found)} 处票号对不上：")
    for line in found:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
