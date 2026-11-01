"""服务占用、失败清理、跨进程互斥与失败后的收尾。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import time
import uuid
from unittest.mock import Mock, patch

from fixtures import job_stub
from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import fast
import run
import ui_session as session


class LockTests(unittest.TestCase):
    def test_other_process_is_blocked_until_owner_exits(self):
        serial = "test-" + uuid.uuid4().hex
        source = "from ui_session import DeviceLock; import sys; lock=DeviceLock(sys.argv[1]); print('locked',flush=True); sys.stdin.read()"
        env = dict(os.environ, PYTHONPATH=str(ROOT / "tool"))
        child = subprocess.Popen([sys.executable, "-u", "-c", source, serial], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaises(session.DeviceBusyError):
                session.DeviceLock(serial, wait=0)
            started = time.time()
            with self.assertRaises(session.DeviceBusyError):
                session.DeviceLock(serial, wait=1)    # 先等一会儿，等不到才报占用
            self.assertGreaterEqual(time.time() - started, 0.9)
            other = session.DeviceLock(serial + "-different-device")
            other.close()
            child.terminate(); child.wait(timeout=10)
            lock = session.DeviceLock(serial)  # 即使 owner 被强制终止也不会永久锁死
            lock.close()
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
            child.stdin.close(); child.stdout.close(); child.stderr.close()


class LifecycleTests(unittest.TestCase):
    def device(self, process=None):
        d = session.ManagedDevice.__new__(session.ManagedDevice)
        d._lock = threading.Lock()
        d._process = process
        d._session_lock = Mock()
        d._check_alive = Mock(return_value=False)
        return d

    def test_reused_service_is_not_stopped(self):
        d = self.device()
        d.close()
        d._check_alive.assert_not_called()
        d._session_lock.close.assert_called_once()

    def test_owned_service_stops_before_releasing_local_lock(self):
        process = Mock(); process.pool.return_value = 0
        d = self.device(process)
        calls = []
        process.kill.side_effect = lambda: calls.append("stop")
        d._check_alive.side_effect = lambda: calls.append("wait") or False
        d._session_lock.close.side_effect = lambda: calls.append("unlock")
        d.close()
        self.assertEqual(calls, ["stop", "wait", "unlock"])
        self.assertIsNone(d._process)

    def test_initialization_failure_closes_owned_handle_and_unlocks(self):
        process = Mock(); process.pool.return_value = 0
        def fail(d, serial):
            d._lock, d._process = threading.Lock(), process
            raise session.AccessibilityServiceAlreadyRegisteredError("root cause")
        with patch.object(session.u2.Device, "__init__", fail), \
             patch.object(session, "DeviceLock") as lock, \
             patch.object(session.ManagedDevice, "_check_alive", return_value=False):
            with self.assertRaisesRegex(session.AccessibilityServiceAlreadyRegisteredError, "root cause"):
                session.ManagedDevice("test")
        process.kill.assert_called_once()
        lock.return_value.close.assert_called_once()

    def test_transient_registration_race_retries_once_after_cleanup(self):
        d = self.device()
        d.stop_uiautomator = Mock()
        error = session.AccessibilityServiceAlreadyRegisteredError("already registered")
        with patch.object(session.u2.Device, "start_uiautomator", side_effect=[error, None]) as start, \
             patch.object(session.time, "sleep") as sleep:
            d.start_uiautomator()
        self.assertEqual(start.call_count, 2)
        d.stop_uiautomator.assert_called_once()
        sleep.assert_called_once_with(1)

    def test_persistent_conflict_stops_after_two_attempts_with_original_cause(self):
        d = self.device(); d.stop_uiautomator = Mock()
        error = session.AccessibilityServiceAlreadyRegisteredError("original registration cause")
        with patch.object(session.u2.Device, "start_uiautomator", side_effect=error) as start, \
             patch.object(session.time, "sleep"):
            with self.assertRaisesRegex(session.AccessibilityServiceAlreadyRegisteredError, "original registration cause"):
                d.start_uiautomator()
        self.assertEqual(start.call_count, 2)
        self.assertEqual(d.stop_uiautomator.call_count, 2)

    def test_unrelated_failure_is_not_retried(self):
        d = self.device(); d.stop_uiautomator = Mock()
        with patch.object(session.u2.Device, "start_uiautomator", side_effect=OSError("device offline")) as start:
            with self.assertRaisesRegex(OSError, "offline"):
                d.start_uiautomator()
        start.assert_called_once()

    def test_unreleased_owned_process_prevents_retry(self):
        process = Mock(); process.pool.return_value = None
        d = self.device(process)
        with patch.object(session.u2.Device, "start_uiautomator", side_effect=session.AccessibilityServiceAlreadyRegisteredError("registered")) as start:
            with self.assertRaisesRegex(RuntimeError, "未退出"):
                d.start_uiautomator()
        start.assert_called_once()

    def test_phone_conflict_message_preserves_cause_and_recovery_steps(self):
        with patch.object(fast, "connect", side_effect=session.AccessibilityServiceAlreadyRegisteredError("first cause")), \
             patch.object(fast, "accessibility_summary", return_value="只读检查：配置了 2 项服务"), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as error:
                fast.Phone("test")
        message = str(error.exception)
        for phrase in ("UIAUTOMATION_BUSY", "first cause", "手动重启手机", "GKD", "自动记账", "按需恢复", "2 项服务"):
            self.assertIn(phrase, message)
        self.assertNotIn("无需关闭手机无障碍", message)

    def test_cli_operation_exception_still_closes_phone(self):
        d = Mock(); d.window_size.return_value = (1080, 2400); d.settings = {}
        with patch.object(fast, "connect", return_value=d), \
             patch.object(fast, "execute", side_effect=RuntimeError("failed step")), \
             patch.object(sys, "argv", ["fast.py", "-s", "test", "check"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as stop:
                fast.main()
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("✗ failed step", out.getvalue())      # 给出原因，不打印报错堆栈
        d.close.assert_called_once()

    def test_phone_setup_failure_closes_connected_service(self):
        d = Mock(); d.settings = {}; d.window_size.side_effect = RuntimeError("display unavailable")
        with patch.object(fast, "connect", return_value=d), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "display unavailable"):
                fast.Phone("test")
        d.close.assert_called_once()


class TaskTests(unittest.TestCase):
    def test_conflict_skips_following_ui_task_but_keeps_cleanup_and_first_error(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api.job = job_stub()
            failed = Mock(stdout=io.StringIO('#aac:event {"kind": "ui_busy"}\nUIAUTOMATION_BUSY: first failure\n'))
            failed.wait.return_value = 1
            finish = Mock(stdout=io.StringIO("插电常亮已改回 7\n")); finish.wait.return_value = 0
            with patch.object(app.subprocess, "Popen", side_effect=[failed, finish]) as popen:
                api._work([app.Task("广告开关", "run.py", ["-s", "test", "recipe"], uses_ui=True),
                           app.Task("通知", "chan_fast.py", uses_ui=True, channels=[]),
                           app.Task("收尾", "run.py", ["-s", "test", "finish"])])
            self.assertEqual(popen.call_count, 2)
            self.assertTrue(api.job.results[1]["skipped"])
            self.assertEqual(api.job.results[2]["rc"], 0)
            self.assertIn("GKD", api.job.recovery)
            api.job.total = 3
            self.assertEqual(api.poll()["recovery"], api.job.recovery)
            self.assertEqual(api.last_error["operation"], "广告开关")
            self.assertIn("first failure", api.last_error["detail"])

    def test_finish_does_not_claim_ad_changes_succeeded(self):
        self.assertNotIn("去广告已经做完", run.DEV_REMINDER)
        self.assertIn("先核对执行结果", run.DEV_REMINDER)


if __name__ == "__main__":
    unittest.main()
