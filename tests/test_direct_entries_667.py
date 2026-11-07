"""#667：小米 M154FF、vivo V2547DA 的设置页能直达就直达，打不开才走菜单，断线不当成「这一档不通」。"""
import ast
import sys
import unittest
from pathlib import Path

import fixtures
from fixtures import load_recipe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adb_link  # noqa: E402
import entries  # noqa: E402

XIAOMI = ROOT / "recipes" / "xiaomi-M154FF" / "recipe.py"
VIVO = ROOT / "recipes" / "vivo-V2547DA" / "recipe_android17.py"


def phone(start=None, lost=False):
    p = fixtures.phone_mock(lost=lost)
    p.locked.return_value = False
    p.focus.return_value = ""
    p.entry.return_value = False
    p.switches.return_value = []
    if start is not None:
        p.start.side_effect = start
    return p


def started(p):
    return [c.args[:2] if len(c.args) > 1 else c.args[:1] for c in p.start.call_args_list]


def expects(p):
    return [c.kwargs.get("expect") for c in p.start.call_args_list]


def shells(p):
    return [c.args[0] for c in p.d.shell.call_args_list]


def fail_direct(pkg, activity=None, **kw):
    if activity:
        raise RuntimeError("无法打开")


class XiaomiTest(unittest.TestCase):
    def run_step(self, name, p):
        return load_recipe(p, XIAOMI, only=name)

    def test_system_ads_goes_straight_to_the_page(self):
        p = phone()
        self.run_step("系统广告", p)
        self.assertEqual(started(p), [("com.android.settings", ".ad.AdServiceSettings")])
        self.assertEqual(expects(p), ["个性化广告推荐"])       # 落点判据要真的传下去
        p.off.assert_called_once_with(only=["个性化广告推荐"], page="系统·广告服务")
        self.assertFalse(any("android.settings.SETTINGS" in c for c in shells(p)))

    def test_system_ads_falls_back_to_the_menu(self):
        p = phone(fail_direct)
        self.run_step("系统广告", p)
        self.assertTrue(any("android.settings.SETTINGS" in c for c in shells(p)))
        self.assertEqual(p.entry.call_args_list[0].args[0], "隐私与安全")

    def test_lost_connection_does_not_walk_the_menu(self):
        p = phone(adb_link.DeviceLost("断了"))
        scope, _ = self.run_step("系统广告", p)
        self.assertEqual(shells(p), [])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])

    def test_lost_in_the_middle_does_not_look_like_an_unreachable_page(self):
        """读到一半断线时 Phone 只置 lost、抛的是普通 RuntimeError（#293、#667）：不能当成「这一页打不开」。"""
        p = phone()
        p.lost = True
        p.start.side_effect = RuntimeError("device offline")
        scope, _ = self.run_step("系统广告", p)
        self.assertEqual(shells(p), [])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])

    def test_store_opens_settings_directly(self):
        p = phone()
        self.run_step("应用商店", p)
        self.assertEqual(started(p), [("com.xiaomi.market", ".ui.MarketPreferenceActivity")])
        self.assertEqual(expects(p), ["通知设置"])
        p.go.assert_not_called()

    def test_store_falls_back_to_my_page(self):
        p = phone(fail_direct)
        p.tree.return_value.iter.return_value = []
        p.find.return_value = None
        self.run_step("应用商店", p)
        self.assertEqual(started(p)[-1], ("com.xiaomi.market",))
        p.go.assert_called_once_with("我的", "设置")

    def test_downloads_goes_straight_to_the_feed_page(self):
        p = phone()
        self.run_step("下载管理", p)
        self.assertEqual(started(p), [("com.android.providers.downloads.ui", ".activity.InfoFlowSettingActivity")])
        self.assertEqual(expects(p), ["资源推荐"])
        p.off.assert_called_once_with(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")

    def test_browser_does_not_depend_on_the_home_page(self):
        # 后台屏上首页的工具栏和底栏认不出来，以前报「设置入口未找到」，这一段就失败了
        p = phone()
        p.tree.side_effect = AssertionError("直达时不该读浏览器首页找入口")
        scope, _ = self.run_step("浏览器", p)
        self.assertEqual(started(p), [("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity"),
                                      ("com.android.browser", ".BrowserSettingsActivity")])
        self.assertEqual(expects(p), ["个性化内容推荐", None])
        p.off.assert_called_once_with(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_browser_second_hop_does_not_fail_the_segment(self):
        """18 Fold 这类版本可能没有 .BrowserSettingsActivity：打不开只跳过子项，不让整段报未完成。"""
        def second_hop_missing(pkg, activity=None, **kw):
            if activity == ".BrowserSettingsActivity":
                raise RuntimeError("无法打开")

        p = phone(second_hop_missing)
        scope, out = self.run_step("浏览器", p)
        self.assertIn("直达不通", out.getvalue())
        p.off.assert_called_once_with(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
        # 只找过这三个子项，没有回头读首页或设置页找别的入口
        self.assertEqual([c.args[0] for c in p.entry.call_args_list], ["主页设置", "搜索设置", "功能设置"])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_browser_basic_mode_still_skips_on_the_menu_path(self):
        p = phone(fail_direct)
        p.focus.return_value = "com.android.browser/.basicmode.BasicModeSettingActivity"
        scope, out = self.run_step("浏览器", p)
        self.assertIn("基本模式", out.getvalue())
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_calendar_goes_straight_and_weather_keeps_its_menu(self):
        p = phone()
        p.find.return_value = None
        p.tree.return_value.iter.return_value = []
        self.run_step("天气和日历", p)
        self.assertEqual(started(p), [("com.miui.weather2",),
                                      ("com.android.calendar", ".settings.UserExperienceActionBarActivity")])
        self.assertEqual(expects(p), [None, "内容推广"])
        p.off.assert_called_once()
        self.assertEqual(p.off.call_args.kwargs["page"], "com.android.calendar·用户体验计划")


class VivoTest(unittest.TestCase):
    def run_step(self, name, p):
        return load_recipe(p, VIVO, only=name)

    def test_system_ads_passes_the_literal_activity(self):
        """页面名带 $：引用只在引擎的 shell 边界做一次（Phone._launch），脚本这层保持字面量。"""
        p = phone()
        self.run_step("系统广告", p)
        self.assertEqual(started(p), [("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo")])
        self.assertEqual(expects(p), ["智能推荐服务"])
        p.off.assert_called_once_with(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")

    def test_lost_in_the_middle_does_not_walk_the_menu(self):
        p = phone()
        p.lost = True
        p.start.side_effect = RuntimeError("device offline")
        scope, _ = self.run_step("系统广告", p)
        self.assertEqual(shells(p), [])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])

    def test_system_ads_falls_back_to_the_menu(self):
        p = phone(fail_direct)
        self.run_step("系统广告", p)
        self.assertTrue(any("android.settings.SETTINGS" in c for c in shells(p)))

    def test_magazine_goes_straight_to_the_page(self):
        p = phone()
        self.run_step("阅图锁屏", p)
        self.assertEqual(started(p), [("com.vivo.magazine", ".ui.MagazineSettings")])
        self.assertEqual(expects(p), ["锁屏横滑进入阅图"])
        self.assertEqual(shells(p), [])

    def test_search_opens_settings_directly(self):
        p = phone()
        p.entry.side_effect = lambda name, scrolls=6: name == "首页展示内容"
        self.run_step("全局搜索", p)
        self.assertEqual(started(p), [("com.vivo.globalsearch", ".view.SearchSettingsActivity")])
        self.assertEqual(expects(p), ["首页展示内容"])
        self.assertEqual(shells(p), [])
        p.off.assert_called_once_with(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容")

    def test_search_stops_when_the_menu_has_no_entry(self):
        p = phone(fail_direct)
        self.run_step("全局搜索", p)
        p.off.assert_not_called()
        self.assertEqual([c.args[0] for c in p.entry.call_args_list], ["系统管理与升级"])

    def test_hot_search_row_is_closed_without_scrolling(self):
        p = phone()
        p.find.return_value = object()
        p.entry.side_effect = lambda name, scrolls=6: name in ("首页展示内容", "推荐热搜榜单")
        self.run_step("全局搜索", p)
        self.assertEqual([c.kwargs["page"] for c in p.off.call_args_list],
                         ["全局搜索·首页展示内容", "全局搜索·热搜榜单"])
        hot = [c for c in p.entry.call_args_list if c.args[0] == "推荐热搜榜单"]
        self.assertEqual(hot[0].kwargs["scrolls"], 0)      # 这一页只有几行，不滚（#667）

    def test_hot_search_row_is_not_searched_for_when_absent(self):
        p = phone()
        p.find.return_value = None
        p.entry.side_effect = lambda name, scrolls=6: name == "首页展示内容"
        self.run_step("全局搜索", p)
        self.assertFalse(any(c.args[0] == "推荐热搜榜单" for c in p.entry.call_args_list))


class RecipeQuotingTest(unittest.TestCase):
    """页面名的 shell 引用只在 Phone._launch 做一次。脚本里再 shlex.quote 会叠成两层，
    am 收到带字面引号的类名（#667 审查时 vivo V2417A 就是这么被弄坏的）。"""

    def test_no_recipe_quotes_the_page_name_before_start(self):
        offenders = []
        for path in sorted((ROOT / "recipes").glob("*/recipe*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (isinstance(node.func, ast.Attribute) and node.func.attr == "start"):
                    continue
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) \
                            and arg.func.attr == "quote":
                        offenders.append(f"{path.relative_to(ROOT)}:{arg.lineno}")
        self.assertEqual(offenders, [], "页面名照字面量传，引用交给 Phone._launch")


class OpenDirectTest(unittest.TestCase):
    def test_activity_is_passed_to_phone_start_unquoted(self):
        """引用交给 Phone._launch；这一层保持字面量，used_by() 才认得出是哪台机在用（#667 审查）。"""
        p = fixtures.phone_mock()
        entries.open_direct(p, entries.Direct("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo"))
        self.assertEqual(p.start.call_args.args, ("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo"))

    def test_plain_activity_is_left_alone(self):
        p = fixtures.phone_mock()
        entries.open_direct(p, entries.Direct("com.android.settings", ".ad.AdServiceSettings"))
        self.assertEqual(p.start.call_args.args, ("com.android.settings", ".ad.AdServiceSettings"))


if __name__ == "__main__":
    unittest.main()
