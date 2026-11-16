"""把 `unittest -v` 的输出解析成一张 job summary 表格（#875），只给 CI 用。

用法（输出 markdown 到 stdout，由 workflow 追加进 `$GITHUB_STEP_SUMMARY`）：

    python3 devtools/unittest_summary.py unittest.log "Linux / 3.13" abc1234

日志尾部认不出 `Ran N tests` 与 `OK` / `FAILED` 时不抛异常，只输出一句说明：summary 写不出来
不该让测试 job 变红。日志按 utf-8 读、坏字节替换，Windows 上 cp1252 混进来的字节不会炸。

另附一节「测试规模」（#1394），三项都由 AST 现算、不读 git 历史或存档：用例数是 `tests/**/*.py`
里 AST 的 `def test_*` / `async def test_*` 定义个数，文件数是这些 `.py` 文件的个数，行数是这些
文件行数之和。`tests/` 读不到或解析失败同样只输出一句说明，不让 job 变红。

再附一节「锚点体量」（#1397）：按文件数出每个锚点的断言数，**超过上限的才各列一行**（含当前值与
上限），其余只报一句「量到的 N 个都没有超过」。这是软预算，超限不红、不阻断合并；上限与口径在
docs/agents/test-anchors.md 的「体量预算」。
"""
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tool"))   # stdio 留在引擎目录
sys.path.insert(0, str(REPO))            # devtools 包：锚点登记与它的上限

from stdio import use_utf8_console
from devtools import test_anchors

RAN = re.compile(r"^Ran (\d+) tests? in ([\d.]+)s", re.MULTILINE)
VERDICT = re.compile(r"^(OK|FAILED)\b(.*)$", re.MULTILINE)
ASSERTION = re.compile(r"^(assert[A-Za-z_]*|fail)$")


def parse(text):
    """(总数, 耗时, 失败, 错误, 跳过)；两组汇总行缺任一组时返回 None。"""
    ran = RAN.search(text)
    verdict = VERDICT.search(text)
    if not ran or not verdict:
        return None
    tail = verdict.group(2)

    def count(key):
        found = re.search(rf"{key}=(\d+)", tail)
        return int(found.group(1)) if found else 0

    return int(ran.group(1)), ran.group(2), count("failures"), count("errors"), count("skipped")


def suite_size(root=None):
    """(用例数, 文件数, 行数)；`tests/` 读不到或解析失败时返回 None。

    `root` 缺省取仓库根（本文件在 `devtools/` 下），不依赖 cwd；单测注入临时目录构造。"""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    tests = base / "tests"
    if not tests.is_dir():
        return None
    cases = files = lines = 0
    try:
        for path in sorted(tests.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            files += 1
            lines += len(text.splitlines())
            for node in ast.walk(ast.parse(text, filename=str(path))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    cases += 1
    except (OSError, SyntaxError, ValueError):
        return None
    return cases, files, lines


def size_section(root=None):
    size = suite_size(root)
    if size is None:
        return ("### 测试规模\n\n"
                "统计不出 `tests/` 下的用例数、文件数与行数（读不到 `tests/` 或文件解析失败）。\n")
    cases, files, lines = size
    return "\n".join([
        "### 测试规模",
        "",
        "| 用例数 | 文件数 | 行数 |",
        "|---:|---:|---:|",
        f"| {cases} | {files} | {lines} |",
    ]) + "\n"


def assertions_in(path):
    """一个文件的断言数：`assert` 语句 + 以 `assert` 开头的方法调用（含 Mock 的
    `assert_called_once` 这类）+ `self.fail(...)` 本身。不数 `failUnless` 一类旧别名，
    也不数 `chan.failed(...)` / `failure_message(...)` 这类同前缀的非断言调用。

    这是体量预算的计量单位：函数个数会被「把几条用例并进一个函数」压下去，断言数不会。"""
    tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) or (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and ASSERTION.match(node.func.attr)):
            count += 1
    return count


def budget_rows(root=None, anchors=None):
    """([(锚点, 断言数, 上限)], 量到的锚点数)：超限的按超出多少降序。

    `tests/` 读不到或文件解析失败时返回 None；超限只是可见，不算违规。
    `anchors` 缺省取锚点登记，单测注入临时表。"""
    anchors = test_anchors.ANCHORS if anchors is None else anchors
    tests = (REPO if root is None else Path(root)) / "tests"
    if not tests.is_dir():
        return None
    rows, measured_count = [], 0
    try:
        for name in sorted(anchors):
            cap = anchors[name][1]
            path = tests / name
            if cap is None or not path.is_file():
                continue
            measured = assertions_in(path)
            measured_count += 1
            if measured > cap:
                rows.append((name, measured, cap))
    except (OSError, SyntaxError, TypeError, ValueError, IndexError):
        return None
    rows.sort(key=lambda row: row[1] - row[2], reverse=True)
    return rows, measured_count


BUDGET_HEAD = "### 锚点体量（断言数）"


def budget_section(root=None, anchors=None):
    anchors = test_anchors.ANCHORS if anchors is None else anchors
    counted = budget_rows(root, anchors)
    if counted is None or not counted[1]:
        return (f"{BUDGET_HEAD}\n\n"
                "统计不出锚点文件的断言数（读不到 `tests/`、一个锚点文件都没找到，或文件解析失败）。\n")
    rows, measured_count = counted
    if not rows:
        return f"{BUDGET_HEAD}\n\n量到的 {measured_count} 个锚点都没有超过各自的断言数上限。\n"
    lines = [BUDGET_HEAD, "", "| 锚点 | 断言数 | 上限 |", "|---|---:|---:|"]
    lines += [f"| `{name}` | {measured} | {cap} |" for name, measured, cap in rows]
    lines += ["", "超限只在这里列出，不阻断合并；上限只许降，口径见 "
                  "docs/agents/test-anchors.md 的「体量预算」。"]
    return "\n".join(lines) + "\n"


def render(label, text, sha="", root=None):
    parsed = parse(text)
    size = size_section(root)
    budget = budget_section(root)
    tail = size + "\n" + budget
    if parsed is None:
        return f"### 测试结果（{label}）\n\n日志里没找到 `Ran N tests` 与 `OK` / `FAILED` 汇总行。\n\n{tail}"
    total, seconds, failures, errors, skipped = parsed
    passed = total - failures - errors - skipped
    mark = "✅ Pass" if not failures and not errors else "❌ Fail"
    lines = [
        f"### 测试结果（{label}）",
        "",
        "| 结果 | 通过 | 失败 | 错误 | 跳过 | 耗时 |",
        "|---|---:|---:|---:|---:|---:|",
        f"| {mark} | {passed} | {failures} | {errors} | {skipped} | {seconds}s |",
    ]
    if sha:
        lines += ["", f"提交 `{sha}`"]
    return "\n".join(lines) + "\n\n" + tail


def main(argv):
    use_utf8_console()
    if len(argv) < 2:
        print("用法：python3 devtools/unittest_summary.py <日志> [标签] [提交短哈希]", file=sys.stderr)
        return 2
    label = argv[2] if len(argv) > 2 else "unittest"
    sha = argv[3] if len(argv) > 3 else ""
    log = Path(argv[1])
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    sys.stdout.write(render(label, text, sha))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
