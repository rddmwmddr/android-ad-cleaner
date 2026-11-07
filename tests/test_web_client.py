"""gui/web 与手机版的前端行为用例放在 tests/js/，这里只做代跑与守卫。

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


class WebClientJsTests(unittest.TestCase):
    def test_page_behaviour_cases_pass(self):
        node = shutil.which("node")
        if not node:
            self.fail("找不到 node：gui/web 的前端用例要 node 跑（CI 里由 actions/setup-node 提供）")
        proc = subprocess.run(
            [node, "--test", "--test-reporter=tap", "--test-timeout=30000", str(JS_DIR)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=TIMEOUT)
        output = proc.stdout + proc.stderr
        total = self._tally(output, "tests")
        passed = self._tally(output, "pass")
        failed = self._tally(output, "fail")
        # node --test 在一个用例文件都没有时返回 0：目录被清空、文件改名都会变成哑用例
        if not total or failed or passed != total or proc.returncode != 0:
            self.fail(f"前端用例没全过（{passed}/{total} 通过，{failed} 失败）：\n{output}")

    @staticmethod
    def _tally(output, key):
        found = re.search(rf"^# {key} (\d+)$", output, re.MULTILINE)
        return int(found.group(1)) if found else 0


if __name__ == "__main__":
    unittest.main()
