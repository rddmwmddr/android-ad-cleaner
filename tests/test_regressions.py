"""设备无关的回归测试：输入、页面识别、开关保护和打包入口。

运行：gui/.venv/bin/python -m unittest discover -s tests -v
"""
import contextlib
import io
import itertools
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import fast
import run


def phone():
    p = fast.Phone.__new__(fast.Phone)
    p.W, p.H = 1168, 1712
    p.log, p.miss, p.changed = False, 0, []
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
        p.d.shell.return_value = types.SimpleNamespace(exit_code=0, output="No activities found to run, monkey aborted.")
        p.texts = Mock()
        with self.assertRaisesRegex(RuntimeError, "无法打开"):
            p.start("com.example.no_launcher")
        p.texts.assert_not_called()

    def test_version_mismatch_reaches_safe_mode(self):
        p = phone()
        p.locked = Mock(return_value=False)
        p.d.shell.return_value = types.SimpleNamespace(output="different-version")
        with tempfile.TemporaryDirectory() as d:
            recipe = Path(d) / "recipe.py"
            recipe.write_text('BUILD = "old-version"\nassert __import__("os").environ["AAC_REF"] == "1"\n')
            with patch.object(fast, "Phone", return_value=p), patch.object(sys, "argv", ["fast.py", "-s", "test", "run", str(recipe)]), \
                 patch.dict(os.environ, {"AAC_BACKUPS": d}), contextlib.redirect_stdout(io.StringIO()):
                fast.main()

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


if __name__ == "__main__":
    unittest.main()
