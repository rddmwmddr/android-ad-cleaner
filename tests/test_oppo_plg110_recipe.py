"""PLG110（OPPO Find X9 Pro）：未确认页面/控件时不点击，并保留服务类开关。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
import fixtures
from recipe_case import load, radios

RECIPE = ROOT / "recipes/oppo/PLG110/PLG110.toml"


class Plg110RecipeTests(unittest.TestCase):
    def setUp(self):
        self.p = Mock()
        self.p.changed = []
        self.p.locked.return_value = False
        self.scope = load(self.p, RECIPE)
        self.read_switches = Mock()
        fixtures.patch_surface(self, "read_switches",
                               lambda p, rt, *a, **k: self.read_switches(*a, **k))

    def states(self, before, after):
        self.read_switches = Mock(side_effect=[before, after])

    def close(self, names, **kwargs):
        return self.scope["close_named_expect"](names, "测试设置", "test/Settings", "测试设置", **kwargs)

    def test_model_uses_its_own_versioned_recipe(self):
        path, reference = run.recipe_for("PLG110", "OPPO")
        self.assertFalse(reference)
        self.assertEqual(Path(path), RECIPE)
        self.assertEqual(run.recipe_meta(path)["build"], "PLG110_16.0.10")
        self.assertEqual(len(run.recipe_meta(path)["steps"]), 9)

    def test_missing_target_prevents_all_switch_changes(self):
        self.read_switches = Mock(return_value={"应用安全": True})
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            self.close(["个性化推荐"])
        self.p.off.assert_not_called()

    def test_already_closed_target_does_not_touch_service_switch(self):
        self.states({"个性化推荐": False, "应用安全": True},
                    {"个性化推荐": False, "应用安全": True})
        self.close(["个性化推荐"])
        self.p.off.assert_not_called()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_carousel_choices_detects_radios(self):
        root = radios(show=True)
        choices = self.scope["carousel_choices"](root)
        self.assertTrue(choices["显示轮播推荐"][0])
        self.assertFalse(choices["不显示轮播推荐"][0])

    def test_oppo_optional_actions_and_safety_guards(self):
        self.assertEqual(run.FAMILY.get("oppo"), "oppo")
        self.assertIn("com.opos.ads", run.AD_PKGS["oppo"])
        self.assertIn("com.nearme.instant.platform", run.QUICKAPP_KEEP)
        self.assertIn("com.heytap.quicksearchbox", run.NEVER)
        self.assertIn("com.coloros.assistantscreen", run.NEVER)


if __name__ == "__main__":
    unittest.main()
