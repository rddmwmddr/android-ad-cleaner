"""`readback()` 与 `pick_retry_rows()`：一屏回读后每条目标是什么结局，以及该补点哪一行。

守的是 `off()` 原先内嵌的回读判定——同名双列（#403）、
随行消失与跳页（#486）、灰态（#333）、保护类开关的「打开」方向。
点击节奏、离页守卫与记账仍在 `tests/test_phone_interface.py` 的驱动层用例里。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import fast


def never():
    """没有消失行时不该被读：读一次就说明判定把惰性弄丢了。"""
    raise AssertionError("没有消失行时不该读前台")


def no_grey(xy):
    return False


class ReachedTests(unittest.TestCase):
    def test_a_row_at_the_target_state_is_reached(self):
        self.assertEqual(
            fast.readback([("广告推荐", (500, 800), False)],
                          [("广告推荐", False, (500, 800))],
                          clicked={"广告推荐"}, others=set(),
                          page_same=never, disabled=no_grey),
            {"广告推荐": fast.REACHED})

    def test_a_protection_switch_is_reached_when_it_reads_on(self):
        # 保护类开关的目标是「打开」：读成 True 才算到
        self.assertEqual(
            fast.readback([("限制广告跟踪", (500, 800), True)],
                          [("限制广告跟踪", True, (500, 800))],
                          clicked={"限制广告跟踪"}, others=set(),
                          page_same=never, disabled=no_grey),
            {"限制广告跟踪": fast.REACHED})


class MissedTests(unittest.TestCase):
    def test_a_row_still_in_the_wrong_state_is_missed(self):
        self.assertEqual(
            fast.readback([("广告推荐", (500, 800), False)],
                          [("广告推荐", True, (500, 800))],
                          clicked={"广告推荐"}, others=set(),
                          page_same=never, disabled=no_grey),
            {"广告推荐": fast.MISSED})

    def test_a_same_named_row_still_on_is_missed_even_if_the_other_one_is_off(self):
        """同名双列（#403）：还有一行没到目标态就算没关掉。"""
        rows = [("营销通知", False, (300, 800)), ("营销通知", True, (900, 800))]
        self.assertEqual(
            fast.readback([("营销通知", (300, 800), False)], rows,
                          clicked={"营销通知"}, others=set(),
                          page_same=never, disabled=no_grey),
            {"营销通知": fast.MISSED})

    def test_an_empty_read_is_missed_and_does_not_count_as_vanished(self):
        # 整页读空：这一页已经无法核对，不能当成关掉了（#486）
        self.assertEqual(
            fast.readback([("广告推荐", (500, 800), False)], [],
                          clicked={"广告推荐"}, others={"常驻行"},
                          page_same=never, disabled=no_grey),
            {"广告推荐": fast.MISSED})


class VanishedTests(unittest.TestCase):
    def test_a_clicked_row_that_is_gone_counts_as_closed_when_the_page_stayed(self):
        self.assertEqual(
            fast.readback([("推荐位", (500, 800), False)],
                          [("常驻行", False, (500, 1200))],
                          clicked={"推荐位"}, others={"常驻行"},
                          page_same=lambda: True, disabled=no_grey),
            {"推荐位": fast.VANISHED})

    def test_a_gone_row_on_another_page_is_not_closed(self):
        # 跳到别的页（含同 Activity 的子页）：找不到不等于关掉了
        self.assertEqual(
            fast.readback([("推荐位", (500, 800), False)],
                          [("别的开关", False, (500, 1200))],
                          clicked={"推荐位"}, others={"常驻行"},
                          page_same=lambda: False, disabled=no_grey),
            {"推荐位": fast.MISSED})

    def test_a_gone_row_with_no_surviving_neighbour_is_not_closed(self):
        self.assertEqual(
            fast.readback([("推荐位", (500, 800), False)],
                          [("全新标题", False, (500, 1200))],
                          clicked={"推荐位"}, others=set(),
                          page_same=lambda: True, disabled=no_grey),
            {"推荐位": fast.MISSED})

    def test_a_row_that_was_never_clicked_is_not_closed_when_it_goes(self):
        # 计划后被跳过、从没点过的行：消失证明不了什么，也不该为此去读前台
        self.assertEqual(
            fast.readback([("推荐位", (500, 800), False)],
                          [("常驻行", False, (500, 1200))],
                          clicked=set(), others={"常驻行"},
                          page_same=never, disabled=no_grey),
            {"推荐位": fast.MISSED})

    def test_a_protection_switch_that_goes_is_not_read_as_opened(self):
        # 保护类开关是主动打开：行消失证明不了它开了（#486 只定义了关闭方向）
        self.assertEqual(
            fast.readback([("限制广告跟踪", (500, 800), True)],
                          [("常驻行", False, (500, 1200))],
                          clicked={"限制广告跟踪"}, others={"常驻行"},
                          page_same=never, disabled=no_grey),
            {"限制广告跟踪": fast.MISSED})


class GreyedTests(unittest.TestCase):
    def test_a_missed_row_whose_switch_is_disabled_is_greyed(self):
        self.assertEqual(
            fast.readback([("摇一摇广告", (500, 800), False)],
                          [("摇一摇广告", True, (500, 800))],
                          clicked={"摇一摇广告"}, others=set(),
                          page_same=never, disabled=lambda xy: True),
            {"摇一摇广告": fast.GREYED})

    def test_one_grey_row_does_not_make_the_whole_title_greyed(self):
        # 同名双列一行灰一行正常：不能把另一行的失败也当成灰态吞掉（#333）
        rows = [("营销通知", True, (300, 800)), ("营销通知", True, (900, 800))]
        self.assertEqual(
            fast.readback([("营销通知", (300, 800), False)], rows,
                          clicked={"营销通知"}, others=set(),
                          page_same=never, disabled=lambda xy: xy == (300, 800)),
            {"营销通知": fast.MISSED})

    def test_a_row_already_at_the_target_state_is_not_greyed(self):
        self.assertEqual(
            fast.readback([("广告推荐", (500, 800), False)],
                          [("广告推荐", False, (500, 800))],
                          clicked={"广告推荐"}, others=set(),
                          page_same=never, disabled=lambda xy: True),
            {"广告推荐": fast.REACHED})

    def test_grey_is_judged_at_the_fresh_coordinates(self):
        # 页面重排过：灰态要按这一次读到的落点判，不用计划时的旧坐标
        self.assertEqual(
            fast.readback([("摇一摇广告", (500, 800), False)],
                          [("摇一摇广告", True, (620, 900))],
                          clicked={"摇一摇广告"}, others=set(),
                          page_same=never, disabled=lambda xy: xy == (620, 900)),
            {"摇一摇广告": fast.GREYED})


class RetryTests(unittest.TestCase):
    def test_the_retry_clicks_the_row_that_is_still_on(self):
        self.assertEqual(
            fast.pick_retry_rows([("广告推荐", (500, 800), False)],
                                 [("广告推荐", True, (620, 900))],
                                 still={"广告推荐"}, disabled=no_grey),
            [("广告推荐", (620, 900))])

    def test_the_retry_picks_the_open_row_of_a_same_named_pair(self):
        # 同名双列：按状态挑还开着的那行，不按标题取最后读到的那行（#403）
        rows = [("营销通知", False, (300, 800)), ("营销通知", True, (900, 800))]
        self.assertEqual(
            fast.pick_retry_rows([("营销通知", (300, 800), False)], rows,
                                 still={"营销通知"}, disabled=no_grey),
            [("营销通知", (900, 800))])

    def test_a_grey_row_is_not_retried(self):
        self.assertEqual(
            fast.pick_retry_rows([("摇一摇广告", (500, 800), False)],
                                 [("摇一摇广告", True, (500, 800))],
                                 still={"摇一摇广告"}, disabled=lambda xy: True),
            [])

    def test_a_gone_row_is_not_retried_at_the_stale_coordinate(self):
        # 节点消失后不能沿用计划坐标补点
        self.assertEqual(
            fast.pick_retry_rows([("广告推荐", (500, 800), False)],
                                 [("常驻行", False, (500, 1200))],
                                 still={"广告推荐"}, disabled=no_grey),
            [])

    def test_titles_outside_still_are_not_retried(self):
        self.assertEqual(
            fast.pick_retry_rows([("广告推荐", (500, 800), False)],
                                 [("广告推荐", True, (500, 800))],
                                 still=set(), disabled=no_grey),
            [])

    def test_two_still_on_rows_of_the_same_title_are_retried_once(self):
        rows = [("营销通知", True, (300, 800)), ("营销通知", True, (900, 800))]
        self.assertEqual(
            fast.pick_retry_rows([("营销通知", (300, 800), False)], rows,
                                 still={"营销通知"}, disabled=no_grey),
            [("营销通知", (300, 800))])

    def test_the_retry_order_follows_the_plan(self):
        targets = [("广告甲", (500, 800), False), ("广告乙", (500, 1000), False)]
        rows = [("广告乙", True, (500, 1000)), ("广告甲", True, (500, 800))]
        self.assertEqual(
            fast.pick_retry_rows(targets, rows, still={"广告甲", "广告乙"}, disabled=no_grey),
            [("广告甲", (500, 800)), ("广告乙", (500, 1000))])


if __name__ == "__main__":
    unittest.main()
