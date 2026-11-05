"""PMX110 17.0.0.116：版本边界、导航与回读失败、功能开关保护。"""
import ast
import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
from fixtures import phone_mock
import run

RECIPE = ROOT / "recipes/oppo-PMX110/recipe_17_0_0_116.py"


def load(phone):
    scope = {"p": phone, "ONLY": ["__no_steps__"]}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(RECIPE.read_text(), str(RECIPE), "exec"), scope)
    return scope


def action(scope, name):
    """取真实分段的函数体，以便给其导航协作方注入失败；不复制分段实现。"""
    node = next(n for n in ast.parse(RECIPE.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.decorator_list
                and n.decorator_list[0].args[0].value == name)
    node.decorator_list, node.name = [], "selected_action"
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(RECIPE), "exec"), scope)
    return scope["selected_action"]


class Pmx110116RecipeTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_mock(W=1272, H=2772, changed=[])
        self.p.locked.return_value = False
        self.p.focus.return_value = "test/Settings"
        self.p.texts.return_value = []
        self.scope = load(self.p)

    def close(self, before, after, names=("开屏广告",), **kwargs):
        self.scope["read_switches"] = Mock(side_effect=[before, after])
        return self.scope["close_named"](names, "测试设置", **kwargs)

    def test_exact_build_selects_variant_and_other_build_keeps_original(self):
        for build, expected in (("PMX110_17.0.0.116(CN01)", RECIPE),
                                ("PMX110_17.0.0.117(CN01)", RECIPE.with_name("recipe.py"))):
            with self.subTest(build=build):
                path, ref = run.recipe_for("PMX110", "OPPO", {"build": build, "os": ""})
                self.assertEqual(Path(path), expected)
                self.assertFalse(ref)
        self.assertEqual(len(run.recipe_meta(RECIPE)["steps"]), 8)

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

    def test_read_switches_merges_multiple_screens(self):
        self.scope["page"] = Mock()
        self.scope["switch_top"] = Mock()
        self.p.switches.side_effect = [[("第一项", True, (100, 500))],
                                       [("第二项", False, (100, 500))],
                                       [("第二项", False, (100, 500))]]
        self.p.scroll_more.side_effect = [True, False]
        self.assertEqual(self.scope["read_switches"]("隐私", 2), {"第一项": True, "第二项": False})
        self.scope["page"].assert_called_once_with("隐私")
        self.scope["switch_top"].assert_called_once_with(2)
        self.p.switches.assert_called_with()
        self.assertEqual(self.p.switches.call_count, 3)

    def test_incomplete_list_is_never_modified(self):
        self.scope["page"] = Mock()
        self.scope["switch_top"] = Mock()
        self.p.switches.side_effect = [[("广告", True, (100, y))] for y in (500, 600, 700)]
        self.p.scroll_more.return_value = True
        with self.assertRaisesRegex(RuntimeError, "超过读取上限"):
            self.scope["read_switches"]("隐私", 2)
        self.scope["page"].assert_called_once_with("隐私")
        self.scope["switch_top"].assert_called_once_with(2)
        self.p.off.assert_not_called()

    def test_dynamic_non_switch_text_does_not_prevent_end_detection(self):
        self.scope["page"] = Mock()
        self.scope["switch_top"] = Mock()
        self.p.switches.return_value = [("已关闭的许可", False, (100, 500))]
        self.p.scroll_more.return_value = True  # 全页的访问时间仍在刷新。
        self.assertEqual(self.scope["read_switches"]("广告跟踪", 3), {"已关闭的许可": False})
        self.scope["page"].assert_called_once_with("广告跟踪")
        self.scope["switch_top"].assert_called_once_with(3)
        self.p.scroll_more.assert_called_once_with()

    def test_top_uses_switch_rows_instead_of_changing_page_text(self):
        self.p.switches.return_value = [("许可", False, (100, 500))]
        self.scope["switch_top"](80)
        self.p.top.assert_called_once_with(1)
        self.assertEqual(self.p.switches.call_count, 2)

    def test_same_name_with_mixed_states_is_rejected(self):
        self.scope["page"] = Mock()
        self.scope["switch_top"] = Mock()
        self.p.switches.return_value = [("同名应用", True, (100, 500)),
                                        ("同名应用", False, (100, 600))]
        self.p.scroll_more.return_value = True
        with self.assertRaisesRegex(RuntimeError, "同名开关状态不一致"):
            self.scope["read_switches"]("广告跟踪", 3)
        self.scope["page"].assert_called_once_with("广告跟踪")
        self.scope["switch_top"].assert_called_once_with(3)
        self.p.off.assert_not_called()

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
        self.p.tree.return_value = ET.fromstring('<hierarchy><node text="隐私" clickable="true" bounds="[0,500][1000,600]"/></hierarchy>')
        self.p.on_screen.return_value = True
        self.p.settle.return_value = False
        self.scope["page"] = Mock()
        with self.assertRaisesRegex(RuntimeError, "页面没有变化"):
            self.scope["row"]("隐私")
        self.p.click.assert_called_once_with(500, 550)
        self.scope["page"].assert_not_called()
        self.p.off.assert_not_called()

    def test_visible_description_only_settings_icon_is_not_scrolled_away(self):
        self.p.tree.return_value = ET.fromstring('<hierarchy><node content-desc="设置" clickable="true" bounds="[900,100][1000,200]"/></hierarchy>')
        self.p.on_screen.return_value = True
        self.p.settle.return_value = True
        self.scope["page"] = Mock()
        self.scope["row"]("设置", title="推荐服务")
        self.p.click.assert_called_once_with(950, 150)
        self.p.top.assert_not_called()
        self.scope["page"].assert_called_once_with("推荐服务", None, None)

    def test_search_never_navigates_to_message_master_or_closes_sources(self):
        self.scope["open_page"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        self.scope["read_switches"] = Mock(return_value={name: False for name in self.scope["SEARCH_CARDS"]})
        action(self.scope, "下拉搜索")()
        self.scope["open_page"].assert_called_once()
        self.scope["read_switches"].assert_called_once_with("首页卡片管理")
        names = [name for call in self.scope["close_named"].call_args_list for name in call.args[0]]
        self.assertEqual(names, ["个性化推荐", "精选资讯", "未下载应用推荐", "应用建议小卡", "热搜应用",
                                 "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片", "搜索框提示词", "个性化推荐"])
        self.assertNotIn("消息管理", [call.args[0] for call in self.scope["row"].call_args_list])
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list],
                         ["搜索范围", "首页卡片管理", "功能管理", "隐私"])

    def test_empty_card_page_is_reported_without_claiming_seven_verified_items(self):
        self.scope["open_page"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        self.scope["read_switches"] = Mock(return_value={})
        action(self.scope, "下拉搜索")()
        self.scope["open_page"].assert_called_once()
        self.scope["read_switches"].assert_called_once_with("首页卡片管理")
        self.assertEqual([c.args[1] for c in self.scope["close_named"].call_args_list],
                         ["搜索范围", "功能管理", "隐私"])
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list],
                         ["搜索范围", "首页卡片管理", "功能管理", "隐私"])
        self.assertEqual(len(self.scope["SKIPPED_ITEMS"]), 1)
        self.assertIn("7", self.scope["SKIPPED_ITEMS"][0])

    def test_theme_only_closes_ad_and_personalization(self):
        self.scope["app_settings"] = Mock()
        self.scope["row"] = Mock()
        self.scope["close_named"] = Mock()
        action(self.scope, "主题")()
        self.assertEqual([c.args[0] for c in self.scope["close_named"].call_args_list],
                         [["开屏广告"], ["个性化推荐设置"]])
        self.assertEqual(self.scope["app_settings"].call_args_list,
                         [call("com.heytap.themestore"), call("com.heytap.themestore")])
        self.assertEqual(self.scope["row"].call_args_list,
                         [call("服务管理"), call("消息与广告"), call("隐私")])

    def test_store_whitelist_does_not_include_functional_services(self):
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

    def test_video_missing_app_skips_without_launching(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="")
        with self.assertRaisesRegex(self.scope["SkipStep"], "未安装视频"):
            action(self.scope, "视频")()
        self.p.d.shell.assert_called_once_with("pm path com.heytap.yoli")
        self.p.start.assert_not_called()
        self.p.off.assert_not_called()

    def test_video_missing_bottom_tab_stops_before_settings(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=0, output="package:/system/video.apk")
        self.p.tab.return_value = False
        with self.assertRaisesRegex(RuntimeError, "底部我的"):
            action(self.scope, "视频")()
        self.p.d.shell.assert_called_once_with("pm path com.heytap.yoli")
        self.p.start.assert_called_once_with("com.heytap.yoli", expect=("我的",))
        self.p.tab.assert_called_once_with("我的")
        self.p.tap.assert_not_called()
        self.p.off.assert_not_called()

    def test_safe_mode_skips_tracking_before_navigation(self):
        self.p.safe_mode = True
        with self.assertRaisesRegex(self.scope["SkipStep"], "完整版本"):
            action(self.scope, "广告跟踪")()
        self.p.d.shell.assert_not_called()
        self.p.off.assert_not_called()

    def test_tracking_wrong_build_skips_before_navigation(self):
        self.p.d.shell.side_effect = [SimpleNamespace(output="PMX110"),
                                      SimpleNamespace(output="PMX110_17.0.0.117(CN01)")]
        with self.assertRaisesRegex(self.scope["SkipStep"], "完整版本"):
            action(self.scope, "广告跟踪")()
        self.assertEqual(self.p.d.shell.call_count, 2)
        self.p.click.assert_not_called()
        self.p.off.assert_not_called()

    def test_radio_preview_is_not_clicked_and_master_is_preserved(self):
        root = ET.fromstring('''<hierarchy>
          <node text="不显示轮播推荐" clickable="true" bounds="[0,100][600,200]"/>
          <node text="显示轮播推荐 不显示轮播推荐">
            <node><node text="显示轮播推荐"/><node class="android.widget.RadioButton"
              checkable="true" checked="true" enabled="true" bounds="[100,500][200,600]"/></node>
            <node><node text="不显示轮播推荐"/><node class="android.widget.RadioButton"
              checkable="true" checked="false" enabled="true" bounds="[100,800][200,900]"/></node>
          </node></hierarchy>''')
        self.scope["read_switches"] = Mock(return_value={"推荐服务": True})
        self.p.on_screen.return_value = True
        self.p.tree.return_value = root
        def click(x, y):
            self.assertEqual((x, y), (150, 850))
            for node in root.iter("node"):
                if node.get("checkable") == "true":
                    node.set("checked", "true" if node.get("bounds").startswith("[100,800]") else "false")
        self.p.click.side_effect = click
        self.scope["hide_carousel"]()
        self.p.click.assert_called_once_with(150, 850)
        self.assertEqual(self.scope["read_switches"].call_count, 2)
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_unknown_radio_state_prevents_clicks(self):
        self.scope["read_switches"] = Mock(return_value={"推荐服务": True})
        self.p.tree.return_value = ET.fromstring('<hierarchy><node text="不显示轮播推荐"/></hierarchy>')
        with self.assertRaisesRegex(RuntimeError, "无法确认轮播"):
            self.scope["hide_carousel"]()
        self.scope["read_switches"].assert_called_once_with("推荐服务")
        self.p.click.assert_not_called()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 0)

    def test_radio_readback_rejects_a_changed_service_master(self):
        root = ET.fromstring('''<hierarchy>
          <node><node text="显示轮播推荐"/><node class="android.widget.RadioButton"
            checkable="true" checked="false" enabled="true" bounds="[100,500][200,600]"/></node>
          <node><node text="不显示轮播推荐"/><node class="android.widget.RadioButton"
            checkable="true" checked="true" enabled="true" bounds="[100,800][200,900]"/></node>
          </hierarchy>''')
        self.scope["read_switches"] = Mock(side_effect=[{"推荐服务": True}, {"推荐服务": False}])
        self.p.on_screen.return_value = True
        self.p.tree.return_value = root
        with self.assertRaisesRegex(RuntimeError, "总开关发生变化"):
            self.scope["hide_carousel"]()
        self.assertEqual(self.scope["read_switches"].call_args_list,
                         [call("推荐服务"), call("推荐服务")])
        self.p.click.assert_not_called()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 0)

    def test_carousel_failure_still_processes_independent_hot_news(self):
        self.p.tree.return_value = ET.fromstring('<hierarchy><node resource-id="test:id/head_icon" bounds="[100,100][200,200]"/></hierarchy>')
        self.p.on_screen.return_value = True
        self.scope["row"] = Mock()
        self.scope["hide_carousel"] = Mock(side_effect=RuntimeError("单选缺失"))
        self.scope["close_named"] = Mock()
        with patch.object(self.scope["time"], "sleep"), self.assertRaisesRegex(RuntimeError, "热点资讯已核对"):
            action(self.scope, "负一屏")()
        self.scope["hide_carousel"].assert_called_once_with()
        self.scope["close_named"].assert_called_once_with(["热点资讯"], "热点资讯")
        self.assertEqual([c.args[0] for c in self.scope["row"].call_args_list],
                         ["设置", "推荐服务", "热点资讯"])

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
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(self.scope["adb_link"].DeviceLost):
            self.scope["step"]("断连")(work)
        work.assert_called_once_with()
        self.assertEqual(self.scope["RESULTS"], [])


if __name__ == "__main__":
    unittest.main()
