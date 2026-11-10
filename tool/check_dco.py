"""DCO 校验：`base..head` 里每个非 merge 提交都要带与作者邮箱一致的 `Signed-off-by`（#848）。

用法（本地与 CI 是同一条命令）：

    python3 tool/check_dco.py origin/main..HEAD

只判参数给的那段范围，不判历史：PR 的范围由 workflow 传 `pull_request.base.sha..pull_request.head.sha`。
merge 提交整条跳过——GitHub 网页 / API 合并产生的合并提交不带 signoff，那是已知例外，不是违规。

退出码：0 全部合规，1 有违规（日志逐条点名 sha 与主题），2 参数或 git 出错。
"""
import re
import sys
from dataclasses import dataclass

from commits import Commit, read_commits
from stdio import use_utf8_console

use_utf8_console()

SIGNOFF = re.compile(r"^[ \t]*Signed-off-by:[ \t]*.*?<([^<>]*)>[ \t]*$", re.IGNORECASE | re.MULTILINE)
MISSING = "missing"
MISMATCH = "mismatch"


@dataclass(frozen=True)
class Violation:
    commit: Commit
    kind: str
    reason: str


def signoff_emails(body):
    return [match.group(1).strip().lower() for match in SIGNOFF.finditer(body)]


def violations(commits):
    """每条的结局只有三种：合规、缺 signoff、signoff 的邮箱与作者不符。"""
    found = []
    for item in commits:
        if item.merge:
            continue
        signed = signoff_emails(item.body)
        if not signed:
            found.append(Violation(item, MISSING, "缺 Signed-off-by"))
        elif item.author_email.strip().lower() not in signed:
            found.append(Violation(
                item, MISMATCH,
                f"Signed-off-by 邮箱与作者不符（作者 {item.author_email}，签署 {', '.join(signed)}）"))
    return found


def main(argv):
    if len(argv) != 1:
        print("用法：python3 tool/check_dco.py <base>..<head>", file=sys.stderr)
        return 2
    try:
        found = violations(read_commits(argv[0]))
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    if not found:
        print(f"{argv[0]} 的提交都带与作者邮箱一致的 Signed-off-by")
        return 0
    print(f"{argv[0]} 有 {len(found)} 个提交不合规：")
    for item in found:
        print(f"  {item.commit.sha} {item.commit.subject} —— {item.reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
