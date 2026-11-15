"""PYB110 机型脚本的商店段：「消息管理」是条件入口，缺了也不挡后面两条子路径（#1281）。

入口在首启时出现过、之后读不到，脚本保留可选探测；快照里这段停在 `in_settings_page`
（合成空页），所以两条分支只能靠这里守。段 action 的取法沿用 #1265。

同一份文件的游戏中心段：首次运行（广告全开）时开屏浮层更长，底栏点击被吞掉后 `p.tap`
照样返回成功，整段就停在推荐流首页上找「设置」（#1235）。`Phone.enter` 转发给真的
`Navigator`，动作原语与观测基座按需换成桩。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from fixtures import Clock, clocked, load_recipe, phone_mock, phone_stub  # noqa: E402

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
            call(keep=self.scope["STORE_KEEP"], page="商店·服务管理"),
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
