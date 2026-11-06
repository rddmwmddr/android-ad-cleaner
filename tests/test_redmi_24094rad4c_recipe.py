"""Redmi Note 14 5G：专用型号匹配、系统版本锁定和保守的开关范围。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe


class Redmi24094RAD4CRecipeTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "recipes/redmi-24094RAD4C/recipe.py"
        self.source = self.path.read_text(encoding="utf-8")

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("24094RAD4C", "Redmi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "redmi-24094RAD4C")
        meta = run.recipe_meta(path)
        self.assertEqual(meta["models"], ["24094RAD4C"])
        self.assertEqual(meta["build"], "OS3.0.306.0")
        self.assertEqual(meta["steps"],
                         ["系统广告", "应用商店", "手机管家", "下载管理",
                          "主题", "浏览器", "全局搜索", "负一屏"])

    def test_build_accepts_this_phone_and_rejects_other_hyperos_generation(self):
        phone = {"build": "BP2A.250605.031.A3", "os": "OS3.0.306.0.WOQCNXM"}
        self.assertTrue(run.build_ok(phone, "OS3.0.306.0"))
        self.assertFalse(run.build_ok(phone, "OS4.0"))

    def test_script_keeps_store_mode_updates_and_functional_browser_entries(self):
        self.assertNotIn('p.tap("极简模式"', self.source)
        self.assertIn('keep=["推送消息", "应用更新"]', self.source)
        self.assertIn('keep=["自动更新"]', self.source)
        self.assertIn('p.off(only=["宫格位推送"]', self.source)
        self.assertIn('p.off(only=["猜你想搜"]', self.source)
        self.assertNotIn('p.off(only=["小说"]', self.source)
        self.assertIn('close_with_plain_tap(["个性化内容推荐", "个性化广告推荐"]', self.source)

    def test_theme_handles_the_observed_skippable_splash_ad(self):
        self.assertIn('p.find("跳过广告")', self.source)
        self.assertIn('p.tap("跳过广告", scrolls=0)', self.source)

    def test_theme_waits_for_the_bottom_tab_to_settle(self):
        p = Mock()
        scope, _ = load_recipe(p, self.path)
        scope["tap_bottom_tab"] = Mock(side_effect=[False, False, True])
        self.assertTrue(scope["wait_bottom_tab"]("我的"))
        self.assertEqual(scope["tap_bottom_tab"].call_count, 3)
        self.assertEqual(p.dismiss.call_count, 3)

    def test_plain_tap_fallback_confirms_and_verifies_only_named_switches(self):
        p = Mock()
        p.changed = []
        p.switches.side_effect = [
            [("资源推荐", True, (1, 2)), ("热榜推荐", True, (3, 4)), ("仅在WLAN下加载", False, (5, 6))],
            [("资源推荐", True, (1, 2)), ("热榜推荐", True, (3, 4))],
            [("热榜推荐", True, (3, 4))],
            [("资源推荐", False, (1, 2)), ("热榜推荐", False, (3, 4)), ("仅在WLAN下加载", False, (5, 6))],
        ]
        scope, _ = load_recipe(p, self.path)
        scope["close_with_plain_tap"](["资源推荐", "热榜推荐"], "下载管理·信息流")
        self.assertEqual(p.d.shell.call_count, 2)
        self.assertEqual(p.confirm.call_count, 2)
        self.assertEqual(p.changed, [("下载管理·信息流", "资源推荐"),
                                     ("下载管理·信息流", "热榜推荐")])

    def test_plain_tap_fallback_records_only_switches_it_turned_off(self):
        p = Mock()
        p.changed = []
        p.switches.side_effect = [
            [("资源推荐", False, (1, 2)), ("热榜推荐", True, (3, 4))],
            [("热榜推荐", True, (3, 4))],
            [("资源推荐", False, (1, 2)), ("热榜推荐", False, (3, 4))],
        ]
        scope, _ = load_recipe(p, self.path)
        scope["close_with_plain_tap"](["资源推荐", "热榜推荐"], "浏览器·隐私和安全")
        self.assertEqual(p.d.shell.call_count, 1)
        self.assertEqual(p.changed, [("浏览器·隐私和安全", "热榜推荐")])

    def test_plain_tap_fallback_aborts_when_target_missing(self):
        p = Mock()
        p.switches.return_value = [("其他开关", True, (1, 2))]
        scope, _ = load_recipe(p, self.path)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_with_plain_tap"](["资源推荐", "热榜推荐"], "下载管理·信息流")
        p.d.shell.assert_not_called()

    def test_note_14_pro_remains_a_separate_recipe(self):
        path, reference = run.recipe_for("24090RA29C", "Redmi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "xiaomi-24090RA29C")


if __name__ == "__main__":
    unittest.main()
