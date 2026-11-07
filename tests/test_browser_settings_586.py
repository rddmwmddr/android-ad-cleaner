"""#586：小米 / 红米浏览器段进设置页要校验落点。

浏览器 20.30 在首页工具栏右上角还有一个叫「设置」的图标，底部「菜单」的弹窗还没画出来时
按文字点会落到它上面，进的是首页编辑面板；后面几页入口全部找不到，整段 0 项又不报错。
两条时间轴：落到工具栏面板时不点任何开关并报出停在哪一页；正常进设置页时照常走到目标行。
"""
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, call

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import Clock, fake_phone, install_clock, load_recipe, phone_mock

XIAOMI = ROOT / "recipes/xiaomi-24129PN74C"
RECIPES = ("recipe.py", "recipe_os4.py")
REDMI_K70 = ROOT / "recipes/redmi-23113RKC6C/recipe.py"
XIAOMI_17U = ROOT / "recipes/xiaomi-2512BPNDAC/recipe.py"

BROWSER = "com.android.browser/.BrowserActivity"
BROWSER_SETTINGS = "com.android.browser/.BrowserSettingsActivity"
ADS = call(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全")

# 首页：底部「菜单」标签 + 工具栏右上角那个也叫「设置」的图标（y≈144，点它是 #586 的错路）
HOME = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true" bounds="[960,96][1056,192]" />
    <node class="android.widget.TextView" text="主页" bounds="[0,2280][216,2400]" />
    <node class="android.widget.TextView" text="菜单" bounds="[432,2280][648,2400]" />
  </node>
</hierarchy>"""

# 点完「菜单」从底部升起的弹窗。两份「设置」卡在 0.3 屏高两侧（2400 屏上是 y=720）：
# 上面那份（top=700）是压在判据上的诱饵，只差 20 像素就会抢走点击，必须点不到。
POPUP = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true" bounds="[960,96][1056,192]" />
    <node class="android.widget.TextView" text="头像" bounds="[48,600][600,700]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[720,700][1020,760]" />
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[720,730][1020,790]" />
  </node>
</hierarchy>"""

# 点到工具栏那个「设置」之后落的页：首页编辑面板，Activity 不是设置页
TOOLBAR_PANEL = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="页面布局" bounds="[48,300][600,400]" />
    <node class="android.widget.TextView" text="快捷网址" bounds="[48,420][600,520]" />
    <node class="android.widget.TextView" text="全网热榜" bounds="[48,540][600,640]" />
  </node>
</hierarchy>"""

SETTINGS = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="隐私和安全" clickable="true" bounds="[48,320][600,420]" />
    <node class="android.widget.TextView" text="搜索设置" clickable="true" bounds="[48,440][600,540]" />
  </node>
</hierarchy>"""

DECOY_SETTING = (870, 730)           # top=700：在 0.3 屏高之上，不该被点到
POPUP_SETTING = (870, 760)           # top=730：刚过 0.3 屏高，弹窗里那一行
TOOLBAR_SETTING_Y = 144              # 工具栏图标的 y


def timeline_phone(stages, focus, clicked=None):
    """假手机 + 播放时间轴：一次点击/返回换一页，页面由时间轴决定。"""
    clock = Clock(click_cost=2.0)
    install_clock(fast, clock)
    p = fake_phone(clock=clock, size=(1080, 2400), stages=stages, focus=focus)
    if clicked is not None:
        p.click = lambda x, y: (clicked.append((x, y)), clock.click())[1]
    p.start = Mock(return_value=True)
    p.off = Mock()
    return p


class XiaomiBrowserSettingsTests(unittest.TestCase):
    def browser_step(self, p, recipe):
        scope, out = load_recipe(p, XIAOMI / recipe, only="浏览器")
        return scope, out.getvalue()

    def test_lands_in_settings_page_and_walks_to_the_target_row(self):
        """正常路径：菜单 → 弹窗「设置」→ BrowserSettingsActivity，后面的行照常处理。"""
        expected = {
            # OS3 这份还要处理「显示猜你想搜模块」，也就是 #281 手动补上的那一项
            "recipe.py": [ADS, call(only=["显示猜你想搜模块"], page="浏览器·搜索设置")],
            "recipe_os4.py": [ADS],
        }
        self.addCleanup(setattr, fast, "time", fast.time)
        for name in RECIPES:
            with self.subTest(recipe=name):
                p = timeline_phone([(0.0, HOME), (1.0, POPUP), (3.0, SETTINGS)],
                                   focus=((0.0, BROWSER), (3.0, BROWSER_SETTINGS)))
                scope, _out = self.browser_step(p, name)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(p.off.call_args_list, expected[name])

    def test_toolbar_panel_is_not_taken_for_the_settings_page(self):
        """落到工具栏面板时：不点任何开关、不在面板上找子页，报出停在哪一页。"""
        self.addCleanup(setattr, fast, "time", fast.time)
        for name in RECIPES:
            with self.subTest(recipe=name):
                clicked = []
                p = timeline_phone([(0.0, HOME), (1.0, POPUP), (3.0, TOOLBAR_PANEL),
                                    (5.0, HOME), (7.0, POPUP), (9.0, TOOLBAR_PANEL), (11.0, HOME)],
                                   focus=((0.0, BROWSER),), clicked=clicked)
                scope, out = self.browser_step(p, name)
                self.assertEqual(scope["FAILED_STEPS"], ["浏览器"])
                p.off.assert_not_called()
                self.assertIn("浏览器设置页没有打开", out)
                self.assertIn(BROWSER, out)
                # 两次都只点弹窗那一行：0.3 屏高之上的两份「设置」一次都没碰
                self.assertEqual(clicked.count(POPUP_SETTING), 2)
                self.assertNotIn(DECOY_SETTING, clicked)
                self.assertNotIn(TOOLBAR_SETTING_Y, [y for _x, y in clicked])


class RedmiBrowserSettingsTests(unittest.TestCase):
    def test_my_page_reaches_settings_and_retries_once(self):
        """K70 走「我的 → 设置」：第一次落空要退回来再点一次，第二次认出设置页就算成功。"""
        p = phone_mock()
        p.tap.return_value = True
        p.in_settings_page.side_effect = [False, True]
        scope, _ = load_recipe(p, REDMI_K70)
        scope["mine_settings"]()
        self.assertEqual(p.tap.call_args_list,
                         [call("我的", exact=True, scrolls=0), call("设置", exact=True, scrolls=0)] * 2)
        p.back.assert_called_once()

    def test_my_page_never_lands_reports_the_page_it_stopped_on(self):
        p = phone_mock()
        p.tap.return_value = True
        p.in_settings_page.return_value = False
        p.focus.return_value = BROWSER
        scope, _ = load_recipe(p, REDMI_K70)
        with self.assertRaisesRegex(RuntimeError, f"浏览器设置页没有打开；停在 {BROWSER}"):
            scope["mine_settings"]()
        self.assertEqual(p.back.call_count, 2)


class Xiaomi17UltraBrowserSettingsTests(unittest.TestCase):
    """2512BPNDAC 按 resource-id 点两个按钮，要点不到工具栏那个；落点仍要校验（#586）。"""

    PAGE = """<hierarchy rotation="0">
      <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
        <node class="android.widget.ImageView" resource-id="com.android.browser:id/action_more"
              clickable="true" bounds="[432,2280][648,2400]" />
        <node class="android.widget.TextView" resource-id="com.android.browser:id/action_menu_setting"
              clickable="true" bounds="[720,1100][1020,1200]" />
      </node>
    </hierarchy>"""

    def mock_phone(self, settings_after_click):
        p = phone_mock()
        p.tree.return_value = ET.fromstring(self.PAGE)
        p.focus.return_value = BROWSER
        p.in_settings_page.side_effect = settings_after_click
        return p

    def test_settings_page_is_reached(self):
        p = self.mock_phone([True])
        scope, _ = load_recipe(p, XIAOMI_17U)
        scope["menu_settings"]()
        self.assertEqual([c.args for c in p.click.call_args_list],
                         [(540, 2340), (870, 1150)])
        p.back.assert_not_called()

    def test_wrong_landing_retries_then_reports_the_page(self):
        p = self.mock_phone([False, False])
        scope, _ = load_recipe(p, XIAOMI_17U)
        with self.assertRaisesRegex(RuntimeError, "浏览器设置页没有打开"):
            scope["menu_settings"]()
        self.assertEqual(p.back.call_count, 2)


if __name__ == "__main__":
    unittest.main()
