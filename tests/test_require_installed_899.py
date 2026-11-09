"""OPPO / 一加机型脚本的 require_installed()：没装的包 `pm path` 返回退出码 1、输出为空，
那是「没装、跳过本段」，不是「读不出安装状态」（#899，0.4.1 报告 9–10 份）。"""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
from fixtures import load_recipe, phone_mock

RECIPES = ("recipes/oppo-PMX110/recipe.py", "recipes/oneplus-PLZ110/recipe.py")


class RequireInstalledTests(unittest.TestCase):
    def check(self, recipe, output, code):
        p = phone_mock()
        p.d.shell = Mock(return_value=SimpleNamespace(output=output, exit_code=code))
        with contextlib.redirect_stdout(io.StringIO()):
            scope, _ = load_recipe(p, ROOT / recipe, only="__none__")
        return scope

    def test_installed_passes(self):
        for recipe in RECIPES:
            with self.subTest(recipe=recipe):
                scope = self.check(recipe, "package:/data/app/x/base.apk\n", 0)
                self.assertIsNone(scope["require_installed"]("com.heytap.yoli", "视频"))

    def test_not_installed_skips_the_segment(self):
        for recipe in RECIPES:
            for code in (1, 0):          # adb shell v2 带回 1；不带回退出码的通道是 0
                with self.subTest(recipe=recipe, code=code):
                    scope = self.check(recipe, "", code)
                    with self.assertRaisesRegex(scope["SkipStep"], "本机未安装视频"):
                        scope["require_installed"]("com.heytap.yoli", "视频")

    def test_real_error_still_fails(self):
        for recipe in RECIPES:
            with self.subTest(recipe=recipe):
                scope = self.check(recipe, "Exception occurred while executing 'path'\n", 255)
                with self.assertRaises(Exception) as caught:
                    scope["require_installed"]("com.heytap.yoli", "视频")
                self.assertNotIsInstance(caught.exception, scope["SkipStep"])
                self.assertIn("无法读取视频安装状态", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
