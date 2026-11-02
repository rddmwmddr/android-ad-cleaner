"""#460：其余小米 / 红米脚本在浏览器基本模式页也要说明原因并跳过。

#414 只给了 xiaomi-M154FF 这条判定；其余七份同款浏览器段（browser_settings()、
require(p.tap(...))、by_id 与 recipe_os4.py 的 monkey 拉起几种形状）在拒绝协议落到
`BasicModeSettingActivity` 时仍会整段空转后报「入口未找到 / 未找到浏览器…」。加载方式与
#414 的测试相同——机型脚本按约定在注入的 `p` 上运行，这里用 runpy 按文件路径执行并注入假设备。
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
    (ROOT / "recipes/xiaomi-25102RKBEC/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/redmi-25060RK16C/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/xiaomi-24129PN74C/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/redmi-23113RKC6C/recipe.py", ("com.android.browser",)),
    (ROOT / "recipes/xiaomi-2512BPNDAC/recipe.py", ("com.android.browser",)),
    # 这份不走 p.start：强停后用 monkey 拉起
    (ROOT / "recipes/xiaomi-24129PN74C/recipe_os4.py", None),
    (ROOT / "recipes/redmi-24122RKC7C/recipe.py", ("com.android.browser", ".BrowserActivity")),
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
        for recipe, start_args in RECIPES:
            with self.subTest(recipe=str(recipe)):
                p, out = self.run_browser_step(recipe, BASIC)
                if start_args:
                    p.start.assert_called_once_with(*start_args)
                self.assertIn("== 浏览器", out)
                self.assertIn("基本模式", out)
                self.assertNotIn("出错", out)
                self.assertNotIn("未完成", out)
                p.click.assert_not_called()
                p.tap.assert_not_called()
                p.back.assert_not_called()
                p.entry.assert_not_called()

    def test_normal_home_page_still_goes_through_the_settings_entries(self):
        for recipe, start_args in RECIPES:
            with self.subTest(recipe=str(recipe)):
                p, out = self.run_browser_step(recipe, HOME)
                if start_args:
                    p.start.assert_called_once_with(*start_args)
                self.assertIn("== 浏览器", out)
                self.assertNotIn("基本模式", out)


if __name__ == "__main__":
    unittest.main()
