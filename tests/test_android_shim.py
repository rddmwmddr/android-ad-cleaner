"""手机版替换层（android/app/src/main/python/aac_android）：不连手机，替换掉执行通道后验 adb 语义、进程内脚本、选择器。"""
import contextlib
import io
import os
import queue
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import types
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))

from aac_android import adb, bridge, inproc, main, screen, u2  # noqa: E402


class FakeBridge:
    def __init__(self, ready=True):
        self.is_ready, self.cmds, self.calls = ready, [], []
        self.exec_result = None
        self.ensure_seq = None
        self.last_exec_timeout = None

    def ready(self):
        self.calls.append("ready")
        return self.is_ready

    def ensure(self):
        self.calls.append("ensure")
        if self.ensure_seq is not None:
            return self.ensure_seq.pop(0) if self.ensure_seq else False
        return self.is_ready

    def exec(self, cmd, stdin=None, timeout=None):
        self.cmds.append((cmd, stdin))
        self.last_exec_timeout = timeout
        if self.exec_result is not None:
            return self.exec_result
        if cmd.startswith("cat ") and not cmd.startswith("cat >"):
            return bridge.Result(0, b"remote-bytes", b"")
        return bridge.Result(3 if "fail" in cmd else 0, b"out\n", b"err\n")


class AdbTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBridge()
        self._saved = bridge._bridge
        bridge._bridge = self.fake

    def tearDown(self):
        bridge._bridge = self._saved

    def test_global_options_are_dropped(self):
        self.assertEqual(adb._split(["-s", "x", "shell", "ls", "-l"]), ("shell", ["ls", "-l"]))
        self.assertEqual(adb._split(["devices", "-l"]), ("devices", ["-l"]))

    def test_shell_joins_like_adb_and_keeps_exit_code(self):
        rc, out, err = adb.answer(["-s", "local", "shell", "pm", "fail", "x"])
        self.assertEqual((rc, out, err), (3, b"out\n", b"err\n"))
        self.assertEqual(self.fake.cmds[-1][0], "pm fail x")

    def test_version_passes_the_client_check(self):
        rc, out, _ = adb.answer(["version"])
        self.assertIn(b"version 1.0.41", out)

    def test_state_follows_shizuku(self):
        self.assertEqual(adb.answer(["-s", "local", "get-state"])[1], b"device\n")
        self.assertIn(b"local\tdevice", adb.answer(["devices"])[1])
        self.fake.is_ready = False
        self.assertEqual(adb.answer(["-s", "local", "get-state"])[0], 1)
        self.assertNotIn(b"local", adb.answer(["devices"])[1])
        self.assertEqual(adb.answer(["-s", "local", "shell", "ls"])[0], 1)

    def test_push_and_pull_go_through_cat(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "a.dex")
            Path(src).write_bytes(b"\x00dex")
            self.assertEqual(adb.answer(["-s", "local", "push", src, "/data/local/tmp/"])[0], 0)
            self.assertEqual(self.fake.cmds[-1], ("cat > /data/local/tmp/a.dex", b"\x00dex"))
            dst = os.path.join(d, "b")
            adb.answer(["-s", "local", "pull", "/data/local/tmp/x", dst])
            self.assertEqual(Path(dst).read_bytes(), b"remote-bytes")

    def test_only_wait_for_device_and_file_transfers_may_connect(self):
        """#622 决策 6/8：查状态（devices / get-state / shell）只许纯查，别让每轮轮询等 mDNS。

        拆门面之前 ready() 既查又连，所以推文件顺带就会重连；拆开之后要显式补上，否则断线中推
        labels.dex 会直接 FAIL。这条守住「谁可以连、谁不许连」的分界。
        """
        self.fake.is_ready = True
        adb.answer(["wait-for-device"])
        self.assertEqual(self.fake.calls, ["ensure"], "wait-for-device 应当去连")

        self.fake.calls.clear()
        adb.answer(["-s", "local", "get-state"])
        adb.answer(["devices"])
        adb.answer(["-s", "local", "shell", "ls"])
        self.assertEqual(self.fake.calls, ["ready"] * 3, "查状态的三个入口只许纯查")

    def test_push_and_pull_try_to_connect_first(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "a.dex")
            Path(src).write_bytes(b"\x00dex")
            adb.answer(["-s", "local", "push", src, "/data/local/tmp/"])
            self.assertEqual(self.fake.calls, ["ensure"])
            self.fake.calls.clear()
            adb.answer(["-s", "local", "pull", "/data/local/tmp/x", os.path.join(d, "b")])
            self.assertEqual(self.fake.calls, ["ensure"])

    def test_subprocess_run_is_answered_for_the_placeholder_only(self):
        with tempfile.TemporaryDirectory() as d:
            saved = (adb.ADB_PATH, dict(adb._orig), subprocess.run, subprocess.call, subprocess.check_output)
            try:
                adb._orig.clear()
                adb.install(os.path.join(d, "bin", "adb"))
                r = subprocess.run([adb.ADB_PATH, "-s", "local", "shell", "echo"], capture_output=True, text=True, encoding="utf-8", errors="replace")
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "out\n", "err\n"))
                other = subprocess.run([sys.executable, "-c", "print(42)"], capture_output=True, text=True, encoding="utf-8", errors="replace")
                self.assertEqual(other.stdout.strip(), "42")
            finally:
                adb.ADB_PATH = saved[0]
                adb._orig.clear(); adb._orig.update(saved[1])
                subprocess.run, subprocess.call, subprocess.check_output = saved[2:]


class LauncherTest(unittest.TestCase):
    """经 Shizuku 跑 monkey 会卡住，拉起 App 换成查启动页再 am start（小米 18 Pro Max 实测）。"""

    def test_monkey_launch_is_rewritten(self):
        cmd = bridge.launcher("monkey -p com.xiaomi.market -c android.intent.category.LAUNCHER 1")
        self.assertNotIn("monkey -p", cmd)
        self.assertIn("resolve-activity --brief -c android.intent.category.LAUNCHER com.xiaomi.market", cmd)
        self.assertIn("Events injected: 1", cmd)

    def test_other_commands_untouched(self):
        for cmd in ("am start -n a/.B", "monkey -p a -v 500", "pm path com.x"):
            self.assertEqual(bridge.launcher(cmd), cmd)


KOTLIN = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "ahuamiao" / "adcleaner"


class ShellStub:
    """Kotlin 的 `Shell` 门面替身：Python 侧只许调这几个名字（bridge.py 的契约）。"""

    def __init__(self, submit=None):
        self.calls, self._submit = [], submit

    def connected(self):
        self.calls.append("connected")
        return True

    def ensure(self):
        self.calls.append("ensure")
        return True

    def submit(self, cmd, stdin):
        self.calls.append("submit")
        return self._submit(cmd, stdin)

    def daemon(self, name, cmd):
        self.calls.append("daemon")
        return True

    def stopDaemon(self, name):
        self.calls.append("stopDaemon")

    def dumpJob(self, display):
        self.calls.append(f"dumpJob:{display}")
        return self._submit("", None)

    def sizeJob(self, display):
        self.calls.append(f"sizeJob:{display}")
        return self._submit("", None)

    def ready(self):
        # 改造前既查又连的旧名字：还有人调就是 Python 侧漏改了
        raise AssertionError("Shell.ready() 已拆成 connected() / ensure()")


class ShellFacadeTest(unittest.TestCase):
    """Python 只认门面的几个名字：查状态不许顺手连（每轮轮询会等 mDNS），要连的只有 wait-for-device。"""

    class Job:
        def __init__(self, ticks):
            self.ticks, self.cancelled = ticks, False

        def isDone(self):
            self.ticks -= 1
            return self.ticks <= 0

        def cancel(self):
            self.cancelled = True

        def result(self, timed_out):
            return bridge.Result(0, b"ok", b"", timed_out)

    def bridge_with(self, job):
        self.shell = ShellStub(submit=lambda cmd, stdin: job)
        b = bridge.ShizukuBridge.__new__(bridge.ShizukuBridge)
        b.shell = self.shell
        return b

    def test_returns_when_done(self):
        r = self.bridge_with(self.Job(3)).exec("ls", None, 5)
        self.assertEqual((r.code, r.out, r.timed_out), (0, b"ok", False))

    def test_times_out_and_cancels(self):
        job = self.Job(10 ** 9)
        r = self.bridge_with(job).exec("monkey", None, 0.05)
        self.assertTrue(r.timed_out)
        self.assertTrue(job.cancelled)

    def test_ready_only_asks_connected(self):
        self.bridge_with(self.Job(1)).ready()
        self.assertEqual(self.shell.calls, ["connected"])

    def test_ensure_is_the_one_that_may_connect(self):
        self.bridge_with(self.Job(1)).ensure()
        self.assertEqual(self.shell.calls, ["ensure"])

    def test_facade_exposes_the_names_python_calls(self):
        """回归里不编译 Kotlin：这里把门面对 Python 的契约钉在源码上。"""
        src = (KOTLIN / "Shell.kt").read_text(encoding="utf-8")
        for name in ("fun connected()", "fun ensure()", "fun submit(", "fun daemon(", "fun stopDaemon(",
                     "fun dumpJob(", "fun sizeJob("):
            self.assertIn(name, src, f"Shell 门面缺 {name}")
        self.assertNotIn("fun backend()", src)

    def test_reading_the_screen_is_polled_not_awaited_in_java(self):
        """读屏也是「提交 + Python 轮询」：在 Java 方法里等会冻住解释器锁（那正是 #623 改前的问题）。"""
        self.shell = ShellStub()
        self.shell.dumpJob = lambda display: self.Job(3)
        b = bridge.ShizukuBridge.__new__(bridge.ShizukuBridge)
        b.shell = self.shell
        r = b.dump(7)
        self.assertEqual((r.code, r.out), (0, b"ok"))

    def test_result_lives_on_the_facade(self):
        self.assertIn("class Result(", (KOTLIN / "Shell.kt").read_text(encoding="utf-8"))
        self.assertNotIn("class Result(", (KOTLIN / "ShizukuShell.kt").read_text(encoding="utf-8"))


PAGE = ('<hierarchy rotation="0">'
        '<node display-id="0" package="com.home" text="主屏" bounds="[0,0][10,10]" />'
        '<node display-id="7" package="com.x" text="" bounds="[0,0][100,100]">'
        '<node display-id="7" resource-id="com.x:id/menu" text="菜单" clickable="true" bounds="[10,10][30,30]" />'
        '<node display-id="7" resource-id="com.x:id/menu" text="菜单" clickable="true" bounds="[40,10][60,30]" />'
        '</node></hierarchy>')

# 命令服务已经按屏号过滤过：后台屏下 Device 拿到的就是这一份
PAGE7 = ('<hierarchy rotation="0">'
         '<node display-id="7" package="com.x" text="" bounds="[0,0][100,100]">'
         '<node display-id="7" resource-id="com.x:id/menu" text="菜单" clickable="true" bounds="[10,10][30,30]" />'
         '<node display-id="7" resource-id="com.x:id/menu" text="菜单" clickable="true" bounds="[40,10][60,30]" />'
         '</node></hierarchy>')


class _Reader:
    """假命令服务：dump / size 回预置值，其它命令记下来（#623 后读屏走的就是这条通道）。"""

    def __init__(self, dump=(None, 0, ""), size=("1080 2400", 0, ""), exit_code=0):
        self.dump_result, self.size_result, self.exit_code = dump, size, exit_code
        self.displays, self.cmds = [], []

    @staticmethod
    def _unpack(t):
        out, code, *err = t
        return code, (out or "").encode(), (err[0] if err else "").encode()

    def ready(self):
        return True

    def ensure(self):
        return True

    def dump(self, display):
        self.displays.append(display)
        return bridge.Result(*self._unpack(self.dump_result))

    def size(self, display):
        return bridge.Result(*self._unpack(self.size_result))

    def exec(self, cmd, stdin=None, timeout=None):
        self.cmds.append(cmd)
        return bridge.Result(self.exit_code, b"", b"")

    def daemon(self, name, cmd):
        self.cmds.append(cmd)
        return True

    def stop_daemon(self, name):
        self.cmds.append(f"stop:{name}")

    def set_clipboard(self, text):
        self.cmds.append(f"clipboard:{text}")


@contextlib.contextmanager
def _using(fake):
    saved = bridge._bridge
    bridge._bridge = fake
    try:
        yield fake
    finally:
        bridge._bridge = saved


class BackgroundScreenTest(unittest.TestCase):
    """后台屏（#618）：命令改发到第 N 块屏，读屏只留这块屏，选择器在过滤后的页面上自己匹配。"""

    def setUp(self):
        self.saved = screen.active
        screen.active = screen.Screen(7, "11529215050074008624", screen.ALWAYS_UNLOCKED)

    def tearDown(self):
        screen.active = self.saved

    def test_commands_go_to_the_background_screen(self):
        r = screen.rewrite
        # 另开一份（MULTIPLE_TASK）：主屏上开着同一个 App 时不把它搬走
        self.assertEqual(r("am start -f 0x10008000 -n a/.B"), "am start --display 7 -f 0x18008000 -n a/.B")
        self.assertEqual(r("am start -n a/.B"), "am start --display 7 -f 0x18000000 -n a/.B")
        self.assertEqual(r("am start --display 3 -n a/.B"), "am start --display 3 -n a/.B")
        self.assertEqual(r("input tap 10 20"), "input -d 7 tap 10 20")
        self.assertEqual(r("input swipe 1 2 3 4 80"), "input -d 7 swipe 1 2 3 4 80")
        self.assertEqual(r("input keyevent BACK"), "input -d 7 keyevent BACK")
        self.assertEqual(r("screencap -p"), "screencap -d 11529215050074008624 -p")
        self.assertIn("am start --display 7", bridge.prepare("monkey -p com.x -c android.intent.category.LAUNCHER 1"))

    def test_home_and_wakeup_never_reach_the_main_screen(self):
        for cmd in ("input keyevent HOME", "input keyevent KEYCODE_HOME", "input keyevent 3", "input keyevent KEYCODE_WAKEUP",
                    "cmd statusbar collapse"):
            self.assertEqual(screen.rewrite(cmd), "true", cmd)
        self.assertEqual(screen.rewrite("am start -n a/.B; input keyevent HOME"), "am start --display 7 -f 0x18000000 -n a/.B; true")

    def test_focus_and_lock_queries_read_only_this_screen(self):
        cmd = screen.rewrite("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | sed -n '1,4p'")
        self.assertIn("dumpsys window displays", cmd)
        self.assertIn("mDisplayId=7[ (]", cmd)
        self.assertIn("isKeyguardShowing=false", cmd)
        cmd = screen.rewrite("dumpsys activity activities | grep -E 'topResumedActivity' | sed -n '1p'")
        self.assertIn("Display #7[ (]", cmd)

    def test_lock_query_is_read_from_the_screen_when_it_can_lock(self):
        """Vd 降到没有 ALWAYS_UNLOCKED 的档位（第 4 档就是 base）：这块屏自己会锁，不能替它答「没锁」。"""
        screen.active = screen.Screen(7, "11529215050074008624", 0x1C9)
        cmd = screen.rewrite("dumpsys window | grep isKeyguardShowing")
        self.assertIn("mDisplayId=7[ (]", cmd)
        self.assertNotIn("isKeyguardShowing=false", cmd)
        self.assertIn("on'; } | grep isKeyguardShowing", cmd, "不加锁屏回答，也不能多出别的字符")

    def test_the_rewritten_queries_keep_their_structure(self):
        """分段改写要原样拼回去：前缀、锁屏回答与收尾都不能被吃掉，否则读屏拿到的是别的命令。"""
        unlocked = screen.rewrite("dumpsys window | grep isKeyguardShowing")
        self.assertTrue(unlocked.startswith("{ dumpsys window displays | awk '/Display: mDisplayId=/"), unlocked)
        self.assertIn("on'; echo '  isKeyguardShowing=false'; } | grep isKeyguardShowing", unlocked)
        activity = screen.rewrite("dumpsys activity activities | grep topResumedActivity")
        self.assertTrue(activity.startswith("dumpsys activity activities | awk '/^Display #/"), activity)
        self.assertIn(")} on' | grep topResumedActivity", activity)

    def test_an_uppercase_hex_flag_still_gets_the_task_bits(self):
        """Vd 上的标记是十六进制：大写字母（0x…A…）也算，别只认小写。"""
        self.assertEqual(screen.rewrite("am start -f 0x10A00000 -n a/.B"),
                         "am start --display 7 -f 0x18a00000 -n a/.B")

    def test_untouched_without_background_screen(self):
        screen.active = None
        for cmd in ("am start -n a/.B", "input tap 1 2", "screencap -p", "input keyevent HOME"):
            self.assertEqual(screen.rewrite(cmd), cmd)

    def test_dump_asks_the_service_for_this_screen(self):
        """读屏不再起监听 9008 的 u2.jar：dump 按屏号问命令服务，回包就是引擎读的页面。"""
        page = '<hierarchy><node display-id="7" text="菜单" /></hierarchy>'
        fake = _Reader((page, 0))
        with _using(fake):
            dev = u2.Device()
            self.assertEqual(dev.dump_hierarchy(), page)
        self.assertEqual(set(fake.displays), {7})

    def test_main_screen_still_reads_display_zero(self):
        """#674：没有后台屏时读屏照旧问主屏 0。"""
        page = '<hierarchy><node display-id="0" text="主屏" /></hierarchy>'
        fake = _Reader((page, 0))
        screen.active = None
        with _using(fake):
            dev = u2.Device()
            self.assertEqual(dev.dump_hierarchy(), page)
        self.assertEqual(set(fake.displays), {0})

    def test_reads_stop_when_the_screen_is_gone(self):
        """#674：屏被判没了之后读屏不再问那块显示，直接报屏已关闭，免得每个等待点各自重试。"""
        fake = _Reader()
        with _using(fake):
            dev = u2.Device()           # 连上先读一次屏
            sent = len(fake.displays)
            screen.active.lost = True
            with self.assertRaises(u2.UiAutomationError) as caught:
                dev.dump_hierarchy()
        self.assertIn(screen.LOST, str(caught.exception))
        self.assertEqual(len(fake.displays), sent, "屏已经没了，不该再问它")

    def test_a_failed_read_raises_with_the_servers_words(self):
        """读屏坏了要报错：回落成空页会让引擎把每个开关都数成「没找到」。"""
        with _using(_Reader((None, 255, "UiAutomation 被别的无障碍服务占用"))):
            with self.assertRaises(u2.UiAutomationError) as caught:
                u2.Device()
        self.assertIn("UiAutomation 被别的无障碍服务占用", str(caught.exception))

    def test_a_missing_display_is_not_an_empty_page(self):
        """#928：显示不存在时 dump 报错，不能回一个空 hierarchy 让引擎当空白页继续跑。

        旧树也绿，守的是不回退：假 reader 代表 Java 侧新报文，真正的判据在 AndroidScreenReader
        （本机没有 JDK，未验）。"""
        gone = "java.lang.IllegalStateException: 显示 7 不存在（这块屏已经没了）"
        with _using(_Reader(dump=(None, 255, gone))):
            with self.assertRaises(u2.UiAutomationError) as caught:
                u2.Device()
        self.assertIn("显示 7 不存在", str(caught.exception))

    def test_window_size_names_the_display_that_is_gone(self):
        """#928：问尺寸时读到的是哪块屏没了，要让用户看得出来，而不是一句 NullPointerException。

        旧树也绿，守的是不回退：报文由 AndroidScreenReader 给，本机没有 JDK，未验。"""
        page = '<hierarchy><node display-id="7" text="菜单" /></hierarchy>'
        gone = "java.lang.IllegalStateException: 显示 7 不存在（这块屏已经没了）"
        with _using(_Reader(dump=(page, 0), size=(None, 255, gone))):
            dev = u2.Device()
            with self.assertRaises(u2.UiAutomationError) as caught:
                dev.window_size()
        self.assertIn("显示 7 不存在", str(caught.exception))
        self.assertIn("已经没了", str(caught.exception))

    def test_a_registered_reader_maps_to_the_busy_type(self):
        """两个客户端抢读屏时，引擎靠这个类型报「读屏服务被占用」，别改成泛泛的读屏错误。"""
        with _using(_Reader((None, 255, "UiAutomationService already registered"))):
            with self.assertRaises(u2.AccessibilityServiceAlreadyRegisteredError):
                u2.Device()

    def test_selector_matches_on_the_page(self):
        import xml.etree.ElementTree as ET
        nodes = list(ET.fromstring(PAGE).iter("node"))
        hits = [n for n in nodes if u2.matches(n, u2.Selector(resourceId="com.x:id/menu"))]
        self.assertEqual([u2.bounds_of(n) for n in hits], [(10, 10, 30, 30), (40, 10, 60, 30)])
        self.assertTrue(any(u2.matches(n, u2.Selector(text="菜单", clickable=True)) for n in nodes))
        self.assertFalse(any(u2.matches(n, u2.Selector(text="主屏")) and n.get("display-id") == "7" for n in nodes))
        self.assertTrue(any(u2.matches(n, u2.Selector(textMatches="菜.")) for n in nodes))

    def test_clearing_a_field_goes_through_input(self):
        """clearTextField 自己发全选 + DEL：不能像 setText 一样一律抛错，
        否则引擎「粘贴前先清空」那一步成了死代码，搜索框里的旧词会和粘贴的内容叠在一起。"""
        fake = _Reader((PAGE, 0))
        with _using(fake):
            dev = u2.Device()
            dev.jsonrpc.clearTextField(dev(resourceId="com.x:id/menu").selector)
        self.assertIn("input keycombination 113 29", fake.cmds)
        self.assertIn("input keyevent KEYCODE_DEL", fake.cmds)
        self.assertTrue(any(c.startswith("input tap 20 20") for c in fake.cmds), fake.cmds)

    def test_clearing_falls_back_when_keycombination_is_missing(self):
        """`input keycombination` 要 Android 11+，minSdk 是 26：老系统上按字数逐字删。"""
        fake = _Reader((PAGE, 0), exit_code=1)
        with _using(fake):
            dev = u2.Device()
            dev.jsonrpc.clearTextField(dev(resourceId="com.x:id/menu").selector)
        self.assertEqual(fake.cmds.count("input keyevent KEYCODE_DEL"), 3)   # 「菜单」两个字 + 收尾那一次

    def test_set_text_still_refuses_so_the_engine_pastes(self):
        """写字的契约没变：走读屏写字一律抛错，引擎退到剪贴板 + 粘贴。"""
        with self.assertRaises(u2.RPCUnknownError):
            u2._Rpc().setText({}, "x")


class ScreenStateTest(unittest.TestCase):
    """刚建出来的屏：还没借出去、还没丢，标记按 Vd 报的原样存着（#1509）。"""

    def test_a_fresh_screen_borrows_nothing_and_is_not_lost(self):
        s = screen.Screen(7, "11")
        self.assertEqual((s.display, s.sf, s.flags), (7, "11", 0))
        self.assertEqual(s.holders, 0, "还没有入口借它，计数从 0 起")
        self.assertIs(s.lost, False)
        self.assertFalse(s.unlocked)


class ScreenBridge:
    """screen.start() / stop() 用的假通道：按命令回答，按顺序记下调用。"""

    def __init__(self, log="DISPLAY 7 flags=0x1f5c9\n", sf_id=11):
        self.log, self.sf_id = log, sf_id
        self.pid = False        # PID_FILE 在不在
        self.stale = False      # 上一次的 Vd 还占着，SurfaceFlinger 里还有一块同名屏
        self.stubborn = False   # kill 不掉的 Vd：拆除之后它那块屏还在
        self.built = False      # 本次的 Vd 起来了
        self.deciding_when_spawned = None   # 拉起 Vd 那一刻界面的说法：应当还在等结论
        self.cmds = []
        self.calls = []         # (命令, stdin, 超时)：每条命令带的是什么参数
        self.daemon_cmd = None
        self.paths = "package:/data/app/x/base.apk\n"
        self.size = "Physical size: 1080x2400\n"
        self.density = "Physical density: 440\n"
        self.dump_bytes = None  # SurfaceFlinger 回包的原始字节（喂坏字节用）

    def exec(self, cmd, stdin=None, timeout=None):
        self.cmds.append(cmd)
        self.calls.append((cmd, stdin, timeout))
        if "kill $(cat" in cmd and not self.stubborn:
            self.pid, self.stale = False, False     # 进程死了，它那块屏随之消失
        if cmd.startswith("pm path"):
            out = self.paths
        elif cmd == "wm size":
            out = self.size
        elif cmd == "wm density":
            out = self.density
        elif cmd.startswith("cat /data/local/tmp/aac-vd.log"):
            out = self.log
        elif cmd.startswith("dumpsys SurfaceFlinger"):
            if self.dump_bytes is not None:
                return bridge.Result(0, self.dump_bytes, b"")
            out = ('Virtual Display 3\n  name="aac-bg"\n' if self.stale else "") + \
                  (f'Virtual Display {self.sf_id}\n  name="aac-bg"\n' if self.built else "")
        elif cmd.startswith("[ -f /data/local/tmp/aac-vd.pid ]"):
            out = "yes" if self.pid else ""
        else:
            out = ""
        return bridge.Result(0, out.encode(), b"")

    def daemon(self, name, cmd):
        self.cmds.append(f"daemon {name}")
        self.daemon_cmd = cmd
        self.deciding_when_spawned = screen.starting
        self.built, self.pid = True, True
        return True

    def stop_daemon(self, name):
        self.cmds.append(f"stop_daemon {name}")


class FakeClock:
    """建屏 / 清残留里的等待环用假钟：不真等，还能数出轮询了几次。"""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now = round(self.now + seconds, 6)     # 0.2 累加有浮点漂移，取整后截止时刻才判得准


def fake_time(clock):
    """把 screen 的等待环接到假钟上：用例不真等，卡在循环里的变异也当轮就有结论。"""
    return mock.patch.object(screen, "time", clock)


class ScreenSizeTest(unittest.TestCase):
    """主屏的逻辑尺寸与密度：后台屏同尺寸；读不到时按 0 处理，让建屏直接放弃（#1509）。"""

    def setUp(self):
        self.saved = bridge._bridge
        self.fake = ScreenBridge()
        bridge._bridge = self.fake

    def tearDown(self):
        bridge._bridge = self.saved

    def test_size_takes_the_last_match_and_the_last_number(self):
        self.fake.size = "Physical size: 1080x2400\nOverride size: 720x1600\n"
        self.fake.density = "Physical density: 440\nOverride density: 480\n"
        self.assertEqual(screen._size(self.fake), (720, 1600, 480))

    def test_missing_size_and_density_read_as_zero(self):
        self.fake.size, self.fake.density = "", ""
        self.assertEqual(screen._size(self.fake), (0, 0, 0))


class ScreenLifecycleTest(unittest.TestCase):
    """建屏 / 拆屏（#618）：起停成对、不建第二块、失败只拆本次、进程被杀后的残留先清掉。"""

    def setUp(self):
        self.saved = (screen.active, screen.starting, bridge._bridge)
        screen.active, screen.starting = None, False
        self.fake = ScreenBridge()
        bridge._bridge = self.fake
        self.clock = FakeClock()
        patcher = fake_time(self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        screen.active, screen.starting, bridge._bridge = self.saved

    def test_lost_screen_is_rebuilt_on_next_start(self):
        """#662：上一块屏已经没了（lost），下一次建屏不借它，拆干净重建。"""
        gone = screen.Screen(5, "9")
        gone.lost, gone.holders = True, 1
        screen.active = gone
        fresh = screen.start("com.ahuamiao.adcleaner")
        self.assertIsNot(fresh, gone)
        self.assertEqual((fresh.display, fresh.holders), (7, 1))

    def test_builds_from_the_flags_vd_reports_and_tears_down(self):
        s = screen.start("com.ahuamiao.adcleaner")
        self.assertEqual((s.display, s.sf, s.flags), (7, "11", 0x1F5C9))
        self.assertIs(screen.active, s)
        self.assertFalse(screen.starting, "建屏结束后界面不该还停在等结论的状态")
        self.assertTrue(s.unlocked)
        self.assertIn("daemon vd", self.fake.cmds)
        self.assertIn("pm path com.ahuamiao.adcleaner", self.fake.cmds, "要按调用方给的包名找 APK")
        screen.stop()
        self.assertIsNone(screen.active)
        self.assertEqual(self.fake.cmds[-2], "stop_daemon vd")

    def test_degraded_flags_keep_the_screen_lockable(self):
        self.fake.log = "DISPLAY 7 flags=0x1c9\n"
        self.assertFalse(screen.start("com.ahuamiao.adcleaner").unlocked)

    def test_a_display_line_without_flags_reads_as_no_flags(self):
        """降级档的 Vd 不一定打印 flags：这时按 0 算，不能替这块屏答「没锁」。"""
        self.fake.log = "DISPLAY 7\n"
        s = screen.start("com.ahuamiao.adcleaner")
        self.assertEqual(s.flags, 0)
        self.assertFalse(s.unlocked)

    def test_display_zero_is_a_real_screen_not_a_failure(self):
        """建屏失败时 Vd 打印 DISPLAY -1；0 是合法编号，不能被当成失败跳过。"""
        self.fake.log = "DISPLAY 0 flags=0x1f5c9\n"
        s = screen.start("com.ahuamiao.adcleaner")
        self.assertEqual(s.display, 0)
        self.assertEqual(screen.rewrite("input tap 1 2"), "input -d 0 tap 1 2")

    def test_the_daemon_is_told_the_apk_size_and_density(self):
        screen.start("com.ahuamiao.adcleaner")
        self.assertIn("CLASSPATH=/data/app/x/base.apk", self.fake.daemon_cmd)
        self.assertIn("com.ahuamiao.adcleaner.Vd 1080 2400 440", self.fake.daemon_cmd)
        self.assertIn("> /data/local/tmp/aac-vd.log 2>&1", self.fake.daemon_cmd)

    def test_the_screen_is_deciding_while_vd_starts(self):
        """界面在结论出来前要一直问：这条状态只有 start() 里那一处置真。"""
        screen.start("com.ahuamiao.adcleaner")
        self.assertTrue(self.fake.deciding_when_spawned)
        self.assertIs(screen.starting, False, "界面读的是布尔字段，None 会在报文里变成 null")

    def test_a_fresh_start_tears_nothing_down_twice(self):
        """没有在跑的屏时不该走「拆掉已有的那块」：拆除命令只由清残留那一次发。"""
        screen.start("com.ahuamiao.adcleaner")
        self.assertEqual(self.fake.cmds.count("stop_daemon vd"), 1)

    def test_every_shell_call_carries_a_timeout(self):
        """通道卡住时每条命令都要靠超时回来：漏掉一个就把整段执行挂在手机上。"""
        self.fake.pid, self.fake.stale = True, True
        screen.start("com.ahuamiao.adcleaner")
        screen.dead()
        self.assertTrue(self.fake.calls)
        for cmd, stdin, timeout in self.fake.calls:
            self.assertIsNone(stdin, cmd)
            self.assertEqual(timeout, 5 if cmd.startswith(f"cat {screen.LOG_FILE}") else 10, cmd)

    def test_reclaim_waits_three_seconds_for_the_old_screen_to_vanish(self):
        """#662：旧 Vd 杀不掉时不能马上建新屏——每 0.2 秒问一次 SurfaceFlinger，最多等 3 秒。"""
        self.fake.pid, self.fake.stale, self.fake.stubborn = True, True, True
        screen._reclaim()
        polls = [c for c in self.fake.cmds if c.startswith("dumpsys SurfaceFlinger")]
        self.assertEqual(len(polls), 15)
        self.assertEqual(self.clock.now, 3.0)

    def test_reclaim_reads_a_dump_that_is_not_clean_utf8(self):
        """SurfaceFlinger 的回包不是干净 UTF-8 时按替换符读：一个坏字节不能让清残留抛错。"""
        self.fake.pid, self.fake.stale, self.fake.stubborn = True, True, True
        self.fake.dump_bytes = b'\xff\xfe\nVirtual Display 3\n  name="aac-bg"\n'
        screen._reclaim()
        polls = [c for c in self.fake.cmds if c.startswith("dumpsys SurfaceFlinger")]
        self.assertEqual(len(polls), 15)

    def test_a_surface_flinger_dump_with_bad_bytes_does_not_break_building(self):
        self.fake.dump_bytes = b"\xff\xfe not utf-8\n"
        self.assertIsNone(screen._build("com.ahuamiao.adcleaner"))

    def test_build_gives_up_after_eight_seconds_without_a_display(self):
        """Vd 起来了却不打印 DISPLAY：等 8 秒就放弃，别一直轮询日志。"""
        self.fake.log = ""
        self.assertIsNone(screen._build("com.ahuamiao.adcleaner"))
        reads = [c for c in self.fake.cmds if c.startswith(f"cat {screen.LOG_FILE}")]
        self.assertEqual(len(reads), 40)
        self.assertEqual(self.clock.now, 8.0)

    def test_no_base_apk_gives_up_before_starting_vd(self):
        """拆分 APK 的机型只有 split_*.apk：找不到 base.apk 就别拉起 Vd。"""
        self.fake.paths = "package:/data/app/x/split_config.arm64_v8a.apk\n"
        self.assertIsNone(screen._build("com.ahuamiao.adcleaner"))
        self.assertNotIn("daemon vd", self.fake.cmds)

    def test_missing_size_gives_up_before_starting_vd(self):
        self.fake.size = ""
        self.assertIsNone(screen._build("com.ahuamiao.adcleaner"))
        self.assertNotIn("daemon vd", self.fake.cmds)

    def test_missing_density_gives_up_before_starting_vd(self):
        self.fake.density = ""
        self.assertIsNone(screen._build("com.ahuamiao.adcleaner"))
        self.assertNotIn("daemon vd", self.fake.cmds)

    def test_second_start_reuses_the_running_screen(self):
        first = screen.start("com.ahuamiao.adcleaner")
        calls = len(self.fake.cmds)
        self.assertIs(screen.start("com.ahuamiao.adcleaner"), first)
        self.assertIs(screen.active, first)
        self.assertEqual(len(self.fake.cmds), calls, "已经有一块屏了，不该再建第二块")

    def test_the_last_holder_tears_the_screen_down(self):
        """两个入口借同一块屏：先结束的那个不能把还在用的屏拆掉。"""
        first = screen.start("com.ahuamiao.adcleaner")
        self.assertIs(screen.start("com.ahuamiao.adcleaner"), first)
        built = len(self.fake.cmds)
        screen.release()
        self.assertIs(screen.active, first)
        self.assertEqual(len(self.fake.cmds), built, "还有执行正跑在屏上，一条命令都不该发")
        screen.release()
        self.assertIsNone(screen.active)
        self.assertIn("stop_daemon vd", self.fake.cmds[built:])

    def test_a_failed_build_does_not_reset_the_running_screen(self):
        """失败清理只针对本次尝试：另一次执行正跑在屏上时，补救不能把它那块拆掉。"""
        running = screen.Screen(9, "22", screen.ALWAYS_UNLOCKED)
        screen.active = running
        self.fake.sf_id = None
        self.assertIsNone(screen._build("com.ahuamiao.adcleaner"))
        self.assertIs(screen.active, running)

    def test_no_surface_flinger_entry_gives_up_and_discards_this_attempt(self):
        self.fake.sf_id = None
        self.assertIsNone(screen.start("com.ahuamiao.adcleaner"))
        self.assertIsNone(screen.active)
        self.assertFalse(screen.starting)
        self.assertIn("stop_daemon vd", self.fake.cmds)

    def test_leftover_daemon_is_reclaimed_before_building(self):
        self.fake.pid, self.fake.stale = True, True
        self.assertIsNotNone(screen.start("com.ahuamiao.adcleaner"))
        kill = next(i for i, c in enumerate(self.fake.cmds) if "kill $(cat" in c)
        self.assertLess(kill, self.fake.cmds.index("daemon vd"), "旧 Vd 还占着同名屏，必须先清掉再建")


class LostScreenTest(unittest.TestCase):
    """#662：建屏进程中途退出后，发往那块屏的命令直接报错，不再发给一块不存在的屏；下次建屏重建。"""

    class Job:
        def __init__(self, code, out=b""):
            self.code, self.out = code, out

        def isDone(self):
            return True

        def cancel(self):
            pass

        def result(self, timed_out):
            return bridge.Result(self.code, self.out, b"", timed_out)

    def setUp(self):
        self.sent = []

        def submit(cmd, stdin):
            self.sent.append(cmd)
            if "kill -0" in cmd:
                return self.Job(1, b"probe\n")          # 探测跑通了，进程不在
            return self.Job(1 if " -d 7 " in cmd else 0)
        b = bridge.ShizukuBridge.__new__(bridge.ShizukuBridge)
        b.shell = ShellStub(submit=submit)
        self.saved = (bridge._bridge, screen.active)
        bridge._bridge, screen.active = b, screen.Screen(7, "11")
        self.b = b

    def tearDown(self):
        bridge._bridge, screen.active = self.saved

    def test_dead_screen_is_marked_and_later_commands_fail_fast(self):
        r = self.b.exec("input tap 1 1", None, 5)
        self.assertTrue(screen.active.lost)
        self.assertIn(screen.LOST, r.err.decode())
        before = len(self.sent)
        r = self.b.exec("input tap 2 2", None, 5)
        self.assertEqual(r.code, 1)
        self.assertEqual(len(self.sent), before, "屏已经没了，不该再发")
        self.b.exec("settings get global x", None, 5)
        self.assertEqual(len(self.sent), before + 1, "不发往后台屏的命令照常")

    def test_failure_on_a_live_screen_is_not_mistaken_for_loss(self):
        self.b.shell._submit = lambda cmd, stdin: self.Job(0, b"probe\nup\n") if "kill -0" in cmd else self.Job(1)
        self.b.exec("input tap 1 1", None, 5)
        self.assertFalse(screen.active.lost)

    def test_probe_that_never_ran_is_not_a_dead_screen(self):
        """#662：通道断了、探测超时时 probe 判不了屏死，否则通道恢复后也一直拒发。"""
        self.b.shell._submit = lambda cmd, stdin: self.Job(1) if "kill -0" in cmd else self.Job(1)
        self.b.exec("input tap 1 1", None, 5)
        self.assertFalse(screen.active.lost, "探测没跑通就判屏死，会把一次通道抖动变成整段执行失败")


class Recorder:
    """main.native 的替身：记下界面侧被调了什么。"""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name,) + a)


class InFrontTest(unittest.TestCase):
    """执行与还原外面包的那一层（#618）：后台屏上跑完按结果发通知，主屏模式回到本 App。"""

    def setUp(self):
        self.native = Recorder()
        self.fake = ScreenBridge()
        self.saved = (main.native, bridge._bridge, screen.active, screen.starting, main.SESSION)
        main.native, bridge._bridge, screen.active, screen.starting = self.native, self.fake, None, False
        main.SESSION = main.Session()
        patcher = fake_time(FakeClock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        main.native, bridge._bridge, screen.active, screen.starting, main.SESSION = self.saved

    def run_with(self, background, fn, action="去广告", stopped=None):
        if not background:
            self.fake.sf_id = None          # 建不了屏：这次走主屏
        return main.in_front(fn, "com.x", action, stopped)()

    def done_calls(self):
        return [c for c in self.native.calls if c[0] == "done"]

    def test_background_run_notifies_done(self):
        self.assertEqual(self.run_with(True, lambda: "ok"), "ok")
        self.assertEqual(self.done_calls(), [("done", "去广告做完了", "点这里查看结果")])
        self.assertIn(("busy", True, True), self.native.calls)
        self.assertIn(("busy", False, True), self.native.calls)
        self.assertIn(("capsule", True, "肉呆去广告中（后台）"), self.native.calls)
        self.assertIsNone(screen.active, "用完要拆屏")
        self.assertEqual([c for c in self.fake.cmds if c.startswith("am start -n")], [])

    def test_user_stop_is_not_reported_as_done(self):
        self.run_with(True, lambda: "ok", stopped=lambda: main.was_stopped(SimpleNamespace(cancel=True)))
        self.assertEqual(self.done_calls(), [("done", "已停止", "点这里查看结果")])

    def test_failure_is_not_reported_as_done(self):
        def boom():
            raise RuntimeError("引擎炸了")

        with self.assertRaises(RuntimeError):
            self.run_with(True, boom)
        self.assertEqual(self.done_calls(), [("done", "去广告失败", "点这里查看原因")])
        self.assertIn(("busy", False, True), self.native.calls, "出错也要把保活与胶囊收掉")
        self.assertIsNone(screen.active)

    def test_restore_reports_its_own_name(self):
        self.run_with(True, lambda: "ok", action="还原")
        self.assertEqual(self.done_calls(), [("done", "还原做完了", "点这里查看结果")])
        self.assertIn(("capsule", True, "肉呆还原中（后台）"), self.native.calls)

    def test_overlapping_entries_keep_the_keepalive_until_the_last_leaves(self):
        """#662：内层先结束不能撤掉外层的前台服务和胶囊，结束通知也只发一次。"""
        def outer():
            main.in_front(lambda: "in", "com.x", "还原")()
            self.assertNotIn(("busy", False, True), self.native.calls, "内层结束时外层还在跑")
            self.assertIsNotNone(screen.active, "外层还在用这块屏")
            return "out"
        self.assertEqual(self.run_with(True, outer), "out")
        self.assertEqual([c for c in self.native.calls if c[0] == "busy"], [("busy", True, True), ("busy", False, True)])
        self.assertEqual(len(self.done_calls()), 1)
        self.assertIsNone(screen.active)

    def test_main_screen_run_comes_back_to_the_app(self):
        self.assertEqual(self.run_with(False, lambda: "ok"), "ok")
        self.assertEqual(self.done_calls(), [])
        self.assertIn(("busy", True, False), self.native.calls)
        self.assertIn("am start -n com.x/.MainActivity", self.fake.cmds)

    def test_failed_entry_does_not_wedge_the_keepalive(self):
        """#662：进会话半路失败要回滚计数；不然之后每次都走「内层」的早退分支，保活与胶囊再也不开。"""
        real = screen.start

        def boom(pkg):
            raise RuntimeError("建屏时桥没起来")

        screen.start = boom
        self.addCleanup(setattr, screen, "start", real)
        with self.assertRaises(RuntimeError):
            self.run_with(True, lambda: "ok")
        self.assertEqual(main.SESSION.count, 0, "失败的这一次不能把计数留在 1")
        screen.start = real
        self.assertEqual(self.run_with(True, lambda: "ok"), "ok")
        self.assertIn(("busy", True, True), self.native.calls, "下一次执行照常开保活")
        self.assertIn(("busy", False, True), self.native.calls, "收尾照常撤保活")

    def test_failed_entry_takes_the_capsule_down_again(self):
        """#662：保活起来了但胶囊没挂上时（visible 抛错），胶囊与屏都不能留下。"""
        real = main.visible

        def boom(package, on, text=""):
            if on:
                raise RuntimeError("设不上悬浮窗权限")
            return real(package, on, text)

        main.visible = boom
        self.addCleanup(setattr, main, "visible", real)
        with self.assertRaises(RuntimeError):
            self.run_with(True, lambda: "ok")
        self.assertIn(("capsule", False, ""), self.native.calls, "胶囊要收掉")
        self.assertIn(("busy", False, False), self.native.calls, "保活也要撤")
        self.assertIsNone(screen.active)


class DeadChannel:
    """调试通道断了（Shizuku 停了、无线调试被关）：发出去的每条命令都抛（#746）。"""

    def exec(self, cmd, stdin=None, timeout=None):
        raise RuntimeError("和手机的调试连接断开了")

    def stop_daemon(self, name):
        raise RuntimeError("和手机的调试连接断开了")


class SessionCleanupTest(unittest.TestCase):
    """#746：清理不能半途中断。通道断了时拆屏会抛，前台服务与屏幕锁仍要撤。"""

    def setUp(self):
        self.native = Recorder()
        self.saved = (main.native, main.SESSION, bridge._bridge, screen.active, screen.start)
        main.native, main.SESSION = self.native, main.Session()
        bridge._bridge = DeadChannel()
        screen.active = None

    def tearDown(self):
        main.native, main.SESSION, bridge._bridge, screen.active, screen.start = self.saved

    def busy(self):
        return [c for c in self.native.calls if c[0] == "busy"]

    def live_screen(self):
        """建屏成功的样子：给 enter/leave 一个持有中的屏，拆它时才会去碰通道。"""
        screen.active = screen.Screen(7, "11")
        screen.active.holders = 1
        return screen.active

    def test_a_failed_entry_still_stops_the_service_and_lock(self):
        """建屏成功了、挂胶囊时通道断了：补救里的拆屏也会抛，保活与屏幕锁仍要撤，计数也要还回去。"""
        def live_start(package):
            return self.live_screen()

        screen.start = live_start
        with self.assertRaises(RuntimeError):
            main.SESSION.enter("com.x", "去广告")
        self.assertEqual(main.SESSION.count, 0)
        self.assertIn(("busy", False, False), self.busy())

    def test_a_failed_screen_take_down_still_stops_the_service(self):
        """离开时拆屏抛了（通道断了）：保活与屏幕锁仍要撤，不能两样都留到进程结束。"""
        self.live_screen()
        main.SESSION.count, main.SESSION.background = 1, True
        with self.assertRaises(RuntimeError):
            main.SESSION.leave("com.x")
        self.assertIn(("busy", False, True), self.busy())


class WasStoppedTest(unittest.TestCase):
    """boot() 靠它在「做完了」和「已停止」之间分开：`_work()` 是正常返回的，只有 Job 上这个标记认得出来。"""

    def test_only_a_cancelled_job_counts(self):
        self.assertTrue(main.was_stopped(SimpleNamespace(cancel=True)))
        self.assertFalse(main.was_stopped(SimpleNamespace(cancel=False)))
        self.assertFalse(main.was_stopped(None))


class RunModeTest(unittest.TestCase):
    """界面问「这次在哪块屏上跑」：建屏没结论前一直是 deciding，页面据此继续问（#618）。"""

    def setUp(self):
        self.saved = (screen.active, screen.starting)

    def tearDown(self):
        screen.active, screen.starting = self.saved

    def test_three_states(self):
        screen.active, screen.starting = None, True
        self.assertEqual(main.mode(), {"background": False, "deciding": True})
        screen.active, screen.starting = screen.Screen(7, "11"), False
        self.assertEqual(main.mode(), {"background": True, "deciding": False})
        screen.active, screen.starting = None, False
        self.assertEqual(main.mode(), {"background": False, "deciding": False})


class ScreenObjectTest(unittest.TestCase):
    """后台屏下的节点读取（#618）：info / get_text 走过滤后的页面，wait 读超时不穿透。"""

    def setUp(self):
        self.saved = screen.active
        screen.active = screen.Screen(7, "11", screen.ALWAYS_UNLOCKED)

    def tearDown(self):
        screen.active = self.saved

    class Device:
        def __init__(self, page=None, error=None):
            self.page, self.error, self.wait_timeout = page, error, 0.5
            self.jsonrpc = None

        def dump_hierarchy(self, *a, **k):
            if self.error:
                raise self.error
            return self.page

    def test_text_and_bounds_come_from_this_screen_only(self):
        dev = self.Device(PAGE7)
        second = u2.UiObject(dev, u2.Selector(text="菜单", instance=1))
        self.assertEqual(second.get_text(), "菜单")
        self.assertEqual(second.info["text"], "菜单")
        self.assertEqual(second.info["bounds"], {"left": 40, "top": 10, "right": 60, "bottom": 30})
        with self.assertRaises(u2.UiObjectNotFoundError):
            u2.UiObject(dev, u2.Selector(text="主屏")).get_text()

    def test_wait_read_timeout_falls_back_instead_of_raising(self):
        obj = u2.UiObject(self.Device(error=u2.HTTPTimeoutError("read timeout")), u2.Selector(text="x"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.assertFalse(obj.wait(timeout=0.1))
        self.assertEqual(len(w), 1)


class _FlushSink:
    """写进缓冲、flush 时才落盘：能看出 `print(..., flush=…)` 到底有没有调 flush。"""

    def __init__(self):
        self.buf, self.flushes = "", 0

    def write(self, s):
        self.buf += s
        return len(s)

    def flush(self):
        self.flushes += 1


class _Done:
    """`_watchdog` 的 done 参数替身：按给定的序列回答，并记下每次等的秒数。"""

    def __init__(self, answers):
        self.answers, self.waits = list(answers), []

    def wait(self, timeout):
        self.waits.append(timeout)
        return self.answers.pop(0) if self.answers else True


def _snapshot_modules(names):
    """记下这些模块键当前的值（缺省记 None），供还原用。"""
    return {name: sys.modules.get(name) for name in names}


def _restore_modules(saved):
    """把 `_snapshot_modules` 的快照回填进 sys.modules：原本缺的键删掉，原本有的放回去。"""
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class InprocTest(unittest.TestCase):
    """进程内执行：清模块、换环境、分流输出、看门狗与停止通道。

    `inproc` 的模块级状态（`TOOL` / `_fallback` / `_sinks` / `_engine_log` / `after_run` /
    `WATCHDOG_INTERVAL`）在同一个解释器里跨用例存活。mutation 把全部 mutant 跑在同一个解释器里，
    不还原就会出现「后一个 mutant 读到的初值不是初值」的假存活（#1510）。先例是 #1454 在会话开头
    清 `tool/` 的 lru_cache：方向一致，只把状态还原成模块刚加载时的样子，不制造假杀死。
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tool = Path(self.dir.name)
        self.saved = (inproc.TOOL, sys.stdout, sys.stderr, inproc._fallback)
        self.saved_globals = (dict(inproc._sinks), inproc._engine_log, list(inproc.after_run),
                              inproc.WATCHDOG_INTERVAL)
        inproc.setup(str(self.tool))

    def tearDown(self):
        inproc.TOOL = self.saved[0]
        sys.stdout, sys.stderr, inproc._fallback = self.saved[1:]
        sinks, engine_log, after_run, interval = self.saved_globals
        inproc._sinks.clear()
        inproc._sinks.update(sinks)
        inproc._engine_log = engine_log
        inproc.after_run[:] = after_run
        inproc.WATCHDOG_INTERVAL = interval
        if str(self.tool) in sys.path:
            sys.path.remove(str(self.tool))
        self.dir.cleanup()

    def script(self, name, body):
        (self.tool / name).write_text(textwrap.dedent(body), encoding="utf-8")

    def read_stdout(self, proc, timeout=5, cap=1000):
        """把 spawn 的 stdout 读到结束标记。

        工作线程没送结束标记（坏掉的 `Proc`）或反复送同一行时，到点 / 到上限就收手：不然一条
        卡在 `q.get()` 的用例会把 mutation 的整个解释器挂住，并留下没有结论的 mutant。
        """
        got = []

        def collect():
            for line in proc.stdout:
                got.append(line)
                if len(got) >= cap:
                    return

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        reader.join(timeout)
        return got

    def clear_sinks(self):
        inproc._sinks.clear()

    def test_exit_code_output_and_env(self):
        self.script("a.py", """
            import os, sys
            print("hi", os.environ.get("AAC_X"), sys.argv[1:])
            print("warn", file=sys.stderr)
            sys.exit(2)
        """)
        out, err, rc = inproc.Runner(lambda: dict(os.environ, AAC_X="1")).run("a.py", "-s", "local")
        self.assertEqual((rc, out, err), (2, "hi 1 ['-s', 'local']\n", "warn\n"))
        self.assertNotIn("AAC_X", os.environ)

    def test_nested_script_capture(self):
        self.script("inner.py", "print('inner')\n")
        self.script("outer.py", """
            from aac_android import inproc
            rc, out, err = inproc.call(["inner.py"], capture=True)
            print("got", out.strip(), rc)
        """)
        out, _, rc = inproc.Runner(lambda: dict(os.environ)).run("outer.py")
        self.assertEqual((rc, out), (0, "got inner 0\n"))

    def test_spawn_streams_lines_and_stops(self):
        self.script("loop.py", """
            import time
            print("start", flush=True)
            while True:
                time.sleep(0.01)
        """)
        proc = inproc.Runner(lambda: dict(os.environ)).spawn("loop.py")
        got = []

        def collect():
            for line in proc.stdout:
                got.append(line)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        deadline = time.monotonic() + 5
        while not got and time.monotonic() < deadline:
            time.sleep(0.01)
        # 流式：脚本还没结束，第一行就已经读到了
        self.assertEqual(got, ["start\n"])
        proc.terminate()
        self.assertEqual(proc.wait(5), -15)

    def test_run_times_out_and_leaves_the_next_run_usable(self):
        # 有限时长的脚本：join 变异成 join(None) 时会等到它自然结束（而不是一起挂住），
        # 那时 `run` 会正常返回而不是抛超时，断言能把它区分出来。
        self.script("slow.py", """
            import sys, time
            print("partial")
            print("warn", file=sys.stderr)
            time.sleep(0.5)
        """)
        self.script("ok.py", "print('ok')\n")
        run = inproc.Runner(lambda: dict(os.environ)).run
        with self.assertRaises(subprocess.TimeoutExpired) as ctx:
            run("slow.py", timeout=0.1)
        error = ctx.exception
        self.assertEqual(error.cmd, "slow.py")
        self.assertEqual(error.timeout, 0.1)
        self.assertEqual(error.output, "partial\n")
        self.assertEqual(error.stderr, "warn\n已停止\n")
        # 打断后锁与环境变量都要还回来，下一步照常跑
        self.assertEqual(run("ok.py", timeout=5), ("ok\n", "", 0))

    def test_a_script_that_outlives_the_stop_grace_reports_what_it_had_printed(self):
        """打断后最多再等 STOP_GRACE：等不到就带着此刻已有输出报超时，不陪着一起等。"""
        saved_grace = inproc.STOP_GRACE
        self.addCleanup(setattr, inproc, "STOP_GRACE", saved_grace)
        inproc.STOP_GRACE = 0.1
        finished = threading.Event()
        inproc.after_run[:] = [finished.set]    # 等被打断的脚本线程收尾，别让它漏到后面的用例
        self.script("stubborn.py", """
            import sys, time
            print("early", flush=True)
            try:
                time.sleep(0.5)
            finally:
                print("late", flush=True)
        """)
        with self.assertRaises(subprocess.TimeoutExpired) as ctx:
            inproc.Runner(lambda: dict(os.environ)).run("stubborn.py", timeout=0.05)
        self.assertEqual(ctx.exception.output, "early\n")
        self.assertTrue(finished.wait(5))

    def test_modules_are_fresh_per_top_level_run(self):
        self.script("counter.py", "N = []\n")
        self.script("bump.py", "import counter\ncounter.N.append(1)\nprint(len(counter.N))\n")
        run = inproc.Runner(lambda: dict(os.environ)).run
        self.assertEqual(run("bump.py")[0], "1\n")
        self.assertEqual(run("bump.py")[0], "1\n")

    def logcat(self):
        """替掉写 logcat 的那一路，返回收到的 (tag, 行) 清单。"""
        lines = []
        saved = inproc._engine_log
        self.addCleanup(setattr, inproc, "_engine_log", saved)
        inproc._engine_log = lambda tag, text: lines.append((tag, text))
        return lines

    def test_engine_lines_mirror_into_logcat_line_by_line(self):
        # 镜像按行切：半行写两次要拼齐，最后一段没有换行的字也要出去；界面那边（队列）看到的不受影响
        self.script("say.py", """
            import sys
            print("核对 3 项")
            sys.stderr.write("半")
            sys.stderr.write("行\\n尾")
        """)
        lines = self.logcat()
        proc = inproc.Runner(lambda: dict(os.environ)).spawn("say.py")
        shown = self.read_stdout(proc)
        self.assertEqual(proc.wait(5), 0)
        self.assertEqual(shown, ["核对 3 项\n", "半行\n", "尾"])
        self.assertEqual(lines, [(inproc.LOGCAT_TAG, "核对 3 项"), (inproc.LOGCAT_TAG, "半行"),
                                 (inproc.LOGCAT_TAG, "尾")])

    def test_shared_sink_mirrors_exactly_what_the_queue_shows(self):
        # Proc 把同一个 _LineSink 当 out 与 err：两个流共用一份缓冲，镜像的行边界要与队列一致
        self.script("mix.py", """
            import sys
            sys.stdout.write("abc")
            sys.stderr.write("def\\n")
        """)
        lines = self.logcat()
        proc = inproc.Runner(lambda: dict(os.environ)).spawn("mix.py")
        shown = self.read_stdout(proc)
        self.assertEqual(proc.wait(5), 0)
        self.assertEqual(shown, ["abcdef\n"])
        self.assertEqual(lines, [(inproc.LOGCAT_TAG, "abcdef")])

    def test_machine_lines_reach_the_ui_but_not_logcat(self):
        self.script("two.py", """
            print('#aac:event {"kind": "ui_busy"}')
            print("核对 3 项")
        """)
        lines = self.logcat()
        out, err, rc = inproc.Runner(lambda: dict(os.environ)).run("two.py")
        self.assertEqual((out, rc), ('#aac:event {"kind": "ui_busy"}\n核对 3 项\n', 0))
        self.assertEqual(lines, [(inproc.LOGCAT_TAG, "核对 3 项")])

    def test_a_broken_logcat_leaves_the_output_alone(self):
        self.script("say.py", "print('一')\nprint('二')\n")

        def boom(tag, text):
            raise RuntimeError("logcat 写不进去")

        saved = inproc._engine_log
        self.addCleanup(setattr, inproc, "_engine_log", saved)
        inproc._engine_log = boom
        out, err, rc = inproc.Runner(lambda: dict(os.environ)).run("say.py")
        self.assertEqual((out, err, rc), ("一\n二\n", "", 0))

    # ---- 模块级状态：logcat 解析、输出分流、tool 目录与模块清理（#1510） ----

    def test_logger_resolves_android_util_log_once(self):
        """镜像取 `android.util.Log.i`：取到就记住，别再每行去 Java 里找一次。"""
        log = lambda tag, text: None
        java = SimpleNamespace(jclass=mock.Mock(return_value=SimpleNamespace(i=log)))
        inproc._engine_log = inproc._UNSET
        with mock.patch.dict(sys.modules, {"java": java}):
            self.assertIs(inproc._logger(), log)
            self.assertIs(inproc._engine_log, log)
        # 刻意锁住 tag 字符串：这是「只在 mock 注册上等价」的变异的唯一区分手段，不锁就只能算
        # 存活；不锁一般的调用序列。
        java.jclass.assert_called_once_with("android.util.Log")

    def test_logger_remembers_no_java_as_none(self):
        """没有 java 模块时返回 None 并记住：镜像据此关掉，不会每行再试。"""
        java = SimpleNamespace(jclass=mock.Mock(side_effect=RuntimeError("no java")))
        inproc._engine_log = inproc._UNSET
        with mock.patch.dict(sys.modules, {"java": java}):
            self.assertIsNone(inproc._logger())
        self.assertIsNone(inproc._engine_log)

    def test_router_routes_each_stream_to_its_sink_then_the_fallback(self):
        """stdout / stderr 各走自己的槽；没有活动 sink 时落到 setup 记下的那一对，嵌套时写最上面一层。"""
        self.clear_sinks()
        saved_fallback = inproc._fallback
        self.addCleanup(setattr, inproc, "_fallback", saved_fallback)
        fb_out, fb_err = io.StringIO(), io.StringIO()
        inproc._fallback = (fb_out, fb_err)
        self.assertEqual(inproc._Router(0).write("o"), 1)
        self.assertEqual(inproc._Router(1).write("e"), 1)
        self.assertEqual((fb_out.getvalue(), fb_err.getvalue()), ("o", "e"))
        top_out, top_err = io.StringIO(), io.StringIO()
        inproc._push(top_out, top_err)
        inproc._Router(0).write("O")
        inproc._Router(1).write("E")
        self.assertEqual((top_out.getvalue(), top_err.getvalue()), ("O", "E"))
        inner_out, inner_err = io.StringIO(), io.StringIO()
        inproc._push(inner_out, inner_err)
        inproc._Router(0).write("I")
        self.assertEqual((inner_out.getvalue(), top_out.getvalue()), ("I", "O"))

    def test_router_flush_reaches_a_sink_that_has_one(self):
        self.clear_sinks()
        sink = _FlushSink()
        saved_fallback = inproc._fallback
        self.addCleanup(setattr, inproc, "_fallback", saved_fallback)
        inproc._fallback = (sink, sink)
        out_router, err_router = inproc._Router(0), inproc._Router(1)
        out_router.flush()
        err_router.flush()
        self.assertEqual(sink.flushes, 2)

    def test_router_flush_ignores_a_sink_without_flush(self):
        """fallback 可能是任意可写对象：没有 flush 也不能让它抛。"""
        self.clear_sinks()
        saved_fallback = inproc._fallback
        self.addCleanup(setattr, inproc, "_fallback", saved_fallback)
        inproc._fallback = (object(), object())
        inproc._Router(0).flush()

    def test_router_claims_to_be_writable(self):
        self.assertIs(inproc._Router(0).writable(), True)

    def test_setup_puts_a_new_tool_dir_at_the_front_once(self):
        """新 tool 目录插到最前（模块先从这里找），已在清单里就不重复插。"""
        other = str(self.tool / "nested")
        os.makedirs(other)
        self.addCleanup(lambda: sys.path.remove(other) if other in sys.path else None)
        inproc.setup(other)
        self.assertEqual(sys.path[0], other)
        inproc.setup(other)
        self.assertEqual(sys.path.count(other), 1)

    def test_setup_keeps_the_original_streams_as_the_fallback(self):
        """换掉的 stdout / stderr 要留一份当 fallback：没有活动 sink 时输出照旧落到原处。"""
        self.assertEqual(inproc._fallback, (self.saved[1], self.saved[2]))

    def test_purge_drops_modules_under_the_tool_dir_only(self):
        """只清 TOOL 目录下的模块：同名前缀的兄弟目录、没有 __file__ 的模块都不动。"""
        inside = types.ModuleType("aac_probe_inside")
        inside.__file__ = os.path.join(str(self.tool), "probe_inside.py")
        sibling = types.ModuleType("aac_probe_sibling")
        sibling.__file__ = str(self.tool) + "x" + os.sep + "probe_sibling.py"
        bare = types.ModuleType("aac_probe_bare")
        names = ("aac_probe_inside", "aac_probe_sibling", "aac_probe_bare")
        self.addCleanup(_restore_modules, _snapshot_modules(names))
        sys.modules.update(dict(zip(names, (inside, sibling, bare), strict=True)))
        inproc._purge()
        self.assertNotIn("aac_probe_inside", sys.modules)
        self.assertIn("aac_probe_sibling", sys.modules)
        self.assertIn("aac_probe_bare", sys.modules)

    def test_script_path_keeps_absolute_and_joins_relative(self):
        absolute = os.path.join(str(self.tool), "x.py")
        self.assertEqual(inproc._script_path(absolute), absolute)
        self.assertEqual(inproc._script_path("x.py"), os.path.join(str(self.tool), "x.py"))

    def test_push_and_pop_keep_one_stack_per_thread(self):
        self.clear_sinks()
        ident = threading.get_ident()
        inproc._push("o", "e")
        inproc._push("o2", "e2")
        self.assertEqual(inproc._sinks[ident], [("o", "e"), ("o2", "e2")])
        inproc._pop()
        self.assertEqual(inproc._sinks[ident], [("o", "e")])
        inproc._pop()
        self.assertNotIn(ident, inproc._sinks)
        inproc._pop()       # 没有栈时再 pop 也不抛

    # ---- 跑脚本：argv / 退出码 / 停止与异常收容（#1510） ----

    def test_cli_marker_is_stripped_and_argv_restored(self):
        """`--cli` 只是引擎的一个标记，传到脚本前去掉；跑完 sys.argv 要还给调用方。"""
        self.script("args.py", "import sys\nprint(sys.argv[1:])\n")
        before = list(sys.argv)
        self.assertEqual(inproc.call(["--cli", "args.py", "a", "b"], capture=True), (0, "['a', 'b']\n", ""))
        self.assertEqual(sys.argv, before)

    def test_the_script_runs_as_main(self):
        self.script("mainonly.py", 'if __name__ == "__main__":\n    print("ran")\n')
        self.assertEqual(inproc.call(["mainonly.py"], capture=True), (0, "ran\n", ""))

    def test_exit_without_a_code_is_zero(self):
        self.script("quiet_exit.py", "import sys\nsys.exit()\n")
        self.assertEqual(inproc.call(["quiet_exit.py"], capture=True), (0, "", ""))

    def test_exit_with_a_message_returns_one(self):
        """非整数的 SystemExit.code 按桌面版的口径：原文进 stderr，退出码 1。"""
        self.script("msg_exit.py", "import sys\nsys.exit('boom')\n")
        self.assertEqual(inproc.call(["msg_exit.py"], capture=True), (1, "", "boom\n"))

    def test_a_keyboard_interrupt_returns_minus_fifteen(self):
        self.script("interrupted.py", "raise KeyboardInterrupt\n")
        self.assertEqual(inproc.call(["interrupted.py"], capture=True), (-15, "", "已停止\n"))

    def test_an_unexpected_error_prints_the_traceback_and_returns_one(self):
        self.script("boom.py", "raise ValueError('bad')\n")
        rc, out, err = inproc.call(["boom.py"], capture=True)
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("Traceback", err)
        self.assertIn("ValueError: bad", err)

    def test_call_without_capture_returns_empty_streams(self):
        """不捕获时只回退出码：输出照旧走当前输出，不往返回值里塞。"""
        self.script("hi.py", "print('hi')\n")
        self.clear_sinks()
        saved_fallback = inproc._fallback
        self.addCleanup(setattr, inproc, "_fallback", saved_fallback)
        fallback = io.StringIO()
        inproc._fallback = (fallback, fallback)
        self.assertEqual(inproc.call(["hi.py"]), (0, "", ""))
        self.assertEqual(fallback.getvalue(), "hi\n")

    def test_capture_collects_stdout_and_stderr_apart(self):
        self.script("sep.py", "import sys\nprint('o')\nprint('e', file=sys.stderr)\n")
        self.assertEqual(inproc.call(["sep.py"], capture=True), (0, "o\n", "e\n"))

    # ---- 行分流与 logcat 镜像（#1510） ----

    def test_a_two_line_chunk_is_mirrored_line_by_line(self):
        """一次 write 里带两个换行：队列与镜像都要按行拆开，而不是整块转手。"""
        self.script("burst.py", "import sys\nsys.stdout.write('a\\nb\\n')\n")
        lines = self.logcat()
        proc = inproc.Runner(lambda: dict(os.environ)).spawn("burst.py")
        shown = self.read_stdout(proc)
        self.assertEqual(proc.wait(5), 0)
        self.assertEqual(shown, ["a\n", "b\n"])
        self.assertEqual(lines, [(inproc.LOGCAT_TAG, "a"), (inproc.LOGCAT_TAG, "b")])

    def test_without_logcat_the_mirror_only_tries_once(self):
        """取不到 logcat 就关掉：不该每行都重新找一次 Java 接口。"""
        self.script("two.py", "print('a')\nprint('b')\n")
        calls = []
        saved = inproc._logger
        self.addCleanup(setattr, inproc, "_logger", saved)
        inproc._logger = lambda: (calls.append(1), None)[1]
        out, _, rc = inproc.Runner(lambda: dict(os.environ)).run("two.py")
        self.assertEqual((out, rc), ("a\nb\n", 0))
        self.assertEqual(len(calls), 1)

    def test_closing_the_mirror_relays_the_tail_and_resets_the_buffer(self):
        self.clear_sinks()
        seen = []
        saved = inproc._engine_log
        self.addCleanup(setattr, inproc, "_engine_log", saved)
        inproc._engine_log = lambda tag, text: seen.append(text)
        sink = io.StringIO()
        mirror = inproc._Mirror(sink)
        mirror.write("tail")
        mirror.close()
        self.assertEqual(sink.getvalue(), "tail")
        self.assertEqual(seen, ["tail"])
        self.assertEqual(mirror.buf, "")

    def test_line_sink_close_emits_the_tail_once_and_resets_the_buffer(self):
        q = queue.Queue()
        sink = inproc._LineSink(q)
        sink.write("tail")
        sink.close()
        sink.close()
        self.assertEqual(q.get_nowait(), "tail")
        self.assertTrue(q.empty())
        self.assertEqual(sink.buf, "")

    # ---- 进程替身：等待、轮询、环境合并与守护线程（#1510） ----

    def test_wait_reports_running_until_the_script_finishes(self):
        self.script("late.py", "import time\ntime.sleep(0.3)\nprint('done')\n")
        proc = inproc.Runner(lambda: dict(os.environ)).spawn("late.py")
        self.assertIsNone(proc.wait(0))
        self.assertEqual(proc.wait(5), 0)

    def test_poll_reports_running_then_the_exit_code(self):
        self.script("late.py", "import time\ntime.sleep(0.2)\nimport sys\nsys.exit(3)\n")
        proc = inproc.Runner(lambda: dict(os.environ)).spawn("late.py")
        self.assertIsNone(proc.poll())
        self.assertEqual(proc.wait(5), 3)
        self.assertEqual(proc.poll(), 3)

    def test_spawn_runs_the_script_on_a_daemon_thread(self):
        """脚本跑在守护线程上：卡住的脚本不能拖住解释器退出。"""
        self.script("threaded.py", "import threading\nprint(threading.current_thread().daemon)\n")
        proc = inproc.Runner(lambda: dict(os.environ)).spawn("threaded.py")
        self.assertEqual(self.read_stdout(proc), ["True\n"])
        self.assertEqual(proc.wait(5), 0)

    def test_spawn_merges_base_and_extra_env(self):
        self.script("envy.py", "import os\nprint(os.environ.get('BASE'), os.environ.get('EXTRA'))\n")
        proc = inproc.Runner(lambda: {"BASE": "b"}).spawn("envy.py", env_extra={"EXTRA": "e"})
        self.assertEqual(self.read_stdout(proc), ["b e\n"])

    def test_run_runs_the_script_on_a_daemon_thread(self):
        self.script("threaded.py", "import threading\nprint(threading.current_thread().daemon)\n")
        out, _, rc = inproc.Runner(lambda: dict(os.environ)).run("threaded.py")
        self.assertEqual((out, rc), ("True\n", 0))

    # ---- 看门狗与收尾回调（#1510） ----

    def test_watched_stack_is_reported(self):
        """看门狗报的是被观察线程的栈（最多 12 层），不是它自己的；tag 行与 flush 都要对。"""
        saved = inproc._fallback
        self.addCleanup(setattr, inproc, "_fallback", saved)
        sink = _FlushSink()
        inproc._fallback = (io.StringIO(), sink)
        done = _Done([False, True])
        reached, held = threading.Event(), threading.Event()
        self.addCleanup(held.set)

        def tower(n):
            if n:
                return tower(n - 1)
            reached.set()
            held.wait(5)        # 停在深栈里，让看门狗取到不止 12 层

        watched = threading.Thread(target=tower, args=(30,), daemon=True)
        watched.start()
        self.assertTrue(reached.wait(5))
        watcher = threading.Thread(target=inproc._watchdog,
                                   args=(watched.ident, "run.py x", done), daemon=True)
        watcher.start()
        watcher.join(5)
        held.set()
        watched.join(5)
        self.assertFalse(watcher.is_alive(), "done 置位后看门狗要退出")
        self.assertEqual(done.waits, [inproc.WATCHDOG_INTERVAL] * 2)
        report = sink.buf
        self.assertTrue(report.startswith("[watchdog] run.py x 仍在运行：\n"), report)
        self.assertIn("tower", report)          # 报的是被观察线程的栈
        self.assertNotIn("_watchdog", report)   # 不是看门狗自己的栈
        self.assertNotIn("XXXX", report)        # 帧之间用换行拼，不是占位串
        self.assertLessEqual(report.count("  File "), inproc.WATCHDOG_FRAMES)  # 上限 12 层，不整栈倒出
        self.assertEqual(sink.flushes, 1)

    def test_the_watchdog_thread_is_daemonic(self):
        """看门狗是守护线程：卡住时不能拖住解释器退出。"""
        done = _Done([True])
        thread = inproc._start_watchdog(["x.py"], done)
        self.assertTrue(thread.daemon)
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_the_watchdog_names_the_running_script(self):
        """top 把脚本前 4 个参数按空格拼成名字交给看门狗：多了少了都不是它。"""
        self.script("slow_ok.py", "import time\ntime.sleep(0.3)\n")
        saved = inproc._fallback
        self.addCleanup(setattr, inproc, "_fallback", saved)
        sink = _FlushSink()
        inproc._fallback = (io.StringIO(), sink)
        saved_interval = inproc.WATCHDOG_INTERVAL
        self.addCleanup(setattr, inproc, "WATCHDOG_INTERVAL", saved_interval)
        inproc.WATCHDOG_INTERVAL = 0.05
        self.assertEqual(inproc.Runner(lambda: dict(os.environ)).run(
            "slow_ok.py", "x", "y", "z", "w", timeout=5), ("", "", 0))
        self.assertIn("[watchdog] slow_ok.py x y z 仍在运行：", sink.buf)

    def test_after_run_callbacks_run_and_a_failure_does_not_block_the_rest(self):
        self.script("ok.py", "print('ok')\n")
        calls = []

        def first():
            calls.append("first")

        def explode():
            raise RuntimeError("callback boom")

        inproc.after_run[:] = [first, explode]
        saved_fallback = inproc._fallback
        self.addCleanup(setattr, inproc, "_fallback", saved_fallback)
        err, other = io.StringIO(), io.StringIO()
        inproc._fallback = (io.StringIO(), err)
        sys.stderr = other      # 回调的堆栈要写回 setup 记下的那份，而不是碰巧当前的 sys.stderr（tearDown 会还回去）
        out, _, rc = inproc.Runner(lambda: dict(os.environ)).run("ok.py")
        self.assertEqual((out, rc), ("ok\n", 0))
        self.assertEqual(calls, ["first"])
        self.assertIn("callback boom", err.getvalue())
        self.assertNotIn("callback boom", other.getvalue())


class WaitTest(unittest.TestCase):
    """读超时只 warn 并回落，不穿透：机型脚本的 click_exists 只捕 UiObjectNotFoundError。"""

    class Device:
        """前 failures 次读屏抛超时，之后正常。"""

        def __init__(self, page, failures=1):
            self.page, self.failures, self.reads = page, failures, 0
            self.jsonrpc, self.wait_timeout = None, 20.0

        def dump_hierarchy(self, *a, **k):
            self.reads += 1
            if self.reads <= self.failures:
                raise u2.HTTPTimeoutError("read timeout")
            return self.page

    def test_read_timeout_falls_back_instead_of_raising(self):
        obj = u2.UiObject(self.Device(PAGE7), u2.Selector(text="菜单"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.assertTrue(obj.wait())
        self.assertEqual(len(w), 1)

    def test_giving_up_returns_false_rather_than_raising(self):
        obj = u2.UiObject(self.Device(PAGE7, failures=99), u2.Selector(text="菜单"))
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            self.assertFalse(obj.wait())


class SelectorTest(unittest.TestCase):
    def test_mask_matches_uiautomator2(self):
        s = u2.Selector(resourceId="a:id/b", text="我的")
        self.assertEqual(s["mask"], 0x200000 | 0x01)
        c = s.clone()
        c["instance"] = 2
        self.assertEqual(c["mask"], 0x200000 | 0x01 | 0x01000000)
        self.assertNotIn("instance", s)
        with self.assertRaises(ReferenceError):
            u2.Selector(bogus=1)

    def test_defaults_are_empty(self):
        s = u2.Selector()
        self.assertEqual(s["mask"], 0)
        self.assertEqual(s["childOrSibling"], [])
        self.assertEqual(s["childOrSiblingSelector"], [])

    def test_unknown_field_names_the_field(self):
        with self.assertRaises(ReferenceError) as caught:
            u2.Selector(bogus=1)
        self.assertEqual(caught.exception.args[0], "bogus is not allowed.")


class AdbHelpersTest(unittest.TestCase):
    """adb 替换层的辅助函数：解析命令行、文本模式、脚本识别、CompletedProcess 组装（#1508）。"""

    def test_split_drops_every_two_arg_global_option(self):
        self.assertEqual(
            adb._split(["-s", "local", "-t", "1", "-H", "h", "-P", "2", "-L", "x", "get-state", "a"]),
            ("get-state", ["a"]))

    def test_split_treats_an_unknown_flag_as_one_token(self):
        self.assertEqual(adb._split(["-d", "devices"]), ("devices", []))

    def test_split_of_only_flags_or_empty_is_empty(self):
        self.assertEqual(adb._split(["-s"]), ("", []))
        self.assertEqual(adb._split([]), ("", []))

    def test_split_accepts_a_tuple(self):
        self.assertEqual(adb._split(("-s", "x", "shell", "ls")), ("shell", ["ls"]))

    def test_decode_returns_bytes_without_text_mode(self):
        self.assertEqual(adb._decode(b"\xe4\xb8\xad", {}), b"\xe4\xb8\xad")

    def test_decode_honours_each_text_flag(self):
        data = b"\xe4\xb8\xad"
        self.assertEqual(adb._decode(data, {"text": True}), "中")
        self.assertEqual(adb._decode(data, {"universal_newlines": True}), "中")
        self.assertEqual(adb._decode(data, {"encoding": "utf-8"}), "中")
        self.assertEqual(adb._decode(b"\xff", {"errors": "ignore"}), "")

    def test_decode_uses_the_given_encoding_and_errors(self):
        self.assertEqual(adb._decode(b"\xe9", {"text": True, "encoding": "latin-1"}), "é")
        self.assertEqual(adb._decode(b"\xffa", {"text": True, "errors": "ignore"}), "a")

    def test_input_bytes_encodes_text_and_passes_bytes_through(self):
        self.assertEqual(adb._input_bytes({"input": "中"}), b"\xe4\xb8\xad")
        self.assertEqual(adb._input_bytes({"input": "é", "encoding": "latin-1"}), b"\xe9")
        self.assertEqual(adb._input_bytes({"input": b"x"}), b"x")
        self.assertIsNone(adb._input_bytes({}))

    def test_is_script_recognizes_the_two_engine_spellings(self):
        self.assertTrue(adb._is_script([inproc.EXECUTABLE, "run.py"]))
        self.assertTrue(adb._is_script([inproc.EXECUTABLE, "--cli", "foo"]))
        self.assertFalse(adb._is_script([inproc.EXECUTABLE, "-c", "x"]))
        self.assertFalse(adb._is_script(["/other/python", "run.py"]))
        self.assertFalse(adb._is_script(["python"]))

    def test_completed_capture_and_text(self):
        cp = adb._completed(["x"], 0, b"out\n", b"err\n", {"capture_output": True, "text": True})
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, "out\n", "err\n"))
        self.assertEqual(cp.args, ["x"])

    def test_completed_without_capture_leaves_streams_none(self):
        cp = adb._completed(["x"], 0, b"o", b"e", {})
        self.assertIsNone(cp.stdout)
        self.assertIsNone(cp.stderr)

    def test_completed_stdout_and_stderr_pipe(self):
        self.assertIsNotNone(adb._completed(["x"], 0, b"o", b"e", {"stdout": subprocess.PIPE}).stdout)
        self.assertIsNone(adb._completed(["x"], 0, b"o", b"e", {"stdout": subprocess.PIPE}).stderr)
        self.assertIsNone(adb._completed(["x"], 0, b"o", b"e", {"stderr": subprocess.PIPE}).stdout)
        self.assertIsNotNone(adb._completed(["x"], 0, b"o", b"e", {"stderr": subprocess.PIPE}).stderr)

    def test_completed_merges_stderr_into_stdout(self):
        cp = adb._completed(["x"], 0, b"o", b"e",
                            {"capture_output": True, "stderr": subprocess.STDOUT})
        self.assertEqual(cp.stdout, b"oe")

    def test_completed_check_raises_with_details(self):
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            adb._completed(["prog"], 3, b"o", b"e", {"capture_output": True, "check": True})
        err = ctx.exception
        self.assertEqual((err.returncode, err.cmd, err.output, err.stderr),
                         (3, ["prog"], b"o", b"e"))

    def test_completed_without_check_does_not_raise(self):
        self.assertEqual(adb._completed(["x"], 3, b"o", b"e", {"capture_output": True}).returncode, 3)


class AdbChannelTest(unittest.TestCase):
    """把 `subprocess.run/call/check_output` 接到 adb 占位命令、脚本与真实子进程三条路上（#1508）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.placeholder = os.path.join(self.tmp.name, "bin", "adb")
        os.makedirs(os.path.dirname(self.placeholder), exist_ok=True)
        open(self.placeholder, "w").close()
        self.fake = FakeBridge()
        self.addCleanup(self._restore, bridge._bridge, adb.ADB_PATH, dict(adb._orig))
        bridge._bridge = self.fake
        adb.ADB_PATH = self.placeholder

    def _restore(self, bridge0, adb_path, orig):
        bridge._bridge = bridge0
        adb.ADB_PATH = adb_path
        adb._orig.clear()
        adb._orig.update(orig)

    def _passthrough(self, **stub):
        adb._orig.clear()
        adb._orig.update(stub)

    def test_run_answers_the_placeholder_command(self):
        argv = [self.placeholder, "-s", "local", "shell", "echo"]
        cp = adb._run(argv, capture_output=True, text=True, encoding="utf-8",
                      timeout=5, input=b"in")
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, "out\n", "err\n"))
        self.assertEqual(cp.args, argv)
        self.assertEqual(self.fake.last_exec_timeout, 5)
        self.assertEqual(self.fake.cmds[-1], ("echo", b"in"))

    def test_run_hands_a_script_to_inproc(self):
        recorded = {}
        def fake_call(argv, capture=False):
            recorded["argv"], recorded["capture"] = argv, capture
            return 7, "so", "se"
        argv = [inproc.EXECUTABLE, "run.py", "x"]
        with mock.patch.object(inproc, "call", fake_call):
            cp = adb._run(argv, capture_output=True)
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (7, b"so", b"se"))
        self.assertEqual(cp.args, argv)
        self.assertEqual(recorded, {"argv": ["run.py", "x"], "capture": True})

    def test_run_a_script_captures_when_only_stdout_is_piped(self):
        recorded = {}
        def fake_call(argv, capture=False):
            recorded["capture"] = capture
            return 0, "", ""
        with mock.patch.object(inproc, "call", fake_call):
            adb._run([inproc.EXECUTABLE, "run.py"], stdout=subprocess.PIPE)
        self.assertTrue(recorded["capture"])

    def test_run_falls_through_to_the_real_subprocess(self):
        sentinel = subprocess.CompletedProcess(["ls", "-l"], 0, b"", b"")
        seen = {}
        def stub(argv, *a, **kw):
            seen.update(argv=argv, a=a, kw=kw)
            return sentinel
        self._passthrough(run=stub)
        self.assertIs(adb._run(["ls", "-l"], "extra", timeout=3), sentinel)
        self.assertEqual(seen, {"argv": ["ls", "-l"], "a": ("extra",), "kw": {"timeout": 3}})

    def test_call_returns_the_code_for_placeholder_and_script(self):
        self.assertEqual(adb._call([self.placeholder, "version"]), 0)
        with mock.patch.object(inproc, "call", lambda argv, capture=False: (5, "", "")):
            self.assertEqual(adb._call([inproc.EXECUTABLE, "run.py"]), 5)

    def test_call_forwards_timeout_and_input_to_adb(self):
        adb._call([self.placeholder, "shell", "x"], timeout=5, input=b"in")
        self.assertEqual(self.fake.last_exec_timeout, 5)
        self.assertEqual(self.fake.cmds[-1], ("x", b"in"))

    def test_call_falls_through(self):
        seen = {}
        def stub(argv, *a, **kw):
            seen.update(argv=argv, a=a, kw=kw)
            return 9
        self._passthrough(call=stub)
        self.assertEqual(adb._call(["ls"], "pos", timeout=2), 9)
        self.assertEqual(seen, {"argv": ["ls"], "a": ("pos",), "kw": {"timeout": 2}})

    def test_check_output_returns_stdout_for_placeholder_and_script(self):
        self.assertEqual(adb._check_output([self.placeholder, "version"]), adb.VERSION_TEXT.encode())
        with mock.patch.object(inproc, "call", lambda argv, capture=False: (0, "hi\n", "")):
            self.assertEqual(adb._check_output([inproc.EXECUTABLE, "run.py"]), b"hi\n")

    def test_check_output_keeps_the_callers_text_mode(self):
        self.assertEqual(adb._check_output([self.placeholder, "version"], text=True), adb.VERSION_TEXT)

    def test_check_output_raises_on_a_failed_command(self):
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            adb._check_output([self.placeholder, "shell", "fail"])
        self.assertEqual(ctx.exception.returncode, 3)

    def test_check_output_falls_through(self):
        seen = {}
        def stub(argv, *a, **kw):
            seen.update(argv=argv, a=a, kw=kw)
            return b"real"
        self._passthrough(check_output=stub)
        self.assertEqual(adb._check_output(["ls"], "pos", timeout=2), b"real")
        self.assertEqual(seen, {"argv": ["ls"], "a": ("pos",), "kw": {"timeout": 2}})

    def test_install_creates_the_placeholder_and_patches_once(self):
        saved = (adb.ADB_PATH, dict(adb._orig), subprocess.run)
        try:
            adb._orig.clear()
            adb.install(self.placeholder)
            self.assertEqual(adb.ADB_PATH, self.placeholder)
            self.assertIs(subprocess.run, adb._run)
            with open(self.placeholder, "w", encoding="utf-8") as handle:
                handle.write("keep")
            adb.install(self.placeholder)          # 幂等：不重开、不清空已有文件
            with open(self.placeholder, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "keep")
        finally:
            adb.ADB_PATH = saved[0]
            adb._orig.clear()
            adb._orig.update(saved[1])
            subprocess.run = saved[2]


class AdbAnswerTest(unittest.TestCase):
    """`_answer` 的各条 adb 语义与 `answer` 的异常处理（#1508）。"""

    def setUp(self):
        self.fake = FakeBridge()
        saved = bridge._bridge
        self.addCleanup(setattr, bridge, "_bridge", saved)
        bridge._bridge = self.fake

    def test_version_reports_the_pinned_build(self):
        self.assertEqual(adb.answer(["version"]), (0, adb.VERSION_TEXT.encode(), b""))

    def test_server_commands_are_noops(self):
        self.assertEqual(adb.answer(["start-server"]), (0, b"", b""))
        self.assertEqual(adb.answer(["kill-server"]), (0, b"", b""))

    def test_devices_lists_the_local_serial_when_ready(self):
        self.assertEqual(adb.answer(["devices"]),
                         (0, b"List of devices attached\nlocal\tdevice\n\n", b""))
        self.fake.is_ready = False
        self.assertEqual(adb.answer(["devices"])[1], b"List of devices attached\n\n")

    def test_get_state_follows_the_bridge(self):
        self.assertEqual(adb.answer(["get-state"]), (0, b"device\n", b""))
        self.fake.is_ready = False
        self.assertEqual(adb.answer(["get-state"]), (1, b"", adb.NOT_READY))

    def test_shell_joins_arguments_and_passes_timeout(self):
        rc, out, err = adb.answer(["shell", "pm", "list"], stdin=b"in", timeout=9)
        self.assertEqual((rc, out, err), (0, b"out\n", b"err\n"))
        self.assertEqual(self.fake.cmds[-1], ("pm list", b"in"))
        self.assertEqual(self.fake.last_exec_timeout, 9)

    def test_exec_out_takes_the_same_branch(self):
        adb.answer(["exec-out", "cat", "x"])
        self.assertEqual(self.fake.cmds[-1][0], "cat x")

    def test_shell_when_not_ready_is_not_ready(self):
        self.fake.is_ready = False
        self.assertEqual(adb.answer(["shell", "ls"]), (1, b"", adb.NOT_READY))

    def test_shell_timeout_becomes_timeout_expired(self):
        self.fake.exec_result = bridge.Result(0, b"", b"", timed_out=True)
        with self.assertRaises(subprocess.TimeoutExpired) as ctx:
            adb.answer(["shell", "sleep"], timeout=4)
        self.assertEqual((ctx.exception.cmd, ctx.exception.timeout), (["shell", "sleep"], 4))

    def test_push_to_a_directory_keeps_the_file_name(self):
        src = os.path.join(self.tmp_name(), "a.dex")
        with open(src, "wb") as handle:
            handle.write(b"\x00dex")
        self.assertEqual(adb.answer(["push", src, "/data/local/tmp/"], timeout=6),
                         (0, f"{src}: 1 file pushed, 0 skipped.\n".encode(), b""))
        self.assertEqual(self.fake.cmds[-1], ("cat > /data/local/tmp/a.dex", b"\x00dex"))
        self.assertEqual(self.fake.last_exec_timeout, 6)
        self.assertEqual(adb.answer(["push", src, "/data/local/tmp/a.dex"])[1],
                         f"{src}: 1 file pushed, 0 skipped.\n".encode())

    def test_push_takes_the_last_argument_as_the_remote(self):
        src = os.path.join(self.tmp_name(), "a.dex")
        dst = os.path.join(self.tmp_name(), "remote.dex")
        with open(src, "wb") as handle:
            handle.write(b"data")
        adb.answer(["push", "ignored", src, dst])
        self.assertEqual(self.fake.cmds[-1], (f"cat > {dst}", b"data"))

    def test_push_failure_reports_the_bridge_error_or_a_default(self):
        src = os.path.join(self.tmp_name(), "a.dex")
        open(src, "wb").close()
        self.fake.exec_result = bridge.Result(3, b"", b"")
        self.assertEqual(adb.answer(["push", src, "/tmp/x"]),
                         (3, b"", b"adb: error: failed to copy\n"))
        self.fake.exec_result = bridge.Result(3, b"", b"boom\n")
        self.assertEqual(adb.answer(["push", src, "/tmp/x"])[2], b"boom\n")

    def test_push_tries_to_connect_first(self):
        src = os.path.join(self.tmp_name(), "a.dex")
        open(src, "wb").close()
        self.fake.ensure_seq = [False]
        self.assertEqual(adb.answer(["push", src, "/tmp/x"]), (1, b"", adb.NOT_READY))

    def test_pull_writes_the_file_and_reports(self):
        dst = os.path.join(self.tmp_name(), "b")
        self.assertEqual(adb.answer(["pull", "/data/local/tmp/x", dst], timeout=8),
                         (0, b"/data/local/tmp/x: 1 file pulled.\n", b""))
        self.assertEqual(self.fake.last_exec_timeout, 8)
        self.assertIsNone(self.fake.cmds[-1][1])
        self.assertEqual(self.fake.cmds[-1][0], "cat /data/local/tmp/x")
        with open(dst, "rb") as handle:
            self.assertEqual(handle.read(), b"remote-bytes")

    def test_pull_writes_the_last_argument(self):
        remote = os.path.join(self.tmp_name(), "remote")
        dst = os.path.join(self.tmp_name(), "local")
        adb.answer(["pull", "ignored", remote, dst])
        with open(dst, "rb") as handle:
            self.assertEqual(handle.read(), b"remote-bytes")
        self.assertFalse(os.path.exists(remote))

    def test_pull_failure_and_not_connected(self):
        dst = os.path.join(self.tmp_name(), "b")
        self.fake.exec_result = bridge.Result(1, b"", b"err\n")
        self.assertEqual(adb.answer(["pull", "/x", dst]), (1, b"", b"err\n"))
        self.fake.ensure_seq = [False]
        self.assertEqual(adb.answer(["pull", "/x", dst]), (1, b"", adb.NOT_READY))

    def test_unsupported_command_names_it(self):
        self.assertEqual(adb.answer(["forward", "tcp:1"]), (1, b"", "adb: 手机版不支持 forward\n".encode()))
        self.assertEqual(adb.answer(["forward", "a", "b"]), (1, b"", "adb: 手机版不支持 forward\n".encode()))

    def test_unsupported_command_when_not_ready(self):
        self.fake.is_ready = False
        self.assertEqual(adb.answer(["forward"]), (1, b"", adb.NOT_READY))

    def test_wait_for_device_returns_once_connected(self):
        self.fake.ensure_seq = [True]
        self.assertEqual(adb.answer(["wait-for-device"]), (0, b"", b""))

    def test_wait_for_device_times_out(self):
        self.fake.ensure_seq = [False] * 10
        clock = iter(range(0, 1000))
        with mock.patch.object(adb.time, "monotonic", lambda: next(clock)), \
                mock.patch.object(adb.time, "sleep", lambda _s: None):
            with self.assertRaises(subprocess.TimeoutExpired) as ctx:
                adb.answer(["wait-for-device"], timeout=0.05)
        self.assertEqual((ctx.exception.cmd, ctx.exception.timeout), (["wait-for-device"], 0.05))

    def test_wait_for_device_polls_every_half_second_for_the_30s_default(self):
        """默认等 30 秒、每 0.5 秒试一次：整秒推进时应当睡 30 次、每次 0.5，才在越过 30 时放弃。"""
        self.fake.ensure_seq = [False] * 1000
        sleeps = []
        ticks = iter(range(0, 10_000))
        with mock.patch.object(adb.time, "monotonic", lambda: next(ticks)), \
                mock.patch.object(adb.time, "sleep", lambda s: sleeps.append(s)):
            with self.assertRaises(subprocess.TimeoutExpired):
                adb.answer(["wait-for-device"])
        self.assertEqual(len(sleeps), 30)
        self.assertEqual(set(sleeps), {0.5})

    def test_unexpected_error_is_logged_then_reraised(self):
        class BoomBridge(FakeBridge):
            def exec(self, cmd, stdin=None, timeout=None):
                raise ValueError("boom")
        bridge._bridge = BoomBridge()
        sink = io.StringIO()
        saved = inproc._fallback
        inproc._fallback = (saved[0], sink)
        try:
            with self.assertRaises(ValueError):
                adb.answer(["shell", "x"])
        finally:
            inproc._fallback = saved
        self.assertIn("boom", sink.getvalue())

    def tmp_name(self):
        if not hasattr(self, "_tmp"):
            self._tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self._tmp.cleanup)
        return self._tmp.name


EMPTY_PAGE = '<hierarchy rotation="0" />'


class _Clipboard:
    """`jsonrpc.setClipboard` 的替身：记下 (label, text)。"""

    def __init__(self):
        self.calls = []

    def setClipboard(self, label, text, http_timeout=10):
        self.calls.append((label, text))


class _Node:
    """u2.UiObject 用的假设备：按页面回 dump（可按次数换页 / 抛错），记下 shell、点按与剪贴板。"""

    def __init__(self, page=PAGE7, exit_code=0, wait_timeout=20.0, pages=None):
        self.page, self.exit_code, self.wait_timeout = page, exit_code, wait_timeout
        self.pages = pages          # [(前 N 次, 页面或异常)]：让读屏在 wait 与取节点之间变化
        self.jsonrpc = _Clipboard()
        self.cmds, self.clicks = [], []
        self.reads = 0

    def dump_hierarchy(self, *a, **k):
        self.reads += 1
        page = self.page
        if self.pages:
            for upto, candidate in self.pages:
                if self.reads <= upto:
                    page = candidate
                    break
        if isinstance(page, BaseException):
            raise page
        return page

    def shell(self, cmdargs, timeout=60):
        self.cmds.append(cmdargs if isinstance(cmdargs, str) else list(cmdargs))
        return u2.ShellResponse("", self.exit_code)

    def click(self, x, y):
        self.clicks.append((x, y))


class DeviceBridge:
    """u2.Device 用的假通道：按命令回包，记下 exec 的 (命令, stdin, 超时)。"""

    def __init__(self, code=0, timed_out=False, out=b"", err=b""):
        self.code, self.timed_out, self.out, self.err = code, timed_out, out, err
        self.exec_args, self.displays = [], []

    def exec(self, cmd, stdin=None, timeout=None):
        self.exec_args.append((cmd, stdin, timeout))
        return bridge.Result(self.code, self.out, self.err, self.timed_out)

    def dump(self, display):
        self.displays.append(display)
        return bridge.Result(self.code, self.out, self.err, self.timed_out)

    def size(self, display):
        self.displays.append(display)
        return bridge.Result(self.code, self.out, self.err, self.timed_out)

    def ready(self):
        return True

    def ensure(self):
        return True


class ModuleHelperTest(unittest.TestCase):
    """模块级的读屏小工具（#1511）：屏号、字节转文字、读屏失败分类。"""

    def test_display_reads_zero_without_a_background_screen(self):
        saved = screen.active
        screen.active = None
        try:
            self.assertEqual(u2.display(), 0)
        finally:
            screen.active = saved

    def test_display_reports_a_lost_screen_with_the_read_wording(self):
        saved = (screen.active, screen.LOST)
        screen.active = screen.Screen(7, "11")
        screen.active.lost = True
        screen.LOST = ""        # 落进「<what>失败」兜底，才看得出 display 传的 what 是「读屏」
        try:
            with self.assertRaises(u2.UiAutomationError) as caught:
                u2.display()
        finally:
            screen.active, screen.LOST = saved
        self.assertEqual(str(caught.exception), "读屏失败")

    def test_text_of_decodes_bytes_and_stringifies_others(self):
        self.assertEqual(u2.text_of(b"\xe8\x8f\x9c"), "菜")
        self.assertEqual(u2.text_of(bytearray(b"ok")), "ok")
        self.assertEqual(u2.text_of("abc"), "abc")
        self.assertEqual(u2.text_of(None), "")
        self.assertEqual(u2.text_of(0), "")

    def test_text_of_replaces_bad_bytes(self):
        self.assertEqual(u2.text_of(b"a\xffb"), "a�b")

    def test_read_failed_maps_already_registered_to_the_busy_type(self):
        for message in ("already registered", "AlreadyRegistered"):
            err = u2.read_failed("读屏", message.encode())
            self.assertIsInstance(err, u2.AccessibilityServiceAlreadyRegisteredError, message)
            self.assertEqual(err.args[0], message)

    def test_read_failed_keeps_other_messages_as_a_plain_read_error(self):
        err = u2.read_failed("读屏", b"  boom  ")
        self.assertIsInstance(err, u2.UiAutomationError)
        self.assertNotIsInstance(err, u2.AccessibilityServiceAlreadyRegisteredError)
        self.assertEqual(err.args[0], "boom")


class RpcTest(unittest.TestCase):
    """jsonrpc 替身（#1511）：引擎按 uiautomator2 的 jsonrpc 调这几个方法。"""

    def test_set_text_refuses_with_the_documented_rpc_error(self):
        with self.assertRaises(u2.RPCUnknownError) as caught:
            u2._Rpc().setText({}, "x")
        self.assertEqual(caught.exception.args, (-32001, "不经读屏写字，改用剪贴板粘贴", "setText"))

    def test_unknown_methods_report_the_method_name(self):
        with self.assertRaises(u2.RPCUnknownError) as caught:
            u2._Rpc().intersect({})
        self.assertEqual(caught.exception.args, (-32601, "手机版读屏不支持 intersect", "intersect"))

    def test_set_clipboard_writes_the_text(self):
        with _using(_Reader()) as fake:
            u2._Rpc().setClipboard(None, "kw")
        self.assertIn("clipboard:kw", fake.cmds)

    def test_device_info_reports_the_window_size(self):
        dev = SimpleNamespace(window_size=lambda: (1080, 2400))
        self.assertEqual(u2._Rpc(dev).deviceInfo(),
                         {"displayWidth": 1080, "displayHeight": 2400, "displayRotation": 0})

    def test_clear_text_field_reports_its_method_name(self):
        with mock.patch.object(u2, "time", FakeClock()), \
                self.assertRaises(u2.UiObjectNotFoundError) as caught:
            u2._Rpc(_Node(EMPTY_PAGE)).clearTextField(u2.Selector(text="x"))
        self.assertEqual(caught.exception.args[0]["method"], "clearTextField")

    def test_shell_response_unpacks_into_output_and_code(self):
        self.assertEqual(tuple(u2.ShellResponse("o", 3)), ("o", 3))


class MatchesTest(unittest.TestCase):
    """选择器字段 → 页面节点属性（#1511）：精确 / 正则 / 包含 / 前缀 / 序号，未知字段不匹配。"""

    def setUp(self):
        import xml.etree.ElementTree as ET
        self.menu = ET.fromstring('<node text="菜单" content-desc="图标" class="android.widget.TextView" '
                                  'resource-id="com.x:id/menu" package="com.x" clickable="true" index="2" />')
        self.blank = ET.fromstring('<node class="android.widget.TextView" />')

    def test_exact_attribute_match(self):
        self.assertTrue(u2.matches(self.menu, u2.Selector(text="菜单")))
        self.assertFalse(u2.matches(self.menu, u2.Selector(text="别的")))

    def test_missing_attribute_reads_as_the_empty_string(self):
        self.assertTrue(u2.matches(self.blank, u2.Selector(text="")))

    def test_regex_match_and_a_regex_that_matches_only_empty(self):
        self.assertTrue(u2.matches(self.menu, u2.Selector(textMatches="菜.")))
        self.assertTrue(u2.matches(self.blank, u2.Selector(textMatches="^$")))

    def test_contains(self):
        self.assertTrue(u2.matches(self.menu, u2.Selector(textContains="单")))
        self.assertFalse(u2.matches(self.blank, u2.Selector(textContains="X")))

    def test_starts_with(self):
        self.assertTrue(u2.matches(self.menu, u2.Selector(textStartsWith="菜")))
        self.assertFalse(u2.matches(self.blank, u2.Selector(textStartsWith="X")))

    def test_index(self):
        self.assertTrue(u2.matches(self.menu, u2.Selector(index=2)))
        self.assertFalse(u2.matches(self.menu, u2.Selector(index=3)))

    def test_unknown_fields_never_match(self):
        self.assertFalse(u2.matches(self.menu, {"bogus": 1}))
        self.assertFalse(u2.matches(self.menu, {"fooMatches": "x"}))

    def test_bounds_reads_the_four_numbers(self):
        import xml.etree.ElementTree as ET
        self.assertEqual(u2.bounds_of(ET.fromstring('<node bounds="[10,20][30,40]" />')), (10, 20, 30, 40))
        self.assertEqual(u2.bounds_of(ET.fromstring('<node />')), (0, 0, 0, 0))


class UiObjectTest(unittest.TestCase):
    """节点读取（#1511）：wait 的截止与回落、must_wait 的报错细节、序号、读字与写字。"""

    def test_wait_stops_at_its_own_deadline(self):
        """显式 timeout 只等这么久，不退到设备默认的 20 秒；截止正好落在第二次轮询后。"""
        dev = _Node(EMPTY_PAGE)
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        with mock.patch.object(u2, "time", FakeClock()):
            self.assertFalse(obj.wait(timeout=0.3))
        self.assertEqual(dev.reads, 2)

    def test_wait_returns_true_once_the_node_appears(self):
        dev = _Node(pages=[(1, EMPTY_PAGE), (9, PAGE7)])
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        clock = FakeClock()
        with mock.patch.object(u2, "time", clock):
            self.assertTrue(obj.wait(timeout=5))
        self.assertEqual(clock.now, 0.3, "轮询间隔是 0.3 秒")

    def test_wait_warns_and_falls_back_when_the_read_times_out(self):
        dev = _Node(pages=[(1, u2.HTTPTimeoutError("read timeout")), (9, PAGE7)])
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        with mock.patch.object(u2, "time", FakeClock()), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertTrue(obj.wait())
        self.assertEqual(len(caught), 1)
        self.assertIs(caught[0].category, RuntimeWarning)
        self.assertEqual(str(caught[0].message), "wait readTimeout: read timeout")
        # 告警要指向调用方；落到 u2 自己的文件就是 stacklevel 被去掉、退回默认（变异副本里还会被 trampoline 多垫一层，所以只比「不是 u2 自己」）
        self.assertNotEqual(caught[0].filename, u2.__file__)

    def test_wait_fallback_respects_exists_false(self):
        dev = _Node(pages=[(1, u2.HTTPTimeoutError("read timeout")), (9, PAGE7)])
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        with mock.patch.object(u2, "time", FakeClock()), warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            self.assertFalse(obj.wait(exists=False))

    def test_must_wait_reports_the_selector_and_method(self):
        """找不到时抛带 code / data / method 的异常；timeout 也要传到 wait 里。"""
        dev = _Node(pages=[(1, EMPTY_PAGE), (9, PAGE7)])
        selector = u2.Selector(text="不存在")
        obj = u2.UiObject(dev, selector)
        with mock.patch.object(u2, "time", FakeClock()), \
                self.assertRaises(u2.UiObjectNotFoundError) as caught:
            obj.must_wait(timeout=0)
        self.assertEqual(caught.exception.args[0],
                         {"code": -32002, "data": str(selector), "method": "wait"})

    def test_index_picks_the_nth_match_or_raises(self):
        dev = _Node(PAGE7)
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        self.assertEqual(obj[1].get_text(), "菜单")
        with self.assertRaises(IndexError) as caught:
            obj[5]
        self.assertEqual(caught.exception.args[0], 5)

    def test_get_text_returns_the_node_text_or_empty(self):
        self.assertEqual(u2.UiObject(_Node(PAGE7), u2.Selector(text="菜单")).get_text(), "菜单")
        page = '<hierarchy><node resource-id="x" /></hierarchy>'
        self.assertEqual(u2.UiObject(_Node(page), u2.Selector(resourceId="x")).get_text(), "")

    def test_get_text_honours_its_timeout_and_names_itself(self):
        dev = _Node(pages=[(1, EMPTY_PAGE), (9, PAGE7)])
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        with mock.patch.object(u2, "time", FakeClock()), self.assertRaises(u2.UiObjectNotFoundError):
            obj.get_text(timeout=0)
        # wait 第一次读到时在，取节点那次已经没了：报错里带着 code / data / getText 方法名
        gone = u2.UiObject(_Node(pages=[(1, PAGE7), (9, EMPTY_PAGE)]), u2.Selector(text="菜单"))
        with self.assertRaises(u2.UiObjectNotFoundError) as caught:
            gone.get_text()
        self.assertEqual(caught.exception.args[0],
                         {"code": -32002, "data": str(gone.selector), "method": "getText"})

    def test_empty_selector_picks_the_first_real_node_not_the_root(self):
        """`_node` 只在 <node> 里找：空选择器不该先匹配到 XML 根元素。"""
        self.assertEqual(u2.UiObject(_Node(PAGE7), u2.Selector()).bounds(), (0, 0, 100, 100))

    def test_bounds_name_themselves_when_the_node_is_gone(self):
        with self.assertRaises(u2.UiObjectNotFoundError) as caught:
            u2.UiObject(_Node(EMPTY_PAGE), u2.Selector(text="菜单")).bounds()
        self.assertEqual(caught.exception.args[0]["method"], "bounds")

    def test_click_honours_its_timeout(self):
        dev = _Node(pages=[(1, EMPTY_PAGE), (9, PAGE7)])
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        with mock.patch.object(u2, "time", FakeClock()), self.assertRaises(u2.UiObjectNotFoundError):
            obj.click(timeout=0)

    def test_click_exists_returns_the_click_result(self):
        dev = _Node(PAGE7)
        obj = u2.UiObject(dev, u2.Selector(text="菜单", instance=1))
        self.assertTrue(obj.click_exists())
        self.assertEqual(dev.clicks, [(50, 20)])
        missing = u2.UiObject(_Node(EMPTY_PAGE), u2.Selector(text="菜单"))
        self.assertFalse(missing.click_exists())

    def test_click_exists_default_is_a_single_look(self):
        """默认 timeout=0 只查一次、不等；把它改成 1 秒会等到第二次轮询才动手。"""
        for call in (lambda o: o.click_exists(), lambda o: o.click_exists(timeout=0)):
            dev = _Node(pages=[(1, EMPTY_PAGE), (9, PAGE7)])
            obj = u2.UiObject(dev, u2.Selector(text="菜单"))
            with mock.patch.object(u2, "time", FakeClock()):
                self.assertFalse(call(obj))

    def test_set_text_clears_then_pastes(self):
        dev = _Node(PAGE7)
        u2.UiObject(dev, u2.Selector(text="菜单", instance=1)).set_text("新词")
        self.assertEqual(dev.jsonrpc.calls, [(None, "新词")])
        self.assertEqual(dev.cmds[-1], "input keyevent KEYCODE_PASTE")

    def test_set_text_with_no_text_just_clears(self):
        dev = _Node(PAGE7)
        u2.UiObject(dev, u2.Selector(text="菜单")).set_text("")
        self.assertEqual(dev.cmds[-1], "input keyevent KEYCODE_DEL")
        self.assertEqual(dev.jsonrpc.calls, [])

    def test_set_text_falls_back_to_per_character_clear(self):
        """keycombination 失败时按「菜单」字数逐字删，node 的文本要读得到。"""
        dev = _Node(PAGE7, exit_code=1)
        u2.UiObject(dev, u2.Selector(text="菜单", instance=1)).set_text("新词")
        self.assertEqual(dev.cmds.count("input keyevent KEYCODE_DEL"), 2)
        self.assertEqual(dev.cmds[-1], "input keyevent KEYCODE_PASTE")

    def test_set_text_names_itself_when_the_node_is_gone(self):
        dev = _Node(pages=[(1, PAGE7), (9, EMPTY_PAGE)])
        with self.assertRaises(u2.UiObjectNotFoundError) as caught:
            u2.UiObject(dev, u2.Selector(text="菜单")).set_text("x")
        self.assertEqual(caught.exception.args[0]["method"], "setText")

    def test_set_text_honours_its_timeout(self):
        dev = _Node(pages=[(1, EMPTY_PAGE), (9, PAGE7)])
        obj = u2.UiObject(dev, u2.Selector(text="菜单"))
        with mock.patch.object(u2, "time", FakeClock()), self.assertRaises(u2.UiObjectNotFoundError):
            obj.set_text("x", timeout=0)


class DeviceTest(unittest.TestCase):
    """u2.Device（#1511）：连上读一次、命令下发、屏尺寸、截图、按键与手势。"""

    def setUp(self):
        self.saved = (bridge._bridge, screen.active)
        screen.active = None

    def tearDown(self):
        bridge._bridge, screen.active = self.saved

    def test_device_carries_serial_settings_and_wait_timeout(self):
        with _using(DeviceBridge(out=b"<hierarchy />")):
            dev = u2.Device("abc")
        self.assertEqual(dev.serial, "abc")
        self.assertEqual(dev.wait_timeout, 20.0)
        self.assertEqual(dev.settings, {"operation_delay": (0, 0),
                                        "operation_delay_methods": ["click", "swipe"],
                                        "wait_timeout": 20.0, "max_depth": 50})

    def test_connect_builds_a_device_for_the_serial(self):
        with _using(DeviceBridge(out=b"<hierarchy />")):
            dev = u2.connect("abc")
        self.assertEqual(dev.serial, "abc")

    def test_dump_returns_the_page_and_labels_the_slow_log(self):
        slow = []
        with _using(DeviceBridge(out=b"<page />")), \
                mock.patch.object(bridge, "slow",
                                  side_effect=lambda what, started, extra="": slow.append(what)):
            page = u2.Device.__new__(u2.Device).dump_hierarchy()
        self.assertEqual(page, "<page />")
        self.assertEqual(slow, ["dump"])

    def test_dump_failure_uses_the_read_wording(self):
        dev = u2.Device.__new__(u2.Device)
        with _using(DeviceBridge(code=255, err=b"")), self.assertRaises(u2.UiAutomationError) as caught:
            dev.dump_hierarchy()
        self.assertEqual(str(caught.exception), "读屏失败")

    def test_shell_passes_the_command_timeout_and_stdin(self):
        fake = DeviceBridge(code=3, out=b"out", err=b"err")
        dev = u2.Device.__new__(u2.Device)
        with _using(fake):
            r = dev.shell("ls -l")
            dev.shell("ls", timeout=0)
        self.assertEqual(fake.exec_args[0], ("ls -l", None, 60))
        self.assertEqual(fake.exec_args[1], ("ls", None, 60))
        self.assertEqual((r.output, r.exit_code), ("outerr", 3))

    def test_shell_joins_a_list_command(self):
        fake = DeviceBridge()
        with _using(fake):
            u2.Device.__new__(u2.Device).shell(["am", "force-stop", "com.x"])
        self.assertEqual(fake.exec_args[-1][0], "am force-stop com.x")

    def test_shell_timeout_raises_with_a_bounded_command(self):
        dev = u2.Device.__new__(u2.Device)
        with _using(DeviceBridge(timed_out=True, code=1)), self.assertRaises(u2.AdbShellError) as caught:
            dev.shell("x" * 100)
        self.assertEqual(caught.exception.args[0], "shell timeout: " + "x" * 80)

    def test_window_size_reads_the_first_two_numbers(self):
        for out, want in ((b"1080 2400", (1080, 2400)), (b"1 2 3", (1, 2)),
                          (b"1080", (1080, 0)), (b"", (0, 0))):
            fake = DeviceBridge(out=out)
            with _using(fake):
                got = u2.Device.__new__(u2.Device).window_size()
            self.assertEqual(got, want, out)
            self.assertEqual(fake.displays, [0], out)

    def test_window_size_failure_names_the_size_wording(self):
        dev = u2.Device.__new__(u2.Device)
        with _using(DeviceBridge(code=255, err=b"")), self.assertRaises(u2.UiAutomationError) as caught:
            dev.window_size()
        self.assertEqual(str(caught.exception), "问屏幕尺寸失败")

    def test_screenshot_cuts_from_the_png_header_and_saves(self):
        opened, converted, saved = [], [], []

        class Image:
            def convert(self, mode):
                converted.append(mode)
                return self

            def save(self, name):
                saved.append(name)

        class PilImage:
            @staticmethod
            def open(fp):
                opened.append(fp.read())
                return Image()

        pil = SimpleNamespace(Image=PilImage)
        for out in (b"pre\x89PNG-A-and-\x89PNG-B", b"\x89PNG-Z"):
            fake = DeviceBridge(out=out)
            with _using(fake), mock.patch.dict(sys.modules, {"PIL": pil}):
                image = u2.Device.__new__(u2.Device).screenshot("/tmp/shot.png")
            self.assertIsInstance(image, Image)
            self.assertEqual(opened[-1], out[out.find(b"\x89PNG"):], out)
            self.assertEqual(fake.exec_args[-1], ("screencap -p", None, 30))
        self.assertEqual(converted, ["RGB", "RGB"])
        self.assertEqual(saved, ["/tmp/shot.png", "/tmp/shot.png"])

    def test_app_stop_forces_stop_through_shell(self):
        fake = DeviceBridge()
        with _using(fake):
            u2.Device.__new__(u2.Device).app_stop("com.x")
        self.assertEqual(fake.exec_args[-1][0], "am force-stop com.x")

    def test_swipe_builds_the_input_command(self):
        fake = DeviceBridge()
        with _using(fake):
            dev = u2.Device.__new__(u2.Device)
            dev.swipe(1, 2, 3, 4, 1.0)      # 1 秒 → 200 步 → 200×5 = 1000ms
            dev.swipe(10, 20, 30, 40)       # 没给时长 → 默认 55 步 → 275ms
            dev.swipe(1, 1, 2, 2, 0.005)    # 1 步 → 下限 2 步 → 10ms
        self.assertEqual([a[0] for a in fake.exec_args],
                         ["input swipe 1 2 3 4 1000", "input swipe 10 20 30 40 275", "input swipe 1 1 2 2 10"])

    def test_press_maps_names_and_integers_to_key_events(self):
        fake = DeviceBridge()
        with _using(fake):
            dev = u2.Device.__new__(u2.Device)
            dev.press("recent")     # 名字表里映射到 APP_SWITCH，默认兜底会写成 KEYCODE_RECENT
            dev.press("F2")         # 表里没有 → KEYCODE_F2
            dev.press(3)            # 整数当键码原样用
        self.assertEqual([a[0] for a in fake.exec_args],
                         ["input keyevent KEYCODE_APP_SWITCH", "input keyevent KEYCODE_F2", "input keyevent 3"])


INSTALLED = ("uiautomator2", "uiautomator2.exceptions", "uiautomator2.core", "adbutils", "ui_session")


class InstallTest(unittest.TestCase):
    """install() 把本模块登记成 uiautomator2 / adbutils / ui_session（#1511）。

    mutmut 默认用 fork 隔离：统计阶段在父进程里跑完整个套件，之后每个 mutant 从父进程 fork。
    父进程里若残留 install() 写进 sys.modules 的条目，会带进每一个 mutant 子进程，断言就可能读到
    上一次的残留（假存活）。所以本用例在调用前后都把被改写的那几个键快照 / 还原，父进程跑完仍是干净的。
    """

    def setUp(self):
        self.saved = _snapshot_modules(INSTALLED)

    def tearDown(self):
        _restore_modules(self.saved)

    def test_install_registers_the_replacement_modules(self):
        u2.install()
        self.assertEqual(sys.modules["uiautomator2"].__name__, "uiautomator2")
        self.assertIs(sys.modules["uiautomator2"].Device, u2.Device)
        self.assertIs(sys.modules["uiautomator2"].connect, u2.connect)
        exceptions = sys.modules["uiautomator2.exceptions"]
        self.assertEqual(exceptions.__name__, "uiautomator2.exceptions")
        self.assertIs(exceptions.UiObjectNotFoundError, u2.UiObjectNotFoundError)
        self.assertIs(exceptions.AccessibilityServiceAlreadyRegisteredError,
                      u2.AccessibilityServiceAlreadyRegisteredError)
        core = sys.modules["uiautomator2.core"]
        self.assertEqual(core.__name__, "uiautomator2.core")
        self.assertTrue(callable(core._http_request))
        self.assertEqual(sys.modules["adbutils"].__name__, "adbutils")
        self.assertIs(sys.modules["adbutils"].AdbError, u2.AdbError)
        session = sys.modules["ui_session"]
        self.assertEqual(session.__name__, "ui_session")
        self.assertIs(session.connect, u2.connect)
        self.assertIs(session.DeviceBusyError, u2.DeviceBusyError)
        self.assertIs(session.ManagedDevice, u2.Device)

    def test_install_http_request_refuses(self):
        u2.install()
        with self.assertRaises(u2.RPCUnknownError) as caught:
            sys.modules["uiautomator2.core"]._http_request()
        self.assertEqual(caught.exception.args, (-32601, "手机版没有读屏 HTTP 服务", "_http_request"))

    def test_install_is_reversible(self):
        before = _snapshot_modules(INSTALLED)
        u2.install()
        self.assertIsNot(sys.modules["uiautomator2"], before.get("uiautomator2"))
        _restore_modules(before)
        self.assertEqual(_snapshot_modules(INSTALLED), before)


if __name__ == "__main__":
    unittest.main()
