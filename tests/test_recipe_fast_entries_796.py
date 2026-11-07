"""#796：慢脚本改走直达。PNM-AN10 三段与 PLR110 下拉搜索不再靠桌面手势逐层点菜单。

守的是「入口换了」这个可观察行为：拉起的是哪个 Activity、有没有再按 HOME / 滑动、
直达不通时退回了原路径、断线不被吞成「入口改名」。真机上的落点仍要另验。
"""
import sys
import unittest
from pathlib import Path

from fixtures import load_recipe, phone_mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import adb_link
from fast import ScreenLocked

PNM = ROOT / "recipes" / "honor-PNM-AN10" / "recipe.py"
PLR = ROOT / "recipes" / "oneplus-PLR110" / "recipe.py"

HIBOARD_START = "am start -f 0x10008000 -n com.hihonor.hiboard/com.hihonor.intelligent.LauncherActivity"
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"


def phone(**over):
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.focus.return_value = ""
    p.find.return_value = None
    p.tap.return_value = True
    p.texts.return_value = []
    p.setting.return_value = True
    for key, value in over.items():
        setattr(p, key, value)
    return p


def load(p, recipe, name):
    scope, out = load_recipe(p, recipe, only=name)
    return scope, out.getvalue()


def page_texts(*labels, top=100):
    return [(label, (0, top, 100, top + 40), {}) for label in labels]


def home_presses(p):
    """按 HOME 的次数：shell 与 `d.press` 两条路都算。"""
    return ([c.args[0] for c in p.d.shell.call_args_list if "keyevent HOME" in c.args[0]]
            + [c.args[0] for c in p.d.press.call_args_list if c.args[0] == "home"])


def landing_failed(pkg, activity=None, **kw):
    """只有直达广告与隐私页这一条失败，同段后面拉智能推荐服务页照常。"""
    if activity == ".oaid.ui.AdvertisingPrivacyActivity":
        raise RuntimeError("启动后停在非预期页面")


class PnmSearchEntryTests(unittest.TestCase):
    def test_search_opens_the_search_home_directly(self):
        """直达搜索首页：「更多」在屏上时直接点，不再按 HOME 再下拉。"""
        p = phone(texts=lambda: page_texts("更多", top=int(2400 * 0.5)))
        scope, _ = load(p, PNM, "搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_called_once_with(
            "com.hihonor.search", ".feature.mainpage.presentation.page.HomeActivity", expect="更多")
        self.assertEqual(home_presses(p), [])
        p.click.assert_called_once()

    def test_missing_more_entry_fails_instead_of_finishing_quietly(self):
        """「更多」始终找不到：记成未完成，不再当成跑完。"""
        p = phone()
        scope, out = load(p, PNM, "搜索")
        self.assertEqual(scope["FAILED_STEPS"], ["搜索"])
        self.assertIn("找不到搜索框旁的「更多」", out)


class PnmNegativeScreenEntryTests(unittest.TestCase):
    def test_negative_screen_opens_the_hiboard_activity(self):
        """负一屏直达：一次 am start 就够，不再先回桌面再右滑。"""
        p = phone(find=lambda text, **kw: object() if text == "头像" else None)
        scope, _ = load(p, PNM, "负一屏")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(p.d.shell.call_args_list[0].args[0], HIBOARD_START)
        self.assertEqual(home_presses(p), [])
        self.assertEqual(len(p.d.shell.call_args_list), 1)
        p.tap.assert_any_call("头像", exact=True, scrolls=0)

    def test_negative_screen_falls_back_to_the_swipe_when_the_activity_does_not_land(self):
        """直达没落到负一屏（后台屏上进不去）：退回桌面右滑，仍找不到才算失败。"""
        p = phone()
        scope, out = load(p, PNM, "负一屏")
        self.assertEqual(scope["FAILED_STEPS"], ["负一屏"])
        self.assertIn("负一屏没打开", out)
        self.assertEqual(p.d.shell.call_args_list[0].args[0], HIBOARD_START)
        self.assertEqual(len(home_presses(p)), 1)
        self.assertTrue(any("input swipe" in c.args[0] for c in p.d.shell.call_args_list))


class PnmAdTrackingEntryTests(unittest.TestCase):
    def test_ad_tracking_opens_the_privacy_activity_directly(self):
        """直达广告与隐私页：不再先搜设置、也不点三层菜单。"""
        p = phone()
        scope, _ = load(p, PNM, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_any_call(
            "com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", expect="应用广告跟踪管理")
        p.setting.assert_not_called()

    def test_ad_tracking_falls_back_to_the_settings_search(self):
        """直达打不开（页面没导出 / 落点不对）：退回设置搜索，不让整段失败。"""
        p = phone()
        p.start.side_effect = landing_failed
        scope, _ = load(p, PNM, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_any_call(
            "com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", expect="应用广告跟踪管理")
        p.setting.assert_called_once_with("广告", "广告与隐私")

    def test_ad_tracking_does_not_swallow_a_lost_connection(self):
        """断线不是「这一档不通」：不许当成入口改名去走设置搜索。"""
        p = phone()
        p.start.side_effect = adb_link.DeviceLost("adb 断了")
        scope, _ = load(p, PNM, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], ["广告跟踪"])
        p.setting.assert_not_called()

    def test_ad_tracking_does_not_swallow_a_locked_screen(self):
        """锁屏同理：上抛给上层停段，不静默换入口。"""
        p = phone()
        p.start.side_effect = ScreenLocked("手机锁屏")
        scope, _ = load(p, PNM, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], ["广告跟踪"])
        p.setting.assert_not_called()


class PlrSearchEntryTests(unittest.TestCase):
    def test_pull_down_search_lands_on_the_settings_page_via_the_scheme(self):
        """PLR110：scheme 直接落到设置页，不再按 HOME、左滑躲速览、下拉、收键盘、点底部「设置」。"""
        p = phone(focus=lambda: "com.heytap.quicksearchbox/.ui.activity.SearchSettingActivity",
                  texts=lambda: page_texts("搜索范围"))
        scope, _ = load(p, PLR, "下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(p.d.shell.call_args_list[0].args[0], SEARCH_SETTING)
        self.assertEqual(home_presses(p), [])
        self.assertFalse(any("input swipe" in c.args[0] for c in p.d.shell.call_args_list))
        p.tap.assert_any_call("搜索范围", exact=True)

    def test_pull_down_search_falls_back_to_the_desktop_gesture(self):
        """scheme 打不开：退回桌面下拉点底部「设置」，两步都不通才记未完成。"""
        p = phone(focus=lambda: "com.android.launcher/.Launcher")
        scope, out = load(p, PLR, "下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], ["下拉搜索"])
        self.assertIn("下拉没进全局搜索", out)
        self.assertIn("没进全局搜索设置页", out)
        self.assertEqual(p.d.shell.call_args_list[0].args[0], SEARCH_SETTING)
        self.assertEqual(len(home_presses(p)), 1)
        self.assertTrue(any("input swipe" in c.args[0] for c in p.d.shell.call_args_list))


if __name__ == "__main__":
    unittest.main()
