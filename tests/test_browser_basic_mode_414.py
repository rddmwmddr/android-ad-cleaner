"""#414：拒绝浏览器协议后落到基本模式设置页，浏览器段要说明原因并跳过。

REDMI K100（M786BC）上拒绝协议后进入 `BasicModeSettingActivity`，隐私和安全、主页、
搜索、功能设置都不在这一页；旧脚本照常找入口，43 秒后报「设置入口未找到」。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import phone_mock

RECIPE = ROOT / "recipes/xiaomi-M154FF/recipe.py"
BASIC = "com.android.browser/com.android.browser.basicmode.BasicModeSettingActivity"
HOME = "com.android.browser/com.android.browser.MainActivity"


class BrowserBasicModeTests(unittest.TestCase):
    def run_browser_step(self, focus):
        """只跑「浏览器」一段：点、返回、入口探测都是 Mock，记录调用。"""
        p = phone_mock()
        p.locked = lambda: False
        p.focus.return_value = focus
        p.tree.return_value = fast.ET.fromstring('<hierarchy rotation="0"></hierarchy>')
        p.find.return_value = None
        p.texts.return_value = []
        scope = {"p": p, "ONLY": ["浏览器"]}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(RECIPE.read_text(encoding="utf-8"), str(RECIPE), "exec"), scope)
        return p, out.getvalue()

    def test_basic_mode_page_is_skipped_with_a_readable_reason(self):
        p, out = self.run_browser_step(BASIC)
        p.start.assert_called_once_with("com.android.browser")
        self.assertIn("基本模式", out)
        self.assertNotIn("出错", out)
        p.click.assert_not_called()
        p.tap.assert_not_called()
        p.back.assert_not_called()
        p.entry.assert_not_called()

    def test_normal_home_page_still_goes_through_the_settings_entries(self):
        p, out = self.run_browser_step(HOME)
        p.start.assert_called_once_with("com.android.browser")
        self.assertNotIn("基本模式", out)
        self.assertIn("浏览器设置入口未找到", out)


if __name__ == "__main__":
    unittest.main()
