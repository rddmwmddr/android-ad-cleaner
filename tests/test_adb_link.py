"""手机连接：adb 在哪、断线怎么判、读屏失败怎么收场。

假 transport 顶替真 adb：按顺序回答「成功 / 断线 / 其它失败」，并记下收到的命令。
后并入的票号文件按主题接在下面，各自的来源与票号写在那段注释里。
"""
import contextlib
import io
import json
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))
import adb_link
import chan_fast as chan
import events
import fast
import run
from fixtures import (Clock, FakeProc, FakeRunner, fake_phone, job_stub, load_tool)
from phone import connection as phone_connection
from aac_android import screen

BROKEN = adb_link.LinkBroken("adb: device 'S' not found")


class FakeAdb:
    """假 transport。answer 是 (stdout, stderr, returncode) 或要抛出的异常。"""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, command, timeout=None):
        self.calls.append((command, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return adb_link.ShellResult(*answer)


class ShellPolicyTests(unittest.TestCase):
    """一次断线等手机回来重试一次；确认断开后只报 REPEAT，不再碰传输。"""

    def test_broken_link_waits_then_retries_once(self):
        adb = FakeAdb(BROKEN, ("ok", "", 0))
        link = adb_link.Connection("S", transport=adb)
        with patch.object(adb_link, "wait_for", return_value=True) as waited:
            self.assertEqual(link.shell("getprop x").output, "ok")
        self.assertEqual([c[0] for c in adb.calls], ["getprop x", "getprop x"])
        waited.assert_called_once_with("S", None)
        self.assertFalse(link.lost)

    def test_confirmed_loss_reports_the_hint_once(self):
        link = adb_link.Connection("S", transport=FakeAdb(BROKEN))
        with patch.object(adb_link, "wait_for", return_value=False):
            with self.assertRaises(adb_link.DeviceLost) as caught:
                link.shell("getprop x")
        self.assertTrue(str(caught.exception).startswith(adb_link.HINT))
        self.assertIn("adb: device 'S' not found", str(caught.exception))

    def test_after_confirmed_loss_the_next_call_is_already_lost(self):
        adb = FakeAdb(BROKEN)
        link = adb_link.Connection("S", transport=adb)
        with patch.object(adb_link, "wait_for", return_value=False):
            with self.assertRaises(adb_link.DeviceLost):
                link.shell("getprop x")
            with self.assertRaises(adb_link.DeviceLost) as caught:
                link.shell("ls")
        self.assertEqual(str(caught.exception), adb_link.REPEAT)
        self.assertEqual(len(adb.calls), 1)

    def test_other_failure_is_not_a_disconnect(self):
        link = adb_link.Connection("S", transport=FakeAdb(RuntimeError("别的错")))
        with patch.object(adb_link, "wait_for") as waited:
            with self.assertRaisesRegex(RuntimeError, "别的错"):
                link.shell("ls")
        waited.assert_not_called()
        self.assertFalse(link.lost)

    def test_adapter_may_keep_the_original_error_after_the_retry(self):
        """u2 那条路径：wait-for-device 回来了，第二次仍失败时抛原异常，不算断线（#293 之前的口径）。"""
        boom = RuntimeError("shell output invalid")
        link = adb_link.Connection("S", transport=FakeAdb(adb_link.LinkBroken(boom), adb_link.LinkBroken(boom)),
                                   lost_on_retry=False)
        with patch.object(adb_link, "wait_for", return_value=True):
            with self.assertRaises(RuntimeError) as caught:
                link.shell("ls")
        self.assertIs(caught.exception, boom)
        self.assertFalse(link.lost)


class AliveTests(unittest.TestCase):
    """「手机此刻连着吗」：先等它回来（可选），再问状态；等超时或问不到都算不在。"""

    def test_no_adb_is_not_alive(self):
        with patch.object(adb_link, "adb_path", return_value=None):
            self.assertFalse(adb_link.Connection("S").alive())

    def test_waits_for_the_device_then_asks_its_state(self):
        with patch.object(adb_link, "_adb_run") as waited, \
             patch.object(adb_link, "present", return_value=True) as asked:
            self.assertTrue(adb_link.Connection("S", adb="/usr/bin/adb").alive(wait=10))
        self.assertEqual(waited.call_args.args[1], ["-s", "S", "wait-for-device"])
        self.assertEqual(waited.call_args.args[2], 10)
        asked.assert_called_once_with("S", "/usr/bin/adb")

    def test_a_timed_out_wait_is_not_alive(self):
        # 基线 adb_present 的口径：等 10 秒没回来就直接算不在，不再追一次 get-state
        with patch.object(adb_link, "_adb_run", side_effect=subprocess.TimeoutExpired("adb", 10)), \
             patch.object(adb_link, "present") as asked:
            self.assertFalse(adb_link.Connection("S", adb="/usr/bin/adb").alive(wait=10))
        asked.assert_not_called()

    def test_a_failed_wait_still_asks_the_state(self):
        # 非零退出不是超时：wait-for-device 答了话，就照常问一次状态
        with patch.object(adb_link, "_adb_run", return_value=adb_link.ShellResult("", "", 1)), \
             patch.object(adb_link, "present", return_value=True) as asked:
            self.assertTrue(adb_link.Connection("S", adb="/usr/bin/adb").alive(wait=10))
        asked.assert_called_once_with("S", "/usr/bin/adb")

    def test_zero_wait_never_asks_the_device_to_come_back(self):
        with patch.object(adb_link, "_adb_run") as waited, \
             patch.object(adb_link, "present", return_value=False):
            self.assertFalse(adb_link.Connection("S", adb="/usr/bin/adb").alive())
        waited.assert_not_called()


class PushTests(unittest.TestCase):
    def test_push_names_the_serial_and_reports_the_result(self):
        done = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(adb_link.subprocess, "run", return_value=done) as ran:
            result = adb_link.Connection("S", adb="/usr/bin/adb").push("a.dex", "/data/local/tmp/a.dex", timeout=30)
        self.assertEqual(ran.call_args.args[0],
                         ["/usr/bin/adb", "-s", "S", "push", "a.dex", "/data/local/tmp/a.dex"])
        self.assertEqual(ran.call_args.kwargs["timeout"], 30)
        self.assertEqual(result.returncode, 0)


class InvokeTests(unittest.TestCase):
    """不绑串号的 adb 命令（devices / version）：客户端和工具脚本共用这条命令行。"""

    def test_runs_the_command_as_given_and_returns_stdout(self):
        done = SimpleNamespace(stdout="Android Debug Bridge version 1.0.41", stderr="", returncode=0)
        with patch.object(adb_link.subprocess, "run", return_value=done) as ran:
            out = adb_link.invoke("/opt/adb", "version", timeout=8)
        self.assertEqual(ran.call_args.args[0], ["/opt/adb", "version"])
        self.assertEqual(ran.call_args.kwargs["timeout"], 8)
        self.assertEqual(out, "Android Debug Bridge version 1.0.41")


# 清空环境变量时留下家目录：Windows 的 expanduser 靠 USERPROFILE / HOMEDRIVE+HOMEPATH，
# 清空后程序里拼不出家目录，和测试算出的路径对不上（v0.2.9 的 Windows 打包测试在这里失败）
HOME_ENV = {k: os.environ[k] for k in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH") if k in os.environ}


class CandidateTests(unittest.TestCase):
    """三份查找列表收成一份：客户端下载的那份排最前，`~/platform-tools` 与 `ADBUTILS_ADB_PATH` 都不再漏。"""

    def only(self, *paths):
        return patch.object(adb_link.os.path, "exists", side_effect=lambda p: p in paths)

    def test_adb_utils_path_env_is_honoured(self):
        with patch.dict(os.environ, {**HOME_ENV, "ADBUTILS_ADB_PATH": "/from/adbutils"}, clear=True), \
             patch.object(adb_link.shutil, "which", return_value=None), self.only("/from/adbutils"):
            self.assertEqual(adb_link.adb_path(), "/from/adbutils")

    def test_platform_tools_in_home_is_a_fallback(self):
        home_adb = os.path.expanduser("~/platform-tools/adb")
        with patch.dict(os.environ, {**HOME_ENV}, clear=True), patch.object(adb_link.shutil, "which", return_value=None), \
             self.only(home_adb):
            self.assertEqual(adb_link.adb_path(), home_adb)

    def test_the_clients_own_download_wins(self):
        with patch.dict(os.environ, {**HOME_ENV, "ADB": "/env/adb"}, clear=True), self.only("/env/adb", "/data/pt/adb"):
            self.assertEqual(adb_link.adb_path(first=("/data/pt/adb",)), "/data/pt/adb")

    def test_candidates_are_deduplicated_in_priority_order(self):
        with patch.dict(os.environ, {**HOME_ENV, "ADB": "/env/adb"}, clear=True), \
             patch.object(adb_link.shutil, "which", return_value="/env/adb"), \
             patch.object(adb_link.os.path, "exists", return_value=True):
            found = adb_link.adb_candidates()
        self.assertEqual(found[0], "/env/adb")
        self.assertEqual(found.count("/env/adb"), 1)


# ---------- 改前改后对拍 ----------
# 旧实现原样复制自 main @ a200c03（run.py:78、chan_fast.py:32、fast.py:112）。
# 它们只活在测试里：同一批回答喂给两边，比较 argv、重试次数、抛出的异常与消息。
NOT_FOUND = "adb: device 'S' not found"

CASES = {
    "一次成功": ([(0, "ok", "")], True),
    "断线后回来": ([(1, "", NOT_FOUND), (0, "ok", "")], True),
    "断线且等不回来": ([(1, "", NOT_FOUND)], False),
    "等回来但第二次还断": ([(1, "", NOT_FOUND), (1, "", NOT_FOUND)], True),
    "普通失败（非断线）": ([(1, "", "error: something went wrong")], True),
}


def old_run_adb_shell(adb, serial, cmd):
    for attempt in range(2):
        r = subprocess.run([adb, "-s", serial, "shell", cmd], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=0)
        if not (r.returncode and adb_link.client_gone(r.stderr)):
            return r
        if attempt or not adb_link.wait_for(serial, adb):
            sys.exit(str(adb_link.lost(r.stderr)))


def old_adb_present(adb, serial):
    """旧 gui.app.adb_present（a200c03，gui/app.py:111）。"""
    try:
        subprocess.run([adb, "-s", serial, "wait-for-device"], capture_output=True, timeout=10,
                       creationflags=adb_link.NOWIN)
        out = subprocess.run([adb, "-s", serial, "get-state"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=8, creationflags=adb_link.NOWIN).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.strip() == "device"


class OldShellPhone:
    def __init__(self, serial, adb):
        self.serial, self.d, self.adb = serial, self, adb

    def shell(self, command, timeout=60):
        for attempt in range(2):
            result = subprocess.run([self.adb, "-s", self.serial, "shell", command], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                    creationflags=0)
            if not (result.returncode and adb_link.client_gone(result.stderr)):
                break
            if attempt or not adb_link.wait_for(self.serial, self.adb):
                raise adb_link.lost(result.stderr)
        if result.returncode:
            raise RuntimeError("adb 读取失败：" + (result.stderr or result.stdout).strip())
        # 旧实现只给 .output；新实现返回的对象是它的超集（多 returncode / stderr），没有调用方读这两项
        return SimpleNamespace(output=result.stdout, returncode=result.returncode)


def old_resilient_shell(p, *args, **kwargs):
    if p.lost:
        raise adb_link.DeviceLost(adb_link.REPEAT)
    try:
        return p._shell(*args, **kwargs)
    except Exception as e:
        if not (adb_link.lib_gone(str(e)) or
                (isinstance(e, fast.u2.exceptions.AdbShellError) and "output invalid" in str(e))):
            raise
        if not adb_link.wait_for(p.serial):
            p.lost = True
            raise adb_link.lost(str(e)) from e
        return p._shell(*args, **kwargs)


def outcome(call):
    """一次调用对外可见的结果：成功（stdout / returncode）、异常（类型 + 消息）或退出码。"""
    try:
        result = call()
    except SystemExit as e:
        return ("exit", str(e.code))
    except Exception as e:
        return ("raise", type(e).__name__, str(e))
    if hasattr(result, "output") or hasattr(result, "stdout"):
        return ("ok", getattr(result, "output", getattr(result, "stdout", None)), getattr(result, "returncode", None))
    return ("value", result)


def as_exit(result):
    """run.adb_shell 现在把断线抛给 main() 的出口（ADR-0005），与旧的 sys.exit(str(e)) 进程级等价：
    同一句文案、同一个退出码，只是异常换了类型。逐字节的退出码与 stderr 由
    tests/test_run_commands.py 的子进程对拍守着，这里只对到「同一句话」。"""
    return ("exit", result[2]) if result[:2] == ("raise", "DeviceLost") else result


class ParityTests(unittest.TestCase):
    """四个入口的改前改后对拍：同一批回答，argv、重试次数、结果逐项相同。"""

    ADB = sys.executable          # 必须真实存在：adb_path() 会按「文件在不在」过滤候选

    def run_script(self, script, wait_ok, call):
        """喂一份回答序列给一次调用，回报「收到的 argv 序列」和对外可见的结果。
        wait_ok=None 表示不替 wait_for 作主，让它真的去跑 subprocess。"""
        pending, seen = list(script), []

        def fake_run(argv, **kwargs):
            seen.append(list(argv))
            returncode, stdout, stderr = pending.pop(0)
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(subprocess, "run", side_effect=fake_run))
            if wait_ok is not None:
                stack.enter_context(patch.object(adb_link, "wait_for", return_value=wait_ok))
            return seen, outcome(call)

    def drive(self, script, wait_ok, call_old, call_new):
        old_argv, old = self.run_script(script, wait_ok, call_old)
        new_argv, new = self.run_script(script, wait_ok, call_new)
        self.assertEqual(as_exit(old), as_exit(new))
        self.assertEqual(old_argv, new_argv)
        return new

    def test_run_adb_shell(self):
        seen = {}
        with patch.object(run, "adb", return_value=self.ADB):
            for name, (script, wait_ok) in CASES.items():
                with self.subTest(name):
                    seen[name] = self.drive(script, wait_ok,
                                            lambda: old_run_adb_shell(self.ADB, "S", "getprop ro.product.model"),
                                            lambda: run.adb_shell("S", "getprop ro.product.model"))
        # 对拍不能是空跑：这几条必须真的走到报错与退出两条路
        self.assertEqual(seen["断线且等不回来"][:2], ("raise", "DeviceLost"))
        self.assertIn("手机助手", str(seen["断线且等不回来"][2]))
        self.assertIn("手机助手", str(seen["等回来但第二次还断"][2]))

    def test_chan_shell_phone(self):
        seen = {}
        with patch.dict(os.environ, {**HOME_ENV, "ADB": self.ADB}, clear=True):
            for name, (script, wait_ok) in CASES.items():
                with self.subTest(name):
                    seen[name] = self.drive(
                        script, wait_ok,
                        lambda: OldShellPhone("S", self.ADB).shell("dumpsys notification --noredact"),
                        lambda: chan.ShellPhone("S").shell("dumpsys notification --noredact"))
        self.assertEqual(seen["断线且等不回来"][:2], ("raise", "DeviceLost"))
        self.assertEqual(seen["普通失败（非断线）"][:2], ("raise", "RuntimeError"))
        self.assertIn("adb 读取失败", str(seen["普通失败（非断线）"]))

    def test_engine_shell(self):
        """读屏库那条路径：断线是「异常」不是返回码，第二次仍失败时抛原异常（不算断线）。"""
        def broken():
            return fast.u2.exceptions.AdbShellError("shell output invalid", "cmd", b"")

        def phone(script):
            # 断线重试归连接基座（ADR-0033）：这里造的是 `Connection`，不是门面。
            p = fast.Connection.__new__(fast.Connection)
            pending = list(script)
            p.calls = []
            p._shell = lambda *a, **k: self.answer(p, pending)
            p.link = adb_link.Connection("S", transport=fast._shell_transport(p._shell), lost_on_retry=False)
            p.serial, p.lost = "S", False
            return p

        ok = SimpleNamespace(output="ok", exit_code=0)
        failed = SimpleNamespace(output="error: something went wrong", exit_code=1)
        cases = {
            "一次成功": ([ok], True),
            "断线后回来": ([broken(), ok], True),
            "断线且等不回来": ([broken()], False),
            "等回来但第二次还断": ([broken(), broken()], True),
            "普通失败（非断线）": ([failed], True),
        }
        seen = {}
        for name, (script, wait_ok) in cases.items():
            with self.subTest(name):
                old, new = phone(script), phone(script)
                with patch.object(adb_link, "wait_for", return_value=wait_ok):
                    seen[name] = outcome(lambda: old_resilient_shell(old, "dumpsys window"))  # noqa: B023 - 当轮创建当轮消费，outcome 同步调用
                    new_result = outcome(lambda: new._resilient_shell("dumpsys window"))  # noqa: B023 - 同上
                self.assertEqual(seen[name], new_result)
                self.assertEqual(len(old.calls), len(new.calls))
        # 对拍不能靠巧合：这两条必须真的走到「断线」和「非断线的命令失败」
        self.assertEqual(seen["断线且等不回来"][:2], ("raise", "DeviceLost"))
        self.assertEqual(seen["普通失败（非断线）"], ("ok", "error: something went wrong", None))

    def test_a_drop_does_not_poison_the_rest_of_the_batch(self):
        """一个 reader 跑一整批：第一次掉线报 HINT，手机回来之后第二次照样能读（旧 ShellPhone 的口径）。"""
        def sequence(reader):
            answers = [SimpleNamespace(returncode=1, stdout="", stderr=NOT_FOUND),
                       SimpleNamespace(returncode=0, stdout="ok", stderr="")]
            with patch.object(subprocess, "run", side_effect=answers), \
                 patch.object(adb_link, "wait_for", return_value=False):
                return outcome(lambda: reader.shell("a")), outcome(lambda: reader.shell("b"))

        with patch.dict(os.environ, {**HOME_ENV, "ADB": self.ADB}, clear=True):
            self.assertEqual(sequence(OldShellPhone("S", self.ADB)), sequence(chan.ShellPhone("S")))

    def test_gui_adb_present(self):
        """客户端那句「手机此刻连着吗」：先 wait-for-device(10 秒) 再 get-state(8 秒)，argv 与结论都比对。"""
        for state in ("device\n", "offline\n", "", "adb: device 'S' not found\n"):
            with self.subTest(state=state.strip()):
                script = [(0, "", ""), (0, state, "")]
                old_argv, old = self.run_script(script, None, lambda: old_adb_present(self.ADB, "S"))
                new_argv, new = self.run_script(script, None, lambda: app.adb_present(self.ADB, "S"))
                self.assertEqual(old, new)
                self.assertEqual(old_argv, new_argv)

        def time_out(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 10)

        with patch.object(subprocess, "run", side_effect=time_out) as ran:
            old = outcome(lambda: old_adb_present(self.ADB, "S"))
        with patch.object(subprocess, "run", side_effect=time_out) as ran:
            new = outcome(lambda: app.adb_present(self.ADB, "S"))
        # 等 10 秒没回来：两边都是 False，且都只跑了一次 wait-for-device，不再问 get-state
        self.assertEqual((old, ran.call_count), (new, ran.call_count))

    def test_the_unified_candidate_order_is_pinned(self):
        """三份列表收成一份之后，客户端顺序是：下载目录 → ADB → ADBUTILS_ADB_PATH → PATH → 系统 SDK → 家目录。"""
        with patch.dict(os.environ, {**HOME_ENV, "ADB": "/env/adb", "ADBUTILS_ADB_PATH": "/env/adbutils"}, clear=True), \
             patch.object(adb_link.shutil, "which", return_value="/path/adb"), \
             patch.object(adb_link.os.path, "exists", return_value=True):
            found = adb_link.adb_candidates(first=("/data/pt/adb",), last=("/opt/homebrew/bin/adb",))
        self.assertEqual(found[:4], ["/data/pt/adb", "/env/adb", "/env/adbutils", "/path/adb"])
        self.assertEqual(found[-1], "/opt/homebrew/bin/adb")
        self.assertLess(found.index(os.path.expanduser("~/Library/Android/sdk/platform-tools/adb")),
                        found.index(os.path.expanduser("~/platform-tools/adb")))

    def answer(self, phone, pending):
        """u2 的 shell：给什么回什么，异常照抛。"""
        phone.calls.append(1)
        answer = pending.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

# ---------- 来源 tests/test_adb_guid_702.py ----------
#   #702：ADB 接口没登记 adb 唯一查询的 device interface GUID 时，诊断要说得出来。
#   
#   Windows 上 adb 只按 {F72FE0D4-CBCB-407D-8814-9ED673D0DD6B} 枚举 USB 接口；
#   手机只登记了厂商自己的 GUID 时，接口状态一切正常、`adb devices` 却静默为 0 台。
ADB_702 = "{F72FE0D4-CBCB-407D-8814-9ED673D0DD6B}"
VENDOR_702 = "{8A4D20A8-A2FA-4495-BEE2-E87ECE4A5356}"
HW_702 = "USB\\VID_339B&PID_107D&MI_02"
DEVICE_LINE_702 = f"荣耀 ADB Interface（OK，调试接口）硬件 ID：{HW_702}"


class UsbFactsGuidTests(unittest.TestCase):
    def test_unregistered_adb_interface_names_the_vendor_guid(self):
        found = [("荣耀", "ADB Interface", "OK", True, HW_702, (VENDOR_702,))]
        lines = app.usb_facts(found)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], DEVICE_LINE_702)
        self.assertIn("未登记", lines[1])
        self.assertIn(VENDOR_702, lines[1])

    def test_registered_adb_interface_is_not_flagged(self):
        found = [("荣耀", "ADB Interface", "OK", True, HW_702, (ADB_702, VENDOR_702))]
        lines = app.usb_facts(found)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], DEVICE_LINE_702)
        self.assertIn("已登记", lines[1])
        self.assertNotIn("未登记", lines[1])

    def test_unreadable_guid_leaves_the_line_out(self):
        # 非 Windows、注册表路径不存在、查询报错：这一行不出现，其余各行逐字不变
        found = [("荣耀", "ADB Interface", "OK", True, HW_702, None)]
        self.assertEqual(app.usb_facts(found), [DEVICE_LINE_702])

    def test_non_adb_interface_is_not_checked(self):
        found = [("荣耀", "荣耀600 超级版", "OK", False, "USB\\VID_339B&PID_107D&MI_00", (VENDOR_702,))]
        self.assertEqual(len(app.usb_facts(found)), 1)
        self.assertNotIn("GUID", app.usb_facts(found)[0])

    def test_no_registered_guid_at_all_is_still_reported(self):
        found = [("荣耀", "ADB Interface", "OK", True, HW_702, ())]
        lines = app.usb_facts(found)
        self.assertIn("未登记", lines[1])
        self.assertIn("没有登记任何 GUID", lines[1])


class UsbParseTests(unittest.TestCase):
    def test_parse_reads_the_guid_field(self):
        out = f"{HW_702}|ADB Interface|OK|USBDevice|{ADB_702},{VENDOR_702}\n"
        found = app.usb_parse(out)
        self.assertEqual(found, [("荣耀", "ADB Interface", "OK", True, HW_702, (ADB_702, VENDOR_702))])

    def test_parse_keeps_unreadable_and_empty_apart(self):
        # `-` 是注册表没读到；空字段是读到了但没登记任何 GUID
        self.assertIsNone(app.usb_parse(f"{HW_702}|ADB Interface|OK|USBDevice|-\n")[0][5])
        self.assertEqual(app.usb_parse(f"{HW_702}|ADB Interface|OK|USBDevice|\n")[0][5], ())

    def test_parse_of_a_line_without_the_guid_field_is_unreadable(self):
        # 老格式 / 输出被截断：宁可不说，也不报成「没登记任何 GUID」
        self.assertIsNone(app.usb_parse(f"{HW_702}|ADB Interface|OK|USBDevice\n")[0][5])


class DiagnosticsTests(unittest.TestCase):
    def test_report_carries_the_guid_line(self):
        # 这一行必须真的进诊断报告，而不只是 usb_facts() 能渲染出来
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        api = app.Api(data.name)
        api.adb = "/opt/tools/adb"
        api.last_devices = "List of devices attached\n"
        found = [("荣耀", "ADB Interface", "OK", True, HW_702, (VENDOR_702,))]
        with patch.object(app, "usb_phones", return_value=found), \
             patch.object(api, "_adb", return_value="Android Debug Bridge"):
            report = api.diagnostics()
        self.assertIn(f"- USB 设备：{DEVICE_LINE_702}", report)
        self.assertIn(f"- USB 设备：荣耀 ADB Interface 未登记 adb 需要的 device interface GUID"
                      f"（实际登记的 GUID：{VENDOR_702}）", report)


# ---------- 来源 tests/test_adb_settings.py ----------
#   手动指定 adb（#311）：查找顺序、保存校验、来源标记。
#   
#   adb 本体是外部边界：这里用「只认白名单里的路径」的假 adb_ok 顶替，
#   被测的是客户端自己的解析链与 settings.json 的读写。
class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.platform_tools = os.path.join(self.root, "platform-tools")
        self.downloaded = self._touch(self.platform_tools, app.adb_exe())
        self.manual = self._touch(os.path.join(self.root, "my-sdk"), app.adb_exe())
        self.env_adb = self._touch(os.path.join(self.root, "env"), app.adb_exe())

    def _touch(self, folder, name):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        open(path, "w").close()
        return path

    def find(self, manual=None, ok=lambda p: True):
        with patch.dict(os.environ, {"ADB": self.env_adb, "ADBUTILS_ADB_PATH": ""}), \
                patch("shutil.which", return_value=None), \
                patch.object(app, "adb_ok", side_effect=ok):
            return app.find_adb(self.platform_tools, manual)


class FindAdbTests(TempRoot):
    def test_manual_wins_over_downloaded_adb(self):
        self.assertEqual(self.find(self.manual), self.manual)

    def test_downloaded_wins_over_environment(self):
        self.assertEqual(self.find(None), self.downloaded)

    def test_environment_used_when_nothing_else_exists(self):
        os.remove(self.downloaded)
        self.assertEqual(self.find(None), self.env_adb)

    def test_missing_manual_path_falls_back(self):
        gone = os.path.join(self.root, "moved-away", "adb")
        self.assertEqual(self.find(gone), self.downloaded)

    def test_manual_with_old_version_falls_back(self):
        self.assertEqual(self.find(self.manual, ok=lambda p: p != self.manual), self.downloaded)


class SettingsFileTests(TempRoot):
    def data(self):
        return app.ClientData(self.root)

    def test_missing_file_reads_as_default(self):
        self.assertIsNone(self.data().setting("adb"))

    def test_written_setting_survives_a_new_client(self):
        self.data().put_setting("adb", "/sdk/platform-tools/adb")
        self.assertEqual(self.data().setting("adb"), "/sdk/platform-tools/adb")

    def test_none_removes_only_that_key(self):
        data = self.data()
        data.put_setting("adb", "/sdk/adb")
        data.put_setting("other", "keep me")
        data.put_setting("adb", None)
        self.assertIsNone(data.setting("adb"))
        self.assertEqual(data.setting("other"), "keep me")

    def test_corrupt_file_is_treated_as_empty(self):
        self.data().ensure()
        with open(self.data().settings, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(self.data().setting("adb"))
        self.data().put_setting("adb", "/sdk/adb")
        self.assertEqual(self.data().setting("adb"), "/sdk/adb")

    def test_clearing_leaves_no_settings_file(self):
        data = self.data()
        data.put_setting("adb", "/sdk/adb")
        data.put_setting("adb", None)
        self.assertFalse(os.path.exists(data.settings))
        self.assertIsNone(data.setting("adb"))

    def test_settings_file_is_json_in_the_data_root(self):
        self.data().put_setting("adb", "/sdk/adb")
        with open(os.path.join(self.root, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"adb": "/sdk/adb"})


VERSION_OUT_311 = "Android Debug Bridge version 1.0.41\nVersion 37.0.1-1234567\n"


class SetAdbPathTests(TempRoot):
    def api(self, adb=None):
        api = app.Api(self.root, adb=adb if adb is not None else self.downloaded)
        api._adb = lambda *a, **k: VERSION_OUT_311
        return api

    def test_saving_a_usable_path_persists_it_and_takes_effect(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            result = api.set_adb_path(self.manual)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "1.0.41")
        self.assertEqual(result["source"], "manual")
        self.assertEqual(api.adb, self.manual)
        self.assertEqual(app.ClientData(self.root).setting("adb"), self.manual)

    def test_missing_file_is_rejected_and_old_setting_kept(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            api.set_adb_path(self.manual)
            result = api.set_adb_path(os.path.join(self.root, "moved-away", "adb"))
        self.assertFalse(result["ok"])
        self.assertIn("找不到", result["error"])
        self.assertEqual(app.ClientData(self.root).setting("adb"), self.manual)
        self.assertEqual(api.adb, self.manual)

    def test_old_adb_is_rejected(self):
        api = self.api()
        with patch.object(app, "adb_ok", side_effect=lambda p: p != self.manual):
            result = api.set_adb_path(self.manual)
        self.assertFalse(result["ok"])
        self.assertIn("1.0.41", result["error"])
        self.assertIsNone(app.ClientData(self.root).setting("adb"))

    def test_relative_path_is_stored_absolute(self):
        api = self.api()
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        with patch.object(app, "adb_ok", return_value=True):
            result = api.set_adb_path(os.path.join("my-sdk", app.adb_exe()))
        self.assertTrue(result["ok"])
        self.assertTrue(os.path.isabs(app.ClientData(self.root).setting("adb")))

    def test_directory_input_gets_the_executable_appended(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            result = api.set_adb_path(os.path.dirname(self.manual))
        self.assertTrue(result["ok"])
        self.assertEqual(app.ClientData(self.root).setting("adb"), self.manual)

    def test_clearing_goes_back_to_automatic_lookup(self):
        api = self.api()
        with patch.object(app, "adb_ok", return_value=True):
            api.set_adb_path(self.manual)
            info = api.clear_adb_path()
        self.assertIsNone(app.ClientData(self.root).setting("adb"))
        self.assertEqual(api.adb, self.downloaded)
        self.assertEqual(info["source"], "downloaded")


class AdbInfoTests(TempRoot):
    def info(self, adb, manual=None):
        api = app.Api(self.root, adb=adb)
        api._adb = lambda *a, **k: VERSION_OUT_311
        if manual:
            app.ClientData(self.root).put_setting("adb", manual)
        return api.adb_info()

    def test_info_reports_ok_only_when_the_version_line_parses(self):
        self.assertTrue(self.info(self.downloaded)["ok"])
        api = app.Api(self.root, adb=self.downloaded)
        api._adb = lambda *a, **k: "not an adb"
        self.assertFalse(api.adb_info()["ok"])

    def test_reports_downloaded_and_system_sources(self):
        self.assertEqual(self.info(self.downloaded)["source"], "downloaded")
        self.assertEqual(self.info("/usr/local/bin/adb")["source"], "system")
        self.assertEqual(self.info(None)["source"], "none")

    def test_manual_path_that_disappeared_falls_back_and_says_so(self):
        gone = os.path.join(self.root, "moved-away", "adb")
        info = self.info(self.downloaded, manual=gone)
        self.assertEqual(info["source"], "downloaded")
        self.assertTrue(info["manual_error"])

    def test_working_manual_path_has_no_problem_reported(self):
        info = self.info(self.manual, manual=self.manual)
        self.assertEqual(info["source"], "manual")
        self.assertEqual(info["manual_error"], "")


# ---------- 来源 tests/test_screen_gone_928.py ----------
#   #928：后台屏没了（读屏打到的显示不存在）要有人话收场，不能带着 Python 堆栈退出。


NPE_READ_928 = "显示 7 不存在（这块屏已经没了）"
ITEMS_928 = [("com.a", "promo", "营销通知")]
DATA_928 = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS_928}


def reader_928():
    """只回答 `settings get` 的假读屏：这条路上不该有任何写入。"""
    return types.SimpleNamespace(shell=lambda cmd, timeout=None: types.SimpleNamespace(output="0\n"))


class ScreenGoneClassifyTests(unittest.TestCase):
    """屏没了既不是断线，也不是「读屏慢一次」：它有自己的那一句（#928）。"""

    def test_both_wordings_are_the_same_outcome(self):
        for message in (NPE_READ_928, screen.LOST,
                        "java.lang.IllegalStateException: 显示 7 不存在（这块屏已经没了）"):
            self.assertTrue(adb_link.screen_gone(message).startswith(adb_link.SCREEN_GONE_STEP), message)

    def test_other_read_failures_are_not_screen_gone(self):
        for message in ("读屏请求超时（30 秒）", "命令服务断开", "UiAutomation 被别的无障碍服务占用"):
            self.assertIsNone(adb_link.screen_gone(message), message)

    def test_the_entry_message_carries_the_original_error(self):
        message = adb_link.failure_message(fast.u2.exceptions.UiAutomationError(NPE_READ_928), "test")
        self.assertTrue(message.startswith(adb_link.SCREEN_GONE_STEP), message)
        self.assertIn(NPE_READ_928, message)            # 社区上报看这段输出，得能看出是哪块屏

    def test_the_connect_sentence_never_claims_a_switch_was_clicked_mid_run(self):
        """段中途屏消失时前面几段可能已经改过开关，不能说「本次未点击开关」（#928 审查）。"""
        self.assertNotIn("未点击", adb_link.SCREEN_GONE_STEP)
        self.assertIn("未点击", adb_link.SCREEN_GONE_CONNECT)

    def test_a_gone_screen_is_still_not_a_disconnect(self):
        """屏没了通道还在：不能报成断线，后面的段也不该被标成跳过（#731 的口径）。

        旧树也绿，守的是不回退：新加的这一族不能被并进 LIB_GONE。"""
        self.assertFalse(adb_link.lib_gone(NPE_READ_928))
        self.assertFalse(adb_link.lib_gone(screen.LOST))


class ScreenGoneEntryTests(unittest.TestCase):
    """两个脚本入口都只报一句人话：屏没了不该以 Python 堆栈收场。

    与 test_reader_failure_731 的入口用例分开：那边守「慢一次」，这边守「屏没了」。
    """

    def test_chan_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        with patch.object(chan, "run", side_effect=fast.u2.exceptions.UiAutomationError(screen.LOST)), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "verify", "x.tsv"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.main()
        self.assertTrue(str(caught.exception.code).startswith(f"✗ {adb_link.SCREEN_GONE_STEP}"))
        self.assertNotIn("Traceback", out.getvalue())

    def test_chan_fast_survives_a_gone_screen_raised_from_the_batch(self):
        """真实路径：段中途新建 Phone 时屏已经没了，异常从 run() 里穿到 main() 的收场。"""
        out = io.StringIO()
        gone = fast.u2.exceptions.UiAutomationError(NPE_READ_928)
        with patch.object(chan, "load", return_value=ITEMS_928), \
                patch.object(chan, "parse", return_value=(DATA_928, {})), \
                patch.object(chan, "ShellPhone", return_value=reader_928()), \
                patch.object(chan, "keep_awake", return_value=None), \
                patch.object(chan, "Phone", side_effect=gone), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", "x.tsv"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.main()
        self.assertTrue(str(caught.exception.code).startswith(f"✗ {adb_link.SCREEN_GONE_STEP}"))
        self.assertNotIn("Traceback", out.getvalue())

    def test_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        gone = fast.u2.exceptions.UiAutomationError(NPE_READ_928)
        with patch.object(phone_connection, "connect", side_effect=gone), \
                patch.object(sys, "argv", ["fast.py", "-s", "test", "run", "recipe.py"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                fast.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn(f"✗ {adb_link.SCREEN_GONE_CONNECT}", out.getvalue())
        self.assertNotIn("Traceback", out.getvalue())


# ---------- 来源 tests/test_shell_backend_1034.py ----------
#   #1034：手机版后端没就绪时给的那两句文案，仍要被 Python 侧判成「命令服务断线」这一族。
#   
#   文案的单一来源是 Kotlin 的 `ShellBackend.NO_BACKEND` / `NO_WIRELESS`，Python 只认「命令服务不可用」这个前缀。
#   两条用例都是守卫：前一条守两侧文案不漂移，后一条守分类不回退——旧树也绿，守的不是这次修复生效。
load_tool()

KT_1034 = ROOT / "android/app/src/main/java/com/ahuamiao/adcleaner/ShellBackend.kt"
NO_BACKEND_1034 = ("命令服务不可用：Shizuku 没在运行或没有授权，内置无线调试也没有连上。"
              "启动 Shizuku，或到「开发者选项」把「无线调试」关掉再打开")
NO_WIRELESS_1034 = "命令服务不可用：内置无线调试没有连上，到「开发者选项」把「无线调试」关掉再打开"


class BackendMissingTextTests(unittest.TestCase):
    def test_both_sentences_are_carried_by_the_kotlin_source(self):
        source = KT_1034.read_text(encoding="utf-8")
        for text in (NO_BACKEND_1034, NO_WIRELESS_1034):
            self.assertIn(text, source)

    def test_both_sentences_still_read_as_a_disconnect(self):
        for text in (NO_BACKEND_1034, NO_WIRELESS_1034):
            self.assertTrue(adb_link.lib_gone(text), text)


# ---------- 来源 tests/test_reader_failure_731.py（连接与读屏失败那一半）----------
#   #731：中途读屏失败要有人话收场：慢一次只是这一步没成，通道没了才算断线。
#   手机版不写插电常亮那一半在 test_phone_host.py。

ITEMS_731 = [("com.a", "promo", "营销通知"), ("com.b", "news", "资讯推送"), ("com.c", "deal", "优惠活动")]
DATA_731 = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS_731}


def reader_731(value="0", commands=None):
    """只回答 `settings get` 的假读屏：记下每条命令，验证有没有人偷偷写设置。"""
    def shell(cmd, timeout=None):
        if commands is not None:
            commands.append(cmd)
        return types.SimpleNamespace(output=value + "\n")
    return types.SimpleNamespace(shell=shell)


class ReadFailureClassifyTests(unittest.TestCase):
    """两种失败的界线：通道没了是断线，慢一次只是这一步没成。"""

    def test_command_service_gone_counts_as_a_disconnect(self):
        for message in ("命令服务断开", "命令服务已断开", "命令服务不可用：java.io.IOException"):
            self.assertTrue(adb_link.lib_gone(message), message)

    def test_a_slow_read_is_not_a_disconnect(self):
        self.assertFalse(adb_link.lib_gone("读屏请求超时（30 秒）"))

    def test_a_slow_read_gets_one_sentence(self):
        self.assertEqual(adb_link.read_failed("读屏请求超时（30 秒）"), "这一步没有完成：读屏请求超时（30 秒）")
        self.assertIsNone(adb_link.read_failed("命令服务断开"))

    def test_phone_takes_the_message_as_evidence(self):
        """手机版的 get-state 由同一个 bridge 回答：它会说「还在」，不能推翻消息里的断开（#731）。"""
        with patch.object(adb_link, "ON_PHONE", True), patch.object(adb_link, "present", return_value=True):
            self.assertIsInstance(adb_link.lost_from(ValueError("命令服务断开"), "test"), adb_link.DeviceLost)

    def test_desktop_still_asks_the_device_list(self):
        """桌面版照旧要双向确认：手机还在列表里就不算断开（#293）。"""
        with patch.object(adb_link, "ON_PHONE", False), patch.object(adb_link, "present", return_value=True):
            self.assertIsNone(adb_link.lost_from(ValueError("device 'test' not found"), "test"))


class ToggleFailureTests(unittest.TestCase):
    def toggle(self, error):
        """跑一次 toggle，返回 (结局, 事件, 异常)：异常照原样交出来，事件已经记下。"""
        p = fake_phone()
        out, result, raised = io.StringIO(), None, None
        with patch.object(chan, "parse", side_effect=error), \
                patch.object(adb_link, "present", return_value=False), \
                patch.dict(os.environ, {"AAC_EVENTS": "1"}), contextlib.redirect_stdout(out):
            try:
                result = chan.toggle(p, "com.a", "promo", False, "营销通知")
            except Exception as e:
                raised = e
        lines = out.getvalue().splitlines()
        return result, [events.parse(line) for line in lines if events.is_event(line)], raised

    def test_command_service_gone_stops_the_batch_as_a_disconnect(self):
        _, sent, raised = self.toggle(fast.u2.exceptions.UiAutomationError("命令服务断开"))
        self.assertIsInstance(raised, adb_link.DeviceLost)
        self.assertEqual(sent, ["link_lost"])

    def test_a_slow_read_is_one_channel_failing(self):
        result, sent, raised = self.toggle(fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）"))
        self.assertIsNone(raised)
        self.assertEqual(result.kind, chan.ERROR)
        self.assertIn("读屏请求超时", result.detail)
        self.assertEqual(sent, [])          # 慢一次不是断线：不发 link_lost


class BatchContinuesTests(unittest.TestCase):
    """Redmi K80 那台：一个渠道读屏超时，后面的渠道照常跑，整步算失败（#731）。"""

    def run_off(self):
        clock = Clock()
        phone, reads = fake_phone(clock=clock), []

        def parse(target, *a, **k):
            if target is not phone:
                return DATA_731, {}                     # 通知记录那一读不在这条路上
            reads.append(target)
            if len(reads) == 1:
                raise fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）")
            return DATA_731, {}

        out = io.StringIO()
        with patch.object(chan, "load", return_value=ITEMS_731), patch.object(chan, "parse", side_effect=parse), \
                patch.object(chan, "ShellPhone", return_value=reader_731()), \
                patch.object(chan, "Phone", return_value=phone), patch.object(chan, "time", clock), \
                patch.dict(os.environ, {"AAC_EVENTS": "1"}), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.run(["-s", "test", "off", "x.tsv"])
        lines = out.getvalue().splitlines()
        return caught.exception.code, lines, [events.parse(x) for x in lines if events.is_event(x)]

    def test_the_rest_of_the_batch_still_runs(self):
        code, lines, sent = self.run_off()
        printed = "\n".join(lines)
        self.assertEqual(code, 1)                                    # 有渠道没关成，整步算失败
        self.assertIn("这一步没有完成：读屏请求超时（30 秒）", printed)
        self.assertIn("资讯推送", printed)                            # 后面的渠道照常处理
        self.assertIn("优惠活动", printed)
        self.assertNotIn("Traceback", printed)
        self.assertEqual(sent, [])                                   # 慢一次不发 link_lost


class ReadFailureEntryTests(unittest.TestCase):
    """两个脚本入口都只报一句人话：读屏慢一次不该以 Python 堆栈收场（#731）。"""

    def test_chan_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        with patch.object(chan, "run", side_effect=fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）")), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "verify", "x.tsv"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                chan.main()
        self.assertEqual(caught.exception.code, "✗ 这一步没有完成：读屏请求超时（30 秒）")

    def test_fast_exits_with_one_sentence(self):
        out = io.StringIO()
        with patch.object(fast, "Phone", side_effect=fast.u2.exceptions.UiAutomationError("读屏请求超时（30 秒）")), \
                patch.object(sys, "argv", ["fast.py", "-s", "test", "run", "recipe.py"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                fast.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(out.getvalue().strip(), "✗ 这一步没有完成：读屏请求超时（30 秒）")

    def test_an_unexpected_error_still_raises(self):
        """只收读屏这一种：别的异常照旧带着堆栈，不能顺手吞掉（#731）。"""
        with patch.object(chan, "run", side_effect=ValueError("boom")), \
                patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "verify", "x.tsv"]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                chan.main()


class ClientKeepsGoingTests(unittest.TestCase):
    """「后续步骤仍照常执行」的客户端一侧：超时不发 link_lost，后面的步骤不会被标成跳过（#731）。"""

    def test_later_steps_run_after_a_slow_read(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory, runner=FakeRunner(spawns=[
                FakeProc("✗ 这一步没有完成：读屏请求超时（30 秒）\n", rc=1), FakeProc()]))
            api.job = job_stub()
            with patch.object(app, "adb_present", return_value=True):
                api._work([app.Task("关闭营销通知", "run.py", ["-s", "test", "chan-off", "x.tsv"]),
                           app.Task("收尾", "run.py", ["-s", "test", "finish"], always_run=True)])
        self.assertEqual(len(api.runner.spawn_calls), 2)      # 后面那一步照常起
        self.assertEqual(api.job.results[0]["rc"], 1)         # 读屏超时的那一步仍算失败
        self.assertNotIn("skipped", api.job.results[1])


if __name__ == "__main__":
    unittest.main()
