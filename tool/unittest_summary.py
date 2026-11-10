"""把 `unittest -v` 的输出解析成一张 job summary 表格（#875），只给 CI 用。

用法（输出 markdown 到 stdout，由 workflow 追加进 `$GITHUB_STEP_SUMMARY`）：

    python3 tool/unittest_summary.py unittest.log "Linux / 3.13" abc1234

日志尾部认不出 `Ran N tests` 与 `OK` / `FAILED` 时不抛异常，只输出一句说明：summary 写不出来
不该让测试 job 变红。日志按 utf-8 读、坏字节替换，Windows 上 cp1252 混进来的字节不会炸。
"""
import re
import sys
from pathlib import Path

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


def render(label, text, sha=""):
    parsed = parse(text)
    if parsed is None:
        return f"### 测试结果（{label}）\n\n日志里没找到 `Ran N tests` 与 `OK` / `FAILED` 汇总行。\n"
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
    return "\n".join(lines) + "\n"


def main(argv):
    use_utf8_console()
    if len(argv) < 2:
        print("用法：python3 tool/unittest_summary.py <日志> [标签] [提交短哈希]", file=sys.stderr)
        return 2
    label = argv[2] if len(argv) > 2 else "unittest"
    sha = argv[3] if len(argv) > 3 else ""
    log = Path(argv[1])
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    sys.stdout.write(render(label, text, sha))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
