"""荣耀 PNM-AN10 参考脚本：主题与音乐两段的入口导航（#238）。

假页面只断言「点了哪个节点、落点验过没有、失败时有没有乱点」，不断言打印的中文文案。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import adb_link
import fast
from fixtures import load_recipe, phone_mock, phone_stub

RECIPE = ROOT / "recipes/honor-PNM-AN10/recipe.py"


def load(phone, only=("__no_steps__",)):
    scope, _ = load_recipe(phone, RECIPE, only)
    return scope


def phone():
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.dismiss.return_value = None
    p.sig.return_value = "page"
    return p


def has(*words):
    """find 的替身：这些词在页面上，其余没有。"""
    return lambda text, exact=False, **kw: (1, 1) if text in words else None


class HonorSettingsEntryTests(unittest.TestCase):
    def test_exact_text_hit_stops_at_the_first_level(self):
        """PNM-AN10 上「设置」是纯文字：第一级就命中，不点图标、不退回（旧机型不回归）。"""
        p = phone()
        p.find.side_effect = has("设置", "个性化服务", "通知")
        p.tap.return_value = True
        scope = load(p)
        self.assertTrue(scope["open_settings"]())
        p.tap.assert_called_once_with("设置", exact=True, scrolls=0)
        p.tap_icon.assert_not_called()
        p.back.assert_not_called()

    def test_page_that_did_not_change_is_not_backed_out_of(self):
        """点「设置」没反应、还停在「我的」页：不能退，退了会离开「我的」页再重试（#238）。"""
        p = phone()
        p.find.side_effect = lambda text, exact=False, **kw: (1, 1) if text == "设置" and exact else None
        p.tap.return_value = False
        p.sig.return_value = "mine"
        p.tap_icon.return_value = False
        scope = load(p)
        self.assertFalse(scope["open_settings"]())
        p.back.assert_not_called()

    def test_notification_badge_falls_back_to_contains_match(self):
        """MagicOS 10 的主题「设置」读作「设置,有1条新通知」：精确落空，包含匹配进去并验落点（#286）。"""
        p = phone()
        p.find.side_effect = lambda text, exact=False, **kw: (
            (1, 1) if text == "设置" and not exact
            else ((2, 2) if text in ("个性化服务", "通知") and exact else None))
        p.tap.return_value = True
        scope = load(p)
        self.assertTrue(scope["open_settings"]())
        p.tap.assert_called_once_with("设置", exact=False, scrolls=0)
        p.tap_icon.assert_not_called()
        p.back.assert_not_called()

    def test_icon_is_the_last_resort_when_no_text_matches(self):
        p = phone()
        p.find.side_effect = has("个性化服务", "通知")
        p.tap_icon.return_value = True
        scope = load(p)
        self.assertTrue(scope["open_settings"]())
        p.tap_icon.assert_called_once_with(["个性化服务", "通知"])
        p.tap.assert_not_called()

    def test_wrong_landing_page_is_left_before_trying_the_icon(self):
        """文字点进去不是设置页：先退回来再试右上角图标，不能留在错页上找入口（#286）。"""
        p = phone()
        p.find.side_effect = lambda text, exact=False, **kw: (1, 1) if text == "设置" and exact else None
        p.tap.return_value = True
        p.sig.side_effect = ["mine", "other", "mine"]
        p.tap_icon.return_value = True
        scope = load(p)
        self.assertTrue(scope["open_settings"]())
        p.back.assert_called_once()
        p.tap_icon.assert_called_once_with(["个性化服务", "通知"])


def tab_phone(*nodes):
    """真 tab()，其余方法都换成替身：底栏匹配要按引擎的实际读法判定。"""
    p = phone_stub("test", W=1080, H=2400)
    p.tree = Mock(return_value=fast.ET.fromstring(
        '<hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>"))
    p.click, p.say = Mock(), Mock()
    p.dismiss = Mock(return_value=None)
    p.sig = Mock(return_value="page")
    p.settle = Mock(return_value=True)
    p.locked = Mock(return_value=False)
    p.start, p.enter, p.off, p.back = Mock(), Mock(), Mock(), Mock()
    p.tap = Mock(return_value=True)
    p.tap_icon = Mock(return_value=True)
    p.find = Mock(side_effect=has("设置", "个性化服务", "通知"))
    return p


class HonorThemeTests(unittest.TestCase):
    def test_bottom_tab_that_matches_is_not_repeated_with_a_plain_tap(self):
        p = phone()
        p.tab.return_value = True
        p.find.side_effect = has("设置", "个性化服务", "通知")
        p.tap.return_value = True
        load(p, ["主题"])
        p.tab.assert_called_once_with("我的")
        p.tap.assert_called_once_with("设置", exact=True, scrolls=0)

    def test_bottom_tab_read_as_unselected_is_clicked_by_the_engine(self):
        """主题 App 底栏读作「未选中,我的」：由 tab() 的逗号末段递进接住，不回退全屏点法。"""
        p = tab_phone(
            '<node class="android.widget.TextView" text="我的" bounds="[0,300][1080,360]"/>',
            '<node class="android.widget.TextView" content-desc="未选中,我的" bounds="[0,2200][216,2300]"/>')
        p.find.side_effect = has("设置", "个性化服务", "通知")
        p.tap.return_value = True
        load(p, ["主题"])
        p.click.assert_called_once_with(108, 2250)          # 底栏那个标签，不是内容区的同名文字
        p.tap.assert_called_once_with("设置", exact=True, scrolls=0)

    def test_missing_bottom_tab_falls_back_to_the_plain_exact_tap(self):
        """底栏不在屏幕最下方 15% 的机型：tab() 找不到就退回原来的全屏精确点击（#238 补充）。"""
        p = phone()
        p.tab.return_value = False
        p.find.side_effect = has("设置", "个性化服务", "通知")
        p.tap.return_value = True
        load(p, ["主题"])
        p.tab.assert_called_once_with("我的")
        self.assertEqual(p.tap.call_args_list[0].args, ("我的",))
        self.assertEqual(p.tap.call_args_list[0].kwargs, {"exact": True, "scrolls": 0})
        self.assertEqual([c.args[0] for c in p.enter.call_args_list], ["通知", "个性化服务"])

    def test_missing_settings_entry_skips_the_section_without_touching_switches(self):
        p = phone()
        p.tab.return_value = False
        p.find.return_value = None
        p.tap.return_value = False
        p.tap_icon.return_value = False
        load(p, ["主题"])
        self.assertEqual(p.tap.call_args_list[0].args, ("我的",))   # 回退确实发生了
        p.note_miss.assert_called_once_with("设置")
        p.off.assert_not_called()
        p.enter.assert_not_called()

    def test_theme_entries_are_opened_with_page_change_confirmation(self):
        p = phone()
        p.find.side_effect = has("设置", "个性化服务", "通知")
        p.tap.return_value = True
        load(p, ["主题"])
        self.assertEqual([c.args[0] for c in p.enter.call_args_list], ["通知", "个性化服务"])
        self.assertEqual([c.kwargs.get("page") for c in p.off.call_args_list],
                         ["主题·通知", "主题·个性化服务"])


class HonorMusicTests(unittest.TestCase):
    def music_phone(self):
        p = phone()
        p.d = MagicMock()          # resourceId(...)[2].click() 要能下标
        return p

    def test_music_entries_are_opened_with_page_change_confirmation(self):
        p = self.music_phone()
        load(p, ["音乐"])
        self.assertEqual([c.args[0] for c in p.enter.call_args_list],
                         ["更多设置", "消息和隐私设置", "第三方推送服务开关"])
        # 抽屉本身不翻（会误点扫一扫）；抽屉里的两个子页入口要滚到中部才看得见（#88）
        self.assertEqual([c.kwargs.get("scrolls", 0) for c in p.enter.call_args_list], [0, 6, 6])
        self.assertEqual([c.kwargs.get("only") for c in p.off.call_args_list], [["朋友页显示推荐动态"], None])
        self.assertEqual([c.kwargs.get("page") for c in p.off.call_args_list],
                         ["音乐·消息和隐私", "音乐·第三方推送（活动、中奖信息）"])

    def test_missing_privacy_menu_skips_the_section_without_blind_scrolling(self):
        """「更多设置」页里没有该菜单时：留下停在哪一页就跳过，脚本自己不另起一套盲点。"""
        p = self.music_phone()
        p.enter.side_effect = [None, RuntimeError("未找到入口「消息和隐私设置」；当前页：设置")]
        load(p, ["音乐"])
        p.note_miss.assert_called_once_with("消息和隐私设置")
        p.off.assert_not_called()
        p.tap.assert_not_called()

    def test_lost_connection_is_not_reported_as_a_missing_entry(self):
        """断线 / 锁屏要照常上抛：它们不能记成「入口改名」，否则排查方向是错的（WKL 同款守卫）。"""
        for error in (adb_link.DeviceLost("lost"), fast.ScreenLocked("locked")):
            with self.subTest(error=type(error).__name__):
                p = phone()
                p.enter.side_effect = error
                scope = load(p)
                with self.assertRaises(type(error)):
                    scope["open_entry"]("更多设置")
                p.note_miss.assert_not_called()

    def test_missing_third_party_entry_stops_before_the_second_page(self):
        p = self.music_phone()
        p.enter.side_effect = [None, None, RuntimeError("点「第三方推送服务开关」后页面没有变化")]
        load(p, ["音乐"])
        p.note_miss.assert_called_once_with("第三方推送服务开关")
        self.assertEqual(len(p.off.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
