"""一加旧系统：入口回读和目标开关不完整时停止，避免把尝试写成成功。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe


class OnePlusRecipeTests(unittest.TestCase):
    def load(self, phone):
        scope, _ = load_recipe(phone, ROOT / "recipes/oneplus-PJA110/recipe.py")
        return scope

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("PJA110", "OnePlus")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "oneplus-PJA110")
        self.assertEqual(run.recipe_meta(path)["build"], "PJA110_14.0.0.812")

    def test_missing_target_aborts_without_clicking_any_switch(self):
        p = Mock(); p.switches.return_value = [("WLAN 自动更新应用", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_named"](["个性化推荐"], "商店")
        p.off.assert_not_called()

    def test_reverted_switch_is_failure_not_verified(self):
        p = Mock(); p.switches.return_value = [("个性化推荐", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认"):
            scope["close_named"](["个性化推荐"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_target_below_fold_is_verified_and_other_switch_is_preserved(self):
        p = Mock()
        p.scroll_more.return_value = True
        p.switches.side_effect = [
            [("活动弹窗", True, (1, 2)), ("应用安全", True, (1, 3))],
            [("软件福利", True, (1, 2))],
            [("活动弹窗", False, (1, 2)), ("应用安全", True, (1, 3))],
            [("软件福利", False, (1, 2))],
        ]
        scope = self.load(p)
        scope["close_named"](["活动弹窗", "软件福利"], "商店", max_screens=2)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 2)

    def test_unrelated_switch_changed_is_not_reported_as_verified(self):
        p = Mock()
        p.switches.side_effect = [
            [("活动弹窗", True, (1, 2)), ("应用安全", True, (1, 3))],
            [("活动弹窗", False, (1, 2)), ("应用安全", False, (1, 3))],
        ]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named"](["活动弹窗"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_swallowed_settings_tap_retries_until_actual_activity_opens(self):
        p = Mock(); p.go.return_value = True; p.tap.return_value = True
        p.focus.side_effect = ["com.example/.Main"] * 5 + ["com.example/.Settings"] * 2
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            scope["app_settings"]("com.example", ".Settings")
        self.assertEqual(p.tap.call_count, 2)


if __name__ == "__main__":
    unittest.main()
