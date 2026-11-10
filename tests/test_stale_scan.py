"""needs-info 停摆机制（tool/stale.py）：判定与阈值覆盖（#977）、写入与幂等（#978）。"""
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import fixtures  # noqa: E402
import stale  # noqa: E402

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
REPORTER = "reporter"


def ago(**kwargs):
    """距今多久的服务器时间戳，与 gh 给的同形。"""
    return (NOW - timedelta(**kwargs)).strftime("%Y-%m-%dT%H:%M:%SZ")


def said(who, created):
    return {"author": {"login": who} if who else None, "createdAt": created}


def ticket(number=1, labels=("needs-info",), author=REPORTER, created=None, comments=()):
    return {
        "number": number,
        "title": f"票 {number}",
        "createdAt": created or ago(days=30),
        "author": {"login": author} if author else None,
        "labels": [{"name": name} for name in labels],
        "comments": [dict(item) for item in comments],
    }


def action(issue, days=stale.DEFAULT_DAYS):
    return stale.decide(issue, NOW, days).action


class DecideTests(unittest.TestCase):
    def test_last_comment_by_reporter_never_marked(self):
        issue = ticket(comments=[said(REPORTER, ago(days=400))])
        self.assertEqual(action(issue), stale.KEEP)

    def test_maintainer_recent_not_marked(self):
        issue = ticket(comments=[said("maintainer", ago(days=3))])
        decision = stale.decide(issue, NOW)
        self.assertEqual(decision.action, stale.KEEP)
        self.assertEqual(decision.days, 3)

    def test_maintainer_past_threshold_marked(self):
        issue = ticket(comments=[said("maintainer", ago(days=20))])
        decision = stale.decide(issue, NOW)
        self.assertEqual(decision.action, stale.MARK)
        self.assertEqual(decision.days, 20)
        self.assertEqual(decision.last_author, "maintainer")

    def test_threshold_counts_whole_days_inclusively(self):
        exact = ticket(comments=[said("maintainer", ago(days=14))])
        short = ticket(comments=[said("maintainer", ago(days=13, hours=23))])
        self.assertEqual(action(exact), stale.MARK)
        self.assertEqual(action(short), stale.KEEP)

    def test_no_comments_counts_from_created_at(self):
        old = ticket(created=ago(days=20))
        fresh = ticket(created=ago(days=3))
        decision = stale.decide(old, NOW)
        self.assertEqual(decision.action, stale.MARK)
        self.assertEqual(decision.days, 20)
        self.assertIn("票下没有评论", decision.reason)
        self.assertNotIn("末评", decision.reason)
        self.assertEqual(action(fresh), stale.KEEP)

    def test_stale_is_not_marked_twice(self):
        issue = ticket(labels=("needs-info", "stale"),
                       comments=[said("maintainer", ago(days=40))])
        self.assertEqual(action(issue), stale.KEEP)

    def test_reporter_reply_unmarks(self):
        issue = ticket(labels=("needs-info", "stale"),
                       comments=[said("maintainer", ago(days=40)), said(REPORTER, ago(days=2))])
        self.assertEqual(action(issue), stale.UNMARK)

    def test_stale_without_comments_stays(self):
        issue = ticket(labels=("needs-info", "stale"), created=ago(days=40))
        decision = stale.decide(issue, NOW)
        self.assertEqual(decision.action, stale.KEEP)
        self.assertIn("票下没有评论", decision.reason)
        self.assertNotIn("末评", decision.reason)

    def test_stale_with_unreadable_last_author_stays(self):
        issue = ticket(labels=("needs-info", "stale"),
                       comments=[said(None, ago(days=40))])
        self.assertEqual(action(issue), stale.KEEP)

    def test_skips_in_progress_and_waiting_for_verify(self):
        for label in ("in-progress", "waiting-for-verify"):
            with self.subTest(label=label):
                issue = ticket(labels=("needs-info", label),
                               comments=[said("maintainer", ago(days=40))])
                self.assertEqual(action(issue), stale.SKIP)

    def test_skips_without_needs_info(self):
        issue = ticket(labels=("bug",), comments=[said("maintainer", ago(days=40))])
        self.assertEqual(action(issue), stale.SKIP)

    def test_skips_without_reporter(self):
        issue = ticket(author=None, comments=[said("maintainer", ago(days=40))])
        self.assertEqual(action(issue), stale.SKIP)

    def test_latest_comment_wins_regardless_of_order(self):
        issue = ticket(comments=[said(REPORTER, ago(days=2)), said("maintainer", ago(days=40))])
        self.assertEqual(action(issue), stale.KEEP)

    def test_reporter_match_ignores_case(self):
        issue = ticket(author="Reporter", comments=[said("reporter", ago(days=40))])
        self.assertEqual(action(issue), stale.KEEP)

    def test_days_override_moves_the_line(self):
        issue = ticket(comments=[said("maintainer", ago(days=13))])
        self.assertEqual(action(issue, days=12), stale.MARK)
        self.assertEqual(action(issue, days=14), stale.KEEP)

    def test_unreadable_comment_time_skips_instead_of_guessing(self):
        issue = ticket(comments=[said("maintainer", ago(days=60)), said(REPORTER, "not a time")])
        decision = stale.decide(issue, NOW)
        self.assertEqual(decision.action, stale.SKIP)
        self.assertIn("读不出时间", decision.reason)

    def test_same_instant_by_two_authors_is_undecidable(self):
        same = ago(days=40)
        issue = ticket(comments=[said("maintainer", same), said(REPORTER, same)])
        self.assertEqual(action(issue), stale.SKIP)
        self.assertEqual(action(ticket(comments=[said("maintainer", same),
                                                said("maintainer", same)])), stale.MARK)

    def test_future_comment_time_counts_as_zero_days(self):
        issue = ticket(comments=[said("maintainer", (NOW + timedelta(days=3))
                                      .strftime("%Y-%m-%dT%H:%M:%SZ"))])
        decision = stale.decide(issue, NOW)
        self.assertEqual(decision.action, stale.KEEP)
        self.assertEqual(decision.days, 0)


class ScanTests(unittest.TestCase):
    def test_splits_mark_and_unmark_sorted_by_number(self):
        issues = [
            ticket(number=30, comments=[said("maintainer", ago(days=20))]),
            ticket(number=10, labels=("needs-info", "stale"),
                   comments=[said(REPORTER, ago(days=1))]),
            ticket(number=20, comments=[said(REPORTER, ago(days=20))]),
            ticket(number=40, labels=("needs-info", "waiting-for-verify"),
                   comments=[said("maintainer", ago(days=20))]),
            ticket(number=5, created=ago(days=20)),
        ]
        report = stale.scan(issues, NOW)
        self.assertEqual([item.number for item in report.mark], [5, 30])
        self.assertEqual([item.number for item in report.unmark], [10])
        self.assertEqual([item.number for item in report.skipped], [40])
        self.assertEqual(len(report.decided), 5)


class ArgsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(stale.parse_args([]), stale.Options(dry_run=False, days=14))

    def test_dry_run_and_days(self):
        self.assertEqual(stale.parse_args(["--dry-run", "--days", "12"]),
                         stale.Options(dry_run=True, days=12))

    def test_rejects_bad_input(self):
        for argv in (["--days"], ["--days", "x"], ["--days", "0"], ["--days", "-3"], ["--nope"]):
            with self.subTest(argv=argv):
                with self.assertRaises(ValueError):
                    stale.parse_args(argv)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.runner = fixtures.FakeRunner(runs=self.reply)
        self.payload = [
            ticket(number=7, comments=[said("maintainer", ago(days=20))]),
            ticket(number=8, comments=[said(REPORTER, ago(days=20))]),
        ]

    def reply(self, script, *args):
        assert script == "gh", f"只该调 gh，收到 {script}"
        return json.dumps(self.payload), "", 0

    def run_main(self, argv, rc_reply=None):
        if rc_reply is not None:
            self.runner = fixtures.FakeRunner(runs=lambda script, *args: ("", "boom", rc_reply))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = stale.main(argv, runner=self.runner.run, now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_lists_candidates_and_never_writes(self):
        code, out, _ = self.run_main(["--dry-run", "--days", "14"])
        self.assertEqual(code, stale.EXIT_OK)
        self.assertIn("#7", out)
        self.assertIn("加标 1", out)
        self.assertIn("不动 1", out)
        self.assertIn("--dry-run", out)
        calls = [(call.script, call.args) for call in self.runner.run_calls]
        self.assertEqual(calls, [("gh", ("issue", "list", "--state", "open", "--label", "needs-info",
                                         "--limit", "1000", "--json", stale.FIELDS))])

    def test_gh_failure_is_reported(self):
        code, out, err = self.run_main(["--dry-run"], rc_reply=1)
        self.assertEqual(code, stale.EXIT_GH)
        self.assertEqual(out, "")
        self.assertIn("boom", err)

    def test_bad_args_exit_usage(self):
        code, _, err = self.run_main(["--days", "zero"])
        self.assertEqual(code, stale.EXIT_USAGE)
        self.assertIn("--days", err)
        self.assertEqual(self.runner.run_calls, [])

    def test_non_json_list_is_reported(self):
        self.runner = fixtures.FakeRunner(runs=lambda script, *args: ("not json", "", 0))
        code, out, err = self.run_main(["--dry-run"])
        self.assertEqual(code, stale.EXIT_GH)
        self.assertEqual(out, "")
        self.assertIn("JSON", err)

    def test_missing_gh_is_reported(self):
        self.runner = fixtures.FakeRunner(runs=lambda script, *args: FileNotFoundError("gh"))
        code, _, err = self.run_main(["--dry-run"])
        self.assertEqual(code, stale.EXIT_GH)
        self.assertIn("gh", err)

    def test_skip_summary_shows_the_reason(self):
        self.payload = [ticket(number=9, labels=("needs-info", "waiting-for-verify"),
                               comments=[said("maintainer", ago(days=40))])]
        code, out, _ = self.run_main(["--dry-run"])
        self.assertEqual(code, stale.EXIT_OK)
        self.assertIn("跳过 1", out)
        self.assertIn("waiting-for-verify", out)


class WriteTests(unittest.TestCase):
    """写层（#978）：只在状态跃迁时动作、一张票一条评论、标签没写上就不写评论。"""

    def setUp(self):
        self.issues = [ticket(number=7, comments=[said("maintainer", ago(days=20))])]
        self.writes = []                  # 读以外的 gh 调用，按发生顺序
        self.fail = lambda args: False    # 哪些写入返回非零
        self.runner = fixtures.FakeRunner(runs=self.reply)

    def reply(self, script, *args):
        assert script == "gh", f"只该调 gh，收到 {script}"
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues), "", 0
        self.writes.append(args)
        if self.fail(args):
            return "", "boom", 1
        return "", "", 0

    def run_main(self, argv=()):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = stale.main(list(argv), runner=self.runner.run, now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_mark_adds_label_then_one_comment(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_OK)
        self.assertIn("写入 1", out)
        self.assertEqual(len(self.writes), 2)
        self.assertEqual(self.writes[0], ("issue", "edit", "7", "--add-label", "stale"))
        self.assertEqual(self.writes[1][:4], ("issue", "comment", "7", "--body"))

    def test_comment_says_how_long_and_what_to_do(self):
        _, _, _ = self.run_main()
        body = self.writes[1][4]
        self.assertIn("距上一次回复已 20 天", body)
        self.assertIn("补齐后直接在本票回复；如果确实拿不到，说一声，我们会按现有信息评估后关票", body)
        self.assertNotIn("@", body)

    def test_comment_without_any_earlier_reply_counts_from_creation(self):
        self.issues = [ticket(number=7, created=ago(days=20))]
        self.run_main()
        self.assertIn("本票创建已 20 天，还没有收到过回复", self.writes[1][4])
        self.assertNotIn("上一次回复", self.writes[1][4])

    def test_second_run_on_the_same_ticket_writes_nothing(self):
        self.run_main()
        self.assertEqual(len(self.writes), 2)
        # 打标后的票就是下一次扫描读到的形状：同一张票再跑零新增
        self.issues = [dict(self.issues[0],
                            labels=[{"name": "needs-info"}, {"name": "stale"}])]
        self.writes.clear()
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_OK)
        self.assertEqual(self.writes, [])
        self.assertIn("写入 0", out)

    def test_reporter_reply_removes_the_label_without_a_comment(self):
        self.issues = [ticket(number=7, labels=("needs-info", "stale"),
                              comments=[said("maintainer", ago(days=40)),
                                        said(REPORTER, ago(days=2))])]
        code, _, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_OK)
        self.assertEqual(self.writes, [("issue", "edit", "7", "--remove-label", "stale")])

    def test_label_failure_skips_the_comment_and_exits_write(self):
        self.fail = lambda args: "--add-label" in args
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_WRITE)
        self.assertEqual(self.writes, [("issue", "edit", "7", "--add-label", "stale")])
        self.assertIn("失败 1", out)
        self.assertIn("boom", out)

    def test_comment_failure_rolls_the_label_back_so_the_next_scan_retries(self):
        self.fail = lambda args: args[:2] == ("issue", "comment")
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_WRITE)
        self.assertEqual(len(self.writes), 3, self.writes)
        self.assertEqual(self.writes[0], ("issue", "edit", "7", "--add-label", "stale"))
        self.assertEqual(self.writes[1][:4], ("issue", "comment", "7", "--body"))
        self.assertEqual(self.writes[2], ("issue", "edit", "7", "--remove-label", "stale"))
        self.assertIn("失败 1", out)
        # 标签退回了：下一次扫描仍判成该加，补写一条评论，而不是永远停在「有标没说明」
        self.fail = lambda args: False
        self.issues = [dict(self.issues[0], labels=[{"name": "needs-info"}])]
        self.writes.clear()
        self.run_main()
        self.assertEqual(len([call for call in self.writes
                              if call[:2] == ("issue", "comment")]), 1)

    def test_one_failed_ticket_does_not_stop_the_others(self):
        self.issues = [
            ticket(number=7, comments=[said("maintainer", ago(days=20))]),
            ticket(number=8, comments=[said("maintainer", ago(days=20))]),
        ]
        self.fail = lambda args: args[2] == "7"
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_WRITE)
        self.assertIn("写入 1", out)
        self.assertIn("失败 1", out)
        self.assertEqual([call[2] for call in self.writes], ["7", "8", "8"])


class CommentTopUpTests(unittest.TestCase):
    """`gh issue list` 的 comments 只带前 100 条：到顶的票要补读，否则末评停在旧的那条。"""

    def setUp(self):
        self.capped = [said("maintainer", ago(days=40))] * stale.COMMENT_CAP
        self.full = self.capped + [said(REPORTER, ago(days=1))]

    def run_main(self, view_reply):
        def reply(script, *args):
            if args[:2] == ("issue", "list"):
                return json.dumps([ticket(number=7, comments=self.capped)]), "", 0
            if args[:2] == ("issue", "view"):
                return view_reply
            raise AssertionError(f"没预料到的 gh 调用：{args}")

        runner = fixtures.FakeRunner(runs=reply)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = stale.main(["--dry-run"], runner=runner.run, now=NOW)
        return code, out.getvalue(), err.getvalue(), runner

    def test_top_up_sees_the_reporter_reply(self):
        code, out, _, runner = self.run_main((json.dumps({"comments": self.full}), "", 0))
        self.assertEqual(code, stale.EXIT_OK)
        self.assertIn("加标 0", out)
        self.assertIn(("gh", ("issue", "view", "7", "--json", "comments")),
                      [(call.script, call.args) for call in runner.run_calls])

    def test_top_up_failure_is_reported(self):
        code, out, err, _ = self.run_main(("", "boom", 1))
        self.assertEqual(code, stale.EXIT_GH)
        self.assertEqual(out, "")
        self.assertIn("boom", err)


if __name__ == "__main__":
    unittest.main()
