"""以 shell 身份执行命令的通道。

手机上走 Shizuku（Kotlin 的 ShizukuShell）；在电脑上调试这一层时设 AAC_BRIDGE_ADB / AAC_BRIDGE_SERIAL，
改走真 adb，替换层的其余部分不用改就能对着模拟器跑。
"""
import os
import re
import shlex
import subprocess
import sys
import time

# 替换层会改写 subprocess.run 等函数：电脑调试通道必须拿改写前的那一份
_run = subprocess.run
_popen = subprocess.Popen

U2_PORT = 9008
SLOW = 3.0


def slow(what, started, extra=""):
    """超过 3 秒的命令 / 读屏请求记进 logcat，查「卡住」用。"""
    took = time.monotonic() - started
    if took > SLOW:
        from . import inproc
        print(f"[slow] {took:.1f}s {what} {extra}", file=inproc._fallback[1] if inproc._fallback[1] else sys.__stderr__, flush=True)


MONKEY = re.compile(r"^monkey -p (\S+) -c android\.intent\.category\.LAUNCHER 1$")


def launcher(cmd):
    """引擎用 `monkey -p 包名 -c LAUNCHER 1` 拉起 App；经 Shizuku 跑 monkey 会卡住，直到别的界面到前台
    （小米 18 Pro Max 实测 122 秒）。换成查出启动页再 am start，输出照 monkey 的写法，引擎的判断不用改。"""
    m = MONKEY.match(cmd.strip())
    if not m:
        return cmd
    pkg = shlex.quote(m.group(1))
    return (f"c=$(cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {pkg} | tail -n 1); "
            'case "$c" in */*) am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER '
            '-f 0x10200000 -n "$c" >/dev/null 2>&1 && echo "Events injected: 1" || '
            '{ echo "** monkey aborted: launch failed"; exit 1; };; '
            '*) echo "** No activities found to run, monkey aborted."; exit 1;; esac')


def prepare(cmd):
    """发给手机前的改写：monkey 拉起换成 am start，再按后台屏（启用时）改目标屏。"""
    from . import screen
    return screen.rewrite(launcher(cmd))


class Result:
    def __init__(self, code, out, err, timed_out=False):
        self.code, self.out, self.err, self.timed_out = code, out, err, timed_out


class ShizukuBridge:
    def __init__(self):
        from java import jclass
        self.shell = jclass("com.ahuamiao.adcleaner.ShizukuShell")

    def ready(self):
        return bool(self.shell.ready())

    def exec(self, cmd, stdin=None, timeout=None):
        """命令在 Java 后台线程里跑，这里轮询：等的时候不占解释器锁（停止、界面轮询、看门狗照常），超时自己掐。"""
        t = time.monotonic()
        job = self.shell.submit(prepare(cmd), stdin)
        deadline, delay, timed_out = t + (timeout or 600), 0.002, False
        while not job.isDone():
            if time.monotonic() > deadline:
                job.cancel()
                timed_out = True
                break
            time.sleep(delay)
            delay = min(delay * 2, 0.05)
        r = job.result(timed_out)
        slow(f"shell {cmd[:120]!r}", t, f"code={r.code} timedOut={timed_out}")
        return Result(r.code, bytes(r.out), bytes(r.err), timed_out)

    def daemon(self, name, cmd):
        return bool(self.shell.daemon(name, cmd))

    def stop_daemon(self, name):
        self.shell.stopDaemon(name)

    def server_port(self):
        return U2_PORT


class AdbBridge:
    """电脑调试用：同一组接口，底下是 `adb -s 序列号 shell`。"""

    def __init__(self, adb, serial):
        self.adb, self.serial = adb, serial
        self.daemons = {}
        self.port = None

    def ready(self):
        r = _run([self.adb, "-s", self.serial, "get-state"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "device"

    def exec(self, cmd, stdin=None, timeout=None):
        try:
            # 用 shell 不用 exec-out：shell v2 分开 stderr 并带回退出码，引擎要看退出码
            r = _run([self.adb, "-s", self.serial, "shell", prepare(cmd)],
                     input=stdin, capture_output=True, timeout=timeout or 600)
        except subprocess.TimeoutExpired:
            return Result(124, b"", b"", True)
        return Result(r.returncode, r.stdout, r.stderr)

    def daemon(self, name, cmd):
        p = self.daemons.get(name)
        if p is not None and p.poll() is None:
            return False
        self.daemons[name] = _popen([self.adb, "-s", self.serial, "shell", cmd],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def stop_daemon(self, name):
        p = self.daemons.pop(name, None)
        if p is not None:
            p.kill()

    def server_port(self):
        if self.port is None:
            out = _run([self.adb, "-s", self.serial, "forward", "tcp:0", f"tcp:{U2_PORT}"],
                       capture_output=True, text=True, timeout=10).stdout
            self.port = int(out.strip())
        return self.port


_bridge = None


def get():
    global _bridge
    if _bridge is None:
        adb = os.environ.get("AAC_BRIDGE_ADB")
        _bridge = AdbBridge(adb, os.environ["AAC_BRIDGE_SERIAL"]) if adb else ShizukuBridge()
    return _bridge
