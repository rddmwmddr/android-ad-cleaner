"""社区反馈回归：不用手机，模拟页面与系统回读，不以 UI 状态代替执行结果。"""
import contextlib
import importlib.util
import io
import json
import ntpath
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
import fast
import run


def channel_phone():
    p = fast.Phone.__new__(fast.Phone)
    p.W, p.H, p.log = 1080, 1920, False
    p.d = Mock()
    p.locked = Mock(return_value=False)
    p.focus = Mock(return_value="com.android.settings/.Settings$ChannelNotificationSettingsActivity")
    p.confirm = Mock()
    p.click = Mock()
    p.tree = Mock(return_value=ET.fromstring('''<hierarchy><node>
      <node text="营销" bounds="[100,80][600,180]"/>
      <node bounds="[0,300][1080,410]">
        <node text="允许通知" bounds="[60,320][600,390]"/>
        <node class="android.widget.Switch" checked="true" checkable="true" bounds="[900,320][1040,390]"/>
      </node>
    </node></hierarchy>'''))
    return p


def snapshot(on=True, app_off=False):
    return {("com.example", "promo"): ("营销", 3 if on else 0, False)}, {"com.example": app_off}


class ScreenshotTests(unittest.TestCase):
    def test_partial_bounds_do_not_read_outside_image(self):
        image = Image.new("RGB", (100, 100), "blue")
        self.assertIsNone(fast.Phone._pixel_on(image, 70, 70, 160, 120))
        self.assertIsNone(fast.Phone._pixel_on(image, -10, 0, 10, 10))
        self.assertTrue(fast.Phone._pixel_on(image, 70, 70, 100, 100))

    def test_resolution_mismatch_is_unknown_not_off(self):
        p = channel_phone()
        p.d.screenshot.return_value = Image.new("RGB", (540, 960))
        root = ET.fromstring('<hierarchy><node resource-id="app:id/switch" clickable="true" bounds="[900,300][1040,400]"/></hierarchy>')
        self.assertEqual(p.switches(root), [])


@patch.object(chan.time, "sleep")
class ChannelTests(unittest.TestCase):
    def test_bom_and_crlf_do_not_drop_first_channel(self, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_bytes("\ufeffcom.example\tpromo\t营销\r\n".encode())
            self.assertEqual(chan.load(path), [("com.example", "promo", "营销")])

    def test_malformed_channel_list_is_reported(self, _sleep):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.example\n")
            with self.assertRaisesRegex(ValueError, "第 1 行"):
                chan.load(path)

    def test_notification_dump_failure_is_not_empty_success(self, _sleep):
        p = channel_phone()
        p.d.shell.return_value.output = "Permission denied"
        with self.assertRaisesRegex(RuntimeError, "读不到"):
            chan.parse(p)

    def test_app_master_switch_is_not_channel_switch(self, _sleep):
        p = channel_phone()
        p.focus.return_value = "com.android.settings/.Settings$AppNotificationSettingsActivity"
        self.assertIsNone(chan.channel_switch(p, "营销"))

    def test_same_text_in_unrelated_page_cannot_authorize_click(self, _sleep):
        p = channel_phone()
        p.focus.return_value = "com.example/.MarketingSettings"
        with patch.object(chan, "parse", return_value=snapshot()), patch.object(chan, "via_app_page", return_value=None):
            self.assertIn("未确认", chan.toggle(p, "com.example", "promo", False, "营销"))
        p.click.assert_not_called()

    def test_no_fallback_to_first_switch(self, _sleep):
        p = channel_phone()
        for node in p.tree().iter():
            if node.get("text") == "允许通知":
                node.set("text", "智能静默")
        self.assertIsNone(chan.channel_switch(p, "营销"))

    def test_vivo_app_wide_notification_page_is_refused(self, _sleep):
        p = channel_phone()
        p.focus.return_value = "com.vivo.systemuiplugin/.NotificationSettings"
        with patch.object(chan, "parse", return_value=snapshot()):
            self.assertIn("整个 App", chan.toggle(p, "com.example", "promo", False, "营销"))
        p.click.assert_not_called()

    def test_last_click_is_verified_not_reported_as_failure(self, _sleep):
        p = channel_phone()
        with patch.object(chan, "parse", side_effect=[snapshot(), snapshot(), snapshot(), snapshot(False)]):
            self.assertIsNone(chan.toggle(p, "com.example", "promo", False, "营销"))
        self.assertEqual(p.click.call_count, 3)

    def test_changed_page_does_not_reuse_coordinates(self, _sleep):
        p = channel_phone()
        p.click.side_effect = lambda *xy: p.tree.__setattr__("return_value", ET.fromstring("<hierarchy/>"))
        with patch.object(chan, "parse", return_value=snapshot()):
            self.assertIn("已变化", chan.toggle(p, "com.example", "promo", False, "营销"))
        self.assertEqual(p.click.call_count, 1)

    def test_app_notification_change_aborts_batch(self, _sleep):
        p = channel_phone()
        with patch.object(chan, "parse", side_effect=[snapshot(), snapshot(app_off=True)]):
            with self.assertRaisesRegex(RuntimeError, "总开关发生变化"):
                chan.toggle(p, "com.example", "promo", False, "营销")
        p.click.assert_called_once()

    def test_ui_only_success_is_not_reported(self, _sleep):
        p = channel_phone()
        for node in p.tree().iter():
            if node.get("checkable") == "true":
                node.set("checked", "false")
        with patch.object(chan, "parse", return_value=snapshot()):
            self.assertIn("不一致", chan.toggle(p, "com.example", "promo", False, "营销"))
        p.click.assert_not_called()

    def test_app_page_fallback_navigates_then_checks_channel(self, _sleep):
        p = channel_phone()
        p.focus.return_value = "com.android.settings/.Settings$AppNotificationSettingsActivity"
        channel_root = p.tree()
        p.tree.return_value = ET.fromstring('''<hierarchy><node>
          <node text="示例应用" bounds="[100,80][600,180]"/>
          <node clickable="true" bounds="[0,600][1080,710]">
            <node text="营销" bounds="[60,620][600,690]"/>
          </node>
        </node></hierarchy>''')
        def navigate(*_):
            p.tree.return_value = channel_root
            p.focus.return_value = "com.android.settings/.SubSettings"
        p.click.side_effect = navigate
        p.settle = Mock(return_value=True)
        self.assertEqual(chan.via_app_page(p, "com.example", "营销")[0], "允许通知")
        p.click.assert_called_once()

    def test_restore_failure_returns_nonzero(self, _sleep):
        with patch.object(chan, "Phone", return_value=channel_phone()), \
             patch.object(chan, "load", return_value=[("com.example", "promo", "营销")]), \
             patch.object(chan, "parse", return_value=snapshot(False)), \
             patch.object(chan, "toggle", return_value="未确认渠道页"), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "on", "channels.tsv"]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                chan.main()
        self.assertEqual(raised.exception.code, 1)


class QuickappTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.backup = Path(self.directory.name, "vivo-test")
        self.backup.mkdir()
        self.value = "1"
        def shell(_serial, cmd):
            if "put secure" in cmd:
                self.value = cmd.split()[-1]
            return ""
        patches = [patch.object(run, "BACKUPS", self.directory.name),
                   patch.object(run, "latest_backup", return_value=str(self.backup)),
                   patch.object(run, "quickapp_switch", side_effect=lambda _: self.value),
                   patch.object(run, "sh", side_effect=shell)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_close_repeat_backup_restore_preserves_original(self):
        run.set_quickapp_service("test-device")
        self.assertEqual(self.value, "0")
        first = self.backup / "quickapp-setting.json"
        original = first.read_text()
        new_backup = Path(self.directory.name, "vivo-later")
        new_backup.mkdir()
        with patch.object(run, "latest_backup", return_value=str(new_backup)):
            run.set_quickapp_service("test-device")
            self.assertEqual(first.read_text(), original)
            run.set_quickapp_service("test-device", restore=True)
        self.assertEqual(self.value, "1")
        self.assertFalse(first.exists())

    def test_already_disabled_never_creates_default_restore(self):
        self.value = "0"
        run.set_quickapp_service("test-device")
        with self.assertRaisesRegex(RuntimeError, "没有找到"):
            run.set_quickapp_service("test-device", restore=True)
        self.assertEqual(self.value, "0")

    def test_other_device_backup_cannot_be_restored(self):
        run.set_quickapp_service("another-device")
        with self.assertRaisesRegex(RuntimeError, "没有找到"):
            run.set_quickapp_service("test-device", restore=True)
        self.assertEqual(self.value, "0")

    def test_failed_write_keeps_original_and_reports_error(self):
        with patch.object(run, "sh", return_value="Permission denied"):
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                run.set_quickapp_service("test-device")
        self.assertEqual(json.loads((self.backup / "quickapp-setting.json").read_text())["original"], "1")

    def test_missing_service_switch_does_not_write(self):
        self.value = None
        with self.assertRaisesRegex(RuntimeError, "读不到"):
            run.set_quickapp_service("test-device")
        run.sh.assert_not_called()

    def test_service_disabled_is_closed_without_package_suspension(self):
        self.value = "0"
        with patch.object(run, "installed", side_effect=lambda _s, pkg: pkg == "com.vivo.hybrid"), \
             patch.object(run, "suspended", return_value=False):
            entries = run.quickapps("test-device")
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["closed"])
        self.assertFalse(entries[0]["suspended"])
        self.assertEqual(entries[0]["method"], "setting")

    def test_force_stop_follows_successful_suspend(self):
        events = []
        initial = {"pkg": "com.example.quick", "name": "测试快应用", "closed": False, "method": "suspend"}
        closed = dict(initial, closed=True)
        with patch.object(run, "quickapps", side_effect=[[initial], [closed]]), \
             patch.object(run, "suspended", return_value=True), patch.object(run, "record"), \
             patch.object(run, "sh_all", side_effect=lambda s, cmd: events.append(cmd) or "success"), \
             patch.object(run, "sh", side_effect=lambda s, cmd: events.append(cmd) or ""), \
             patch.object(sys, "argv", ["run.py", "-s", "test", "quickapp", "off"]), \
             contextlib.redirect_stdout(io.StringIO()):
            run.main()
        self.assertEqual(events, ["pm suspend --user 0 com.example.quick", "am force-stop --user 0 com.example.quick"])


class BackupTests(unittest.TestCase):
    def test_backup_path_on_another_windows_drive(self):
        with patch.object(run, "ROOT", r"D:\app"), \
             patch.object(run.os.path, "relpath", side_effect=ntpath.relpath), \
             patch.dict(os.environ, {"AAC_BACKUPS": ""}):
            self.assertEqual(run.display_backup_path(r"C:\backup\channels.tsv"), r"C:\backup\channels.tsv")

    def test_scan_failure_preserves_existing_channel_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("original-list")
            with patch.object(run, "latest_backup", return_value=directory), \
                 patch.object(run.subprocess, "run", return_value=types.SimpleNamespace(returncode=1, stdout="", stderr="读取失败")), \
                 patch.object(sys, "argv", ["run.py", "-s", "test", "chan-scan"]), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    run.main()
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(path.read_text(), "original-list")

    def test_package_backup_is_limited_to_owner(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run, "latest_backup", return_value=directory), \
             patch.object(run, "info", return_value={"model": "test"}), \
             patch.object(run, "sh", return_value="") as shell, \
             patch.object(sys, "argv", ["run.py", "-s", "test", "backup"]), \
             contextlib.redirect_stdout(io.StringIO()):
            run.main()
        calls = [c.args[1] for c in shell.call_args_list if "pm list packages" in c.args[1]]
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("--user 0" in cmd for cmd in calls))


class DesktopTests(unittest.TestCase):
    def test_gui_smoke_output_works_with_non_utf8_console(self):
        spec = importlib.util.spec_from_file_location("aac_gui_test", ROOT / "gui/app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="ascii", newline="\n")
        with patch.object(sys, "stdout", stream), patch.object(sys, "stderr", stream):
            app._fix_stdio()
            print("GUI smoke: 页面通过")
            stream.flush()
        self.assertEqual(buffer.getvalue().decode("utf-8"), "GUI smoke: 页面通过\n")

    def test_failed_scan_reaches_gui_as_error(self):
        spec = importlib.util.spec_from_file_location("aac_gui_test", ROOT / "gui/app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        api = app.Api()
        api._run = Mock(return_value=("", "读取失败", 1))
        self.assertEqual(api.chan_scan("test"), {"error": "读取失败"})

    def test_gui_loads_file_uri_without_http_server(self):
        spec = importlib.util.spec_from_file_location("aac_gui_test", ROOT / "gui/app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        fake = types.SimpleNamespace(create_window=Mock(), start=Mock())
        with patch.dict(sys.modules, {"webview": fake}), patch.object(app, "IS_WIN", True), \
             patch.object(sys, "argv", ["app.py"]):
            app.main()
        url = fake.create_window.call_args.args[1]
        self.assertTrue(url.startswith("file:///"))
        self.assertIn("index.html", url)
        self.assertFalse(fake.start.call_args.kwargs["http_server"])
        self.assertEqual(fake.start.call_args.kwargs["gui"], "edgechromium")


if __name__ == "__main__":
    unittest.main()
