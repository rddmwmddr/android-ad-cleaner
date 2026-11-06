"""PMA110：未确认页面/控件时不点击，并保留服务类开关。"""
import contextlib
import io
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe

RECIPE = ROOT / "recipes/oppo-PMA110/recipe.py"


def load(phone, only=None):
    scope, _ = load_recipe(phone, RECIPE, only)
    return scope


def radios(show=True):
    return ET.fromstring(f'''<hierarchy><node text="不显示轮播推荐" clickable="true"/>
      <node><node text="显示轮播推荐"/><node class="android.widget.RadioButton"
        checkable="true" checked="{str(show).lower()}" enabled="true" bounds="[20,30][60,70]"/></node>
      <node><node text="不显示轮播推荐"/><node class="android.widget.RadioButton"
        checkable="true" checked="{str(not show).lower()}" enabled="true" bounds="[200,300][240,340]"/></node>
    </hierarchy>''')


class Pma110RecipeTests(unittest.TestCase):
    def setUp(self):
        self.p = Mock()
        self.p.changed = []
        self.scope = load(self.p)

    def states(self, before, after):
        self.scope["read_switches"] = Mock(side_effect=[before, after])

    def close(self, names, **kwargs):
        return self.scope["close_named"](names, "测试设置", "test/Settings", "测试设置", **kwargs)

    def test_model_uses_its_own_versioned_recipe(self):
        path, reference = run.recipe_for("PMA110", "OPPO")
        self.assertFalse(reference)
        self.assertEqual(Path(path), RECIPE)
        self.assertEqual(run.recipe_meta(path)["build"], "PMA110_17.0.0.106(CN01)")
        self.assertEqual(len(run.recipe_meta(path)["steps"]), 8)

    def test_missing_target_prevents_all_switch_changes(self):
        self.scope["read_switches"] = Mock(return_value={"应用安全": True})
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            self.close(["个性化推荐"])
        self.p.off.assert_not_called()

    def test_already_closed_target_does_not_touch_service_switch(self):
        self.scope["read_switches"] = Mock(return_value={"个性化推荐": False, "天气预警": True})
        self.close(["个性化推荐"])
        self.p.off.assert_not_called()
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_similar_unknown_title_is_excluded_from_substring_match(self):
        self.states({"个性化推荐": True, "个性化推荐帮助": True},
                    {"个性化推荐": False, "个性化推荐帮助": True})
        self.close(["个性化推荐"])
        self.assertIn("个性化推荐帮助", self.p.off.call_args.kwargs["keep"])

    def test_reverted_target_is_not_counted_as_verified(self):
        self.states({"开屏广告": True}, {"开屏广告": True})
        with self.assertRaisesRegex(RuntimeError, "回读未确认"):
            self.close(["开屏广告"])
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 0)

    def test_unrelated_service_change_fails_verification(self):
        self.states({"开屏广告": True, "允许更新": True}, {"开屏广告": False, "允许更新": False})
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            self.close(["开屏广告"])

    def test_only_declared_aggregate_can_change_with_children(self):
        self.states({"全部": True, "精选资讯": True, "本机应用": True},
                    {"全部": False, "精选资讯": False, "本机应用": True})
        self.close(["精选资讯"], dependent=["全部"])
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_theme_confirmation_is_reopened_before_readback(self):
        self.states({"个性化推荐设置": True}, {"个性化推荐设置": False})
        reopen = Mock()
        self.close(["个性化推荐设置"], reopen=reopen)
        reopen.assert_called_once_with()

    def test_denied_activity_never_falls_through_to_clicks(self):
        self.p.d.shell.return_value = SimpleNamespace(exit_code=1, output="SecurityException: not exported")
        self.scope["wait_page"] = Mock()
        with self.assertRaisesRegex(RuntimeError, "系统未允许"):
            self.scope["open_page"]("am start", "test/Settings", "设置")
        self.scope["wait_page"].assert_not_called()
        self.p.tap.assert_not_called()

    def test_reference_mode_skips_bulk_tracking(self):
        self.p.locked.return_value = False
        self.p.d.shell.side_effect = [SimpleNamespace(output="PMA110"),
                                      SimpleNamespace(output="PMA110_17.0.0.106(CN01)")]
        with patch.dict(os.environ, {"AAC_REF": "1"}):
            scope = load(self.p, ["广告跟踪"])
        self.assertEqual(scope["RESULTS"], [("广告跟踪", "skipped")])
        self.p.off.assert_not_called()

    def test_lock_stops_subsequent_steps_before_navigation(self):
        self.scope["ONLY"] = []
        self.p.locked.return_value = True
        action = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            self.scope["step"]("第一段")(action)
            self.scope["step"]("第二段")(action)
        action.assert_not_called()
        self.assertEqual(self.p.locked.call_count, 1)
        self.assertEqual(self.scope["FAILED_STEPS"], ["第一段", "第二段"])

    def test_preview_text_is_not_a_carousel_radio(self):
        self.p.on_screen.return_value = True
        choices = self.scope["carousel_choices"](radios())
        self.assertFalse(choices["不显示轮播推荐"][0])
        self.assertEqual(choices["不显示轮播推荐"][1], (200, 300, 240, 340))

    def test_unknown_radio_state_is_not_guessed(self):
        self.p.on_screen.return_value = True
        with self.assertRaisesRegex(RuntimeError, "无法确认"):
            self.scope["carousel_choices"](ET.fromstring('<hierarchy><node text="不显示轮播推荐"/></hierarchy>'))
        self.p.click.assert_not_called()

    def test_carousel_uses_current_node_bounds_and_keeps_master(self):
        root = radios()
        self.p.on_screen.return_value = True
        self.p.tree.return_value = root
        self.p.focus.return_value = self.scope["ASSISTANT"] + "setting.recommendservice.RecommendServiceSettingActivity"
        self.scope["wait_page"] = Mock()
        self.scope["read_switches"] = Mock(return_value={"推荐服务": True})
        def click(*_):
            for n in root.iter("node"):
                if n.get("checkable") == "true":
                    n.set("checked", "false" if n.get("bounds").startswith("[20,") else "true")
        self.p.click.side_effect = click
        with patch.object(self.scope["time"], "sleep"):
            self.scope["hide_carousel"]()
        self.p.click.assert_called_once_with(220, 320)
        self.assertEqual(self.scope["VERIFIED_SWITCHES"], 1)

    def test_carousel_page_change_prevents_click(self):
        self.p.on_screen.return_value = True
        self.p.tree.return_value = radios()
        self.p.focus.return_value = "unrelated/Activity"
        self.scope["wait_page"] = Mock()
        self.scope["read_switches"] = Mock(return_value={"推荐服务": True})
        with self.assertRaisesRegex(RuntimeError, "页面变化"):
            self.scope["hide_carousel"]()
        self.p.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
