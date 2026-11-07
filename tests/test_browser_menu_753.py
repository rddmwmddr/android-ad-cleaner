"""#753：vivo 浏览器段点开菜单后，「设置」还没画出来菜单就被当成弹窗关掉了，整段跳过。

报告者借 recipes/vivo-V2547DA 跑 V2217A，日志是「弹窗点了 ✕（返回 com.vivo.browser:id/iv_back_cancel）」
接着「设置」没找到；同一个节点手工 p.tap("设置", exact=True) 一次就进去了。两处判据：

- dismiss() 把 content-desc + resource-id 丢进 CLOSE 正则，裸词 cancel 命中了菜单自己的返回键
  （desc 读作「返回」），点一下就把刚打开的菜单收起来；
- 脚本靠 tap(scrolls=0) 的等待循环找菜单项，而这个循环本身就在调 dismiss()。

四个同形脚本（V2547DA、Android 17 变体、V2309A、V2303A）的浏览器段入口一起改。
"""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import Clock, fake_phone, install_clock, load_recipe, phone_mock, phone_stub

RECIPES = [ROOT / "recipes/vivo-V2547DA/recipe.py",
           ROOT / "recipes/vivo-V2547DA/recipe_android17.py",
           ROOT / "recipes/vivo-V2309A/recipe.py",
           ROOT / "recipes/vivo-V2303A/recipe.py"]

# vivo 浏览器右上菜单弹层：右上角是浮层自己的返回键（desc「返回」，id 里带 cancel），
# 下面才是「设置」那一行。
MENU_PAGE = '''<hierarchy>
  <node package="com.vivo.browser" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="返回" clickable="true"
          resource-id="com.vivo.browser:id/iv_back_cancel" bounds="[40,120][140,220]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[100,700][900,800]" />
  </node>
</hierarchy>'''

# 真正的弹窗 ✕：纯图标、desc 读作「关闭」，页面上没有开关也没有可滚动列表
POPUP_PAGE = '''<hierarchy>
  <node package="com.vivo.browser" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.LinearLayout" bounds="[100,600][980,1400]">
      <node class="android.widget.TextView" text="发现新版本" bounds="[140,660][900,720]" />
      <node class="android.widget.ImageView" content-desc="关闭" clickable="true"
            resource-id="com.vivo.browser:id/iv_close" bounds="[900,600][990,690]" />
    </node>
  </node>
</hierarchy>'''

SETTINGS = "com.vivo.browser/com.vivo.browser.setting.SettingActivity"


def dismiss_phone(page, focus="com.vivo.browser/com.vivo.browser.BrowserActivity"):
    p = phone_stub("test", d=Mock(), W=1080, H=2400)
    p.tree = Mock(return_value=ET.fromstring(page))
    p.focus = Mock(return_value=focus)
    p.app = "com.vivo.browser"
    p.click = Mock()
    return p


class DismissBackButtonTests(unittest.TestCase):
    def test_menu_back_button_is_not_treated_as_a_popup_close(self):
        """菜单的返回键 id 里有 cancel：点了会把刚打开的浮层关掉，入口再也找不到。"""
        p = dismiss_phone(MENU_PAGE)
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.click.assert_not_called()

    def test_a_real_popup_close_is_still_clicked(self):
        """旧树也绿，守的是不回退：desc 读作「关闭」的浮层 ✕ 照旧要关掉。"""
        p = dismiss_phone(POPUP_PAGE)
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        p.click.assert_called_once_with(945, 645)

    def test_an_english_or_padded_back_label_is_skipped_too(self):
        """真机 dump 的 desc 可能带首尾空白、也可能是英文界面：按同一判据排掉。"""
        p = dismiss_phone(MENU_PAGE.replace('content-desc="返回"', 'content-desc=" Back "'))
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
        p.click.assert_not_called()


def menu_phone(**fields):
    p = phone_mock(W=1080, H=2400, **fields)
    p.locked.return_value = False
    p.start.return_value = None
    p.back.return_value = None
    p.click.return_value = None
    p.sig.return_value = "sig"
    p.await_page.return_value = True
    p.settle.return_value = True
    p.in_settings_page.return_value = True
    p.find.return_value = (540, 750)
    p.entry.return_value = False
    p.off.return_value = None
    p.top.return_value = None
    p.focus.return_value = SETTINGS
    p.d.return_value.click_exists.return_value = True
    return p


def run_browser(p, path):
    scope, out = load_recipe(p, path, only=["浏览器"])
    return scope, out.getvalue()


class VivoBrowserMenuTests(unittest.TestCase):
    def test_menu_row_is_clicked_without_dismissing_the_menu(self):
        """入口改成只等那一行画出来再点：不经过会关弹窗的 tap()。"""
        for path in RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                scope, _ = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                p.d.assert_any_call(resourceId="com.vivo.browser:id/menu_btn")
                p.click.assert_called_once_with(540, 750)
                self.assertNotIn("设置", [c.args[0] for c in p.tap.call_args_list if c.args])
                self.assertEqual(["首页设置", "网页浏览设置", "更多设置", "隐私权限设置"],
                                 [c.args[0] for c in p.entry.call_args_list])

    def test_reopens_the_menu_once_when_the_first_click_lands_elsewhere(self):
        """第一轮点完没进设置页：退回收起浮层、重开菜单再试一次。"""
        for path in RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                p.in_settings_page.side_effect = [False, True]
                scope, _ = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(2, p.d.return_value.click_exists.call_count)
                self.assertIn(call(), p.back.call_args_list)     # 退回收起浮层，重开菜单
                self.assertIn("首页设置", [c.args[0] for c in p.entry.call_args_list])

    def test_skips_the_section_when_the_browser_has_no_menu_button(self):
        """别的型号没有这个按钮（最多等 3 秒）：算本机没有这个入口，打印一句后跳过本段。"""
        for path in RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                p.d.return_value.click_exists.return_value = False
                scope, out = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("没有右上菜单按钮", out)
                p.back.assert_not_called()
                p.click.assert_not_called()

    def test_a_menu_without_the_settings_row_fails_the_step_loudly(self):
        """菜单开了却两轮都认不出设置页：必需入口没打开，记进 FAILED_STEPS，不再静默算成功。"""
        for path in RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                p = menu_phone()
                p.find.return_value = None
                scope, out = run_browser(p, path)
                self.assertEqual(["浏览器"], scope["FAILED_STEPS"])
                self.assertIn("浏览器设置页没有打开", out)
                p.entry.assert_not_called()
                self.assertEqual(2, p.d.return_value.click_exists.call_count)


BOTTOM_MENU_PAGE = '''<hierarchy>
  <node package="com.vivo.browser" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="返回" clickable="true"
          resource-id="com.vivo.browser:id/iv_back_cancel" bounds="[40,120][140,220]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[100,2250][900,2320]" />
  </node>
</hierarchy>'''


class _MenuButton:
    """p.d 的门面：既能按 uiautomator2 的选择器调用（找右上角按钮），又照旧当读屏 adapter 用。"""

    def __init__(self, device):
        self._device = device

    def __call__(self, **selectors):
        return self

    def click_exists(self, timeout=3):
        return True

    def __getattr__(self, name):
        return getattr(self._device, name)


class VivoBrowserRealPageTests(unittest.TestCase):
    """走真 find() 与真 clicks：把「设置」那一行放到底部 8% 带里，验证等待用的是带 edge_ok 的查找。"""

    def test_a_row_at_the_bottom_of_the_sheet_is_clicked(self):
        for path in RECIPES:
            with self.subTest(path=path.parent.name + "/" + path.name):
                clock = Clock()
                original = fast.time
                install_clock(fast, clock)
                self.addCleanup(setattr, fast, "time", original)
                clicks = []
                p = fake_phone(clock=clock, size=(1080, 2400), stages=[(0.0, BOTTOM_MENU_PAGE)],
                               focus=((0.0, "com.vivo.browser/.BrowserActivity"),),
                               click=lambda x, y: clicks.append((x, y)))
                p.start = lambda *a, **k: None
                p.await_page = lambda *a, **k: True
                p.settle = lambda *a, **k: True
                p.in_settings_page = lambda: True
                p.back = lambda *a, **k: None
                p.top = lambda *a, **k: None
                p.entry = lambda *a, **k: False
                p.off = lambda *a, **k: None
                p.d = _MenuButton(p.reader)
                scope, _ = run_browser(p, path)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual([(500, 2285)], clicks)      # 菜单那一行，不是上面那个「返回」✕


if __name__ == "__main__":
    unittest.main()
