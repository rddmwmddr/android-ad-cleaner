"""PLP120 浏览器段转成数据（#1369）：三档入口各走一次，外加「直达也没打开」那条收尾。

快照在空页面上只走到「底栏我的」与「两个按钮都没有」两档；`p.tap(a) or p.tap(b)` 那档与
「设置页根本没打开」的提前收尾在这里补。转数据前的那棵树上这些用例也绿——守的是搬进
`if_find` / `if_lib_any` / `if_focus` 之后分支选择没有回退。
"""
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/oppo/PLP120/PLP120.toml"
BROWSER = "com.heytap.browser"


def run(*, found=(), focus="", tap=False, out=None):
    """跑浏览器段：`found` 是 `p.find` 认得出来的文字，`tap` 是 `p.tap` 的返回值。"""
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.focus.return_value = focus
    p.find.side_effect = lambda text, **kwargs: text in found
    p.tap.return_value = tap
    scope, _ = load_recipe(p, RECIPE, only="浏览器", out=out)
    return p, scope


class Plp120BrowserTests(unittest.TestCase):
    def test_the_menu_button_is_used_when_there_is_no_my_tab(self):
        # `find("菜单") or find("更多")`：第一个认得出来就不再找第二个。
        p, scope = run(found={"菜单"}, tap=True)
        self.assertEqual([c.args[0] for c in p.find.call_args_list], ["我的", "菜单"])
        self.assertEqual([c.args[0] for c in p.tap.call_args_list][:2], ["菜单", "设置"])
        self.assertEqual(p.tap.call_args_list[0].kwargs, {"scrolls": 0})
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_swallowed_first_tap_still_tries_the_second_button(self):
        p, _scope = run(found={"更多"}, tap=False)
        self.assertEqual([c.args[0] for c in p.tap.call_args_list][:3], ["菜单", "更多", "设置"])

    def test_a_settings_page_that_never_opens_ends_the_segment_before_any_switch(self):
        out = io.StringIO()
        p, scope = run(focus="com.android.launcher/com.android.launcher.Launcher", out=out)
        p.off.assert_not_called()
        p.back.assert_not_called()
        self.assertIn("浏览器设置页没有打开", out.getvalue())
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_the_direct_page_path_keeps_walking_when_the_browser_is_in_front(self):
        p, _scope = run(focus=f"{BROWSER}/.BrowserActivity", tap=True)
        self.assertEqual(p.tap.call_args_list[0].args[0], "主页设置")
        self.assertIn("BrowserPreferencesPage", p.shell.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
