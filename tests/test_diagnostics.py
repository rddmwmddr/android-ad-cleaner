"""诊断文本的唯一定义（#1376）：给定一份 state 与两个探针查询，整段输出逐字等于什么。

期望值取自搬前基线：同一装置的 32 组 state 先喂给 `origin/main @ 67ce5e07` 的 `Api.diagnostics()`
取文本，搬到 `tool/diagnostics.py` 后逐字比对，零差异。所以这里断言的是整段输出而不是子串——
措辞回归会整条红，能直接指出是哪一档分支。分支只由 state 与 probe 给，用例不构造 `Api`、不碰手机。

USB 的纯函数（`usb_parse` / `usb_hw_id` / `usb_facts` / `usb_hint`，以及 `usb_facts` 内部用的
`usb_guid_note`）由 `tests/test_page_and_link_regressions.py` 与 `tests/test_adb_link.py` 覆盖，
本文件只补一条从模块直调的：客户端包装 `gui.app.usb_facts()` 每次都显式传 `limit`，默认条数只有
直接调本模块才走得到。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import diagnostics

CLIENT = "- 客户端：肉呆去广告 0.4.4（源码）"
COMPUTER = "- 电脑：Windows 11（10.0.26100）（AMD64）"
ADB_OK = "- adb：Android Debug Bridge version 1.0.41"
ONE_DEVICE = "- adb 设备：1 台（device）"
NO_DEVICE = "- adb 设备：0 台"
NO_PHONE = "- 手机：还没检测"
PHONE = "- 手机：Xiaomi 13（M154FF）"
SYSTEM = "- 系统：OS3.0.308.0（OS3.0.308.0），Android 16"
FOLD_OFF = "- 折叠屏展开：否；锁屏：是"
FOLD_ON = "- 折叠屏展开：是；锁屏：是"
TAP_REFUSED = "；电脑点击被拒（未开 USB 调试安全设置）"
ADB_PATH = "/opt/tools/adb"
HEADER = (CLIENT, COMPUTER)

INFO = {"brand": "Xiaomi", "name": "Xiaomi 13", "model": "M154FF", "os": "OS3.0.308.0",
        "build": "OS3.0.308.0", "android": "16"}
# 一台登记了调试接口、但没登记 adb 要的那个 GUID 的荣耀手机（一行的 GUID 字段是 `-`：没读到）
USB_ONE = ("荣耀", "ADB Interface", "OK", True, "USB\\VID_339B&PID_107D&MI_02", None)
USB_TWO = [("荣耀", "ADB Interface", "OK", True, "USB\\VID_339B&PID_107D&MI_02", ()),
           ("华硕", "ROG Phone", "OK", True, "USB\\VID_0B05&PID_1ABC", None)]


def status(**extra):
    st = {"info": dict(INFO), "recipe": "xiaomi-M154FF", "recipe_ref": False,
          "recipe_build": "OS3.0.308.0", "recipe_ok": True, "fold_open": False,
          "locked": True, "input_blocked": False}
    st.update(extra)
    return st


def state(**extra):
    """默认这一份：adb 正常、连着 1 台、还没检测过手机、没有执行与失败记录。"""
    base = {"app": "肉呆去广告", "version": "0.4.4", "frozen": False,
            "os": "Windows 11（10.0.26100）", "machine": "AMD64",
            "adb": ADB_PATH, "other_adb": [], "devices": ("device",),
            "status": None, "scan_notes": [], "job": None, "last_error": None,
            "tap_refused": TAP_REFUSED, "home": "/home/tester"}
    base.update(extra)
    return base


def job_view(**extra):
    view = {"serial": "TESTSERIAL01", "results": [], "log": []}
    view.update(extra)
    return view


class Probe:
    """两个本机查询的替身；`usb_calls` 记调用次数，用来证明惰性。"""

    def __init__(self, version="Android Debug Bridge version 1.0.41", usb=()):
        self.version = version
        self.usb = list(usb)
        self.usb_calls = 0

    def adb_version(self):
        return self.version

    def usb_devices(self):
        self.usb_calls += 1
        return list(self.usb)


def text(probe=None, **extra):
    return diagnostics.diagnostics(state(**extra), probe or Probe())


def report(*lines):
    return "\n".join(lines)


class ClientLineTests(unittest.TestCase):
    def test_a_frozen_client_is_reported_as_packaged(self):
        self.assertEqual(text(frozen=True),
                         report("- 客户端：肉呆去广告 0.4.4（打包版）", COMPUTER, ADB_OK, ONE_DEVICE, NO_PHONE))


class AdbLineTests(unittest.TestCase):
    def test_the_line_is_whatever_the_probe_says(self):
        for version in ("Android Debug Bridge version 1.0.41", "没有 adb", "adb 出错：device offline"):
            with self.subTest(version=version):
                self.assertEqual(text(Probe(version)),
                                 report(*HEADER, f"- adb：{version}", ONE_DEVICE, NO_PHONE))


class DeviceLineTests(unittest.TestCase):
    def test_counts_the_devices_and_names_their_states(self):
        cases = [((), NO_DEVICE), (("device",), ONE_DEVICE),
                 (("device", "unauthorized"), "- adb 设备：2 台（device、unauthorized）")]
        for devices, line in cases:
            with self.subTest(devices=devices):
                self.assertEqual(text(devices=devices),
                                 report(*HEADER, ADB_OK, line, NO_PHONE))


class OtherAdbTests(unittest.TestCase):
    def test_our_own_adb_is_not_named_again(self):
        self.assertEqual(
            text(other_adb=[ADB_PATH, "C:/Phone/Helper/adb.exe", "/usr/bin/adb"]),
            report(*HEADER, ADB_OK, ONE_DEVICE,
                   "- 其他正在运行的 adb：C:/Phone/Helper/adb.exe；/usr/bin/adb", NO_PHONE))

    def test_no_line_when_nothing_else_is_running(self):
        self.assertEqual(text(other_adb=[]), report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE))

    def test_without_an_adb_of_our_own_every_path_is_kept(self):
        self.assertEqual(text(Probe("没有 adb"), adb=None, other_adb=["/usr/bin/adb"]),
                         report(*HEADER, "- adb：没有 adb", ONE_DEVICE,
                                "- 其他正在运行的 adb：/usr/bin/adb", NO_PHONE))


class UsbTests(unittest.TestCase):
    def test_the_usb_probe_is_asked_only_when_adb_sees_nothing(self):
        probe = Probe(usb=[USB_ONE])
        self.assertEqual(
            text(probe, devices=()),
            report(*HEADER, ADB_OK, NO_DEVICE,
                   "- USB：电脑识别到荣耀手机的调试接口，但 adb 没连上：请退出手机助手类软件和模拟器后重新插线。"
                   "开发者选项里同时打开「仅充电模式下允许 ADB 调试」。驱动可装荣耀手机助手获取，装好后退出手机助手再用本工具。",
                   "- USB 设备：荣耀 ADB Interface（OK，调试接口）硬件 ID：USB\\VID_339B&PID_107D&MI_02",
                   NO_PHONE))
        self.assertEqual(probe.usb_calls, 1)

    def test_nothing_hit_leaves_no_usb_line(self):
        self.assertEqual(text(Probe(), devices=()),
                         report(*HEADER, ADB_OK, NO_DEVICE, NO_PHONE))

    def test_every_hit_phone_is_listed_with_its_guid_line(self):
        self.assertEqual(
            text(Probe(usb=USB_TWO), devices=()),
            report(*HEADER, ADB_OK, NO_DEVICE,
                   "- USB：电脑识别到多台手机：荣耀（调试接口在，但 adb 没连上）、华硕（调试接口在，但 adb 没连上）。"
                   "只留要处理的那一台插着，重新插线后再检测。",
                   "- USB 设备：荣耀 ADB Interface（OK，调试接口）硬件 ID：USB\\VID_339B&PID_107D&MI_02",
                   "- USB 设备：荣耀 ADB Interface 未登记 adb 需要的 device interface GUID，也没有登记任何 GUID",
                   "- USB 设备：华硕 ROG Phone（OK，调试接口）硬件 ID：USB\\VID_0B05&PID_1ABC",
                   NO_PHONE))

    def test_a_connected_device_never_triggers_the_usb_probe(self):
        probe = Probe(usb=[USB_ONE])
        self.assertEqual(text(probe), report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE))
        self.assertEqual(probe.usb_calls, 0)


class UsbFactsDefaultTests(unittest.TestCase):
    def test_the_default_limit_is_five_devices(self):
        found = [("安卓", f"外设 {i}", "OK", False, f"USB\\VID_05C6&PID_900{i}", None) for i in range(6)]
        self.assertEqual(len(diagnostics.usb_facts(found)), 5)


class PhoneStatusTests(unittest.TestCase):
    def test_no_info_means_not_detected_yet(self):
        for st in (None, {"recipe": "xiaomi-M154FF"}):
            with self.subTest(status=st):
                self.assertEqual(text(status=st), report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE))

    def test_borrowed_reference_script_is_not_a_version_mismatch(self):
        st = status(recipe="xiaomi-M154FF-ref", recipe_ref=True,
                    recipe_build="OS3.0.300.0", recipe_ok=False)
        self.assertEqual(text(status=st),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF-ref（同品牌参考脚本，录制版本 OS3.0.300.0）", FOLD_OFF))

    def test_borrowed_reference_script_without_a_recorded_version(self):
        st = status(recipe="xiaomi-M154FF-ref", recipe_ref=True, recipe_build="", recipe_ok=False)
        self.assertEqual(text(status=st),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF-ref（同品牌参考脚本，录制版本 未标）", FOLD_OFF))

    def test_own_script_keeps_the_version_comparison(self):
        self.assertEqual(text(status=status()),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.308.0，一致）", FOLD_OFF))
        self.assertEqual(text(status=status(recipe_build="OS3.0.300.0", recipe_ok=False)),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.300.0，不一致）", FOLD_OFF))

    def test_own_script_without_a_recorded_version_says_unmarked(self):
        self.assertEqual(text(status=status(recipe_build="", recipe_ok=False)),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 未标）", FOLD_OFF))

    def test_no_script_stays_no_script(self):
        self.assertEqual(text(status=status(recipe="", recipe_build="")),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：无", FOLD_OFF))

    def test_a_name_without_the_brand_gets_the_brand_prefixed(self):
        """`info` 的 name 不带品牌时诊断自己补上，否则报告里那台机认不出是谁（基线 1644 行那个分支）。"""
        self.assertEqual(text(status={**status(), "info": dict(INFO, name="13")}),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.308.0，一致）", FOLD_OFF))

    def test_a_missing_name_falls_back_to_the_model(self):
        info = {key: value for key, value in INFO.items() if key != "name"}
        self.assertEqual(text(status=status(info=info)),
                         report(*HEADER, ADB_OK, ONE_DEVICE, "- 手机：Xiaomi M154FF（M154FF）", SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.308.0，一致）", FOLD_OFF))

    def test_a_missing_brand_does_not_prefix_the_name(self):
        info = {key: value for key, value in INFO.items() if key != "brand"}
        self.assertEqual(text(status=status(info=info)),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.308.0，一致）", FOLD_OFF))

    def test_a_missing_os_falls_back_to_the_build(self):
        info = {key: value for key, value in INFO.items() if key != "os"}
        self.assertEqual(text(status=status(info=info)),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.308.0，一致）", FOLD_OFF))

    def test_fold_open_is_reported(self):
        self.assertEqual(text(status=status(fold_open=True)),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.308.0，一致）", FOLD_ON))

    def test_a_refused_tap_uses_the_callers_wording(self):
        self.assertEqual(text(status=status(input_blocked=True)),
                         report(*HEADER, ADB_OK, ONE_DEVICE, PHONE, SYSTEM,
                                "- 机型脚本：xiaomi-M154FF（录制版本 OS3.0.308.0，一致）", FOLD_OFF + TAP_REFUSED))


class ScanNoteTests(unittest.TestCase):
    def test_notes_come_on_one_line(self):
        notes = ["排除 3 个系统渠道",
                 "另有 2 个渠道属于系统锁定、不允许关闭的系统应用，未列入清单"]
        self.assertEqual(text(scan_notes=notes),
                         report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE,
                                "- 通知扫描附注：排除 3 个系统渠道；"
                                "另有 2 个渠道属于系统锁定、不允许关闭的系统应用，未列入清单"))

    def test_no_notes_no_line(self):
        self.assertNotIn("通知扫描附注", text(scan_notes=[]))


class ExecutionTests(unittest.TestCase):
    def test_each_result_row_says_success_failure_or_the_skip_reason(self):
        results = [{"title": "备份", "rc": 0, "sec": 1, "skipped": False, "reason": ""},
                   {"title": "广告开关", "rc": 2, "sec": 30, "skipped": False, "reason": ""},
                   {"title": "关闭营销通知", "rc": 0, "sec": 0, "skipped": True,
                    "reason": "读屏服务仍被占用，跳过本步骤"},
                   {"title": "收尾", "rc": 0, "sec": 1, "skipped": True, "reason": ""}]
        self.assertEqual(text(job=job_view(results=results, log=["ok"])),
                         report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE,
                                "", "**执行结果**", "",
                                "- 备份：成功，1 秒",
                                "- 广告开关：失败（退出码 2），30 秒",
                                "- 关闭营销通知：跳过（读屏服务仍被占用，跳过本步骤），0 秒",
                                "- 收尾：跳过，1 秒",
                                "", "<details><summary>最近的日志</summary>", "",
                                "```text", "ok", "```", "</details>"))

    def test_the_log_tail_is_scrubbed_of_the_serial(self):
        job = job_view(results=[{"title": "备份", "rc": 0, "sec": 1, "skipped": False, "reason": ""}],
                       log=["TESTSERIAL01 connected", "备份到 backups/x"])
        self.assertEqual(text(job=job),
                         report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE,
                                "", "**执行结果**", "", "- 备份：成功，1 秒",
                                "", "<details><summary>最近的日志</summary>", "",
                                "```text", "<序列号> connected", "备份到 backups/x", "```", "</details>"))

    def test_the_home_directory_is_scrubbed_in_the_whole_report(self):
        job = job_view(results=[{"title": "备份", "rc": 0, "sec": 1, "skipped": False, "reason": ""}],
                       log=["save to /home/tester/backups/x"])
        self.assertEqual(text(job=job),
                         report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE,
                                "", "**执行结果**", "", "- 备份：成功，1 秒",
                                "", "<details><summary>最近的日志</summary>", "",
                                "```text", "save to <用户目录>/backups/x", "```", "</details>"))

    def test_a_windows_home_is_scrubbed_in_both_spellings(self):
        # 日志里既有原样的 `C:\Users\...`，也有被转义成双反斜杠的那一份：两种都要换成占位符
        job = job_view(results=[{"title": "备份", "rc": 0, "sec": 1, "skipped": False, "reason": ""}],
                       log=[r"save to C:\Users\tester\a", r"save to C:\\Users\\tester\\b"])
        self.assertEqual(text(job=job, home="C:\\Users\\tester"),
                         report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE,
                                "", "**执行结果**", "", "- 备份：成功，1 秒",
                                "", "<details><summary>最近的日志</summary>", "",
                                "```text", "save to <用户目录>\\a", "save to <用户目录>\\\\b",
                                "```", "</details>"))

    def test_no_job_no_execution_section(self):
        self.assertNotIn("执行结果", text(job=None))


class LastErrorTests(unittest.TestCase):
    def test_the_full_failure_is_fenced_off_safely(self):
        detail = "java.lang.IllegalStateException: root cause\n```\nfenced\n```"
        self.assertEqual(
            text(last_error={"operation": "通知扫描", "detail": detail}),
            report(*HEADER, ADB_OK, ONE_DEVICE, NO_PHONE,
                   "", "<details><summary>最近失败的完整诊断：通知扫描</summary>", "",
                   "```text", "java.lang.IllegalStateException: root cause", "~~~", "fenced", "~~~",
                   "```", "</details>"))

    def test_no_failure_no_section(self):
        self.assertNotIn("最近失败的完整诊断", text(last_error=None))


if __name__ == "__main__":
    unittest.main()
