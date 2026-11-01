"""手机连接 module（架构体检候选 1）：重试与断线判定只在这一个地方。

假 transport 顶替真 adb：按顺序回答「成功 / 断线 / 其它失败」，并记下收到的命令。
"""
import contextlib
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gui import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tool"))
import adb_link
import chan_fast as chan
import fast
import run

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


class CandidateTests(unittest.TestCase):
    """三份查找列表收成一份：客户端下载的那份排最前，`~/platform-tools` 与 `ADBUTILS_ADB_PATH` 都不再漏。"""

    def only(self, *paths):
        return patch.object(adb_link.os.path, "exists", side_effect=lambda p: p in paths)

    def test_adb_utils_path_env_is_honoured(self):
        with patch.dict(os.environ, {"ADBUTILS_ADB_PATH": "/from/adbutils"}, clear=True), \
             patch.object(adb_link.shutil, "which", return_value=None), self.only("/from/adbutils"):
            self.assertEqual(adb_link.adb_path(), "/from/adbutils")

    def test_platform_tools_in_home_is_a_fallback(self):
        home_adb = os.path.expanduser("~/platform-tools/adb")
        with patch.dict(os.environ, {}, clear=True), patch.object(adb_link.shutil, "which", return_value=None), \
             self.only(home_adb):
            self.assertEqual(adb_link.adb_path(), home_adb)

    def test_the_clients_own_download_wins(self):
        with patch.dict(os.environ, {"ADB": "/env/adb"}, clear=True), self.only("/env/adb", "/data/pt/adb"):
            self.assertEqual(adb_link.adb_path(first=("/data/pt/adb",)), "/data/pt/adb")

    def test_candidates_are_deduplicated_in_priority_order(self):
        with patch.dict(os.environ, {"ADB": "/env/adb"}, clear=True), \
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
        out = subprocess.run([adb, "-s", serial, "get-state"], capture_output=True, text=True,
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
        with patch.dict(os.environ, {"ADB": self.ADB}, clear=True):
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
            p = fast.Phone.__new__(fast.Phone)
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
                    seen[name] = outcome(lambda: old_resilient_shell(old, "dumpsys window"))
                    new_result = outcome(lambda: new._resilient_shell("dumpsys window"))
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

        with patch.dict(os.environ, {"ADB": self.ADB}, clear=True):
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
        with patch.dict(os.environ, {"ADB": "/env/adb", "ADBUTILS_ADB_PATH": "/env/adbutils"}, clear=True), \
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
