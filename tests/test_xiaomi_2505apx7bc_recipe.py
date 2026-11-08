"""Xiaomi MIX Flip 2（2505APX7BC，#832）：机型匹配、版本钉住与四处入口差异。

脚本照社区报告者的实测路径写，本仓库没有这台机器，未在真机上复跑。用例护住四件事：
选得到这份脚本、底栏一律走 p.tab()、主题与浏览器的设置入口按这台机的路径、天气与日历没有
「用户体验计划」时一项都不动。
"""
import ast
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import call
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/xiaomi-2505APX7BC/recipe.py"
STEPS = ["系统广告", "应用商店", "手机管家", "下载管理", "主题", "浏览器", "全局搜索", "负一屏", "天气和日历"]


class MixFlip2RecipeTests(unittest.TestCase):
    def setUp(self):
        self.path = RECIPE
        self.source = self.path.read_text(encoding="utf-8")

    def phone(self, focus=""):
        p = phone_mock()
        p.W, p.H = 1224, 2912                 # 这台机合盖外屏的分辨率
        p.locked.return_value = False
        p.focus.return_value = focus
        p.tree.return_value = ET.fromstring("<hierarchy/>")
        p.entry.return_value = False
        p.scroll_more.return_value = False
        p.switches.return_value = []
        return p

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("2505APX7BC", "Xiaomi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "xiaomi-2505APX7BC")
        meta = run.recipe_meta(path)
        self.assertEqual(meta["models"], ["2505APX7BC"])
        self.assertEqual(meta["build"], "BP2A.250605.031")
        self.assertEqual(meta["steps"], STEPS)

    def test_build_accepts_this_phone_and_rejects_a_neighbouring_build(self):
        phone = {"build": "BP2A.250605.031.A3", "os": "OS3.0.309.0.WOCCNXM"}
        self.assertTrue(run.build_ok(phone, "BP2A.250605.031"))
        self.assertFalse(run.build_ok({"build": "BP2B.250605.031.A3", "os": ""},
                                      "BP2A.250605.031"))

    def test_other_phones_on_the_same_baseband_still_borrow_the_reference_recipe(self):
        # BUILD 写到 `.031` 为止，是为了不让同底包、没有专属脚本的机型改借这一份：
        # 它们底栏是「菜单」、天气也没有「更多设置」，会被这里的必需入口卡住
        xiaomi13 = {"model": "2211133C", "brand": "Xiaomi", "build": "BP2A.250605.031.A3",
                    "os": "OS3.0.309.0.WOCCNXM"}
        path, reference = run.recipe_for("2211133C", "Xiaomi", xiaomi13)
        self.assertTrue(reference)
        self.assertEqual(Path(path).parent.name, "xiaomi-24129PN74C")

    def test_bottom_tabs_go_through_tab_not_go_or_tap(self):
        # 这台的第 5 个底栏标签在 y≈94% 屏高；p.tap() 会先命中内容区同名文字（#305 / #386）
        called = {n.func.attr for n in ast.walk(ast.parse(self.source))
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr in {"tab", "go", "tap", "entry"}
                  and any(isinstance(a, ast.Constant) and a.value == "我的" for a in n.args)}
        self.assertEqual(called, {"tab"})

    def test_browser_opens_settings_from_my_tab_and_does_not_touch_the_menu(self):
        # 这台底栏是 主页/视频/AI搜索/免费小说/我的，没有「菜单」（票面实测）
        p = self.phone("com.android.browser/.BrowserSettingsActivity")
        p.find.return_value = (960, 160)
        p.tab.return_value = True
        p.in_settings_page.return_value = True
        load_recipe(p, self.path, ["浏览器"])
        self.assertEqual(p.start.call_args_list[0].args, ("com.android.browser",))
        self.assertEqual(p.tab.call_args_list[0].args, ("我的",))
        self.assertNotIn(("菜单",), [c.args for c in p.tap.call_args_list])

    def test_browser_returns_to_the_settings_page_before_the_three_sub_pages(self):
        # 「隐私」→「隐私和安全」是两层：只退一层还停在「隐私」页，后面三项全找不到
        p = self.phone("com.android.browser/.BrowserSettingsActivity")
        p.find.return_value = (960, 160)
        p.tab.return_value = True
        p.in_settings_page.return_value = True
        p.entry.side_effect = lambda name, **_: name in {"隐私", "隐私和安全"}
        load_recipe(p, self.path, ["浏览器"])
        self.assertEqual(p.back.call_args_list, [call(), call(), call(2)])

    def test_browser_that_does_not_reach_a_settings_page_fails_the_step(self):
        # 底栏点得开、但那一页认不出是设置页时不能当成功（点击被吞 / 结构变了）
        p = self.phone("com.android.browser")
        p.tab.return_value = True
        p.find.return_value = (960, 160)
        p.in_settings_page.return_value = False
        out = io.StringIO()
        scope, _ = load_recipe(p, self.path, ["浏览器"], out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["浏览器"])
        p.off.assert_not_called()
        self.assertIn("浏览器设置入口没找到", out.getvalue())

    def test_theme_settings_entry_is_the_text_button_on_the_my_page(self):
        p = self.phone("com.android.thememanager/.ThemePreferenceActivity")
        p.d.shell.return_value.output = "package:/data/app/themestore/base.apk"
        p.tab.return_value = True
        p.tap.return_value = True
        p.expect_page.return_value = True
        load_recipe(p, self.path, ["主题"])
        self.assertEqual(p.tab.call_args_list[0].args, ("我的",))
        # 「设置」在这台是文字按钮：精确匹配那一下要真的点出去
        p.tap.assert_any_call("设置", exact=True, scrolls=0)
        self.assertEqual(p.off.call_args_list[0].kwargs["page"], "主题·设置")

    def test_theme_settings_page_that_does_not_open_fails_the_step(self):
        # ThemePreferenceActivity 的类名不含 Setting，落点只能看页面上的项：判据不过必须报失败
        p = self.phone("com.android.thememanager/.ThemePreferenceActivity")
        p.d.shell.return_value.output = "package:/data/app/themestore/base.apk"
        p.tab.return_value = True
        p.tap.return_value = True
        p.expect_page.return_value = False
        out = io.StringIO()
        scope, _ = load_recipe(p, self.path, ["主题"], out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["主题"])
        p.off.assert_not_called()
        self.assertIn("主题设置页没有打开", out.getvalue())

    def test_ad_service_page_that_does_not_show_the_switch_fails_the_step(self):
        # 搜索或深链落到别的页面时不能 0 项还报成功（参考脚本靠 close_named 的 require 守这条）
        p = self.phone("com.android.settings/.Settings")
        p.setting.return_value = True
        p.expect_page.return_value = False
        out = io.StringIO()
        scope, _ = load_recipe(p, self.path, ["系统广告"], out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])
        p.off.assert_not_called()
        self.assertIn("广告服务页没有打开", out.getvalue())

    def test_weather_popup_row_is_found_above_the_lower_third(self):
        # 「更多设置」浮层从右上锚点往下展开，「设置」可能落在屏幕上部，不能套用浏览器菜单那条下半屏判据
        p = self.phone("com.miui.weather2/.ActivitySet")
        p.tap.return_value = True
        p.texts.return_value = [("设置", (900, 300, 1000, 400), None)]
        _, out = load_recipe(p, self.path, ["天气和日历"])
        self.assertNotIn("菜单里没有「设置」", out.getvalue())

    def test_weather_and_calendar_leave_everything_alone_when_the_page_has_no_ad_switch(self):
        # 这版天气只有提醒与单位设置、日历 7 项全是功能开关：两项都不许动（票面实测）
        p = self.phone("com.android.calendar/.settings.CalendarActionbarSettingsActivity")
        p.tap.return_value = True
        p.texts.return_value = [("设置", (500, 1600, 700, 1700), None)]
        out = io.StringIO()
        scope, _ = load_recipe(p, self.path, ["天气和日历"], out=out)
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.off.assert_not_called()
        self.assertEqual(out.getvalue().count("本版无此类开关"), 2)
        self.assertNotIn("没有可识别的设置入口", out.getvalue())
        p.d.shell.assert_any_call(
            "am start -f 0x10008000 -n com.android.calendar/.settings.CalendarActionbarSettingsActivity")

    def test_weather_that_does_not_reach_its_settings_page_fails_instead_of_claiming_no_switches(self):
        # 菜单点空时不能把「没进设置页」说成「本版无此类开关」
        p = self.phone("com.miui.weather2/.MainActivity")
        p.tap.return_value = True
        p.settle.return_value = False
        p.find.return_value = False
        p.texts.return_value = [("设置", (500, 1600, 700, 1700), None)]
        out = io.StringIO()
        scope, _ = load_recipe(p, self.path, ["天气和日历"], out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["天气和日历"])
        p.off.assert_not_called()
        self.assertIn("天气设置页没有打开", out.getvalue())
        self.assertNotIn("本版无此类开关", out.getvalue())

    def test_weather_and_calendar_still_close_a_user_experience_page_if_one_shows_up(self):
        p = self.phone("com.android.calendar/.settings.CalendarActionbarSettingsActivity")
        p.tap.return_value = True
        p.texts.return_value = [("设置", (500, 1600, 700, 1700), None)]
        p.entry.side_effect = lambda name, **_: name == "用户体验计划"
        load_recipe(p, self.path, ["天气和日历"])
        pages = [c.kwargs["page"] for c in p.off.call_args_list]
        self.assertEqual(pages, ["天气·用户体验计划", "日历·用户体验计划"])

    def test_every_switch_page_names_the_switches_it_touches(self):
        # 不整页全关：每一处 p.off 都写死 only / keep（注释里提到 p.off() 不算调用）
        calls = [n for n in ast.walk(ast.parse(self.source))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "off"]
        self.assertTrue(calls)
        for node in calls:
            keywords = {k.arg for k in node.keywords}
            self.assertTrue(keywords & {"only", "keep"},
                            f"第 {node.lineno} 行的 off() 没有点名目标")
        self.assertIn('p.off(only=["个性化广告推荐"]', self.source)
        self.assertIn('p.off(only=["每次联网时通知"], keep=["自动更新"]', self.source)
        self.assertIn('p.off(only=["小说"], keep=["我的网盘"]', self.source)
        self.assertIn('p.off(only=["显示猜你想搜模块"]', self.source)


if __name__ == "__main__":
    unittest.main()
