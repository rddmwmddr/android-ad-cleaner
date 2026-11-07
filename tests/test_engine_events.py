"""引擎侧发事件（ADR-0004）：在语义发生地发一条，人话逐字不变。"""
import contextlib
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import events
import fast
import run
import wait
from fixtures import phone_stub

PAUSED = "⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」"
RESUMED = "▶ 继续执行"
LOCKED = "  ! 手机锁屏了：请解锁手机并保持亮屏，解锁后自动继续（最多等 90 秒）"


def capture(fn, on=True):
    """跑 fn，返回 (人话输出, 事件列表, 返回值)；事件行不算人话。"""
    out = io.StringIO()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AAC_EVENTS", None)
        if on:
            os.environ["AAC_EVENTS"] = "1"
        with contextlib.redirect_stdout(out):
            result = fn()
    lines = out.getvalue().splitlines()
    return ("\n".join(line for line in lines if not events.is_event(line)),
            [events.parse(line) for line in lines if events.is_event(line)], result)


class LinkLostTests(unittest.TestCase):
    def lost(self, on):
        return capture(lambda: str(adb_link.lost("adb: device 'x' not found")), on=on)

    def test_confirmed_disconnect_emits_exactly_one_event(self):
        human, sent, error = self.lost(on=True)
        self.assertEqual(sent, ["link_lost"])
        self.assertEqual(human, "")                     # 人话由调用方 sys.exit 打印，事件不添一行
        self.assertIn("adb 连接断开了", error)

    def test_the_message_is_byte_identical_without_events(self):
        self.assertEqual(self.lost(True)[2], self.lost(False)[2])

    def test_repeat_confirmation_also_reports_link_lost(self):
        # 旧的文案嗅探认不出 REPEAT（「…已断开…」），所以同一次任务里后续步骤不会被跳过
        conn = adb_link.Connection("test")
        conn.lost = True

        def call():
            with self.assertRaises(adb_link.DeviceLost) as caught:
                conn.check_alive()
            return str(caught.exception)
        human, sent, message = capture(call)
        self.assertEqual(sent, ["link_lost"])
        self.assertEqual(message, adb_link.REPEAT)
        self.assertEqual(human, "")


class PausePointTests(unittest.TestCase):
    def pause_point(self, on):
        def call():
            with tempfile.TemporaryDirectory() as d:
                path = Path(d, "pause")
                with patch.dict(fast.os.environ, {"AAC_PAUSE_FILE": str(path)}):
                    path.write_text("")
                    threading.Timer(0.05, path.unlink).start()
                    # 实现的轮询间隔是 0.5 秒：换成 0.01 秒，文件一删就退出，不真等满一轮。
                    # 真 sleep 先取出来 —— fast.time 就是 time 模块本身，直接调会递归回替身。
                    real_sleep = time.sleep
                    with patch.object(fast.time, "sleep", lambda seconds: real_sleep(0.01)):
                        return fast.pause_point()
        return capture(call, on=on)

    def test_reports_paused_then_resumed_around_the_wait(self):
        human, sent, result = self.pause_point(on=True)
        self.assertTrue(result)
        self.assertEqual(sent, ["paused", "resumed"])
        self.assertEqual(human, PAUSED + "\n" + RESUMED)

    def test_human_text_is_byte_identical_without_events(self):
        off, _, _ = self.pause_point(on=False)
        on, _, _ = self.pause_point(on=True)
        self.assertEqual(on, off)


class LockedTests(unittest.TestCase):
    def phone_wait(self, on):
        p = phone_stub("test", d=Mock())
        p.locked = Mock(side_effect=[True, False])
        with patch.object(fast.time, "sleep"):
            return capture(lambda: p.wait_unlocked(), on=on)

    def test_phone_reports_locked_while_waiting_for_the_owner(self):
        human, sent, result = self.phone_wait(on=True)
        self.assertTrue(result)
        self.assertEqual(sent, ["locked"])
        self.assertEqual(human, LOCKED)

    def test_phone_human_text_is_byte_identical_without_events(self):
        self.assertEqual(self.phone_wait(True)[0], self.phone_wait(False)[0])

    def test_run_py_reports_locked_from_its_own_copy(self):
        def report(on):
            with patch.object(run, "sh"), patch.object(run, "locked", side_effect=[True, False]), \
                 patch.object(run.time, "sleep"):
                return capture(lambda: run.wait_unlocked("test"), on=on)
        on, off = report(True), report(False)
        self.assertTrue(on[2])
        self.assertEqual(on[1], ["locked"])
        self.assertEqual(on[0], LOCKED)
        self.assertEqual(on[0], off[0])

    def test_both_call_sites_go_through_the_shared_wait(self):
        # 文案与节奏只有一份（#709）：两处都调 wait.wait_unlocked，只交出锁屏判据与亮屏命令
        p = phone_stub("test", d=Mock())
        p.locked = Mock(return_value=False)
        with patch.object(wait, "wait_unlocked", return_value=True) as shared, \
             patch.object(run, "sh") as sh, patch.object(run, "locked", return_value=False) as run_locked:
            self.assertTrue(run.wait_unlocked("test"))
            self.assertTrue(p.wait_unlocked())
            (run_locked_arg, run_wake), (phone_locked, phone_wake) = [c.args[:2] for c in shared.call_args_list]
            run_locked_arg()
            run_wake()
            phone_wake()
        run_locked.assert_called_once_with("test")
        sh.assert_called_once_with("test", adb_link.WAKEUP)
        self.assertIs(phone_locked, p.locked)
        p.d.shell.assert_called_once_with(adb_link.WAKEUP)


class UiBusyTests(unittest.TestCase):
    def service_busy(self, on):
        from uiautomator2.exceptions import AccessibilityServiceAlreadyRegisteredError
        raised = {}

        def call():
            with self.assertRaises(RuntimeError) as caught:
                fast.Phone("test", False)
            raised["message"] = str(caught.exception)
        with patch.object(fast, "connect", side_effect=AccessibilityServiceAlreadyRegisteredError("first cause")), \
             patch.object(fast, "accessibility_summary", return_value="只读检查"):
            human, sent, _ = capture(call, on=on)
        return human, sent, raised["message"]

    def lock_busy(self, on):
        import ui_session
        held = ui_session.DeviceLock("aac-test-serial", wait=0)
        raised = {}

        def call():
            with self.assertRaises(ui_session.DeviceBusyError) as caught:
                ui_session.DeviceLock("aac-test-serial", 0)
            raised["message"] = str(caught.exception)
        try:
            human, sent, _ = capture(call, on=on)
        finally:
            held.close()
        return human, sent, raised["message"]

    def test_service_already_registered_reports_busy(self):
        human, sent, message = self.service_busy(on=True)
        self.assertEqual(sent, ["ui_busy"])
        self.assertEqual(human, "")
        self.assertIn("UIAUTOMATION_BUSY", message)

    def test_local_lock_contention_reports_busy(self):
        human, sent, message = self.lock_busy(on=True)
        self.assertEqual(sent, ["ui_busy"])
        self.assertEqual(human, "")
        self.assertIn("读屏服务", message)

    def test_both_messages_are_byte_identical_without_events(self):
        self.assertEqual(self.service_busy(True)[2], self.service_busy(False)[2])
        self.assertEqual(self.lock_busy(True)[2], self.lock_busy(False)[2])


if __name__ == "__main__":
    unittest.main()
