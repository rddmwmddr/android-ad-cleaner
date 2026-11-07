"""#671：荣耀 CLE-AN00 机型脚本。不代为同意协议、底部标签带角标、必需入口缺失要报失败。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from fixtures import load_recipe, phone_mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

RECIPE = ROOT / "recipes" / "honor-CLE-AN00" / "recipe.py"


def phone(**over):
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.focus.return_value = ""
    p.entry.return_value = True
    p.tab.return_value = True
    p.tap.return_value = True
    p.find.return_value = None
    p.setting.return_value = True
    p.expect_page.return_value = True
    p.switches.return_value = []
    p.texts.return_value = []
    for k, v in over.items():
        setattr(p, k, v)
    return p


def run(p, name):
    scope, out = load_recipe(p, RECIPE, only=name)
    return scope, out.getvalue()


def agreement(text, exact=False, **kw):
    return object() if text == "同意" else None


def in_app(p, pkg):
    """前台已经是这个 App。"""
    p.focus.return_value = f"{pkg}/.Page"
    return p


THEME = "com.hihonor.android.thememanager"
BROWSER = "com.hihonor.baidu.browser"


class AgreementTest(unittest.TestCase):
    def test_theme_with_agreement_is_skipped_not_failed(self):
        p = in_app(phone(), THEME)
        p.find.side_effect = agreement
        scope, out = run(p, "主题")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("不代为同意", out)
        p.off.assert_not_called()
        p.tap.assert_not_called()
        p.entry.assert_not_called()

    def test_theme_is_launched_raw_so_the_engine_does_not_cancel_the_dialog(self):
        # p.start 的弹窗处理会点「取消」，App 一退就分不清是没同意还是没打开
        p = in_app(phone(), THEME)
        p.find.side_effect = agreement
        run(p, "主题")
        p.start.assert_not_called()
        self.assertIn("com.hihonor.android.thememanager/.PageActivity", p.d.shell.call_args.args[0])

    def test_agreement_that_draws_late_is_still_seen(self):
        # 后台屏慢：首页先有文字，协议框晚一点。没等到就会接着往下点，弹窗处理再把协议「取消」掉
        p = in_app(phone(), THEME)
        seen = iter([None, None, None])
        p.find.side_effect = lambda text, exact=False, **kw: (next(seen, object()) if text == "同意" else None)
        scope, out = run(p, "主题")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("不代为同意", out)
        p.tab.assert_not_called()

    def test_agreement_that_draws_after_the_tabs_is_still_seen(self):
        # 真实发生过：底栏先出来，协议框晚 1 秒，接着往下走时弹窗处理点了「取消」，App 退回浏览器
        p = in_app(phone(), THEME)
        asked = {"同意": 0}

        def find(text, exact=False, **kw):
            if text == "我的":
                return object()
            if text == "同意":
                asked["同意"] += 1
                return object() if asked["同意"] >= 3 else None
            return None

        p.find.side_effect = find
        scope, out = run(p, "主题")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("不代为同意", out)
        p.tab.assert_not_called()

    def test_agreement_button_at_the_very_bottom_of_the_screen_counts(self):
        # find 默认不看屏幕最底下那一条；后台屏上协议框的按钮可能正好落在那里，这时弹窗处理会点「取消」
        p = in_app(phone(), THEME)
        p.find.side_effect = lambda text, exact=False, edge_ok=False, **kw: (
            object() if text == "同意" and edge_ok == "tab" else None)
        scope, out = run(p, "主题")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("不代为同意", out)

    def test_stale_page_of_the_previous_app_is_not_used(self):
        # 真实发生过：主题还没起来，就在上一个 App（浏览器）的页面上点了「我的」
        p = in_app(phone(), BROWSER)
        scope, out = run(p, "主题")
        self.assertEqual(scope["FAILED_STEPS"], ["主题"])
        self.assertIn("主题没有打开", out)
        p.tab.assert_not_called()

    def test_market_with_agreement_is_skipped(self):
        p = phone()
        p.find.side_effect = agreement
        scope, _ = run(p, "市场")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.off.assert_not_called()


class MarketTest(unittest.TestCase):
    def test_uses_the_bottom_tab_and_closes_each_switch_alone(self):
        p = phone()
        scope, _ = run(p, "市场")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tab.assert_called_once_with("我的")
        only = [c.kwargs["only"] for c in p.off.call_args_list]
        self.assertEqual(only[:3], [["营销服务推荐"], ["个性化服务推荐"], ["热门推荐管理"]])

    def test_keeps_update_and_system_notices(self):
        p = phone()
        run(p, "市场")
        kept = [c.kwargs.get("keep", []) for c in p.off.call_args_list]
        self.assertIn(["应用更新通知"], kept)
        self.assertIn(["系统通知", "互动"], kept)

    def test_never_switches_to_basic_service(self):
        # 切回完整服务要重新同意协议
        p = phone()
        run(p, "市场")
        self.assertNotIn("基本服务", [c.args[0] for c in p.tap.call_args_list])
        self.assertNotIn("服务模式", [c.args[0] for c in p.entry.call_args_list])

    def test_missing_entry_is_a_failure_not_silent_success(self):
        p = phone()
        p.entry.side_effect = lambda text, scrolls=4: text != "内容推荐服务"
        scope, out = run(p, "市场")
        self.assertEqual(scope["FAILED_STEPS"], ["市场"])
        self.assertIn("内容推荐服务", out)

    def test_tab_hidden_by_a_late_dialog_is_not_read_as_basic_service(self):
        # 晚到的「发现新版本」盖住底栏时「我的」读不到；只是被盖住，不是基本服务模式
        p = phone()
        covered = {"dialog": True}

        def find(text, exact=False, **kw):
            if text == "基本服务":
                return object()
            if text == "我的":
                return None if covered["dialog"] else object()
            return None

        p.find.side_effect = find
        p.dismiss.side_effect = lambda: covered.update(dialog=False)
        scope, _ = run(p, "市场")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tab.assert_called_once_with("我的")


class LaunchTest(unittest.TestCase):
    def test_raw_launch_sets_the_app_used_by_promoted_checks(self):
        # launch() 绕开 p.start：不设 p.app，推广位识别会沿用上一段的 App
        p = in_app(phone(), BROWSER)
        p.find.side_effect = agreement
        run(p, "浏览器")
        self.assertEqual(p.app, BROWSER)


class AdTrackingTest(unittest.TestCase):
    def test_reports_switches_still_on_after_close_all(self):
        p = phone()
        p.switches.return_value = [("某应用", True), ("别的应用", False)]
        scope, out = run(p, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], ["广告跟踪"])
        self.assertIn("还有 1 个开着", out)

    def test_does_not_print_app_names(self):
        # 列表是装机应用，属于个人信息
        p = phone()
        p.switches.return_value = [("某个私人应用", False)]
        _, out = run(p, "广告跟踪")
        self.assertNotIn("某个私人应用", out)


class ReaderTest(unittest.TestCase):
    def test_tab_covered_by_a_late_dialog_is_found_after_closing_it(self):
        # 真实发生过：开屏广告之后才弹「发现新版本」，盖住底栏，直接点就报「我的」没找到
        p = in_app(phone(), "com.hihonor.dz.reader")
        closed = []
        p.dismiss.side_effect = lambda: closed.append(1)
        p.find.side_effect = lambda text, exact=False, **kw: (object() if text == "我的" and closed else None)
        p.tab.side_effect = lambda text: bool(closed)
        scope, _ = run(p, "阅读")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tab.assert_called_once_with("我的")

    def test_agreement_is_not_closed_while_looking_for_the_tab(self):
        p = in_app(phone(), "com.hihonor.dz.reader")
        shown = {"agreement": False}
        p.dismiss.side_effect = lambda: shown.update(agreement=True)    # 引擎启动后的那次之后协议框才出现
        p.find.side_effect = lambda text, exact=False, **kw: (object() if text == "同意" and shown["agreement"] else None)
        scope, out = run(p, "阅读")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("不代为同意", out)
        p.tab.assert_not_called()


class ReduceAdsTest(unittest.TestCase):
    """#693：「减少广告」方向相反，要打开。"""

    def test_it_is_named_on_the_music_ad_page(self):
        p = in_app(phone(), "com.hihonor.cloudmusic")
        p.d.shell.return_value = Mock(output="")
        run(p, "音乐")
        p.off.assert_any_call(only=["个性化广告推荐", "减少广告"], page="音乐·广告推荐")

    def test_the_engine_opens_it_and_leaves_lookalikes_alone(self):
        from fast import want_state
        self.assertIs(want_state("减少广告"), True)
        self.assertIs(want_state("減少廣告"), True)
        self.assertIs(want_state("减少推荐内容"), True)
        self.assertIsNone(want_state("减少动画"))           # 不带广告词：不碰，也不能当广告开关关掉
        self.assertIs(want_state("个性化广告推荐"), False)


class MusicTest(unittest.TestCase):
    """音乐 App 的「启动后自动播放歌曲」开着时，一打开就放歌。"""

    PLAYING = "package=com.hihonor.cloudmusic\n  state=PlaybackState {state=PLAYING(3), }\n"
    PAUSED = "package=com.hihonor.cloudmusic\n  state=PlaybackState {state=PAUSED(2), }\n"
    OTHER_PLAYING = "package=com.other.player\n  state=PlaybackState {state=PLAYING(3), }\n"

    def phone(self, before, after):
        """启动前读到 before；发了启动指令之后读到 after，暂停之后读到 PAUSED。"""
        p = in_app(phone(), "com.hihonor.cloudmusic")
        state = {"now": before}

        def shell(cmd):
            if cmd.startswith("am start"):
                state["now"] = after
            elif "KEYCODE_MEDIA_PAUSE" in cmd:
                state["now"] = self.PAUSED
            return Mock(output=state["now"] if cmd.startswith("dumpsys") else "")

        p.d.shell.side_effect = shell
        return p

    def pauses(self, p):
        return [c for c in p.d.shell.call_args_list if "KEYCODE_MEDIA_PAUSE" in c.args[0]]

    def test_auto_play_is_paused_once_before_the_page_is_awaited(self):
        p = self.phone(self.PAUSED, self.PLAYING)
        at_first_look = []

        def focus():
            at_first_look.append(len(self.pauses(p)))
            return "com.hihonor.cloudmusic/.Main"

        p.focus.side_effect = focus
        scope, out = run(p, "音乐")
        self.assertEqual(at_first_look[0], 1, "要在等首页之前就暂停")
        self.assertEqual(len(self.pauses(p)), 1)
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("已暂停", out)

    def test_app_is_launched_only_once(self):
        # 真实发生过：暂停后 p.start 再拉起一次，它又放了一遍
        p = self.phone(self.PAUSED, self.PLAYING)
        run(p, "音乐")
        p.start.assert_not_called()
        self.assertEqual(sum(c.args[0].startswith("am start") for c in p.d.shell.call_args_list), 1)

    def test_user_who_was_already_listening_is_left_alone(self):
        p = self.phone(self.PLAYING, self.PLAYING)
        run(p, "音乐")
        self.assertEqual(self.pauses(p), [])

    def test_app_that_does_not_auto_play_is_left_alone(self):
        p = self.phone("", self.PAUSED)
        scope, out = run(p, "音乐")
        self.assertEqual(self.pauses(p), [])
        self.assertNotIn("已暂停", out)

    def test_another_app_playing_is_not_paused(self):
        p = self.phone(self.OTHER_PLAYING + self.PAUSED, self.OTHER_PLAYING + self.PAUSED)
        run(p, "音乐")
        self.assertEqual(self.pauses(p), [])

    def test_late_playback_is_paused_even_when_the_step_fails(self):
        p = self.phone(self.PAUSED, self.PAUSED)
        p.d.return_value.click_exists.return_value = False      # 设置图标没找到

        def late():
            p.d.shell.side_effect = lambda cmd: Mock(output=self.PLAYING if cmd.startswith("dumpsys") else "")
            return "com.hihonor.cloudmusic/.Main"

        p.focus.side_effect = late
        scope, _ = run(p, "音乐")
        self.assertEqual(scope["FAILED_STEPS"], ["音乐"])
        self.assertTrue(any("KEYCODE_MEDIA_PAUSE" in c.args[0] for c in p.d.shell.call_args_list))


class SearchTest(unittest.TestCase):
    def more_at(self, top):
        return [("更多", (0, top, 10, top + 10), None)]

    def test_back_is_not_pressed_when_more_is_already_there(self):
        # 后台屏没有键盘，按返回会把搜索页退掉
        p = phone()
        p.texts.return_value = self.more_at(1000)
        scope, _ = run(p, "搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.d.press.assert_not_called()

    def test_back_closes_the_keyboard_when_more_is_hidden(self):
        p = phone()
        p.texts.side_effect = [[], self.more_at(1000)] + [[]] * 20
        scope, _ = run(p, "搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.d.press.assert_called_once_with("back")


class MinusOneTest(unittest.TestCase):
    def test_background_screen_skips_with_manual_steps(self):
        # 负一屏是桌面的一部分，后台屏上没有：说明并跳过，不把整轮报成失败
        p = phone()
        scope, out = run(p, "负一屏")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("桌面向右滑", out)
        p.off.assert_not_called()

    def test_waits_for_the_page_before_scrolling(self):
        # 页面切换时前台还是上一页，这时翻页引擎会判成「离开了设置页」
        p = phone()
        p.find.side_effect = lambda text, exact=False, **kw: object() if text == "头像" else None
        calls = []
        p.expect_page.side_effect = lambda *a, **k: calls.append("等") or True
        p.off.side_effect = lambda **k: calls.append("关")
        run(p, "负一屏")
        self.assertEqual(calls, ["等", "关", "等", "关"])

    def test_page_that_never_draws_is_a_failure(self):
        p = phone()
        p.find.side_effect = lambda text, exact=False, **kw: object() if text == "头像" else None
        p.expect_page.return_value = False
        scope, _ = run(p, "负一屏")
        self.assertEqual(scope["FAILED_STEPS"], ["负一屏"])
        p.off.assert_not_called()


class NamedOnlyTest(unittest.TestCase):
    def test_every_close_names_its_switches(self):
        # 按型号 + 版本匹配时不是安全模式，不点名就是整页全关
        src = RECIPE.read_text(encoding="utf-8")
        for line in src.splitlines():
            if "p.off(" in line and "only=" not in line:
                self.fail(f"没有点名的 p.off：{line.strip()}")


if __name__ == "__main__":
    unittest.main()
