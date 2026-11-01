"""基于 ALN-AL00 已观察页面的脱敏离线回归；不会连接或改变手机。"""
from contextlib import ExitStack, redirect_stdout
import copy
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import huawei_channels as hw
import adb_link
import run


class OfflineDevice:
    """模拟已观察事实：进通知页可将 default 写成 allow；点击只切换对应渠道。"""
    def __init__(self):
        self.channels = {("com.example.a", "ad1"): ("营销通知", 1, False),
                         ("com.example.a", "ad2"): ("活动通知", 2, False),
                         ("com.example.a", "service"): ("服务通知", 3, False)}
        self.apps = {"com.example.a": False}
        self.modes = {"com.example.a": "default"}
        self.awake = "0"
        self.commands = []
        self.ui_commands = []
        self.opened = None
        self.tap_count = 0
        self.on_tap = None
        self.on_restore = None
        self.clock = 0
        self.reader = SimpleNamespace(shell=self.shell)
        self.phone = SimpleNamespace(serial="offline-device", W=1080, H=2400, changed=[],
                                     locked=Mock(return_value=False), close=Mock(),
                                     focus=lambda: hw.APP_PAGE, tree=self.tree,
                                     top=Mock(), scroll_more=Mock(return_value=False),
                                     on_screen=lambda node: True)
        self.phone.d = SimpleNamespace(shell=self.ui_shell, window_size=lambda: (1080, 2400))

    def shell(self, command):
        self.commands.append(command)
        if command == "getprop ro.product.model":
            text = hw.MODEL
        elif command == "getprop ro.build.display.id":
            text = hw.BUILD
        elif command.startswith("cmd appops get "):
            text = "POST_NOTIFICATION: " + self.modes[command.split()[3]]
        elif command.startswith("cmd appops set "):
            self.modes[command.split()[3]] = command.split()[-1]
            if self.on_restore:
                self.on_restore(self)
            text = ""
        elif command.startswith("settings get "):
            text = self.awake
        elif command.startswith("settings put "):
            self.awake = command.split()[-1]
            text = ""
        else:
            raise AssertionError("未允许的离线命令：" + command)
        return SimpleNamespace(output=text)

    def ui_shell(self, command):
        self.ui_commands.append(command)
        if command.startswith("am start "):
            self.opened = command.split()[-1]
            self.modes[self.opened] = "allow"
        elif command.startswith("input tap "):
            self.tap_count += 1
            y = int(command.split()[-1])
            index = (y - 550) // 200
            key = [key for key in self.channels if key[0] == self.opened][index]
            name, importance, deleted = self.channels[key]
            self.channels[key] = (name, 0 if importance else 2, deleted)
            if self.on_tap:
                self.on_tap(self)
        elif command != "input keyevent HOME":
            raise AssertionError("未允许的离线 UI 命令：" + command)
        return SimpleNamespace(output="")

    def tree(self):
        root = ET.Element("hierarchy")
        ET.SubElement(root, "node", {"resource-id": hw.HEADER, "text": "样例应用"})
        for index, (key, value) in enumerate(self.channels.items()):
            if key[0] != self.opened:
                continue
            y = 500 + index * 200
            ET.SubElement(root, "node", {"resource-id": hw.CHECKBOX,
                          "class": "android.widget.CheckBox", "content-desc": value[0],
                          "checkable": "true", "enabled": "true",
                          "checked": str(value[1] != 0).lower(),
                          "bounds": f"[900,{y}][1000,{y+100}]"})
        return root

    def sleep(self, seconds):
        self.clock += seconds

    def patches(self):
        stack = ExitStack()
        stack.enter_context(patch.object(hw, "parse", side_effect=lambda reader: (
            copy.deepcopy(self.channels), dict(self.apps))))
        stack.enter_context(patch.object(hw, "Phone", return_value=self.phone))
        stack.enter_context(patch.object(hw, "save_snapshot", return_value=Path("offline.json")))
        stack.enter_context(patch.object(hw, "time", SimpleNamespace(
            monotonic=lambda: self.clock, sleep=self.sleep)))
        stack.enter_context(redirect_stdout(io.StringIO()))
        return stack


class HuaweiChannelsTests(unittest.TestCase):
    def items(self):
        return [hw.Item("com.example.a", "ad1", "营销通知", "样例应用"),
                hw.Item("com.example.a", "ad2", "活动通知", "样例应用")]

    def test_load_requires_current_names_and_deduplicates_identical_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "approved.tsv"
            row = "com.example.a\tad1\t营销通知\t样例应用\n"
            path.write_text("# reviewed\n" + row + row, encoding="utf-8")
            self.assertEqual(hw.load_items(path), self.items()[:1])
            for invalid in ("com.example.a\tad1\t营销通知\n",
                            "com.example.a\ttruncated...\t营销通知\t样例应用\n",
                            row + row.replace("营销通知", "服务通知")):
                path.write_text(invalid, encoding="utf-8")
                with self.assertRaises(ValueError):
                    hw.load_items(path)

    def test_same_app_channels_share_one_page_and_permission_is_restored(self):
        device = OfflineDevice()
        with device.patches():
            result = hw.execute("offline-device", self.items(), reader=device.reader)
        self.assertEqual(result.changed, 2)
        self.assertFalse(result.failed)
        self.assertEqual(len([c for c in device.ui_commands if c.startswith("am start ")]), 1)
        self.assertFalse(any("CHANNEL_NOTIFICATION_SETTINGS" in c for c in device.ui_commands))
        self.assertEqual(device.channels[("com.example.a", "service")][1], 3)
        self.assertEqual(device.modes["com.example.a"], "default")
        self.assertEqual(device.awake, "0")
        device.phone.close.assert_called_once()

    def test_readonly_verify_respects_existing_global_ban(self):
        device = OfflineDevice()
        device.modes["com.example.a"] = "ignore"
        with device.patches():
            result = hw.execute("offline-device", self.items(), verify=True, reader=device.reader)
            hw.Phone.assert_not_called()
            hw.save_snapshot.assert_not_called()
        self.assertEqual(result.blocked, 2)
        self.assertFalse(result.failed)
        self.assertFalse(device.ui_commands)
        self.assertFalse(any(command.startswith("settings put") for command in device.commands))

    def test_restore_on_reopens_only_reviewed_channels(self):
        device = OfflineDevice()
        device.channels[("com.example.a", "ad1")] = ("营销通知", 0, False)
        device.channels[("com.example.a", "ad2")] = ("活动通知", 0, False)
        with device.patches():
            result = hw.execute("offline-device", self.items(), want_on=True, reader=device.reader)
        self.assertEqual(result.changed, 2)
        self.assertFalse(result.failed)
        self.assertTrue(all(device.channels[item.key][1] != 0 for item in self.items()))
        self.assertEqual(device.channels[("com.example.a", "service")][1], 3)
        self.assertEqual(device.modes["com.example.a"], "default")

    def test_snapshot_contains_original_state_and_precedes_any_phone_mutation(self):
        device = OfflineDevice()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(run, "latest_backup", return_value=folder):
                with redirect_stdout(io.StringIO()):
                    path = hw.save_snapshot("offline-device", device.channels, device.apps, device.modes, "0")
            import json
            data = json.loads(path.read_text())
            self.assertEqual(data["stay_on"], "0")
            self.assertEqual(data["permissions"], device.modes)
            self.assertEqual(len(data["channels"]), 3)
        with device.patches():
            def snapshot(*args):
                self.assertEqual(device.awake, "0")
                self.assertFalse(device.ui_commands)
            with patch.object(hw, "save_snapshot", side_effect=snapshot):
                hw.execute("offline-device", self.items(), reader=device.reader)

    def test_permission_cleanup_attempts_remaining_apps_after_a_failure(self):
        modes = {"com.example.a": "allow", "com.example.b": "allow"}
        def shell(command):
            package = command.split()[3]
            if command.startswith("cmd appops set ") and package == "com.example.b":
                modes[package] = "default"
            return SimpleNamespace(output="POST_NOTIFICATION: " + modes[package])
        with self.assertRaisesRegex(RuntimeError, "com.example.a"):
            hw.restore_modes(SimpleNamespace(shell=shell), dict.fromkeys(modes, "default"))
        self.assertEqual(modes["com.example.b"], "default")

    def test_disconnect_stops_permission_cleanup_without_waiting_for_each_app(self):
        reader = Mock()
        reader.shell.side_effect = adb_link.DeviceLost("device offline")
        with self.assertRaises(adb_link.DeviceLost):
            hw.restore_modes(reader, {"com.example.a": "default", "com.example.b": "default"})
        self.assertEqual(reader.shell.call_count, 1)

    def test_unverified_permission_mode_is_rejected_before_any_mutation(self):
        device = OfflineDevice()
        device.modes["com.example.a"] = "foreground"
        with device.patches():
            result = hw.execute("offline-device", self.items(), reader=device.reader)
            hw.Phone.assert_not_called()
            hw.save_snapshot.assert_not_called()
        self.assertEqual(len(result.failed), 2)
        self.assertFalse(device.ui_commands)
        self.assertFalse(any(command.startswith("settings put") for command in device.commands))

    def test_verify_reports_still_open_without_mutating_any_setting(self):
        device = OfflineDevice()
        with device.patches():
            result = hw.execute("offline-device", self.items(), verify=True, reader=device.reader)
            hw.Phone.assert_not_called()
        self.assertEqual(len(result.failed), 2)
        self.assertFalse(device.ui_commands)
        self.assertFalse(any(command.startswith("settings put") for command in device.commands))

    def test_wrong_device_or_build_stops_before_settings_writes(self):
        device = OfflineDevice()
        with device.patches():
            with self.assertRaises(ValueError):
                hw.execute("another-device", self.items(), phone=device.phone, reader=device.reader)
        self.assertFalse(device.commands)
        reader = Mock()
        reader.shell.side_effect = [SimpleNamespace(output=hw.MODEL), SimpleNamespace(output="another-build")]
        with self.assertRaises(ValueError):
            hw.execute("offline-device", self.items(), reader=reader)
        self.assertEqual(reader.shell.call_count, 2)

    def test_renamed_or_missing_channels_never_open_phone_ui(self):
        device = OfflineDevice()
        with device.patches():
            result = hw.execute("offline-device", [
                hw.Item("com.example.a", "ad1", "旧名称", "样例应用"),
                hw.Item("com.example.a", "missing", "营销通知", "样例应用")], reader=device.reader)
            hw.Phone.assert_not_called()
        self.assertEqual(len(result.failed), 2)
        self.assertFalse(device.ui_commands)

    def test_protected_photo_channel_is_not_closed(self):
        device = OfflineDevice()
        device.channels[("com.example.a", "ad1")] = ("找机位推荐", 1, False)
        with device.patches():
            result = hw.execute("offline-device", [hw.Item(
                "com.example.a", "ad1", "找机位推荐", "样例应用")], reader=device.reader)
            hw.Phone.assert_not_called()
        self.assertIn("受保护", result.failed[0])

    def test_unselected_change_stops_and_cleanup_still_restores_runtime_settings(self):
        device = OfflineDevice()
        device.on_tap = lambda d: d.channels.__setitem__(
            ("com.example.a", "service"), ("服务通知", 0, False))
        with device.patches(), self.assertRaisesRegex(RuntimeError, "清单外渠道"):
            hw.execute("offline-device", self.items(), reader=device.reader)
        self.assertEqual(device.tap_count, 1)
        self.assertEqual(device.awake, "0")
        self.assertEqual(device.modes["com.example.a"], "default")

    def test_reopening_another_selected_channel_is_also_an_incident(self):
        device = OfflineDevice()
        def reopen_first(d):
            if d.tap_count == 2:
                d.channels[("com.example.a", "ad1")] = ("营销通知", 1, False)
        device.on_tap = reopen_first
        with device.patches(), self.assertRaisesRegex(RuntimeError, "清单外渠道"):
            hw.execute("offline-device", self.items(), reader=device.reader)
        self.assertEqual(device.tap_count, 2)
        self.assertEqual(device.awake, "0")

    def test_close_failure_cannot_prevent_permission_and_awake_restoration(self):
        device = OfflineDevice()
        device.phone.close.side_effect = RuntimeError("读屏退出失败")
        with device.patches(), self.assertRaisesRegex(RuntimeError, "读屏退出失败"):
            hw.execute("offline-device", self.items(), reader=device.reader)
        self.assertEqual(device.awake, "0")
        self.assertEqual(device.modes["com.example.a"], "default")

    def test_caller_owned_phone_is_not_closed(self):
        device = OfflineDevice()
        with device.patches():
            hw.execute("offline-device", self.items(), phone=device.phone, reader=device.reader)
        device.phone.close.assert_not_called()

    def test_final_verification_catches_changes_after_earlier_success(self):
        device = OfflineDevice()
        device.on_restore = lambda d: d.channels.__setitem__(
            ("com.example.a", "ad1"), ("营销通知", 1, False))
        with device.patches():
            result = hw.execute("offline-device", self.items(), reader=device.reader)
        self.assertTrue(any("最终复查" in failure for failure in result.failed))

    def test_snapshot_failure_prevents_first_mutation(self):
        device = OfflineDevice()
        with device.patches(), patch.object(hw, "save_snapshot", side_effect=OSError("no space")):
            with self.assertRaises(OSError):
                hw.execute("offline-device", self.items(), reader=device.reader)
        self.assertFalse(device.ui_commands)
        self.assertFalse(any(command.startswith("settings put") for command in device.commands))

    def test_widget_handles_duplicate_nodes_and_scrolled_out_header(self):
        device = OfflineDevice()
        device.opened = "com.example.a"
        root = device.tree()
        root.remove(root[0])
        root.append(copy.deepcopy(root[0]))
        device.phone.tree = lambda: root
        self.assertIsNotNone(hw.checkbox(device.phone, "样例应用", "营销通知"))
        root.append(ET.Element("node", {"resource-id": hw.CHECKBOX,
                    "class": "android.widget.CheckBox", "content-desc": "营销通知",
                    "checkable": "true", "enabled": "true", "bounds": "[900,1800][1000,1900]"}))
        self.assertIsNone(hw.checkbox(device.phone, "样例应用", "营销通知"))

    def test_wrong_header_global_switch_or_different_activity_is_rejected(self):
        device = OfflineDevice()
        device.opened = "com.example.a"
        with self.assertRaisesRegex(RuntimeError, "应用身份"):
            hw.checkbox(device.phone, "另一应用", "营销通知")
        device.phone.tree = lambda: ET.fromstring('''<hierarchy>
          <node resource-id="com.android.settings:id/entity_header_title" text="样例应用"/>
          <node resource-id="com.android.settings:id/switch_widget" class="android.widget.Switch"
                content-desc="允许通知" checkable="true" enabled="true" checked="true"
                bounds="[900,300][1000,400]"/>
          </hierarchy>''')
        self.assertIsNone(hw.checkbox(device.phone, "样例应用", "允许通知"))
        device.phone.focus = lambda: "com.huawei.systemmanager/.NotificationSettingsActivity"
        with self.assertRaisesRegex(RuntimeError, "离开"):
            hw.checkbox(device.phone, "样例应用", "营销通知")

    def test_client_does_not_run_it_as_a_recipe(self):
        # 合并 #332 时调整：当成机型脚本时，没有人工审核清单就报失败，
        # 客户端里 ALN-AL00 用户每次都会多一个失败步骤。只作为命令行工具，需显式给清单
        self.assertEqual(run.recipe_for(hw.MODEL, "HUAWEI"), (None, False))
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                hw.main(["-s", "offline-device", "off"])            # 不给清单直接退出，不碰手机


if __name__ == "__main__":
    unittest.main()
