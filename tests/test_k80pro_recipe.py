"""Redmi K80 Pro：机型匹配、浏览器冷启动重试和齿轮兜底。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe


class K80ProRecipeTests(unittest.TestCase):
    def load(self, phone):
        scope, _ = load_recipe(phone, ROOT / "recipes/redmi-24122RKC7C/recipe.py")
        return scope

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("24122RKC7C", "Redmi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "redmi-24122RKC7C")
        self.assertEqual(run.recipe_meta(path)["models"], ["24122RKC7C"])
        self.assertEqual(run.recipe_meta(path)["build"], "OS3.0.304.0")
        self.assertEqual(run.recipe_meta(path)["steps"],
                         ["系统广告", "应用商店", "手机管家", "下载管理", "主题",
                          "浏览器", "全局搜索", "负一屏", "天气和日历"])
        self.assertTrue(run.build_ok({"build": "BP2A.250605.031.A3", "os": "OS3.0.304.0.WOMCNXM"},
                                     "OS3.0.304.0"))
        self.assertFalse(run.build_ok({"build": "BP2A.250605.031.A3", "os": "OS3.0.304.0.WOMCNXM"},
                                      "OS4.0"))

    def test_browser_start_retries_once_after_leaving_foreground(self):
        p = Mock()
        p.start.side_effect = [RuntimeError("com.android.browser 启动后离开前台，停止本段以免操作其他 App"), None]
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            self.assertTrue(scope["browser_start"]())
        self.assertEqual(p.start.call_count, 2)
        p.d.shell.assert_called_once_with("am force-stop com.android.browser")

    def test_browser_start_does_not_retry_other_failures(self):
        p = Mock()
        p.start.side_effect = RuntimeError("无法打开 com.android.browser：no activities")
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "无法打开"):
            scope["browser_start"]()
        p.d.shell.assert_not_called()
        self.assertEqual(p.start.call_count, 1)

    def test_browser_start_reports_failure_when_retry_also_leaves(self):
        p = Mock()
        p.start.side_effect = RuntimeError("com.android.browser 启动后离开前台，停止本段以免操作其他 App")
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            with self.assertRaisesRegex(RuntimeError, "离开前台"):
                scope["browser_start"]()

    def test_gear_tap_uses_plain_tap_when_short_press_is_swallowed(self):
        root = ET.fromstring(
            '<hierarchy><node class="android.widget.ImageView" text="设置" clickable="true"'
            ' bounds="[922,133][1038,249]"/></hierarchy>')
        p = Mock(W=1080, H=2400)
        p.tree.return_value = root
        p.on_screen.return_value = True
        p.focus.return_value = "com.android.browser/com.android.browser.BrowserSettingsActivity"
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            self.assertTrue(scope["gear_tap"]("com.android.browser", "BrowserSettingsActivity"))
        p.d.shell.assert_called_once_with("input tap 980 191")

    def test_gear_tap_reports_when_settings_still_not_open(self):
        root = ET.fromstring(
            '<hierarchy><node class="android.widget.ImageView" text="设置" clickable="true"'
            ' bounds="[922,133][1038,249]"/></hierarchy>')
        p = Mock(W=1080, H=2400)
        p.tree.return_value = root
        p.on_screen.return_value = True
        p.focus.return_value = "com.android.browser/com.android.browser.BrowserActivity"
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            self.assertFalse(scope["gear_tap"]("com.android.browser", "BrowserSettingsActivity"))

    def test_missing_target_aborts_without_touching_switches(self):
        p = Mock()
        p.switches.return_value = [("其他开关", True, (1, 2))]
        p.scroll_more.return_value = False
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        p.off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
