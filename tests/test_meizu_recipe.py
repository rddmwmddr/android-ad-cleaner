"""魅族脚本只操作已确认的页面和精确目标，不把失败回读当成功。"""
import contextlib
import io
import itertools
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run
from fixtures import phone_mock

RECIPE = ROOT / "recipes/meizu-MEIZU 21 Pro/recipe.py"


class MeizuRecipeTests(unittest.TestCase):
    def phone(self):
        p = phone_mock()
        p.changed = []
        p.W, p.H = 1000, 2000
        p.focus.return_value = "app/Settings"
        p.locked.return_value = False
        p.tree.return_value = ET.Element("hierarchy")
        p.texts.return_value = []
        return p

    def device(self, phone):
        """按本机型号与录制版本应答 getprop；要验不符时由用例自己覆盖。"""
        phone.d.shell.side_effect = lambda command: Mock(
            output="MEIZU 21 Pro" if "model" in command else "Flyme 12.6.0.0A")
        return phone

    def load(self, phone, only=None, out=None):
        scope = {"p": phone, "ONLY": only or ["__none__"]}
        with contextlib.redirect_stdout(out if out is not None else io.StringIO()):
            exec(compile(RECIPE.read_text(encoding="utf-8"), str(RECIPE), "exec"), scope)
        return scope

    def test_model_selects_exact_recipe(self):
        path, reference = run.recipe_for("MEIZU 21 Pro", "meizu")
        self.assertFalse(reference)
        self.assertEqual(Path(path), RECIPE)
        meta = run.recipe_meta(path)
        self.assertEqual(meta["build"], "Flyme 12.6.0.0A")
        self.assertIn("锁屏画报", meta["steps"])

    def test_version_mismatch_aborts_before_navigation(self):
        p = self.phone()
        p.d.shell.side_effect = [Mock(output="MEIZU 21 Pro"), Mock(output="Flyme 12.6.1.0A")]
        scope = self.load(p, ["全局搜索"])
        self.assertEqual(scope["FAILED_STEPS"], ["全局搜索"])
        p.click.assert_not_called()
        self.assertEqual(p.d.shell.call_count, 2)

    def test_safe_mode_runs_the_step_instead_of_aborting_on_model_mismatch(self):
        # 别的魅族机型借这份脚本走安全模式；型号硬校验若照旧生效，8 段会全部空转（#379）
        p = self.phone()
        p.safe_mode = True
        p.d.shell.return_value = Mock(output="MEIZU 22")
        scope = self.load(p, ["探针"])
        ran = []

        @scope["step"]("探针")
        def probe():
            ran.append(1)

        self.assertEqual(ran, [1])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertFalse(p.d.shell.called)

    def test_unsafe_mode_still_aborts_on_model_mismatch(self):
        p = self.phone()
        p.d.shell.return_value = Mock(output="MEIZU 22")
        scope = self.load(p, ["探针"])
        ran = []

        @scope["step"]("探针")
        def probe():
            ran.append(1)

        self.assertEqual(ran, [])
        self.assertEqual(scope["FAILED_STEPS"], ["探针"])

    def test_entry_under_navigation_bar_is_scrolled_before_click(self):
        p = self.phone()
        target = ET.Element("node", {"package": "app"})
        p.texts.side_effect = [[("入口", (100, 1940, 900, 1980), target)],
                               [("入口", (100, 1200, 900, 1280), target)]]
        p.scroll_more.return_value = True
        scope = self.load(p)
        scope["TARGET_PACKAGE"] = "app"
        with patch.object(scope["time"], "sleep"):
            scope["tap_text"]("入口", scrolls=1)
        p.scroll_more.assert_called_once()
        p.click.assert_called_once_with(500, 1240)

    def test_open_app_hands_the_landmark_to_start(self):
        # 启动后不认页，落在开屏/推广页就只能整段放弃（#523）
        p = self.phone()
        p.focus.return_value = "com.android.browser/BrowserActivity"
        scope = self.load(p)
        scope["open_app"]("com.android.browser", "工具")
        p.start.assert_called_once_with("com.android.browser", expect="工具")

    def test_browser_enters_settings_through_go_and_still_confirms_the_page(self):
        p = self.device(self.phone())
        main = "com.android.browser/com.android.browser.BrowserActivity"
        settings = "com.android.browser/com.android.browser.activity.BrowserPreferencesPage"
        node = ET.Element("node", {"package": "com.android.browser"})
        p.texts.side_effect = lambda *args: [
            ("工具", (100, 1700, 300, 1800), node),
            ("主页展示", (100, 300, 600, 380), node),
            ("极简版", (100, 400, 600, 480), node),
        ]
        p.switches.return_value = []
        p.focus.side_effect = lambda: main if p.go.call_count == 0 else settings
        out = io.StringIO()
        with patch("time.sleep"):
            self.load(p, ["浏览器"], out=out)
        self.assertEqual(p.go.call_args_list, [call("工具", "设置"), call("设置", "主页展示")])
        self.assertNotIn("未确认目标页", out.getvalue())

    def test_browser_stops_when_the_settings_page_never_appears(self):
        # go 说点到了不算数：Activity 不对就停，别接着往下点
        p = self.device(self.phone())
        main = "com.android.browser/com.android.browser.BrowserActivity"
        node = ET.Element("node", {"package": "com.android.browser"})
        p.texts.side_effect = lambda *args: [
            ("工具", (100, 1700, 300, 1800), node),
            ("主页展示", (100, 300, 600, 380), node),
            ("极简版", (100, 400, 600, 480), node),
        ]
        p.switches.return_value = []
        p.focus.return_value = main
        out = io.StringIO()
        with patch("time.sleep"), patch("time.monotonic", side_effect=itertools.count()):
            self.load(p, ["浏览器"], out=out)
        self.assertIn("未确认目标页「主页展示」", out.getvalue())

    def test_app_store_enters_the_profile_tab_through_the_engine_tab_entry(self):
        # 「我的」在底栏，不能交给按屏高百分比拒点的 tap_text；找不到就整段停（#523）
        p = self.device(self.phone())
        main = "com.meizu.mstore/com.meizu.flyme.appcenter.activitys.AppMainActivity"
        node = ET.Element("node", {"package": "com.meizu.mstore"})
        p.texts.side_effect = lambda *args: [
            ("我的", (400, 1900, 600, 1980), node),
            ("设置", (100, 500, 300, 580), node),
            ("应用更新通知", (100, 300, 600, 380), node),
        ]
        p.switches.return_value = []
        p.focus.return_value = main
        p.tab.return_value = False
        out = io.StringIO()
        with patch("time.sleep"):
            self.load(p, ["应用商店"], out=out)
        p.tab.assert_called_once_with("我的")
        self.assertIn("应用商店底部没有「我的」标签", out.getvalue())
        p.click.assert_not_called()

    def test_failed_step_reports_page_shape_without_page_text(self):
        # 报错要能让报告者自证停在哪一页，同时不把账号页文字带出去
        p = self.phone()
        p.safe_mode = True
        root = ET.Element("hierarchy")
        account = ET.SubElement(root, "node", {"package": "com.android.browser",
                                               "text": "账号：13800000000",
                                               "bounds": "[0,100][200,200]"})
        tab = ET.SubElement(root, "node", {"package": "com.android.browser",
                                           "text": "我的",
                                           "bounds": "[100,1900][300,1980]"})
        p.tree.return_value = root
        p.texts.return_value = [("账号：13800000000", (0, 100, 200, 200), account),
                                ("我的", (100, 1900, 300, 1980), tab)]
        scope = self.load(p, ["探针"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            @scope["step"]("探针")
            def probe():
                raise RuntimeError("未找到「设置」")
        printed = out.getvalue()
        self.assertIn("未找到「设置」", printed)
        self.assertIn("app/Settings", printed)
        self.assertIn("标题 1 个，开关 0 个", printed)
        self.assertIn("底栏 1 条", printed)
        self.assertNotIn("13800000000", printed)
        p.switches.assert_not_called()

    def test_missing_or_duplicate_target_stops_before_click(self):
        for switches in ([('其他', True, (1, 2))],
                         [('目标', True, (1, 2)), ('目标', True, (3, 4))]):
            p = self.phone(); p.switches.return_value = switches
            scope = self.load(p)
            with self.assertRaisesRegex(RuntimeError, "未全部唯一识别"):
                scope["close_named"](["目标"], "页面", "app/Settings")
            p.click.assert_not_called()

    def test_only_confirm_matching_dialog_and_verify(self):
        p = self.phone()
        p.switches.side_effect = [[("目标", True, (900, 500)), ("提醒", True, (900, 700))],
                                  [("目标", True, (900, 500))],
                                  [("目标", False, (900, 500)), ("提醒", True, (900, 700))]]
        button = ET.Element("node", {"class": "android.widget.Button"})
        p.texts.return_value = [("确定关闭目标？", (100, 1000, 800, 1100), ET.Element("node")),
                                ("确定", (600, 1200, 800, 1300), button)]
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            scope["close_named"](["目标"], "页面", "app/Settings")
        self.assertEqual(p.click.call_count, 2)
        self.assertEqual(p.changed, [("页面", "目标")])

    def test_unrelated_confirmation_stops_without_confirming(self):
        p = self.phone()
        p.switches.return_value = [("目标", True, (900, 500))]
        button = ET.Element("node", {"class": "android.widget.Button"})
        p.texts.return_value = [("同意协议", (100, 1000, 800, 1100), ET.Element("node")),
                                ("确定", (600, 1200, 800, 1300), button)]
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"), self.assertRaisesRegex(RuntimeError, "无法识别"):
            scope["close_named"](["目标"], "页面", "app/Settings")
        self.assertEqual(p.click.call_count, 1)
        self.assertEqual(p.changed, [])

    def test_other_switch_change_fails_verification(self):
        p = self.phone()
        p.switches.side_effect = [[("目标", True, (900, 500)), ("提醒", True, (900, 700))],
                                  [("目标", True, (900, 500))],
                                  [("目标", False, (900, 500)), ("提醒", False, (900, 700))]]
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"), self.assertRaisesRegex(RuntimeError, "其他开关"):
            scope["close_named"](["目标"], "页面", "app/Settings")
        self.assertEqual(p.changed, [])


class MeizuFamilyTests(unittest.TestCase):
    """魅族要像另外四族一样，没有本型号脚本时兜底到同品牌参考（#379）。"""

    def test_other_meizu_models_fall_back_to_the_21_pro_recipe(self):
        for brand in ("MEIZU", "meizu", "Meizu"):
            with self.subTest(brand=brand):
                path, reference = run.recipe_for("MEIZU 22", brand)
                self.assertTrue(reference)
                self.assertEqual(Path(path), RECIPE)

    def test_reference_is_pinned_not_the_first_directory(self):
        # REFERENCE 必须显式指定：社区再提一份魅族脚本，别的魅族机型用的参考不能跟着变
        with tempfile.TemporaryDirectory() as root:
            for name in ("meizu-MEIZU 20", "meizu-MEIZU 21 Pro"):
                Path(root, "recipes", name).mkdir(parents=True)
                Path(root, "recipes", name, "recipe.py").write_text('BUILD = "Flyme 12.6.0.0A"\n', encoding="utf-8")
            with patch.object(run, "ROOT", root):
                path, reference = run.recipe_for("MEIZU 22", "MEIZU")
                self.assertTrue(reference)
                self.assertEqual(Path(path).parent.name, "meizu-MEIZU 21 Pro")

    def test_other_families_still_resolve_to_their_reference(self):
        cases = [("POCO", "xiaomi-M154FF"), ("Redmi", "xiaomi-M154FF"),
                 ("OnePlus", "oppo-PLP120"), ("realme", "oppo-PLP120"),
                 ("iQOO", "vivo-V2547DA"), ("HONOR", "honor-PNM-AN10")]
        for brand, expected in cases:
            with self.subTest(brand=brand):
                path, reference = run.recipe_for("ZZZ0000", brand)
                self.assertTrue(reference)
                self.assertEqual(Path(path).parent.name, expected)


if __name__ == "__main__":
    unittest.main()
