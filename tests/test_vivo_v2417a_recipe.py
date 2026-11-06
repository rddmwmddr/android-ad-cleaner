"""V2417A：标题变化/确认关闭、服务开关保护和失败结果的离线回归。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import adb_link
import fast
import run
from fixtures import load_recipe, phone_mock


class VivoV2417ARecipeTests(unittest.TestCase):
    def load(self, phone, only=None):
        scope, _ = load_recipe(phone, ROOT / "recipes/vivo-V2417A/recipe.py", only)
        return scope

    def test_model_is_matched_without_reference_and_records_exact_build(self):
        path, reference = run.recipe_for("V2417A", "vivo")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "vivo-V2417A")
        meta = run.recipe_meta(path)
        self.assertEqual(meta["build"], "PD2417D_A_16.2.14.1.W10")
        self.assertEqual(meta["models"], ["V2417A"])
        self.assertEqual(len(meta["steps"]), 8)

    def test_missing_target_cannot_close_similarly_named_service(self):
        p = phone_mock()
        p.switches.return_value = [("天气服务异常提醒.有异常时提醒", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_named"](["天气服务"], "天气")
        p.off.assert_not_called()

    def test_unrelated_service_change_is_not_verified(self):
        p = phone_mock()
        p.switches.side_effect = [
            [("天气服务.接收热点资讯", True, (1, 2)), ("气象预警", True, (1, 3))],
            [("天气服务.接收热点资讯", False, (1, 2)), ("气象预警", False, (1, 3))],
        ]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named"](["天气服务"], "天气")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)
        self.assertEqual(p.off.call_args.kwargs["keep"], ["气象预警"])

    def test_reverted_switch_is_not_verified(self):
        p = phone_mock()
        p.switches.return_value = [("服务推荐.说明", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认"):
            scope["close_named"](["服务推荐"], "负一屏")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_real_engine_keeps_non_target_with_matching_prefix(self):
        p = phone_mock()
        p.H, p.miss, p.changed = 3000, 0, []
        p.tree.return_value = ET.Element("hierarchy")
        p.focus.return_value = "com.example/.Settings"
        p.confirm.return_value = None
        p.scroll_more.return_value = False
        names = ["个性化广告", "个性化广告推荐"]
        states = {name: True for name in names}
        p.switches.side_effect = lambda *args: [
            (name, states[name], (index + 1, 600)) for index, name in enumerate(names)
        ]

        def toggle(x, y):
            name = names[x - 1]
            states[name] = not states[name]

        p.click.side_effect = toggle
        p.off.side_effect = lambda **kwargs: fast.Phone.off(p, **kwargs)
        scope = self.load(p)
        scope["close_named"](["个性化广告"], "系统广告")
        self.assertEqual(states, {"个性化广告": False, "个性化广告推荐": True})
        p.click.assert_called_once_with(1, 600)
        p.off.assert_called_once()
        p.switches.assert_called()
        p.focus.assert_called()
        p.confirm.assert_called()
        p.scroll_more.assert_called_once_with()

    def test_store_handles_confirmation_and_state_in_title_without_reopening(self):
        p = phone_mock()
        states = {"个性化推荐": True, "个性化广告推荐": True}
        pending = []
        names = list(states)
        # #565 后引擎剥掉状态尾缀，脚本收到的标题不再随状态变化。
        p.switches.side_effect = lambda: [
            (name, states[name], (index + 1, 2))
            for index, name in enumerate(names)
        ]
        p.click.side_effect = lambda x, y: pending.append(names[x - 1])
        p.find.side_effect = lambda name, **kw: (1, 2) if name == "确认关闭" and pending else None

        def confirm(name, **kwargs):
            self.assertEqual(name, "确认关闭")
            states[pending.pop()] = False
            return True

        p.tap.side_effect = confirm
        scope = self.load(p)
        scope["store_personalization"]()
        scope["store_personalization"]()  # 第二次必须保持关闭，不再点击。
        self.assertEqual(p.click.call_count, 2)
        self.assertEqual(p.tap.call_count, 2)
        self.assertEqual(p.changed.append.call_count, 2)
        self.assertFalse(any(states.values()))

    def test_step_failure_is_visible_and_disconnect_is_not_swallowed(self):
        p = phone_mock()
        p.locked.return_value = False
        scope = self.load(p)
        scope["ONLY"].clear()
        action = Mock(side_effect=RuntimeError("入口不符"))
        scope["step"]("应用商店")(action)
        self.assertEqual(scope["FAILED_STEPS"], ["应用商店"])
        lost = Mock(side_effect=adb_link.DeviceLost("断开"))
        with self.assertRaises(adb_link.DeviceLost):
            scope["step"]("天气")(lost)

    def test_home_restoring_hiboard_opens_settings_without_swiping_again(self):
        p = phone_mock()
        p.focus.side_effect = [
            "com.vivo.weather/.WeatherSettings", "HiBoard", "HiBoard",
            "com.vivo.hiboard/com.vivo.hiboard.settings.AppletSettingActivity",
        ]
        p.find.return_value = (1, 2)
        p.go.return_value = True
        scope = self.load(p)
        scope["hiboard_panel"]()
        self.assertEqual([call.args[0] for call in p.d.shell.call_args_list],
                         ["input keyevent HOME", "input keyevent HOME"])
        p.go.assert_called_once_with("设置", "更多设置")

    def test_unknown_home_cannot_trigger_swipe_or_settings_click(self):
        p = phone_mock()
        p.focus.side_effect = ["com.vivo.weather/.WeatherSettings", "com.example/.Other"]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未回到系统桌面"):
            scope["hiboard_panel"]()
        self.assertEqual([call.args[0] for call in p.d.shell.call_args_list],
                         ["input keyevent HOME", "input keyevent HOME"])
        p.go.assert_not_called()

    def test_direct_ad_settings_does_not_dismiss_switch_description_as_popup(self):
        p = phone_mock()
        p.locked.return_value = False
        p.focus.return_value = "com.android.settings/com.android.settings.Settings$AdAndPrivacyActivityForOsTwo"
        p.reader.shell.return_value = Mock(exit_code=0, output="Starting: Intent")   # Phone.start 走 reader
        p.texts.return_value = [("个性化广告.关闭后仍会看到广告", (1, 2, 3, 4), None)]
        p.switches.return_value = [(name, False, (1, 600))
                                   for name in ("个性化广告", "个性化推荐", "智能推荐服务")]
        p.dismiss.side_effect = AssertionError("不应在设置开关页消弹窗")
        p.start.side_effect = lambda *args, **kwargs: fast.Phone.start(p, *args, **kwargs)
        scope = self.load(p, only=["系统广告"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 3)
        p.dismiss.assert_not_called()


if __name__ == "__main__":
    unittest.main()
