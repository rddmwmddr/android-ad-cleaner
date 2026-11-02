"""Xiaomi 15（24129PN74C）：本机实测入口、回读保护、与同底包脚本的差异。

2026-10-29 无线调试实测：底包 BP2A.250605.031.A3 与 recipes/redmi-25060RK16C 一致，
但浏览器入口是「菜单 → 设置」（不是底栏「我的」），商店没有隐私设置入口，
系统广告走设置搜索 / 深链（隐私与安全页里没有「更多安全设置」）。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import fast
import run
from fixtures import Clock, fake_phone, install_clock, phone_mock

GEAR_PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.calendar" bounds="[0,0][1080,2340]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true" bounds="[950,120][1040,210]" />
  </node>
</hierarchy>"""

CALENDAR = "com.android.calendar/com.android.calendar.AllInOneActivity"
CALENDAR_SETTINGS = "com.android.calendar/com.android.calendar.settings.SettingsActivity"
WEATHER_SETTINGS = "com.miui.weather2/com.miui.weather2.settings.WeatherSettingsActivity"
POPUP = "PopupWindow:9e12e45"
RECIPES = ("recipe.py", "recipe_os4.py")


class Xiaomi24129PN74CRecipeTests(unittest.TestCase):
    def load(self, phone, recipe="recipe.py"):
        path = ROOT / "recipes/xiaomi-24129PN74C" / recipe
        scope = {"p": phone, "ONLY": ["__no_steps__"]}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
        return scope

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("24129PN74C", "Xiaomi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "xiaomi-24129PN74C")
        self.assertEqual(run.recipe_meta(path)["build"], "BP2A.250605.031")
        self.assertEqual(run.recipe_meta(path)["models"], ["24129PN74C"])
        self.assertEqual(run.recipe_meta(path)["steps"],
                         ["系统广告", "应用商店", "手机管家", "下载管理", "主题",
                          "浏览器", "全局搜索", "负一屏", "天气和日历"])

    def test_build_matches_this_phone_and_not_other_base_packages(self):
        this_phone = {"build": "BP2A.250605.031.A3", "os": "OS3.0.307.0.WOCCNXM"}
        self.assertTrue(run.build_ok(this_phone, "BP2A.250605.031"))
        # OS4.0（小米 18 系列）不是这台机的底包。
        self.assertFalse(run.build_ok(this_phone, "OS4.0"))
        # build_ok 同时比对 HyperOS 版本号，这台的 OS3.0.307.0 与 K70 同号。
        self.assertTrue(run.build_ok(this_phone, "OS3.0.307.0"))

    def test_same_base_package_as_k80_script_but_own_entry_points(self):
        # 底包相同不等于入口相同：浏览器走「菜单」而不是底栏「我的」，商店没有隐私设置。
        k80 = run.recipe_meta(ROOT / "recipes/redmi-25060RK16C/recipe.py")["build"]
        self.assertEqual(k80, "BP2A")
        source = (ROOT / "recipes/xiaomi-24129PN74C/recipe.py").read_text(encoding="utf-8")
        self.assertIn('p.tap("菜单", exact=True, scrolls=0)', source)
        self.assertNotIn('p.tap("我的", exact=True, scrolls=0), "未找到浏览器', source)

    def test_system_ads_uses_search_or_deep_link_not_more_security_settings(self):
        source = (ROOT / "recipes/xiaomi-24129PN74C/recipe.py").read_text(encoding="utf-8")
        # 本机「隐私与安全」是权限中心，没有「更多安全设置」这一项。
        self.assertIn('p.setting("广告服务")', source)
        self.assertIn("com.android.settings/.ad.AdServiceSettings", source)
        # 菜单路径里不能出现「更多安全设置」这个点击动作（注释里的说明不算）。
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertNotIn("更多安全设置", code)

    def test_browser_keeps_function_switches_and_turns_off_ads_only(self):
        source = (ROOT / "recipes/xiaomi-24129PN74C/recipe.py").read_text(encoding="utf-8")
        # 运营任务 = 做任务得金币挣红包，纯营销，要关。
        self.assertIn('p.off(only=["运营任务", "小说"], keep=["我的网盘"]', source)
        # 扫一扫 / 搜索历史 / 书签 / 最常访问是功能项，不能进 only 名单。
        for functional in ("显示扫一扫模块", "显示搜索历史模块", "显示书签模块", "显示最常访问模块"):
            self.assertNotIn(functional, source)

    def test_missing_target_aborts_without_touching_switches(self):
        p = Mock()
        p.switches.return_value = [("其他开关", True, (1, 2))]
        p.scroll_more.return_value = False
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        p.off.assert_not_called()

    def test_reverted_switch_is_failure_not_verified(self):
        p = Mock()
        p.switches.return_value = [("个性化广告推荐", True, (1, 2))]
        p.scroll_more.return_value = False
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭"):
            scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_already_off_target_is_verified(self):
        p = Mock()
        p.switches.return_value = [("个性化广告推荐 个性化广告服务会根据您的喜好进行精准匹配。", False, (1, 2))]
        p.scroll_more.return_value = False
        scope = self.load(p)
        scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)
        p.off.assert_called_once()

    def test_unrelated_switch_changed_is_not_reported_as_verified(self):
        p = Mock()
        p.switches.side_effect = [
            [("个性化广告推荐", True, (1, 2)), ("其他开关", True, (1, 3))],
            [("个性化广告推荐", False, (1, 2)), ("其他开关", False, (1, 3))],
        ]
        p.scroll_more.return_value = False
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_protection_switch_is_not_in_any_only_list(self):
        """「限制广告跟踪」「防止广告追踪」这类开关是保护类，打开才对，不能进 only 名单。"""
        source = (ROOT / "recipes/xiaomi-24129PN74C/recipe.py").read_text(encoding="utf-8")
        for protective in ("限制广告跟踪", "防止广告追踪", "阻止广告跟踪"):
            self.assertNotIn(protective, source)

    def gear_phone(self, focus_stages, recipe="recipe.py"):
        clock = Clock()
        original = fast.time
        install_clock(fast, clock)
        self.addCleanup(setattr, fast, "time", original)
        p = fake_phone(clock=clock, stages=[(0.0, GEAR_PAGE)], focus=focus_stages)
        p.back = Mock()
        scope = self.load(p, recipe)
        scope["time"] = clock
        return p, scope

    def test_gear_rejects_a_click_that_lands_on_a_popup(self):
        """#407：日历的齿轮打开 PopupWindow，不能当成进了设置页。两份同型号脚本一致。"""
        for recipe in RECIPES:
            with self.subTest(recipe=recipe):
                p, scope = self.gear_phone([(0.0, CALENDAR), (0.5, POPUP)], recipe)
                self.assertFalse(scope["gear"](toolbar_only=True))
                p.back.assert_called_once()

    def test_gear_keeps_the_page_when_the_click_is_swallowed(self):
        """点击被吞、页面没换：判失败但不按返回，别把用户从原页退出去（#331）。"""
        for recipe in RECIPES:
            with self.subTest(recipe=recipe):
                p, scope = self.gear_phone([(0.0, CALENDAR)], recipe)
                self.assertFalse(scope["gear"](toolbar_only=True))
                p.back.assert_not_called()

    def test_gear_accepts_calendar_and_weather_settings_pages(self):
        """日历与天气的设置页都含 Setting，同一条判定对两段都成立。"""
        for recipe in RECIPES:
            for activity in (CALENDAR_SETTINGS, WEATHER_SETTINGS):
                with self.subTest(recipe=recipe, activity=activity):
                    p, scope = self.gear_phone([(0.0, CALENDAR), (0.5, activity)], recipe)
                    self.assertTrue(scope["gear"](toolbar_only=True))
                    p.back.assert_not_called()

    def calendar_section(self):
        p = phone_mock()
        p.locked = lambda: False
        scope = self.load(p)
        return p, scope

    def test_calendar_section_skips_instead_of_searching_inside_the_popup(self):
        p, scope = self.calendar_section()
        gear = scope["gear"] = Mock(return_value=False)
        entry = scope["maybe"] = Mock(return_value=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(scope["time"], "sleep"):
            scope["_"]()
        self.assertIn("日历没有可识别的设置入口，跳过", out.getvalue())
        # 天气、日历各试一次工具栏齿轮 + 一次全页齿轮，失败后都不进 maybe。
        self.assertEqual(gear.call_count, 4)
        entry.assert_not_called()

    def test_weather_section_still_opens_the_user_experience_plan(self):
        """天气齿轮进的是真设置页：校验不能把这一段拦下来。

        gear() 在天气设置页焦点下返回 True 由 test_gear_accepts_calendar_and_weather_settings_pages
        证明；这条只管「gear 成功之后两段都照常处理」。
        """
        p, scope = self.calendar_section()
        gear = scope["gear"] = Mock(return_value=True)
        scope["maybe"] = Mock(return_value=True)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(scope["time"], "sleep"):
            scope["_"]()
        self.assertEqual(gear.call_count, 2)
        pages = [call.kwargs["page"] for call in p.off.call_args_list]
        self.assertIn("天气·用户体验计划", pages)
        self.assertIn("日历·用户体验计划", pages)


if __name__ == "__main__":
    unittest.main()
