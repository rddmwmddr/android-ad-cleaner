"""PYB110 机型脚本的商店段：「消息管理」是条件入口，缺了也不挡后面两条子路径（#1281）。

入口在首启时出现过、之后读不到，脚本保留可选探测；快照里这段停在 `in_settings_page`
（合成空页），所以两条分支只能靠这里守。段 action 的取法沿用 #1265。

同一份文件的游戏中心段：首次运行（广告全开）时开屏浮层更长，底栏点击被吞掉后 `p.tap`
照样返回成功，整段就停在推荐流首页上找「设置」（#1235）。`Phone.enter` 转发给真的
`Navigator`，动作原语与观测基座按需换成桩。

负一屏段转成数据之后（#1369）：快照停在「右滑没进速览」那一条出口，进得去之后的两条子路径与
「我的」入口缺失只能靠这里守；右滑入口本身收在家族库 `assistant_swipe_in`，两档判据各一条。
这些用例在转数据前的那棵树上也绿——守的是「收进数据与家族库之后行为没有回退」。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from fixtures import Clock, clocked, keep_list, load_recipe, phone_mock, phone_stub  # noqa: E402

RECIPE = ROOT / "recipes/oppo/PYB110/PYB110.toml"
# 首次运行停在推荐流首页时当次读到的页面文字，失败时要原样带出来。
HOME_TEXT = "HomeBannerCarousel / 斗破苍穹：异火降世 / 热门游戏精选"
# 「我的 → 设置 → 隐私开关设置」三页上认得的文字与落点：读屏一律从这里取。
SETTINGS_PAGE = {"我的": (540, 2200), "设置": (540, 800), "隐私开关设置": (540, 600)}


def action(scope, name):
    return next(item.action for item in scope["rt"].steps if item.name == name)


class StoreStepTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.in_settings_page.return_value = True
        self.scope, _ = load_recipe(self.p, RECIPE)
        self.store = action(self.scope, "软件商店")

    def test_missing_message_entry_leaves_the_two_subpaths_intact(self):
        self.p.entry.return_value = False
        self.store()
        self.assertEqual(self.p.off.call_args_list, [
            call(keep=keep_list(RECIPE, "软件商店"), page="商店·服务管理"),
            call(only=["个性化推荐"], page="商店·个性化推荐"),
        ])

    def test_present_message_entry_is_closed_before_service_management(self):
        self.p.entry.return_value = True
        self.store()
        self.assertEqual(self.p.off.call_args_list[0],
                         call(only=["热门内容推送"], page="商店·消息管理"))
        self.assertEqual(len(self.p.off.call_args_list), 3)


class GameCenterTabTests(unittest.TestCase):
    """游戏中心的两跳入口：底栏「我的」与设置页的「设置」都要确认落点（#1235）。

    `Phone.enter` 转发给真的 `Navigator`，所以「点了一次但页面没换」与「一直没换」都由引擎
    自己的判定给出；动作原语（`start` / `tap` / `tap_icon` / `dismiss` / `off` / `back`）与观测
    基座按需换成桩。
    """

    def setUp(self):
        clocked(self, fast, Clock())
        self.p = phone_stub(W=1080, H=2340)
        self.p.start = Mock()
        self.p.tap = Mock(return_value=True)
        self.p.tap_icon = Mock(return_value=True)
        self.p.off = Mock()
        self.p.back = Mock()
        self.p.dismiss = Mock(return_value=False)
        self.p.locked = Mock(return_value=False)
        self.p.screen.click = Mock()
        self.p.screen.say = Mock()
        self.p.screen.texts = Mock(return_value=[])
        self.p.screen.focus = Mock(return_value="com.nearme.gamecenter/.MainActivity")
        self.p.screen.residual_note = Mock(return_value="")
        self.p.screen.page_text = Mock(return_value=HOME_TEXT)
        self.p.screen.find = Mock(side_effect=lambda text, exact=False, **kw: SETTINGS_PAGE.get(text))
        self.p.screen.sig = Mock(return_value="home")
        self.scope, _ = load_recipe(self.p, RECIPE)
        self.game_center = action(self.scope, "游戏中心")

    def test_a_swallowed_tab_click_is_retried_before_settings_is_sought(self):
        """第一次点「我的」返回成功但页面没换：再点一次，而不是继续在推荐流上找「设置」。

        `settle` 每次点击后被读两次：`tap()` 自己等一次（不看结果），`enter()` 再判一次换没换。
        """
        self.p.screen.settle = Mock(side_effect=[True, False, True, True, True, True])
        self.game_center()
        self.assertEqual(self.p.screen.click.call_args_list[:2],
                         [call(*SETTINGS_PAGE["我的"])] * 2)
        self.p.tap.assert_any_call("隐私开关设置", exact=True)

    def test_a_tab_that_never_turns_the_page_fails_with_the_page_text(self):
        """连续不换页时整段以「点了但没换页」结束，并带上当次读到的页面文字。"""
        self.p.screen.settle = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, "页面没有变化.*HomeBannerCarousel"):
            self.game_center()
        self.assertEqual(self.p.screen.click.call_count, 3)     # tries 次重点
        self.p.tap.assert_not_called()                          # 不在推荐流上找「设置」
        self.p.tap_icon.assert_not_called()

    def test_the_page_upgrade_dialog_is_tapped_by_name(self):
        """「页面升级」弹窗带滚动列表，dismiss() 点不掉，只能点名点「我知道了」。"""
        self.p.screen.find.side_effect = lambda text, exact=False, **kw: (
            SETTINGS_PAGE.get(text) or ((540, 900) if text == "我知道了" else None))
        self.p.screen.settle = Mock(return_value=True)
        self.game_center()
        self.p.tap.assert_any_call("我知道了", exact=True, scrolls=0)
        self.p.dismiss.assert_not_called()

    def test_without_the_upgrade_dialog_the_popup_step_still_dismisses(self):
        """没有「页面升级」弹窗时照常 dismiss()，不把这一步跳过。"""
        self.p.screen.settle = Mock(return_value=True)
        self.game_center()
        self.p.dismiss.assert_called_once()
        self.assertNotIn("我知道了", [c.args[0] for c in self.p.tap.call_args_list])


class NegativeScreenTests(unittest.TestCase):
    """负一屏段收进数据之后的三条出口：右滑进不去、没有「我的」入口、两个子页都不在。

    快照停在这段的第一条判据上（合成空页右滑永远进不去），后面两条子路径只有这里走得到。
    """

    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.locked.return_value = False
        self.p.find.return_value = True          # 右滑一次就认到首页的「我的服务」
        self.p.go.return_value = True
        self.p.tap.return_value = True

    def run_segment(self):
        return load_recipe(self.p, RECIPE, ["负一屏"])

    def test_the_recommendation_switches_are_closed_under_privacy(self):
        scope, _out = self.run_segment()
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(self.p.off.call_args_list, [
            call(only=["最新服务资讯通知"], page="负一屏·消息管理"),
            call(only=["热点资讯"], page="负一屏·个性化推荐"),
        ])
        self.assertEqual([item.args for item in self.p.back.call_args_list], [(), (), (), (3,)])

    def test_a_swipe_that_never_lands_fails_the_segment(self):
        self.p.find.return_value = False
        scope, out = self.run_segment()
        self.assertEqual(scope["FAILED_STEPS"], ["负一屏"])
        self.assertIn("右滑没进速览（负一屏）", out.getvalue())
        self.p.off.assert_not_called()

    def test_a_missing_mine_entry_fails_the_segment(self):
        self.p.go.return_value = False
        scope, out = self.run_segment()
        self.assertEqual(scope["FAILED_STEPS"], ["负一屏"])
        self.assertIn("没找到「我的」入口", out.getvalue())

    def test_without_the_two_sub_pages_no_switch_is_touched(self):
        self.p.tap.return_value = False
        scope, _out = self.run_segment()
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.p.off.assert_not_called()
        self.assertEqual([item.args for item in self.p.back.call_args_list], [(3,)])


class SwipeInTests(unittest.TestCase):
    """`assistant_swipe_in` 的返回值两档判据，以及三次滑不进去就放弃。

    ColorOS 17 把速览内嵌进桌面进程（焦点停在 launcher），只能按首页文案判；ColorOS 15 是独立
    窗口，看前台窗口名就够了。两档都不能误判——进不去却返回真，后面整段会在桌面上点「我的」。
    """

    def test_the_text_mode_swipes_until_the_home_rows_show_up(self):
        import recipe_lib.oppo as oppo
        p = phone_mock(W=1080, H=2400)
        p.find.side_effect = [False, False, True]     # 第二轮读到「我的服务」
        self.assertTrue(oppo.assistant_swipe_in(p, Mock(), "我的服务", "添加卡片"))
        self.assertEqual([item.args[0] for item in p.shell.call_args_list[:2]],
                         ["input keyevent HOME"] * 2)
        self.assertEqual(len([item for item in p.shell.call_args_list
                              if "input swipe" in item.args[0]]), 2)
        p.find.assert_any_call("我的服务")             # 一条按包含比
        p.find.assert_any_call("添加卡片", exact=True)  # 一条按精确比

    def test_three_swipes_without_a_hit_give_up(self):
        import recipe_lib.oppo as oppo
        p = phone_mock(W=1080, H=2400)
        p.find.return_value = False
        self.assertFalse(oppo.assistant_swipe_in(p, Mock(), "我的服务", "添加卡片"))
        self.assertEqual(len([item for item in p.shell.call_args_list
                              if "input swipe" in item.args[0]]), 3)

    def test_without_texts_the_foreground_window_name_decides(self):
        """ColorOS 15 档：不给文案时只看前台名，一次文案比较都不做。"""
        import recipe_lib.oppo as oppo
        p = phone_mock(W=1080, H=2400)
        p.focus.side_effect = ["com.android.launcher/.Launcher",
                               "com.coloros.assistantscreen/.AssistantScreenActivity"]
        self.assertTrue(oppo.assistant_swipe_in(p, Mock()))
        self.assertEqual(len([item for item in p.shell.call_args_list
                              if "input swipe" in item.args[0]]), 2)
        p.find.assert_not_called()

    def test_a_foreground_name_that_never_matches_returns_false(self):
        """ColorOS 15 档同样有假出口：焦点一直在 launcher 时不能报「进去了」。"""
        import recipe_lib.oppo as oppo
        p = phone_mock(W=1080, H=2400)
        p.focus.return_value = "com.android.launcher/.Launcher"
        self.assertFalse(oppo.assistant_swipe_in(p, Mock()))
        p.find.assert_not_called()
