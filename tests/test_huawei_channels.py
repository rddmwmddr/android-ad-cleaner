"""基于 ALN-AL00 已观察页面的脱敏离线回归；不会连接或改变手机。"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import re
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

RECORDED_BUILD = "ALN-AL00 4.2.0.223(C00E215R5P16)"   # 假设备演的是做过路径实测的那台，不跟元组顺序走


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
        self.phone = SimpleNamespace(conn=SimpleNamespace(serial="offline-device"),
                                     W=1080, H=2400, changed=[],
                                     locked=Mock(return_value=False), close=Mock(),
                                     focus=lambda: hw.APP_PAGE, tree=self.tree,
                                     top=Mock(), scroll_more=Mock(return_value=False),
                                     on_screen=lambda node: True)
        # 门面动词：引擎改走 `p.shell()` / `p.window_size()`（沿用 #1476 的做法），桩是同一份 ui_shell。
        self.phone.shell = lambda command, timeout=None: self.ui_shell(command).output
        self.phone.window_size = lambda: (1080, 2400)

    def shell(self, command):
        self.commands.append(command)
        if command == "getprop ro.product.model":
            text = hw.MODEL
        elif command == "getprop ro.build.display.id":
            text = RECORDED_BUILD
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
        # 显式 reader 不该被替换成会连真设备的 ShellPhone：给了 reader 还去建它，直接红。
        stack.enter_context(patch.object(hw, "ShellPhone",
                                         side_effect=AssertionError("显式 reader 不该被替换")))
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
            data = json.loads(path.read_text(encoding="utf-8"))      # Windows 默认 cp1252，读不了中文
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

    def test_build_gate_lists_only_builds_with_evidence(self):
        """R5P16 在本工具上路径实测；R4P16 只有报告者临时实现跑出的页面证据（#1449），门禁认、本工具没跑过。"""
        listed = re.escape("、".join(hw.BUILDS) + "；当前版本未验证")
        def reader(model, build):
            return SimpleNamespace(shell=Mock(side_effect=[
                SimpleNamespace(output=model + "\n"), SimpleNamespace(output=build + "\n")]))
        for build in ("ALN-AL00 4.2.0.223(C00E215R5P16)", "ALN-AL00 4.2.0.223(C00E215R4P16)"):
            with self.subTest(build=build):
                hw.require_device(reader(hw.MODEL, build))
        for model, build in ((hw.MODEL, "ALN-AL00 4.2.0.223(C00E215R3P16)"),
                             (hw.MODEL, "ALN-AL00 4.2.0.223(C00E216R5P16)"),
                             (hw.MODEL, "ALN-AL00 4.2.0.226(C00E215R4P16)"),
                             ("ALN-AL10", "ALN-AL00 4.2.0.223(C00E215R4P16)")):
            with self.subTest(model=model, build=build):
                with self.assertRaisesRegex(ValueError, listed):
                    hw.require_device(reader(model, build))

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


# ---------- #1535：变异判据补的断言 ----------
# 上面一组用例走的是「正常路径 + 少数异常」；下面把每条失败分支、命令行契约与
# 写入磁盘的格式逐条钉住。断言都落在对外可见的结果上（返回值、异常文案、写出的
# 文件、下发给假设备的命令），不锁内部调用序列。


class FlushRecorder(io.StringIO):
    """记录 flush 次数：`print(..., flush=True)` 与默认值的区别只在它身上看得见。"""

    def __init__(self):
        super().__init__()
        self.flushed = 0

    def flush(self):
        self.flushed += 1
        super().flush()


class ListLoadingTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "approved.tsv"
            path.write_text(text, encoding="utf-8")
            return hw.load_items(path)

    def test_a_fifth_column_is_ignored(self):
        self.assertEqual(self.load("com.example.a\tad1\t营销通知\t样例应用\t备注\n"),
                         [hw.Item("com.example.a", "ad1", "营销通知", "样例应用")])

    def test_spaces_inside_a_name_survive(self):
        self.assertEqual(self.load("com.example.a\tad1\t营销 通知\t样例应用\n")[0].name, "营销 通知")

    def test_an_indented_comment_is_skipped(self):
        self.assertEqual(self.load("  # reviewed\ncom.example.a\tad1\t营销通知\t样例应用\n"),
                         [hw.Item("com.example.a", "ad1", "营销通知", "样例应用")])

    def test_every_invalid_column_is_rejected_with_the_same_sentence(self):
        sentence = "第 1 行需要有效包名、完整渠道 ID 和第四列应用名"
        for row in ("com.example.a\tad1\t营销通知\n", "bad-name\tad1\t营销通知\t样例应用\n",
                    "com.example.a\t\t营销通知\t样例应用\n", "com.example.a\tad1\t\t样例应用\n",
                    "com.example.a\tad1\t营销通知\t\n"):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, re.escape(sentence)):
                self.load(row)

    def test_the_line_number_counts_skipped_lines(self):
        with self.assertRaisesRegex(ValueError, "第 3 行"):
            self.load("# reviewed\n\ncom.example.a\tad1\n")

    def test_duplicate_keys_and_renamed_apps_are_rejected_with_the_line(self):
        with self.assertRaisesRegex(ValueError, "第 2 行：同一应用的显示名不一致"):
            self.load("com.example.a\tad1\t营销通知\t样例应用\n"
                      "com.example.a\tad2\t活动通知\t别的名字\n")
        with self.assertRaisesRegex(ValueError, "第 2 行：同一渠道的审核名称不一致"):
            self.load("com.example.a\tad1\t营销通知\t样例应用\n"
                      "com.example.a\tad1\t活动通知\t样例应用\n")


class PermissionModeTests(unittest.TestCase):
    def mode(self, text):
        reader = SimpleNamespace(shell=Mock(return_value=SimpleNamespace(output=text)))
        return hw.permission_mode(reader, "com.example.a"), reader

    def test_the_appops_line_is_read_back(self):
        mode, reader = self.mode("POST_NOTIFICATION: allow\n")
        self.assertEqual(mode, "allow")
        reader.shell.assert_called_once_with("cmd appops get com.example.a POST_NOTIFICATION")

    def test_no_operations_means_default_and_anything_else_is_unknown(self):
        self.assertEqual(self.mode("No operations.\n")[0], "default")
        self.assertEqual(self.mode("something odd\n")[0], "unknown")


class GuardTests(unittest.TestCase):
    def test_an_unlisted_channel_change_names_the_package(self):
        before = {("com.example.a", "ad1"): ("营销通知", 1, False),
                  ("com.example.b", "ad2"): ("活动通知", 2, False)}
        current = {("com.example.a", "ad1"): ("营销通知", 0, False),
                   ("com.example.b", "ad2"): ("活动通知", 0, False)}
        with self.assertRaisesRegex(RuntimeError, "清单外渠道发生变化，停止并保留备份：com.example.b"):
            hw.guard(before, {}, current, {}, {("com.example.a", "ad1")})

    def test_a_global_switch_change_stops_the_run(self):
        with self.assertRaises(RuntimeError) as caught:
            hw.guard({}, {"com.example.a": False}, {}, {"com.example.a": True}, set())
        self.assertEqual(str(caught.exception), "应用通知总开关发生变化，停止并保留备份")


class WidgetTests(unittest.TestCase):
    def test_only_the_header_node_texts_count(self):
        root = ET.fromstring('<hierarchy><node resource-id="%s" text="样例应用"/>'
                             '<node text="别的文字"/></hierarchy>' % hw.HEADER)
        self.assertEqual(hw.headers(root), {"样例应用"})

    def phone(self, tree, on_screen=lambda node: True):
        return SimpleNamespace(focus=lambda: hw.APP_PAGE, tree=lambda: tree, on_screen=on_screen)

    def tree(self, name, attr="text", bounds="[0,0][10,10]"):
        root = ET.Element("hierarchy")
        ET.SubElement(root, "node", {"resource-id": hw.CHECKBOX, "class": "android.widget.CheckBox",
                                     "checkable": "true", "enabled": "true",
                                     "bounds": bounds, attr: name})
        return root

    def test_the_name_may_come_from_text_or_content_desc(self):
        self.assertIsNotNone(hw.checkbox(self.phone(self.tree("营销通知")), "样例应用", "营销通知"))
        self.assertIsNotNone(hw.checkbox(self.phone(self.tree("营销通知", "content-desc")),
                                         "样例应用", "营销通知"))

    def test_on_screen_receives_the_candidate_node(self):
        phone = self.phone(self.tree("营销通知"), on_screen=lambda node: node is not None)
        self.assertIsNotNone(hw.checkbox(phone, "样例应用", "营销通知"))

    def test_duplicate_rows_are_ambiguous(self):
        root = self.tree("营销通知", bounds="[0,0][10,10]")
        ET.SubElement(root, "node", {"resource-id": hw.CHECKBOX, "class": "android.widget.CheckBox",
                                     "checkable": "true", "enabled": "true",
                                     "bounds": "[0,20][10,30]", "text": "营销通知"})
        self.assertIsNone(hw.checkbox(self.phone(root), "样例应用", "营销通知"))

    def test_leaving_the_page_or_another_app_stops_the_click(self):
        phone = self.phone(self.tree("营销通知"))
        phone.focus = lambda: "com.other/.Page"
        with self.assertRaises(RuntimeError) as caught:
            hw.checkbox(phone, "样例应用", "营销通知")
        self.assertEqual(str(caught.exception), "离开已确认的应用通知页，未继续点击")
        root = ET.Element("hierarchy")
        ET.SubElement(root, "node", {"resource-id": hw.HEADER, "text": "另一应用"})
        with self.assertRaises(RuntimeError) as caught:
            hw.checkbox(self.phone(root), "样例应用", "营销通知")
        self.assertEqual(str(caught.exception), "应用身份已变化，未继续点击")


class OpenAppTests(unittest.TestCase):
    def item(self):
        return hw.Item("com.example.a", "ad1", "营销通知", "样例应用")

    def test_the_start_command_is_pinned(self):
        device = OfflineDevice()
        with patch.object(hw, "wait", SimpleNamespace(until=lambda *args, **kwargs: True)):
            hw.open_app(device.phone, self.item())
        self.assertEqual(device.ui_commands[0],
                         "am start -f 0x10008000 -a android.settings.APP_NOTIFICATION_SETTINGS"
                         " --es android.provider.extra.APP_PACKAGE com.example.a")

    def test_a_mismatched_header_keeps_waiting_and_then_fails(self):
        device = OfflineDevice()
        device.phone.tree = lambda: ET.fromstring('<hierarchy><node text="别的"/></hierarchy>')
        with device.patches(), self.assertRaises(RuntimeError) as caught:
            hw.open_app(device.phone, self.item())
        self.assertEqual(str(caught.exception), "未核对到目标应用通知页")

    def test_a_locked_phone_stops_the_wait(self):
        device = OfflineDevice()
        device.phone.locked = Mock(return_value=True)
        device.phone.tree = lambda: ET.fromstring('<hierarchy><node text="别的"/></hierarchy>')
        with device.patches(), self.assertRaises(hw.ScreenLocked) as caught:
            hw.open_app(device.phone, self.item())
        self.assertEqual(str(caught.exception), "手机锁屏，请机主解锁后重跑")

    def test_the_wait_budget_is_pinned(self):
        device = OfflineDevice()
        recorded = {}

        def until(sample, **kwargs):
            recorded.update(kwargs)
            return True

        with patch.object(hw, "wait", SimpleNamespace(until=until)):
            hw.open_app(device.phone, self.item())
        self.assertEqual((recorded["timeout"], recorded["stable"], recorded["poll"]), (8, .2, .15))
        self.assertIs(recorded["now"], hw.time.monotonic)
        self.assertIs(recorded["sleep"], hw.time.sleep)
        self.assertIsNotNone(recorded["blocked"])


class LocateTests(unittest.TestCase):
    def item(self):
        return hw.Item("com.example.a", "ad1", "营销通知", "样例应用")

    def test_top_and_the_scroll_cap_are_pinned(self):
        phone = SimpleNamespace(top=Mock(), locked=Mock(return_value=False),
                                scroll_more=Mock(return_value=True))
        with patch.object(hw, "checkbox", return_value=None) as looked:
            self.assertIsNone(hw.locate(phone, self.item(), "营销通知"))
        phone.top.assert_called_once_with(12)
        self.assertEqual(looked.call_count, 16)

    def test_the_scan_finds_a_node_after_a_scroll(self):
        phone = SimpleNamespace(top=Mock(), locked=Mock(return_value=False),
                                scroll_more=Mock(return_value=True))
        node = Mock()
        with patch.object(hw, "checkbox", side_effect=[None, node]):
            self.assertIs(hw.locate(phone, self.item(), "营销通知"), node)

    def test_a_locked_phone_stops_the_scan(self):
        phone = SimpleNamespace(top=Mock(), locked=Mock(return_value=True),
                                scroll_more=Mock(return_value=False))
        with self.assertRaises(hw.ScreenLocked) as caught:
            hw.locate(phone, self.item(), "营销通知")
        self.assertEqual(str(caught.exception), "手机锁屏，未继续点击")


class SnapshotFileTests(unittest.TestCase):
    def test_the_file_name_and_json_body_are_pinned(self):
        device = OfflineDevice()
        with tempfile.TemporaryDirectory() as folder:
            backup = Mock(return_value=folder)
            out = io.StringIO()
            with patch.object(run, "latest_backup", backup), redirect_stdout(out):
                path = hw.save_snapshot("offline-device", device.channels, device.apps,
                                        device.modes, "0")
            self.assertEqual(backup.call_args.args, ("offline-device",))
            self.assertRegex(path.name, r"^huawei-channels-before-\d{8}-\d{6}-\d{6}\.json$")
            text = path.read_text(encoding="utf-8")
            self.assertIn("营销通知", text)               # ensure_ascii=False
            self.assertIn('\n  "channels": [', text)      # indent=2
            data = json.loads(text)
            self.assertEqual(data["apps"], device.apps)
            self.assertEqual(data["permissions"], device.modes)
            self.assertEqual(data["stay_on"], "0")
            self.assertEqual(len(data["channels"]), 3)
            self.assertEqual(out.getvalue().strip(),
                             "改动前快照已保存到本地 backups/；包含个人渠道资料，请勿提交")


class RestoreModesTests(unittest.TestCase):
    def test_a_non_confirmed_mode_is_never_rewritten(self):
        modes = {"com.example.a": "allow"}
        commands = []

        def shell(command):
            commands.append(command)
            return SimpleNamespace(output="POST_NOTIFICATION: " + modes["com.example.a"])

        with self.assertRaisesRegex(RuntimeError, "通知权限模式未恢复原值：com.example.a"):
            hw.restore_modes(SimpleNamespace(shell=shell), {"com.example.a": "ignore"})
        self.assertEqual(commands, ["cmd appops get com.example.a POST_NOTIFICATION"])
        self.assertEqual(modes["com.example.a"], "allow")

    def test_a_failing_shell_is_collected_with_the_other_failures(self):
        def shell(command):
            if "com.example.b" in command:
                raise OSError("gone")
            return SimpleNamespace(output="POST_NOTIFICATION: allow")

        with self.assertRaises(RuntimeError) as caught:
            hw.restore_modes(SimpleNamespace(shell=shell),
                             {"com.example.a": "default", "com.example.b": "default"})
        self.assertEqual(str(caught.exception),
                         "通知权限模式未恢复原值：com.example.a、com.example.b")

    def test_a_confirmed_default_is_rewritten_back(self):
        modes = {"com.example.a": "allow"}
        commands = []

        def shell(command):
            commands.append(command)
            if command.startswith("cmd appops set "):
                modes["com.example.a"] = "default"
            return SimpleNamespace(output="POST_NOTIFICATION: " + modes["com.example.a"])

        hw.restore_modes(SimpleNamespace(shell=shell), {"com.example.a": "default"})
        self.assertEqual(commands, ["cmd appops get com.example.a POST_NOTIFICATION",
                                    "cmd appops set com.example.a POST_NOTIFICATION default",
                                    "cmd appops get com.example.a POST_NOTIFICATION"])


class MainTests(unittest.TestCase):
    def item(self):
        return hw.Item("com.example.a", "ad1", "营销通知", "样例应用")

    def test_each_action_maps_to_the_execute_flags(self):
        seen = []

        def execute(serial, items, **kwargs):
            seen.append((serial, items, kwargs))
            return hw.Result()

        with patch.object(hw, "execute", side_effect=execute), \
             patch.object(hw, "load_items", return_value=[self.item()]) as loaded:
            for action, flags in (("off", (False, False)), ("on", (True, False)),
                                  ("verify", (False, True))):
                seen.clear()
                with redirect_stdout(io.StringIO()):
                    code = hw.main(["-s", "offline-device", action, "approved.tsv"])
                self.assertEqual(code, 0)
                self.assertEqual(seen, [("offline-device", [self.item()],
                                         {"want_on": flags[0], "verify": flags[1]})])
                self.assertEqual(loaded.call_args.args, (Path("approved.tsv"),))

    def test_the_summary_and_each_failure_are_printed_once(self):
        result = hw.Result(changed=2, already=1, blocked=3, failed=["x", "x", "y"])
        out = io.StringIO()
        with patch.object(hw, "execute", return_value=result), \
             patch.object(hw, "load_items", return_value=[]), redirect_stdout(out):
            code = hw.main(["-s", "S", "off", "approved.tsv"])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue().splitlines(), [
            "调整 2 项，已是目标状态 1 项，原有总通知屏蔽 3 项",
            "未完成：x", "未完成：y"])

    def test_disconnect_and_other_errors_take_the_two_exits(self):
        err = io.StringIO()
        with patch.object(hw, "execute", side_effect=adb_link.DeviceLost("断开了")), \
             patch.object(hw, "load_items", return_value=[]), \
             redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(hw.main(["-s", "S", "off", "approved.tsv"]), 1)
        self.assertEqual(err.getvalue().strip(), "断开了")
        out = io.StringIO()
        with patch.object(hw, "execute", side_effect=RuntimeError("坏了")), \
             patch.object(hw, "load_items", return_value=[]), redirect_stdout(out):
            self.assertEqual(hw.main(["-s", "S", "off", "approved.tsv"]), 1)
        self.assertEqual(out.getvalue().strip(), "未完成：坏了")

    def test_the_cli_contract_is_pinned(self):
        help_out = io.StringIO()
        with redirect_stdout(help_out), self.assertRaises(SystemExit):
            hw.main(["-h"])
        self.assertIn(hw.__doc__.splitlines()[0], help_out.getvalue())
        self.assertIn("--serial", help_out.getvalue())
        for argv in (["off", "approved.tsv"], ["-s", "S", "bogus", "approved.tsv"],
                     ["-s", "S", "off"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit):
                hw.main(argv)
        with patch.object(hw, "execute", return_value=hw.Result()), \
             patch.object(hw, "load_items", return_value=[]), redirect_stdout(io.StringIO()):
            self.assertEqual(hw.main(["--serial", "S", "off", "approved.tsv"]), 0)


class ExecuteTests(unittest.TestCase):
    """execute 的每条失败分支：在假设备上走到那一步，断言它对外给出的结果。"""

    def item(self, channel="ad1", name="营销通知", app="样例应用", package="com.example.a"):
        return hw.Item(package, channel, name, app)

    def run_execute(self, device, items, **kwargs):
        with device.patches():
            return hw.execute("offline-device", items, reader=device.reader, **kwargs)

    def test_failed_reasons_are_the_exact_sentences(self):
        device = OfflineDevice()
        result = self.run_execute(device, [
            self.item(channel="missing"),
            self.item(name="旧名称"),
        ])
        self.assertEqual(result.failed, ["样例应用：渠道不存在或已删除",
                                         "样例应用：渠道名已变化，请重新审核清单"])
        self.assertFalse(device.ui_commands)

    def test_a_protected_channel_is_reported_verbatim(self):
        device = OfflineDevice()
        device.channels[("com.example.a", "ad1")] = ("找机位推荐", 1, False)
        result = self.run_execute(device, [self.item(name="找机位推荐")])
        self.assertEqual(result.failed, ["样例应用：受保护的功能通知，未关闭"])

    def test_an_app_wide_ban_blocks_the_channel(self):
        device = OfflineDevice()
        device.apps = {"com.example.a": True}
        result = self.run_execute(device, [self.item()])
        self.assertEqual((result.blocked, result.failed), (1, []))
        self.assertFalse(device.ui_commands)

    def test_restoring_a_blocked_app_says_why_it_was_skipped(self):
        device = OfflineDevice()
        device.apps = {"com.example.a": True}
        device.channels[("com.example.a", "ad1")] = ("营销通知", 0, False)
        result = self.run_execute(device, [self.item()], want_on=True)
        self.assertEqual((result.blocked, result.failed),
                         (1, ["样例应用：应用通知原已禁止，未自动开启总开关"]))

    def test_an_unverified_mode_is_reported_and_an_allow_proceeds(self):
        device = OfflineDevice()
        device.modes = {"com.example.a": "foreground"}
        result = self.run_execute(device, [self.item()])
        self.assertEqual(result.failed, ["样例应用：通知权限模式未识别或未验证，未修改"])
        device = OfflineDevice()
        device.modes = {"com.example.a": "allow"}
        result = self.run_execute(device, [self.item()])
        self.assertEqual((result.changed, result.failed), (1, []))

    def test_verify_reports_the_unreached_state_verbatim(self):
        device = OfflineDevice()
        result = self.run_execute(device, [self.item()], verify=True)
        self.assertEqual(result.failed, ["样例应用 / 营销通知：尚未达到目标状态"])

    def test_already_target_items_are_counted(self):
        device = OfflineDevice()
        device.channels[("com.example.a", "ad1")] = ("营销通知", 0, False)
        device.channels[("com.example.a", "ad2")] = ("活动通知", 0, False)
        result = self.run_execute(device, [self.item(), self.item(channel="ad2", name="活动通知")])
        self.assertEqual((result.already, result.changed, result.failed), (2, 0, []))
        self.assertFalse(device.ui_commands)

    def test_channels_that_become_targets_mid_batch_count_as_already(self):
        device = OfflineDevice()
        device.channels[("com.example.a", "ad3")] = ("推荐通知", 1, False)
        items = [self.item(), self.item(channel="ad2", name="活动通知"),
                 self.item(channel="ad3", name="推荐通知")]
        start = copy.deepcopy(device.channels)
        after_first = copy.deepcopy(start)
        after_first[("com.example.a", "ad1")] = ("营销通知", 0, False)
        second_off = copy.deepcopy(after_first)
        second_off[("com.example.a", "ad2")] = ("活动通知", 0, False)
        all_off = copy.deepcopy(second_off)
        all_off[("com.example.a", "ad3")] = ("推荐通知", 0, False)
        states = iter([start, start, after_first, second_off, all_off, all_off])
        with device.patches(), patch.object(hw, "parse", side_effect=lambda reader: (
                copy.deepcopy(next(states)), dict(device.apps))):
            result = hw.execute("offline-device", items, reader=device.reader)
        self.assertEqual((result.already, result.changed, result.failed), (2, 1, []))

    def test_a_phone_bound_to_another_serial_is_rejected(self):
        device = OfflineDevice()
        device.phone.conn.serial = "another"
        with device.patches(), self.assertRaises(ValueError) as caught:
            hw.execute("offline-device", [self.item()], phone=device.phone, reader=device.reader)
        self.assertEqual(str(caught.exception), "读屏设备和指定序列号不一致，未修改")

    def test_the_reader_defaults_to_the_given_serial(self):
        device = OfflineDevice()
        with device.patches(), patch.object(hw, "ShellPhone", return_value=device.reader) as made:
            hw.execute("offline-device", [self.item()])
        made.assert_called_once_with("offline-device")

    def test_parse_always_reads_the_same_reader(self):
        device = OfflineDevice()
        seen = []

        def parse(reader):
            seen.append(reader)
            return copy.deepcopy(device.channels), dict(device.apps)

        with device.patches(), patch.object(hw, "parse", side_effect=parse):
            hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertTrue(seen and all(reader is device.reader for reader in seen))

    def test_the_phone_is_opened_once_for_the_given_serial(self):
        device = OfflineDevice()
        with device.patches():
            hw.execute("offline-device", [self.item()], reader=device.reader)
            hw.Phone.assert_called_once_with("offline-device", log=False)
            self.assertEqual(device.phone.changed, [("样例应用", "营销通知")])

    def test_a_caller_owned_phone_is_reused(self):
        device = OfflineDevice()
        with device.patches():
            hw.execute("offline-device", [self.item()], phone=device.phone, reader=device.reader)
            hw.Phone.assert_not_called()

    def test_the_snapshot_is_written_from_the_original_state(self):
        device = OfflineDevice()
        initial = copy.deepcopy(device.channels)
        with device.patches():
            hw.execute("offline-device", [self.item()], reader=device.reader)
            args = hw.save_snapshot.call_args.args
        self.assertEqual(args, ("offline-device", initial, {"com.example.a": False},
                                {"com.example.a": "default"}, "0"))

    def test_a_deleted_record_after_opening_the_page_stops_the_click(self):
        device = OfflineDevice()
        original = copy.deepcopy(device.channels)
        deleted = copy.deepcopy(original)
        deleted[("com.example.a", "ad1")] = ("营销通知", 1, True)
        states = iter([original, deleted])
        with device.patches(), patch.object(hw, "parse", side_effect=lambda reader: (
                copy.deepcopy(next(states)), dict(device.apps))):
            with self.assertRaises(RuntimeError) as caught:
                hw.execute("offline-device", [self.item()], reader=device.reader)
            self.assertEqual(str(caught.exception), "渠道记录已变化，未继续点击")

    def test_a_deleted_record_after_the_tap_is_not_a_success(self):
        device = OfflineDevice()
        original = copy.deepcopy(device.channels)
        deleted = copy.deepcopy(original)
        deleted[("com.example.a", "ad1")] = ("营销通知", 1, True)
        states = iter([original, original, deleted, original])
        with device.patches(), patch.object(hw, "parse", side_effect=lambda reader: (
                copy.deepcopy(next(states)), dict(device.apps))):
            with self.assertRaises(RuntimeError) as caught:
                hw.execute("offline-device", [self.item()], reader=device.reader)
            self.assertEqual(str(caught.exception), "点击后渠道记录已变化，未确认目标状态")

    def test_a_duplicated_name_is_never_guessed_and_later_items_still_run(self):
        device = OfflineDevice()
        device.channels[("com.example.a", "ad2")] = ("营销通知", 2, False)
        result = self.run_execute(device, [self.item(), self.item(channel="service", name="服务通知")])
        self.assertEqual(result.failed[0], "样例应用：渠道名不唯一，未猜测渠道 ID")
        self.assertEqual(result.changed, 1)

    def test_a_checked_state_mismatch_is_not_a_tap_and_later_items_still_run(self):
        device = OfflineDevice()
        real_tree = device.tree

        def tree():
            root = real_tree()
            for node in root.iter():
                if node.get("content-desc") == "营销通知":
                    node.set("checked", "false")
            return root

        device.phone.tree = tree
        result = self.run_execute(device, [self.item(), self.item(channel="service", name="服务通知")])
        self.assertEqual(result.failed[0], "样例应用 / 营销通知：未确认独立复选框或状态不一致")
        self.assertEqual(result.changed, 1)

    def test_a_size_change_abandons_the_stale_coordinates(self):
        device = OfflineDevice()
        device.phone.window_size = lambda: (1080, 2300)
        with device.patches(), self.assertRaises(RuntimeError) as caught:
            hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertEqual(str(caught.exception), "锁屏或尺寸变化，未使用旧坐标")

    def test_a_missing_stay_on_value_stops_before_writing(self):
        device = OfflineDevice()
        device.awake = ""
        with device.patches(), self.assertRaises(RuntimeError) as caught:
            hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertEqual(str(caught.exception), "读不到插电常亮原值，未修改")
        self.assertFalse(any(command.startswith("settings put") for command in device.commands))

    def test_a_failed_stay_on_restore_is_reported(self):
        device = OfflineDevice()
        real = device.shell

        def shell(command):
            if command == "settings put global stay_on_while_plugged_in 0":
                return SimpleNamespace(output="")
            return real(command)

        device.reader.shell = shell
        with device.patches(), self.assertRaises(RuntimeError) as caught:
            hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertEqual(str(caught.exception), "插电常亮未恢复，请按备份手动核对")

    def test_a_permission_mode_change_after_restore_is_reported(self):
        device = OfflineDevice()
        original = copy.deepcopy(device.channels)
        calls = []

        def parse(reader):
            calls.append(1)
            if len(calls) == 4:                       # 收尾复查前才变
                device.modes["com.example.a"] = "allow"
            return copy.deepcopy(original), dict(device.apps)

        with device.patches(), patch.object(hw, "parse", side_effect=parse):
            with self.assertRaises(RuntimeError) as caught:
                hw.execute("offline-device", [self.item()], reader=device.reader)
            self.assertEqual(str(caught.exception), "候选应用通知权限模式发生变化，请按快照核对")

    def test_each_click_is_announced_with_flush(self):
        device = OfflineDevice()
        recorder = FlushRecorder()
        with device.patches(), redirect_stdout(recorder):
            hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertEqual(recorder.getvalue().splitlines(), ["即将关闭：样例应用 / 营销通知"])
        self.assertEqual(recorder.flushed, 1)
        device = OfflineDevice()
        device.channels[("com.example.a", "ad1")] = ("营销通知", 0, False)
        recorder = FlushRecorder()
        with device.patches(), redirect_stdout(recorder):
            hw.execute("offline-device", [self.item()], want_on=True, reader=device.reader)
        self.assertEqual(recorder.getvalue().splitlines(), ["即将恢复：样例应用 / 营销通知"])

    def test_the_tap_uses_the_node_centre_and_waits_a_third_of_a_second(self):
        device = OfflineDevice()
        tapped = {}
        device.on_tap = lambda d: tapped.setdefault("clock", d.clock)
        with device.patches():
            hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertIn("input tap 950 550", device.ui_commands)
        self.assertAlmostEqual(device.clock - tapped["clock"], .3)

    def test_a_locked_phone_before_the_click_stops_the_run(self):
        device = OfflineDevice()
        device.phone.locked = Mock(return_value=True)
        with device.patches(), self.assertRaises(hw.ScreenLocked) as caught:
            hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertEqual(str(caught.exception), "手机锁屏，请机主解锁后重跑")

    def test_a_tap_that_does_not_take_is_reported(self):
        device = OfflineDevice()
        original = copy.deepcopy(device.channels)
        states = iter([original, original, original, original])
        with device.patches(), patch.object(hw, "parse", side_effect=lambda reader: (
                copy.deepcopy(next(states)), dict(device.apps))):
            result = hw.execute("offline-device", [self.item()], reader=device.reader)
        self.assertEqual(result.failed[0], "样例应用 / 营销通知：回读未确认")

    def test_a_supplied_reader_is_not_replaced(self):
        device = OfflineDevice()
        with device.patches(), patch.object(hw, "ShellPhone") as made:
            hw.execute("offline-device", [self.item()], reader=device.reader)
        made.assert_not_called()

    def test_a_protected_channel_id_outranks_a_neutral_name(self):
        device = OfflineDevice()
        device.channels[("com.example.a", "机位推荐")] = ("相册推荐", 1, False)
        result = self.run_execute(device, [self.item(channel="机位推荐", name="相册推荐")])
        self.assertEqual(result.failed, ["样例应用：受保护的功能通知，未关闭"])

    def test_the_final_check_reports_the_exact_sentence(self):
        device = OfflineDevice()
        device.on_restore = lambda d: d.channels.__setitem__(
            ("com.example.a", "ad1"), ("营销通知", 1, False))
        result = self.run_execute(device, [self.item()])
        self.assertEqual(result.failed, ["样例应用 / 营销通知：最终复查未达目标"])


if __name__ == "__main__":
    unittest.main()
