"""魅族脚本只操作已确认的页面和精确目标，不把失败回读当成功。"""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run
from fixtures import load_recipe, phone_mock, shell_result

RECIPE = ROOT / "recipes/meizu/MEIZU 21 Pro/MEIZU 21 Pro.toml"


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
        phone.shell.side_effect = lambda command: shell_result(
            "MEIZU 21 Pro" if "model" in command else "Flyme 12.6.0.0A")
        return phone

    def load(self, phone, only=None, out=None):
        scope, _ = load_recipe(phone, RECIPE, only, out)
        return scope

    def test_version_mismatch_aborts_before_navigation(self):
        p = self.phone()
        p.shell.side_effect = [shell_result("MEIZU 21 Pro", 0), shell_result("Flyme 12.6.1.0A", 0)]
        scope = self.load(p, ["全局搜索"])
        self.assertEqual(scope["FAILED_STEPS"], ["全局搜索"])
        p.click.assert_not_called()
        self.assertEqual(p.shell.call_count, 2)

    def test_safe_mode_runs_the_step_instead_of_aborting_on_model_mismatch(self):
        # 别的魅族机型借这份脚本走安全模式；型号硬校验若照旧生效，8 段会全部空转（#379）
        p = self.phone()
        p.safe_mode = True
        p.shell.return_value = shell_result("MEIZU 22", 0)
        scope = self.load(p, ["探针"])
        ran = []

        def probe():
            ran.append(1)
        scope["rt"].run_step("探针", probe)

        self.assertEqual(ran, [1])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertFalse(p.shell.called)

    def test_unsafe_mode_still_aborts_on_model_mismatch(self):
        p = self.phone()
        p.shell.return_value = shell_result("MEIZU 22", 0)
        scope = self.load(p, ["探针"])
        ran = []

        def probe():
            ran.append(1)
        scope["rt"].run_step("探针", probe)

        self.assertEqual(ran, [])
        self.assertEqual(scope["FAILED_STEPS"], ["探针"])

    def test_entry_under_navigation_bar_is_scrolled_before_click(self):
        p = self.phone()
        target = ET.Element("node", {"package": "app"})
        p.texts.side_effect = [[("入口", (100, 1940, 900, 1980), target)],
                               [("入口", (100, 1200, 900, 1280), target)]]
        p.scroll_more.return_value = True
        scope = self.load(p)
        scope["rt"].target = "app"
        with patch.object(scope["rt"].clock, "sleep"):
            scope["tap_text"]("入口", scrolls=1)
        p.scroll_more.assert_called_once()
        p.click.assert_called_once_with(500, 1240)

    def test_open_app_hands_the_landmark_to_start(self):
        # 启动后不认页，落在开屏/推广页就只能整段放弃（#523）
        p = self.phone()
        p.focus.return_value = "com.android.browser/BrowserActivity"
        scope = self.load(p)
        scope["open_app"](p, scope["rt"], "com.android.browser", "工具")
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
            def probe():
                raise RuntimeError("未找到「设置」")
            scope["rt"].run_step("探针", probe)
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
        with patch.object(scope["rt"].clock, "sleep"):
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


class RecipeSelectionTests(unittest.TestCase):
    """型号 → 脚本的选择协议：本型号直达，缺脚本时兜底到同品牌固定参考（沿用 #379 的做法）。"""

    # model, family, 是否参考, 脚本（相对 recipes/）, 记录版本（None = 该行不验）, 段名（None = 该行不验）
    CASES = [
        ("MEIZU 21 Pro", "meizu", False, "meizu/MEIZU 21 Pro/MEIZU 21 Pro.toml", "Flyme 12.6.0.0A", "锁屏画报"),
        ("MEIZU 22", "MEIZU", True, "meizu/MEIZU 21 Pro/MEIZU 21 Pro.toml", None, None),
        ("MEIZU 22", "meizu", True, "meizu/MEIZU 21 Pro/MEIZU 21 Pro.toml", None, None),
        ("MEIZU 22", "Meizu", True, "meizu/MEIZU 21 Pro/MEIZU 21 Pro.toml", None, None),
        ("ZZZ0000", "POCO", True, "xiaomi/M154FF/M154FF.toml", None, None),
        ("ZZZ0000", "Redmi", True, "xiaomi/M154FF/M154FF.toml", None, None),
        ("ZZZ0000", "OnePlus", True, "oppo/PLP120/PLP120.toml", None, None),
        ("ZZZ0000", "realme", True, "oppo/PLP120/PLP120.toml", None, None),
        ("ZZZ0000", "iQOO", True, "vivo/V2547DA/V2547DA.toml", None, None),
        ("ZZZ0000", "HONOR", True, "honor/PNM-AN10/PNM-AN10.toml", None, None),
    ]

    def test_model_resolves_to_its_own_recipe_or_the_family_reference(self):
        for model, family, reference, rel, build, step in self.CASES:
            with self.subTest(model=model, family=family):
                path, is_reference = run.recipe_for(model, family)
                self.assertEqual(bool(is_reference), reference)
                self.assertEqual(Path(path), ROOT / "recipes" / rel)
                if build:
                    meta = run.recipe_meta(path)
                    self.assertEqual(meta["build"], build)
                    self.assertIn(step, meta["steps"])

    def test_reference_is_pinned_not_the_first_directory(self):
        # REFERENCE 必须显式指定：社区再提一份魅族脚本，别的魅族机型用的参考不能跟着变
        with tempfile.TemporaryDirectory() as root:
            for name in ("MEIZU 20", "MEIZU 21 Pro"):
                Path(root, "recipes", "meizu", name).mkdir(parents=True)
                Path(root, "recipes", "meizu", name, "recipe.py").write_text('BUILD = "Flyme 12.6.0.0A"\n', encoding="utf-8")
            path, reference = run.recipe_for("MEIZU 22", "MEIZU", root=root)
            self.assertTrue(reference)
            self.assertEqual(Path(path).parent.name, "MEIZU 21 Pro")


if __name__ == "__main__":
    unittest.main()
