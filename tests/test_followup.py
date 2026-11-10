"""复测队列核对（tool/followup.py）：只读报出标签与主表的差异（#988）。"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import fixtures  # noqa: E402
import followup  # noqa: E402

HEADER = "| Issue | 报告者 | 机型 / 系统 | 修复（进入的版本） | 要观察的输出 |"
RULE = "| ----- | --- | --- | --- | --- |"


def doc(*rows, queue=HEADER, batch=()):
    """一份形如真实文档的样本：队列小节前有一张表、里面有一个 `###` 批次表、后面还有一张。"""
    return "\n".join([
        "# 发版后复测清单",
        "## 每次发版后照做",
        "1. 取出当前队列",
        "| Issue | 报告者 |",
        "| ----- | ------ |",
        "| #88 | @early |",
        "## 当前队列",
        "2026-11-10：一段日期记录，不该被当成表。",
        queue,
        RULE,
        *rows,
        "### 更早的一批",
        HEADER,
        RULE,
        *batch,
        "## 待真机反馈（不是 `waiting-for-verify`）",
        "| Issue | 谁 | 机型 / 系统 | 要什么 |",
        "| ----- | -- | ----------- | ------ |",
        "| #91 | @q | 机型 | 数据 |",
    ])


class TableTests(unittest.TestCase):
    def test_only_tables_inside_the_queue_section_count(self):
        text = doc("| #10 | @a | 机型 | PR #1 | 输出 |",
                   batch=("| #90 | @old | 机型 | PR #1 | 输出 |",))
        result = followup.scan(text, [{"number": 10}, {"number": 90}])
        self.assertEqual(result.rows, 2, "`###` 批次的表算登记；别的 `##` 小节里的表不算")
        self.assertEqual(result.missing, ())
        self.assertEqual(result.expired, (), "小节外的 #88 与 #91 都不该被当成队列")

    def test_a_missing_queue_section_is_unreadable(self):
        text = doc("| #10 | @a | 机型 | PR #1 | 输出 |").replace("## 当前队列", "## 队列")
        with self.assertRaises(followup.Unreadable):
            followup.table_of(text)

    def test_a_header_without_the_issue_column_is_unreadable(self):
        text = doc("| #10 | @a | 机型 | PR #1 | 输出 |",
                   queue="| 票号 | 报告者 | 机型 / 系统 | 修复（进入的版本） | 要观察的输出 |")
        with self.assertRaises(followup.Unreadable):
            followup.table_of(text)

    def test_a_row_whose_issue_cell_is_not_a_number_is_unreadable(self):
        text = doc("| 待定 | @a | 机型 | PR #1 | 输出 |")
        with self.assertRaises(followup.Unreadable):
            followup.table_of(text)

    def test_a_row_naming_two_tickets_registers_both(self):
        result = followup.scan(doc("| #193 / #581 | @a | 机型 | PR #1 | 输出 |"),
                               [{"number": 193}, {"number": 581}])
        self.assertEqual(result.expired, (), "合列行里的两个号都算已登记")
        self.assertEqual(result.rows, 2)

    def test_an_escaped_pipe_inside_a_cell_does_not_split_the_row(self):
        text = doc("| #10 | @a | 机型 \\| 系统 | PR #1 | 输出 \\| 预期 |")
        result = followup.scan(text, [{"number": 10}])
        self.assertEqual(result.rows, 1, "`\\|` 是单元格里的竖线，不是分隔符")
        self.assertEqual(result.expired, ())


class DiffTests(unittest.TestCase):
    def test_rows_and_labels_are_diffed_both_ways(self):
        text = doc("| #10 | @a | 机型 | PR #1 | 输出 |",
                   "| #11 | @b | 机型 | PR #2 | 输出 |",
                   "| #12 | @c | 机型 | PR #3 | 输出 |")
        result = followup.scan(text, [{"number": 10, "author": {"login": "a"}},
                                      {"number": 13, "author": {"login": "d"}}])
        self.assertEqual(result.missing, ((13, "d"),), "标签有、主表没有的按票号升序")
        self.assertEqual(result.expired, (11, 12), "主表有、标签没有的同样升序")
        self.assertEqual((result.rows, result.labeled), (3, 2))
        self.assertFalse(result.same)

    def test_an_issue_without_an_author_is_still_listed(self):
        result = followup.scan(doc(), [{"number": 7, "author": None}])
        self.assertEqual(result.missing, ((7, ""),))
        self.assertIn("#7", followup.render(result))

    def test_an_issue_payload_without_the_author_key_is_still_listed(self):
        result = followup.scan(doc(), [{"number": 7}])
        self.assertEqual(result.missing, ((7, ""),))


class RenderTests(unittest.TestCase):
    def test_the_report_gives_each_difference_with_its_count(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        out = followup.render(followup.scan(text, [{"number": 7, "author": {"login": "s"}},
                                                   {"number": 8}]))
        self.assertIn("缺行 2", out)
        self.assertIn("过期行 1", out)
        self.assertIn("#7  @s", out)
        self.assertIn("#11", out)

    def test_a_matching_pair_says_so_without_listing_anything(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        out = followup.render(followup.scan(text, [{"number": 11}]))
        self.assertIn("一致", out)
        self.assertEqual(len(out.splitlines()), 2, "一致时只有标题行与结论行，没有清单")


class FakeGh:
    """假 `gh`：只应答 `issue list`，其余调用一律记为错。"""

    def __init__(self, issues=(), rc=0, out=None):
        self.issues, self.rc, self.out = list(issues), rc, out
        self.runner = fixtures.FakeRunner(runs=self.route)

    def route(self, script, *args):
        assert script == "gh", f"只该调 gh，收到 {script}"
        assert args[:2] == ("issue", "list"), f"没预料到的 gh 调用：{args}"
        if self.rc:
            return "", "boom", self.rc
        return self.out if self.out is not None else json.dumps(self.issues), "", 0


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "release-followup.md"

    def run_main(self, text, gh):
        self.path.write_text(text, encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = followup.main([], runner=gh.runner.run, doc=self.path)
        return code, out.getvalue(), err.getvalue()

    def test_the_gh_query_covers_every_open_ticket(self):
        gh = FakeGh([{"number": 11}])
        self.run_main(doc("| #11 | @b | 机型 | PR #2 | 输出 |"), gh)
        self.assertEqual(gh.runner.run_calls[0].args,
                         ("issue", "list", "--label", "waiting-for-verify", "--state", "open",
                          "--limit", "1000", "--json", "number,author"))

    def test_a_consistent_queue_exits_zero(self):
        code, out, _ = self.run_main(doc("| #11 | @b | 机型 | PR #2 | 输出 |"),
                                     FakeGh([{"number": 11, "author": {"login": "b"}}]))
        self.assertEqual(code, 0)
        self.assertIn("一致", out)

    def test_a_difference_exits_one_and_lists_both_kinds(self):
        code, out, _ = self.run_main(doc("| #11 | @b | 机型 | PR #2 | 输出 |"),
                                     FakeGh([{"number": 7, "author": {"login": "s"}}]))
        self.assertEqual(code, 1)
        self.assertIn("缺行 1", out)
        self.assertIn("#7  @s", out)
        self.assertIn("过期行 1", out)
        self.assertIn("#11", out)

    def test_a_ticket_without_an_author_is_reported_not_crashed(self):
        code, out, _ = self.run_main(doc(), FakeGh([{"number": 7, "author": None}]))
        self.assertEqual(code, 1)
        self.assertIn("#7", out)

    def test_a_failed_gh_call_exits_two_and_leaves_the_document_alone(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        code, out, err = self.run_main(text, FakeGh(rc=1))
        self.assertEqual(code, 2)
        self.assertIn("读不到", err)
        self.assertEqual(out, "")
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [self.path], "没有写出别的文件")

    def test_an_unreadable_table_exits_two_and_leaves_the_document_alone(self):
        text = doc("| 待定 | @a | 机型 | PR #1 | 输出 |")
        code, out, err = self.run_main(text, FakeGh([{"number": 11}]))
        self.assertEqual(code, 2)
        self.assertIn("结构认不出", err)
        self.assertEqual(out, "")
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_a_hung_gh_call_exits_two_instead_of_hanging(self):
        def hung(script, *args):
            raise subprocess.TimeoutExpired("gh", followup.TIMEOUT)

        self.path.write_text(doc(), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = followup.main([], runner=hung, doc=self.path)
        self.assertEqual(code, 2)
        self.assertIn("没有返回", err.getvalue())

    def test_arguments_are_refused_rather_than_ignored(self):
        gh = FakeGh()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = followup.main(["--write"], runner=gh.runner.run, doc=self.path)
        self.assertEqual(code, 2)
        self.assertEqual(gh.runner.run_calls, [], "参数不合规时不碰 gh")


class RealQueueTests(unittest.TestCase):
    """真实的复测队列文档：小节名、列名或合列行被改掉时，这里先红。"""

    def test_the_checked_in_queue_document_still_parses(self):
        table = followup.table_of(followup.DOC.read_text(encoding="utf-8"))
        self.assertIn(followup.ISSUE_COLUMN, table.columns)
        self.assertGreater(len(table.issues), 0)
        self.assertIn(193, table.issues)
        self.assertIn(581, table.issues, "`#193 / #581` 这种合列行要两个号都算")


if __name__ == "__main__":
    unittest.main()
