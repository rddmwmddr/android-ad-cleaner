"""2026-10-28 错误日志回归：0.2.5 上线后用户确认上报的 122 份日志归类出的问题。
不用手机，模拟 dumpsys 输出、页面与系统回读。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import adbutils
import uiautomator2 as u2

from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
import fast
from phone import connection as phone_connection
from fixtures import Clock, FakeProc, FakeRunner, job_stub, phone_stub
import run


def out(text):
    return types.SimpleNamespace(output=text)


SHADE = "  mCurrentFocus=Window{2b4c1f0 u0 NotificationShade}\n"
SETTINGS = "  mCurrentFocus=Window{91aa u0 com.android.settings/com.android.settings.SubSettings}\n"


class KeyguardTests(unittest.TestCase):
    DOMAIN = "device_state"
    def test_coloros_lock_screen_without_keyguard_fields(self):
        # ColorOS 16/17：没有 isKeyguardShowing，锁屏时焦点是 NotificationShade（9 份报告「停在 NotificationShade」）
        self.assertTrue(adb_link.keyguard_showing(SHADE))
        self.assertTrue(adb_link.keyguard_showing(SHADE + "      mIsShowing=true\n"))

    def test_pulled_down_shade_with_explicit_unlocked_fields_is_not_a_lock(self):
        self.assertFalse(adb_link.keyguard_showing(SHADE + "    isKeyguardShowing=false mKeyguardOccluded=true\n"))
        self.assertFalse(adb_link.keyguard_showing(SHADE + "      mIsShowing=false\n"))

    def test_app_in_front_is_not_a_lock(self):
        self.assertFalse(adb_link.keyguard_showing(SETTINGS))
        self.assertFalse(adb_link.keyguard_showing(SETTINGS + "    isKeyguardShowing=false mKeyguardOccluded=true\n"))

    def test_keyguard_fields_still_count(self):
        self.assertTrue(adb_link.keyguard_showing(SETTINGS + "    isKeyguardShowing=true\n"))
        self.assertTrue(adb_link.keyguard_showing("    mDreamingLockscreen=true\n"))

    def test_engine_collapses_shade_when_not_locked(self):
        p = phone_stub("test", reader=Mock())
        p.conn.reader.shell.side_effect = [out(SHADE + "      mIsShowing=false\n"), out(""),
                                 out(SETTINGS + "      mIsShowing=false\n")]
        with patch.object(fast.time, "sleep"):
            self.assertFalse(p.locked())
        self.assertEqual(p.conn.reader.shell.call_args_list[1].args[0], "cmd statusbar collapse")

    def test_engine_lock_screen_stays_locked_after_collapse(self):
        p = phone_stub("test", reader=Mock())
        p.conn.reader.shell.side_effect = [out(SHADE), out(""), out(SHADE)]
        with patch.object(fast.time, "sleep"):
            self.assertTrue(p.locked())

    def test_run_py_uses_the_same_rule(self):
        with patch.object(run, "sh", return_value=SHADE):
            self.assertTrue(run.locked("test"))
        with patch.object(run, "sh", return_value=SETTINGS):
            self.assertFalse(run.locked("test"))


class WaitUnlockedTests(unittest.TestCase):
    DOMAIN = "device_state"
    def phone(self, states):
        p = phone_stub("test", reader=Mock())
        p.conn.locked = Mock(side_effect=states)      # 锁屏判定归连接基座（ADR-0033）
        return p

    def test_waits_for_owner_to_unlock(self):
        p = self.phone([True, True, False])
        with patch.object(fast.time, "sleep"), contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertTrue(p.wait_unlocked())
        self.assertEqual(p.conn.reader.shell.call_args_list[0].args[0], "input keyevent KEYCODE_WAKEUP")
        self.assertIn("解锁后自动继续", printed.getvalue())

    def test_gives_up_after_timeout(self):
        p = self.phone(lambda: True)
        clock = iter(range(0, 1000, 30))
        with patch.object(fast.time, "sleep"), patch.object(fast.time, "time", side_effect=lambda: next(clock)), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(p.wait_unlocked(timeout=90))

    def test_unlocked_phone_is_not_delayed(self):
        p = self.phone([False])
        with patch.object(fast.time, "sleep") as sleep:
            self.assertTrue(p.wait_unlocked())
        sleep.assert_not_called()


class FocusTests(unittest.TestCase):
    DOMAIN = "device_state"
    def test_trailing_brace_is_not_part_of_the_activity(self):
        # vivo OriginOS 3 / Android 13：焦点行以「Activity}}」结尾，以前取到「…Activity}」，渠道页全部认不出
        p = phone_stub("test", reader=Mock())
        name = "com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification.settings.channels.NotificationSettingsActivity"
        p.conn.reader.shell.return_value = out(f"  mCurrentFocus=Window{{4c2 u0 {name}}}}}\n")
        self.assertEqual(p.focus(), name)
        self.assertEqual(adb_link.focus_window(f"mCurrentFocus=Window{{4c2 u0 {name}}}}}"), name)


ITEMS = [("com.a", "promo", "营销通知"), ("com.b", "news", "资讯推送"), ("com.c", "deal", "优惠活动")]
DATA = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS}
OK = chan.Outcome(chan.DONE)


def run_off(toggle, phone=None, data=None):
    phone = phone or Mock(wait_unlocked=Mock(return_value=True), lost=False)
    reads = [(DATA, {}), (data or DATA, {})]
    with patch.object(chan, "load", return_value=ITEMS), patch.object(chan, "parse", side_effect=reads), \
         patch.object(chan, "Phone", return_value=phone), patch.object(chan, "keep_awake", return_value=None), \
         patch.object(chan, "toggle", side_effect=toggle) as toggled, \
         patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", "x.tsv"]), \
         contextlib.redirect_stdout(io.StringIO()) as printed:
        try:
            chan.main()
            code = 0
        except SystemExit as e:
            code = e.code
    return code, printed.getvalue(), toggled, phone


class LockedBatchTests(unittest.TestCase):
    DOMAIN = "device_state"
    def test_locked_at_start_reports_once_and_touches_nothing(self):
        # 约 15 份报告：开始执行时手机已锁屏，以前每个渠道都打一行「手机锁屏了」
        phone = Mock(wait_unlocked=Mock(return_value=False), lost=False)
        code, printed, toggled, _ = run_off(None, phone)
        self.assertEqual(code, 1)
        toggled.assert_not_called()
        self.assertEqual(printed.count("锁屏"), 1)

    def test_lock_midway_waits_then_retries_the_same_channel(self):
        phone = Mock(wait_unlocked=Mock(return_value=True), lost=False)
        code, printed, toggled, _ = run_off([OK, chan.ScreenLocked("手机锁屏了"), OK, OK],
                                           phone, {k: (v[0], 0, False) for k, v in DATA.items()})
        self.assertEqual(code, 0)
        self.assertEqual(toggled.call_count, 4)
        self.assertEqual([c.args[2] for c in toggled.call_args_list], ["promo", "news", "news", "deal"])

    def test_lock_that_stays_stops_the_batch_with_one_line(self):
        phone = Mock(lost=False)
        phone.wait_unlocked.side_effect = [True, False]
        code, printed, toggled, _ = run_off([OK, chan.ScreenLocked("手机锁屏了")], phone)
        self.assertEqual(code, 1)
        self.assertEqual(toggled.call_count, 2)
        self.assertIn("剩下 2 项没有处理", printed)
        self.assertEqual(printed.count("锁屏"), 1)


class GreyedChannelTests(unittest.TestCase):
    DOMAIN = "device_state"
    def test_system_locked_channel_is_not_a_failure(self):
        # 23 份报告：只剩一个系统锁定（开关是灰的）的渠道开着，整步被标成失败
        after = {k: (v[0], 0, False) for k, v in DATA.items()}
        after[("com.b", "news")] = ("资讯推送", 3, False)
        code, printed, _, _ = run_off([OK, chan.Outcome(chan.GREYED), OK], data=after)
        self.assertEqual(code, 0)
        self.assertIn("系统锁定", printed)
        self.assertNotIn("仍开着：", printed)
        self.assertIn("营销渠道仍开着: 0 个", printed)


class NonMarketingChannelTests(unittest.TestCase):
    DOMAIN = "channel"
    def test_ocr_and_transfer_channels_are_not_marketing(self):
        for name in ("内容提取", "内容已传输", "已共享列表活动", "正在进行的活动的最新动态"):
            self.assertTrue(chan.classify(name).scan_excluded, name)
        self.assertFalse(chan.classify("内容与营销").scan_excluded)


class DisconnectTests(unittest.TestCase):
    DOMAIN = "connection"
    def test_lost_device_is_reported_once_without_traceback(self):
        code, printed, toggled, _ = run_off([OK, adb_link.lost("adb.exe: device 'x' not found")])
        self.assertEqual(code, 1)
        self.assertEqual(printed.count("adb 连接断开了"), 1)
        self.assertNotIn("Traceback", printed)

    def test_lost_while_reading_channels_exits_with_hint(self):
        with patch.object(chan, "load", return_value=ITEMS), \
             patch.object(chan, "parse", side_effect=adb_link.lost("device 'x' not found")), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", "x.tsv"]):
            with self.assertRaises(SystemExit) as stop:
                chan.main()
        self.assertIn("adb 连接断开了", str(stop.exception.code))

    def test_windows_program_name_variants(self):
        self.assertTrue(adb_link.client_gone("adb.: device 'x' not found"))
        self.assertTrue(adb_link.client_gone("adb.EXE: device offline"))

    def test_empty_shell_reply_waits_for_device_then_retries(self):
        shell = Mock(side_effect=[fast.u2.exceptions.AdbShellError("shell output invalid", "getprop x", b""), out("ok")])
        p = phone_stub("test", shell=fast._shell_transport(shell))
        with patch.object(adb_link, "wait_for", return_value=True):
            self.assertEqual(p._resilient_shell("getprop x").output, "ok")

    def test_failed_service_push_maps_to_disconnect_or_clear_message(self):
        push = fast.adbutils.AdbError("FAIL")
        with patch.object(phone_connection, "connect", side_effect=push), patch.object(adb_link, "present", return_value=False):
            with self.assertRaises(adb_link.DeviceLost):
                fast.Phone("test", log=False)
        with patch.object(phone_connection, "connect", side_effect=push), patch.object(adb_link, "present", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "读屏服务没能装到手机上"):
                fast.Phone("test", log=False)


LISTVIEW_APP_PAGE = '''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node text="通知管理" bounds="[60,100][600,200]"/>
  <node class="android.widget.ListView" scrollable="true" clickable="false" bounds="[0,300][1080,2200]">
    <node class="android.widget.LinearLayout" clickable="false" bounds="[0,600][1080,760]">
      <node text="订单通知" bounds="[60,630][700,700]"/>
    </node>
    <node class="android.widget.LinearLayout" clickable="false" bounds="[0,760][1080,920]">
      <node text="营销通知" bounds="[60,790][700,860]"/>
    </node>
  </node>
</node></hierarchy>'''


class ListRowTests(unittest.TestCase):
    DOMAIN = "switch"
    focus = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"

    def phone(self):
        p = phone_stub("test", reader=Mock())
        p.W, p.H = 1080, 2340
        p.locked = Mock(return_value=False)
        p.screen.focus = Mock(return_value=self.focus)
        p.click = p.screen.click = Mock()      # 到达决策经 apply() 落到观测基座
        p.screen.settle = Mock(return_value=False)
        p.screen.sig = Mock(return_value="")
        p.scroll_more = Mock(return_value=False)
        p.screen.tree = Mock(return_value=ET.fromstring(LISTVIEW_APP_PAGE))
        return p

    def test_listview_rows_without_clickable_flag_are_found(self):
        # 华为 HarmonyOS 4：应用通知页的渠道行不可点（ListView 处理点击），以前找不到行就放弃
        p = self.phone()
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.example", "营销通知", at))
        p.click.assert_called_once_with(380, 825)
        self.assertEqual(at.stage, "点这一行后页面没变")

    def test_skip_message_says_where_it_failed(self):
        p = self.phone()
        p.confirm = Mock()
        with patch.object(chan, "parse", return_value=({("com.example", "promo"): ("营销通知", 3, False)}, {})), \
             patch.object(chan.time, "sleep"):
            message = chan.toggle(p, "com.example", "promo", False, "营销通知").detail
        self.assertIn("停在 " + self.focus, message)
        self.assertIn("点这一行后页面没变", message)
        self.assertIn("标题列表，允许通知开关 0 个", message)


class ReferenceRecipeTests(unittest.TestCase):
    DOMAIN = "startup"
    def test_reference_does_not_change_when_community_recipes_are_added(self):
        with tempfile.TemporaryDirectory() as root:
            for family, model in (("xiaomi", "24090RA29C"), ("xiaomi", "M154FF"),
                                  ("vivo", "V2324HA"), ("vivo", "V2547DA")):
                Path(root, "recipes", family, model).mkdir(parents=True)
                Path(root, "recipes", family, model, "recipe.py").write_text('BUILD = "x"\n', encoding="utf-8")
            path, reference = run.recipe_for("NEWMODEL1", "Redmi", root=root)
            self.assertTrue(reference)
            self.assertEqual(Path(path).parent.name, "M154FF")
            self.assertEqual(Path(run.recipe_for("NEWMODEL2", "iQOO", root=root)[0]).parent.name, "V2547DA")
            self.assertEqual(run.recipe_for("24090RA29C", "Redmi", root=root), (str(Path(root, "recipes", "xiaomi/24090RA29C", "recipe.py")), False))

    def test_reference_prefers_the_main_toml_over_a_version_variant(self):
        """主本优先于变体：`-android17` 这类变体按字母序排在 `.` 前面，取 `sorted()[0]` 会选错。

        选错时参考脚本变成 Android 17 变体，`same_version_family_recipe()` 的 `ref_core`
        跟着从 `16` 变成 `17.x`，同族候选的比较基准整个歪掉（#1263）。
        """
        with tempfile.TemporaryDirectory() as root:
            here = Path(root, "recipes", "vivo", "V2547DA")
            here.mkdir(parents=True)
            (here / "V2547DA.toml").write_text('build = "16"\n', encoding="utf-8")
            (here / "V2547DA-android17.toml").write_text('build = "17.1.10.2"\n', encoding="utf-8")
            path, reference = run.recipe_for("ZZZ0000", "iQOO", root=root)
        self.assertTrue(reference)
        self.assertEqual(Path(path).name, "V2547DA.toml")

    def test_new_brand_borrows_its_only_recipe_as_reference(self):
        """FAMILY 没登记的品牌，别的型号借不到同品牌脚本；三星进目录时踩过（#605）。"""
        with tempfile.TemporaryDirectory() as root:
            Path(root, "recipes", "samsung/SM-N9760").mkdir(parents=True)
            Path(root, "recipes", "samsung/SM-N9760", "recipe.py").write_text('BUILD = "x"\nMODELS = ["SM-N9760"]\n', encoding="utf-8")
            path, reference = run.recipe_for("SM-S9280", "samsung", root=root)
            self.assertTrue(reference)
            self.assertEqual(Path(path).parent.name, "SM-N9760")


class ScrubTests(unittest.TestCase):
    DOMAIN = "connection"

    @classmethod
    def setUpClass(cls):
        cls.app = app

    def test_user_folder_moved_to_another_drive(self):
        # 一份报告的路径是 E:\360MoveData\Users\<真名>\Desktop\…，两层脱敏都没盖住
        text = self.app.scrub(r'File "E:\360MoveData\Users\TestName\Desktop\AndroidAdCleaner\tool\chan_fast.py"')
        self.assertNotIn("TestName", text)
        self.assertIn(r"<用户目录>\Desktop", text)
        self.assertNotIn("TestName", self.app.scrub(r"C:\Users\TestName\AppData"))
        self.assertNotIn("TestName", self.app.scrub("/home/TestName/x"))

    def test_install_folder_and_huawei_version_are_kept(self):
        self.assertEqual(self.app.scrub(r"D:\AndroidAdCleaner\_internal\tool\fast.py"), r"D:\AndroidAdCleaner\_internal\tool\fast.py")
        self.assertEqual(self.app.scrub("NOH-AN00 4.2.0.180(C00E180R)"), "NOH-AN00 4.2.0.180(C00E180R)")
        self.assertEqual(self.app.scrub("adb connect 192.168.1.5:5555"), "adb connect <IP>")

    def test_disconnect_skips_remaining_steps_once(self):
        # 断线后快应用、挂起、收尾各打一遍同样的排查说明（约 20 份报告）
        with tempfile.TemporaryDirectory() as directory:
            api = self.app.Api(directory, runner=FakeRunner(
                spawns=[FakeProc('#aac:event {"kind": "link_lost"}\n' + adb_link.HINT + "\n", rc=1)]))
            api.job = job_stub()
            with patch.object(self.app, "adb_present", return_value=False):
                api._work([self.app.Task("关闭营销通知", "run.py", ["-s", "test", "x"]),
                           self.app.Task("关闭快应用", "run.py", ["-s", "test", "quickapp", "off"]),
                           self.app.Task("收尾", "run.py", ["-s", "test", "finish"], always_run=True)])
            self.assertEqual(len(api.runner.spawn_calls), 1)
            self.assertEqual([r.get("skipped", False) for r in api.job.results], [False, True, True])
            self.assertEqual("\n".join(api.job.lines).count("adb 连接断开了"), 1)


class Recorder(io.StringIO):
    """标准流替身：既收文本，也数 flush —— 连接层的提示必须当场推给客户端。"""

    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1


def reader_stub(shell_output=""):
    reader = Mock()
    reader.settings = {}
    reader.shell = Mock(return_value=out(shell_output))
    return reader


def make_connection(*, log=False, reader=None, serial="SER"):
    reader = reader or reader_stub(SETTINGS)
    with patch.object(phone_connection, "connect", return_value=reader):
        conn = phone_connection.Connection(serial, log=log)
    return conn, reader


class ConsoleRegressionTests(unittest.TestCase):
    DOMAIN = "connection"

    def test_the_banner_is_flushed_by_default(self):
        reader = reader_stub(SETTINGS)
        with contextlib.redirect_stdout(Recorder()) as printed, \
             patch.object(phone_connection, "connect", return_value=reader):
            conn = phone_connection.Connection("SER")
        self.assertEqual(printed.getvalue(), "正在连接手机读屏服务……\n")
        self.assertGreaterEqual(printed.flushes, 1)
        self.assertIs(conn.log, True)
        with contextlib.redirect_stdout(Recorder()) as said:
            conn.say("还要能说话")
        self.assertEqual(said.getvalue(), "还要能说话\n")

    def test_say_prints_and_flushes_what_it_is_given(self):
        conn, _ = make_connection()
        conn.log = True
        with contextlib.redirect_stdout(Recorder()) as printed:
            conn.say("第一行", "第二行")
        self.assertEqual(printed.getvalue(), "第一行 第二行\n")
        self.assertGreaterEqual(printed.flushes, 1)

    def test_say_is_silent_when_logging_is_off(self):
        conn, _ = make_connection(log=False)
        self.assertFalse(conn.log)

    def test_pause_point_prints_flushes_and_waits_for_the_file_to_go(self):
        with tempfile.NamedTemporaryFile() as handle, \
             patch.dict(os.environ, {"AAC_PAUSE_FILE": handle.name}), \
             patch.object(phone_connection, "time", Clock()) as clock, \
             patch.object(phone_connection.os.path, "exists",
                          side_effect=[True, True, False]), \
             contextlib.redirect_stdout(Recorder()) as printed:
            self.assertTrue(phone_connection.pause_point())
        self.assertIn("已暂停", printed.getvalue())
        self.assertIn("继续执行", printed.getvalue())
        self.assertGreaterEqual(printed.flushes, 2)
        self.assertEqual(clock.t, 0.5)

    def test_without_a_pause_file_nothing_happens(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AAC_PAUSE_FILE", None)
            self.assertFalse(phone_connection.pause_point())


class ShellTransportRegressionTests(unittest.TestCase):
    DOMAIN = "connection"

    def send(self, shell):
        return phone_connection._shell_transport(shell)

    def test_a_plain_call_keeps_the_command_only(self):
        calls = []
        self.send(lambda *a, **k: calls.append((a, k)))("ls")
        self.assertEqual(calls, [(("ls",), {})])

    def test_a_timeout_is_forwarded(self):
        calls = []
        self.send(lambda *a, **k: calls.append((a, k)))("ls", timeout=5)
        self.assertEqual(calls, [(("ls",), {"timeout": 5})])

    def test_a_dead_transport_becomes_link_broken(self):
        def dead(command):
            raise u2.exceptions.AdbShellError("shell output invalid: b''")
        with self.assertRaises(adb_link.LinkBroken):
            self.send(dead)("ls")

    def test_another_shell_error_is_not_a_disconnect(self):
        def broken(command):
            raise u2.exceptions.AdbShellError("permission denied")
        with self.assertRaises(u2.exceptions.AdbShellError):
            self.send(broken)("ls")

    def test_an_unrelated_error_is_raised_unchanged(self):
        def broken(command):
            raise ValueError("boom")
        with self.assertRaises(ValueError):
            self.send(broken)("ls")


class ReaderFailureRegressionTests(unittest.TestCase):
    DOMAIN = "connection"

    def test_a_gone_screen_is_not_blamed_on_the_reader_service(self):
        with patch.object(phone_connection.adb_link, "screen_gone", return_value=True):
            error = phone_connection.reader_failure("SER", OSError("no screen"))
        message = str(error)
        self.assertIn(adb_link.SCREEN_GONE_CONNECT, message)
        self.assertIn("OSError: no screen", message)

    def test_other_failures_point_at_the_accessibility_service(self):
        with patch.object(phone_connection.adb_link, "screen_gone", return_value=False), \
             patch.object(phone_connection, "accessibility_summary", return_value="检查结果"):
            error = phone_connection.reader_failure("SER", OSError("boom"))
        message = str(error)
        self.assertTrue(message.startswith("手机读屏服务（UiAutomation）启动失败，本次未点击开关。"))
        self.assertIn("检查结果", message)
        self.assertIn(phone_connection.UI_RECOVERY, message)
        self.assertIn("OSError: boom", message)


class ConnectionWiringRegressionTests(unittest.TestCase):
    DOMAIN = "connection"

    def test_the_reader_is_used_and_its_shell_is_wrapped(self):
        conn, reader = make_connection()
        self.assertIs(conn.reader, reader)
        self.assertEqual(conn.reader.shell, conn._resilient_shell)

    def test_the_link_keeps_the_serial_and_no_reader_retry(self):
        conn, _ = make_connection()
        self.assertEqual(conn.link.serial, "SER")
        self.assertIs(conn.link.lost_on_retry, False)

    def test_the_operation_delay_is_cleared_on_the_device(self):
        conn, reader = make_connection()
        self.assertEqual(reader.settings["operation_delay"], (0, 0))

    def test_pause_is_offered_between_segments(self):
        conn, _ = make_connection()
        self.assertTrue(conn.pause_at_lock_check)

    def test_the_connection_asks_for_the_serial(self):
        with patch.object(phone_connection, "connect", return_value=reader_stub()) as connect:
            phone_connection.Connection("SER", log=False)
        connect.assert_called_once_with("SER")

    def test_the_resilient_shell_forwards_every_argument(self):
        conn, _ = make_connection()
        conn.link.shell = Mock(return_value="ok")
        self.assertEqual(conn._resilient_shell("ls", timeout=5), "ok")
        conn.link.shell.assert_called_once_with("ls", timeout=5)

    def test_a_busy_reader_is_reported_with_recovery_steps(self):
        with patch.object(phone_connection, "connect",
                          side_effect=u2.exceptions.AccessibilityServiceAlreadyRegisteredError("first cause")), \
             patch.object(phone_connection, "accessibility_summary", return_value="检查结果") as summary:
            with self.assertRaises(RuntimeError) as caught:
                phone_connection.Connection("SER", log=False)
        self.assertEqual(str(caught.exception),
                         "UIAUTOMATION_BUSY：手机读屏服务已被占用，本次未点击开关。"
                         "已清理本次失败的启动并重试一次，仍无法连接。"
                         "请退出旧版客户端，只保留一个客户端。\n"
                         f"检查结果\n{phone_connection.UI_RECOVERY}\n"
                         "原始异常：AccessibilityServiceAlreadyRegisteredError: first cause")
        summary.assert_called_once_with("SER")

    def test_a_broken_reader_is_translated_for_the_serial(self):
        error = u2.exceptions.UiAutomationError("broken")
        with patch.object(phone_connection, "connect", side_effect=error), \
             patch.object(phone_connection, "reader_failure", return_value=RuntimeError("x")) as failure:
            with self.assertRaises(RuntimeError):
                phone_connection.Connection("SER", log=False)
        failure.assert_called_once_with("SER", error)

    def test_a_push_failure_with_the_phone_gone_is_a_disconnect(self):
        error = u2.exceptions.AdbShellError("FAIL: push")
        with patch.object(phone_connection, "connect", side_effect=error), \
             patch.object(phone_connection.adb_link, "present", return_value=False) as present:
            with self.assertRaises(adb_link.DeviceLost) as caught:
                phone_connection.Connection("SER", log=False)
        present.assert_called_once_with("SER")
        self.assertIn("AdbShellError: FAIL: push", str(caught.exception))

    def test_a_push_failure_with_the_phone_still_here_names_the_install(self):
        detail = "x" * 250
        error = adbutils.AdbError(detail)
        with patch.object(phone_connection, "connect", side_effect=error), \
             patch.object(phone_connection.adb_link, "present", return_value=True):
            with self.assertRaises(RuntimeError) as caught:
                phone_connection.Connection("SER", log=False)
        detail_expected = "AdbError: " + "x" * 200
        self.assertEqual(str(caught.exception),
                         phone_connection.UI_INSTALL_FAILED + "\n原始异常：" + detail_expected)


class CheckInputRegressionTests(unittest.TestCase):
    DOMAIN = "switch"

    def test_the_probe_sends_a_noop_key_and_translates_a_block(self):
        conn, reader = make_connection()
        reader.shell = Mock(return_value=out("blocked"))
        with patch.object(phone_connection, "input_blocked", return_value=True) as blocked:
            with self.assertRaises(RuntimeError) as caught:
                conn.check_input()
        reader.shell.assert_called_once_with("input keyevent 0")
        blocked.assert_called_once_with("blocked")
        self.assertIn("INPUT_BLOCKED", str(caught.exception))
        self.assertIn(phone_connection.TAPPED, str(caught.exception))
        self.assertIn(phone_connection.XIAOMI_INPUT, str(caught.exception))

    def test_an_allowed_probe_stays_quiet(self):
        conn, reader = make_connection()
        with patch.object(phone_connection, "input_blocked", return_value=False):
            conn.check_input()


class LockedProbeRegressionTests(unittest.TestCase):
    DOMAIN = "device_state"

    def test_the_keyguard_command_is_read(self):
        conn, reader = make_connection()
        conn.pause_at_lock_check = False
        reader.shell = Mock(return_value=out(SETTINGS))
        self.assertFalse(conn.locked())
        self.assertEqual(reader.shell.call_args.args, (adb_link.KEYGUARD_CMD,))

    def test_pause_is_only_asked_for_when_enabled(self):
        conn, reader = make_connection()
        conn.pause_at_lock_check = False
        reader.shell = Mock(return_value=out(SETTINGS))
        with patch.object(phone_connection, "pause_point") as pause:
            conn.locked()
        pause.assert_not_called()

    def test_a_real_lock_screen_is_not_collapsed(self):
        conn, reader = make_connection()
        conn.pause_at_lock_check = False
        reader.shell = Mock(return_value=out(SHADE + "    isKeyguardShowing=true\n"))
        with patch.object(phone_connection.time, "sleep"):
            self.assertTrue(conn.locked())
        self.assertNotIn("cmd statusbar collapse",
                         [c.args[0] for c in reader.shell.call_args_list])

    def test_the_collapse_waits_for_the_shade_to_go(self):
        conn, reader = make_connection()
        conn.pause_at_lock_check = False
        reader.shell = Mock(side_effect=[out(SHADE + "      mIsShowing=false\n"), out(""), out(SETTINGS)])
        clock = Clock()
        with patch.object(phone_connection, "time", clock):
            self.assertFalse(conn.locked())
        self.assertEqual(clock.t, 0.4)
        self.assertEqual([c.args[0] for c in reader.shell.call_args_list],
                         [adb_link.KEYGUARD_CMD, "cmd statusbar collapse", adb_link.KEYGUARD_CMD])

    def test_the_unlock_wait_passes_its_budget_and_clock(self):
        conn, reader = make_connection()
        conn.locked = Mock(return_value=True)
        clock = Clock()
        with patch.object(phone_connection.time, "time", clock.time), \
             patch.object(phone_connection.time, "sleep", clock.sleep), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(conn.wait_unlocked(timeout=1))
        self.assertEqual(clock.t, 1.0)


if __name__ == "__main__":
    unittest.main()
