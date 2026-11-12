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
import sys
from pathlib import Path

from gh import GhError, json_of, runner_for

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
    VERIFY, CLAIM, "stale", "blocked-on-device", "bug", "enhancement", "新机型",
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


def checked(issues, source):
    """一份 `gh issue list --json number,labels` 的形状校验；不符时抛 GhError。

    联网与 `--input` 两条输入来源都走这一份：形状不合就是给不出结论，不分工。
    """
    if not isinstance(issues, list):
        raise GhError(f"{source} 的顶层不是数组，不是 `gh issue list --json` 的输出")
    for issue in issues:
        if not isinstance(issue, dict) or "number" not in issue:
            raise GhError(f"{source} 里有条目缺 number，不是 `gh issue list --json` 的输出")
        labels = issue.get("labels")
        if labels is not None and (not isinstance(labels, list)
                                   or any(not isinstance(label, dict) for label in labels)):
            raise GhError(f"{source} 里的 labels 不是对象数组，像是被 --jq 压平过")
    return issues


def fetch_issues(runner):
    """全量 open 票的 number 与 labels；取不到时抛 GhError。"""
    issues = json_of(runner, "issue", "list", "--state", "open",
                     "--limit", str(LIMIT), "--json", FIELDS, source="`gh issue list`")
    return checked(issues, "`gh issue list`")


def read_dump(path):
    """读一份 `gh issue list --json number,labels` 的落盘；读不了或形状不符都抛 GhError。"""
    try:
        issues = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GhError(f"读不了 {path}：{error}") from error
    return checked(issues, str(path))


def main(argv, runner=None):
    try:
        path = parse_args(argv)
    except Usage as error:
        print(f"{error}\n\n{USAGE}", file=sys.stderr)
        return EXIT_UNREACHABLE
    try:
        issues = read_dump(path) if path else fetch_issues(runner or runner_for())
    except GhError as error:
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
