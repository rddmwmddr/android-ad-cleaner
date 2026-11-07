"""渠道批处理：一项的结局是值，怎么记账由一张表决定。不用手机。

结局集覆盖 toggle() 的每个出口与 run() 的预筛；判据表是纯函数，直接测。
数组从 chan.RULES 取，新增一个结局不会因为漏加而静默通过。
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan


def outcome(kind, detail=""):
    return chan.Outcome(kind, detail)


class OutcomeTableTests(unittest.TestCase):
    def test_channel_missing_counts_as_a_failure_in_both_directions(self):
        for want_on in (False, True):
            self.assertTrue(chan.failed(outcome(chan.NO_CHANNEL), want_on))

    def test_deleted_or_app_off_only_counts_when_restoring(self):
        for kind in (chan.DELETED, chan.APP_OFF):
            self.assertFalse(chan.failed(outcome(kind), False))
            self.assertTrue(chan.failed(outcome(kind), True))

    def test_reached_states_are_not_failures(self):
        for kind in (chan.DONE, chan.ALREADY, chan.GREYED, chan.APP_DENIED, chan.PROTECTED,
                     chan.CONFIRMED_LATER):
            self.assertFalse(chan.failed(outcome(kind), False))

    def test_outcomes_that_need_a_human_are_failures(self):
        for kind in (chan.NOT_CONFIRMED, chan.MISMATCH, chan.UNCHANGED, chan.ERROR):
            self.assertTrue(chan.failed(outcome(kind), False))

    def test_only_not_confirmed_and_unchanged_are_retried(self):
        self.assertEqual({k for k in chan.KINDS if chan.retryable(outcome(k))},
                         {chan.NOT_CONFIRMED, chan.UNCHANGED})

    def test_only_done_and_confirmed_later_count_as_toggled(self):
        self.assertEqual({k for k in chan.KINDS if chan.toggled(outcome(k))},
                         {chan.DONE, chan.CONFIRMED_LATER})

    def test_channels_that_cannot_be_closed_are_exempt_from_the_recheck(self):
        self.assertEqual({k for k in chan.KINDS if chan.exempt_from_recheck(outcome(k))},
                         {chan.GREYED, chan.APP_DENIED, chan.UI_HIDDEN})


class RenderTests(unittest.TestCase):
    def test_done_prints_the_verb_then_the_label(self):
        self.assertEqual(chan.render(outcome(chan.DONE), "营销通知", False), "  关  营销通知")
        self.assertEqual(chan.render(outcome(chan.DONE), "营销通知", True), "  开  营销通知")

    def test_only_already_and_confirmed_later_are_silent(self):
        silent = {k for k in chan.KINDS if chan.render(outcome(k), "营销通知", False) is None}
        self.assertEqual(silent, {chan.ALREADY, chan.CONFIRMED_LATER})

    def test_every_kind_renders_a_line(self):
        for kind in chan.KINDS:
            with self.subTest(kind=kind):
                line = chan.render(outcome(kind, "说明"), "营销通知", False)
                self.assertTrue(line is None or line.startswith("  "))

    def test_locked_and_app_denied_say_they_are_not_failures(self):
        self.assertIn("不算失败", chan.render(outcome(chan.GREYED), "营销通知", False))
        self.assertIn("不算失败", chan.render(outcome(chan.APP_DENIED), "营销通知", False))

    def test_protected_shows_the_current_state(self):
        self.assertEqual(chan.render(outcome(chan.PROTECTED, "当前状态 off"), "找机位通知", False),
                         "  · 受保护，未改动 找机位通知（找机位功能通知，当前状态 off）")

    def test_unoperated_kinds_share_one_line(self):
        for kind in (chan.NO_CHANNEL, chan.DELETED, chan.APP_OFF):
            self.assertEqual(chan.render(outcome(kind), "营销通知", False),
                             "  · 未操作 营销通知（渠道不存在、已删除或应用通知已关闭）")

    def test_failures_print_the_detail_after_a_cross(self):
        line = chan.render(outcome(chan.MISMATCH, "界面状态与渠道实际状态不一致，未继续点击"), "营销通知", False)
        self.assertEqual(line, "  ✗ 界面状态与渠道实际状态不一致，未继续点击  营销通知")


class ToggleTests(unittest.TestCase):
    """toggle() 的出口：设备侧那三种「没得可关」必须分开，因为记账口径不同。"""

    def outcome_for(self, parsed):
        p = Mock()
        p.locked.return_value = False
        with patch.object(chan, "parse", return_value=parsed):
            return chan.toggle(p, "com.x", "promo", False, "营销通知")

    def test_missing_deleted_and_app_off_are_distinct_outcomes(self):
        cases = {
            chan.NO_CHANNEL: ({}, {}),
            chan.DELETED: ({("com.x", "promo"): ("营销通知", 3, True)}, {}),
            chan.APP_OFF: ({("com.x", "promo"): ("营销通知", 3, False)}, {"com.x": True}),
        }
        for kind, parsed in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.outcome_for(parsed).kind, kind)


ITEMS = [("com.a", "promo", "营销通知")]


def read(on=True, deleted=False):
    return ({("com.a", "promo"): ("营销通知", 3 if on else 0, deleted)}, {})


class BatchTests(unittest.TestCase):
    def run_chan(self, cmd, reads, outcomes):
        phone = Mock(wait_unlocked=Mock(return_value=True))
        with patch.object(chan, "load", return_value=ITEMS), \
             patch.object(chan, "parse", side_effect=reads), \
             patch.object(chan, "Phone", return_value=phone), \
             patch.object(chan, "keep_awake", return_value=None), \
             patch.object(chan, "toggle", side_effect=outcomes) as toggled, \
             patch.object(chan, "pause_point"), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "t", cmd, "x.tsv"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                chan.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), toggled

    def test_channel_confirmed_on_the_retry_counts_as_changed_and_is_not_retried_again(self):
        code, out, toggled = self.run_chan("off", [read(True), read(False), read(False)],
                                           [outcome(chan.UNCHANGED, "点击后渠道状态未改变")])
        self.assertEqual(code, 0)
        self.assertEqual(toggled.call_count, 1)     # 第二遍只重试还没改好的那个
        self.assertIn("拨了 1 个", out)
        self.assertIn("营销渠道仍开着: 0 个", out)

    def test_channel_still_unchanged_after_the_retry_fails_the_step(self):
        code, out, _ = self.run_chan("off", [read(True), read(True), read(True)],
                                     [outcome(chan.UNCHANGED, "点击后渠道状态未改变")] * 2)
        self.assertEqual(code, 1)
        self.assertIn("拨了 0 个", out)              # 失败项不算「拨了」
        self.assertIn("仍开着：营销通知（com.a）", out)

    def test_mismatch_is_not_retried(self):
        code, out, toggled = self.run_chan("off", [read(True), read(True)],
                                           [outcome(chan.MISMATCH, "界面状态与渠道实际状态不一致，未继续点击")])
        self.assertEqual(code, 1)
        self.assertEqual(toggled.call_count, 1)
        self.assertNotIn("再试一次", out)

    def test_locked_channel_is_printed_but_not_counted(self):
        code, out, _ = self.run_chan("off", [read(True), read(True)], [outcome(chan.GREYED)])
        self.assertEqual(code, 0)
        self.assertIn("系统锁定（开关是灰的），不能关闭，不算失败  营销通知", out)

    def test_deleted_channel_does_not_fail_a_close_run(self):
        code, out, toggled = self.run_chan("off", [read(True, True), read(True, True)], [])
        self.assertEqual(code, 0)
        self.assertIn("未操作 营销通知（渠道不存在、已删除或应用通知已关闭）", out)
        toggled.assert_not_called()

    def test_deleted_channel_fails_a_restore_run(self):
        code, out, _ = self.run_chan("on", [read(True, True), read(True, True)], [])
        self.assertEqual(code, 1)
        self.assertIn("未恢复的渠道: 1 个", out)

    def test_channel_already_closed_is_silent_and_untouched(self):
        code, out, toggled = self.run_chan("off", [read(False), read(False)], [])
        self.assertEqual(code, 0)
        self.assertNotIn("  关  ", out)
        toggled.assert_not_called()
