"""PMX110 机型脚本：保留搜索数据源与服务通知，只关点名的广告与推荐（#598）。

搜索范围里的榜单 / 小说 / 购物是数据源，搜索与主题的「消息通知」是服务通知，营销留给
chan-scan / chan-off 在渠道级处理。关闭前先读整页并核对目标存在，关闭后回读目标已关、
非目标未变。轮播推荐那一页的父容器会把两个选项的标签并成一段文字，按子串匹配会把
「不显示」点到「显示」上（#280）。脚本按录制版本钉住 BUILD，不留 `recipe_<版本>.py` 变体。
"""
import ast
import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock, phone_stub
import fast
import run

RECIPE = ROOT / "recipes/oppo-PMX110/recipe.py"
RECORDED = "PMX110_17.0.0.116(CN01)"
SEARCH_SETTINGS_FOCUS = ("com.heytap.quicksearchbox/"
                         "com.heytap.quicksearchbox.ui.activity.SearchSettingActivity")
SEARCH_HOME_FOCUS = ("com.heytap.quicksearchbox/"
                     "com.heytap.quicksearchbox.ui.activity.MultiSearchHomeActivity")


def load(phone, only=("__no_steps__",), out=None):
    scope, _ = load_recipe(phone, RECIPE, only, out)
    return scope


def action(scope, name):
    """取真实分段的函数体，以便给它的协作者注入失败；不复制分段实现。"""
    node = next(n for n in ast.parse(RECIPE.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.decorator_list
                and n.decorator_list[0].args[0].value == name)
    node.decorator_list, node.name = [], "selected_action"
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(RECIPE), "exec"), scope)
    return scope["selected_action"]


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


class RecipeSelectionTests(unittest.TestCase):
    def test_script_is_the_only_one_for_the_model(self):
        path, ref = run.recipe_for("PMX110", "OPPO", {"build": RECORDED, "os": ""})
        self.assertEqual(Path(path), RECIPE)
        self.assertFalse(ref)
        self.assertEqual(sorted(p.name for p in RECIPE.parent.glob("recipe_*.py")), [])

    def test_build_stays_at_the_generation_so_siblings_can_borrow_it(self):
        """BUILD 写细到 17.0.0.116，同族的 ColorOS 17 机型就借不到这份脚本（#319 / #483）。"""
        self.assertEqual(run.recipe_meta(RECIPE)["build"], "PMX110_17.0.0")
        path, ref = run.recipe_for("PJZ110", "OnePlus", {"build": "PJZ110_17.0.0.103(CN01)", "os": ""})
        self.assertEqual(Path(path), RECIPE)
        self.assertTrue(ref)

    def test_all_nine_segments_survive(self):
        self.assertEqual(run.recipe_meta(RECIPE)["steps"],
                         ["广告跟踪", "浏览器", "软件商店", "下拉搜索", "负一屏",
                          "主题", "视频", "游戏中心", "小布建议"])


class CloseNamedTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.scope = load(self.p)

    def close(self, before, after, names=("开屏广告",), **kwargs):
        self.scope["read_switches"] = Mock(side_effect=[before, after])
        return self.scope["close_named"](names, "测试设置", **kwargs)

    def test_missing_target_stops_before_any_switch_operation(self):
        self.scope["read_switches"] = Mock(return_value={"消息通知": True})
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            self.scope["close_named"](["开屏广告"], "测试设置")
        self.scope["read_switches"].assert_called_once_with("测试设置", 12)
        self.p.off.assert_not_called()

    def test_already_closed_targets_are_read_once_without_clicking(self):
        self.scope["read_switches"] = Mock(return_value={"开屏广告": False, "消息通知": True})
        self.scope["close_named"](["开屏广告"], "测试设置")
        self.scope["read_switches"].assert_called_once_with("测试设置", 12)
        self.p.off.assert_not_called()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_similar_titles_and_message_master_are_kept(self):
        self.close({"开屏广告": True, "开屏广告设置帮助": True, "消息通知": True},
                   {"开屏广告": False, "开屏广告设置帮助": True, "消息通知": True})
        self.p.off.assert_called_once()
        options = self.p.off.call_args.kwargs
        self.assertEqual(options["only"], ["开屏广告"])
        self.assertEqual(set(options["keep"]), {"开屏广告设置帮助", "消息通知"})
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_reverted_target_fails_readback(self):
        with self.assertRaisesRegex(RuntimeError, "回读未确认"):
            self.close({"开屏广告": True}, {"开屏广告": True})
        self.p.off.assert_called_once()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 0)

    def test_unrelated_function_change_fails_readback(self):
        with self.assertRaisesRegex(RuntimeError, "其他功能开关"):
            self.close({"开屏广告": True, "消息通知": True},
                       {"开屏广告": False, "消息通知": False})
        self.p.off.assert_called_once()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 0)

    def test_optional_row_missing_is_reported_instead_of_closed(self):
        self.close({"个性化广告推荐": True}, {"个性化广告推荐": False},
                   names=["个性化广告推荐", "个性化内容推荐"], optional=["个性化内容推荐"])
        self.p.off.assert_called_once()
        self.assertEqual(self.p.off.call_args.kwargs["only"], ["个性化广告推荐"])
        self.assertEqual(len(self.scope["SKIPPED_ITEMS"]), 1)
        self.assertIn("个性化内容推荐", self.scope["SKIPPED_ITEMS"][0])
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_optional_row_present_is_closed_like_the_rest(self):
        self.close({"个性化广告推荐": True, "个性化内容推荐": True},
                   {"个性化广告推荐": False, "个性化内容推荐": False},
                   names=["个性化广告推荐", "个性化内容推荐"], optional=["个性化内容推荐"])
        self.assertEqual(set(self.p.off.call_args.kwargs["only"]), {"个性化广告推荐", "个性化内容推荐"})
        self.assertEqual(self.scope["SKIPPED_ITEMS"], [])

    def test_search_aggregate_may_follow_children_but_sources_are_kept(self):
        self.close({"精选资讯": True, "全部": True, "本机应用": True, "购物": True},
                   {"精选资讯": False, "全部": False, "本机应用": True, "购物": True},
                   names=["精选资讯"], dependent=["全部"])
        self.p.off.assert_called_once()
        self.assertIn("购物", self.p.off.call_args.kwargs["keep"])

    def test_theme_reopens_before_readback(self):
        events = []
        values = iter([{"个性化推荐设置": True}, {"个性化推荐设置": False}])
        def read(*_):
            events.append("读取")
            return next(values)
        self.scope["read_switches"] = Mock(side_effect=read)
        reopen = Mock(side_effect=lambda: events.append("重新进入"))
        self.scope["close_named"](["个性化推荐设置"], "隐私", reopen=reopen)
        reopen.assert_called_once_with()
        self.assertEqual(self.scope["read_switches"].call_count, 2)
        self.assertEqual(events, ["读取", "重新进入", "读取"])


class ReadSwitchesTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.locked.return_value = False
        self.scope = load(self.p)
        self.scope["page"] = Mock()
        self.scope["switch_top"] = Mock()

    def test_merges_multiple_screens(self):
        self.p.switches.side_effect = [[("第一项", True, (100, 500))],
                                       [("第二项", False, (100, 500))],
                                       [("第二项", False, (100, 500))]]
        self.p.scroll_more.side_effect = [True, False]
        self.assertEqual(self.scope["read_switches"]("隐私", 2), {"第一项": True, "第二项": False})
        self.scope["page"].assert_called_once_with("隐私")
        self.scope["switch_top"].assert_called_once_with(2)
        self.assertEqual(self.p.switches.call_count, 3)

    def test_incomplete_list_is_never_modified(self):
        self.p.switches.side_effect = [[("广告", True, (100, y))] for y in (500, 600, 700)]
        self.p.scroll_more.return_value = True
        with self.assertRaisesRegex(RuntimeError, "超过读取上限"):
            self.scope["read_switches"]("隐私", 2)
        self.p.off.assert_not_called()

    def test_dynamic_non_switch_text_does_not_prevent_end_detection(self):
        self.p.switches.return_value = [("已关闭的许可", False, (100, 500))]
        self.p.scroll_more.return_value = True  # 全页的访问时间仍在刷新。
        self.assertEqual(self.scope["read_switches"]("广告跟踪", 3), {"已关闭的许可": False})
        self.p.scroll_more.assert_called_once_with()

    def test_same_name_with_mixed_states_is_rejected(self):
        self.p.switches.return_value = [("同名应用", True, (100, 500)),
                                        ("同名应用", False, (100, 600))]
        self.p.scroll_more.return_value = True
        with self.assertRaisesRegex(RuntimeError, "同名开关状态不一致"):
            self.scope["read_switches"]("广告跟踪", 3)
        self.p.off.assert_not_called()

class SwitchTopTests(unittest.TestCase):
    def test_top_uses_switch_rows_instead_of_changing_page_text(self):
        p = phone_mock(W=1272, H=2772)
        p.locked.return_value = False
        p.switches.return_value = [("许可", False, (100, 500))]
        scope = load(p)
        scope["switch_top"](80)
        p.top.assert_called_once_with(1)
        self.assertEqual(p.switches.call_count, 2)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.locked.return_value = False
        self.p.focus.return_value = "test/Settings"
        self.p.texts.return_value = []
        self.scope = load(self.p)

    def test_denied_public_entry_stops_before_page_or_taps(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=1, output="Permission Denial")
        self.scope["page"] = Mock()
        with self.assertRaisesRegex(RuntimeError, "系统未允许"):
            self.scope["open_page"]("am start", "隐私", "test")
        self.p.d.shell.assert_called_once_with("am start")
        self.scope["page"].assert_not_called()
        self.p.click.assert_not_called()

    def test_consent_dialog_is_rejected_before_switches(self):
        button = ET.fromstring('<node class="android.widget.Button"/>')
        self.p.texts.return_value = [("同意并继续", (0, 0, 100, 100), button)]
        with self.assertRaisesRegex(self.scope["SkipStep"], "不代为同意"):
            self.scope["page"]("隐私")
        self.p.dismiss.assert_called_once_with()
        self.p.off.assert_not_called()

    def test_wrong_activity_stops_even_if_title_matches(self):
        self.p.focus.return_value = "test/MainActivity"
        with self.assertRaisesRegex(RuntimeError, "未进入目标设置页"):
            self.scope["page"]("设置", "test", "SettingActivity")
        self.p.off.assert_not_called()

    def test_row_click_must_change_page(self):
        self.p.tree.return_value = ET.fromstring(
            '<hierarchy><node text="隐私" clickable="true" bounds="[0,500][1000,600]"/></hierarchy>')
        self.p.on_screen.return_value = True
        self.p.settle.return_value = False
        self.scope["page"] = Mock()
        with self.assertRaisesRegex(RuntimeError, "页面没有变化"):
            self.scope["row"]("隐私")
        self.p.click.assert_called_once_with(500, 550)
        self.scope["page"].assert_not_called()
        self.p.off.assert_not_called()

    def test_visible_description_only_settings_icon_is_not_scrolled_away(self):
        self.p.tree.return_value = ET.fromstring(
            '<hierarchy><node content-desc="设置" clickable="true" bounds="[900,100][1000,200]"/></hierarchy>')
        self.p.on_screen.return_value = True
        self.p.settle.return_value = True
        self.scope["page"] = Mock()
        self.scope["row"]("设置", title="推荐服务")
        self.p.click.assert_called_once_with(950, 150)
        self.p.top.assert_not_called()
        self.scope["page"].assert_called_once_with("推荐服务", None, None)


class SearchStepTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1080, H=2340)
        self.p.locked.return_value = False
        self.p.texts.return_value = []
        self.scope = load(self.p)

    def test_search_never_touches_message_master_or_sources(self):
        self.scope["open_page"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        self.scope["read_switches"] = Mock(
            return_value={name: False for name in self.scope["SEARCH_CARDS"]})
        action(self.scope, "下拉搜索")()
        self.scope["open_page"].assert_called_once()
        self.scope["read_switches"].assert_called_once_with("首页卡片管理")
        names = [name for c in self.scope["close_named"].call_args_list for name in c.args[0]]
        self.assertEqual(names, ["个性化推荐", "精选资讯", "未下载应用推荐", "应用建议小卡", "热搜应用",
                                 "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片", "搜索框提示词", "个性化推荐"])
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list],
                         ["搜索范围", "首页卡片管理", "功能管理", "隐私"])
        self.assertNotIn("榜单", names)
        self.assertNotIn("小说", names)
        self.assertNotIn("购物", names)
        self.assertNotIn("消息通知", names)

    def test_empty_card_page_is_reported_without_claiming_verified_items(self):
        self.scope["open_page"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        self.scope["read_switches"] = Mock(return_value={})
        action(self.scope, "下拉搜索")()
        self.assertEqual([c.args[1] for c in self.scope["close_named"].call_args_list],
                         ["搜索范围", "功能管理", "隐私"])
        self.assertEqual(len(self.scope["SKIPPED_ITEMS"]), 1)
        self.assertIn("7", self.scope["SKIPPED_ITEMS"][0])

    def test_settings_page_without_titles_is_not_accepted(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="")
        self.p.focus.return_value = SEARCH_SETTINGS_FOCUS
        self.p.find.return_value = False
        scope = load(self.p, only=("下拉搜索",))
        self.assertEqual(scope["FAILED_STEPS"], ["下拉搜索"])
        self.p.off.assert_not_called()

    def test_search_home_is_not_mistaken_for_the_settings_page(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="")
        self.p.focus.return_value = SEARCH_HOME_FOCUS
        self.p.find.return_value = True
        scope = load(self.p, only=("下拉搜索",))
        self.assertEqual(scope["FAILED_STEPS"], ["下拉搜索"])
        self.p.off.assert_not_called()
        self.p.click.assert_not_called()
        commands = [c.args[0] for c in self.p.d.shell.call_args_list]
        self.assertFalse([c for c in commands if "input swipe" in c])


class StoreThemeVideoTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1080, H=2340)
        self.p.locked.return_value = False
        self.p.texts.return_value = []
        self.scope = load(self.p)

    def test_store_closes_named_promotions_only(self):
        self.scope["app_settings"] = Mock()
        self.scope["row"] = Mock()
        self.scope["read_switches"] = Mock(return_value={"首页：活动弹窗": True, "应用安全": True,
            "帮助与客服": True, "首页：AI搜索": True, "游戏专区：找游戏": True, "AI智能体": True})
        self.scope["close_named"] = Mock()
        action(self.scope, "软件商店")()
        self.scope["read_switches"].assert_called_once_with("服务管理")
        self.assertEqual(self.scope["app_settings"].call_args_list,
                         [call("com.heytap.market"), call("com.heytap.market")])
        self.assertEqual(self.scope["row"].call_args_list,
                         [call("隐私"), call("个性化推荐"), call("服务管理")])
        self.assertEqual([c.args[0] for c in self.scope["close_named"].call_args_list],
                         [["个性化推荐"], ["首页：活动弹窗"]])

    def menu(self, *screens):
        """每次读屏返回一屏菜单文字；「已停用」写在读屏描述里（PMX110 实测）。"""
        frames = iter(screens)
        node = ET.fromstring("<node/>")
        current = []
        def texts():
            return [(t, (0, 0, 1, 1), node) for t in current]
        def advance():
            current[:] = next(frames)
            return True
        self.p.tap.side_effect = lambda text, **kw: advance() if text in ("更多选项", "更多") else True
        self.p.texts.side_effect = texts

    def test_ad_tracking_menu_already_grey_is_not_clicked(self):
        self.menu(["显示系统应用 - 未选中", "显示系统应用", "全部关闭 - 已停用", "全部关闭"])
        self.scope["close_all_listed"]("用户应用")
        tapped = [c.args[0] for c in self.p.tap.call_args_list]
        self.assertNotIn("全部关闭", tapped)

    def test_ad_tracking_grey_label_with_suffix_alone_is_still_disabled(self):
        """置灰只体现为一条带后缀的文字（text 为空、content-desc 为「全部关闭 - 已停用」）时也要认。"""
        self.menu(["全部关闭 - 已停用"])
        self.scope["close_all_listed"]("用户应用")
        self.assertNotIn("全部关闭", [c.args[0] for c in self.p.tap.call_args_list])

    def test_ad_tracking_disabled_flag_alone_is_still_disabled(self):
        """置灰只落在节点 enabled=false 上（文字仍是「全部关闭」）时也要认。"""
        node = ET.fromstring('<node text="全部关闭" enabled="false"/>')
        self.p.texts.return_value = [("全部关闭", (0, 0, 1, 1), node)]
        self.p.tap.return_value = True
        self.scope["close_all_listed"]("用户应用")
        self.assertNotIn("全部关闭", [c.args[0] for c in self.p.tap.call_args_list])

    def test_ad_tracking_close_all_must_turn_grey(self):
        self.menu(["显示系统应用", "全部关闭"], ["显示系统应用", "全部关闭"])
        with self.assertRaisesRegex(RuntimeError, "仍有开着的应用"):
            self.scope["close_all_listed"]("用户应用")
        self.assertIn("全部关闭", [c.args[0] for c in self.p.tap.call_args_list])

    def test_ad_tracking_close_all_confirmed_by_grey_item(self):
        self.menu(["显示系统应用", "全部关闭"], ["显示系统应用", "全部关闭 - 已停用", "全部关闭"])
        self.scope["close_all_listed"]("用户应用")
        self.p.confirm.assert_called()

    def test_game_center_goes_straight_to_privacy_switch_settings(self):
        self.scope["require_installed"] = Mock()
        self.scope["open_page"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        action(self.scope, "游戏中心")()
        self.assertIn("APP_SETTINGS -p com.nearme.gamecenter", self.scope["open_page"].call_args.args[0])
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list], ["隐私开关设置", "个性化推荐管理"])

    def test_theme_only_closes_the_ad_switch(self):
        self.scope["app_settings"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        action(self.scope, "主题")()
        self.assertEqual([c.args[0] for c in self.scope["close_named"].call_args_list],
                         [["开屏广告"], ["个性化推荐设置"]])
        self.assertEqual([c.args[1] for c in self.scope["close_named"].call_args_list],
                         ["消息与广告", "隐私"])
        self.assertEqual(self.scope["app_settings"].call_args_list,
                         [call("com.heytap.themestore"), call("com.heytap.themestore")])

    def test_browser_treats_content_recommendation_as_optional(self):
        self.scope["browser_settings"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        action(self.scope, "浏览器")()
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list],
                         ["隐私", "广告管理", "个性化管理"])
        self.assertEqual([c.args[0] for c in self.scope["close_named"].call_args_list],
                         [["开屏广告", "资讯列表广告", "摇一摇广告"],
                          ["个性化广告推荐", "个性化内容推荐"]])
        self.assertEqual(self.scope["close_named"].call_args_list[1].kwargs,
                         {"optional": ["个性化内容推荐"]})

    def test_video_missing_app_skips_without_launching(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="")
        with self.assertRaisesRegex(self.scope["SkipStep"], "未安装视频"):
            action(self.scope, "视频")()
        self.p.d.shell.assert_called_once_with("pm path com.heytap.yoli")
        self.p.start.assert_not_called()
        self.p.off.assert_not_called()

    def test_video_settings_open_by_deep_link(self):
        """设置页用 App 自己的深链直达（#650），不经开屏页和「我的」。"""
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="package:/system/video.apk")
        self.p.focus.return_value = "com.heytap.yoli/com.heytap.yoli.mine.setting.SettingActivity"
        self.p.find.return_value = True
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        action(self.scope, "视频")()
        launch = self.p.d.shell.call_args_list[1].args[0]
        self.assertIn("yoli://yoli.com/mine_act_lib_yoli/settings", launch)
        self.assertIn("-p com.heytap.yoli", launch)          # 别的 App 也注册 scheme 时不弹选择器
        self.p.start.assert_not_called()
        self.p.tab.assert_not_called()

    def test_video_wrong_landing_stops_before_personalization(self):
        """深链没落到 SettingActivity 就停本段，不接着在别的页里关开关。"""
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="package:/system/video.apk")
        self.p.focus.return_value = "com.heytap.yoli/MainActivity"
        self.p.find.return_value = True
        with self.assertRaisesRegex(RuntimeError, "未进入目标设置页"):
            action(self.scope, "视频")()
        self.p.off.assert_not_called()


class CarouselTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1080, H=2340)
        self.p.locked.return_value = False
        self.p.on_screen.return_value = True
        self.p.focus.return_value = "com.coloros.assistantscreen/setting.RecommendServiceSettingActivity"
        self.scope = load(self.p)
        self.scope["read_switches"] = Mock(return_value={"推荐服务": True})

    def click_to(self, root, target_bounds):
        def click(*_):
            for n in root.iter("node"):
                if n.get("class", "").endswith("RadioButton"):
                    n.set("checked", "true" if n.get("bounds") == target_bounds else "false")
        return click

    def test_merged_parent_does_not_invert_the_radio(self):
        root = carousel_page()
        self.p.tree.return_value = root
        self.p.click.side_effect = self.click_to(root, "[60,2000][140,2080]")
        self.scope["hide_carousel"]()
        self.p.click.assert_called_once_with(100, 2040)
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_already_off_target_is_left_alone(self):
        root = carousel_page()
        for n in root.iter("node"):
            if n.get("bounds") == "[60,1700][140,1780]":
                n.set("checked", "false")
            if n.get("bounds") == "[60,2000][140,2080]":
                n.set("checked", "true")
        self.p.tree.return_value = root
        self.scope["hide_carousel"]()
        self.p.click.assert_not_called()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_two_labels_in_one_row_are_not_guessed(self):
        self.p.tree.return_value = ET.fromstring('''<hierarchy>
          <node class="android.widget.LinearLayout">
            <node text="显示轮播推荐" bounds="[60,1000][700,1080]"/>
            <node text="不显示轮播推荐" bounds="[60,1400][700,1480]"/>
            <node class="android.widget.RadioButton" checkable="true" checked="true"
                  enabled="true" bounds="[60,1100][140,1180]"/>
          </node>
        </hierarchy>''')
        with self.assertRaisesRegex(RuntimeError, "无法确认"):
            self.scope["hide_carousel"]()
        self.p.click.assert_not_called()

    def test_missing_checked_state_is_not_guessed(self):
        self.p.tree.return_value = ET.fromstring('''<hierarchy>
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
        with self.assertRaisesRegex(RuntimeError, "状态未知"):
            self.scope["hide_carousel"]()
        self.p.click.assert_not_called()

    def test_click_without_state_change_is_reported_as_failure(self):
        self.p.tree.return_value = carousel_page()
        with self.assertRaisesRegex(RuntimeError, "回读未选中"):
            self.scope["hide_carousel"]()
        self.assertEqual(self.p.click.call_count, 1)

    def test_page_change_between_read_and_click_cancels_the_click(self):
        self.p.tree.return_value = carousel_page()
        self.p.focus.side_effect = ["a/RadioPage", "b/OtherPage"]
        with self.assertRaisesRegex(RuntimeError, "读取后轮播页面变化"):
            self.scope["hide_carousel"]()
        self.p.click.assert_not_called()

    def test_radio_readback_rejects_a_changed_service_master(self):
        self.p.tree.return_value = carousel_page()
        self.scope["read_switches"] = Mock(side_effect=[{"推荐服务": True}, {"推荐服务": False}])
        for n in self.p.tree.return_value.iter("node"):     # 不显示已经选中：本轮不点击
            if n.get("bounds") == "[60,2000][140,2080]":
                n.set("checked", "true")
            if n.get("bounds") == "[60,1700][140,1780]":
                n.set("checked", "false")
        with self.assertRaisesRegex(RuntimeError, "总开关发生变化"):
            self.scope["hide_carousel"]()
        self.p.click.assert_not_called()


class NegativeScreenTests(unittest.TestCase):
    def test_carousel_failure_still_closes_independent_hot_news(self):
        p = phone_mock(W=1080, H=2340)
        p.locked.return_value = False
        p.on_screen.return_value = True
        p.tree.return_value = ET.fromstring('''<hierarchy>
          <node resource-id="com.coloros.assistantscreen:id/head_icon"
                clickable="true" bounds="[40,80][160,200]"/>
        </hierarchy>''')
        p.focus.return_value = "com.coloros.assistantscreen/Setting"
        scope = load(p)
        scope["row"] = Mock()
        scope["hide_carousel"] = Mock(side_effect=RuntimeError("单选缺失"))
        scope["close_named"] = Mock()
        scope["open_page"] = Mock()
        with self.assertRaisesRegex(RuntimeError, "热点资讯已核对"):
            action(scope, "负一屏")()
        scope["hide_carousel"].assert_called_once_with()
        scope["close_named"].assert_called_once_with(["热点资讯"], "热点资讯")
        self.assertEqual([c.args[0] for c in scope["row"].call_args_list], ["设置", "推荐服务"])
        self.assertIn("InfoFlowSettingActivity", scope["open_page"].call_args.args[0])    # 直达，不回设置页找（#650）


class GameCenterTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1080, H=2340)
        self.p.locked.return_value = False
        self.p.texts.return_value = []
        self.p.d.shell.return_value = SimpleNamespace(
            exit_code=0, output="package:/data/app/gamecenter/base.apk")
        self.scope = load(self.p)
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()

    def test_missing_app_skips_without_launching(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="")
        with self.assertRaisesRegex(self.scope["SkipStep"], "未安装游戏中心"):
            action(self.scope, "游戏中心")()
        self.p.start.assert_not_called()
        self.p.off.assert_not_called()

    def test_settings_page_opens_directly_and_skips_the_privacy_header(self):
        """设置页认 APP_SETTINGS 直达（#650）；「隐私」是点不动的分组标题，入口是「隐私开关设置」。"""
        self.p.focus.return_value = "com.nearme.gamecenter/com.nearme.gamecenter.me.ui.SettingActivity"
        self.p.find.return_value = True
        action(self.scope, "游戏中心")()
        self.p.start.assert_not_called()
        self.assertIn("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.nearme.gamecenter",
                      [c.args[0] for c in self.p.d.shell.call_args_list])
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list], ["隐私开关设置", "个性化推荐管理"])
        self.assertEqual(self.scope["close_named"].call_args_list, [call(["个性化推荐"], "个性化推荐管理")])

    def test_denied_settings_entry_stops_before_rows(self):
        def shell(command):
            if command.startswith("pm path"):
                return SimpleNamespace(exit_code=0, output="package:/data/app/gamecenter/base.apk")
            return SimpleNamespace(exit_code=1, output="Permission Denial")
        self.p.d.shell.side_effect = shell
        with self.assertRaisesRegex(RuntimeError, "系统未允许"):
            action(self.scope, "游戏中心")()
        self.scope["row"].assert_not_called()
        self.scope["close_named"].assert_not_called()


class AdTrackingFlowTests(unittest.TestCase):
    """广告跟踪段的编排：搜索不通要回菜单，显示系统应用后要关第二轮并把显示方式恢复（#650）。"""

    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.locked.return_value = False
        self.p.texts.return_value = []
        self.p.safe_mode = False
        self.p.back = Mock()
        self.p.await_page = Mock()
        self.p.tap = Mock(return_value=True)
        self.p.d.shell = Mock(side_effect=lambda cmd: SimpleNamespace(
            exit_code=0, output="PMX110" if cmd.startswith("getprop") else ""))
        self.scope = load(self.p)
        self.scope["p"].setting = Mock()
        self.scope["menu_state"] = Mock()
        self.scope["close_all_listed"] = Mock()
        self.scope["page"] = Mock()
        self.scope["system_settings"] = Mock()
        self.scope["row"] = Mock()
        self.scope["more_menu"] = Mock()

    def test_unreachable_search_falls_back_to_the_settings_menu(self):
        self.scope["p"].setting.return_value = False
        self.scope["menu_state"].return_value = self.scope["MenuState"](True, True)
        action(self.scope, "广告跟踪")()
        self.scope["p"].setting.assert_called_once_with(
            "广告跟踪", "限制广告跟踪", path="隐私与安全 > 隐私 > 设备标识与广告")
        self.scope["system_settings"].assert_called_once_with()
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list],
                         ["隐私与安全", "设备标识与广告", "广告跟踪"])

    def test_system_apps_are_revealed_closed_and_hidden_again(self):
        self.scope["p"].setting.return_value = True
        self.scope["menu_state"].side_effect = [self.scope["MenuState"](False, False),
                                                self.scope["MenuState"](False, True)]
        action(self.scope, "广告跟踪")()
        self.assertEqual([c.args[0] for c in self.scope["close_all_listed"].call_args_list],
                         ["用户应用", "含系统应用"])
        self.assertEqual([c.args[0] for c in self.p.tap.call_args_list],
                         ["显示系统应用", "隐藏系统应用"])

    def test_failed_second_round_still_hides_system_apps(self):
        self.scope["p"].setting.return_value = True
        self.scope["menu_state"].side_effect = [self.scope["MenuState"](False, False),
                                                self.scope["MenuState"](False, True)]
        self.scope["close_all_listed"].side_effect = [None, RuntimeError("仍有开着的应用")]
        with self.assertRaisesRegex(RuntimeError, "仍有开着的应用"):
            action(self.scope, "广告跟踪")()
        self.assertIn("隐藏系统应用", [c.args[0] for c in self.p.tap.call_args_list])


class RealDumpMenuTests(unittest.TestCase):
    """用真实 dump 形状跑一遍：`Phone.texts()` 每个节点只产出一条文字，text 优先于 content-desc。"""

    def setUp(self):
        self.p = phone_stub("dump", fast_mod=fast)
        self.p.W, self.p.H = 1080, 2340
        # 读屏 adapter：`tree()` / `texts()` 走它；window_size 在 reader 上是可调用的
        self.p.reader = Mock(window_size=Mock(return_value=(1080, 2340)))
        self.p.tap = Mock(return_value=True)
        self.p.await_page = Mock()
        self.p.back = Mock()
        self.scope, _ = load_recipe(self.p, RECIPE, ("__no_steps__",))

    def dump(self, xml):
        self.p.reader.dump_hierarchy.return_value = xml

    def test_content_desc_only_state_suffix_is_disabled(self):
        self.dump('<hierarchy><node content-desc="全部关闭 - 已停用" enabled="false" '
                  'bounds="[0,0][1080,120]"/></hierarchy>')
        self.scope["close_all_listed"]("用户应用")
        self.assertNotIn("全部关闭", [c.args[0] for c in self.p.tap.call_args_list])

    def test_text_wins_over_content_desc_and_enabled_flag_is_read(self):
        self.dump('<hierarchy><node text="全部关闭" content-desc="全部关闭 - 已停用" enabled="false" '
                  'bounds="[0,0][1080,120]"/></hierarchy>')
        self.scope["close_all_listed"]("用户应用")
        self.assertNotIn("全部关闭", [c.args[0] for c in self.p.tap.call_args_list])


class TrackingGuardTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.locked.return_value = False
        self.p.texts.return_value = []
        self.scope = load(self.p)

    def test_safe_mode_skips_before_navigation(self):
        self.p.safe_mode = True
        with self.assertRaisesRegex(self.scope["SkipStep"], "仅在 PMX110"):
            action(self.scope, "广告跟踪")()
        self.p.d.shell.assert_not_called()
        self.p.off.assert_not_called()

    def test_another_model_skips_before_navigation(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="PMX120")
        with self.assertRaisesRegex(self.scope["SkipStep"], "仅在 PMX110"):
            action(self.scope, "广告跟踪")()
        self.p.d.shell.assert_called_once_with("getprop ro.product.model")
        self.p.click.assert_not_called()
        self.p.off.assert_not_called()


class StepDecoratorTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772)
        self.p.locked.return_value = False
        self.scope = load(self.p)

    def test_lock_halts_remaining_segments(self):
        self.scope["ONLY"] = []
        self.p.locked.return_value = True
        work = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            self.scope["step"]("第一段")(work)
            self.scope["step"]("第二段")(work)
        work.assert_not_called()
        self.p.locked.assert_called_once_with()
        self.assertEqual(self.scope["FAILED_STEPS"], ["第一段", "第二段"])

    def test_device_loss_is_not_converted_to_segment_success(self):
        self.scope["ONLY"] = []
        work = Mock(side_effect=self.scope["adb_link"].DeviceLost("test disconnect"))
        with contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(self.scope["adb_link"].DeviceLost):
            self.scope["step"]("断连")(work)
        work.assert_called_once_with()
        self.assertEqual(self.scope["RESULTS"], [])


if __name__ == "__main__":
    unittest.main()
