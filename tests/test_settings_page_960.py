"""#960：in_settings_page() 只认字面「Setting」，*PreferenceActivity / *PreferencesPage 被判成「没进设置页」。

小米主题商店、商店、浏览器、全局搜索的设置页有两套命名：一套类名带 Setting，另一套带
Preferences / Preference。后者点完齿轮一律判失败，gear() 退回上一页、返回 False，后面整段
在旧页上找入口全部落空。样本取自仓库里记着的真机类名（docs/清单/小米-HyperOS.md、
docs/清单/入口速查.md、docs/14-红米K70Pro实测.md）。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import Clock, clocked, load_recipe, phone_stub, stub

# 仓库里已有的真机读数：设置页命名分「Setting」与「Preference」两族
SETTINGS_PAGES = [
    "com.android.thememanager/.ThemePreferenceActivity",                             # 主题「我的」→ 设置
    "com.android.browser/.preferences.activity.CustomizationPreferenceActivity",     # 浏览器个性化推荐设置
    "com.heytap.browser/com.heytap.browser.settings.component.BrowserPreferencesPage",  # OPPO 浏览器设置
    "com.xiaomi.market/.ui.MarketPreferenceActivity",                                # 应用商店 → 我的 → 设置
    "com.xiaomi.mipicks/com.xiaomi.market.ui.MarketPreferenceActivity",              # 海外版商店设置
    "com.android.quicksearchbox/.preferences.SearchSettingsPreferenceActivity",      # 全局搜索设置
    "com.android.browser/.BrowserSettingsActivity",                                  # 旧判据本来就认
    "com.xiaomi.calendar/.settings.CalendarActionbarSettingsActivity",
]

NOT_SETTINGS_PAGES = [
    "com.android.thememanager/.ThemeResourceProxyTabActivity",   # 主题「我的」页本身
    "com.android.thememanager/.MainActivity",
    "com.android.browser/.MainActivity",
    "PopupWindow:9e12e45",                                      # 弹窗：不是设置页（#407）
    "",
]

THEME_MINE = "com.android.thememanager/.ThemeResourceProxyTabActivity"
THEME_SETTINGS = "com.android.thememanager/.ThemePreferenceActivity"

# 「我的」页右上一个齿轮图标，点了进主题设置页
GEAR_PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true"
          bounds="[960,120][1060,220]" />
  </node>
</hierarchy>"""


def focus_phone(**fields):
    """不连手机、焦点窗口由参数给的 Phone：判据只读 focus()。

    `focus` 归观测基座（ADR-0033）：桩要落在 `p.screen` 上，门面与导航阶段读的才是同一处。"""
    p = phone_stub("test", d=Mock(), W=1080, H=2400)
    for name, value in fields.items():
        stub(p, name, value)
    return p


class SettingsPageTests(unittest.TestCase):
    def test_preference_named_settings_pages_are_recognized(self):
        for focus in SETTINGS_PAGES:
            with self.subTest(focus=focus):
                p = focus_phone(focus=lambda f=focus: f)
                self.assertTrue(p.in_settings_page())

    def test_other_pages_are_not_settings_pages(self):
        """旧树也绿，守的是不回退：弹窗（#407）、App 首页、读不出前台都还不能算设置页。"""
        for focus in NOT_SETTINGS_PAGES:
            with self.subTest(focus=focus):
                p = focus_phone(focus=lambda f=focus: f)
                self.assertFalse(p.in_settings_page())


class GearLandingTests(unittest.TestCase):
    """票面症状：点完齿轮落在 ThemePreferenceActivity，gear() 判「没进去」并退回上一页。

    用票面那台机（Xiaomi 15 HyperOS 4）的脚本：它的 gear() 内含落点校验，
    判据没扩宽时这条用例会红（2026-11-10 复核：撤销 SETTINGS_MARKS 的 Preference 后返红）。
    """

    def setUp(self):
        clocked(self, fast, Clock())

    def gear_phone(self):
        p = focus_phone(focus=lambda: THEME_MINE)
        p.screen.tree = Mock(return_value=ET.fromstring(GEAR_PAGE))
        stub(p, "click", Mock(side_effect=lambda x, y: setattr(p.screen, "focus", lambda: THEME_SETTINGS)))
        stub(p, "back", Mock())
        stub(p, "find", Mock(return_value=None))
        stub(p, "tap", Mock(return_value=False))
        return p

    def test_gear_landing_on_a_preference_activity_counts_as_entering_settings(self):
        p = self.gear_phone()
        scope, _ = load_recipe(p, ROOT / "recipes/xiaomi-24129PN74C/recipe_os4.py")
        self.assertTrue(scope["gear"]())
        p.screen.back.assert_not_called()


if __name__ == "__main__":
    unittest.main()
