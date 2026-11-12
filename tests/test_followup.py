"""复测队列核对与写回（tool/followup.py）：报出标签与队列的差异，`--write` 把表补到一致（#988、#989）。"""
import contextlib
import io
import json
import os
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

    def test_a_blocked_on_device_ticket_never_joins_the_queue(self):
        blocked = {"number": 7, "author": {"login": "s"},
                   "labels": [{"name": "waiting-for-verify"}, {"name": "blocked-on-device"}]}
        result = followup.scan(doc(), [blocked])
        self.assertEqual(result.missing, (), "催不动的票不补进队列")
        self.assertEqual(result.labeled, 0)
        self.assertEqual(result.blocked, 1)
        self.assertTrue(result.same)

    def test_a_blocked_on_device_row_is_parked_not_expired(self):
        text = doc("| #1125 | @s | 机型 | 0.4.4 | 输出 |")
        result = followup.scan(text, [{"number": 1125,
                                       "labels": [{"name": "blocked-on-device"}]}])
        self.assertEqual(result.expired, (), "行不是过期行：删掉会连机型与观察项一起丢掉")
        self.assertEqual((result.blocked, result.parked), (1, 1))
        self.assertIn("| #1125 | @s | 机型 | 0.4.4 | 输出 |", followup.apply(text, result))


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


def main_rows(text):
    """`## 当前队列` 里第一张表的数据行（不含表头与分隔行）。"""
    lines = text.splitlines()
    start, end = followup.table_ranges(lines, *followup.section_bounds(lines))[0]
    return lines[start + 2:end]


class ApplyTests(unittest.TestCase):
    def test_missing_rows_land_at_the_end_of_the_main_table_in_number_order(self):
        text = doc("| #20 | @b | 机型 | PR #2 | 输出 |")
        result = followup.scan(text, [{"number": 20, "author": {"login": "b"}},
                                      {"number": 31, "author": {"login": "c"}},
                                      {"number": 25, "author": {"login": "d"}}])
        out = followup.apply(text, result)
        self.assertEqual(main_rows(out)[-2:], ["| #25 | @d | — | — | — |",
                                               "| #31 | @c | — | — | — |"],
                         "缺行按票号升序补在主表末尾，五列都用 `—` 占位")

    def test_a_ticket_without_an_author_gets_the_placeholder_without_an_at_sign(self):
        text = doc()
        out = followup.apply(text, followup.scan(text, [{"number": 7}]))
        self.assertIn("| #7 | — | — | — | — |", out)
        self.assertNotIn("@—", out)

    def test_an_expired_row_leaves_the_main_table(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |",
                   "| #12 | @c | 机型 | PR #3 | 输出 |")
        out = followup.apply(text, followup.scan(text, [{"number": 11}]))
        gone = [line for line in text.splitlines() if line not in out.splitlines()]
        self.assertEqual(gone, ["| #12 | @c | 机型 | PR #3 | 输出 |"])
        self.assertEqual(out.splitlines(), [line for line in text.splitlines() if line not in gone],
                         "除了删掉那一行，别的逐字不动")

    def test_an_expired_row_leaves_the_batch_table_it_is_in(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |",
                   batch=("| #90 | @old | 机型 | PR #1 | 输出 |",))
        out = followup.apply(text, followup.scan(text, [{"number": 11}]))
        self.assertNotIn("#90", out, "过期行从它实际所在的那张表里删")
        self.assertIn("### 更早的一批", out)
        self.assertEqual(len(out.splitlines()), len(text.splitlines()) - 1)

    def test_a_row_whose_tickets_are_only_partly_expired_is_kept(self):
        text = doc("| #193 / #581 | @a | 机型 | PR #1 | 输出 |")
        out = followup.apply(text, followup.scan(text, [{"number": 581},
                                                        {"number": 12}]))
        self.assertIn("| #193 / #581 | @a | 机型 | PR #1 | 输出 |", out,
                      "删整行会连带丢掉仍开着的那张票，宁可留着让核对继续报差异")

    def test_a_consistent_queue_comes_back_byte_for_byte(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        self.assertEqual(followup.apply(text, followup.scan(text, [{"number": 11}])), text)

    def test_everything_outside_the_queue_tables_is_unchanged(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        out = followup.apply(text, followup.scan(text, [{"number": 11},
                                                        {"number": 7, "author": {"login": "s"}}]))
        self.assertIn("2026-11-10：一段日期记录，不该被当成表。", out)
        self.assertIn("| #91 | @q | 机型 | 数据 |", out, "别的 `##` 小节里的表不动")
        self.assertIn("| #88 | @early |", out, "队列小节之前的表也不动")

    def test_applying_twice_changes_nothing_more(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        issues = [{"number": 11, "author": {"login": "b"}},
                  {"number": 7, "author": {"login": "s"}}]
        once = followup.apply(text, followup.scan(text, issues))
        self.assertEqual(followup.apply(once, followup.scan(once, issues)), once)


class DocumentCase(unittest.TestCase):
    """跑 `main()` 的基线：临时目录里一份样例文档 + 假 `gh`。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "release-followup.md"

    def run_main(self, text, gh, argv=()):
        self.path.write_text(text, encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = followup.main(list(argv), runner=gh.runner.run, doc=self.path)
        return code, out.getvalue(), err.getvalue()


class CommandTests(DocumentCase):

    def test_the_gh_query_covers_every_open_ticket(self):
        gh = FakeGh([{"number": 11}])
        self.run_main(doc("| #11 | @b | 机型 | PR #2 | 输出 |"), gh)
        self.assertEqual(gh.runner.run_calls[0].args,
                         ("issue", "list", "--label", "waiting-for-verify", "--state", "open",
                          "--limit", "1000", "--json", "number,author,labels"))

    def test_a_blocked_on_device_ticket_exits_zero_and_says_why(self):
        blocked = {"number": 1125, "author": {"login": "s"},
                   "labels": [{"name": "waiting-for-verify"}, {"name": "blocked-on-device"}]}
        code, out, _ = self.run_main(doc(), FakeGh([blocked]))
        self.assertEqual(code, 0, "不进队列的票不算差异")
        self.assertIn("blocked-on-device 1 张不进队列", out)
        self.assertNotIn("#1125", out)

    def test_malformed_labels_are_unreadable_not_a_crash(self):
        banned = {"number": 1125, "labels": ["blocked-on-device"]}   # 被 --jq 压平过的形状
        code, out, err = self.run_main(doc(), FakeGh(out=json.dumps([banned])))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("labels 不是对象数组", err)

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
            code = followup.main(["--dry-run"], runner=gh.runner.run, doc=self.path)
        self.assertEqual(code, 2)
        self.assertEqual(gh.runner.run_calls, [], "参数不合规时不碰 gh")


class WriteTests(DocumentCase):
    def test_write_adds_the_missing_row_and_rechecks_clean(self):
        gh = FakeGh([{"number": 11, "author": {"login": "b"}},
                     {"number": 7, "author": {"login": "s"}}])
        code, out, _ = self.run_main(doc("| #11 | @b | 机型 | PR #2 | 输出 |"), gh,
                                     argv=["--write"])
        self.assertEqual(code, 0, "写回后再核对一遍，应当一致")
        self.assertIn("补 1 行", out)
        self.assertIn("一致", out)
        stored = self.path.read_text(encoding="utf-8")
        self.assertIn("| #7 | @s | — | — | — |", stored)

    def test_write_keeps_a_blocked_on_device_row(self):
        gh = FakeGh([{"number": 1125, "labels": [{"name": "blocked-on-device"}]}])
        code, _, _ = self.run_main(doc("| #1125 | @s | 机型 | 0.4.4 | 输出 |"), gh,
                                   argv=["--write"])
        self.assertEqual(code, 0)
        self.assertIn("| #1125 | @s | 机型 | 0.4.4 | 输出 |",
                      self.path.read_text(encoding="utf-8"),
                      "机型、版本与要观察的输出留原处；解阻后不必重填")

    def test_write_drops_an_expired_row_from_the_batch_table(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |",
                   batch=("| #90 | @old | 机型 | PR #1 | 输出 |",))
        gh = FakeGh([{"number": 11, "author": {"login": "b"}}])
        code, _, _ = self.run_main(text, gh, argv=["--write"])
        self.assertEqual(code, 0)
        stored = self.path.read_text(encoding="utf-8")
        self.assertNotIn("#90", stored)
        self.assertIn("### 更早的一批", stored, "批次表本身还在，只少了那一行")

    def test_a_second_write_changes_nothing(self):
        gh = FakeGh([{"number": 11, "author": {"login": "b"}},
                     {"number": 7, "author": {"login": "s"}}])
        self.run_main(doc("| #11 | @b | 机型 | PR #2 | 输出 |"), gh, argv=["--write"])
        first = self.path.read_text(encoding="utf-8")
        code, _, _ = self.run_main(first, gh, argv=["--write"])
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), first, "第二次一个字都不该改")

    def test_write_does_not_touch_a_consistent_document(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        gh = FakeGh([{"number": 11, "author": {"login": "b"}}])
        self.path.write_text(text, encoding="utf-8")
        if os.name == "posix":
            os.chmod(self.path, 0o444)      # 真去写就会失败，只读是「没动文件」的判据
            self.addCleanup(os.chmod, self.path, 0o644)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = followup.main(["--write"], runner=gh.runner.run, doc=self.path)
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_a_failed_gh_call_leaves_the_document_alone_even_with_write(self):
        text = doc("| #11 | @b | 机型 | PR #2 | 输出 |")
        code, out, err = self.run_main(text, FakeGh(rc=1), argv=["--write"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_write_keeps_lf_line_endings(self):
        gh = FakeGh([{"number": 11, "author": {"login": "b"}},
                     {"number": 7, "author": {"login": "s"}}])
        self.run_main(doc("| #11 | @b | 机型 | PR #2 | 输出 |"), gh, argv=["--write"])
        # macOS / Linux 的 os.linesep 就是 `\n`，这条只有 Windows job 能证伪
        self.assertNotIn(b"\r\n", self.path.read_bytes())

    def test_write_still_reports_a_difference_it_will_not_resolve(self):
        # `#193 / #581` 只有一半过期：删整行会丢掉仍开着的那张，所以留着，写回后照报差异
        text = doc("| #193 / #581 | @a | 机型 | PR #1 | 输出 |")
        gh = FakeGh([{"number": 581, "author": {"login": "a"}}])
        code, out, _ = self.run_main(text, gh, argv=["--write"])
        self.assertEqual(code, 1)
        self.assertIn("过期行 1", out)
        self.assertIn("| #193 / #581 | @a | 机型 | PR #1 | 输出 |",
                      self.path.read_text(encoding="utf-8"))


class RealQueueTests(unittest.TestCase):
    """真实的复测队列文档：小节名、列名或合列行被改掉时，这里先红。"""

    def test_the_checked_in_queue_document_still_parses(self):
        table = followup.table_of(followup.DOC.read_text(encoding="utf-8"))
        self.assertIn(followup.ISSUE_COLUMN, table.columns)
        self.assertGreater(len(table.issues), 0)
        self.assertIn(193, table.issues)
        self.assertIn(581, table.issues, "`#193 / #581` 这种合列行要两个号都算")

    def test_apply_handles_the_checked_in_document(self):
        text = followup.DOC.read_text(encoding="utf-8")
        known = [{"number": number} for number in followup.table_of(text).issues]
        self.assertEqual(followup.apply(text, followup.scan(text, known)), text,
                         "既有票号全在时，真实文档原样返回")

        out = followup.apply(text, followup.scan(text, known + [{"number": 999999}]))
        self.assertIn(999999, followup.table_of(out).issues, "写回后的文档仍是合法队列")
        self.assertEqual(len(out.splitlines()), len(text.splitlines()) + 1)
        self.assertIn("\n| #999999 | — | — | — | — |\n", out, "补行落在主表末尾而不是文件末尾")


if __name__ == "__main__":
    unittest.main()
