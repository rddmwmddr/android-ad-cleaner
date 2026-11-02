"""`plan_switches()` 的策略面：这一页该拨哪些开关，与点击循环无关。

守的是 `off()` 原先的目标选择与屏幕带过滤；点击节奏、回读重试、离页与记账
在 `tests/test_phone_interface.py` 的驱动层用例里。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import fast


class TargetSelectionTests(unittest.TestCase):
    def test_only_drops_rows_not_named(self):
        plan = fast.plan_switches([("广告推荐", True, (500, 800)),
                                   ("运营任务", True, (500, 1200))],
                                  only=["运营任务"], screen_h=2340)
        self.assertEqual(plan.targets, (("运营任务", (500, 1200), False),))
        self.assertEqual(plan.checked, frozenset({"运营任务"}))

    def test_only_still_opens_track_protection(self):
        plan = fast.plan_switches([("限制广告跟踪", False, (500, 800))],
                                  only=["运营任务"], screen_h=2340)
        self.assertEqual(plan.targets, (("限制广告跟踪", (500, 800), True),))

    def test_only_does_not_open_unnamed_protection_without_a_track_word(self):
        plan = fast.plan_switches([("关闭个性化推荐", False, (500, 800))],
                                  only=["运营任务"], screen_h=2340)
        self.assertEqual(plan.targets, ())
        self.assertEqual(plan.checked, frozenset())

    def test_keep_protects_a_switch_that_should_be_closed(self):
        plan = fast.plan_switches([("个性化推荐", True, (500, 800))],
                                  keep=["推荐"], screen_h=2340)
        self.assertEqual(plan.targets, ())
        self.assertEqual(plan.checked, frozenset())

    def test_keep_wins_over_only(self):
        plan = fast.plan_switches([("个性化推荐", True, (500, 800))],
                                  keep=["推荐"], only=["个性化推荐"], screen_h=2340)
        self.assertEqual(plan.targets, ())

    def test_a_switch_without_ad_words_is_not_touched_at_all(self):
        plan = fast.plan_switches([("关闭推送", True, (500, 800))], screen_h=2340)
        self.assertEqual(plan.targets, ())
        self.assertEqual((plan.checked, plan.kept), (frozenset(), frozenset()))

    def test_rows_without_a_title_are_dropped(self):
        plan = fast.plan_switches([("", True, (500, 800))], screen_h=2340)
        self.assertEqual(plan.targets, ())
        self.assertEqual((plan.checked, plan.kept), (frozenset(), frozenset()))

    def test_rows_already_at_the_target_state_are_checked_but_not_clicked(self):
        plan = fast.plan_switches([("个性化推荐", False, (500, 800)),
                                   ("限制广告跟踪", True, (500, 1200))], screen_h=2340)
        self.assertEqual(plan.targets, ())
        self.assertEqual(plan.checked, frozenset({"个性化推荐", "限制广告跟踪"}))

    def test_target_order_follows_the_rows(self):
        plan = fast.plan_switches([("猜你喜欢", True, (500, 800)),
                                   ("个性化推荐", True, (500, 1200))], screen_h=2340)
        self.assertEqual([t for t, _, _ in plan.targets], ["猜你喜欢", "个性化推荐"])


class SafeModeTests(unittest.TestCase):
    def test_safe_mode_keeps_unnamed_normal_switches_untouched(self):
        plan = fast.plan_switches([("个性化推荐", True, (500, 800)),
                                   ("限制广告跟踪", False, (500, 1200))],
                                  safe_mode=True, screen_h=2340)
        self.assertEqual(plan.kept, frozenset({"个性化推荐"}))
        self.assertEqual(plan.targets, (("限制广告跟踪", (500, 1200), True),))
        self.assertEqual(plan.checked, frozenset({"限制广告跟踪"}))

    def test_safe_mode_with_only_follows_the_named_list(self):
        plan = fast.plan_switches([("个性化推荐", True, (500, 800)),
                                   ("运营任务", True, (500, 1200))],
                                  only=["运营任务"], safe_mode=True, screen_h=2340)
        self.assertEqual(plan.kept, frozenset())
        self.assertEqual(plan.targets, (("运营任务", (500, 1200), False),))


class DisabledRowTests(unittest.TestCase):
    """被上级开关禁用的行（#333）：开关是灰的，点了也不会变，不进 targets。"""

    def test_a_greyed_row_is_checked_but_not_a_target(self):
        plan = fast.plan_switches([("摇一摇广告", True, (500, 800))], screen_h=2340,
                                  disabled=lambda xy: xy == (500, 800))
        self.assertEqual(plan.targets, ())
        self.assertEqual(plan.disabled, frozenset({"摇一摇广告"}))
        self.assertEqual(plan.checked, frozenset({"摇一摇广告"}))   # 读过这一行，不算「未找到目标开关」

    def test_a_row_already_at_the_target_state_is_not_reported_as_greyed(self):
        plan = fast.plan_switches([("摇一摇广告", False, (500, 800))], screen_h=2340,
                                  disabled=lambda xy: True)
        self.assertEqual((plan.targets, plan.disabled), ((), frozenset()))

    def test_rows_outside_the_vertical_band_are_not_reported_as_greyed(self):
        plan = fast.plan_switches([("顶部广告", True, (500, 150))], screen_h=2000,
                                  disabled=lambda xy: True)
        self.assertEqual((plan.targets, plan.disabled), ((), frozenset()))

    def test_without_the_predicate_nothing_is_marked_greyed(self):
        plan = fast.plan_switches([("摇一摇广告", True, (500, 800))], screen_h=2340)
        self.assertEqual(plan.targets, (("摇一摇广告", (500, 800), False),))
        self.assertEqual(plan.disabled, frozenset())


class ScreenBandTests(unittest.TestCase):
    def test_rows_outside_the_vertical_band_are_checked_but_not_clicked(self):
        plan = fast.plan_switches([("顶部广告", True, (500, 150)),
                                   ("底部广告", True, (500, 1990)),
                                   ("屏幕内广告", True, (500, 1000))], screen_h=2000)
        self.assertEqual([t for t, _, _ in plan.targets], ["屏幕内广告"])
        self.assertEqual(plan.checked, frozenset({"顶部广告", "底部广告", "屏幕内广告"}))

    def test_the_same_row_moves_out_of_band_on_a_taller_screen(self):
        row = [("广告推荐", True, (500, 200))]
        short = fast.plan_switches(row, screen_h=1600)     # 0.08×1600 = 128，200 在带内
        tall = fast.plan_switches(row, screen_h=4000)      # 0.08×4000 = 320，200 在带外
        self.assertEqual([t for t, _, _ in short.targets], ["广告推荐"])
        self.assertEqual([t for t, _, _ in tall.targets], [])

    def test_the_band_constants_are_pinned_near_both_edges(self):
        # 170 在 0.08H=160 与 0.09H=180 之间；1900 在 0.90H=1800 与 0.985H=1970 之间。
        plan = fast.plan_switches([("上边缘", True, (500, 170)),
                                   ("下边缘", True, (500, 1900))], screen_h=2000)
        self.assertEqual([t for t, _, _ in plan.targets], ["上边缘", "下边缘"])


if __name__ == "__main__":
    unittest.main()
