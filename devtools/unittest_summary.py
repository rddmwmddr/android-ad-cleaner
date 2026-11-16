"""把 `unittest -v` 的输出解析成一张 job summary 表格（#875），只给 CI 用。

用法（输出 markdown 到 stdout，由 workflow 追加进 `$GITHUB_STEP_SUMMARY`）：

    python3 devtools/unittest_summary.py unittest.log "Linux / 3.13" abc1234

日志尾部认不出 `Ran N tests` 与 `OK` / `FAILED` 时不抛异常，只输出一句说明：summary 写不出来
不该让测试 job 变红。日志按 utf-8 读、坏字节替换，Windows 上 cp1252 混进来的字节不会炸。

另附一节「测试规模」（#1394），三项都由 AST 现算、不读 git 历史或存档：用例数是 `tests/**/*.py`
里 AST 的 `def test_*` / `async def test_*` 定义个数，文件数是这些 `.py` 文件的个数，行数是这些
文件行数之和。`tests/` 读不到或解析失败同样只输出一句说明，不让 job 变红。
"""
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))   # stdio 留在引擎目录

from stdio import use_utf8_console

RAN = re.compile(r"^Ran (\d+) tests? in ([\d.]+)s", re.MULTILINE)
VERDICT = re.compile(r"^(OK|FAILED)\b(.*)$", re.MULTILINE)


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


def render(label, text, sha="", root=None):
    parsed = parse(text)
    size = size_section(root)
    if parsed is None:
        return f"### 测试结果（{label}）\n\n日志里没找到 `Ran N tests` 与 `OK` / `FAILED` 汇总行。\n\n{size}"
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
    return "\n".join(lines) + "\n\n" + size


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
