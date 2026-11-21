"""CI 的测试结果表格（devtools/unittest_summary.py，#875）：列取错或漏算跳过数，summary 会静默给出错数字；
锚点体量同一条口径（#1397）：超限各列一行，不红。
测试规模三项（#1394）按 AST 现算，数错就没法当棘轮量具。"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from devtools import test_anchors  # noqa: E402
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

    def test_one_missing_summary_line_returns_none(self):
        # 两组汇总行缺一即认不出；`or` 写成 `and` 会放过只剩一组的日志。
        self.assertIsNone(unittest_summary.parse("Ran 3 tests in 1.0s\n"))
        self.assertIsNone(unittest_summary.parse("OK\n"))


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


class AnchorBudgetTests(unittest.TestCase):
    """锚点软体量预算（#1397）：超限只可见、不红，量具按断言数而不是函数数。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _write(self, rel, source):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def test_an_over_budget_anchor_is_listed_with_measured_and_cap(self):
        self._write("tests/test_big.py",
                    "class T:\n    def test_x(self):\n"
                    "        self.assertTrue(1)\n        self.assertEqual(1, 1)\n"
                    "        self.assertIsNone(None)\n")
        self._write("tests/test_ok.py",
                    "class T:\n    def test_x(self):\n        self.assertTrue(1)\n")
        section = unittest_summary.budget_section(
            self.root, {"test_big.py": ("大文件", 2), "test_ok.py": ("小文件", 1)})
        self.assertIn("| `test_big.py` | 3 | 2 |", section)
        self.assertNotIn("test_ok.py", section)

    def test_the_visibility_line_does_not_turn_the_guard_red(self):
        """超限不进 violations：同一棵树里守卫仍是零违规，summary 才多出那一行。"""
        self._write("tests/test_big.py",
                    "class T:\n    def test_x(self):\n        self.assertTrue(1)\n")
        anchors = {"test_big.py": ("大文件", 0)}
        self.assertEqual(test_anchors.violations(self.root, anchors), [])
        self.assertEqual(unittest_summary.budget_rows(self.root, anchors),
                         ([("test_big.py", 1, 0)], 1))

    def test_assertions_are_counted_not_test_functions(self):
        """量具口径：`assert` 语句与 assert/fail 方法都算，`def test_` 本身不算。"""
        self._write("tests/test_a.py",
                    "class T:\n    def test_x(self):\n        self.m.assert_called_once()\n"
                    "        with self.assertRaises(ValueError):\n            raise ValueError\n"
                    "        self.fail('boom')\n        assert True\n")
        self.assertEqual(unittest_summary.assertions_in(self.root / "tests/test_a.py"), 4)

    def test_an_anchor_without_a_cap_is_not_measured(self):
        self._write("tests/test_a.py",
                    "class T:\n    def test_x(self):\n        self.assertTrue(1)\n")
        self.assertEqual(unittest_summary.budget_rows(self.root, {"test_a.py": ("无上限", None)}),
                         ([], 0))

    def test_all_within_their_cap_says_so(self):
        self._write("tests/test_a.py",
                    "class T:\n    def test_x(self):\n        self.assertTrue(1)\n")
        section = unittest_summary.budget_section(self.root, {"test_a.py": ("小", 5)})
        self.assertIn("量到的 1 个锚点都没有超过", section)

    def test_an_unmeasured_tree_reports_instead_of_claiming_compliance(self):
        """一个锚点文件都没量到时不许说「都没超」：空测量与真合规要能分开。"""
        self._write("tests/test_a.py",
                    "class T:\n    def test_x(self):\n        self.assertTrue(1)\n")
        section = unittest_summary.budget_section(self.root, {"test_missing.py": ("缺文件", 5)})
        self.assertIn("统计不出", section)
        self.assertNotIn("都没有超过", section)

    def test_missing_tests_dir_says_so_and_does_not_raise(self):
        section = unittest_summary.budget_section(self.root, {"test_a.py": ("小", 5)})
        self.assertIn("统计不出", section)

    def test_render_includes_the_budget_section(self):
        self._write("tests/test_a.py",
                    "class T:\n    def test_x(self):\n        self.assertTrue(1)\n")
        table = unittest_summary.render("Linux / 3.13", SKIPPED, root=self.root)
        self.assertIn("### 锚点体量", table)


def read_options(call, *args):
    """跑一次会读文件的调用，回填 `Path.read_text` 收到的关键字参数。

    日志、脚本与用例文件都按 utf-8 读、坏字节替换；这两档在 ASCII 输入上没有可观察差异，
    只能从调用参数上把它钉住（与 `test_ticket_ref` 盯 `open(encoding=…)` 同一做法）。
    """
    real = Path.read_text
    seen = {}

    def spy(path_self, *a, **kw):
        seen.update(kw)
        return real(path_self, *a, **kw)

    with mock.patch.object(Path, "read_text", spy):
        call(*args)
    return seen


class ExactSectionTests(unittest.TestCase):
    """整段输出逐字对拍：小节标题、表格列与分隔符都是 CI 里看的文本，换一个字就该红。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self._write("tests/test_a.py", "def test_one():\n    pass\n")

    def _write(self, rel, source):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def test_size_section_with_a_tree(self):
        self.assertEqual(unittest_summary.size_section(self.root),
                         "### 测试规模\n\n| 用例数 | 文件数 | 行数 |\n|---:|---:|---:|\n| 1 | 1 | 2 |\n")

    def test_size_section_without_a_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(unittest_summary.size_section(Path(tmp)),
                             "### 测试规模\n\n统计不出 `tests/` 下的用例数、文件数与行数"
                             "（读不到 `tests/` 或文件解析失败）。\n")

    def test_budget_section_lists_an_over_budget_anchor(self):
        self._write("tests/test_big.py",
                    "class T:\n    def test_x(self):\n        self.assertTrue(1)\n"
                    "        self.assertEqual(1, 1)\n        self.assertIsNone(None)\n")
        self.assertEqual(
            unittest_summary.budget_section(self.root, {"test_big.py": ("大", 2)}),
            "### 锚点体量（断言数）\n\n| 锚点 | 断言数 | 上限 |\n|---|---:|---:|\n| `test_big.py` | 3 | 2 |\n\n"
            "超限只在这里列出，不阻断合并；上限只许降，口径见 "
            "docs/agents/test-anchors.md 的「体量预算」。\n")

    def test_budget_section_reports_an_unmeasured_tree(self):
        self.assertEqual(
            unittest_summary.budget_section(self.root, {"test_missing.py": ("缺文件", 5)}),
            "### 锚点体量（断言数）\n\n统计不出锚点文件的断言数"
            "（读不到 `tests/`、一个锚点文件都没找到，或文件解析失败）。\n")

    def test_budget_section_says_nothing_is_over_budget(self):
        self.assertEqual(
            unittest_summary.budget_section(self.root, {"test_a.py": ("小", 5)}),
            "### 锚点体量（断言数）\n\n量到的 1 个锚点都没有超过各自的断言数上限。\n")

    def test_render_pass(self):
        self.assertEqual(
            unittest_summary.render("Linux / 3.13", SKIPPED, "abc1234", root=self.root),
            "### 测试结果（Linux / 3.13）\n\n| 结果 | 通过 | 失败 | 错误 | 跳过 | 耗时 |\n"
            "|---|---:|---:|---:|---:|---:|\n| ✅ Pass | 2002 | 0 | 0 | 2 | 36.206s |\n\n"
            "提交 `abc1234`\n\n### 测试规模\n\n| 用例数 | 文件数 | 行数 |\n|---:|---:|---:|\n| 1 | 1 | 2 |\n\n"
            "### 锚点体量（断言数）\n\n统计不出锚点文件的断言数"
            "（读不到 `tests/`、一个锚点文件都没找到，或文件解析失败）。\n")

    def test_render_without_a_sha_has_no_commit_line(self):
        # 默认是没有提交行的：`sha` 给一个占位串就会凭空多出一行「提交」。
        self.assertNotIn("提交", unittest_summary.render("Linux / 3.13", SKIPPED, root=self.root))

    def test_render_fail_row_with_only_failures(self):
        # 只有 failures 时仍是 ❌：`and` 写成 `or` 会把这条判成 Pass。
        self.assertEqual(
            unittest_summary.render("Windows / 3.12", "Ran 5 tests in 1.0s\n\nFAILED (failures=1)\n",
                                    root=self.root).splitlines()[4],
            "| ❌ Fail | 4 | 1 | 0 | 0 | 1.0s |")

    def test_render_without_a_parseable_summary(self):
        self.assertEqual(
            unittest_summary.render("Linux", "nothing", root=self.root),
            "### 测试结果（Linux）\n\n日志里没找到 `Ran N tests` 与 `OK` / `FAILED` 汇总行。\n\n"
            "### 测试规模\n\n| 用例数 | 文件数 | 行数 |\n|---:|---:|---:|\n| 1 | 1 | 2 |\n\n"
            "### 锚点体量（断言数）\n\n统计不出锚点文件的断言数"
            "（读不到 `tests/`、一个锚点文件都没找到，或文件解析失败）。\n")

    def test_render_measures_the_same_tree_it_is_given(self):
        """预算小节读的是传进来的 `root`：退化成默认仓库会把「量到了」说成「统计不出」。"""
        self._write("tests/test_row.py", "class T:\n    def test_x(self):\n        self.assertTrue(1)\n")
        self.assertIn("量到的 1 个锚点都没有超过各自的断言数上限。",
                      unittest_summary.render("Linux", SKIPPED, root=self.root))


class ReadOptionsTests(unittest.TestCase):
    """日志、脚本与用例文件都按 utf-8 读、坏字节替换（Windows cp1252 不炸）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_a.py").write_text("def test_one():\n    pass\n", encoding="utf-8")

    def test_suite_size(self):
        self.assertEqual(read_options(unittest_summary.suite_size, self.root),
                         {"encoding": "utf-8", "errors": "replace"})

    def test_assertions_in(self):
        self.assertEqual(read_options(unittest_summary.assertions_in, self.root / "tests" / "test_a.py"),
                         {"encoding": "utf-8", "errors": "replace"})


class SuiteSizeRootTests(unittest.TestCase):
    def test_the_default_root_is_the_module_parent(self):
        """`root` 缺省取本文件上一级（`devtools/` 的父目录），层级写错就找不到 `tests/`。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "devtools").mkdir(parents=True)
            (repo / "tests").mkdir()
            (repo / "tests" / "test_a.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
            fake = repo / "devtools" / "unittest_summary.py"
            with mock.patch.object(unittest_summary, "__file__", str(fake)):
                self.assertEqual(unittest_summary.suite_size(), (1, 1, 2))


class BudgetRowsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self._write("tests/test_aaa.py", 3)
        self._write("tests/test_abb.py", 1)
        self._write("tests/test_bbb.py", 5)
        self._write("tests/test_ccc.py", 6)

    def _write(self, rel, asserts):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("class T:\n    def test_x(self):\n" + "        self.assertTrue(1)\n" * asserts,
                        encoding="utf-8")

    def test_rows_are_sorted_by_excess_and_counted(self):
        """按（当前值 − 上限）降序；跳过无上限的锚点后仍继续量、且计数是量到的个数。

        排序键、降序与计数三条都要被区分：行名按字典序、插入序或（当前值 + 上限）排序都会给出
        另一个顺序，`break` 会在无上限的 `test_abb.py` 处提前停下。
        """
        anchors = {"test_aaa.py": ("a", 1), "test_abb.py": ("s", None),
                   "test_bbb.py": ("b", 1), "test_ccc.py": ("c", 3)}
        self.assertEqual(unittest_summary.budget_rows(self.root, anchors),
                         ([("test_bbb.py", 5, 1), ("test_ccc.py", 6, 3),
                           ("test_aaa.py", 3, 1)], 3))

    def test_the_default_anchor_table_yields_no_rows_on_a_stranger_tree(self):
        self.assertEqual(unittest_summary.budget_rows(self.root), ([], 0))


class MainTests(unittest.TestCase):
    """`unittest_summary.main` 的进程内调用点：退出码、标签 / 提交哈希的取用与两路输出（#1519）。"""

    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.log = self.dir / "unittest.log"
        self.log.write_text(SKIPPED, encoding="utf-8")

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = unittest_summary.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_usage_when_fewer_than_two_arguments(self):
        code, out, err = self.call()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err, "用法：python3 devtools/unittest_summary.py <日志> [标签] [提交短哈希]\n")

    def test_default_label_and_no_sha(self):
        code, out, err = self.call("prog", str(self.log))
        self.assertEqual(code, 0, err)
        self.assertIn("### 测试结果（unittest）\n", out)
        self.assertNotIn("提交", out)

    def test_explicit_label(self):
        code, out, err = self.call("prog", str(self.log), "Linux / 3.13")
        self.assertEqual(code, 0, err)
        self.assertIn("### 测试结果（Linux / 3.13）\n", out)

    def test_explicit_sha(self):
        code, out, err = self.call("prog", str(self.log), "Linux / 3.13", "abc1234")
        self.assertEqual(code, 0, err)
        self.assertIn("提交 `abc1234`", out)

    def test_a_missing_log_is_unparseable_not_fatal(self):
        code, out, err = self.call("prog", str(self.dir / "nope.log"))
        self.assertEqual(code, 0, err)
        self.assertIn("日志里没找到", out)

    def test_the_log_is_read_as_utf8_with_replacement(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(read_options(unittest_summary.main, ["prog", str(self.log)]),
                             {"encoding": "utf-8", "errors": "replace"})


if __name__ == "__main__":
    unittest.main()
