"""vivo V1986A（Funtouch 13 / Android 12）：机型脚本选中、录制版本，以及两处必须按坐标点的位置。

本机实测的两个坑都写在这里：应用商店底部「我的」在 y>92%（find() 默认不点导航栏），
「关于」那行点标题文字不跳转、要点副标题所在行的中间。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe


class VivoV1986ARecipeTests(unittest.TestCase):
    def load(self, phone):
        scope, _ = load_recipe(phone, ROOT / "recipes/vivo-V1986A/recipe.py")
        return scope

    def test_actual_model_selects_own_recipe_not_reference(self):
        path, reference = run.recipe_for("V1986A", "vivo")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "vivo-V1986A")
        self.assertEqual(run.recipe_meta(path)["build"], "PD1986_A_8")
        self.assertEqual(run.recipe_meta(path)["steps"], ["系统广告", "阅图锁屏", "应用商店"])

    def test_recorded_build_matches_this_rom_and_small_update_keeps_safe_mode(self):
        self.assertTrue(run.build_ok({"build": "PD1986_A_8.21.29", "os": ""}, "PD1986_A_8"))
        self.assertFalse(run.build_ok({"build": "PD1986_A_9.1.2", "os": ""}, "PD1986_A_8"))

    def test_about_row_clicked_on_subtitle_row_not_title_text(self):
        p = Mock(W=1080, H=2400)
        p.texts.return_value = [
            ("关于", (72, 2119, 192, 2190), {}),
            ("包括禁用服务设置、个性化推荐服务设置…", (72, 2190, 918, 2288), {}),
        ]
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            self.assertTrue(scope["tap_row"]("包括禁用服务设置"))
        p.click.assert_called_once_with(432, 2239)

    def test_my_tab_falls_back_to_bottom_nav_coordinates(self):
        p = Mock(W=1080, H=2400)
        p.find.return_value = None
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"):
            scope["my_tab"]()
        p.click.assert_called_once_with(972, 2304)


if __name__ == "__main__":
    unittest.main()
