"""手机版替换层（android/app/src/main/python/aac_android）：不连手机，替换掉执行通道后验 adb 语义、进程内脚本、选择器。"""
import contextlib
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))

from aac_android import adb, bridge, inproc, main, screen, u2  # noqa: E402


class FakeBridge:
    def __init__(self, ready=True):
        self.is_ready, self.cmds, self.calls = ready, [], []

    def ready(self):
        self.calls.append("ready")
        return self.is_ready

    def ensure(self):
        self.calls.append("ensure")
        return self.is_ready

    def exec(self, cmd, stdin=None, timeout=None):
        self.cmds.append((cmd, stdin))
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


class ScreenBridge:
    """screen.start() / stop() 用的假通道：按命令回答，按顺序记下调用。"""

    def __init__(self, log="DISPLAY 7 flags=0x1f5c9\n", sf_id=11):
        self.log, self.sf_id = log, sf_id
        self.pid = False        # PID_FILE 在不在
        self.stale = False      # 上一次的 Vd 还占着，SurfaceFlinger 里还有一块同名屏
        self.built = False      # 本次的 Vd 起来了
        self.deciding_when_spawned = None   # 拉起 Vd 那一刻界面的说法：应当还在等结论
        self.cmds = []

    def exec(self, cmd, stdin=None, timeout=None):
        self.cmds.append(cmd)
        if cmd.startswith("kill $(cat"):
            self.pid, self.stale = False, False     # 进程死了，它那块屏随之消失
        if cmd.startswith("pm path"):
            out = "package:/data/app/x/base.apk"
        elif cmd == "wm size":
            out = "Physical size: 1080x2400"
        elif cmd == "wm density":
            out = "Physical density: 440"
        elif cmd.startswith("cat /data/local/tmp/aac-vd.log"):
            out = self.log
        elif cmd.startswith("dumpsys SurfaceFlinger"):
            out = ('Virtual Display 3\n  name="aac-bg"\n' if self.stale else "") + \
                  (f'Virtual Display {self.sf_id}\n  name="aac-bg"\n' if self.built else "")
        elif cmd.startswith("[ -f /data/local/tmp/aac-vd.pid ]"):
            out = "yes" if self.pid else ""
        else:
            out = ""
        return bridge.Result(0, out.encode(), b"")

    def daemon(self, name, cmd):
        self.cmds.append(f"daemon {name}")
        self.deciding_when_spawned = screen.starting
        self.built, self.pid = True, True
        return True

    def stop_daemon(self, name):
        self.cmds.append(f"stop_daemon {name}")


class ScreenLifecycleTest(unittest.TestCase):
    """建屏 / 拆屏（#618）：起停成对、不建第二块、失败只拆本次、进程被杀后的残留先清掉。"""

    def setUp(self):
        self.saved = (screen.active, screen.starting, bridge._bridge)
        screen.active, screen.starting = None, False
        self.fake = ScreenBridge()
        bridge._bridge = self.fake

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
        screen.stop()
        self.assertIsNone(screen.active)
        self.assertEqual(self.fake.cmds[-2], "stop_daemon vd")

    def test_degraded_flags_keep_the_screen_lockable(self):
        self.fake.log = "DISPLAY 7 flags=0x1c9\n"
        self.assertFalse(screen.start("com.ahuamiao.adcleaner").unlocked)

    def test_the_screen_is_deciding_while_vd_starts(self):
        """界面在结论出来前要一直问：这条状态只有 start() 里那一处置真。"""
        screen.start("com.ahuamiao.adcleaner")
        self.assertTrue(self.fake.deciding_when_spawned)
        self.assertFalse(screen.starting)

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


class InprocTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tool = Path(self.dir.name)
        self.saved = (inproc.TOOL, sys.stdout, sys.stderr, inproc._fallback)
        inproc.setup(str(self.tool))

    def tearDown(self):
        inproc.TOOL = self.saved[0]
        sys.stdout, sys.stderr, inproc._fallback = self.saved[1:]
        if str(self.tool) in sys.path:
            sys.path.remove(str(self.tool))
        self.dir.cleanup()

    def script(self, name, body):
        (self.tool / name).write_text(textwrap.dedent(body), encoding="utf-8")

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
        lines = iter(proc.stdout)
        self.assertEqual(next(lines), "start\n")
        time.sleep(0.05)
        proc.terminate()
        self.assertEqual(proc.wait(5), -15)

    def test_run_times_out_and_leaves_the_next_run_usable(self):
        self.script("slow.py", """
            import time
            while True:
                time.sleep(0.01)
        """)
        self.script("ok.py", "print('ok')\n")
        run = inproc.Runner(lambda: dict(os.environ)).run
        with self.assertRaises(subprocess.TimeoutExpired):
            run("slow.py", timeout=0.2)
        # 打断后锁与环境变量都要还回来，下一步照常跑
        self.assertEqual(run("ok.py", timeout=5), ("ok\n", "", 0))

    def test_modules_are_fresh_per_top_level_run(self):
        self.script("counter.py", "N = []\n")
        self.script("bump.py", "import counter\ncounter.N.append(1)\nprint(len(counter.N))\n")
        run = inproc.Runner(lambda: dict(os.environ)).run
        self.assertEqual(run("bump.py")[0], "1\n")
        self.assertEqual(run("bump.py")[0], "1\n")


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


if __name__ == "__main__":
    unittest.main()
