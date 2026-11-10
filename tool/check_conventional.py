"""Conventional Commits 校验：`base..head` 里每个非 merge 提交的主题都要带合规前缀（#849）。

用法（本地与 CI 是同一条命令）：

    python3 tool/check_conventional.py origin/main..HEAD

规则只约束主题行：`type(scope): subject`，`type` 取自下面的 TYPES，`scope` 只允许 `[a-z0-9_-]`，
破坏性改动在冒号前加 `!`。这条规则此前只在本机 commit-msg 钩子里执行，换个提交环境就失效。

只判参数给的那段范围，不判历史：PR 的范围由 workflow 传 `pull_request.base.sha..pull_request.head.sha`，
所以 main 上 `初版：引擎` 这类老提交不会被翻出来。

退出码：0 全部合规，1 有违规（日志逐条点名 sha 与主题），2 参数或 git 出错。
"""
import re
import sys
from dataclasses import dataclass

from commits import Commit, read_commits
from stdio import use_utf8_console

use_utf8_console()

TYPES = ("feat", "fix", "docs", "refactor", "test", "chore", "ci", "perf", "build", "style", "revert")
SCOPE = re.compile(r"[a-z0-9_-]+")
SUBJECT = re.compile(r"^(?P<type>[A-Za-z0-9_-]+)(?:\((?P<scope>[^)]*)\))?!?: ")


@dataclass(frozen=True)
class Violation:
    commit: Commit
    reason: str


def reason_for(subject):
    """合规返回 None；不合规返回一句为什么，三种结局各有各的说法。"""
    match = SUBJECT.match(subject)
    if not match:
        return "主题没有 `type(scope): ` 前缀"
    kind = match.group("type")
    if kind not in TYPES:
        return f"type {kind} 不在清单里（{' / '.join(TYPES)}）"
    scope = match.group("scope")
    if scope is not None and not SCOPE.fullmatch(scope):
        return f"scope {scope} 不合规，只允许小写字母、数字、下划线、连字符"
    return None


def violations(commits):
    found = []
    for item in commits:
        if item.merge:
            continue
        reason = reason_for(item.subject)
        if reason:
            found.append(Violation(item, reason))
    return found


def main(argv):
    if len(argv) != 1:
        print("用法：python3 tool/check_conventional.py <base>..<head>", file=sys.stderr)
        return 2
    try:
        found = violations(read_commits(argv[0]))
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    if not found:
        print(f"{argv[0]} 的提交主题都符合 Conventional Commits")
        return 0
    print(f"{argv[0]} 有 {len(found)} 个提交主题不合规：")
    for item in found:
        print(f"  {item.commit.sha} {item.commit.subject} —— {item.reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
