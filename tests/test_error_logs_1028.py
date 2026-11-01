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

from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
import fast
from fixtures import job_stub, phone_stub
import run


def out(text):
    return types.SimpleNamespace(output=text)


SHADE = "  mCurrentFocus=Window{2b4c1f0 u0 NotificationShade}\n"
SETTINGS = "  mCurrentFocus=Window{91aa u0 com.android.settings/com.android.settings.SubSettings}\n"


class KeyguardTests(unittest.TestCase):
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
        p = phone_stub("test", d=Mock())
        p.d.shell.side_effect = [out(SHADE + "      mIsShowing=false\n"), out(""),
                                 out(SETTINGS + "      mIsShowing=false\n")]
        with patch.object(fast.time, "sleep"):
            self.assertFalse(p.locked())
        self.assertEqual(p.d.shell.call_args_list[1].args[0], "cmd statusbar collapse")

    def test_engine_lock_screen_stays_locked_after_collapse(self):
        p = phone_stub("test", d=Mock())
        p.d.shell.side_effect = [out(SHADE), out(""), out(SHADE)]
        with patch.object(fast.time, "sleep"):
            self.assertTrue(p.locked())

    def test_run_py_uses_the_same_rule(self):
        with patch.object(run, "sh", return_value=SHADE):
            self.assertTrue(run.locked("test"))
        with patch.object(run, "sh", return_value=SETTINGS):
            self.assertFalse(run.locked("test"))


class WaitUnlockedTests(unittest.TestCase):
    def phone(self, states):
        p = phone_stub("test", d=Mock())
        p.locked = Mock(side_effect=states)
        return p

    def test_waits_for_owner_to_unlock(self):
        p = self.phone([True, True, False])
        with patch.object(fast.time, "sleep"), contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertTrue(p.wait_unlocked())
        self.assertEqual(p.d.shell.call_args_list[0].args[0], "input keyevent KEYCODE_WAKEUP")
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
    def test_trailing_brace_is_not_part_of_the_activity(self):
        # vivo OriginOS 3 / Android 13：焦点行以「Activity}}」结尾，以前取到「…Activity}」，渠道页全部认不出
        p = phone_stub("test", d=Mock())
        name = "com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification.settings.channels.NotificationSettingsActivity"
        p.d.shell.return_value = out(f"  mCurrentFocus=Window{{4c2 u0 {name}}}}}\n")
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
    def test_system_locked_channel_is_not_a_failure(self):
        # 23 份报告：只剩一个系统锁定（开关是灰的）的渠道开着，整步被标成失败
        after = {k: (v[0], 0, False) for k, v in DATA.items()}
        after[("com.b", "news")] = ("资讯推送", 3, False)
        code, printed, _, _ = run_off([OK, chan.Outcome(chan.GREYED), OK], data=after)
        self.assertEqual(code, 0)
        self.assertIn("系统锁定", printed)
        self.assertNotIn("仍开着：", printed)
        self.assertIn("营销渠道仍开着: 0 个", printed)

    def test_ocr_and_transfer_channels_are_not_marketing(self):
        for name in ("内容提取", "内容已传输", "已共享列表活动", "正在进行的活动的最新动态"):
            self.assertTrue(chan.classify(name).scan_excluded, name)
        self.assertFalse(chan.classify("内容与营销").scan_excluded)


class DisconnectTests(unittest.TestCase):
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
        with patch.object(fast, "connect", side_effect=push), patch.object(adb_link, "present", return_value=False):
            with self.assertRaises(adb_link.DeviceLost):
                fast.Phone("test", log=False)
        with patch.object(fast, "connect", side_effect=push), patch.object(adb_link, "present", return_value=True):
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
    focus = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"

    def phone(self):
        p = phone_stub("test", d=Mock())
        p.W, p.H = 1080, 2340
        p.locked = Mock(return_value=False)
        p.focus = Mock(return_value=self.focus)
        p.click = Mock()
        p.settle = Mock(return_value=False)
        p.sig = Mock(return_value="")
        p.scroll_more = Mock(return_value=False)
        p.tree = Mock(return_value=ET.fromstring(LISTVIEW_APP_PAGE))
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
    def test_reference_does_not_change_when_community_recipes_are_added(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("xiaomi-24090RA29C", "xiaomi-M154FF", "vivo-V2324HA", "vivo-V2547DA"):
                Path(root, "recipes", name).mkdir(parents=True)
                Path(root, "recipes", name, "recipe.py").write_text('BUILD = "x"\n', encoding="utf-8")
            with patch.object(run, "ROOT", root):
                path, reference = run.recipe_for("NEWMODEL1", "Redmi")
                self.assertTrue(reference)
                self.assertEqual(Path(path).parent.name, "xiaomi-M154FF")
                self.assertEqual(Path(run.recipe_for("NEWMODEL2", "iQOO")[0]).parent.name, "vivo-V2547DA")
                self.assertEqual(run.recipe_for("24090RA29C", "Redmi"), (str(Path(root, "recipes", "xiaomi-24090RA29C", "recipe.py")), False))


class ScrubTests(unittest.TestCase):
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
            api = self.app.Api(directory)
            api.job = job_stub()
            failed = Mock(stdout=io.StringIO('#aac:event {"kind": "link_lost"}\n' + adb_link.HINT + "\n")); failed.wait.return_value = 1
            with patch.object(self.app.subprocess, "Popen", side_effect=[failed]) as popen, \
                 patch.object(self.app, "adb_present", return_value=False):
                api._work([self.app.Task("关闭营销通知", "run.py", ["-s", "test", "x"]),
                           self.app.Task("关闭快应用", "run.py", ["-s", "test", "quickapp", "off"]),
                           self.app.Task("收尾", "run.py", ["-s", "test", "finish"])])
            self.assertEqual(popen.call_count, 1)
            self.assertEqual([r.get("skipped", False) for r in api.job.results], [False, True, True])
            self.assertEqual("\n".join(api.job.lines).count("adb 连接断开了"), 1)


if __name__ == "__main__":
    unittest.main()
