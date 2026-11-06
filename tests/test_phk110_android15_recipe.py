"""版本选择及开关识别保护：不需要连接设备。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe


class Android15RecipeTests(unittest.TestCase):
    def load(self, phone):
        scope, _ = load_recipe(phone, ROOT / "recipes/oneplus-PHK110/recipe_android15.py")
        scope["page"] = lambda *args: True
        return scope

    def test_matching_version_selects_variant_and_other_versions_keep_original(self):
        old = {"build": "PHK110_15.0.0.601(CN01)", "os": ""}
        new = {"build": "PHK110_16.0.5.1201(CN01)", "os": ""}
        self.assertEqual(Path(run.recipe_for("PHK110", "OnePlus", old)[0]).name, "recipe_android15.py")
        self.assertEqual(Path(run.recipe_for("PHK110", "OnePlus", new)[0]).name, "recipe.py")
        self.assertEqual(Path(run.recipe_for("PHK110", "OnePlus", {"build": "other", "os": ""})[0]).name, "recipe.py")

    def test_missing_or_ambiguous_target_does_not_click(self):
        phone = Mock()
        phone.switches.return_value = [("应用安全", True, (5, 8))]
        scope = self.load(phone)
        self.assertFalse(scope["off_exact"](["个性化推荐"], "activity", "title"))
        phone.click.assert_not_called()
        phone.switches.return_value = [("个性化推荐", True, (5, 8)), ("个性化推荐", True, (5, 9))]
        self.assertFalse(scope["off_exact"](["个性化推荐"], "activity", "title"))
        phone.click.assert_not_called()

    def test_failed_readback_is_not_reported_as_success(self):
        phone = Mock()
        phone.switches.return_value = [("开屏广告", True, (5, 8))]
        scope = self.load(phone)
        self.assertFalse(scope["off_exact"](["开屏广告"], "activity", "title"))
        phone.click.assert_called_once_with(5, 8)


if __name__ == "__main__":
    unittest.main()
