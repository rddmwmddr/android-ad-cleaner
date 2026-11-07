"""前端行为用例放在 tests/js/（桌面版 gui/web 与官网下载页），这里只做代跑与守卫。

回归入口是一条 python -m unittest discover -s tests：前端用例由这条命令带跑，
不另开第二条命令（ADR-0017）。
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "tests" / "js"
TIMEOUT = 300


def tally(output, key):
    found = re.search(rf"^# {key} (\d+)$", output, re.MULTILINE)
    return int(found.group(1)) if found else 0


def judge(output, returncode):
    """跑完 node 之后判绿：没用例、有失败、返回码非零都不算过。通过时返回 None。"""
    total = tally(output, "tests")
    passed = tally(output, "pass")
    failed = tally(output, "fail")
    # node --test 在一个用例文件都没有时返回 0，空集合不能算过
    if not total:
        return "一个用例都没跑到"
    if failed or passed != total or returncode != 0:
        return f"{passed}/{total} 通过，{failed} 失败，退出码 {returncode}"
    return None


class WebClientJsTests(unittest.TestCase):
    def test_page_behaviour_cases_pass(self):
        node = shutil.which("node")
        if not node:
            self.fail("找不到 node：gui/web 的前端用例要 node 跑（CI 里由 actions/setup-node 提供）")
        # Node 22 不认目录参数，用例文件在这里展开成显式路径
        cases = [str(path) for path in sorted(JS_DIR.glob("*.test.js"))]
        if not cases:
            self.fail("tests/js 下没有 *.test.js 用例")
        proc = subprocess.run(
            [node, "--test", "--test-reporter=tap", "--test-timeout=30000", "--test-force-exit", *cases],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT)
        output = proc.stdout + proc.stderr
        problem = judge(output, proc.returncode)
        if problem:
            # 干净副本与新 worktree 都没有 node_modules，直接告诉下一个人装什么
            hint = "（先 npm ci 装 jsdom）" if "Cannot find module" in output else ""
            self.fail(f"前端用例没全过（{problem}）{hint}：\n{output}")


class JudgeTests(unittest.TestCase):
    """守卫自己也要能被证伪：去掉任一条判断，下面必有一条返红。"""

    GREEN = "# tests 6\n# pass 6\n# fail 0\n"

    def test_all_green_passes(self):
        self.assertIsNone(judge(self.GREEN, 0))

    def test_no_cases_is_a_failure(self):
        self.assertIsNotNone(judge("# tests 0\n# pass 0\n# fail 0\n", 0))

    def test_unreadable_output_is_a_failure(self):
        self.assertIsNotNone(judge("", 0))

    def test_a_failed_case_is_a_failure(self):
        self.assertIsNotNone(judge("# tests 6\n# pass 5\n# fail 1\n", 0))

    def test_nonzero_exit_is_a_failure(self):
        self.assertIsNotNone(judge(self.GREEN, 1))


if __name__ == "__main__":
    unittest.main()
