"""导航搬出 `Phone` 之后的对外契约（ADR-0033、#1044）。

钉四件事：
  · 门面继续逐个转发导航方法——返回值与异常都由阶段给，门面没有实现残留；
  · 这个阶段只造自己就能验：一个假 `Screen`、一个丢失记录与一个 `dismiss` 桩，
    不必造整台 `Phone`（搬迁声称的测试面下沉，不是实现细节）；
  · 失败语义逐处保持：`tap()` / `entry()` / `go()` / `tab()` 只返回假，`enter()` 抛；
  · 调用图单向无环：阶段只 import 基座，彼此之间只传注入的窄接口。
"""
import ast
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
import wait  # noqa: E402
from phone import navigator  # noqa: E402
from fixtures import (SIZES, Clock, EMPTY_PAGE, clocked, load_recipe, phone_stub,  # noqa: E402
                      screen_stub, stub)

# ---------- 基线：bb2afb7 的旧实现，逐字冻结 ----------
BASE_SETTINGS_MARKS = ("Setting", "Preference")

SETTINGS = "com.example.app/.SettingsActivity"
HOME = "com.example.app/.MainActivity"

PAGE = '''<hierarchy rotation="0">
  <node package="com.example.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2100]">
      <node class="android.widget.TextView" text="设置" clickable="true" bounds="[60,400][900,500]"/>
    </node>
    <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
  </node>
</hierarchy>'''


def bare_navigator(page=PAGE, focus=SETTINGS, dismiss=None, size=SIZES[0]):
    """只造导航阶段：观测替身取 `fixtures.screen_stub()`，没有 `Phone`。点击与返回只记账。"""
    screen = screen_stub(page, size=size, conn=SimpleNamespace(say=lambda *a: None))
    screen.focus = focus if callable(focus) else (lambda: focus)
    screen.say = lambda *a: None
    screen.sig = lambda: "page"
    screen.settle = lambda *a, **k: True
    screen.scroll = lambda *a, **k: None
    clicks, backs = [], []
    screen.click = lambda x, y: clicks.append((x, y))
    screen.back = lambda n=1: backs.append(n)
    return fast.Navigator(screen, fast.LostNote(), dismiss or (lambda: None)), clicks, backs


class FacadeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_the_phase_methods_go_through_the_stage(self):
        """门面没有实现残留：把阶段换成替身，返回值与异常必须由替身给出。"""
        self.p.navigator = Mock()
        nav = self.p.navigator
        nav.tap.return_value = True
        nav.go.return_value = False
        nav.enter.side_effect = RuntimeError("页面没有变化")
        nav.entry.return_value = True
        nav.tab.return_value = False
        nav.tap_icon.return_value = True
        nav.await_page.return_value = "ok"
        nav.in_settings_page.return_value = True

        self.assertTrue(self.p.tap("设置", exact=True, scrolls=2))
        self.assertFalse(self.p.go("我的", "设置"))
        with self.assertRaisesRegex(RuntimeError, "页面没有变化"):
            self.p.enter("设置")
        self.assertTrue(self.p.entry("设置"))
        self.assertFalse(self.p.tab("我的"))
        self.assertTrue(self.p.tap_icon("设置"))
        self.assertEqual(self.p.await_page(), "ok")
        self.assertTrue(self.p.in_settings_page())
        self.p.top(2)

        nav.tap.assert_called_once_with("设置", True, 2, 0.6, False, None)
        nav.go.assert_called_once_with("我的", "设置", 3, True)
        nav.enter.assert_called_once_with("设置", 0, 3)
        nav.entry.assert_called_once_with("设置", 6, 2.4, 0.2, 2)
        nav.tab.assert_called_once_with("我的", 6.0)
        nav.tap_icon.assert_called_once_with("设置", (0.72, 0.0, 1.0, 0.16), 3)
        nav.await_page.assert_called_once()
        nav.in_settings_page.assert_called_once_with()
        nav.top.assert_called_once_with(2)


class StandalonePhaseTests(unittest.TestCase):
    def setUp(self):
        # 等页、找字与 6 秒底栏预算都读 `time`：假钟一装，这些等待不占真实时间。
        self.clock = clocked(self, fast, Clock())

    def test_the_bottom_band_label_is_clicked_without_a_phone(self):
        stage, clicks, _ = bare_navigator()
        self.assertTrue(stage.tab("我的"))
        self.assertEqual(clicks, [(940, 2220)])

    def test_a_missing_text_only_records_the_miss(self):
        stage, clicks, _ = bare_navigator()
        self.assertFalse(stage.tap("没有的字", scrolls=2))
        self.assertEqual(stage.lost_note.miss, 1)
        self.assertEqual(clicks, [])

    def test_entering_a_page_that_never_changes_raises(self):
        stage, clicks, _ = bare_navigator()
        stage.screen.settle = lambda *a, **k: False      # 入口找得到，点了页面没换
        with self.assertRaisesRegex(RuntimeError, "页面没有变化"):
            stage.enter("设置")
        self.assertEqual(len(clicks), 3)                  # tries 次重点

    def test_the_settings_page_signature_is_read_from_the_base(self):
        stage, _, _ = bare_navigator(focus=lambda: SETTINGS)
        self.assertTrue(stage.in_settings_page())
        stage.screen.focus = lambda: HOME
        self.assertFalse(stage.in_settings_page())

    def test_the_injected_dismiss_is_the_only_way_back_to_the_popups(self):
        """挡路的弹窗归 `Dismisser`：导航只调注入的窄接口，不 import 那个模块。"""
        called = []
        stage, _, _ = bare_navigator(page=EMPTY_PAGE, dismiss=lambda: called.append(1))
        self.assertFalse(stage.tap("我的", exact=True, scrolls=0))
        self.assertTrue(called)


class FailureSemanticsTests(unittest.TestCase):
    """按文字导航的失败语义逐个保持：一处也不许改成统一的「抛」或「返回假」。"""

    def setUp(self):
        clocked(self, fast, Clock())

    def assert_returns_false(self, call):
        stage, _, _ = bare_navigator(page=EMPTY_PAGE)
        self.assertIs(call(stage), False)

    def test_false_is_returned_by_the_optional_paths(self):
        self.assert_returns_false(lambda s: s.tap("我的"))
        self.assert_returns_false(lambda s: s.tap("我的", exact=True, scrolls=0))
        self.assert_returns_false(lambda s: s.entry("设置"))
        self.assert_returns_false(lambda s: s.go("我的", "设置"))
        self.assert_returns_false(lambda s: s.tab("我的", maxwait=0))
        self.assert_returns_false(lambda s: s.tap_icon("设置"))

    def test_enter_raises_because_the_caller_has_no_fallback(self):
        stage, _, _ = bare_navigator(page=EMPTY_PAGE)
        with self.assertRaisesRegex(RuntimeError, "未找到入口"):
            stage.enter("设置")


class SingleWordListTests(unittest.TestCase):
    def test_the_settings_signature_matches_the_frozen_baseline(self):
        self.assertEqual(navigator.SETTINGS_MARKS, BASE_SETTINGS_MARKS)

    def test_the_settings_signature_lives_only_in_this_module(self):
        self.assertIs(fast.SETTINGS_MARKS, navigator.SETTINGS_MARKS)
        for owner in (fast.Phone, fast.Screen, fast.Toggler, fast.Launcher,
                      fast.SettingsSearch, fast.Dismisser):
            self.assertFalse(hasattr(owner, "SETTINGS_MARKS"),
                             f"{owner.__name__} 上又出现了一份设置页签名")


def go_phone(*, exact_tab, loose_tab, lands):
    """#305：精确 / 包含匹配「我的」返回的坐标，以及点完后 expect 是否出现。"""
    p = phone_stub("test", W=1080, H=2400)
    p.say = Mock()
    p.dismiss = Mock(return_value=None)
    # `go()` 内部调的是导航阶段的 `tap()`、观测基座的 `find()`（ADR-0033）：桩要落到那里
    stub(p, "tap", Mock(return_value=True))

    def find(text, exact=False, root=None, edge_ok=False, nav=False):
        if text == "我的":
            return exact_tab if exact else loose_tab
        return (300, 300) if lands else None

    stub(p, "find", find)
    return p


class GoBottomTabTests(unittest.TestCase):
    """#305：`go()` 精确匹配不到时退回包含匹配，但落点仍由 expect 确认（第二层原因）。"""

    def test_exact_tab_is_used_when_it_reads_exactly_my(self):
        p = go_phone(exact_tab=(540, 2300), loose_tab=None, lands=True)
        self.assertTrue(p.go("我的", "设置"))
        p.navigator.tap.assert_called_once_with("我的", exact=True, scrolls=0)

    def test_suffixed_tab_falls_back_to_contains(self):
        p = go_phone(exact_tab=None, loose_tab=(540, 2300), lands=True)
        self.assertTrue(p.go("我的", "设置"))
        p.navigator.tap.assert_called_once_with("我的", exact=False, scrolls=0)

    def test_loose_click_that_lands_nowhere_still_fails(self):
        p = go_phone(exact_tab=None, loose_tab=(540, 2300), lands=False)
        with patch.object(fast.time, "sleep"):
            self.assertFalse(p.go("我的", "设置"))

    def test_caller_requesting_loose_match_skips_the_probe(self):
        p = go_phone(exact_tab=(540, 2300), loose_tab=(540, 2300), lands=True)
        self.assertTrue(p.go("我的", "设置", exact=False))
        p.navigator.tap.assert_called_with("我的", exact=False, scrolls=0)


# ---------- #386：`tab()` 只在屏幕底部带里找标签 ----------
TAB_W, TAB_H = 1080, 2400
TAB_CONTENT = "[0,300][1080,360]"
TAB_BAND = "[0,2200][216,2300]"
TAB_RIGHT = "[864,2200][1080,2300]"
TAB_JUST_BELOW = "[0,2039][216,2099]"     # 屏高 85% = 2040
TAB_JUST_INSIDE = "[0,2041][216,2101]"


def tab_page(*nodes):
    return ET.fromstring('<hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>")


def tab_node(text=None, desc=None, area=TAB_BAND):
    attrs = f'class="android.widget.TextView" bounds="{area}"'
    if text is not None:
        attrs += f' text="{text}"'
    if desc is not None:
        attrs += f' content-desc="{desc}"'
    return f"<node {attrs}/>"


def tab_phone(*nodes):
    p = phone_stub("test", W=TAB_W, H=TAB_H)
    p.screen.tree = Mock(return_value=tab_page(*nodes))
    stub(p, "click", Mock())                 # 导航阶段经观测基座点击，桩要落到 `p.screen`
    p.say = Mock()
    p.dismiss = Mock(return_value=None)
    p.screen.sig = Mock(return_value="page")
    p.screen.settle = Mock(return_value=True)
    return p


class TabTests(unittest.TestCase):
    """#386：`tab()` 只在底部带里找标签，带内三层匹配，找不到不回退。"""

    def test_plain_label_in_the_bottom_band_is_clicked(self):
        p = tab_phone(tab_node(text="我的"))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(108, 2250)
        p.screen.settle.assert_called_once()

    def test_selected_state_prefix_in_content_desc_is_ignored(self):
        p = tab_phone(tab_node(desc="未选中,我的"))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(108, 2250)

    def test_unread_suffix_label_is_clicked(self):
        p = tab_phone(tab_node(text="我的，有新消息"))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(108, 2250)

    def test_same_name_outside_the_band_is_not_clicked(self):
        p = tab_phone(tab_node(text="我的", area=TAB_CONTENT))
        self.assertFalse(p.tab("我的", maxwait=0))
        p.screen.click.assert_not_called()

    # vivo 应用商店底栏把角标和序号一起塞进无障碍名（#530）：末段是「共5个」，
    # 既不等于「我的」也不以逗号收在「我的」，只剩包含匹配能命中。
    def test_badge_and_index_suffix_is_clicked(self):
        p = tab_phone(tab_node(text="我的, 2个应用待更新,第5个, 共5个"))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(108, 2250)

    def test_badge_suffix_tab_wins_over_a_content_label_with_the_same_name(self):
        p = tab_phone(tab_node(text="我的", area=TAB_CONTENT),
                      tab_node(text="我的, 2个应用待更新,第5个, 共5个"))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(108, 2250)

    def test_exact_label_wins_over_a_longer_label_in_the_band(self):
        p = tab_phone(tab_node(text="我的奇妙小镇"), tab_node(text="我的", area=TAB_RIGHT))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(972, 2250)

    def test_comma_tail_wins_over_a_longer_label_in_the_band(self):
        p = tab_phone(tab_node(text="我的奇妙小镇"), tab_node(desc="未选中,我的", area=TAB_RIGHT))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(972, 2250)

    def test_a_label_above_the_band_is_left_alone(self):
        p = tab_phone(tab_node(text="我的", area=TAB_JUST_BELOW))
        self.assertFalse(p.tab("我的", maxwait=0))
        p.screen.click.assert_not_called()

    def test_a_label_just_inside_the_band_is_clicked(self):
        p = tab_phone(tab_node(text="我的", area=TAB_JUST_INSIDE))
        self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(108, 2071)

    def test_band_without_a_match_returns_false_and_clicks_nothing(self):
        p = tab_phone(tab_node(text="首页"))
        self.assertFalse(p.tab("我的", maxwait=0))
        p.screen.click.assert_not_called()

    def test_tab_that_shows_up_late_is_still_clicked(self):
        pages = [tab_page(), tab_page(), tab_page(tab_node(text="我的"))]
        p = tab_phone()
        p.screen.tree = Mock(side_effect=lambda: pages.pop(0) if len(pages) > 1 else pages[0])
        clock = [0.0]
        with patch.object(fast.time, "time", side_effect=lambda: clock[0]), \
                patch.object(fast.time, "sleep", side_effect=lambda s: clock.__setitem__(0, clock[0] + s)):
            self.assertTrue(p.tab("我的"))
        p.screen.click.assert_called_once_with(108, 2250)


# ---------- #575：vivo 机型脚本的 gear() 点完要校验落地 ----------
GEAR_RECIPES = [ROOT / "recipes/vivo/V2547DA/V2547DA.toml",
                ROOT / "recipes/vivo/V2547DA/V2547DA-android17.toml"]

MINE = "com.bbk.appstore/.MainActivity"
VIVO_SETTINGS = "com.bbk.appstore/.ui.menu.AppstoreSettingsActivity"

# 「我的」页右上一排图标：两个都读作「设置」，前面那个点了没反应
TWO_GEARS = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true"
          bounds="[760,120][860,220]" />
    <node class="android.widget.ImageView" content-desc="设置" clickable="true"
          bounds="[960,120][1060,220]" />
  </node>
</hierarchy>"""

ONE_GEAR = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.ImageView" content-desc="设置" clickable="true"
          bounds="[960,120][1060,220]" />
  </node>
</hierarchy>"""

NO_GEAR = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="我的" bounds="[48,320][320,400]" />
  </node>
</hierarchy>"""


def gear_phone(page, focus=MINE):
    p = phone_stub("test", reader=Mock(), W=1080, H=2400)
    p.screen.tree = Mock(return_value=ET.fromstring(page))
    p.screen.focus = Mock(return_value=focus)
    p.click = Mock()
    p.back = Mock()
    p.find = Mock(return_value=None)
    p.tap = Mock(return_value=False)
    return p


def gear(p, recipe=GEAR_RECIPES[0]):
    scope, _ = load_recipe(p, recipe)
    return scope["gear"]()


class GearLandingTests(unittest.TestCase):
    """#575：gear() 点完要校验落地，点不动就继续找，最后回退到按文字点。

    报告者那台上先命中的是一个点不动的图标，旧实现点完就 `return True`，
    函数末尾按文字回退的那一句永远轮不到，整段在后面按旧页找入口、全部落空。

    「点得动就一次进去」「无入口返回假」「回退成功也算数」三条在旧实现上本来就绿，
    它们守的是原路径没被这几处校验改坏。
    """

    def setUp(self):
        """点完要等页面站稳：await_page 读的是 fast 的时钟，换成假的才不真睡。"""
        clocked(self, fast, Clock())

    def test_a_gear_that_does_not_open_settings_is_not_success(self):
        """点击被吞（页面没换）：不能当成进了设置页，要继续试下一个候选。"""
        p = gear_phone(TWO_GEARS)

        def click(x, y):
            if (x, y) == (810, 170):            # 前面那个：点了没反应
                return
            p.screen.focus.return_value = VIVO_SETTINGS    # 后面那个：真的进了设置页

        p.click.side_effect = click
        self.assertTrue(gear(p))
        self.assertEqual(p.click.call_count, 2)

    def test_the_text_fallback_is_also_checked_for_landing(self):
        """齿轮一个都没命中、按文字点也被吞：页面没换就不能报成功。"""
        p = gear_phone(NO_GEAR)
        p.tap.return_value = True
        self.assertFalse(gear(p))
        p.tap.assert_called_once_with("设置", exact=True, scrolls=0)

    def test_a_swallowed_click_does_not_count_on_a_page_that_already_looks_like_settings(self):
        """起始页的 Activity 本来就含 Setting 时，点击被吞仍不算这一次进了设置页（AC4）。"""
        p = gear_phone(ONE_GEAR, focus=VIVO_SETTINGS)
        self.assertFalse(gear(p))
        p.click.assert_called_once()

    def test_a_working_gear_still_goes_in_on_the_first_tap(self):
        """点得动的齿轮仍按原路径进去，不多点一次。"""
        p = gear_phone(ONE_GEAR)
        p.click.side_effect = lambda x, y: setattr(p.screen.focus, "return_value", VIVO_SETTINGS)
        self.assertTrue(gear(p))
        self.assertEqual(p.click.call_count, 1)
        p.tap.assert_not_called()

    def test_a_gear_that_lands_on_another_page_is_not_success(self):
        """点到别的图标（换页但页上没有「设置」标题）：不算命中，先退回原页再试。"""
        p = gear_phone(ONE_GEAR)
        p.click.side_effect = lambda x, y: setattr(
            p.screen.focus, "return_value", "com.bbk.appstore/.ui.Message")
        self.assertFalse(gear(p))
        p.back.assert_called_once()

    def test_a_wrong_page_is_left_before_trying_the_next_gear(self):
        """第一个候选点进了别的页：先退回来再试下一个，不能在新页上用旧树的坐标接着点。"""
        p = gear_phone(TWO_GEARS)

        def click(x, y):
            if (x, y) == (810, 170):
                p.screen.focus.return_value = "com.bbk.appstore/.ui.Message"
            else:
                p.screen.focus.return_value = VIVO_SETTINGS

        p.click.side_effect = click
        p.back.side_effect = lambda *a: setattr(p.screen.focus, "return_value", MINE)
        self.assertTrue(gear(p))
        self.assertEqual(p.click.call_count, 2)
        p.back.assert_called_once()

    def test_a_settings_page_without_setting_in_its_activity_still_counts(self):
        """App 自定义设置页的 Activity 名不含 Setting：换页后页面上出现「设置」标题也算进了。"""
        p = gear_phone(ONE_GEAR)

        def click(x, y):
            p.screen.focus.return_value = "com.bbk.appstore/.ui.MinePrefs"
            p.find.return_value = (100, 200)

        p.click.side_effect = click
        self.assertTrue(gear(p))

    def test_a_settings_button_in_the_body_is_not_a_title(self):
        """换页后页面中部有「设置」按钮（不在标题带）：没换 Activity 就不算进了设置页。"""
        p = gear_phone(ONE_GEAR)

        def click(x, y):
            p.screen.focus.return_value = "com.bbk.appstore/.ui.MinePrefs"
            p.find.return_value = (500, 1800)

        p.click.side_effect = click
        self.assertFalse(gear(p))

    def test_the_text_fallback_counts_when_it_opens_settings(self):
        p = gear_phone(NO_GEAR)

        def tap(text, **kw):
            p.screen.focus.return_value = VIVO_SETTINGS
            return True

        p.tap.side_effect = tap
        self.assertTrue(gear(p))

    def test_no_entry_at_all_returns_false_for_the_caller_to_skip(self):
        """页面没有任何入口：返回假，调用方跳过该段。"""
        p = gear_phone(NO_GEAR)
        self.assertFalse(gear(p))

    def test_both_v2547da_scripts_check_landing_the_same_way(self):
        for path in GEAR_RECIPES:
            with self.subTest(recipe=path.name):
                p = gear_phone(NO_GEAR)
                p.tap.return_value = True
                self.assertFalse(gear(p, path))


# ---------- 变异判据（ADR-0043、#1539）：翻页回路与各默认值留下的可观察效果 ----------
def loop_navigator(*, find=None, dismiss=None, scroll_more=True, miss=0):
    """翻页回路用的导航阶段：观测基座的每次查找、点击、翻页都可数，等待走假钟。"""
    screen = screen_stub(EMPTY_PAGE)
    screen.say = Mock()
    screen.sig = Mock(return_value="sig")
    screen.settle = Mock(return_value=True)
    screen.click = Mock()
    screen.back = Mock()
    screen.focus = lambda: HOME
    screen.find = Mock(side_effect=find or (lambda *a, **k: None))
    screen.scroll_more = Mock(return_value=scroll_more)
    screen.scroll_top = Mock()
    stage = fast.Navigator(screen, fast.LostNote(), dismiss or Mock(return_value=None))
    stage.lost_note.miss = miss
    return stage, screen


class TapLoopTests(unittest.TestCase):
    """`tap()` 的翻页回路：默认值、两轮循环、弹窗与会话的交互都是对外可见的。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_a_plain_word_is_matched_loosely_by_default(self):
        """默认按包含匹配找：精确匹配不到的「我的，有新消息」也要点中。"""
        stage, screen = loop_navigator(
            find=lambda text, exact=False, **kw: None if exact else (10, 20))
        self.assertTrue(stage.tap("我的"))
        screen.click.assert_called_once_with(10, 20)

    def test_a_hit_settles_from_the_signature_taken_before_the_click(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, edge_ok=False, nav=False:
            (5, 6) if (exact is True and nav is True and edge_ok is False) else None)
        seen = []
        self.assertTrue(stage.tap("设置", exact=True, scrolls=2, seen=seen))
        screen.settle.assert_called_once_with("sig", 1.0)
        self.assertEqual(seen, ["sig"])

    def test_the_fast_path_after_a_miss_resets_the_note(self):
        """本段已经走丢：只看当前这一屏，命中就清零，并把点击前的签名记进 seen。"""
        stage, screen = loop_navigator(
            find=lambda text, exact=False, nav=False:
            (3, 4) if (exact is True and nav is True) else None, miss=2)
        seen = []
        self.assertTrue(stage.tap("设置", exact=True, seen=seen))
        self.assertEqual(stage.lost_note.miss, 0)
        screen.settle.assert_called_once_with("sig", 1.0)
        self.assertEqual(seen, ["sig"])

    def test_a_failed_fast_path_counts_the_miss(self):
        stage, _ = loop_navigator(miss=2)
        self.assertFalse(stage.tap("设置", exact=True))
        self.assertEqual(stage.lost_note.miss, 3)

    def test_a_zero_scroll_tap_closes_popups_and_rereads_immediately(self):
        """刚关掉弹窗就立刻重读（一秒也不等），并只在底栏带里找。"""
        found = []

        def find(text, exact=False, edge_ok=False, nav=False):
            hit = (1, 2) if (exact is True and edge_ok == "tab" and nav is True) else None
            found.append(hit)
            return None if len(found) == 1 else hit

        stage, screen = loop_navigator(find=find, dismiss=Mock(side_effect=[True] + [None] * 40))
        self.assertTrue(stage.tap("我的", exact=True, scrolls=0))
        self.assertEqual(self.clock.t, 0.0)
        screen.click.assert_called_once_with(1, 2)
        screen.settle.assert_called_once_with("sig", 1.0)

    def test_a_zero_scroll_tap_polls_every_two_tenths_of_a_second(self):
        """什么都没关掉时按 0.2 秒的间隔重看，6 秒预算用完就报没找到。"""
        stage, screen = loop_navigator(dismiss=Mock(side_effect=[None] * 30 + [True] * 5))
        self.assertFalse(stage.tap("我的", scrolls=0))
        self.assertAlmostEqual(self.clock.t, 6.0)
        self.assertEqual(screen.find.call_count, 30)
        screen.say.assert_called_once_with("  ✗ 没找到「我的」")

    def test_the_six_second_budget_stops_on_the_boundary(self):
        """6.0 秒整不算「还在预算内」：假钟按整秒读数，边界差一就会多找一次。"""
        stage, screen = loop_navigator()
        stage.dismiss = Mock(return_value=None)
        scripted = SimpleNamespace(
            time=Mock(side_effect=[0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
            sleep=Mock())
        with patch.object(navigator, "time", scripted):
            self.assertFalse(stage.tap("我的", scrolls=0))
        self.assertEqual(screen.find.call_count, 6)

    def test_the_scroll_loop_tries_seven_finds_per_round_and_returns_to_the_top(self):
        """默认 scrolls=6：每轮 7 次查找、6 次翻页，两轮之间回一次页顶。"""
        stage, screen = loop_navigator()
        rounds = []
        screen.scroll_top = Mock(side_effect=lambda n: rounds.append((n, screen.find.call_count)))
        self.assertFalse(stage.tap("我的"))
        self.assertEqual(screen.find.call_count, 14)
        self.assertEqual(screen.scroll_more.call_count, 12)
        self.assertEqual(rounds, [(8, 7)])          # 第一轮翻完就回页顶，第二轮不再回

    def test_a_closed_popup_triggers_one_more_find_before_scrolling(self):
        calls = []

        def find(text, exact=False, nav=False, **kw):
            calls.append((text, exact, nav, kw))
            return (7, 8) if (len(calls) > 1 and nav is True and screen.scroll_more.call_count == 0) else None

        stage, screen = loop_navigator(find=find, dismiss=Mock(return_value=True))
        self.assertTrue(stage.tap("设置", exact=True))
        self.assertEqual(screen.find.call_count, 2)
        self.assertEqual(calls[1], ("设置", True, True, {}))
        screen.settle.assert_called_once_with("sig", 1.0)

    def test_a_popup_does_not_trigger_a_second_find_after_a_hit(self):
        """找到了就不为弹窗再找一次：`xy 与 dismiss` 只有缺字时才成立。"""
        stage, screen = loop_navigator(
            find=lambda *a, **k: (1, 1), dismiss=Mock(return_value=True))
        self.assertTrue(stage.tap("设置"))
        self.assertEqual(screen.find.call_count, 1)

    def test_a_miss_after_the_last_scroll_looks_in_the_edge_band_once(self):
        """翻不动时在边缘带再找一遍，找到就点、按 wait 等，但不改动丢失计数。"""
        stage, screen = loop_navigator(
            find=lambda text, exact=False, edge_ok=False, nav=False:
            (9, 9) if (exact is True and edge_ok is True and nav is True) else None,
            scroll_more=False)
        seen = []
        self.assertTrue(stage.tap("设置", exact=True, scrolls=1, seen=seen))
        screen.click.assert_called_once_with(9, 9)
        self.assertEqual(self.clock.t, 0.6)
        self.assertEqual(seen, ["sig"])
        screen.settle.assert_not_called()

    def test_a_successful_scroll_does_not_take_the_edge_band_fallback(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, edge_ok=False, nav=False:
            (9, 9) if edge_ok is True else None, scroll_more=True)
        self.assertFalse(stage.tap("设置", scrolls=1))
        screen.click.assert_not_called()

    def test_the_long_loop_reports_the_miss_once(self):
        stage, screen = loop_navigator()
        self.assertFalse(stage.tap("我的", scrolls=1))
        self.assertEqual(stage.lost_note.miss, 1)
        screen.say.assert_called_once_with("  ✗ 没找到「我的」")


class AwaitPageDefaultsTests(unittest.TestCase):
    """`await_page()` 的默认预算与节奏：给假钟看它什么时候返回。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_a_settled_page_is_returned_after_two_samples(self):
        stage, screen = loop_navigator()
        screen.sig = Mock(return_value="settled")
        self.assertEqual(stage.await_page(), "settled")
        self.assertEqual(screen.sig.call_count, 2)
        self.assertEqual(self.clock.t, 0.2)

    def test_a_page_that_keeps_changing_times_out_at_the_budget(self):
        stage, screen = loop_navigator()
        screen.sig = Mock(side_effect=iter(range(100)))
        self.assertIsNone(stage.await_page())
        self.assertEqual(screen.sig.call_count, 12)
        self.assertAlmostEqual(self.clock.t, 2.4)


class EntryDefaultsTests(unittest.TestCase):
    """`entry()` 的两轮重试：后一轮等「与上一轮不同」的页面，预算摊到各轮。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_a_failed_entry_retries_twice_with_a_changed_page(self):
        stage, screen = loop_navigator()
        stage.lost_note.miss = 5
        seen_miss = []

        def tap(*args, **kw):
            seen_miss.append(stage.lost_note.miss)
            return False

        stage.tap = Mock(side_effect=tap)
        stage.await_page = Mock()
        screen.note_miss = Mock()
        self.assertFalse(stage.entry("设置", scrolls=2))
        self.assertEqual(seen_miss, [0, 0])          # 每轮进 tap 前丢失记录都是清零的
        self.assertEqual(stage.await_page.call_args_list,
                         [call(1.2, 0.2, changed_from=wait.UNSET),
                          call(1.2, 0.2, changed_from="sig")])
        stage.tap.assert_called_with("设置", exact=True, scrolls=2, quiet=True)
        self.assertEqual(stage.tap.call_count, 2)
        screen.note_miss.assert_called_once_with("设置")
        self.assertEqual(stage.lost_note.miss, 0)

    def test_a_found_entry_reports_success_and_clears_the_note(self):
        stage, screen = loop_navigator()
        stage.tap = Mock(return_value=True)
        stage.await_page = Mock()
        screen.note_miss = Mock()
        self.assertTrue(stage.entry("设置"))
        self.assertEqual(stage.tap.call_args.kwargs["scrolls"], 6)   # 默认翻六屏
        screen.note_miss.assert_not_called()
        self.assertEqual(stage.lost_note.miss, 0)


def give_up_after_one_look():
    """第一次返回「还没画出来」，之后判定这一页永远认不出：把失败路径的等待压到一拍。"""
    calls = []

    def find(text=None, exact=False, **kw):
        calls.append(text)
        if len(calls) % 2 == 0:
            raise wait.GiveUp
        return None
    return find


class TapIconTests(unittest.TestCase):
    """点没有文字的图标入口：候选取几个、等多久、失败时报什么。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_a_string_expect_is_one_criterion(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, **kw: (5, 5) if (text == "设置" and exact is True) else None)
        screen.icon_candidates = Mock(return_value=[(800, 100)])
        screen.page_text = Mock(return_value="首页")
        self.assertTrue(stage.tap_icon("设置"))
        screen.click.assert_called_once_with(800, 100)
        screen.say.assert_called_once_with("  · 点开了右上角图标（出现「设置」）")

    def test_a_list_expect_matches_any_of_its_words(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, **kw: (5, 5) if text == "个人" else None)
        screen.icon_candidates = Mock(return_value=[(800, 100)])
        screen.page_text = Mock(return_value="首页")
        self.assertTrue(stage.tap_icon(("设置", "个人")))
        screen.say.assert_called_once_with("  · 点开了右上角图标（出现「设置」）")

    def test_only_the_first_three_icons_are_tried(self):
        stage, screen = loop_navigator(find=give_up_after_one_look())
        screen.icon_candidates = Mock(return_value=[(1, 1), (2, 2), (3, 3), (4, 4)])
        screen.page_text = Mock(return_value="首页")
        self.assertFalse(stage.tap_icon("设置"))
        self.assertEqual(screen.click.call_count, 3)

    def test_the_failure_note_lists_the_current_page_text(self):
        stage, screen = loop_navigator(find=give_up_after_one_look())
        screen.icon_candidates = Mock(return_value=[(1, 1)])
        screen.page_text = Mock(return_value="屏幕上的字")
        self.assertFalse(stage.tap_icon("设置"))
        screen.say.assert_called_once_with("  · 当前页文字：屏幕上的字")

    def test_the_icon_window_is_the_two_point_four_second_budget(self):
        stage, screen = loop_navigator()
        screen.icon_candidates = Mock(return_value=[(1, 1)])
        screen.page_text = Mock(return_value="首页")
        self.assertFalse(stage.tap_icon("设置"))
        self.assertEqual(screen.find.call_count, 4)
        self.assertAlmostEqual(self.clock.t, 2.4)

    def test_a_wrong_page_is_left_with_the_animation_wait(self):
        stage, screen = loop_navigator(find=give_up_after_one_look())
        screen.icon_candidates = Mock(return_value=[(1, 1), (2, 2)])
        screen.focus = Mock(side_effect=[HOME, "other/.Main", HOME, HOME])
        screen.page_text = Mock(return_value="首页")
        self.assertFalse(stage.tap_icon("设置"))
        screen.back.assert_called_once()
        self.assertAlmostEqual(self.clock.t, 1.8)      # 每候选一次 0.6 秒轮询，加上退回后的 0.6 秒


class EnterTests(unittest.TestCase):
    """`enter()` 只给会换页的入口用：精确匹配优先，找不到退回包含匹配。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_exact_match_is_preferred_when_the_entry_is_on_screen(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, edge_ok=False, nav=False:
            (1, 1) if (text == "设置" and exact is True and edge_ok == "tab" and nav is True) else None)
        stage.tap = Mock(side_effect=lambda text, **kw: (kw["seen"].append("sig"), True)[1])
        self.assertIsNone(stage.enter("设置"))
        kwargs = stage.tap.call_args.kwargs
        self.assertIs(kwargs["exact"], True)
        self.assertEqual(kwargs["scrolls"], 0)
        screen.settle.assert_called_once_with("sig", 2.0)

    def test_a_bottom_tab_suffix_falls_back_to_contains(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, edge_ok=False, nav=False:
            (1, 1) if (text == "我的" and exact is False and edge_ok == "tab" and nav is True) else None)
        stage.tap = Mock(side_effect=lambda text, **kw: (kw["seen"].append("sig"), True)[1])
        self.assertIsNone(stage.enter("我的"))
        self.assertIs(stage.tap.call_args.kwargs["exact"], False)


class GoTests(unittest.TestCase):
    """`go()` 的落点重试：5 次找 expect、3 轮重点、精确不行退回包含。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_the_default_probes_exact_first_then_taps_loose(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, edge_ok=False, nav=False: (2, 2) if text == "设置" else None)
        stage.tap = Mock(return_value=True)
        self.assertTrue(stage.go("我的", "设置"))
        self.assertIs(screen.find.call_args_list[0].kwargs["exact"], True)   # 默认先精确探一次
        stage.tap.assert_called_once_with("我的", exact=False, scrolls=0)

    def test_an_explicit_exact_probe_stays_exact(self):
        def find(text, exact=False, edge_ok=False, nav=False):
            if text == "设置":
                return (2, 2)
            return (1, 1) if (exact is True and edge_ok == "tab" and nav is True) else None

        stage, screen = loop_navigator(find=find)
        stage.tap = Mock(return_value=True)
        self.assertTrue(stage.go("我的", "设置", exact=True))
        stage.tap.assert_called_once_with("我的", exact=True, scrolls=0)

    def test_a_landing_text_on_the_bottom_band_counts(self):
        stage, screen = loop_navigator(
            find=lambda text, exact=False, edge_ok=False, nav=False:
            (3, 3) if (text == "设置" and edge_ok == "tab") else None)
        stage.tap = Mock(return_value=True)
        self.assertTrue(stage.go("我的", "设置"))

    def test_three_tries_of_five_looks_each(self):
        stage, screen = loop_navigator()
        stage.tap = Mock(return_value=True)
        self.assertFalse(stage.go("我的", "设置"))
        self.assertEqual(screen.find.call_count, 31)      # 一次精确探测加三轮各五次两种查找
        self.assertAlmostEqual(self.clock.t, 4.5)
        screen.say.assert_called_once_with("  ✗ 点「我的」后没出现「设置」")


class TabTimingTests(unittest.TestCase):
    """`tab()` 的等待预算与点击前的签名。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_the_bottom_band_label_is_settled_from_the_signature_taken_first(self):
        p = tab_phone(tab_node(text="我的"))
        self.assertTrue(p.tab("我的"))
        p.screen.settle.assert_called_once_with("page", 1.0)

    def test_a_missing_tab_waits_six_seconds_by_default(self):
        """阶段的默认预算（门面总会显式传 6.0，默认值只有直接调阶段时才生效）。"""
        stage, screen = loop_navigator()
        screen.texts = Mock(return_value=[])
        stage.dismiss = Mock(return_value=None)
        lines = []
        screen.say = Mock(side_effect=lambda text: lines.append(text))
        self.assertFalse(stage.tab("我的"))
        self.assertAlmostEqual(self.clock.t, 6.0)
        self.assertEqual(screen.texts.call_count, 31)
        self.assertEqual(lines, ["  ✗ 底部没有「我的」标签"])

    def test_the_maxwait_deadline_is_reached_exactly(self):
        """6.0 秒整判超时：边界差一就会多看一眼、多等一拍。"""
        stage, screen = loop_navigator()
        screen.texts = Mock(return_value=[])
        stage.dismiss = Mock(return_value=None)
        screen.say = Mock()
        scripted = SimpleNamespace(
            time=Mock(side_effect=[0.0, 0.0, 3.0, 6.0, 9.0]), sleep=Mock())
        with patch.object(navigator, "time", scripted):
            self.assertFalse(stage.tab("我的", maxwait=6.0))
        self.assertEqual(screen.texts.call_count, 3)

    def test_a_closed_popup_does_not_delay_the_next_look(self):
        p = tab_phone()
        p.screen.texts = Mock(side_effect=[[], [("我的", (0, 2200, 216, 2300), None)]])
        p.dismiss = Mock(return_value=True)
        self.assertTrue(p.tab("我的"))
        self.assertEqual(self.clock.t, 0.0)
        p.screen.click.assert_called_once_with(108, 2250)

    def test_the_band_boundary_is_exclusive(self):
        p = tab_phone(tab_node(text="我的", area="[0,2040][216,2100]"))
        self.assertFalse(p.tab("我的", maxwait=0))
        p.screen.click.assert_not_called()

    def test_an_exact_label_wins_over_an_earlier_contains_match(self):
        p = tab_phone(tab_node(text="我的，设置x"), tab_node(text="我的，设置", area=TAB_RIGHT))
        self.assertTrue(p.tab("我的，设置"))
        p.screen.click.assert_called_once_with(972, 2250)


class CallGraphTests(unittest.TestCase):
    """阶段之间不互相 import，整张图无环：环从方法之间挪到模块之间不算断掉（#1044）。"""

    STAGES = {"toggler", "launcher", "settings_search", "dismisser", "navigator"}
    BASES = {"connection", "screen", "session"}

    def package_imports(self):
        """{模块: 它 import 的同包模块}，来自 `tool/phone/` 的源码。"""
        out = {}
        for path in sorted((ROOT / "tool" / "phone").glob("*.py")):
            if path.name == "__init__.py":
                continue
            graph = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("phone."):
                    graph.add(node.module.split(".", 1)[1])
                elif isinstance(node, ast.Import):
                    graph.update(a.name.split(".", 1)[1] for a in node.names
                                 if a.name.startswith("phone."))
            out[path.stem] = graph
        return out

    def test_phases_only_import_the_bases(self):
        graph = self.package_imports()
        self.assertTrue(self.STAGES <= set(graph), f"阶段模块不全：{sorted(graph)}")
        for stage in self.STAGES:
            others = graph[stage] - self.BASES
            self.assertEqual(others, set(), f"{stage} 直接 import 了 {sorted(others)}：应走注入的窄接口")

    def test_the_import_graph_has_no_cycle(self):
        graph = self.package_imports()

        def walk(node, seen):
            if node in seen:
                return True
            return any(walk(nxt, seen | {node}) for nxt in graph.get(node, ()))

        cycles = [node for node in graph if walk(node, frozenset())]
        self.assertEqual(cycles, [], f"包内 import 成环：{cycles}")


if __name__ == "__main__":
    unittest.main()
