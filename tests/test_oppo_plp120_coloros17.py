"""PLP120 在 ColorOS 17 上的「小布建议」与「游戏中心」两段（#905）。

小布建议以前点到「内容资讯」这个点不动的分组标题，然后在列表页找开关，结果是「核对 0 项」
静默收尾：开关一个没动，段也不算干净失败。现在要点进「资讯服务」二级页再点名关，旧入口留作兜底，
两条都不通时报错并带上现场。游戏中心以前死等底部「我的」，这台机上没有；现在先试 APP_SETTINGS
直达设置页，「我的 → 设置」只在直达落空时兜底，设置入口同时认文字行与右上角无文字齿轮。
"""
import io
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock
from fast import ScreenLocked

RECIPE = ROOT / "recipes/oppo/PLP120/PLP120.toml"
SETTINGS_FOCUS = "com.android.settings/com.oplus.settings.OplusSettingsActivity"
GAME_HOME = "com.nearme.gamecenter/com.nearme.gamecenter.ui.activity.MainActivity"
GAME_SETTINGS = "com.nearme.gamecenter/com.nearme.gamecenter.settings.SettingActivity"
TARGET = [("资讯服务", True, (40, 900, 1040, 1000))]
GAME_TARGET = [("个性化推荐", True, (40, 900, 1040, 1000))]


def run(phone, step):
    out = io.StringIO()
    scope, _ = load_recipe(phone, RECIPE, only=(step,), out=out)
    return scope, out.getvalue()


def make_phone(focus=SETTINGS_FOCUS, switches=TARGET, enter=None, shell=None, find=True):
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.focus.return_value = focus
    if callable(find):
        p.find.side_effect = find
    else:
        p.find.return_value = find
    p.texts.return_value = []
    p.switches.return_value = list(switches)
    if enter is not None:
        p.enter.side_effect = enter
    if shell is not None:
        p.d.shell.side_effect = shell
    return p


class XiaobuStepTests(unittest.TestCase):
    def test_service_sub_page_is_opened_before_the_switch_is_closed(self):
        """ColorOS 17：「内容资讯」点不动，开关在「资讯服务」二级页上。"""
        p = make_phone()
        run(p, "小布建议")
        self.assertEqual([call.args[0] for call in p.enter.call_args_list],
                         ["OPPO AI", "小布建议", "资讯服务"])
        self.assertEqual(p.off.call_args.kwargs["only"], ["资讯服务"])
        self.assertEqual(p.off.call_args.kwargs["page"], "小布建议·资讯服务")

    def test_sub_page_that_did_not_open_falls_back_to_the_list_page(self):
        """`p.enter` 只认「页面变了」：点进别的页也算成功，落点不对时要接着试下一个入口。"""
        asked = {"资讯服务": 0}

        def find(text, **kwargs):
            if text == "资讯服务":
                asked["资讯服务"] += 1
                return asked["资讯服务"] > 1
            return True

        p = make_phone(find=find)
        run(p, "小布建议")
        self.assertEqual(p.off.call_args.kwargs["page"], "小布建议·内容资讯")

    def test_old_content_entry_is_the_fallback_on_coloros16(self):
        """ColorOS 16 没有「资讯服务」这一行：回退到点「内容资讯」进列表页。"""

        def enter(text, **kwargs):
            if text == "资讯服务":
                raise RuntimeError("未找到入口「资讯服务」")

        p = make_phone(enter=enter)
        run(p, "小布建议")
        self.assertEqual([call.args[0] for call in p.enter.call_args_list][-2:],
                         ["资讯服务", "内容资讯"])
        self.assertEqual(p.off.call_args.kwargs["page"], "小布建议·内容资讯")

    def test_lock_screen_is_not_mistaken_for_a_missing_entry(self):
        """锁屏不是「入口没进去」：整批中止，不能一路回退到「两条入口都没进去」。"""

        def enter(text, **kwargs):
            if text == "资讯服务":
                raise ScreenLocked("手机锁屏了，请机主解锁后重跑")

        p = make_phone(enter=enter)
        scope, _ = run(p, "小布建议")
        self.assertTrue(scope["HALTED"])
        self.assertEqual(scope["FAILED_STEPS"], ["小布建议"])
        p.off.assert_not_called()

    def test_neither_entry_opening_is_a_failure_without_touching_switches(self):
        """两条入口都不通：整段记失败，不能像以前那样「核对 0 项」静默收尾。"""

        def enter(text, **kwargs):
            if text in ("资讯服务", "内容资讯"):
                raise RuntimeError(f"未找到入口「{text}」")

        p = make_phone(enter=enter)
        scope, log = run(p, "小布建议")
        self.assertEqual(scope["FAILED_STEPS"], ["小布建议"])
        self.assertIn("两条入口都没进去", log)
        p.off.assert_not_called()

    def test_missing_switch_on_the_sub_page_keeps_the_page_scene(self):
        """进了二级页却没有目标开关：报错带停在哪个页与当次读到的标题（#903）。"""
        p = make_phone(switches=[("其他开关", True, (40, 900, 1040, 1000))])
        scope, log = run(p, "小布建议")
        self.assertEqual(scope["FAILED_STEPS"], ["小布建议"])
        self.assertIn("未识别全部目标开关", log)
        p.page_evidence.assert_called_once_with(["其他开关"])
        p.off.assert_not_called()


class GameCenterStepTests(unittest.TestCase):
    def test_app_settings_entry_skips_the_mine_tab(self):
        """ColorOS 17 认 APP_SETTINGS，直达设置页，不用找底部「我的」。"""
        p = make_phone(focus=GAME_SETTINGS, switches=GAME_TARGET,
                       shell=[SimpleNamespace(exit_code=0, output="")])
        run(p, "游戏中心")
        self.assertIn("oppo.intent.action.APP_SETTINGS", p.d.shell.call_args.args[0])
        p.start.assert_not_called()
        self.assertEqual(p.off.call_args.kwargs["only"], ["个性化推荐"])

    def test_denied_direct_command_falls_back_to_the_mine_tab(self):
        p = make_phone(focus=GAME_HOME, switches=GAME_TARGET,
                       shell=[SimpleNamespace(exit_code=1, output="Permission Denial")])
        run(p, "游戏中心")
        p.start.assert_called_once_with("com.nearme.gamecenter")
        self.assertEqual(p.off.call_args.kwargs["only"], ["个性化推荐"])

    def test_direct_entry_landing_elsewhere_falls_back_instead_of_failing(self):
        """旧版本不认这个动作时 am start 不报错，只是落在首页：按落点回退，不是整段失败。"""
        p = make_phone(focus=GAME_HOME, switches=GAME_TARGET,
                       shell=[SimpleNamespace(exit_code=0, output="")])
        scope, _ = run(p, "游戏中心")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_called_once_with("com.nearme.gamecenter")
        self.assertEqual(p.off.call_args.kwargs["only"], ["个性化推荐"])

    def test_settings_entry_accepts_the_textless_gear(self):
        """「我的」页的「设置」在新版是没有文字的齿轮：文字行找不到时用右上角图标。"""

        def enter(text, **kwargs):
            if text == "设置":
                raise RuntimeError("未找到入口「设置」")

        p = make_phone(focus=GAME_HOME, switches=GAME_TARGET, enter=enter,
                       shell=[SimpleNamespace(exit_code=1, output="Permission Denial")])
        run(p, "游戏中心")
        p.tap_icon.assert_called_once_with(["隐私开关设置", "隐私"])
        self.assertEqual(p.off.call_args.kwargs["only"], ["个性化推荐"])

    def test_wrong_settings_row_falls_back_to_the_textless_gear(self):
        """含「设置」的行（如「隐私设置」）点进去不是设置页：退回来改点齿轮，不押在包含匹配上。"""

        def find(text, **kwargs):
            return text != "隐私开关设置"

        p = make_phone(focus=GAME_HOME, switches=GAME_TARGET, find=find,
                       shell=[SimpleNamespace(exit_code=1, output="Permission Denial")])
        run(p, "游戏中心")
        p.tap_icon.assert_called_once_with(["隐私开关设置", "隐私"])
        self.assertEqual(p.off.call_args.kwargs["only"], ["个性化推荐"])

    def test_missing_switch_on_the_switch_page_is_not_silent(self):
        p = make_phone(focus=GAME_SETTINGS, switches=[("其他开关", True, (40, 900, 1040, 1000))],
                       shell=[SimpleNamespace(exit_code=0, output="")])
        scope, log = run(p, "游戏中心")
        self.assertEqual(scope["FAILED_STEPS"], ["游戏中心"])
        self.assertIn("未识别全部目标开关", log)
        p.off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
