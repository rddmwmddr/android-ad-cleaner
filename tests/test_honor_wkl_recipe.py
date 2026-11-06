"""WKL-AN20：型号匹配、精确开关范围、确认按钮和账号页截图保护。"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import run
from fixtures import load_recipe, phone_stub


class HonorWKLRecipeTests(unittest.TestCase):
    def load(self, phone):
        scope, _ = load_recipe(phone, ROOT / "recipes/honor-WKL-AN20/recipe.py")
        return scope

    def phone(self, xml="<hierarchy/>"):
        p = phone_stub("test", d=Mock())
        p.W, p.H = 1080, 2400
        p.d.window_size.return_value = (p.W, p.H)
        p.tree = Mock(return_value=ET.fromstring(xml))
        p.locked = Mock(return_value=False)
        return p

    def closing_scope(self, before, after):
        p = Mock(changed=[])
        p.focus.return_value = "com.example/.Settings"
        p.tree.return_value = ET.fromstring("<hierarchy/>")
        scope = self.load(p)
        scope["page"] = Mock()
        scope["labels"] = Mock(return_value={"设置"})
        scope["scan"] = Mock(side_effect=[before, after])
        return p, scope

    def test_model_build_and_steps_are_discoverable_by_runner(self):
        path, reference = run.recipe_for("WKL-AN20", "HONOR")
        self.assertFalse(reference)
        meta = run.recipe_meta(path)
        self.assertEqual(Path(path).parent.name, "honor-WKL-AN20")
        self.assertEqual(meta["build"], "WKL-AN20 11.0.0.111(SP7C00E110R101P7)")
        self.assertEqual(len(meta["steps"]), 13)
        self.assertIn("音乐", meta["steps"])
        self.assertEqual(set(meta["steps"]), set(self.load(Mock())["CHANGES"]))

    def test_wrong_build_does_not_enter_any_action(self):
        p = Mock()
        p.d.shell.side_effect = [Mock(output="WKL-AN20"), Mock(output="another build")]
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        action = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            scope["step"]("系统管家")(action)
        action.assert_not_called()
        p.start.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["RESULTS"], [("系统管家", "跳过")])

    def test_wrong_model_is_skipped_not_failed(self):
        p = Mock()
        p.d.shell.side_effect = [Mock(output="OTHER-MODEL"), Mock(output="WKL-AN20 11.0.0.111")]
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        action = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            scope["step"]("系统管家")(action)
        action.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_full_run_skips_music_step_without_failing(self):
        """音乐段全跑时按约定跳过；记成未完成会让每轮全跑都退出码 1。

        `_` 是模块里最后一个 `@step` 装饰的段函数，也就是「音乐」这一段的函数体。
        """
        p = Mock()
        p.locked.return_value = False
        p.d.shell.side_effect = [Mock(output="WKL-AN20"), Mock(output="WKL-AN20 11.0.0.111(SP7C00E110R101P7)")]
        scope = self.load(p)
        scope["ONLY"] = []
        with contextlib.redirect_stdout(io.StringIO()):
            scope["step"]("音乐")(scope["_"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["RESULTS"], [("音乐", "跳过")])

    def test_skip_step_does_not_enter_failed_steps(self):
        p = Mock()
        p.locked.return_value = False
        p.d.shell.side_effect = [Mock(output="WKL-AN20"), Mock(output="WKL-AN20 11.0.0.111(SP7C00E110R101P7)")]
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        with contextlib.redirect_stdout(io.StringIO()):
            scope["step"]("系统管家")(Mock(side_effect=scope["SkipStep"]("按约定跳过")))
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["RESULTS"], [("系统管家", "跳过")])

    def test_device_loss_is_not_swallowed_as_a_skipped_step(self):
        p = Mock()
        p.d.shell.side_effect = adb_link.DeviceLost("lost")
        scope = self.load(p)
        scope["ONLY"] = ["系统管家"]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(adb_link.DeviceLost):
            scope["step"]("系统管家")(Mock())

    def test_missing_switch_stops_before_any_changes(self):
        p, scope = self.closing_scope({"应用更新": True}, {})
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_named"](["个性化广告"], "测试", "com.example", "设置")
        p.off.assert_not_called()
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_similar_title_and_service_switch_do_not_reach_off(self):
        p, scope = self.closing_scope(
            {"个性化广告": True, "个性化广告服务说明": True, "应用更新": True},
            {"个性化广告": False, "个性化广告服务说明": True, "应用更新": True})
        p.switches.return_value = [("个性化广告", True, (100, 300)),
                                   ("个性化广告服务说明", True, (100, 400)),
                                   ("应用更新", True, (100, 500))]
        filtered = []
        p.off.side_effect = lambda **kw: filtered.extend(p.switches())
        scope["close_named"](["个性化广告"], "测试", "com.example", "设置")
        self.assertEqual([row[0] for row in filtered], ["个性化广告"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_reverted_target_is_not_reported_as_verified(self):
        p, scope = self.closing_scope({"个性化广告": True}, {"个性化广告": True})
        with self.assertRaisesRegex(RuntimeError, "回读未确认"):
            scope["close_named"](["个性化广告"], "测试", "com.example", "设置")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_unrelated_change_is_not_reported_as_verified(self):
        p, scope = self.closing_scope({"个性化广告": True, "评论提醒": True},
                                     {"个性化广告": False, "评论提醒": False})
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named"](["个性化广告"], "测试", "com.example", "设置")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_protection_switch_must_be_on(self):
        p, scope = self.closing_scope({"限制广告跟踪": False}, {"限制广告跟踪": True})
        scope["close_named"](["限制广告跟踪"], "测试", "com.example", "设置")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_account_page_custom_switch_never_takes_screenshot(self):
        p = self.phone('''<hierarchy><node text="我的" bounds="[0,50][100,100]"/>
          <node resource-id="app:id/switch" class="android.widget.ImageView"
           clickable="true" bounds="[900,400][1000,450]"/></hierarchy>''')
        scope = self.load(p)
        with scope["safe_ui"]():
            self.assertEqual(p.switches(), [])
        p.d.screenshot.assert_not_called()

    def test_offscreen_and_disabled_confirmation_buttons_are_ignored(self):
        p = self.phone('''<hierarchy>
          <node text="确定" class="android.widget.Button" bounds="[2000,500][2100,600]"/>
          <node text="确定" class="android.widget.Button" enabled="false" bounds="[500,500][600,600]"/>
          <node text="确定" class="android.widget.Button" bounds="[500,700][600,800]"/>
          </hierarchy>''')
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"), scope["safe_ui"]():
            self.assertEqual(p.confirm(), "确定")
        p.d.click.assert_called_once_with(550, 750)

    def test_text_confirmation_requires_the_specific_music_dialog(self):
        p = self.phone('''<hierarchy><node text="确定" class="android.widget.TextView"
                           bounds="[500,700][600,800]"/></hierarchy>''')
        scope = self.load(p)
        with patch.object(scope["time"], "sleep"), scope["safe_ui"]():
            self.assertIsNone(p.confirm())
        p.d.click.assert_not_called()
        root = p.tree.return_value
        ET.SubElement(root, "node", text="关闭个性化广告推荐", bounds="[100,300][800,400]")
        ET.SubElement(root, "node", text="取消", bounds="[100,700][200,800]")
        with patch.object(scope["time"], "sleep"), scope["safe_ui"]():
            self.assertEqual(p.confirm(), "确定")
        p.d.click.assert_called_once_with(550, 750)

    def test_helpers_are_restored_even_when_action_fails(self):
        p = self.phone()
        scope = self.load(p)
        originals = {name: getattr(p, name) for name in ("click", "scroll", "confirm", "switches")}
        with self.assertRaisesRegex(RuntimeError, "stop"):
            with scope["safe_ui"]():
                raise RuntimeError("stop")
        for name, value in originals.items():
            self.assertEqual(getattr(p, name), value)

    def test_homepage_radio_must_belong_to_the_named_option(self):
        p = self.phone('''<hierarchy><node bounds="[0,0][1080,2400]">
          <node text="简洁首页" bounds="[50,200][500,250]"/>
          <node class="android.widget.RadioButton" checkable="true" checked="true"
           bounds="[900,1600][1000,1700]"/>
          </node></hierarchy>''')
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "唯一单选按钮"):
            scope["radio"](p.tree(), "简洁首页")
        p.d.click.assert_not_called()
        root = ET.fromstring('''<hierarchy><node bounds="[0,200][1080,400]">
          <node text="简洁首页" bounds="[50,250][500,300]"/>
          <node class="android.widget.RadioButton" checkable="true" checked="false"
           bounds="[900,250][1000,300]"/>
          </node></hierarchy>''')
        self.assertEqual(scope["radio"](root, "简洁首页").get("checked"), "false")


if __name__ == "__main__":
    unittest.main()
