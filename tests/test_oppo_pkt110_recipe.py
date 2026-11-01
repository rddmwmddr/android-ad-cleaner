"""OPPO Find X8s（PKT110 / ColorOS 17）：入口回读和目标开关不完整时停止，避免把尝试写成成功。"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import run


class OppoPkt110RecipeTests(unittest.TestCase):
    def load(self, phone):
        path = ROOT / "recipes/oppo-PKT110/recipe.py"
        scope = {"p": phone, "ONLY": ["__no_steps__"]}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
        return scope

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("PKT110", "OPPO")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "oppo-PKT110")
        self.assertEqual(run.recipe_meta(path)["build"], "PKT110_17.0.0.102(CN01)")

    def test_other_oppo_model_falls_back_to_reference_recipe(self):
        path, reference = run.recipe_for("PZZ999", "OPPO")      # 没有本型号脚本的 OPPO（PMX110 已由 #279 补上）
        self.assertTrue(reference)
        self.assertEqual(Path(path).parent.name, "oppo-PLP120")

    def test_missing_target_aborts_without_clicking_any_switch(self):
        p = Mock(); p.switches.return_value = [("WLAN 自动更新应用", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标开关"):
            scope["close_named"](["个性化推荐"], "商店")
        p.off.assert_not_called()

    def test_reverted_switch_is_failure_not_verified(self):
        p = Mock(); p.switches.return_value = [("个性化推荐", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭"):
            scope["close_named"](["个性化推荐"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_target_below_fold_is_verified_and_other_switch_is_preserved(self):
        p = Mock()
        p.scroll_more.return_value = True
        p.switches.side_effect = [
            [("活动弹窗", True, (1, 2)), ("应用安全", True, (1, 3))],
            [("软件福利", True, (1, 2))],
            [("活动弹窗", False, (1, 2)), ("应用安全", True, (1, 3))],
            [("软件福利", False, (1, 2))],
        ]
        scope = self.load(p)
        scope["close_named"](["活动弹窗", "软件福利"], "商店", max_screens=2)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 2)

    def test_unrelated_switch_changed_is_not_reported_as_verified(self):
        p = Mock()
        p.switches.side_effect = [
            [("活动弹窗", True, (1, 2)), ("应用安全", True, (1, 3))],
            [("活动弹窗", False, (1, 2)), ("应用安全", False, (1, 3))],
        ]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named"](["活动弹窗"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_page_that_asks_for_confirmation_is_reopened_before_readback(self):
        """主题商店「个性化推荐设置」：点下去弹确认框，确认后页面退回「设置」，
        回读前要重新进一次，否则会把关成功的开关算成没关。"""
        p = Mock()
        p.switches.side_effect = [
            [("个性化推荐设置", True, (1, 2))],
            [("个性化推荐设置", False, (1, 2))],
        ]
        scope = self.load(p)
        reopened = []
        scope["close_named"](["个性化推荐设置"], "主题", reopen=lambda: reopened.append(1))
        self.assertEqual(len(reopened), 1)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_close_all_needs_a_switch_to_be_present(self):
        p = Mock(); p.switches.return_value = []
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "没读到开关"):
            scope["close_all"]("广告跟踪", max_screens=1)
        p.off.assert_not_called()

    def test_close_all_reports_switches_still_on_after_readback(self):
        p = Mock()
        p.switches.side_effect = [
            [("广告跟踪", True, (1, 2))],
            [("广告跟踪", True, (1, 2))],
        ]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭"):
            scope["close_all"]("广告跟踪", max_screens=1)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_close_all_verifies_every_switch_is_off(self):
        p = Mock()
        p.switches.side_effect = [
            [("广告跟踪", True, (1, 2)), ("示例应用", True, (1, 3))],
            [("广告跟踪", False, (1, 2)), ("示例应用", False, (1, 3))],
        ]
        scope = self.load(p)
        scope["close_all"]("广告跟踪", max_screens=1)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 2)

    def test_recipe_never_suspends_disables_or_uninstalls_packages(self):
        """挂起、停用、卸载和整包关通知都不该出现在机型脚本里（归档记录 0.2.6 记过问题写法）。"""
        source = (ROOT / "recipes/oppo-PKT110/recipe.py").read_text(encoding="utf-8")
        for forbidden in ("pm suspend", "pm uninstall", "pm disable-user", "pm revoke", "notif-off"):
            self.assertNotIn(forbidden, source)


class OppoPkt110ParentChildTests(unittest.TestCase):
    """全局搜索「首页卡片管理」里，父开关一关，子开关那两行就从页面上消失。"""

    def make(self, state):
        phone = Mock()
        phone.scroll_more.return_value = False
        phone.top.return_value = None
        phone.switches.side_effect = lambda *a, **k: [(t, on, (10, 10)) for t, on in state.items()]

        def off(only=None, page="", max_screens=40, **kw):
            for name in list(state):
                if only is not None and not any(k in name for k in only):
                    continue
                state[name] = False
                if name == "应用建议":              # 父项一关，子项那两行就没了
                    for child in ("未下载应用推荐", "应用建议小卡"):
                        state.pop(child, None)
        phone.off.side_effect = off
        return phone, state

    def load(self, phone):
        path = ROOT / "recipes/oppo-PKT110/recipe.py"
        scope = {"p": phone, "ONLY": ["__no_steps__"]}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
        return scope

    def test_children_are_closed_before_the_parent(self):
        phone, state = self.make({"应用建议": True, "未下载应用推荐": True,
                                  "应用建议小卡": True, "热搜应用": True})
        scope = self.load(phone)
        scope["close_group"](["未下载应用推荐", "应用建议小卡"], "应用建议", "卡片", max_screens=1)
        self.assertEqual(state.get("应用建议"), False)
        self.assertEqual(state.get("热搜应用"), True)      # 别的开关不能被顺手动
        self.assertEqual(scope["VERIFIED_SWITCHES"], 3)

    def test_only_parent_is_closed_when_children_rows_are_already_gone(self):
        phone, state = self.make({"应用建议": False, "热搜应用": True})
        scope = self.load(phone)
        scope["close_group"](["未下载应用推荐", "应用建议小卡"], "应用建议", "卡片", max_screens=1)
        self.assertEqual(state.get("应用建议"), False)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_row_disappearing_with_parent_is_not_reported_as_state_change(self):
        """子项那两行随父项一起消失，回读时不能再当成「别的开关状态变了」。"""
        phone, state = self.make({"应用建议": True, "未下载应用推荐": True,
                                  "应用建议小卡": True, "热搜应用": True})
        scope = self.load(phone)
        scope["close_named"](["应用建议"], "卡片", max_screens=1,
                             gone=["未下载应用推荐", "应用建议小卡"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_page_without_any_switch_is_reported(self):
        phone, state = self.make({})
        scope = self.load(phone)
        scope["wait_switches"] = lambda *a, **k: False
        with self.assertRaisesRegex(RuntimeError, "没读到开关"):
            scope["close_named"](["个性化推荐"], "卡片", max_screens=1)


    def load_only(self, phone, only):
        """按段名加载：ONLY 命中的段在 exec 时就执行，异常记进 FAILED_STEPS。"""
        path = ROOT / "recipes/oppo-PKT110/recipe.py"
        scope = {"p": phone, "ONLY": only}
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
        return scope

    def test_game_center_falls_back_to_the_settings_icon(self):
        """游戏中心 14.43.3 的「设置」是右上角没有文字的齿轮：文字找不到就用图标，不能整段失败（#292）。"""
        phone = Mock()
        phone.locked.return_value = False
        phone.tap.side_effect = lambda text, **kw: text in ("我的", "隐私开关设置", "个性化推荐管理")
        phone.tap_icon.return_value = True
        phone.switches.side_effect = [[("个性化推荐", True, (1, 2))], [("个性化推荐", False, (1, 2))]]
        phone.scroll_more.return_value = False
        scope = self.load_only(phone, ["游戏中心"])
        phone.tap_icon.assert_called_once_with(["隐私开关设置", "隐私"])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_game_center_without_the_icon_reports_failure_and_stops(self):
        """图标也点不开时要报未完成，不能继续点后面的入口装作成功。"""
        phone = Mock()
        phone.locked.return_value = False
        phone.tap.side_effect = lambda text, **kw: text == "我的"
        phone.tap_icon.return_value = False
        scope = self.load_only(phone, ["游戏中心"])
        self.assertEqual(scope["FAILED_STEPS"], ["游戏中心"])
        self.assertNotIn("隐私开关设置", [c.args[0] for c in phone.tap.call_args_list])

    def test_ad_tracking_tries_the_renamed_entry_first(self):
        """ColorOS 17 叫「隐私与安全」：先试新名字，不要在旧名字上白翻一轮再打一行失败（#292）。"""
        phone = Mock()
        phone.locked.return_value = False
        phone.tap.return_value = False
        scope = self.load_only(phone, ["广告跟踪"])
        self.assertEqual(phone.tap.call_args_list[0].args[0], "隐私与安全")
        self.assertEqual(scope["FAILED_STEPS"], ["广告跟踪"])


if __name__ == "__main__":
    unittest.main()
