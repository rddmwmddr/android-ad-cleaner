"""Redmi K70：系统广告入口、标签识别和回读保护。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe
import recipe_case


class K70RecipeTests(recipe_case.RecipeSafetyCase):
    RECIPE = ROOT / "recipes/xiaomi/23113RKC6C/23113RKC6C.toml"

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("23113RKC6C", "Redmi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "23113RKC6C")
        self.assertEqual(run.recipe_meta(path)["build"], "OS3.0.307.0")
        self.assertEqual(run.recipe_meta(path)["steps"],
                         ["系统广告", "应用商店", "手机管家", "下载管理", "主题",
                          "浏览器", "全局搜索", "负一屏", "天气和日历"])
        self.assertTrue(run.build_ok({"build": "BP2A.250605.031.A3", "os": "OS3.0.307.0.WNKCNXM"},
                                     "OS3.0.307.0"))
        self.assertFalse(run.build_ok({"build": "BP2A.250605.031.A3", "os": "OS3.0.307.0.WNKCNXM"},
                                      "OS4.0"))

    def test_security_tab_clicks_clickable_container_not_label_text(self):
        p = Mock(W=1080, H=2400)
        p.texts.return_value = [
            ("安全", (749, 287, 827, 339), {"clickable": "false"}),
            ("安全", (540, 269, 1036, 357), {"clickable": "true"}),
        ]
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            self.assertTrue(scope["security_tab"]())
        p.click.assert_called_once_with(788, 313)


class K70ProRecipeTests(unittest.TestCase):
    def run_store(self, switches):
        phone = Mock()
        phone.locked.return_value = False
        phone.tap.return_value = True
        phone.switches.return_value = switches
        phone.scroll_more.return_value = False
        scope, _ = load_recipe(phone, ROOT / "recipes/xiaomi/23117RK66C/23117RK66C.toml", ["应用商店"])
        return phone, scope

    def test_store_missing_target_aborts_before_toggling_other_settings(self):
        phone, scope = self.run_store([("应用更新通知", True, (1, 2))])
        phone.off.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], ["应用商店"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_store_target_that_stays_on_is_not_reported_as_verified(self):
        phone, scope = self.run_store([("个性化服务", True, (1, 2))])
        phone.off.assert_called_once()
        self.assertEqual(scope["FAILED_STEPS"], ["应用商店"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)


if __name__ == "__main__":
    unittest.main()
