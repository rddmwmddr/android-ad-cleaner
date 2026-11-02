"""设备无关的回归测试：输入、页面识别、开关保护和打包入口。

运行：gui/.venv/bin/python -m unittest discover -s tests -v
"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import contextlib
import io
import itertools
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import adb_link
import fast
import run
from fixtures import fake_adb, phone_stub


def phone():
    p = phone_stub("S")
    p.W, p.H = 1168, 1712
    p.d = Mock()
    return p


class SwitchTests(unittest.TestCase):
    def test_titles_deduplicate_rows_and_preserve_auto_update(self):
        root = ET.fromstring('''<hierarchy><node bounds="[0,300][1168,900]">
          <node bounds="[0,320][1168,430]">
            <node text="每次联网时通知" bounds="[60,350][600,400]"/>
            <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,350][1080,400]"/>
          </node>
          <node class="android.widget.LinearLayout" checkable="true" clickable="true" checked="true" bounds="[0,540][1168,650]"/>
          <node text="自动更新" bounds="[60,570][600,620]"/>
          <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,570][1080,620]"/>
          <node bounds="[0,680][1168,880]">
            <node text="个性化广告推荐" bounds="[60,700][700,750]"/>
            <node text="个性化广告服务会根据您的喜好进行精准匹配" bounds="[60,755][900,860]"/>
            <node class="android.widget.Switch" checkable="true" checked="false" content-desc="个性化广告推荐 个性化广告服务会根据您的喜好进行精准匹配" bounds="[990,760][1080,810]"/>
          </node>
          <node class="android.widget.Switch" checkable="true" checked="true" bounds="[2160,500][2240,546]"/>
        </node></hierarchy>''')
        self.assertEqual([(t, c) for t, c, _ in phone().switches(root)],
                         [("每次联网时通知", True), ("自动更新", True), ("个性化广告推荐", False)])

    def test_offscreen_custom_switch_and_radio_are_not_touched(self):
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.RadioButton" text="卡片形态" checkable="true" clickable="true" checked="true" bounds="[50,400][400,500]"/>
          <node class="android.widget.ImageView" resource-id="app:id/switch" clickable="true" bounds="[2200,500][2300,600]"/>
        </hierarchy>''')
        self.assertEqual(p.switches(root), [])
        p.d.screenshot.assert_not_called()

    def test_accessibility_label_on_switch_is_preserved(self):
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.Switch" checkable="true" checked="true" content-desc="内容推广&#10;推荐相关内容" bounds="[900,400][1050,500]"/>
          <node class="android.view.View" content-desc="天气预警提醒&#10;气象灾害预警推送" bounds="[50,600][1100,800]">
            <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,650][1050,750]"/>
          </node>
        </hierarchy>''')
        self.assertEqual([t for t, _, _ in phone().switches(root)], ["内容推广", "天气预警提醒"])

    def test_search_text_switcher_is_not_a_toggle(self):
        p = phone()
        root = ET.fromstring('<hierarchy><node class="android.widget.TextSwitcher" resource-id="app:id/search_text_switcher" content-desc="搜索框" clickable="true" bounds="[50,100][900,200]"/></hierarchy>')
        self.assertEqual(p.switches(root), [])
        p.d.screenshot.assert_not_called()

    def test_protection_polarity(self):
        for text in ("限制广告跟踪", "防止广告追踪", "关闭个性化推荐"):
            self.assertIs(fast.want_state(text), True)
        self.assertIs(fast.want_state("个性化广告推荐"), False)
        self.assertIsNone(fast.want_state("关闭推送"))

    @patch.object(fast.time, "sleep")
    def test_disappeared_switch_is_not_reported_as_success_or_retapped(self, _sleep):
        p = phone()
        switches = [[("广告推荐", True, (1000, 500))]] * 2 + [[]] * 8
        p.switches = Mock(side_effect=switches)
        p.tree = Mock(return_value=ET.fromstring('<hierarchy/>'))
        p.focus = Mock(return_value="app/settings")
        p.click, p.confirm = Mock(), Mock(return_value=None)
        p.scroll_more = Mock(return_value=False)
        self.assertEqual(p.off(only=["广告推荐"]), 0)
        self.assertEqual(p.changed, [])
        p.click.assert_called_once_with(1000, 500)
        p.confirm.assert_called()
        p.focus.assert_called()
        p.tree.assert_called_once_with()
        p.scroll_more.assert_called_once_with()


class InputTests(unittest.TestCase):
    def test_no_input_without_visible_focused_edit(self):
        p = phone()
        p.edit_ready = Mock(return_value=False)
        self.assertFalse(p.type_text("广告"))
        p.d.assert_not_called()
        p.d.shell.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_input_rpc_has_timeout_and_verifies_text(self, _sleep):
        p = phone()
        p.edit_ready = Mock(return_value=True)
        p.focused_text = Mock(return_value="广告")
        self.assertTrue(p.type_text("广告", timeout=0.5))
        p.d.jsonrpc.setText.assert_called_once_with(p.d.return_value.selector, "广告", http_timeout=0.5)
        p.d.jsonrpc.setClipboard.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_failed_rpc_uses_bounded_clipboard_then_verifies(self, _sleep):
        p = phone()
        p.edit_ready = Mock(return_value=True)
        p.d.jsonrpc.setText.side_effect = TimeoutError()
        p.focused_text = Mock(return_value="广告")
        self.assertTrue(p.type_text("广告", timeout=0.5))
        p.d.jsonrpc.setClipboard.assert_called_once_with(None, "广告", http_timeout=0.5)
        p.d.shell.assert_called_once_with("input keyevent KEYCODE_PASTE", timeout=0.5)

    @patch.object(fast.time, "sleep")
    def test_unverified_input_returns_false(self, _sleep):
        p = phone()
        p.edit_ready = Mock(return_value=True)
        p.focused_text = Mock(return_value="%%%%")
        self.assertFalse(p.type_text("广告", timeout=0.5))
        self.assertEqual(p.d.shell.call_args.args, ("input keyevent BACK",))

    def search_phone(self, with_result):
        p = phone()
        home = ET.fromstring('<node text="搜索设置项" bounds="[50,100][1100,200]"/>')
        edit = ET.fromstring('<node text="广告" class="android.widget.EditText" bounds="[50,100][1000,200]"/>')
        result = ET.fromstring('<node text="广告" class="android.widget.TextView" bounds="[50,400][1000,500]"/>')
        typed, selected = [], []
        def click(x, y):
            if y > 300:
                selected.append((x, y))
        p.click = Mock(side_effect=click)
        p.type_text = Mock(side_effect=lambda text: typed.append(text) or True)
        p.edit_ready = Mock(return_value=True)
        p.focus = lambda: "settings/result" if selected else "settings/search"
        def texts():
            nodes = ([edit, result] if with_result else [edit]) if typed else [home]
            return [(n.get("text"), fast.bounds(n), n) for n in nodes]
        p.texts = texts
        return p

    def test_search_does_not_treat_input_as_result(self):
        p = self.search_phone(False)
        with patch.object(fast.time, "time", side_effect=itertools.count(0, 0.2)), patch.object(fast.time, "sleep"):
            self.assertFalse(p.setting("广告"))
        self.assertEqual(p.click.call_count, 1)  # 只打开搜索框，没有再点输入文字

    def test_search_selects_result_below_input(self):
        p = self.search_phone(True)
        with patch.object(fast.time, "time", side_effect=itertools.count(0, 0.2)), patch.object(fast.time, "sleep"):
            self.assertTrue(p.setting("广告"))
        self.assertEqual(p.click.call_args.args, (525, 450))


class LaunchTests(unittest.TestCase):
    def setUp(self):
        fake_adb(self)

    def test_settings_panel_cancel_is_not_dismissed_as_popup(self):
        p = phone()
        p.tree = Mock(return_value=ET.fromstring('''<hierarchy>
          <node text="取消" class="android.widget.Button" clickable="true" bounds="[900,100][1100,200]"/>
          <node class="android.widget.Switch" checkable="true" bounds="[900,400][1100,500]"/>
        </hierarchy>'''))
        p.click = Mock()
        self.assertIsNone(p.dismiss())
        p.click.assert_not_called()

    def test_single_screen_panel_is_not_swiped_away(self):
        p = phone()
        p.tree = Mock(return_value=ET.fromstring('<hierarchy><node bounds="[0,0][1168,1712]" scrollable="false"/></hierarchy>'))
        p.scroll = Mock()
        self.assertFalse(p.scroll_more())
        p.top()
        p.scroll.assert_not_called()

    def test_scrolling_cannot_continue_in_another_app(self):
        p = phone()
        p.tree = Mock(return_value=ET.fromstring('<hierarchy><node bounds="[0,0][1168,1712]" scrollable="true"/></hierarchy>'))
        p.focus = Mock(side_effect=["settings/page", "another/app"])
        p.texts, p.scroll = Mock(return_value=[]), Mock()
        with self.assertRaisesRegex(RuntimeError, "离开了"):
            p.scroll_more()

    def test_transition_empty_tree_is_not_ready(self):
        p = phone()
        p.sig = Mock(return_value="")
        with patch.object(fast.time, "time", side_effect=itertools.count(0, 0.1)), patch.object(fast.time, "sleep"):
            self.assertFalse(p.settle("old page", maxwait=1))

    def test_transition_waits_for_stable_nonempty_page(self):
        p = phone()
        p.sig = Mock(side_effect=["", "new page", "new page", "new page", "new page"])
        with patch.object(fast.time, "time", side_effect=itertools.count(0, 0.1)), patch.object(fast.time, "sleep"):
            self.assertTrue(p.settle("old page", maxwait=2))
        self.assertGreaterEqual(p.sig.call_count, 3)

    def test_missing_launcher_stops_before_reading_other_app(self):
        p = phone()
        p.d.shell.side_effect = [types.SimpleNamespace(exit_code=0, output="No activities found to run, monkey aborted."),
                                 types.SimpleNamespace(exit_code=0, output="package:/data/app/base.apk")]
        p.texts = Mock()
        with self.assertRaisesRegex(RuntimeError, "无法打开"):
            p.start("com.example.no_launcher")
        p.texts.assert_not_called()

    def test_reference_recipe_app_not_installed_is_named(self):
        # #87 / #165：参考脚本里的 App 本机没装，说「没有安装」，不报成打开失败。
        p = phone()
        p.d.shell.side_effect = [types.SimpleNamespace(exit_code=0, output="No activities found to run, monkey aborted."),
                                 types.SimpleNamespace(exit_code=0, output="")]
        p.d.app_stop = Mock()
        with patch.object(adb_link, "detached", return_value=False):    # 手机还在，只是没装这个 App
            with self.assertRaisesRegex(RuntimeError, "没有安装 com.honor.browser"):
                p.start("com.honor.browser")

    def test_runtime_permission_only_clicks_explicit_deny_button(self):
        p = phone(); p.focus = Mock(return_value="com.android.permissioncontroller/.permission.ui.GrantPermissionsActivity")
        p.tree = Mock(return_value=ET.fromstring('''<hierarchy>
          <node package="com.android.permissioncontroller" class="android.widget.Button" text="允许" bounds="[10,100][200,200]"/>
          <node package="com.android.permissioncontroller" class="android.widget.Button" text="拒绝" bounds="[10,300][200,400]"/>
        </hierarchy>'''))
        p.click = Mock()
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "拒绝权限")
        p.click.assert_called_once_with(105, 350)

    def test_permission_page_without_deny_does_not_grant_permission(self):
        p = phone(); p.focus = Mock(return_value="com.android.permissioncontroller/.permission.ui.GrantPermissionsActivity")
        p.tree = Mock(return_value=ET.fromstring('''<hierarchy><node package="com.android.permissioncontroller"
          class="android.widget.Button" text="允许" bounds="[10,100][200,200]"/></hierarchy>'''))
        p.click = Mock()
        self.assertIsNone(p.dismiss())
        p.click.assert_not_called()

    def test_launch_handles_permission_gate_before_checking_target_foreground(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Starting")
        p.focus = Mock(side_effect=["com.android.permissioncontroller/.GrantPermissionsActivity"] * 2 + ["com.example/.Main"] * 3)
        p.texts = Mock(return_value=[("首页", (), None)]); p.dismiss = Mock(return_value="拒绝权限")
        with patch.object(fast.time, "sleep"):
            p.start("com.example", settle=0)
        p.dismiss.assert_called_once()

    def test_sparse_homepage_is_not_dismissed_as_an_ad(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Events injected: 1")
        p.focus = Mock(return_value="com.example/.Main")
        p.texts = Mock(return_value=[("首页", (), None), ("我的", (), None)])
        with patch.object(fast.time, "sleep"):
            p.start("com.example", settle=0)
        self.assertNotIn("input keyevent BACK", [c.args[0] for c in p.d.shell.call_args_list])

    def test_late_permission_gate_is_denied_before_accepting_launch(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Starting")
        p.focus = Mock(side_effect=["com.example/.Main", "com.android.permissioncontroller/.GrantPermissionsActivity"] + ["com.example/.Main"] * 2)
        p.texts = Mock(return_value=[("首页", (), None)])
        p.dismiss = Mock(return_value="拒绝权限")
        with patch.object(fast.time, "sleep"):
            p.start("com.example", settle=0)
        p.dismiss.assert_called_once()

    def test_late_permission_without_deny_button_stops(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Starting")
        p.focus = Mock(side_effect=["com.example/.Main", "com.android.permissioncontroller/.GrantPermissionsActivity"])
        p.texts = Mock(return_value=[("首页", (), None)])
        p.dismiss = Mock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "离开前台"):
            p.start("com.example", settle=0)
        p.dismiss.assert_called_once()

    def test_start_leaving_target_app_stops_before_dismiss_or_click(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Events injected: 1")
        p.focus = Mock(side_effect=["com.example/.Main", "com.other/.Account"])
        p.texts = Mock(return_value=[])
        p.dismiss = Mock()
        with patch.object(fast.time, "time", side_effect=itertools.count()), patch.object(fast.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "离开前台"):
                p.start("com.example")
        p.dismiss.assert_not_called()

    def test_dismiss_leaving_target_app_is_not_accepted_as_success(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Events injected: 1")
        p.focus = Mock(side_effect=["com.example/.Main"] * 3 + ["com.other/.Main"])
        p.texts = Mock(return_value=[("首页", (), None)])
        p.dismiss = Mock()
        with patch.object(fast.time, "time", side_effect=itertools.count(0, .1)), patch.object(fast.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "离开前台"):
                p.start("com.example", settle=.2)

    def test_slow_blank_start_waits_for_page_without_pressing_back(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Starting")
        p.focus = Mock(return_value="com.example/.Main")
        p.texts = Mock(side_effect=[[], [], [("首页", (), None)]])
        p.dismiss = Mock(return_value=None)
        with patch.object(fast.time, "time", side_effect=itertools.count(0, .5)), patch.object(fast.time, "sleep"):
            p.start("com.example", settle=0)
        self.assertNotIn("input keyevent BACK", [c.args[0] for c in p.d.shell.call_args_list])

    def test_unreadable_start_is_bounded_and_does_not_press_back(self):
        p = phone()
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="Starting")
        p.focus = Mock(return_value="com.example/.Main")
        p.texts = Mock(return_value=[]); p.dismiss = Mock(return_value=None)
        with patch.object(fast.time, "time", side_effect=itertools.count()), patch.object(fast.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "仍读不到页面"):
                p.start("com.example")
        self.assertNotIn("input keyevent BACK", [c.args[0] for c in p.d.shell.call_args_list])

    def test_recipe_declared_failures_return_failure_after_preserving_change_log(self):
        p = phone(); p.locked = Mock(return_value=False)
        p.d.shell.return_value = types.SimpleNamespace(output="test-build")
        p.changed = [("已成功的页面", "个性化推荐")]
        with tempfile.TemporaryDirectory() as directory:
            recipe = Path(directory) / "recipe.py"
            recipe.write_text('FAILED_STEPS = ["服务管理"]\n', encoding="utf-8")
            with patch.dict(os.environ, {"AAC_BACKUPS": directory}), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    fast.execute(p, "run", [str(recipe)])
            self.assertEqual(result.exception.code, 1)
            self.assertIn("已成功的页面", Path(directory, "run-log.txt").read_text(encoding="utf-8"))

    def test_version_mismatch_reaches_safe_mode(self):
        p = phone()
        p.locked = Mock(return_value=False)
        p.d.shell.return_value = types.SimpleNamespace(output="different-version")
        with tempfile.TemporaryDirectory() as d:
            recipe = Path(d) / "recipe.py"
            recipe.write_text('BUILD = "old-version"\nassert p.safe_mode is True\n')
            with patch.object(fast, "Phone", return_value=p), patch.object(sys, "argv", ["fast.py", "-s", "test", "run", str(recipe)]), \
                 patch.dict(os.environ, {"AAC_BACKUPS": d}), contextlib.redirect_stdout(io.StringIO()):
                fast.main()

    def test_reference_script_flag_reaches_safe_mode(self):
        # run.py 用 --ref 传下来，不再靠 AAC_REF 环境变量
        p = phone()
        p.locked = Mock(return_value=False)
        p.d.shell.return_value = types.SimpleNamespace(output="OS4.0")
        with tempfile.TemporaryDirectory() as d:
            recipe = Path(d) / "recipe.py"
            recipe.write_text('assert p.safe_mode is True\n')
            with patch.object(fast, "Phone", return_value=p), \
                 patch.object(sys, "argv", ["fast.py", "-s", "test", "run", str(recipe), "--ref"]), \
                 patch.dict(os.environ, {"AAC_BACKUPS": d}), contextlib.redirect_stdout(io.StringIO()):
                fast.main()
        self.assertNotIn("AAC_REF", os.environ)

    def test_vivo_model_alias_and_version(self):
        for model in ("V2547DA", "V2547A"):
            path, reference = run.recipe_for(model, "vivo")
            self.assertTrue(path)
            self.assertFalse(reference)
        self.assertFalse(run.build_ok({"build": "PD2547B_A_17.1.10.2", "os": "OriginOS 7"}, "PD2547D_A_16"))

    def test_packaged_child_uses_cli_dispatch(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "/tmp/app"):
            self.assertEqual(run.script_cmd("fast.py", "-s", "test", "ls"),
                             ["/tmp/app", "--cli", "fast.py", "-s", "test", "ls"])

    def test_recipe_passes_safe_mode_as_a_flag(self):
        with patch.object(sys, "argv", ["run.py", "-s", "test", "recipe", "--ref"]), \
             patch.object(run, "info", return_value={"brand": "Xiaomi", "model": "M154FF", "build": "OS4.0"}), \
             patch.object(run, "recipe_for", return_value=("recipe.py", "ref.py")), \
             patch.object(run, "recipe_meta", return_value={"build": "OS4.0"}), \
             patch.object(run, "locked", return_value=False), \
             patch.object(run, "sh", return_value="15"), \
             patch.object(run, "py", return_value=0) as py:
            self.assertEqual(run.main(), 0)
        self.assertEqual(py.call_args.args, ("fast.py", "-s", "test", "run", "recipe.py", "--ref"))

    def test_recipe_restores_stay_awake_on_failure(self):
        with patch.object(sys, "argv", ["run.py", "-s", "test", "recipe"]), \
             patch.object(run, "info", return_value={"brand": "Xiaomi", "model": "M154FF", "build": "OS4.0"}), \
             patch.object(run, "recipe_for", return_value=("recipe.py", False)), \
             patch.object(run, "recipe_meta", return_value={"build": "OS4.0"}), \
             patch.object(run, "locked", return_value=False), \
             patch.object(run, "sh", return_value="15") as sh, \
             patch.object(run, "py", side_effect=RuntimeError("child failed")):
            with self.assertRaisesRegex(RuntimeError, "child failed"):
                run.main()
        self.assertEqual(sh.call_args.args, ("test", "settings put global stay_on_while_plugged_in 15"))


class TapIconTests(unittest.TestCase):
    """没有文字的图标入口：游戏中心 14.43.3 把「设置」做成「我的」页右上角的齿轮（#292）。"""

    PAGE = '''<hierarchy>
      <node clickable="true" bounds="[980,120][1080,240]"/>
      <node clickable="true" bounds="[860,120][960,240]"/>
      <node clickable="true" text="消息" bounds="[740,120][840,240]"/>
      <node clickable="true" content-desc="客服" bounds="[620,120][720,240]"/>
      <node clickable="false" bounds="[500,120][600,240]"/>
      <node clickable="true" bounds="[0,400][1168,1200]"/>
    </hierarchy>'''

    def page_phone(self):
        p = phone()
        p.tree = Mock(return_value=ET.fromstring(self.PAGE))
        p.focus = Mock(return_value="com.nearme.gamecenter/.Home")
        p.sig = Mock(return_value="我的游戏")
        p.click = Mock()
        p.back = Mock()
        return p

    def clock(self):
        """点图标后的等待走假时钟：每个候选等 2.4 秒，测试不用真等。"""
        class Clock:
            t = 0.0

            @staticmethod
            def monotonic():
                return Clock.t

            @staticmethod
            def sleep(s):
                Clock.t += s
        return Clock

    def test_candidates_are_unlabeled_icons_from_right_to_left(self):
        self.assertEqual(self.page_phone().icon_candidates(), [(1030, 180), (910, 180)])

    def test_tap_icon_accepts_the_first_icon_when_the_target_text_appears(self):
        p = self.page_phone()
        p.find = Mock(return_value=(5, 5))
        self.assertTrue(p.tap_icon("隐私开关设置"))
        self.assertEqual([c.args for c in p.click.call_args_list], [(1030, 180)])
        # 必须精确匹配：页面上本来就有「隐私政策」这类文字时，包含匹配会把第一次点击当成成功、不再回退
        self.assertTrue(p.find.call_args.kwargs.get("exact"))

    def test_tap_icon_goes_back_and_tries_the_next_icon_when_the_page_changes(self):
        p = self.page_phone()
        Clock = self.clock()
        p.focus = Mock(side_effect=["home", "message", "message"])
        p.find = Mock(side_effect=lambda *a, **k: (5, 5) if Clock.t > 2.5 else None)
        with patch.object(fast.time, "monotonic", Clock.monotonic), patch.object(fast.time, "sleep", Clock.sleep):
            self.assertTrue(p.tap_icon("隐私开关设置"))
        self.assertEqual([c.args for c in p.click.call_args_list], [(1030, 180), (910, 180)])
        p.back.assert_called_once()

    def test_tap_icon_gives_up_when_no_icon_opens_the_target(self):
        p = self.page_phone()
        Clock = self.clock()
        p.find = Mock(return_value=None)
        with patch.object(fast.time, "monotonic", Clock.monotonic), patch.object(fast.time, "sleep", Clock.sleep):
            self.assertFalse(p.tap_icon("隐私开关设置"))
        self.assertEqual([c.args for c in p.click.call_args_list], [(1030, 180), (910, 180)])
        p.back.assert_not_called()          # 页面没变就不 back，避免把用户留在别的页面

    def test_tap_icon_prints_page_text_when_no_icon_works(self):
        p = self.page_phone()
        Clock = self.clock()
        p.log, p.find = True, Mock(return_value=None)
        p.texts = Mock(return_value=[("我的游戏", (0, 0, 1, 1), None)])
        out = io.StringIO()
        with patch.object(fast.time, "monotonic", Clock.monotonic), patch.object(fast.time, "sleep", Clock.sleep), \
             contextlib.redirect_stdout(out):
            self.assertFalse(p.tap_icon("隐私开关设置"))
        self.assertIn("我的游戏", out.getvalue())


if __name__ == "__main__":
    unittest.main()
