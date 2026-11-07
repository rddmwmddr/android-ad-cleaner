"""#702：ADB 接口没登记 adb 唯一查询的 device interface GUID 时，诊断要说得出来。

Windows 上 adb 只按 {F72FE0D4-CBCB-407D-8814-9ED673D0DD6B} 枚举 USB 接口；
手机只登记了厂商自己的 GUID 时，接口状态一切正常、`adb devices` 却静默为 0 台。
"""
import tempfile
import unittest
from unittest.mock import patch

from gui import app

ADB = "{F72FE0D4-CBCB-407D-8814-9ED673D0DD6B}"
VENDOR = "{8A4D20A8-A2FA-4495-BEE2-E87ECE4A5356}"
HW = "USB\\VID_339B&PID_107D&MI_02"
DEVICE_LINE = f"荣耀 ADB Interface（OK，调试接口）硬件 ID：{HW}"


class UsbFactsGuidTests(unittest.TestCase):
    def test_unregistered_adb_interface_names_the_vendor_guid(self):
        found = [("荣耀", "ADB Interface", "OK", True, HW, (VENDOR,))]
        lines = app.usb_facts(found)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], DEVICE_LINE)
        self.assertIn("未登记", lines[1])
        self.assertIn(VENDOR, lines[1])

    def test_registered_adb_interface_is_not_flagged(self):
        found = [("荣耀", "ADB Interface", "OK", True, HW, (ADB, VENDOR))]
        lines = app.usb_facts(found)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], DEVICE_LINE)
        self.assertIn("已登记", lines[1])
        self.assertNotIn("未登记", lines[1])

    def test_unreadable_guid_leaves_the_line_out(self):
        # 非 Windows、注册表路径不存在、查询报错：这一行不出现，其余各行逐字不变
        found = [("荣耀", "ADB Interface", "OK", True, HW, None)]
        self.assertEqual(app.usb_facts(found), [DEVICE_LINE])

    def test_non_adb_interface_is_not_checked(self):
        found = [("荣耀", "荣耀600 超级版", "OK", False, "USB\\VID_339B&PID_107D&MI_00", (VENDOR,))]
        self.assertEqual(len(app.usb_facts(found)), 1)
        self.assertNotIn("GUID", app.usb_facts(found)[0])

    def test_no_registered_guid_at_all_is_still_reported(self):
        found = [("荣耀", "ADB Interface", "OK", True, HW, ())]
        lines = app.usb_facts(found)
        self.assertIn("未登记", lines[1])
        self.assertIn("没有登记任何 GUID", lines[1])


class UsbParseTests(unittest.TestCase):
    def test_parse_reads_the_guid_field(self):
        out = f"{HW}|ADB Interface|OK|USBDevice|{ADB},{VENDOR}\n"
        found = app.usb_parse(out)
        self.assertEqual(found, [("荣耀", "ADB Interface", "OK", True, HW, (ADB, VENDOR))])

    def test_parse_keeps_unreadable_and_empty_apart(self):
        # `-` 是注册表没读到；空字段是读到了但没登记任何 GUID
        self.assertIsNone(app.usb_parse(f"{HW}|ADB Interface|OK|USBDevice|-\n")[0][5])
        self.assertEqual(app.usb_parse(f"{HW}|ADB Interface|OK|USBDevice|\n")[0][5], ())

    def test_parse_of_a_line_without_the_guid_field_is_unreadable(self):
        # 老格式 / 输出被截断：宁可不说，也不报成「没登记任何 GUID」
        self.assertIsNone(app.usb_parse(f"{HW}|ADB Interface|OK|USBDevice\n")[0][5])


class DiagnosticsTests(unittest.TestCase):
    def test_report_carries_the_guid_line(self):
        # 这一行必须真的进诊断报告，而不只是 usb_facts() 能渲染出来
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        api = app.Api(data.name)
        api.adb = "/opt/tools/adb"
        api.last_devices = "List of devices attached\n"
        found = [("荣耀", "ADB Interface", "OK", True, HW, (VENDOR,))]
        with patch.object(app, "usb_phones", return_value=found), \
             patch.object(api, "_adb", return_value="Android Debug Bridge"):
            report = api.diagnostics()
        self.assertIn(f"- USB 设备：{DEVICE_LINE}", report)
        self.assertIn(f"- USB 设备：荣耀 ADB Interface 未登记 adb 需要的 device interface GUID"
                      f"（实际登记的 GUID：{VENDOR}）", report)


if __name__ == "__main__":
    unittest.main()
