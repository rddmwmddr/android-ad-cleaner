"""0.2.2：只读扫描不依赖 UiAutomation，初始化失败保留完整原因。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fixtures import fake_adb, job_stub
from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
import fast


def dump(importance=3):
    return f"""PackagePreferences:
      AppSettings: com.example importance=DEFAULT
        NotificationChannel{{mId='promo', mName=活动优惠, mDescription=null, mImportance={importance}, mDeleted=false}}
    """


class ReadOnlyTests(unittest.TestCase):
    def invoke(self, args, output):
        fake_adb(self)
        result = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch.object(fast, "connect", side_effect=AssertionError("只读操作不应启动 UiAutomation")) as connect, \
             patch.object(subprocess, "run", return_value=result) as shell, \
             patch.object(chan, "app_labels", return_value={}), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test-device", *args]), \
             contextlib.redirect_stdout(io.StringIO()) as log:
            chan.main()
        connect.assert_not_called()
        self.assertTrue(all(c.args[0][1:3] == ["-s", "test-device"] for c in shell.call_args_list))
        self.assertTrue(all(c.args[0][-1] == "dumpsys notification --noredact" for c in shell.call_args_list))
        return log.getvalue()

    def test_scan_survives_unavailable_automation(self):
        self.assertEqual(self.invoke(["scan"], dump()), "com.example\tpromo\t活动优惠\n")

    def test_mixed_payment_and_deals_channel_is_not_marketing_candidate(self):
        # 一加 Ace 2 Pro 实机 Google Play 渠道同时承载付款和推荐，不能因推荐字样关闭。
        for name in ("付款事宜、特惠信息和推荐内容", "Payments, deals and recommendations"):
            with self.subTest(name=name):
                self.assertEqual(self.invoke(["scan"], dump().replace("活动优惠", name)), "")

    def test_ad_network_channel_is_listed(self):
        body = (dump().replace("com.example", "com.freeme.launcher")
                .replace("'promo', mName=活动优惠", "'TencentAdNetCH1', mName=频道"))
        self.assertEqual(self.invoke(["scan"], body), "com.freeme.launcher\tTencentAdNetCH1\t频道\n")

    def test_verify_and_noop_close_never_initialize_or_navigate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.example\tpromo\t活动优惠\n", encoding="utf-8")
            self.assertIn("仍开着: 1", self.invoke(["verify", str(path)], dump()))
            self.assertIn("拨了 0 个", self.invoke(["off", str(path)], dump(0)))

    def test_missing_list_fails_before_device_access(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fast, "connect") as connect, \
             patch.object(subprocess, "run") as shell, \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", str(Path(directory, "missing.tsv"))]):
            with self.assertRaises(FileNotFoundError):
                chan.main()
        shell.assert_not_called()
        connect.assert_not_called()

    def test_close_still_requires_working_automation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.example\tpromo\t活动优惠\n", encoding="utf-8")
            with patch.object(chan.ShellPhone, "shell", return_value=SimpleNamespace(output=dump())), \
                 patch.object(fast, "accessibility_summary", return_value="只读检查不可用"), \
                 patch.object(fast, "connect", side_effect=fast.u2.exceptions.LaunchUiAutomationError("java.lang.IllegalStateException: example")), \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stop:
                    chan.main()
            # 不打印 Python 报错堆栈，原因和客户端识别用的标记（LaunchUiAutomationError）仍在
            self.assertRegex(str(stop.exception.code), r"读屏服务.*启动失败[\s\S]*LaunchUiAutomationError")

    def test_adb_failure_is_not_empty_success(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="device unauthorized")
        with patch.object(adb_link, "adb_path", return_value="/fake/adb"), \
             patch.object(subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "unauthorized"):
                chan.parse(chan.ShellPhone("test"))

    def test_shell_call_has_serial_utf8_and_timeout(self):
        with patch.object(adb_link, "adb_path", return_value="/fake/adb"), \
             patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=dump(), stderr="")) as shell:
            chan.parse(chan.ShellPhone("test"))
        self.assertEqual(shell.call_args.args[0], ["/fake/adb", "-s", "test", "shell", "dumpsys notification --noredact"])
        self.assertEqual(shell.call_args.kwargs["timeout"], 60)
        self.assertEqual(shell.call_args.kwargs["encoding"], "utf-8")


class ErrorTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.api = self.app.Api(self.directory.name)
        self.api._adb = Mock(return_value="Android Debug Bridge version 1.0.41")

    def test_scan_failure_keeps_root_cause_and_redacts_before_saving(self):
        home = str(Path.home())
        detail = f"java.lang.IllegalStateException: root cause; device-123; {home}/private\n" + "at QueryController.java:95\n" * 100
        self.api._run = Mock(return_value=("", detail, 1))
        result = self.api.chan_scan("device-123")
        self.assertIn("root cause", result["error"])
        self.assertGreater(len(result["detail"]), 600)
        self.assertNotIn("device-123", result["detail"])
        self.assertNotIn(home, result["detail"])
        saved = Path(self.directory.name, "logs/last-error.txt").read_text(encoding="utf-8")
        self.assertIn(result["detail"], saved)
        self.assertIn("root cause", self.api.diagnostics())  # 扫描失败时还没有执行 job

    def test_scan_timeout_is_reported_and_saved(self):
        self.api._run = Mock(side_effect=subprocess.TimeoutExpired(["scan", "device-123"], 120))
        result = self.api.chan_scan("device-123")
        self.assertIn("timed out", result["detail"])
        self.assertNotIn("device-123", result["detail"])

    def test_read_screen_check_preserves_full_failure_and_os_version(self):
        self.api.last_status = {"info": {"brand": "Xiaomi", "model": "M154FF", "name": "Xiaomi 18 Pro Max",
                                        "build": "CP2A.260605.016", "os": "OS4.0.27", "android": "17"}}
        self.api._run = Mock(return_value=("", "UiAutomation failed at QueryController", 1))
        result = self.api.ui_check("test")
        self.assertIn("UiAutomation", result["detail"])
        self.assertIn("OS4.0.27", self.api.diagnostics())
        self.api._run.assert_called_once_with("fast.py", "-s", "test", "check", timeout=75)

    def test_read_screen_check_does_not_run_during_job(self):
        self.api.job = job_stub()
        self.api._run = Mock()
        self.assertIn("正在执行", self.api.ui_check("test")["error"])
        self.api._run.assert_not_called()

    def test_failed_task_keeps_first_exception_not_only_tail(self):
        detail = "java.lang.IllegalStateException: first cause\n" + f"at {Path.home()}/frame\n" * 100
        self.api.job = job_stub()
        process = Mock(stdout=io.StringIO(detail))
        process.wait.return_value = 1
        with patch.object(self.app.subprocess, "Popen", return_value=process):
            self.api._work([self.app.Task("关闭广告", "run.py", [])])
        self.assertFalse(self.api.job.running)
        self.assertEqual(self.api.job.results[0]["rc"], 1)
        self.assertIn("first cause", self.api.last_error["detail"])
        self.assertNotIn(str(Path.home()), self.api.diagnostics())

    def test_packaged_cli_handles_exception_with_nonzero_exit(self):
        with patch.object(self.app, "_fix_stdio"), \
             patch.object(self.app.runpy, "run_path", side_effect=RuntimeError("java.lang.IllegalStateException: full cause")), \
             patch.object(sys, "argv", ["aac-cli.exe", "--cli", "fast.py", "-s", "test", "check"]), \
             contextlib.redirect_stderr(io.StringIO()) as log:
            with self.assertRaises(SystemExit) as raised:
                self.app.cli_main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("full cause", log.getvalue())
        self.assertNotIn("[PYI-", log.getvalue())


if __name__ == "__main__":
    unittest.main()
