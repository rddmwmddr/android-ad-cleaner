"""同一型号按系统版本选机型脚本变体（PR #338），以及变体要进安装包。不用手机。"""
from pathlib import Path
import sys
import unittest

from gui.bundle_data import bundle_data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run


class VariantTests(unittest.TestCase):
    def pick(self, model, brand, os_, build):
        path, reference = run.recipe_for(model, brand, {"os": os_, "build": build})
        self.assertFalse(reference)
        return Path(path).relative_to(ROOT / "recipes").as_posix()

    def test_xiaomi_15_hyperos_3_and_4(self):
        # #312 是 HyperOS 3，#298 是 HyperOS 4：同一型号两份，按系统版本选
        self.assertEqual(self.pick("24129PN74C", "Xiaomi", "OS3.0.307.0.WOCCNXM", "BP2A.250605.031.A3"),
                         "xiaomi-24129PN74C/recipe.py")
        self.assertEqual(self.pick("24129PN74C", "Xiaomi", "OS4.0.0.22.XOCCNXM", "CP2A.260605.016"),
                         "xiaomi-24129PN74C/recipe_os4.py")

    def test_oneplus_ace_2_android_15(self):
        self.assertEqual(self.pick("PHK110", "OnePlus", "", "PHK110_15.0.0.601(CN01)"), "oneplus-PHK110/recipe_android15.py")
        self.assertEqual(self.pick("PHK110", "OnePlus", "", "PHK110_16.0.5.701(CN01)"), "oneplus-PHK110/recipe.py")

    def test_vivo_x300_ultra_satellite_android_17(self):
        # #220：同一型号升到 Android 17 后商店入口换了，路径按系统版本分开
        self.assertEqual(self.pick("V2547DA", "vivo", "", "PD2547D_A_17.1.10.2.W10"),
                         "vivo-V2547DA/recipe_android17.py")
        self.assertEqual(self.pick("V2547DA", "vivo", "", "PD2547D_A_16.0.22.14.W10"),
                         "vivo-V2547DA/recipe.py")

    def test_variants_are_packaged(self):
        shipped = {Path(src).relative_to(ROOT).as_posix() for src, _ in bundle_data(ROOT)}
        for variant in ROOT.glob("recipes/*/recipe_*.py"):
            self.assertIn(variant.relative_to(ROOT).as_posix(), shipped)


if __name__ == "__main__":
    unittest.main()
