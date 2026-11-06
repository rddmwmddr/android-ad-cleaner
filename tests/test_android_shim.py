"""手机版替换层（android/app/src/main/python/aac_android）：不连手机，替换掉执行通道后验 adb 语义、进程内脚本、选择器。"""
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))

from aac_android import adb, bridge, inproc, u2  # noqa: E402


class FakeBridge:
    def __init__(self, ready=True):
        self.is_ready, self.cmds = ready, []

    def ready(self):
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

    def test_subprocess_run_is_answered_for_the_placeholder_only(self):
        with tempfile.TemporaryDirectory() as d:
            saved = (adb.ADB_PATH, dict(adb._orig), subprocess.run, subprocess.call, subprocess.check_output)
            try:
                adb._orig.clear()
                adb.install(os.path.join(d, "bin", "adb"))
                r = subprocess.run([adb.ADB_PATH, "-s", "local", "shell", "echo"], capture_output=True, text=True)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "out\n", "err\n"))
                other = subprocess.run([sys.executable, "-c", "print(42)"], capture_output=True, text=True)
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


class ShizukuPollTest(unittest.TestCase):
    """等命令时不占解释器锁、超时自己掐：Java 那边的 waitForTimeout 在真机上没按时返回。"""

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
        b = bridge.ShizukuBridge.__new__(bridge.ShizukuBridge)
        b.shell = type("S", (), {"submit": staticmethod(lambda cmd, stdin: job)})()
        return b

    def test_returns_when_done(self):
        r = self.bridge_with(self.Job(3)).exec("ls", None, 5)
        self.assertEqual((r.code, r.out, r.timed_out), (0, b"ok", False))

    def test_times_out_and_cancels(self):
        job = self.Job(10 ** 9)
        r = self.bridge_with(job).exec("monkey", None, 0.05)
        self.assertTrue(r.timed_out)
        self.assertTrue(job.cancelled)


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

    def test_modules_are_fresh_per_top_level_run(self):
        self.script("counter.py", "N = []\n")
        self.script("bump.py", "import counter\ncounter.N.append(1)\nprint(len(counter.N))\n")
        run = inproc.Runner(lambda: dict(os.environ)).run
        self.assertEqual(run("bump.py")[0], "1\n")
        self.assertEqual(run("bump.py")[0], "1\n")


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
