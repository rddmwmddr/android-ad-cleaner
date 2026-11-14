"""设置搜索搬出 `Phone` 之后的两条对外契约（ADR-0033、#1042）。

钉两件事：
  · 门面继续转发 `setting()` / `type_text()` / `edit_ready()` / `focused_text()`——返回值由阶段给；
  · 这个阶段只造自己就能验：给一个假 `Screen` 就能判「在不在搜索页」「框里是什么」，
    不必造整台 `Phone`。这是搬迁声称的测试面下沉，不是实现细节。
"""
import itertools
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from fixtures import (Clock, clocked, fake_phone, load_recipe, phone_stub,  # noqa: E402
                      screen_stub, stub)

# 荣耀 MagicOS 10 的设置搜索框：AutoCompleteTextView，类名里没有 EditText（沿用 #597 的判例）
SEARCH_BOX = ('<hierarchy><node class="android.widget.AutoCompleteTextView" focused="true" '
              'text="广告" bounds="[138,509][930,629]"/></hierarchy>')


def bare_search(page=SEARCH_BOX):
    """只造设置搜索阶段：观测替身取 `fixtures.screen_stub()`，没有 `Phone`。"""
    return fast.SettingsSearch(screen_stub(page), fast.LostNote())


class FacadeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_the_phase_methods_go_through_the_session(self):
        """门面没有实现残留：把阶段换成替身，返回值必须由替身给出。"""
        self.p.search = Mock()
        self.p.search.setting.return_value = False
        self.p.search.type_text.return_value = True
        self.p.search.edit_ready.return_value = True
        self.p.search.focused_text.return_value = "广告"
        self.assertFalse(self.p.setting("广告", "广告服务", "搜索设置", "隐私 > 广告"))
        self.assertTrue(self.p.type_text("广告", timeout=0.5))
        self.assertTrue(self.p.edit_ready())
        self.assertEqual(self.p.focused_text(), "广告")
        self.p.search.setting.assert_called_once_with("广告", "广告服务", "搜索设置", "隐私 > 广告")
        self.p.search.type_text.assert_called_once_with("广告", 0.5)
        self.p.search.edit_ready.assert_called_once_with()
        self.p.search.focused_text.assert_called_once_with()


class StandalonePhaseTests(unittest.TestCase):
    def test_the_search_page_is_recognised_without_a_phone(self):
        search = bare_search()
        self.assertTrue(search.edit_ready())
        self.assertEqual(search.focused_text(), "广告")

    def test_a_page_without_a_focused_box_is_not_the_search_page(self):
        search = bare_search('<hierarchy><node text="搜索设置项" bounds="[50,100][1030,200]"/></hierarchy>')
        self.assertFalse(search.edit_ready())
        self.assertIsNone(search.focused_text())


# ---------- #639：设置搜索失败后必须离开搜索页 ----------
# 报告者的机器（HONOR DVD-AN00，MagicOS 10）搜不到「新闻资讯」时页面停在设置搜索页，
# 半屏手写输入法还开着；`off()` 接着滚了 40 屏找开关，滑动全落在输入法上，一直画出「丨」。
SEARCH_PAGE = ('<hierarchy><node text="新闻资讯" class="android.widget.EditText"'
               ' focused="true" bounds="[50,100][1000,200]"/></hierarchy>')
SETTINGS_HOME = '<hierarchy><node text="搜索设置项" bounds="[50,100][1100,200]"/></hierarchy>'


class SettingSearchExitTests(unittest.TestCase):
    def make_phone(self, *, page="search", results=(), focus="com.android.settings/.SearchActivity"):
        p = phone_stub("S")
        p.W, p.H = 1168, 1712
        p.screen.focus = Mock(return_value=focus)
        self.said, self.back, self.click = Mock(), Mock(), Mock()
        stub(p, "say", self.said)            # 退场与「没搜到」的说明在内层会经观测基座说
        stub(p, "back", self.back)
        stub(p, "click", self.click)
        stub(p, "type_text", Mock(return_value=True))
        p.reader = Mock()
        p.reader.shell.return_value = types.SimpleNamespace(exit_code=0, output="Starting: Intent")
        state = {"page": page}
        p.screen.tree = Mock(side_effect=lambda: ET.fromstring(
            SEARCH_PAGE if state["page"] == "search" else SETTINGS_HOME))
        self.back.side_effect = lambda *a, **k: state.update(page="home")
        row = ET.fromstring('<node class="android.widget.TextView"/>')
        p.screen.texts = Mock(return_value=[(t, (50, y, 1000, y + 100), row)
                                     for t, y in results])
        p.state = state
        return p

    def run_setting(self, p, **kw):
        with patch.object(fast.time, "time", side_effect=itertools.count(0, 0.2)), \
                patch.object(fast.time, "sleep"):
            return p.setting("新闻资讯", **kw)

    def test_missing_result_returns_after_leaving_the_search_page(self):
        p = self.make_phone()
        self.assertFalse(self.run_setting(p))
        self.assertTrue(self.back.called)
        self.assertFalse(p.edit_ready())
        self.assertTrue(any("没搜到" in c.args[0] for c in self.said.call_args_list))

    def test_result_that_does_not_open_also_leaves_the_search_page(self):
        # 结果行在，点下去没换页（落点判据 timeout）：仍要退场
        p = self.make_phone(results=[("新闻资讯", 400)])
        self.assertFalse(self.run_setting(p))
        self.assertTrue(self.back.called)
        self.assertFalse(p.edit_ready())

    def test_input_failure_also_leaves_the_search_page(self):
        p = self.make_phone()
        stub(p, "type_text", Mock(return_value=False))
        self.assertFalse(self.run_setting(p))
        self.assertTrue(self.back.called)
        self.assertFalse(p.edit_ready())

    def test_search_box_not_opening_does_not_press_back(self):
        """旧树也绿，守的是失败路径不乱按返回：没进搜索页就没有输入法占屏。"""
        p = self.make_phone(page="home")
        p.reader.shell.return_value = types.SimpleNamespace(
            exit_code=1, output="Error: Activity not started, unable to resolve Intent")
        self.assertFalse(self.run_setting(p))
        self.back.assert_not_called()

    def test_failure_returns_to_the_settings_home(self):
        # 直达搜索页时它是新任务根：退场要主动拉起设置首页，不能只按返回
        p = self.make_phone()
        self.assertFalse(self.run_setting(p))
        commands = [c.args[0] for c in p.reader.shell.call_args_list]
        self.assertIn("am start -f 0x10008000 -a android.settings.SETTINGS", commands)

    def test_stuck_on_search_page_reports_where_it_landed(self):
        p = self.make_phone()
        stub(p, "back", Mock())              # 按了也不离开：退场失败
        self.assertFalse(self.run_setting(p))
        self.assertTrue(any("com.android.settings/.SearchActivity" in c.args[0]
                            for c in self.said.call_args_list))


class HonorYoyoSearchFailureTests(unittest.TestCase):
    RECIPE = ROOT / "recipes/honor/PNM-AN10/PNM-AN10.toml"

    def test_missing_search_result_skips_dismiss_and_off(self):
        p = fake_phone()
        p.setting = Mock(return_value=False)
        p.dismiss, p.off = Mock(), Mock()
        load_recipe(p, self.RECIPE, only="YOYO")
        p.dismiss.assert_not_called()
        p.off.assert_not_called()

    def test_working_search_still_closes_the_switch(self):
        """旧树也绿，守的是成功路径不回退：搜索到了仍要关那个开关。"""
        p = fake_phone()
        p.setting = Mock(return_value=True)
        p.off = Mock(return_value=1)
        load_recipe(p, self.RECIPE, only="YOYO")
        p.off.assert_called_once()


# ---------- #960：设置页签名认 Setting 与 Preference 两族 ----------
# 小米主题商店、商店、浏览器、全局搜索的设置页有两套命名：一套类名带 Setting，另一套带
# Preferences / Preference。后者点完齿轮一律判失败，gear() 退回上一页、返回 False，后面整段
# 在旧页上找入口全部落空。样本取自仓库里记着的真机类名（docs/清单/小米-HyperOS.md、
# docs/清单/入口速查.md、docs/14-红米K70Pro实测.md）。
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


class PreferenceGearLandingTests(unittest.TestCase):
    """#960 票面症状：点完齿轮落在 ThemePreferenceActivity，gear() 判「没进去」并退回上一页。

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
        scope, _ = load_recipe(p, ROOT / "recipes/xiaomi/24129PN74C/24129PN74C-os4.toml")
        self.assertTrue(scope["gear"]())
        p.screen.back.assert_not_called()


if __name__ == "__main__":
    unittest.main()
