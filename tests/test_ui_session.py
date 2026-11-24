"""服务占用、失败清理、跨进程互斥与失败后的收尾。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import contextlib
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import uuid
from unittest.mock import Mock, patch

from fixtures import Clock, FakeProc, FakeRunner, job_stub
from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import fast
from phone import connection as phone_connection
import run
import ui_session as session


class LockTests(unittest.TestCase):
    def test_other_process_is_blocked_until_owner_exits(self):
        serial = "test-" + uuid.uuid4().hex
        source = "from ui_session import DeviceLock; import sys; lock=DeviceLock(sys.argv[1]); print('locked',flush=True); sys.stdin.read()"
        env = dict(os.environ, PYTHONPATH=str(ROOT / "tool"))
        child = subprocess.Popen([sys.executable, "-u", "-c", source, serial], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaises(session.DeviceBusyError):
                session.DeviceLock(serial, wait=0)
            clock = Clock()
            with patch.object(session, "time", clock), \
                    self.assertRaises(session.DeviceBusyError):
                session.DeviceLock(serial, wait=20)   # 等到 deadline 才报占用，不用真等 20 秒
            self.assertGreaterEqual(clock.t, 20)
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
        with patch.object(phone_connection, "connect", side_effect=session.AccessibilityServiceAlreadyRegisteredError("first cause")), \
             patch.object(phone_connection, "accessibility_summary", return_value="只读检查：配置了 2 项服务"), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as error:
                fast.Phone("test")
        message = str(error.exception)
        for phrase in ("UIAUTOMATION_BUSY", "first cause", "手动重启手机", "GKD", "自动记账", "按需恢复", "2 项服务"):
            self.assertIn(phrase, message)
        self.assertNotIn("无需关闭手机无障碍", message)

    def test_cli_operation_exception_still_closes_phone(self):
        d = Mock(); d.window_size.return_value = (1080, 2400); d.settings = {}
        with patch.object(phone_connection, "connect", return_value=d), \
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
        with patch.object(phone_connection, "connect", return_value=d), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "display unavailable"):
                fast.Phone("test")
        d.close.assert_called_once()


class TaskTests(unittest.TestCase):
    def test_conflict_skips_following_ui_task_but_keeps_cleanup_and_first_error(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory, runner=FakeRunner(spawns=[
                FakeProc('#aac:event {"kind": "ui_busy"}\nUIAUTOMATION_BUSY: first failure\n', rc=1),
                FakeProc("插电常亮已改回 7\n")]))
            api.job = job_stub()
            api._work([app.Task("广告开关", "run.py", ["-s", "test", "recipe"], uses_ui=True),
                       app.Task("通知", "chan_fast.py", uses_ui=True, channels=[]),
                       app.Task("收尾", "run.py", ["-s", "test", "finish"], always_run=True)])
            self.assertEqual(len(api.runner.spawn_calls), 2)
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


class Watch:
    """`time` 的替身：sleep 与 monotonic 共用同一个假钟，等释放循环按它算预算。"""

    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t = round(self.t + seconds, 3)     # 假钟按毫秒取整：20 次 0.2 落在整 5.0 上


def fake_msvcrt():
    """Windows 锁的替身：记住每次调用时的文件描述符、模式与当前文件位置。"""
    calls = []

    def locking(fd, mode, length):
        calls.append((fd, mode, length, os.lseek(fd, 0, os.SEEK_CUR)))

    module = types.SimpleNamespace(LK_NBLCK="NBLCK", LK_UNLCK="UNLCK", locking=locking)
    return module, calls


class DeviceLockTests(unittest.TestCase):
    """锁文件的口径：文件名、内容与互斥；win32 那支用假 msvcrt 走到。"""

    def serial(self):
        return "lock-" + uuid.uuid4().hex

    def seed_bytes(self, lock):
        """锁文件此刻的内容：Windows 上另开一个句柄读会被共享模式挡住，只能读自己持有那个句柄。"""
        lock.file.seek(0)
        return lock.file.read()

    def test_the_lock_file_is_derived_from_the_serial(self):
        serial = self.serial()
        lock = session.DeviceLock(serial, wait=0)
        try:
            expected = (Path(tempfile.gettempdir()) / "android-ad-cleaner-locks"
                        / (hashlib.sha256(serial.encode("utf-8")).hexdigest() + ".lock"))
            self.assertEqual(Path(lock.file.name), expected)
            self.assertEqual(self.seed_bytes(lock), b"0")
        finally:
            lock.close()

    def test_a_fresh_lock_carries_one_seed_byte(self):
        lock = session.DeviceLock(self.serial(), wait=0)
        try:
            self.assertEqual(self.seed_bytes(lock), b"0")
        finally:
            lock.close()

    def test_reopening_the_lock_does_not_append_another_seed(self):
        serial = self.serial()
        session.DeviceLock(serial, wait=0).close()
        lock = session.DeviceLock(serial, wait=0)
        try:
            self.assertEqual(self.seed_bytes(lock), b"0")
        finally:
            lock.close()

    def test_the_same_serial_is_held_until_the_owner_closes(self):
        serial = self.serial()
        held = session.DeviceLock(serial, wait=0)
        try:
            with self.assertRaises(session.DeviceBusyError):
                session.DeviceLock(serial, wait=0)
        finally:
            held.close()
        session.DeviceLock(serial, wait=0).close()

    def test_another_serial_is_not_blocked(self):
        first = session.DeviceLock(self.serial(), wait=0)
        try:
            session.DeviceLock(self.serial(), wait=0).close()
        finally:
            first.close()

    def test_the_default_wait_is_twenty_seconds(self):
        serial = self.serial()
        held = session.DeviceLock(serial, wait=0)
        clock = Clock()
        try:
            with patch.object(session, "time", clock), self.assertRaises(session.DeviceBusyError) as busy:
                session.DeviceLock(serial)
            self.assertEqual(str(busy.exception),
                             "本电脑另一个去广告任务正在使用这台手机的读屏服务，请结束该任务后重试。")
            self.assertEqual(clock.t, 20.0)
        finally:
            held.close()

    def test_windows_locks_and_unlocks_the_first_byte(self):
        module, calls = fake_msvcrt()
        with patch.dict(sys.modules, {"msvcrt": module}), \
             patch.object(session.sys, "platform", "win32"):
            lock = session.DeviceLock(self.serial(), wait=0)
            fd = lock.file.fileno()
            lock.close()
        self.assertEqual(calls, [(fd, "NBLCK", 1, 0), (fd, "UNLCK", 1, 0)])


class CheckAliveTests(unittest.TestCase):
    def device(self):
        d = session.ManagedDevice.__new__(session.ManagedDevice)
        d._dev = types.SimpleNamespace()
        d._device_server_port = 7912
        return d

    def test_the_ping_contract(self):
        d = self.device()
        with patch.object(session, "_http_request",
                          return_value=types.SimpleNamespace(content=b"pong")) as ping:
            self.assertTrue(d._check_alive())
        ping.assert_called_once_with(d._dev, 7912, "GET", "/ping", timeout=1)

    def test_a_short_answer_is_not_alive(self):
        with patch.object(session, "_http_request",
                          return_value=types.SimpleNamespace(content=b"pong!")):
            self.assertFalse(self.device()._check_alive())

    def test_a_transport_error_is_not_alive(self):
        for error in (OSError("down"), session.HTTPError("boom")):
            with patch.object(session, "_http_request", side_effect=error):
                self.assertFalse(self.device()._check_alive())


class ManagedDeviceTests(unittest.TestCase):
    def device(self, process=None, alive=False):
        d = session.ManagedDevice.__new__(session.ManagedDevice)
        d._lock = threading.Lock()
        d._process = process
        d._session_lock = Mock()
        d._check_alive = Mock(return_value=alive)
        return d

    def test_connect_builds_a_managed_device_for_the_serial(self):
        with patch.object(session, "ManagedDevice") as device:
            self.assertIs(session.connect("SERIAL"), device.return_value)
        device.assert_called_once_with("SERIAL")

    def test_the_serial_goes_to_the_lock_and_the_upstream_device(self):
        with patch.object(session, "DeviceLock", return_value=Mock()) as lock, \
             patch.object(session.u2.Device, "__init__", return_value=None) as init, \
             patch.object(session.atexit, "unregister") as unregister, \
             patch.object(session.atexit, "register") as register:
            device = session.ManagedDevice("SERIAL")
        lock.assert_called_once_with("SERIAL")
        self.assertEqual(init.call_args.args, ("SERIAL",))
        self.assertEqual(unregister.call_args.args, (device.stop_uiautomator,))
        self.assertEqual(register.call_args.args, (device.close,))

    def test_a_reused_service_closes_the_lock_and_nothing_else(self):
        d = session.ManagedDevice.__new__(session.ManagedDevice)   # 没有 `_process`：复用来的服务
        d._session_lock = Mock()
        with patch.object(session.atexit, "unregister") as unregister:
            d.close()
        d._session_lock.close.assert_called_once_with()
        unregister.assert_called_once_with(d.close)

    def test_an_unreleased_process_names_the_retry_stop(self):
        process = Mock()
        process.pool.return_value = None
        d = self.device(process)
        with self.assertRaises(RuntimeError) as stopped:
            d.stop_uiautomator()
        self.assertEqual(str(stopped.exception),
                         "本次读屏进程未退出，停止重连；请退出客户端并重启手机后重试。")

    def test_a_service_that_releases_within_one_poll_returns(self):
        process = Mock()
        process.pool.return_value = 0
        d = self.device(process, alive=True)
        d._check_alive = Mock(side_effect=[True, False])
        watch = Watch()
        with patch.object(session, "time", watch):
            d.stop_uiautomator()
        self.assertEqual(watch.sleeps, [.2])
        self.assertIsNone(d._process)

    def test_the_release_budget_is_five_seconds(self):
        process = Mock()
        process.pool.return_value = 0
        d = self.device(process, alive=True)
        watch = Watch()
        with patch.object(session, "time", watch), self.assertRaises(RuntimeError) as stuck:
            d.stop_uiautomator()
        self.assertEqual(str(stuck.exception),
                         "本次读屏服务未释放，停止重连；请退出客户端并重启手机后重试。")
        self.assertEqual(watch.t, 5.0)


if __name__ == "__main__":
    unittest.main()
