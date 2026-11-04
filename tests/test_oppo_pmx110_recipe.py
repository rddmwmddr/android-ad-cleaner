"""PMX110 机型脚本：#280 三处 —— 下拉搜索改走 scheme、轮播单选按标签配对并回读、游戏中心先跳首进引导。

下拉搜索的设置页没有导出，只能走应用自己的 scheme；搜索首页上有同名文字，认页不能让首页过关。
轮播推荐那一页的父容器会把两个选项的标签并成一段文字，按子串匹配会把「不显示」点到「显示」上，
不能点完就报告成功。游戏中心首次进入的引导浮层会盖住齿轮，跳过之后才算真的找到。
"""
import contextlib
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import phone_mock

RECIPE = ROOT / "recipes/oppo-PMX110/recipe.py"
SEARCH_SETTINGS_FOCUS = ("com.heytap.quicksearchbox/"
                         "com.heytap.quicksearchbox.ui.activity.SearchSettingActivity")
SEARCH_HOME_FOCUS = ("com.heytap.quicksearchbox/"
                     "com.heytap.quicksearchbox.ui.activity.MultiSearchHomeActivity")
# 冻结的认页词表：以后删词、改词都要在这里一起改，否则真机上认不出设置页不会报红。
RECOGNIZED_TITLES = {"搜索范围", "功能管理", "首页卡片管理", "消息管理", "账号与隐私"}


class FakeClock:
    """假时钟：等落点、等浮层消失的循环按它推进，用例不必真睡。"""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


@contextlib.contextmanager
def frozen_time():
    clock = FakeClock()
    with patch.object(time, "monotonic", clock.monotonic), \
            patch.object(time, "sleep", clock.sleep):
        yield clock


def load(phone, only=("__no_steps__",), out=None):
    scope = {"p": phone, "ONLY": list(only)}
    with contextlib.redirect_stdout(out if out is not None else io.StringIO()):
        exec(compile(RECIPE.read_text(encoding="utf-8"), str(RECIPE), "exec"), scope)
    return scope


def texts(*labels):
    return [(label, (0, 0, 0, 0), {}) for label in labels]


def search_page():
    return ET.fromstring('''<hierarchy>
      <node text="搜索" bounds="[0,0][1080,120]"/>
      <node text="搜索范围" clickable="true" bounds="[0,200][1080,300]"/>
      <node text="首页卡片管理" clickable="true" bounds="[0,320][1080,420]"/>
      <node text="功能管理" clickable="true" bounds="[0,440][1080,540]"/>
      <node text="消息管理" clickable="true" bounds="[0,560][1080,660]"/>
      <node text="账号与隐私" clickable="true" bounds="[0,680][1080,780]"/>
    </hierarchy>''')


def carousel_page():
    """父容器把两个选项的标签并成一段文字；预览区另有一段同名文字（不是可点目标）。"""
    return ET.fromstring('''<hierarchy>
      <node text="推荐服务" bounds="[0,0][1080,150]"/>
      <node text="不显示轮播推荐" bounds="[40,1000][600,1080]"/>
      <node class="android.widget.LinearLayout" text="显示轮播推荐 不显示轮播推荐"
            bounds="[0,1600][1080,2100]">
        <node class="android.widget.LinearLayout" bounds="[0,1600][1080,1840]">
          <node text="显示轮播推荐" bounds="[60,1600][700,1680]"/>
          <node class="android.widget.RadioButton" checkable="true" checked="true"
                enabled="true" bounds="[60,1700][140,1780]"/>
        </node>
        <node class="android.widget.LinearLayout" bounds="[0,1860][1080,2100]">
          <node text="不显示轮播推荐" bounds="[60,1900][700,1980]"/>
          <node class="android.widget.RadioButton" checkable="true" checked="false"
                enabled="true" bounds="[60,2000][140,2080]"/>
        </node>
      </node>
    </hierarchy>''')


def game_page():
    return ET.fromstring('''<hierarchy>
      <node content-desc="设置,有新通知" clickable="true" bounds="[900,60][1020,180]"/>
      <node text="隐私" clickable="true" bounds="[0,300][1080,400]"/>
      <node text="隐私开关设置" clickable="true" bounds="[0,500][1080,600]"/>
      <node text="个性化推荐管理" clickable="true" bounds="[0,700][1080,800]"/>
    </hierarchy>''')


class SearchEntryTests(unittest.TestCase):
    def phone(self, focus, labels):
        p = phone_mock(W=1080, H=2340)
        p.locked.return_value = False
        p.focus.return_value = focus
        p.texts.return_value = texts(*labels)
        p.tree = search_page
        p.tap.return_value = True
        return p

    def test_scheme_opens_settings_and_every_group_is_read_back(self):
        p = self.phone(SEARCH_SETTINGS_FOCUS, ["搜索范围", "功能管理"])
        with frozen_time():
            scope = load(p, only=("下拉搜索",))
        self.assertIn("gs://search/setting", p.d.shell.call_args_list[0].args[0])
        self.assertEqual([c.kwargs["page"] for c in p.off.call_args_list],
                         ["下拉搜索·搜索范围", "下拉搜索·首页卡片管理", "下拉搜索·功能管理",
                          "下拉搜索·消息管理", "下拉搜索·隐私"])
        self.assertEqual(p.off.call_args_list[0].kwargs["only"],
                         ["榜单", "小说", "购物", "个性化推荐", "精选资讯"])
        self.assertEqual(p.off.call_args_list[3].kwargs["only"], ["消息通知"])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_settings_page_without_titles_is_not_accepted(self):
        """前台是设置页、标题还没画完时不能放行：两个判据都要认得出。"""
        p = self.phone(SEARCH_SETTINGS_FOCUS, ["应用建议"])
        with frozen_time():
            scope = load(p, only=("下拉搜索",))
        self.assertEqual(scope["FAILED_STEPS"], ["下拉搜索"])
        p.off.assert_not_called()

    def test_borrowed_recipe_leaves_search_sources_alone(self):
        """借给别的机型（安全模式）时只关推荐位：榜单 / 小说 / 购物在 ColorOS 17 上是内容源。"""
        p = self.phone(SEARCH_SETTINGS_FOCUS, ["搜索范围"])
        p.safe_mode = True
        with frozen_time():
            load(p, only=("下拉搜索",))
        self.assertEqual(p.off.call_args_list[0].kwargs["only"], ["个性化推荐", "精选资讯"])

    def test_search_home_is_not_mistaken_for_the_settings_page(self):
        """同一个包的搜索首页也读得到「搜索范围」：前台不是设置页就不算打开，也不退回滑动找入口。"""
        p = self.phone(SEARCH_HOME_FOCUS, ["应用建议"])
        out = io.StringIO()
        with frozen_time():
            scope = load(p, only=("下拉搜索",), out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["下拉搜索"])
        p.off.assert_not_called()
        p.tap.assert_not_called()
        self.assertIn(SEARCH_HOME_FOCUS, out.getvalue())
        commands = [c.args[0] for c in p.d.shell.call_args_list]
        self.assertFalse([c for c in commands if "input swipe" in c])

    def test_recognized_page_titles_are_frozen(self):
        scope = load(self.phone(SEARCH_SETTINGS_FOCUS, ["搜索范围"]))
        self.assertEqual(scope["SEARCH_TITLES"], RECOGNIZED_TITLES)


class CarouselTests(unittest.TestCase):
    def phone(self, root):
        p = phone_mock(W=1080, H=2340)
        p.locked.return_value = False
        p.tree = lambda: root
        p.on_screen.return_value = True
        p.focus.return_value = "com.coloros.assistantscreen/setting.RecommendServiceSettingActivity"
        return p

    def click_to(self, root, target_bounds):
        def click(*_):
            for n in root.iter("node"):
                if n.get("class", "").endswith("RadioButton"):
                    n.set("checked", "true" if n.get("bounds") == target_bounds else "false")
        return click

    def test_merged_parent_does_not_invert_the_radio(self):
        """父容器合并成一段文字时也要点到「不显示」，不能落到第一个按钮（显示）上。"""
        root = carousel_page()
        p = self.phone(root)
        p.click.side_effect = self.click_to(root, "[60,2000][140,2080]")
        scope = load(p)
        with frozen_time():
            self.assertTrue(scope["pick_radio"]("不显示轮播推荐"))
        p.click.assert_called_once_with(100, 2040)

    def test_already_off_target_is_left_alone(self):
        root = carousel_page()
        for n in root.iter("node"):
            if n.get("bounds") == "[60,1700][140,1780]":
                n.set("checked", "false")
            if n.get("bounds") == "[60,2000][140,2080]":
                n.set("checked", "true")
        p = self.phone(root)
        scope = load(p)
        with frozen_time():
            self.assertTrue(scope["pick_radio"]("不显示轮播推荐"))
        p.click.assert_not_called()

    def test_two_labels_in_one_row_are_not_guessed(self):
        """一行里读到两个标签命中：无法确定按钮对应哪一项，不点击。"""
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.LinearLayout">
            <node text="显示轮播推荐" bounds="[60,1000][700,1080]"/>
            <node text="不显示轮播推荐" bounds="[60,1400][700,1480]"/>
            <node class="android.widget.RadioButton" checkable="true" checked="true"
                  enabled="true" bounds="[60,1100][140,1180]"/>
          </node>
        </hierarchy>''')
        p = self.phone(root)
        scope = load(p)
        with self.assertRaisesRegex(RuntimeError, "无法确认"):
            scope["carousel_choices"]()
        p.click.assert_not_called()

    def test_missing_checked_state_is_not_guessed(self):
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.LinearLayout">
            <node text="显示轮播推荐" bounds="[60,1000][700,1080]"/>
            <node class="android.widget.RadioButton" checkable="true" enabled="true"
                  bounds="[60,1100][140,1180]"/>
          </node>
          <node class="android.widget.LinearLayout">
            <node text="不显示轮播推荐" bounds="[60,1300][700,1380]"/>
            <node class="android.widget.RadioButton" checkable="true" checked="false"
                  enabled="true" bounds="[60,1400][140,1480]"/>
          </node>
        </hierarchy>''')
        p = self.phone(root)
        scope = load(p)
        with self.assertRaisesRegex(RuntimeError, "状态未知"):
            scope["carousel_choices"]()
        p.click.assert_not_called()

    def test_click_without_state_change_is_reported_as_failure(self):
        root = carousel_page()
        p = self.phone(root)
        scope = load(p)
        with frozen_time():
            with self.assertRaisesRegex(RuntimeError, "回读未选中"):
                scope["pick_radio"]("不显示轮播推荐")
        self.assertEqual(p.click.call_count, 1)

    def test_page_change_between_read_and_click_cancels_the_click(self):
        root = carousel_page()
        p = self.phone(root)
        p.focus.side_effect = ["a/RadioPage", "b/OtherPage"]
        scope = load(p)
        with frozen_time():
            with self.assertRaisesRegex(RuntimeError, "读取与点击之间"):
                scope["pick_radio"]("不显示轮播推荐")
        p.click.assert_not_called()


class NegativeScreenTests(unittest.TestCase):
    def test_carousel_failure_still_runs_the_rest_of_the_step(self):
        """轮播定不下来只记这一项失败：同段的「热点资讯」照常关，手机不会停在二级页。"""
        p = phone_mock(W=1080, H=2340)
        p.locked.return_value = False
        p.texts.return_value = texts("应用建议")
        p.tap.return_value = True
        p.tree = lambda: ET.fromstring('''<hierarchy>
          <node resource-id="com.coloros.assistantscreen:id/head_icon"
                clickable="true" bounds="[40,80][160,200]"/>
          <node text="推荐服务" clickable="true" bounds="[0,900][1080,1000]"/>
          <node text="热点资讯" clickable="true" bounds="[0,1200][1080,1300]"/>
          <node class="android.widget.RadioButton" checkable="true" checked="true"
                enabled="true" bounds="[60,1500][140,1580]"/>
        </hierarchy>''')
        out = io.StringIO()
        with frozen_time():
            scope = load(p, only=("负一屏",), out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["负一屏"])
        self.assertEqual([c.kwargs["page"] for c in p.off.call_args_list],
                         ["负一屏", "负一屏·热点资讯"])
        self.assertIn("轮播推荐没改成", out.getvalue())


class GameCenterGuideTests(unittest.TestCase):
    def phone(self):
        p = phone_mock(W=1080, H=2340)
        p.locked.return_value = False
        p.tree = game_page
        return p

    def test_first_run_overlay_is_skipped_before_the_gear(self):
        p = self.phone()
        overlay = {"up": True}

        def find(text, **kwargs):
            return (100, 100) if text == "跳过" and overlay["up"] else None

        def tap(text, **kwargs):
            if text == "跳过":
                overlay["up"] = False
            return True

        p.find.side_effect = find
        p.tap.side_effect = tap
        with frozen_time():
            scope = load(p, only=("游戏中心",))
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["跳过", "我的"])
        self.assertEqual(p.click.call_args_list[0].args, (960, 120))
        self.assertEqual([c.kwargs["page"] for c in p.off.call_args_list], ["游戏中心·个性化"])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_overlay_that_never_closes_fails_the_step(self):
        p = self.phone()
        p.find.side_effect = lambda text, **kwargs: (100, 100)
        p.tap.return_value = True
        out = io.StringIO()
        with frozen_time():
            scope = load(p, only=("游戏中心",), out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["游戏中心"])
        p.off.assert_not_called()
        self.assertIn("首进引导浮层", out.getvalue())

    def test_no_overlay_goes_straight_to_the_gear(self):
        p = self.phone()
        p.find.return_value = None
        p.tap.return_value = True
        with frozen_time():
            scope = load(p, only=("游戏中心",))
        p.find.assert_any_call("跳过", exact=True)
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["我的"])
        self.assertEqual(scope["FAILED_STEPS"], [])


if __name__ == "__main__":
    unittest.main()
