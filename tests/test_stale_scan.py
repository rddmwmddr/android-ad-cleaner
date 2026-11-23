"""needs-info 停摆机制（devtools/stale.py）：判定与阈值覆盖（#977）、写入与幂等（#978）。"""
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
from devtools import stale  # noqa: E402

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

    def test_skips_claim_verify_and_device_blocked(self):
        for label in ("in-progress", "waiting-for-verify", "blocked-on-device"):
            with self.subTest(label=label):
                issue = ticket(labels=("needs-info", label),
                               comments=[said("maintainer", ago(days=40))])
                self.assertEqual(action(issue), stale.SKIP)

    def test_device_blocked_ticket_names_itself_in_the_reason(self):
        issue = ticket(labels=("needs-info", "blocked-on-device"),
                       comments=[said("maintainer", ago(days=40))])
        decision = stale.decide(issue, NOW)
        self.assertEqual(decision.action, stale.SKIP)
        self.assertIn("blocked-on-device", decision.reason)

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

    def test_the_threshold_reaches_every_decision(self):
        # 13 天：默认阈值判不动，12 天判加标。`scan` 丢掉 days 就退回默认。
        issues = [ticket(number=7, comments=[said("maintainer", ago(days=13))])]
        self.assertEqual([item.number for item in stale.scan(issues, NOW, 12).mark], [7])
        self.assertEqual(stale.scan(issues, NOW, 14).mark, ())


class ClockTests(unittest.TestCase):
    """`instant` / `age_days` / `stamp` 的时区与格式口径（#1520）。"""

    def test_a_z_suffix_is_utc(self):
        self.assertEqual(stale.instant("2026-11-10T04:30:00Z"),
                         datetime(2026, 11, 10, 4, 30, tzinfo=timezone.utc))

    def test_an_explicit_offset_is_kept(self):
        self.assertEqual(stale.instant("2026-11-10T12:30:00+08:00").utcoffset(), timedelta(hours=8))

    def test_a_naive_stamp_is_read_as_utc(self):
        self.assertEqual(stale.instant("2026-11-10 12:30:00").tzinfo, timezone.utc)

    def test_garbage_is_none(self):
        self.assertIsNone(stale.instant("not a time"))

    def test_a_naive_now_is_read_in_the_local_zone(self):
        # gh 的时间戳都带时区；调用方偶尔给不带时区的 now，比较前要先补上本地时区。
        since = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
        naive = since.astimezone().replace(tzinfo=None)
        self.assertEqual(stale.age_days(since, naive), 0)

    def test_stamp_of_none_is_the_words(self):
        self.assertEqual(stale.stamp(None), "时间未知")

    def test_stamp_is_year_month_day_hour_minute(self):
        self.assertRegex(stale.stamp(datetime(2026, 11, 10, 4, 30, tzinfo=timezone.utc)),
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


class LastCommentTests(unittest.TestCase):
    """末评的两条「判不了」：整句文案钉住，好让调用方原样转给维护者（#1520）。"""

    def test_an_unreadable_time_is_named(self):
        with self.assertRaises(stale.Unreadable) as caught:
            stale.last_comment([said("maintainer", "not a time")])
        self.assertEqual(str(caught.exception), "有评论读不出时间，判不了末评")

    def test_two_authors_on_the_same_instant_are_undecidable(self):
        same = ago(days=40)
        with self.assertRaises(stale.Unreadable) as caught:
            stale.last_comment([said("maintainer", same), said(REPORTER, same)])
        self.assertEqual(str(caught.exception),
                         f"{stale.stamp(NOW - timedelta(days=40))} 有多位作者同时发言，判不了末评是谁")


class DecisionTableTests(unittest.TestCase):
    """每一条判定分支的整个 `Decision`：动作、文案与对账字段一起钉（#1520）。

    `decide` 的每个出口都走同一个 `no(...)` 位置参数列表，只断 action 的话，`when` / `who` /
    `age` 被串位、文案被换成占位串都看不出来。
    """

    def check(self, issue, expected):
        self.assertEqual(stale.decide(issue, NOW), expected)

    def test_skips_without_the_state_label(self):
        self.check(ticket(labels=("bug",)),
                   stale.Decision(1, "票 1", stale.SKIP, "没有 needs-info 标签"))

    def test_skips_a_blocked_ticket(self):
        self.check(ticket(labels=("needs-info", "blocked-on-device")),
                   stale.Decision(1, "票 1", stale.SKIP, "带 blocked-on-device，不参与本机制"))

    def test_skips_a_ticket_without_a_reporter(self):
        self.check(ticket(author=None),
                   stale.Decision(1, "票 1", stale.SKIP, "读不出票的作者，判不了末评算不算报告者"))

    def test_skips_a_comment_without_a_time(self):
        self.check(ticket(comments=[said("maintainer", "not a time")]),
                   stale.Decision(1, "票 1", stale.SKIP, "有评论读不出时间，判不了末评"))

    def test_skips_two_authors_on_the_same_instant(self):
        same = ago(days=40)
        self.check(ticket(comments=[said("maintainer", same), said(REPORTER, same)]),
                   stale.Decision(1, "票 1", stale.SKIP,
                                  f"{stale.stamp(NOW - timedelta(days=40))} 有多位作者同时发言，"
                                  "判不了末评是谁"))

    def test_skips_an_unreadable_creation_time(self):
        self.check(ticket(created="not a time"),
                   stale.Decision(1, "票 1", stale.SKIP, "起算时间读不出来"))

    def test_marks_a_ticket_that_never_got_a_reply(self):
        since = NOW - timedelta(days=20)
        self.check(ticket(created=ago(days=20)),
                   stale.Decision(1, "票 1", stale.MARK,
                                  f"票下没有评论，创建于 {stale.stamp(since)}，已 20 天",
                                  20, since, "", False))

    def test_keeps_a_ticket_whose_last_author_is_unknown(self):
        since = NOW - timedelta(days=40)
        self.check(ticket(comments=[said(None, ago(days=40))]),
                   stale.Decision(1, "票 1", stale.KEEP, "末评作者读不出，判不了算不算报告者",
                                  40, since, "", False))

    def test_unmarks_after_a_reporter_reply(self):
        since = NOW - timedelta(days=2)
        self.check(ticket(labels=("needs-info", "stale"),
                          comments=[said("maintainer", ago(days=40)), said(REPORTER, ago(days=2))]),
                   stale.Decision(1, "票 1", stale.UNMARK,
                                  f"报告者已回话（{stale.stamp(since)}）", 2, since, "reporter", True))

    def test_keeps_after_a_reporter_reply_without_the_stale_label(self):
        since = NOW - timedelta(days=2)
        self.check(ticket(comments=[said(REPORTER, ago(days=2))]),
                   stale.Decision(1, "票 1", stale.KEEP,
                                  f"末评由报告者发出（{stale.stamp(since)}），球在维护者这边",
                                  2, since, "reporter", False))

    def test_keeps_an_already_stale_ticket(self):
        since = NOW - timedelta(days=40)
        self.check(ticket(labels=("needs-info", "stale"), comments=[said("maintainer", ago(days=40))]),
                   stale.Decision(1, "票 1", stale.KEEP,
                                  f"已带 stale，末评由 maintainer 发在 {stale.stamp(since)}，不动",
                                  40, since, "maintainer", True))

    def test_keeps_a_ticket_below_the_threshold(self):
        since = NOW - timedelta(days=3)
        self.check(ticket(comments=[said("maintainer", ago(days=3))]),
                   stale.Decision(1, "票 1", stale.KEEP,
                                  f"末评由 maintainer 发在 {stale.stamp(since)}，"
                                  "只过了 3 天（阈值 14 天）",
                                  3, since, "maintainer", False))

    def test_marks_a_ticket_past_the_threshold(self):
        since = NOW - timedelta(days=20)
        self.check(ticket(comments=[said("maintainer", ago(days=20))]),
                   stale.Decision(1, "票 1", stale.MARK,
                                  f"末评由 maintainer 发在 {stale.stamp(since)}，已 20 天",
                                  20, since, "maintainer", False))

    def test_a_missing_title_becomes_empty(self):
        issue = ticket()
        del issue["title"]
        self.assertEqual(stale.decide(issue, NOW).title, "")


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

    def test_a_days_value_before_dry_run_survives(self):
        # 后出现的开关整份覆盖 Options：`--dry-run` 丢掉 days 的那版在这个顺序下才看得见。
        self.assertEqual(stale.parse_args(["--days", "12", "--dry-run"]),
                         stale.Options(dry_run=True, days=12))

    def test_one_day_is_a_valid_threshold(self):
        self.assertEqual(stale.parse_args(["--days", "1"]), stale.Options(dry_run=False, days=1))

    def test_bad_values_say_what_is_wrong_and_keep_the_usage(self):
        for argv, fragment in ((["--days"], "--days 后面要跟天数"),
                               (["--days", "x"], "--days 要是正整数，收到 x"),
                               (["--nope"], "不认识的参数 --nope")):
            with self.subTest(argv=argv):
                with self.assertRaises(ValueError) as caught:
                    stale.parse_args(argv)
                self.assertIn(fragment, str(caught.exception))
                self.assertIn(stale.USAGE, str(caught.exception))


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
        self.assertEqual(out.splitlines()[0],
                         f"needs-info 2 张，阈值 14 天，判定时刻 {stale.stamp(NOW)}")
        self.assertEqual(out.splitlines()[-1], "--dry-run：只算不写，没有改动任何票。")
        calls = [(call.script, call.args) for call in self.runner.run_calls]
        self.assertEqual(calls, [("gh", ("issue", "list", "--state", "open", "--label", "needs-info",
                                         "--limit", "1000", "--json", stale.FIELDS))])

    def test_without_an_injected_clock_it_reads_the_real_one(self):
        # `now` 省略时只有一处取时钟：`now or datetime.now(...)` 塌成 `and` 会把它变成真实时间戳之外的类型。
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = stale.main(["--dry-run"], runner=self.runner.run)
        self.assertEqual((code, err.getvalue()), (stale.EXIT_OK, ""))
        self.assertEqual(out.getvalue().splitlines()[-1], "--dry-run：只算不写，没有改动任何票。")

    def test_the_days_threshold_reaches_the_scan(self):
        # 13 天：默认阈值 14 判不动，`--days 12` 判加标；`scan(issues, now)` 丢掉 days 就回到 14。
        self.payload = [ticket(number=7, comments=[said("maintainer", ago(days=13))])]
        code, out, _ = self.run_main(["--dry-run", "--days", "12"])
        self.assertEqual(code, stale.EXIT_OK)
        self.assertIn("加标 1", out)

    def test_gh_failure_is_reported(self):
        code, out, err = self.run_main(["--dry-run"], rc_reply=1)
        self.assertEqual((code, out), (stale.EXIT_GH, ""))
        self.assertEqual(err.strip(), "`gh issue list` 退出码非零：boom")

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
        self.should_fail = lambda args: False    # 哪些写入返回非零
        self.runner = fixtures.FakeRunner(runs=self.reply)

    def reply(self, script, *args):
        assert script == "gh", f"只该调 gh，收到 {script}"
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues), "", 0
        self.writes.append(args)
        if self.should_fail(args):
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
        self.assertIn("  #7  加标+评论", out)

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
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_OK)
        self.assertEqual(self.writes, [("issue", "edit", "7", "--remove-label", "stale")])
        self.assertIn("  #7  摘标", out)

    def test_label_failure_skips_the_comment_and_exits_write(self):
        self.should_fail = lambda args: "--add-label" in args
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_WRITE)
        self.assertEqual(self.writes, [("issue", "edit", "7", "--add-label", "stale")])
        self.assertIn("失败 1", out)
        self.assertIn("boom", out)

    def test_comment_failure_rolls_the_label_back_so_the_next_scan_retries(self):
        self.should_fail = lambda args: args[:2] == ("issue", "comment")
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_WRITE)
        self.assertEqual(len(self.writes), 3, self.writes)
        self.assertEqual(self.writes[0], ("issue", "edit", "7", "--add-label", "stale"))
        self.assertEqual(self.writes[1][:4], ("issue", "comment", "7", "--body"))
        self.assertEqual(self.writes[2], ("issue", "edit", "7", "--remove-label", "stale"))
        self.assertIn("失败 1", out)
        # 标签退回了：下一次扫描仍判成该加，补写一条评论，而不是永远停在「有标没说明」
        self.should_fail = lambda args: False
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
        self.should_fail = lambda args: args[2] == "7"
        code, out, _ = self.run_main()
        self.assertEqual(code, stale.EXIT_WRITE)
        self.assertIn("写入 1", out)
        self.assertIn("失败 1", out)
        self.assertEqual([call[2] for call in self.writes], ["7", "8", "8"])


class RenderTests(unittest.TestCase):
    """整段文本对拍：计数、分隔符、「不动 / 跳过」尾行都在同一句里（#1520）。"""

    def report(self):
        mark = stale.Decision(2, "票 2", stale.MARK, "理由一", 20)
        unmark = stale.Decision(3, "票 3", stale.UNMARK, "理由二", 1)
        skips = (stale.Decision(4, "票 4", stale.SKIP, "理由三"),
                 stale.Decision(5, "票 5", stale.SKIP, "理由四"))
        keep = stale.Decision(6, "票 6", stale.KEEP, "留着")
        return stale.Report(mark=(mark,), unmark=(unmark,), decided=(mark, unmark, *skips, keep))

    def test_the_whole_text_is_pinned(self):
        self.assertEqual(stale.render(self.report(), NOW, 14), "\n".join([
            f"needs-info 5 张，阈值 14 天，判定时刻 {stale.stamp(NOW)}",
            "加标 1：",
            "  #2  票 2（理由一）",
            "摘标 1：",
            "  #3  票 3（理由二）",
            "不动 1；跳过 2（理由三、理由四）",
        ]))

    def test_no_skips_leaves_no_parenthesised_suffix(self):
        report = stale.Report(mark=(), unmark=(),
                              decided=(stale.Decision(6, "票 6", stale.KEEP, "留着"),))
        self.assertEqual(stale.render(report, NOW, 14).splitlines()[-1], "不动 1；跳过 0")

    def test_render_writes_lists_failures_after_successes(self):
        self.assertEqual(stale.render_writes([(7, "加标+评论")], [(8, "boom")]),
                         "\n".join(["写入 1：", "  #7  加标+评论", "失败 1：", "  #8  boom"]))


class CommentBodyTests(unittest.TestCase):
    def test_a_ticket_with_an_earlier_reply_says_how_long(self):
        decision = stale.Decision(1, "票 1", stale.MARK, "", 20, None, "maintainer")
        self.assertEqual(stale.comment_body(decision), "\n\n".join(["距上一次回复已 20 天。",
                                                                    stale.REPLY_HINT]))

    def test_a_ticket_without_any_reply_says_so(self):
        decision = stale.Decision(1, "票 1", stale.MARK, "", 20)
        self.assertEqual(stale.comment_body(decision), "\n\n".join(["本票创建已 20 天，还没有收到过回复。",
                                                                    stale.REPLY_HINT]))


class LabelWriteTests(unittest.TestCase):
    """标签与评论两条写命令的实参和失败文案（#1520）。"""

    def run_gh(self, result, calls):
        def run(script, *args):
            calls.append((script, *args))
            return result
        return run

    def test_set_labels_puts_add_and_remove_in_one_edit(self):
        calls = []
        self.assertIsNone(stale.set_labels(7, self.run_gh(("", "", 0), calls),
                                           ["stale"], ["needs-info"]))
        self.assertEqual(calls, [("gh", "issue", "edit", "7",
                                  "--add-label", "stale", "--remove-label", "needs-info")])

    def test_set_labels_with_nothing_to_do_makes_no_call(self):
        calls = []
        self.assertIsNone(stale.set_labels(7, self.run_gh(("", "", 0), calls), [], []))
        self.assertEqual(calls, [])

    def test_set_labels_failure_carries_the_text(self):
        self.assertEqual(stale.set_labels(7, self.run_gh(("", "boom", 1), []), ["stale"], []),
                         "改标签失败：boom")

    def test_set_labels_failure_without_text_uses_the_fallback(self):
        self.assertEqual(stale.set_labels(7, self.run_gh(("", "", 1), []), ["stale"], []),
                         "改标签失败：gh 返回非零")

    def test_post_comment_sends_the_body(self):
        calls = []
        self.assertIsNone(stale.post_comment(7, "正文", self.run_gh(("", "", 0), calls)))
        self.assertEqual(calls, [("gh", "issue", "comment", "7", "--body", "正文")])

    def test_post_comment_failure_carries_the_text(self):
        self.assertEqual(stale.post_comment(7, "正文", self.run_gh(("", "boom", 1), [])),
                         "写评论失败：boom")

    def test_post_comment_failure_without_text_uses_the_fallback(self):
        self.assertEqual(stale.post_comment(7, "正文", self.run_gh(("", "", 1), [])),
                         "写评论失败：gh 返回非零")


class TopUpUnitTests(unittest.TestCase):
    def test_top_up_replaces_only_the_comments(self):
        issue = ticket(number=7, comments=())
        reply = lambda script, *args: (json.dumps({"comments": [said(REPORTER, ago(days=1))]}), "", 0)
        self.assertEqual(stale.top_up(issue, reply),
                         dict(issue, comments=[said(REPORTER, ago(days=1))]))

    def test_top_up_failure_names_the_ticket(self):
        with self.assertRaises(stale.GhError) as caught:
            stale.top_up(ticket(number=7), lambda script, *args: ("", "boom", 1))
        self.assertEqual(str(caught.exception), "`gh issue view 7` 退出码非零：boom")

    def test_a_non_list_payload_is_a_gh_error(self):
        with self.assertRaises(stale.GhError) as caught:
            stale.read_open(lambda script, *args: ("{}", "", 0))
        self.assertEqual(str(caught.exception), "`gh issue list` 的输出不是票的列表")


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
