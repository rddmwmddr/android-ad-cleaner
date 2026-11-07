"""#575：vivo 机型脚本的 gear() 点完要校验落地，点不动就继续找，最后回退到按文字点。

报告者那台上先命中的是一个点不动的图标，旧实现点完就 `return True`，
函数末尾按文字回退的那一句永远轮不到，整段在后面按旧页找入口、全部落空。

「点得动就一次进去」「无入口返回假」「回退成功也算数」三条在旧实现上本来就绿，
它们守的是原路径没被这几处校验改坏。
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
from fixtures import Clock, install_clock, load_recipe, phone_stub

RECIPES = [ROOT / "recipes/vivo-V2547DA/recipe.py",
           ROOT / "recipes/vivo-V2547DA/recipe_android17.py"]

MINE = "com.bbk.appstore/.MainActivity"
SETTINGS = "com.bbk.appstore/.ui.menu.AppstoreSettingsActivity"

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
    p = phone_stub("test", d=Mock(), W=1080, H=2400)
    p.tree = Mock(return_value=ET.fromstring(page))
    p.focus = Mock(return_value=focus)
    p.click = Mock()
    p.back = Mock()
    p.find = Mock(return_value=None)
    p.tap = Mock(return_value=False)
    return p


def gear(p, recipe=RECIPES[0]):
    scope, _ = load_recipe(p, recipe)
    return scope["gear"]()


class GearLandingTests(unittest.TestCase):
    def setUp(self):
        """点完要等页面站稳：await_page 读的是 fast 的时钟，换成假的才不真睡。"""
        original = fast.time
        install_clock(fast, Clock())
        self.addCleanup(setattr, fast, "time", original)
    def test_a_gear_that_does_not_open_settings_is_not_success(self):
        """点击被吞（页面没换）：不能当成进了设置页，要继续试下一个候选（#575）。"""
        p = gear_phone(TWO_GEARS)

        def click(x, y):
            if (x, y) == (810, 170):            # 前面那个：点了没反应
                return
            p.focus.return_value = SETTINGS    # 后面那个：真的进了设置页

        p.click.side_effect = click
        self.assertTrue(gear(p))
        self.assertEqual(p.click.call_count, 2)

    def test_the_text_fallback_is_also_checked_for_landing(self):
        """齿轮一个都没命中、按文字点也被吞：页面没换就不能报成功（#575）。"""
        p = gear_phone(NO_GEAR)
        p.tap.return_value = True
        self.assertFalse(gear(p))
        p.tap.assert_called_once_with("设置", exact=True, scrolls=0)

    def test_a_swallowed_click_does_not_count_on_a_page_that_already_looks_like_settings(self):
        """起始页的 Activity 本来就含 Setting 时，点击被吞仍不算这一次进了设置页（AC4）。"""
        p = gear_phone(ONE_GEAR, focus=SETTINGS)
        self.assertFalse(gear(p))
        p.click.assert_called_once()

    def test_a_working_gear_still_goes_in_on_the_first_tap(self):
        """点得动的齿轮仍按原路径进去，不多点一次。"""
        p = gear_phone(ONE_GEAR)
        p.click.side_effect = lambda x, y: setattr(p.focus, "return_value", SETTINGS)
        self.assertTrue(gear(p))
        self.assertEqual(p.click.call_count, 1)
        p.tap.assert_not_called()

    def test_a_gear_that_lands_on_another_page_is_not_success(self):
        """点到别的图标（换页但页上没有「设置」标题）：不算命中，先退回原页再试。"""
        p = gear_phone(ONE_GEAR)
        p.click.side_effect = lambda x, y: setattr(
            p.focus, "return_value", "com.bbk.appstore/.ui.Message")
        self.assertFalse(gear(p))
        p.back.assert_called_once()

    def test_a_wrong_page_is_left_before_trying_the_next_gear(self):
        """第一个候选点进了别的页：先退回来再试下一个，不能在新页上用旧树的坐标接着点。"""
        p = gear_phone(TWO_GEARS)

        def click(x, y):
            if (x, y) == (810, 170):
                p.focus.return_value = "com.bbk.appstore/.ui.Message"
            else:
                p.focus.return_value = SETTINGS

        p.click.side_effect = click
        p.back.side_effect = lambda *a: setattr(p.focus, "return_value", MINE)
        self.assertTrue(gear(p))
        self.assertEqual(p.click.call_count, 2)
        p.back.assert_called_once()

    def test_a_settings_page_without_setting_in_its_activity_still_counts(self):
        """App 自定义设置页的 Activity 名不含 Setting：换页后页面上出现「设置」标题也算进了。"""
        p = gear_phone(ONE_GEAR)

        def click(x, y):
            p.focus.return_value = "com.bbk.appstore/.ui.MinePrefs"
            p.find.return_value = (100, 200)

        p.click.side_effect = click
        self.assertTrue(gear(p))

    def test_a_settings_button_in_the_body_is_not_a_title(self):
        """换页后页面中部有「设置」按钮（不在标题带）：没换 Activity 就不算进了设置页。"""
        p = gear_phone(ONE_GEAR)

        def click(x, y):
            p.focus.return_value = "com.bbk.appstore/.ui.MinePrefs"
            p.find.return_value = (500, 1800)

        p.click.side_effect = click
        self.assertFalse(gear(p))

    def test_the_text_fallback_counts_when_it_opens_settings(self):
        p = gear_phone(NO_GEAR)

        def tap(text, **kw):
            p.focus.return_value = SETTINGS
            return True

        p.tap.side_effect = tap
        self.assertTrue(gear(p))

    def test_no_entry_at_all_returns_false_for_the_caller_to_skip(self):
        """页面没有任何入口：返回假，调用方跳过该段。"""
        p = gear_phone(NO_GEAR)
        self.assertFalse(gear(p))

    def test_both_v2547da_scripts_check_landing_the_same_way(self):
        for path in RECIPES:
            with self.subTest(recipe=path.name):
                p = gear_phone(NO_GEAR)
                p.tap.return_value = True
                self.assertFalse(gear(p, path))


if __name__ == "__main__":
    unittest.main()
