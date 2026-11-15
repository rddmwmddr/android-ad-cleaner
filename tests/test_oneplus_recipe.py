"""一加旧系统：入口回读和目标开关不完整时停止，避免把尝试写成成功。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe, phone_mock


class OnePlusRecipeTests(unittest.TestCase):
    def load(self, phone):
        scope, _ = load_recipe(phone, ROOT / "recipes/oppo/PJA110/PJA110.toml")
        return scope

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("PJA110", "OnePlus")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "PJA110")
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


class PJASearchSegmentTests(unittest.TestCase):
    """「下拉搜索」段（#1362）：home → 下滑手势 → back 三步进搜索页，落点不对就整段失败。

    手势由数据里的 `gesture` 下发；两个库调用换成桩，这里只验数据段的走法，不重测库实现。
    段体从 `code=` 搬进数据，调用不变：旧树也绿，守的是这条走法不回退。"""

    RECIPE = ROOT / "recipes/oppo/PJA110/PJA110.toml"

    def run_segment(self, focus):
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1080, H=2340)
        phone.locked.return_value = False
        phone.focus.return_value = focus
        taps, closes = [], []
        with patch.dict(interpreter.LIBRARY, {
                "tap": lambda p, rt, name: taps.append(name),
                "close_named": lambda p, rt, names, page: closes.append((names, page))}):
            scope, _out = load_recipe(phone, self.RECIPE, ["下拉搜索"])
        return phone, taps, closes, scope["rt"].results

    def test_home_gesture_back_enters_search_then_closes_the_privacy_page(self):
        phone, taps, closes, results = self.run_segment("com.heytap.quicksearchbox/.MainActivity")
        commands = [call.args[0] for call in phone.d.shell.call_args_list]
        self.assertEqual([c for c in commands if c.startswith("input")],
                         ["input keyevent HOME", "input swipe 540 702 540 1638 300",
                          "input keyevent BACK"])
        phone.focus.assert_called_once()
        self.assertEqual(taps, ["设置", "账号与隐私", "隐私"])
        self.assertEqual(closes, [(["个性化推荐"], "下拉搜索·隐私")])
        self.assertEqual(results, [("下拉搜索", "完成")])

    def test_landing_on_another_app_fails_before_touching_anything(self):
        _phone, taps, closes, results = self.run_segment("com.android.launcher/.Launcher")
        self.assertEqual(results, [("下拉搜索", "未完成")])
        self.assertEqual(taps, [])
        self.assertEqual(closes, [])


if __name__ == "__main__":
    unittest.main()
