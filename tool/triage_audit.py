"""open 票标签集的四条集合判据（#1019）：分类恰好一个、`waiting-for-verify` 压过角色、
`in-progress` 不与 `waiting-for-verify` 并存、标签集 ⊆ 文档登记集。

用法：

    python3 tool/triage_audit.py                       # 拉全量 open 票
    python3 tool/triage_audit.py --input issues.json   # 用一份 `gh issue list --json` 的落盘

判据正文在 docs/agents/triage-labels.md，本文件只是它的机械镜像：`KNOWN` 与文档的
`## 标签登记` 表由 tests/test_triage_audit.py 逐项对拍。只读——不写标签、不评论、不关票。

退出码：0 全绿；1 有违规（逐行 `#<num>  <判据 id>  <标签集>`）；2 取数失败或参数不合规。
2 不当作违规：网络抖动不该把作业标红，那会让红信号贬值。

已知漏口：`--limit` 之上会被截断（当前 245 张，红线 1000）；只看 cron 那一刻的状态，
中途改坏又改回不留痕迹；第四条只查「标签集 ⊆ 登记集」，查不出这张票该不该带这个标签。
"""
import json
import subprocess
import sys
from pathlib import Path

from stdio import use_utf8_console

use_utf8_console()

LIMIT = 1000
FIELDS = "number,labels"

CATEGORIES = ("bug", "enhancement")
OUTRANKED = ("needs-info", "ready-for-agent", "ready-for-human")
VERIFY = "waiting-for-verify"
CLAIM = "in-progress"

# 与 docs/agents/triage-labels.md 的 `## 标签登记` 表逐项相同，tests/test_triage_audit.py 守着。
KNOWN = frozenset({
    "needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix",
    VERIFY, CLAIM, "stale", "bug", "enhancement", "新机型",
    "documentation", "accessibility", "duplicate", "good first issue", "help wanted",
    "invalid", "question",
})

ONE_CATEGORY = "doc.triage.one-category-label"
VERIFY_OUTRANKS = "doc.triage.waiting-for-verify-outranks"
CLAIM_CLASH = "doc.triage.in-progress-is-a-claim"
MAPPED = "doc.triage.five-roles-map"

EXIT_OK, EXIT_FINDINGS, EXIT_UNREACHABLE = 0, 1, 2

USAGE = """用法：python3 tool/triage_audit.py [--input <path>]

  --input <path>  读一份 `gh issue list --state open --json number,labels` 的落盘，不联网"""


class Unreachable(RuntimeError):
    """取不到票（gh 失败、输出不是 JSON、注入文件读不了）：给不出结论。"""


class Usage(RuntimeError):
    """参数不合规。"""


def label_names(issue):
    """一张票的标签名，去掉空串；顺序按 gh 给的来。"""
    return [name for name in (label.get("name") for label in issue.get("labels") or []) if name]


def hits(names):
    """一张票的标签集违反了哪几条判据；返回 [(判据 id, 一句现场)]。"""
    found, present = [], set(names)
    categories = [name for name in CATEGORIES if name in present]
    if len(categories) != 1:
        found.append((ONE_CATEGORY,
                      "分类要恰好一个：" + ("、".join(categories) if categories else "一个都没有")))
    roles = [name for name in OUTRANKED if name in present]
    if VERIFY in present and roles:
        found.append((VERIFY_OUTRANKS, f"{VERIFY} 压过角色标签，不能再带 " + "、".join(roles)))
    if VERIFY in present and CLAIM in present:
        found.append((CLAIM_CLASH, f"{CLAIM} 是认领，不能与 {VERIFY} 并存"))
    unknown = sorted(present - KNOWN)
    if unknown:
        found.append((MAPPED, "标签没在 triage-labels.md 登记：" + "、".join(unknown)))
    return found


def audit(issues):
    """逐条违规文案，按票号升序；同一张票按判据顺序。"""
    lines = []
    for issue in sorted(issues, key=lambda item: int(item["number"])):
        names = sorted(label_names(issue))
        for rule, _ in hits(names):
            lines.append(f"#{issue['number']}  {rule}  {','.join(names) or '(无标签)'}")
    return lines


def parse_args(argv):
    """`--input <path>` / `--input=<path>`；其余一律报错。返回路径，没给时返回 None。"""
    path, rest = None, list(argv)
    while rest:
        item = rest.pop(0)
        if item == "--input":
            if not rest:
                raise Usage("--input 后面要给路径")
            path = rest.pop(0)
        elif item.startswith("--input="):
            path = item.split("=", 1)[1]
        else:
            raise Usage(f"不认识的参数 {item}")
        if path is not None and not path:
            raise Usage("--input 后面要给路径")
    return path


def gh_json(args):
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as error:
        raise Unreachable(f"跑不起 gh：{error}") from error
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        raise Unreachable(detail or f"gh 退出码 {done.returncode}")
    try:
        return json.loads(done.stdout)
    except ValueError as error:
        raise Unreachable(f"gh 输出不是 JSON：{error}") from error


def fetch_issues():
    """全量 open 票的 number 与 labels；取不到时抛 Unreachable。"""
    return gh_json(["issue", "list", "--state", "open",
                    "--limit", str(LIMIT), "--json", FIELDS])


def read_dump(path):
    """读一份 `gh issue list --json number,labels` 的落盘；形状不符时也抛 Unreachable。"""
    try:
        issues = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Unreachable(f"读不了 {path}：{error}") from error
    if not isinstance(issues, list):
        raise Unreachable(f"{path} 的顶层不是数组，不是 `gh issue list --json` 的输出")
    for issue in issues:
        if not isinstance(issue, dict) or "number" not in issue:
            raise Unreachable(f"{path} 里有条目缺 number，不是 `gh issue list --json` 的输出")
        labels = issue.get("labels")
        if labels is not None and (not isinstance(labels, list)
                                   or any(not isinstance(label, dict) for label in labels)):
            raise Unreachable(f"{path} 里的 labels 不是对象数组，像是被 --jq 压平过")
    return issues


def main(argv, fetch=fetch_issues):
    try:
        path = parse_args(argv)
    except Usage as error:
        print(f"{error}\n\n{USAGE}", file=sys.stderr)
        return EXIT_UNREACHABLE
    try:
        issues = read_dump(path) if path else fetch()
    except Unreachable as error:
        print(f"取不到 open 票的标签集，这条审计给不出结论：{error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    lines = audit(issues)
    if not lines:
        print(f"{len(issues)} 张 open 票，四条标签判据全绿。")
        return EXIT_OK
    print("\n".join(lines))
    tickets = len({line.split()[0] for line in lines})
    print(f"{len(lines)} 条违规，涉及 {tickets} 张票。", file=sys.stderr)
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
