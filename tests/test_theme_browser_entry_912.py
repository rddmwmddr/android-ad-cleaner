"""#912：浏览器段直达优先，主题段用底栏 tab 进「我的」。

报告者那台 Xiaomi 15 Pro（2410DPN6CC）两条入口都断在同一处：入口靠 `gear()` 读一次界面树、
点一次图标，没有等待也没有第二入口。反过来，浏览器设置页有导出，`am start -n
com.android.browser/.BrowserSettingsActivity` 实测能直接落过去；主题「我的」在底栏只有
content-desc（读作「未选中,我的」），而内容区还有「我的点赞 / 我的收藏 / 我的订单」。

三条行为各一组用例：直达成功；直达落空按「菜单」→「我的」回退；主题 tab 命中的是底栏。
页面节点取自报告者贴的 dump（1080×2400）。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import Clock, fake_phone, install_clock, load_recipe, phone_mock

RECIPE = ROOT / "recipes/xiaomi-24129PN74C/recipe.py"
BROWSER_HOME = "com.android.browser/com.android.browser.BrowserActivity"
BROWSER_BASIC = "com.android.browser/com.android.browser.basicmode.BasicModeSettingActivity"

# 底栏没有「菜单」，只有「我的」（MIX Flip 2 那类布局）
BOTTOM_WITHOUT_MENU = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="主页" bounds="[0,2280][216,2400]" />
    <node class="android.widget.TextView" text="视频" bounds="[216,2280][432,2400]" />
    <node class="android.widget.TextView" text="免费小说" bounds="[648,2280][864,2400]" />
    <node class="android.widget.TextView" text="我的" bounds="[864,2280][1080,2400]" />
  </node>
</hierarchy>"""

# 报告者那台机浏览器「我的」页：顶部图标只有 content-desc、自身可点，底栏标签也只有 desc
BROWSER_MINE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_scan"
          content-desc="扫一扫" clickable="true" bounds="[538,139][654,255]" />
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_incognito"
          content-desc="无痕模式" clickable="true" bounds="[666,139][782,255]" />
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_night_mode"
          content-desc="夜间模式" clickable="true" bounds="[794,139][910,255]" />
    <node class="android.widget.ImageView" resource-id="com.android.browser:id/iv_personal_settings"
          content-desc="设置" clickable="true" bounds="[922,139][1038,255]" />
    <node class="android.view.ViewGroup" resource-id="com.android.browser:id/action_person"
          content-desc="我的已选中" clickable="true" bounds="[864,2226][1080,2355]">
      <node class="android.widget.TextView" text="我的" clickable="false" bounds="[942,2307][1002,2348]" />
    </node>
  </node>
</hierarchy>"""

# 主题「我的」页：内容区三行「我的…」，底栏只有 content-desc 的标签，右上是只有 desc 的图标
THEME_MINE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.thememanager" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="我的点赞" clickable="true" bounds="[48,700][400,780]" />
    <node class="android.widget.TextView" text="我的收藏" clickable="true" bounds="[48,800][400,880]" />
    <node class="android.widget.TextView" text="我的订单" clickable="true" bounds="[48,900][400,980]" />
    <node class="android.widget.ImageView" resource-id="com.android.thememanager:id/settings"
          content-desc="设置" clickable="true" bounds="[967,200][1044,277]" />
    <node class="android.widget.RelativeLayout" content-desc="未选中,我的" clickable="true"
          bounds="[776,2212][1011,2355]" />
  </node>
</hierarchy>"""

# 同一页，顶部那一排图标这一帧还没画出来（「设置」晚一帧进树）
THEME_MINE_EARLY = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.thememanager" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="我的点赞" clickable="true" bounds="[48,700][400,780]" />
    <node class="android.widget.RelativeLayout" content-desc="未选中,我的" clickable="true"
          bounds="[776,2212][1011,2355]" />
  </node>
</hierarchy>"""

THEME_MINE_FOCUS = "com.android.thememanager/.ThemeResourceProxyTabActivity"
BROWSER_GEAR = (980, 197)           # iv_personal_settings 的中心
THEME_GEAR = (1005, 238)            # com.android.thememanager:id/settings 的中心
MINE_TAB_CENTER = (893, 2283)
BROWSER_MINE_TAB = (972, 2327)      # action_person 里那个「我的」文字
CONTENT_CENTERS = [(224, 740), (224, 840), (224, 940)]      # 「我的点赞 / 收藏 / 订单」


class ClockCase(unittest.TestCase):
    """假时钟装进 fast：Phone 里的等待都按假时间走。"""

    def install(self):
        original = fast.time
        clock = Clock()
        install_clock(fast, clock)
        self.addCleanup(setattr, fast, "time", original)
        self.clock = clock
        return clock


class BrowserDirectTests(ClockCase):
    def browser_phone(self, stages, focus):
        clock = self.install()
        p = fake_phone(clock=clock, size=(1080, 2400), stages=stages, focus=focus)
        p.entry = Mock(return_value=False)          # 后面几页入口不在这一段要测的东西里
        p.back = Mock()                             # 结尾的 back(2) 不算「点过什么」
        return p, clock

    def test_direct_settings_page_is_tried_before_the_menu(self):
        """直达落在设置页时，只拉起这一个页面：不走「菜单」，也不点底栏「我的」。"""
        started = []
        p, clock = self.browser_phone([(0.0, BROWSER_MINE)], ((0.0, BROWSER_HOME),))

        def start(pkg, activity=None, **kw):
            started.append((pkg, activity))
            if activity:
                p.screen.focus = lambda: f"{pkg}/{activity}"
        p.start = start
        scope, out = load_recipe(p, RECIPE, only="浏览器")
        self.assertIn("直达浏览器设置页", out.getvalue())
        self.assertEqual(started, [("com.android.browser", ".BrowserSettingsActivity")])
        self.assertEqual(clock.clicks, 0)           # 底栏一个都没点
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_falls_back_to_the_menu_then_my_tab(self):
        """直达落空时按「菜单」→「我的」→ 齿轮走，用的是报告者贴的「我的」页节点。"""
        clicked = []
        p, clock = self.browser_phone([(0.0, BROWSER_MINE)], ((0.0, BROWSER_HOME),))
        p.click = lambda x, y: (clicked.append((x, y)), clock.click())[1]
        p.in_settings_page = Mock(return_value=True)    # 落点判据由 #960 的用例守

        def start(pkg, activity=None, **kw):
            if activity:
                raise RuntimeError("无法打开")
        p.start = start
        scope, out = load_recipe(p, RECIPE, only="浏览器")
        self.assertIn("· 底栏没有「菜单」，改走「我的」→ 设置", out.getvalue())
        self.assertEqual(clicked, [BROWSER_MINE_TAB, BROWSER_GEAR])
        p.in_settings_page.assert_called_once_with()
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_basic_mode_page_is_still_skipped_after_trying_the_direct(self):
        """基本模式的机型直达会落到 BasicModeSettingActivity：落点判不过，仍按跳过收尾（#414）。"""
        p, clock = self.browser_phone([(0.0, BOTTOM_WITHOUT_MENU)], ((0.0, BROWSER_BASIC),))
        p.start = Mock()                            # 拉起不改变前台，两张页面都不认
        scope, out = load_recipe(p, RECIPE, only="浏览器")
        self.assertIn("基本模式", out.getvalue())
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(clock.clicks, 0)

    def test_entry_failure_reports_the_page_evidence(self):
        """两条回退都不通时，收尾行带页面现场（与「到了但页面不对」同形）。"""
        p, _clock = self.browser_phone([(0.0, BOTTOM_WITHOUT_MENU)], ((0.0, BROWSER_HOME),))

        def start(pkg, activity=None, **kw):
            if activity:
                raise RuntimeError("无法打开")
        p.start = start
        p.tab = Mock(return_value=False)            # 底栏也没有「我的」
        scope, out = load_recipe(p, RECIPE, only="浏览器")
        text = out.getvalue()
        self.assertEqual(scope["FAILED_STEPS"], ["浏览器"])
        self.assertIn(f"浏览器底部没有「菜单」，也没有「我的」标签；停在 {BROWSER_HOME}", text)
        self.assertIn("当次读到 0 个开关", text)      # 现场是 page_evidence() 的四段，不是一句 focus


class ThemeSettingsTests(ClockCase):
    """主题「我的」：底栏标签只有 desc、内容区有同名文字，齿轮晚一帧进树。"""

    def setUp(self):
        clock = self.install()
        self.clicked = []
        self.p = fake_phone(clock=clock, size=(1080, 2400), stages=[(0.0, THEME_MINE)],
                            focus=((0.0, THEME_MINE_FOCUS),))
        self.p.click = lambda x, y: (self.clicked.append((x, y)), clock.click())[1]

    def load(self):
        scope, _ = load_recipe(self.p, RECIPE)
        scope["time"] = self.clock        # 脚本级等待也走同一只假钟
        return scope

    def test_my_tab_hits_the_bottom_bar_not_the_content_rows(self):
        scope = self.load()
        scope["gear"] = Mock(return_value=True)
        with contextlib.redirect_stdout(io.StringIO()):
            scope["theme_settings"]()
        self.assertEqual(self.clicked, [MINE_TAB_CENTER])
        for center in CONTENT_CENTERS:
            self.assertNotIn(center, self.clicked)
        scope["gear"].assert_called_once_with()

    def test_settings_icon_showing_up_late_is_waited_for(self):
        """图标前一帧还不在树里：等它进树再交给 gear()，齿轮照样点得中。

        去掉那次等待，gear() 的第一帧快照看到的是没有图标的页面，两次都失败（返红）。"""
        p = phone_mock()
        p.locked = lambda: False
        p.W, p.H = 1080, 2400
        p.tab.return_value = True
        p.find.return_value = None
        p.tap.return_value = False
        p.in_settings_page.return_value = True
        pages = [ET.fromstring(THEME_MINE_EARLY), ET.fromstring(THEME_MINE_EARLY),
                 ET.fromstring(THEME_MINE)]
        p.screen.tree.side_effect = lambda: pages[min(p.tree.call_count - 1, len(pages) - 1)]
        scope, _ = load_recipe(p, RECIPE)
        with contextlib.redirect_stdout(io.StringIO()):
            scope["theme_settings"]()
        p.click.assert_called_once_with(*THEME_GEAR)
        self.assertGreaterEqual(p.tree.call_count, 4)   # 等的那几帧 + gear() 自己那一帧

    def test_two_misses_report_the_page_evidence(self):
        scope = self.load()
        scope["gear"] = Mock(return_value=False)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, f"主题设置入口没找到；停在 {THEME_MINE_FOCUS}"):
                scope["theme_settings"]()
        self.assertEqual(scope["gear"].call_count, 2)


if __name__ == "__main__":
    unittest.main()
