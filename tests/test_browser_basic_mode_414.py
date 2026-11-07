"""#414：拒绝浏览器协议后落到基本模式设置页，浏览器段要说明原因并跳过。

REDMI K100（M786BC）上拒绝协议后进入 `BasicModeSettingActivity`，隐私和安全、主页、
搜索、功能设置都不在这一页；旧脚本照常找入口，43 秒后报「设置入口未找到」。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/xiaomi-M154FF/recipe.py"
BASIC = "com.android.browser/com.android.browser.basicmode.BasicModeSettingActivity"
HOME = "com.android.browser/com.android.browser.MainActivity"


class BrowserBasicModeTests(unittest.TestCase):
    def run_browser_step(self, focus):
        """只跑「浏览器」一段：点、返回、入口探测都是 Mock，记录调用。
        M154FF 先试直达（#667）。基本模式下设置页会被转走，直达落不到预期页，才走到这里测的老路。"""
        def start(pkg, activity=None, **kw):
            if activity:
                raise RuntimeError("启动后停在非预期页面")

        p = phone_mock()
        p.start.side_effect = start
        p.locked = lambda: False
        p.focus.return_value = focus
        p.tree.return_value = fast.ET.fromstring('<hierarchy rotation="0"></hierarchy>')
        p.find.return_value = None
        p.texts.return_value = []
        _, out = load_recipe(p, RECIPE, ["浏览器"])
        return p, out.getvalue()

    def test_basic_mode_page_is_skipped_with_a_readable_reason(self):
        p, out = self.run_browser_step(BASIC)
        # 先试一次直达，落空后才裸拉起首页：两次调用，顺序固定
        self.assertEqual([c.args for c in p.start.call_args_list],
                         [("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity"),
                          ("com.android.browser",)])
        self.assertIn("基本模式", out)
        self.assertNotIn("出错", out)
        p.click.assert_not_called()
        p.tap.assert_not_called()
        p.back.assert_not_called()
        p.entry.assert_not_called()

    def test_normal_home_page_still_goes_through_the_settings_entries(self):
        p, out = self.run_browser_step(HOME)
        self.assertEqual([c.args for c in p.start.call_args_list],
                         [("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity"),
                          ("com.android.browser",)])
        self.assertNotIn("基本模式", out)
        self.assertIn("浏览器设置入口未找到", out)


if __name__ == "__main__":
    unittest.main()
