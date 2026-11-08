"""CI 的测试结果表格（tool/unittest_summary.py，#875）：列取错或漏算跳过数，summary 会静默给出错数字。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import unittest_summary  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
