"""0.2.3 用户反馈：无障碍排查只读、找机位通知保护以及旧清单还原。"""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fixtures import FakeRunner
from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
import troubleshooting as help_ui


class AccessibilityTests(unittest.TestCase):
    def test_probe_is_bounded_read_only_and_does_not_disclose_service_names(self):
        output = "1\ncom.private.app/.Service:com.reader/.Service:com.private.app/.Service\n"
        with patch.object(help_ui.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=output)) as shell:
            result = help_ui.accessibility_summary("private-serial", "adb-test")
        self.assertIn("2 项服务", result)
        self.assertIn("不能证明", result)
        for value in ("com.private", "com.reader", "private-serial"):
            self.assertNotIn(value, result)
        args = shell.call_args.args[0]
        self.assertEqual(args[:4], ["adb-test", "-s", "private-serial", "shell"])
        self.assertEqual(args[4], "settings get secure accessibility_enabled; settings get secure enabled_accessibility_services")
        self.assertEqual(shell.call_args.kwargs["timeout"], 3)
        self.assertEqual(shell.call_args.kwargs["encoding"], "utf-8")

    def test_disabled_global_setting_does_not_claim_configured_services_are_active(self):
        with patch.object(help_ui.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="0\ncom.example/.Service\n")):
            result = help_ui.accessibility_summary("test", "adb-test")
        self.assertIn("总开关为关闭", result)
        self.assertIn("不能排除", result)

    def test_timeout_permission_failure_and_invalid_output_are_not_clean_bills_of_health(self):
        for result in (subprocess.TimeoutExpired(["adb"], 3), SimpleNamespace(returncode=1, stdout="denied"),
                       SimpleNamespace(returncode=0, stdout="1\ninvalid service output\n")):
            with self.subTest(result=result), patch.object(help_ui.subprocess, "run") as shell:
                if isinstance(result, Exception): shell.side_effect = result
                else: shell.return_value = result
                message = help_ui.accessibility_summary("test", "adb-test")
                self.assertIn("排查", message)
                self.assertNotIn("0 项服务", message)


class PhotoSpotTests(unittest.TestCase):
    def state(self, name="找机位推荐", on=True):
        return {("com.example", "recommend"): (name, 3 if on else 0, False)}, {"com.example": False}

    def test_scan_protects_feature_names_even_with_marketing_channel_id(self):
        for name in ("找机位", "找 机 位通知", "找\u200b機位", "机位推荐", "推薦機位", "摄影找机位活动"):
            with self.subTest(name=name), patch.object(chan, "parse", return_value=self.state(name)), \
                 patch.object(chan, "phone_model", return_value=""), patch.object(chan, "Phone") as phone, \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "scan"]), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                chan.main()
                self.assertEqual(output.getvalue(), "")
                phone.assert_not_called()

    def test_old_list_uses_current_name_and_saved_label_before_connecting(self):
        for actual, label in (("找机位推荐", "活动优惠"), ("活动优惠", "找机位通知")):
            with self.subTest(actual=actual), tempfile.TemporaryDirectory() as directory:
                path = Path(directory, "old.tsv")
                path.write_text(f"com.example\trecommend\t{label}\n", encoding="utf-8")
                with patch.object(chan, "parse", return_value=self.state(actual)), patch.object(chan, "Phone") as phone, \
                     patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", str(path)]), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    chan.main()
                self.assertIn("受保护，未改动", output.getvalue())
                self.assertIn("仍开着: 0", output.getvalue())
                phone.assert_not_called()

    def test_already_disabled_protected_channel_is_not_automatically_reenabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "old.tsv")
            path.write_text("com.example\trecommend\t找机位通知\n", encoding="utf-8")
            with patch.object(chan, "parse", return_value=self.state(on=False)), patch.object(chan, "Phone") as phone, \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                chan.main()
            self.assertIn("当前状态 off", output.getvalue())
            phone.assert_not_called()

    def test_fresh_protection_in_toggle_cannot_be_bypassed_by_stale_marketing_name(self):
        p = Mock(); p.locked.return_value = False
        with patch.object(chan, "parse", return_value=self.state()):
            result = chan.toggle(p, "com.example", "recommend", False, "活动优惠")
        self.assertEqual(result.kind, chan.PROTECTED)
        p.d.shell.assert_not_called()
        p.click.assert_not_called()

    def test_targeted_restore_of_protected_notification_is_still_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "restore.tsv")
            path.write_text("com.example\trecommend\t找机位通知\n", encoding="utf-8")
            with patch.object(chan, "parse", side_effect=[self.state(on=False), self.state()]), \
                 patch.object(chan, "Phone") as phone, patch.object(chan, "toggle", return_value=chan.Outcome(chan.DONE)) as toggle, \
                 patch.object(chan, "keep_awake", return_value=None), \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "on", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                chan.main()
            toggle.assert_called_once_with(phone.return_value, "com.example", "recommend", True, "找机位推荐",
                                           {("com.example", "recommend")})
            self.assertIn("未恢复的渠道: 0", output.getvalue())

    def test_low_level_restore_can_enable_protected_channel(self):
        p = Mock(); p.locked.return_value = False
        with patch.object(chan, "parse", side_effect=[self.state(on=False), self.state()]), \
             patch.object(chan.ChannelPage, "refresh", return_value=chan.Reached(("允许通知", False, (500, 500)))), \
             patch.object(chan, "disabled_at", return_value=False), \
             patch.object(chan.time, "sleep"):
            self.assertEqual(chan.toggle(p, "com.example", "recommend", True, "找机位推荐").kind, chan.DONE)
        p.click.assert_called_once_with(500, 500)


class GuiFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.api = self.app.Api(self.directory.name)

    def test_gui_filters_old_scan_results_so_select_all_cannot_reinclude_feature(self):
        self.api = self.app.Api(self.directory.name, runner=FakeRunner(
            runs=("com.example\trecommend\t找机位通知\ncom.shop\tpromo\t活动优惠\n", "", 0)))
        self.assertEqual(self.api.chan_scan("test")["chans"], [{"pkg": "com.shop", "id": "promo", "name": "活动优惠", "app": "", "checked": True}])

    def test_recovery_is_visible_before_long_stack_and_full_cause_is_preserved(self):
        detail = "AccessibilityServiceAlreadyRegisteredError: first cause\n" + "java.lang.IllegalStateException: stack\n" * 100
        result = self.api._remember_error("读屏检查", "private-serial", detail)
        self.assertTrue(result["error"].startswith(help_ui.UI_RECOVERY))
        self.assertEqual(result["recovery"], help_ui.UI_RECOVERY)
        self.assertEqual(result["detail"], detail)
        self.assertIn("first cause", self.api.last_error["detail"])


if __name__ == "__main__":
    unittest.main()
