"""启动与落点阶段（`tool/phone/launcher.py`，ADR-0033）：`start()` 之后算不算到了目标 App。

三件事分开守：
  · 启动时的前台归属——读不出焦点不是「离开」，确知被别的 App 占了才停段（#581）；
  · 停段时的现场——被谁抢了前台、当前落在哪个页面，两者分开写（#940）；
  · 落点校验——给了期望文字就先确认落在那一页，落在开屏 / 推广页时退一次重来（#420）。

票号留在各用例的 docstring 首行；按票号 grep 仍能找到它。
"""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adb_link  # noqa: E402
import fast  # noqa: E402
import recipe_kit  # noqa: E402
from fixtures import (EMPTY_PAGE, Clock, clocked, fake_phone, phone_stub, screen_stub,  # noqa: E402
                      shell_result, stub)
from phone import launcher as launcher_module  # noqa: E402

# ---------- #581：主题商店的前台归属 ----------
THEME_PKG = "com.miui.themestore"
THEME_APP = THEME_PKG + "/.MainActivity"
THEME_OTHER = "com.example.other/.Account"
THEME_MANAGER = "com.android.thememanager/.ThemeResourceProxyTabActivity"

THEME_HOME = f'''<hierarchy rotation="0"><node package="{THEME_PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="主题" bounds="[60,100][400,180]"/>
  <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
</node></hierarchy>'''

# ---------- #940：应用商店启动时报出抢夺者 ----------
MARKET_PKG = "com.heytap.market"
MARKET_APP = MARKET_PKG + "/com.heytap.market.activity.MainActivity"
MARKET_OTHER = "com.oplus.securitypermission/.XActivity"
MARKET_LAUNCHER = "com.miui.home/.Launcher"

MARKET_HOME = f'''<hierarchy rotation="0"><node package="{MARKET_PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="应用商店" bounds="[60,100][400,180]"/>
</node></hierarchy>'''


def frames(*seq, tail=""):
    """焦点按帧给：seq 读完以后一直给 tail。轮询读几次就是几帧，不看挂钟。"""
    it = iter(seq)

    def focus():
        return next(it, tail)
    return focus


# ---------- #420：应用商店的落点校验 ----------
def promo_page(n=17):
    """开屏推荐页：有文字、没有底栏（所以「我的」找不到）。"""
    rows = "".join(
        f'<node class="android.widget.TextView" text="推荐{i}款应用" '
        f'bounds="[60,{300 + i * 110}][900,{380 + i * 110}]"/>' for i in range(n))
    return ('<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">'
            f'{rows}</node></hierarchy>')


STORE_HOME = '''<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="应用商店" bounds="[60,100][600,180]"/>
  <node class="android.widget.TextView" text="首页" bounds="[60,2180][200,2260]"/>
  <node class="android.widget.TextView" text="应用" bounds="[260,2180][400,2260]"/>
  <node class="android.widget.TextView" text="游戏" bounds="[460,2180][600,2260]"/>
  <node class="android.widget.TextView" text="分类" bounds="[660,2180][800,2260]"/>
  <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
</node></hierarchy>'''

# 不是底栏、只是标题里含「我的」：不能当成落在主页
TITLE_PAGE = '''<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="我的应用" bounds="[60,300][900,380]"/>
  <node class="android.widget.TextView" text="管理我的应用" bounds="[60,420][900,500]"/>
</node></hierarchy>'''

STORE_APP = "com.bbk.appstore/.Main"


class LaunchForegroundTests(unittest.TestCase):
    def phone(self, stages, focus, **fields):
        clock = Clock()
        clocked(self, fast, clock)
        p = fake_phone(clock=clock, stages=stages, focus=focus, **fields)
        return p, clock

    def test_empty_focus_while_the_window_paints_is_not_leaving(self):
        """#581 空格→目标包：过渡期读不出焦点照常等，不报「没有进入前台」。
        旧实现也能过（0.6 秒落在 5 秒预算内），守着的是这条基本路径不回退。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (0.6, THEME_HOME)],
                          focus=((0.0, ""), (0.6, THEME_APP)))
        p.start(THEME_PKG, settle=0)

    def test_empty_focus_after_entering_is_not_leaving(self):
        """#581 目标→空→目标：进过目标 App 之后短暂读不出，不是「启动后离开前台」。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (0.25, ""), (0.7, THEME_APP)))
        p.start(THEME_PKG, settle=1.2)

    def test_one_frame_in_another_app_is_not_leaving(self):
        """#581 目标→别的包 1 次→回到目标：跳包过渡帧不算被占住。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (0.25, THEME_OTHER), (0.7, THEME_APP)))
        p.start(THEME_PKG, settle=1.2)

    def test_jump_package_transition_is_not_leaving(self):
        """#581 主题商店 → 主题管理器的跳包过渡帧（报告者实测的形态）。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (0.3, THEME_MANAGER), (0.8, THEME_APP)))
        p.start(THEME_PKG, settle=1.2)

    def test_sustained_other_app_stops_the_step_with_the_landing_page(self):
        """#581 持续被别的 App 占住照样停段，报错带上落点（#547）。"""
        p, _ = self.phone([(0.0, THEME_HOME)], focus=((0.0, THEME_APP), (0.2, THEME_OTHER)))
        reads = []
        focus = p.screen.focus      # 取基座原来那个：门面的 focus 已经转到基座上，取门面会绕回自己
        p.screen.focus = lambda: (lambda v: (reads.append(v), v)[1])(focus())
        with self.assertRaisesRegex(RuntimeError,
                                    r"离开前台.*停在 com\.example\.other/\.Account"):
            p.start(THEME_PKG, settle=1.2)
        self.assertGreaterEqual(reads.count(THEME_OTHER), 3)      # 连续读到才算，不是一帧就停

    def test_six_seconds_of_unreadable_focus_still_reaches_the_app(self):
        """#581 空焦点持续 6 秒后出现目标包：不算超时（5 秒启动预算不计空焦点）。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (6.0, THEME_HOME)],
                          focus=((0.0, ""), (6.0, THEME_APP)))
        p.start(THEME_PKG, settle=0)

    def test_unreadable_focus_forever_fails_within_the_upper_bound(self):
        """#581 空焦点一直不出现目标包：有界失败，文案与原来一致，且是顺延到上限才放弃。
        旧实现在 5 秒就报错，这里要求等过 7 秒——空焦点不能提前花掉启动预算。"""
        # 9 秒后换成确知的外来 App：正常在 8 秒硬上限就停，边界差一的实现才走得到后面
        p, clock = self.phone([(0.0, EMPTY_PAGE)], focus=((0.0, ""), (9.0, THEME_OTHER)))
        with self.assertRaisesRegex(RuntimeError, "没有进入前台"):
            p.start(THEME_PKG, settle=0)
        self.assertLessEqual(clock.t, 8.4)
        self.assertGreater(clock.t, 7.0)

    def test_other_app_taking_over_right_at_the_end_is_caught(self):
        """#581 settle 最后一拍之后才被别的 App 抢前台：收尾那次复核仍要读到并停段
        （d4ee2d2e 的保证）。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (1.0, THEME_OTHER)))
        with self.assertRaisesRegex(RuntimeError, "离开前台"):
            p.start(THEME_PKG, settle=1.2)


class LaunchSeizerTests(unittest.TestCase):
    def phone(self, focus=((0.0, ""),)):
        clock = Clock()
        clocked(self, fast, clock)
        return fake_phone(clock=clock, stages=((0.0, MARKET_HOME),), focus=focus)

    def test_transient_takeover_names_the_seizer_and_the_landing(self):
        """#940 目标 → 别的包连续 3 帧 → 回到目标包：抢夺者与当前落点分开写。"""
        p = self.phone()
        p.screen.focus = frames(MARKET_APP, MARKET_OTHER, MARKET_OTHER, MARKET_OTHER, MARKET_APP)
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertRegex(
            msg,
            r"离开前台.*被 com\.oplus\.securitypermission/\.XActivity 抢了前台，连续 3 帧"
            r".*当前停在 " + MARKET_PKG.replace(".", r"\.")
            + r"/com\.heytap\.market\.activity\.MainActivity")
        # 机型脚本从报错里取落点判 dead_ends：多出「被谁抢了」那一句后仍要取到当前落点（#902 / #906）
        self.assertEqual(recipe_kit.LANDING.search(msg).group(1), MARKET_PKG)

    def test_sustained_takeover_keeps_the_existing_wording(self):
        """#940 目标 → 一直停在别的 App：落点已经写着抢夺者，不重复那一句。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        p.screen.focus = frames(MARKET_APP, tail=MARKET_OTHER)
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn(f"（停在 {MARKET_OTHER}；", msg)
        self.assertNotIn("抢了前台", msg)

    def test_unreadable_focus_never_names_a_seizer(self):
        """#940 只读到空焦点：确知不了是谁，落点仍是「未知页面」，不写伪造的抢夺者。
        旧树也绿，守的是不回退。"""
        p = self.phone(focus=((0.0, ""), (9.0, THEME_OTHER)))
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn("没有进入前台", msg)
        self.assertIn("停在 未知页面", msg)
        self.assertNotIn("抢了前台", msg)

    def test_single_foreign_frame_is_not_named_as_a_seizer(self):
        """#940 启动时桌面闪一帧、之后一直读空：一两帧是过渡，不算确知（#581），不写抢夺者。
        旧树也绿，守的是不回退。"""
        p = self.phone(focus=((0.0, ""), (0.2, MARKET_LAUNCHER), (0.4, ""), (9.0, THEME_OTHER)))
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn("没有进入前台", msg)
        self.assertNotIn("抢了前台", msg)

    def test_alternating_foreign_apps_do_not_invent_a_run(self):
        """#940 A → B → A：外来前台连读 3 帧才停段，但没有哪个包连占 3 帧，不把帧数记到某个包头上。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        p.screen.focus = frames(MARKET_APP, MARKET_OTHER, MARKET_LAUNCHER, MARKET_OTHER, MARKET_APP)
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn(f"停在 {MARKET_APP}", msg)
        self.assertNotIn("抢了前台", msg)

    def test_never_entered_foreground_still_names_a_seizer_it_saw(self):
        """#940 一直没进目标包、最后一帧又读空：之前记下的抢夺者仍要报出来（#940 的另一条短路）。"""
        p = self.phone(focus=((0.0, MARKET_OTHER), (4.9, ""), (9.0, THEME_OTHER)))
        with self.assertRaisesRegex(
                RuntimeError,
                r"没有进入前台.*被 com\.oplus\.securitypermission/\.XActivity 抢了前台，连续 \d+ 帧；"
                r"当前停在 未知页面"):
            p.start(MARKET_PKG, settle=0)


class LandingTests(unittest.TestCase):
    """启动后的落点校验（判据由调用方给）。"""

    def phone(self, stages, focus=((0.0, STORE_APP),), **fields):
        clock = Clock()
        clocked(self, fast, clock)
        return fake_phone(clock=clock, stages=stages, focus=focus, **fields), clock

    def test_promo_page_is_left_before_looking_for_entries(self):
        """#420 落在开屏推广页：退一次回到主页后才去点「我的」。"""
        p, clock = self.phone([(0.0, promo_page()), (30.0, STORE_HOME)])
        stub(p, "back", lambda *a, **k: setattr(clock, "t", 30.0))   # 推广页不会自己消失，返回一次才回主页
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertTrue(p.tap("我的", exact=True, scrolls=0))

    def test_without_expect_the_promo_page_is_searched_until_timeout(self):
        """#420 对照（改前行为）：不给判据就不知道落在推广页，入口探测在推广页里翻满 6 秒才放弃。"""
        p, clock = self.phone([(0.0, promo_page()), (30.0, STORE_HOME)])
        p.start("com.bbk.appstore", settle=0)
        self.assertFalse(p.tap("我的", exact=True, scrolls=0))
        self.assertGreaterEqual(clock.t, 6.0)

    def test_promo_page_that_never_goes_away_fails_with_diagnostics(self):
        """#420 推广页始终不消失：有界失败，日志写清停在哪、期望什么、实际结构，不打印页面文字。"""
        p, clock = self.phone([(0.0, promo_page())])
        lines = []
        stub(p, "say", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))
        with self.assertRaisesRegex(RuntimeError, "非预期页面"):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        out = "\n".join(lines)
        self.assertEqual(out.count("启动后没落在预期页面"), 2)   # 恢复前一次、结束前一次
        self.assertIn(STORE_APP, out)                 # 停在哪个前台
        self.assertIn("我的", out)                    # 期望看到什么
        self.assertIn("标题", out)                    # 实际页面结构摘要
        self.assertNotIn("推荐0款应用", out)          # 不打印页面文字
        self.assertLess(clock.t, 20)                  # 不再把时间走满
        self.assertIn("推荐0款应用", [t for t, _, _ in p.texts()])   # 守卫：页面里真有这些文字

    def test_recovery_relaunches_when_back_leaves_the_app(self):
        """#420 返回把 App 退到后台：重新拉起一次，仍按判据确认落点。"""
        p, clock = self.phone(
            [(0.0, promo_page()), (30.0, STORE_HOME)],
            focus=((0.0, STORE_APP), (30.0, "com.android.launcher/.Launcher"), (31.0, STORE_APP)))
        p.conn.reader.app_stop = Mock()
        stub(p, "back", lambda *a, **k: setattr(clock, "t", 30.0))
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertEqual(p.conn.reader.app_stop.call_count, 2)  # 首次拉起 + 返回后重拉
        self.assertTrue(p.tap("我的", exact=True, scrolls=0))

    def test_expected_page_needs_no_recovery(self):
        """#420 已经在期望的页面上：不返回、不点击。"""
        p, clock = self.phone([(0.0, STORE_HOME)])
        p.start("com.bbk.appstore", settle=0, expect=("首页", "应用", "游戏", "分类", "我的"))
        self.assertEqual(clock.clicks, 0)             # 没有返回、没有点击

    def test_landing_failure_only_presses_back_and_never_taps(self):
        """#420 恢复只发一次返回，不在陌生页面上猜着点。"""
        p, _ = self.phone([(0.0, promo_page())])
        click, back = Mock(), Mock()
        stub(p, "click", click)
        stub(p, "back", back)
        with self.assertRaises(RuntimeError):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        back.assert_called_once()
        click.assert_not_called()

    def test_blank_page_is_not_treated_as_a_promo_page(self):
        """#420 页面重绘成空白（还没画完）时不按返回：空白不等于推广页。"""
        p, _ = self.phone([(0.0, promo_page()), (2.0, EMPTY_PAGE)])
        back = Mock()
        stub(p, "back", back)
        with self.assertRaises(RuntimeError):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        back.assert_not_called()

    def test_a_string_criterion_is_not_split_into_characters(self):
        """#420 单个字符串判据按整词算，不拆成一个个字。"""
        p, _ = self.phone([(0.0, STORE_HOME)])
        self.assertEqual(p.expect_hits("我的"), ["我的"])

    def test_a_title_that_starts_with_the_word_is_not_the_tab(self):
        """#420「我的应用」不是底栏「我的」：判据要停在文字开头或分隔符上。"""
        p, _ = self.phone([(0.0, TITLE_PAGE)])
        self.assertIn("我的应用", [t for t, _, _ in p.texts()])   # 守卫：页面里确实有这个词
        self.assertFalse(p.expect_page("我的", timeout=0.4))

    def test_promoted_keys_are_reset_on_start(self):
        """#420 每次启动清空「点过的推广位」：同一个 App 的新一轮不再沿用上一轮的豁免。"""
        p, _ = self.phone([(0.0, STORE_HOME)])
        p.launch_session.promoted = {("com.bbk.appstore", "关闭")}
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertEqual(p.launch_session.promoted, set())

    def test_device_lost_while_waiting_for_the_landing_page_is_raised(self):
        """#420 等落点时设备掉线：抛 DeviceLost，不当作「没落在预期页面」。"""
        p = phone_stub("test", reader=Mock())
        p.W, p.H = 1080, 2340
        p.lost = True
        with self.assertRaises(adb_link.DeviceLost):
            p.expect_page("我的", timeout=1)



# ---------- 变异判据（ADR-0043、#1539）：启动命令、等待预算与落点现场 ----------
def launch_stage(*, shell=None, focus="com.x/.A", texts=("首页",), serial="S"):
    """只造启动阶段：观测基座与传输都可数，不造整台 Phone。"""
    reader = Mock(name="reader")
    reader.shell = Mock(side_effect=shell or (lambda command, **kw: shell_result("")))
    reader.app_stop = Mock()
    conn = SimpleNamespace(check_alive=Mock(return_value=None), reader=reader, serial=serial,
                           _u2=lambda fn, *a, **kw: fn(*a, **kw))
    screen = screen_stub(EMPTY_PAGE, conn=conn)
    screen.focus = focus if callable(focus) else (lambda: focus)
    screen.texts = Mock(return_value=[(text, (0, 0, 1, 1), None) for text in texts])
    screen._page_diagnosis = Mock(return_value=("com.x/.A", "标题：X"))
    screen.say = Mock()
    screen.back = Mock()
    lost = fast.LostNote()
    stage = fast.Launcher(screen, lost, fast.LaunchSession(), Mock(return_value=None))
    return stage, screen, reader


def shell_by_command(main, pm=""):
    """按命令回不同的 shell 结果：启动命令给 `main`，`pm path` 给 `pm`。"""
    def run(command, **kw):
        if command.startswith("pm path"):
            return shell_result(pm)
        return main
    return run


def scripted_time(values, axis="monotonic"):
    """一个读数按给定序列走、sleep 只记账的时钟：边界值不被浮点累加吃掉。"""
    it = iter(values)
    walker = Mock(side_effect=lambda: next(it))
    clock = SimpleNamespace(time=Mock(return_value=0.0), monotonic=Mock(return_value=0.0), sleep=Mock())
    setattr(clock, axis, walker)
    return clock


class LauncherWiringTests(unittest.TestCase):
    """构造只转发：screen / conn / 会话 / 弹窗接口各落一处。"""

    def test_the_constructor_wires_the_screen_and_the_sessions(self):
        screen = screen_stub(EMPTY_PAGE)
        lost, session, dismiss = fast.LostNote(), fast.LaunchSession(), Mock()
        stage = fast.Launcher(screen, lost, session, dismiss)
        self.assertIs(stage.screen, screen)
        self.assertIs(stage.conn, screen.conn)
        self.assertIs(stage.lost_note, lost)
        self.assertIs(stage.session, session)
        self.assertIs(stage.dismiss, dismiss)

    def test_a_criterion_word_needs_a_separator_after_it(self):
        self.assertTrue(launcher_module.expect_match("我的", "我的，有新消息"))
        self.assertTrue(launcher_module.expect_match("我的", "我的"))
        self.assertFalse(launcher_module.expect_match("我的", "我的应用"))

    def test_a_broken_dump_reads_as_no_text(self):
        stage, screen, _ = launch_stage()
        screen.texts = Mock(side_effect=ET.ParseError)
        self.assertFalse(stage.has_text())


class LaunchCommandTests(unittest.TestCase):
    """`_launch()` 下发的命令与启动失败的三条出口。"""

    def test_a_launch_without_an_activity_uses_monkey_and_clears_the_note(self):
        stage, _, reader = launch_stage()
        stage.lost_note.miss = 3
        stage._launch("com.x", None, 0, None)
        reader.app_stop.assert_called_once_with("com.x")
        reader.shell.assert_called_once_with(
            "monkey -p com.x -c android.intent.category.LAUNCHER 1")
        self.assertEqual(stage.lost_note.miss, 0)

    def test_a_launch_with_an_activity_quotes_the_component(self):
        stage, _, reader = launch_stage()
        stage._launch("com.x", "A$B", 0, None)
        reader.shell.assert_called_once_with("am start -f 0x10008000 -n 'com.x/A$B'")

    def error_launch(self, main, pm=""):
        stage, screen, reader = launch_stage(shell=shell_by_command(main, pm))
        return stage

    def test_a_client_error_is_reported_as_device_lost(self):
        stage = self.error_launch(shell_result("error: no devices", 1))
        with patch.object(adb_link, "detached", side_effect=lambda serial: False), \
                self.assertRaises(adb_link.DeviceLost) as caught:
            stage._launch("com.x", None, 0, None)
        self.assertIn("error: no devices", str(caught.exception))

    def test_a_library_error_is_reported_as_device_lost(self):
        stage = self.error_launch(shell_result("device 'S' not found", 1))
        with patch.object(adb_link, "detached", side_effect=lambda serial: False), \
                self.assertRaises(adb_link.DeviceLost):
            stage._launch("com.x", None, 0, None)

    def test_a_detached_serial_is_reported_as_device_lost(self):
        stage = self.error_launch(shell_result("boom", 1))
        with patch.object(adb_link, "detached", side_effect=lambda serial: serial == "S"), \
                self.assertRaises(adb_link.DeviceLost):
            stage._launch("com.x", None, 0, None)

    def test_the_package_probe_output_also_names_the_disconnect(self):
        """启动命令自己没给输出时，`pm path` 那句原始错误要进报错。"""
        stage = self.error_launch(shell_result("", 1), pm="device offline")
        with patch.object(adb_link, "detached", side_effect=lambda serial: False), \
                self.assertRaises(adb_link.DeviceLost) as caught:
            stage._launch("com.x", None, 0, None)
        self.assertIn("device offline", str(caught.exception))

    def test_a_missing_package_is_a_skip_not_a_failure(self):
        stage = self.error_launch(shell_result("boom", 1))
        with patch.object(adb_link, "detached", side_effect=lambda serial: False), \
                self.assertRaises(recipe_kit.MissingPackage):
            stage._launch("com.x", None, 0, None)

    def test_any_other_launch_failure_keeps_the_last_two_hundred_fifty_chars(self):
        output = "x" * 300
        stage = self.error_launch(shell_result(output, 1), pm="package:/data/app/x")
        with patch.object(adb_link, "detached", side_effect=lambda serial: False), \
                self.assertRaises(RuntimeError) as caught:
            stage._launch("com.x", None, 0, None)
        self.assertEqual(str(caught.exception), f"无法打开 com.x：{output.strip()[-250:]}")


class LaunchBudgetTests(unittest.TestCase):
    """等前台的预算只计「确知不是它」的时间；空焦点顺延到硬上限。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def stage(self, focus):
        stage, _, reader = launch_stage(focus=focus)
        return stage

    def test_known_foreign_frames_spend_the_launch_budget(self):
        stage = self.stage(lambda: "com.other/.A")
        with self.assertRaisesRegex(RuntimeError, "没有进入前台"):
            stage._launch("com.x", None, 0, None)
        self.assertGreater(self.clock.t, 4.5)          # 只计「确知是别的 App」的帧
        self.assertLess(self.clock.t, 5.5)

    def test_the_launch_wait_boundary_is_reached_exactly(self):
        """5 秒整就停：假钟给精确的 0.25 秒步长，边界差一要多读一帧。"""
        focus = Mock(return_value="com.other/.A")
        stage = self.stage(focus)
        clock = scripted_time([0.0] + [0.25 * i for i in range(1, 60)])
        with patch.object(launcher_module, "time", clock), \
                self.assertRaises(RuntimeError):
            stage._launch("com.x", None, 0, None)
        self.assertEqual(focus.call_count, 40)   # 每个循环读两次焦点

    def test_unreadable_focus_defers_to_the_hard_stop(self):
        focus = Mock(return_value="")
        stage = self.stage(focus)
        clock = scripted_time([0.0] + [0.25 * i for i in range(1, 60)])
        with patch.object(launcher_module, "time", clock), \
                self.assertRaisesRegex(RuntimeError, "没有进入前台"):
            stage._launch("com.x", None, 0, None)
        self.assertEqual(focus.call_count, 64)       # 正好 8.0 秒：32 轮，每轮读两次

    def unpacked(self, inside):
        """焦点读两次一轮（条件一次、循环体一次）：条件那次给固定外来包，循环体按给定序列。"""
        state = {"n": 0}
        it = iter(inside)

        def focus():
            state["n"] += 1
            if state["n"] % 2:
                return "com.z/.Z"
            return next(it, inside[-1])
        return focus

    def test_alternating_foreign_apps_never_add_up_to_a_seizer(self):
        stage = self.stage(self.unpacked(["com.a/.A", "com.b/.B"] * 40))
        with self.assertRaises(RuntimeError) as caught:
            stage._launch("com.x", None, 0, None)
        self.assertNotIn("抢了前台", str(caught.exception))

    def test_sustained_foreign_frames_count_from_one(self):
        stage = self.stage(lambda: "com.a/.A")
        with self.assertRaises(RuntimeError) as caught:
            stage._launch("com.x", None, 0, None)
        self.assertIn("连续 26 帧", str(caught.exception))

    def test_a_blank_read_between_two_runs_splits_the_frame_count(self):
        """读空只打断当前连读：同一包再连占的帧数从新算，不把读空前后的帧加在一起。"""
        stage = self.stage(self.unpacked(["com.a/.A", "com.a/.A", "", "com.a/.A"]))
        with self.assertRaises(RuntimeError) as caught:
            stage._launch("com.x", None, 0, None)
        self.assertIn("连续 24 帧", str(caught.exception))   # 空白那一帧不计，之后读到预算耗尽

    def test_the_page_hard_stop_boundary_is_reached_exactly(self):
        """读不到字的那 8 秒上限：正好 8.0 秒就放弃。"""
        stage, screen, _ = launch_stage(texts=(), focus=lambda: "com.x/.A")
        clock = scripted_time([0.0] + [0.25 * i for i in range(1, 60)], axis="time")
        with patch.object(launcher_module, "time", clock), \
                self.assertRaisesRegex(RuntimeError, "8 秒仍读不到页面"):
            stage._launch("com.x", None, 0, None)
        self.assertEqual(stage.dismiss.call_count, 31)


class LandingNoteTests(unittest.TestCase):
    """落点不对时的现场：命中哪些判据词、缺哪些、页面结构摘要。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_the_note_lists_the_hits_the_misses_and_the_structure(self):
        stage, screen, _ = launch_stage(texts=("首页",))
        self.assertEqual(
            stage._landing_note(["首页", "我的", "设置"]),
            "  · 启动后没落在预期页面：停在 com.x/.A；期望看到「首页、我的、设置」，"
            "没看到「我的、设置」；标题：X")

    def test_a_single_criterion_is_not_split_into_characters(self):
        stage, screen, _ = launch_stage(texts=("首页",))
        self.assertIn("期望看到「我的」", stage._landing_note("我的"))

    def test_a_broken_dump_still_yields_a_note(self):
        stage, screen, _ = launch_stage()
        screen.texts = Mock(side_effect=ET.ParseError)
        note = stage._landing_note(["我的"])          # 半截 dump 当作什么都没命中，不抛
        self.assertIn("期望看到「我的」", note)
        self.assertIn("没看到「我的」", note)

    def test_the_evidence_names_the_seizer_only_after_the_streak(self):
        stage, screen, _ = launch_stage()
        screen._page_diagnosis = Mock(return_value=("com.x/.A", "标题：X"))
        self.assertIn("被 com.b/.B 抢了前台，连续 3 帧",
                      stage._launch_evidence("com.b/.B", 3))
        self.assertNotIn("抢了前台", stage._launch_evidence("com.b/.B", 2))


class StartRecoveryTests(unittest.TestCase):
    """`start()` 的落点恢复：退一次、重新拉起一次、仍不对才停段。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def stage(self, focus, texts=("首页",)):
        stage, screen, _ = launch_stage(focus=focus, texts=texts)
        stage._launch = Mock()
        stage.expect_page = Mock()
        return stage, screen

    def test_the_defaults_go_to_the_launch_and_to_the_landing_check(self):
        stage, screen = self.stage(lambda: "com.x/.A")
        stage.expect_page.side_effect = [False, True]
        stage.start("com.x", expect=("首页",))
        stage._launch.assert_called_once_with("com.x", None, 1.2, None)
        self.assertEqual(stage.expect_page.call_args_list, [call(("首页",), 6.0), call(("首页",), 6.0)])
        self.assertEqual(screen.say.call_args.args[0],
                         "  · 退出非预期页面重进后，已落在 com.x 的预期页面")

    def test_a_landing_in_another_app_relaunches_with_the_same_arguments(self):
        focuses = iter(["com.other/.A", "com.x/.A"])
        stage, screen = self.stage(lambda: next(focuses, "com.x/.A"))
        stage.expect_page.side_effect = [False, True]
        stage.start("com.x", activity="A.B", settle=3.3, foreground="fg", expect=("首页",))
        self.assertEqual(stage._launch.call_args_list,
                         [call("com.x", "A.B", 3.3, "fg"), call("com.x", "A.B", 3.3, "fg")])

    def test_a_promo_page_is_left_and_the_app_is_relaunched_only_when_back_leaves_it(self):
        focuses = iter(["com.x/.A", "com.other/.A", "com.x/.A"])
        stage, screen = self.stage(lambda: next(focuses, "com.x/.A"))
        stage.expect_page.side_effect = [False, True]
        stage.start("com.x", activity="A.B", settle=1.2, foreground="com.x", expect=("首页",))
        screen.back.assert_called_once()
        self.assertEqual(stage._launch.call_args_list,
                         [call("com.x", "A.B", 1.2, "com.x"), call("com.x", "A.B", 1.2, "com.x")])
        self.assertAlmostEqual(self.clock.t, 0.8)

    def test_back_that_stays_in_the_app_needs_no_relaunch(self):
        stage, screen = self.stage(lambda: "com.x/.A")
        stage.expect_page.side_effect = [False, True]
        stage.start("com.x", activity="A.B", settle=1.2, foreground="com.x", expect=("首页",))
        screen.back.assert_called_once()
        self.assertEqual(stage._launch.call_count, 1)

    def test_back_into_an_unreadable_foreground_needs_no_relaunch(self):
        focuses = iter(["com.x/.A", "", "com.x/.A"])
        stage, screen = self.stage(lambda: next(focuses, "com.x/.A"))
        stage.expect_page.side_effect = [False, True]
        stage.start("com.x", activity="A.B", settle=1.2, foreground="com.x", expect=("首页",))
        self.assertEqual(stage._launch.call_count, 1)

    def test_a_landing_that_never_recovers_stops_the_step(self):
        stage, screen = self.stage(lambda: "com.x/.A")
        stage.expect_page.return_value = False
        with self.assertRaisesRegex(RuntimeError, "非预期页面"):
            stage.start("com.x", expect=("首页",))
        self.assertEqual(screen.say.call_count, 2)


class ExpectPageTests(unittest.TestCase):
    """等落点：默认预算、断线上抛、判据词全中才算数。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_a_page_that_never_shows_the_words_times_out_at_the_default_budget(self):
        stage, screen, _ = launch_stage(texts=("别的",))
        self.assertFalse(stage.expect_page("我的"))
        self.assertEqual(screen.texts.call_count, 20)
        self.assertAlmostEqual(self.clock.t, 4.0)

    def test_a_single_word_is_not_split_into_characters(self):
        stage, screen, _ = launch_stage(texts=("我的",))
        self.assertTrue(stage.expect_page("我的"))

    def test_every_word_is_needed(self):
        stage, screen, _ = launch_stage(texts=("我的",))
        self.assertFalse(stage.expect_page(("我的", "设置")))
        self.assertEqual(screen.texts.call_count, 20)

    def test_a_confirmed_disconnect_is_raised_not_swallowed(self):
        stage, screen, reader = launch_stage(texts=("别的",))
        stage.conn.check_alive = Mock(side_effect=adb_link.DeviceLost("掉线了"))
        with self.assertRaises(adb_link.DeviceLost):
            stage.expect_page("我的")




class ForeignStreakTests(unittest.TestCase):
    """启动后连续读到别的 App 才停段：帧数怎么数、什么时候停。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def run_stage(self, inside, texts=("首页",), settle=0):
        screen_state = {"started": False}
        it = iter(inside)

        def focus():
            if not screen_state["started"]:      # 第一段只看一次就承认进了前台
                screen_state["started"] = True
                return "com.x/.A"
            return next(it, inside[-1])

        stage, screen, _ = launch_stage(focus=focus, texts=texts)
        try:
            stage._launch("com.x", None, settle, None)
        except RuntimeError as error:
            return stage, screen, str(error)
        return stage, screen, None

    def test_a_blank_read_resets_the_streak(self):
        stage, screen, message = self.run_stage(
            ["com.a/.A", "com.a/.A", "", "com.a/.A", "com.a/.A", "com.x/.A"])
        self.assertIsNone(message)                    # 读空把连读清零，后两帧不足以停段

    def test_a_blank_read_splits_the_frame_count(self):
        stage, screen, message = self.run_stage(
            ["com.a/.A", "com.a/.A", "", "com.a/.A", "com.a/.A", "com.a/.A"])
        self.assertIn("连续 3 帧", message)

    def test_the_target_package_resets_the_streak(self):
        stage, screen, message = self.run_stage(
            ["com.a/.A", "com.a/.A", "com.x/.A", "com.a/.A", "com.a/.A", "com.a/.A"])
        self.assertIn("连续 3 帧", message)

    def test_a_blank_foreground_is_never_confirmed(self):
        stage, screen, message = self.run_stage([""] * 60 + ["com.a/.A"] * 60)
        self.assertIn("8 秒仍读不到页面", message)

    def test_the_last_reads_are_checked_before_success(self):
        """settle 收尾后至少再读一次：最后一拍被抢也要停段。"""
        stage, screen, message = self.run_stage(
            ["com.x/.A", "com.a/.A", "com.a/.A", "com.a/.A"])
        self.assertIn("连续 3 帧", message)
        self.assertAlmostEqual(self.clock.t, 0.4)      # 两拍等待之后第三拍才停

    def test_a_permission_page_is_waited_on_then_stops_the_step(self):
        state = {"started": False}

        def focus():
            if not state["started"]:
                state["started"] = True
                return "com.x/.A"
            return "com.android.permissioncontroller/.G"

        stage, screen, _ = launch_stage(focus=focus)
        stage.dismiss = Mock(return_value=True)
        with self.assertRaisesRegex(RuntimeError, "离开前台"):
            stage._launch("com.x", None, 0, None)
        self.assertAlmostEqual(self.clock.t, 3.0)

    def test_the_permission_deadline_is_reached_exactly(self):
        state = {"started": False}

        def focus():
            if not state["started"]:
                state["started"] = True
                return "com.x/.A"
            return "com.android.permissioncontroller/.G"

        stage, screen, _ = launch_stage(focus=focus)
        stage.dismiss = Mock(return_value=True)
        clock = scripted_time([0.0] + [0.25 * i for i in range(1, 40)])
        with patch.object(launcher_module, "time", clock), \
                self.assertRaises(RuntimeError):
            stage._launch("com.x", None, 0, None)
        self.assertEqual(stage.dismiss.call_count, 11)   # 0.25 秒一拍，正好 3.0 秒放弃

    def test_the_settle_loop_closes_popups_every_four_tenths(self):
        stage, screen, _ = launch_stage(focus=lambda: "com.x/.A")
        stage._launch("com.x", None, 1.2, None)
        self.assertEqual(stage.dismiss.call_count, 3)
        self.assertAlmostEqual(self.clock.t, 1.2)

    def test_the_blank_page_hard_stop_is_reached_exactly(self):
        stage, screen, _ = launch_stage(focus=lambda: "com.x/.A", texts=())
        with self.assertRaisesRegex(RuntimeError, "8 秒仍读不到页面"):
            stage._launch("com.x", None, 0, None)
        self.assertAlmostEqual(self.clock.t, 8.0)


if __name__ == "__main__":
    unittest.main()
