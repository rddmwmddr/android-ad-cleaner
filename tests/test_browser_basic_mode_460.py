"""#460：其余小米 / 红米脚本在浏览器基本模式页也要说明原因并跳过。

#414 只给了 xiaomi-M154FF 这条判定；另外四份同款浏览器段（两份 browser_settings()
形状、两份 require(p.tap(...)) 形状）在拒绝协议落到 `BasicModeSettingActivity` 时
仍会整段空转后报「入口未找到 / 未找到浏览器…」。加载方式与 #414 的测试相同——
机型脚本按约定在注入的 `p` 上运行，这里用 runpy 按文件路径执行并注入假设备。
"""
import contextlib
import io
from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import phone_mock

BASIC = "com.android.browser/com.android.browser.basicmode.BasicModeSettingActivity"
HOME = "com.android.browser/com.android.browser.MainActivity"

RECIPES = (
    ROOT / "recipes/xiaomi-25102RKBEC/recipe.py",
    ROOT / "recipes/redmi-25060RK16C/recipe.py",
    ROOT / "recipes/xiaomi-24129PN74C/recipe.py",
    ROOT / "recipes/redmi-23113RKC6C/recipe.py",
)


class BrowserBasicMode460(unittest.TestCase):
    def run_browser_step(self, recipe, focus):
        """只跑「浏览器」一段：点、返回、入口探测都是 Mock，记录调用。"""
        p = phone_mock()
        p.locked = lambda: False
        p.focus.return_value = focus
        p.tree.return_value = fast.ET.fromstring('<hierarchy rotation="0"></hierarchy>')
        p.find.return_value = None
        p.texts.return_value = []
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            runpy.run_path(str(recipe), init_globals={"p": p, "ONLY": ["浏览器"]})
        return p, out.getvalue()

    def test_basic_mode_page_is_skipped_with_a_readable_reason(self):
        for recipe in RECIPES:
            with self.subTest(recipe=str(recipe)):
                p, out = self.run_browser_step(recipe, BASIC)
                p.start.assert_called_once_with("com.android.browser")
                self.assertIn("基本模式", out)
                self.assertNotIn("出错", out)
                p.click.assert_not_called()
                p.tap.assert_not_called()
                p.back.assert_not_called()
                p.entry.assert_not_called()

    def test_normal_home_page_still_goes_through_the_settings_entries(self):
        for recipe in RECIPES:
            with self.subTest(recipe=str(recipe)):
                p, out = self.run_browser_step(recipe, HOME)
                p.start.assert_called_once_with("com.android.browser")
                self.assertNotIn("基本模式", out)


if __name__ == "__main__":
    unittest.main()
