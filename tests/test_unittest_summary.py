"""CI 的测试结果表格（devtools/unittest_summary.py，#875）：列取错或漏算跳过数，summary 会静默给出错数字；
测试规模三项（#1394）按 AST 现算，数错就没法当棘轮量具。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from devtools import unittest_summary  # noqa: E402

OK = "----------------------------------------------------------------------\nRan 12 tests in 3.456s\n\nOK\n"
SKIPPED = "Ran 2004 tests in 36.206s\n\nOK (skipped=2)\n"
FAILED = "Ran 30 tests in 2.0s\n\nFAILED (failures=1, errors=2, skipped=3)\n"


class ParseTests(unittest.TestCase):
    def test_ok_without_skips(self):
        self.assertEqual(unittest_summary.parse(OK), (12, "3.456", 0, 0, 0))

    def test_ok_with_skips(self):
        self.assertEqual(unittest_summary.parse(SKIPPED), (2004, "36.206", 0, 0, 2))

    def test_failed_counts_every_kind(self):
        self.assertEqual(unittest_summary.parse(FAILED), (30, "2.0", 1, 2, 3))

    def test_missing_summary_lines_returns_none(self):
        self.assertIsNone(unittest_summary.parse("no summary here"))


class RenderTests(unittest.TestCase):
    def test_pass_row_subtracts_failures_and_skips(self):
        table = unittest_summary.render("Linux / 3.13", SKIPPED, "abc1234")
        self.assertIn("| ✅ Pass | 2002 | 0 | 0 | 2 | 36.206s |", table)
        self.assertIn("提交 `abc1234`", table)

    def test_fail_row(self):
        table = unittest_summary.render("Windows / 3.12", FAILED)
        self.assertIn("| ❌ Fail | 24 | 1 | 2 | 3 | 2.0s |", table)

    def test_unparseable_log_says_so(self):
        self.assertIn("没找到", unittest_summary.render("Linux", "nothing"))


class SuiteSizeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _write(self, rel, source):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def test_counts_test_defs_files_and_lines(self):
        # 顶层函数、类方法、async 方法都算用例；非 test_ 的辅助函数只贡献文件数与行数。
        self._write("tests/test_a.py", "def test_one():\n    pass\n")                 # 2 行, 1 用例
        self._write("tests/sub/test_b.py",
                    "class X:\n    def test_two(self):\n        pass\n\n"
                    "    async def test_three(self):\n        pass\n")                 # 6 行, 2 用例
        self._write("tests/fixtures.py", "def helper():\n    return 1\n")             # 2 行, 0 用例
        self.assertEqual(unittest_summary.suite_size(self.root), (3, 3, 10))

    def test_missing_tests_dir_returns_none(self):
        self.assertIsNone(unittest_summary.suite_size(self.root))

    def test_render_includes_size_labels(self):
        self._write("tests/test_a.py", "def test_one():\n    pass\n")
        table = unittest_summary.render("Linux / 3.13", SKIPPED, "abc1234", root=self.root)
        self.assertIn("### 测试规模", table)
        self.assertIn("用例数", table)
        self.assertIn("文件数", table)
        self.assertIn("行数", table)
        self.assertIn("| 1 | 1 | 2 |", table)

    def test_render_without_tests_dir_says_so_and_does_not_raise(self):
        table = unittest_summary.render("Linux", SKIPPED, root=self.root)
        self.assertIn("### 测试规模", table)
        self.assertIn("统计不出", table)


if __name__ == "__main__":
    unittest.main()
