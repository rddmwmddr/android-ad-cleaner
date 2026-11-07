"""以 shell 身份执行命令的通道。

手机上走 Kotlin 的 `Shell` 门面：已授权的 Shizuku 用 `ShizukuShell`，否则用内置无线调试的 `AdbShell`（#622）。
在电脑上调试这一层时设 AAC_BRIDGE_ADB / AAC_BRIDGE_SERIAL，改走真 adb，替换层的其余部分不用改就能对着模拟器跑。
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
        self.shell = jclass("com.ahuamiao.adcleaner.Shell")    # Shizuku 或内置无线调试（#622）

    def ready(self):
        return bool(self.shell.connected())

    def ensure(self):
        """去试着连上（最多 4 秒）：wait-for-device 用这个，其余只查现状。"""
        return bool(self.shell.ensure())

    def exec(self, cmd, stdin=None, timeout=None):
        """命令在 Java 后台线程里跑，这里轮询：等的时候不占解释器锁（停止、界面轮询、看门狗照常），超时自己掐。"""
        from . import screen
        t = time.monotonic()
        target = prepare(cmd)
        moved = target != launcher(cmd)          # 改写过：这条发往后台屏
        s = screen.active
        if moved and s is not None and s.lost:
            return Result(1, b"", screen.LOST.encode())
        job = self.shell.submit(target, stdin)
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
        if moved and r.code and not timed_out and s is not None and not s.lost and screen.dead():
            s.lost = True                        # 屏没了：之后发往它的命令直接报错，不再发给一块不存在的屏
            return Result(r.code, bytes(r.out), bytes(r.err) + ("\n" + screen.LOST).encode(), False)
        return Result(r.code, bytes(r.out), bytes(r.err), timed_out)

    def daemon(self, name, cmd):
        return bool(self.shell.daemon(name, cmd))

    def stop_daemon(self, name):
        self.shell.stopDaemon(name)

    def _await(self, job, timeout):
        """等一条内部请求（读屏、问尺寸）。轮询而不是在 Java 方法里等：Chaquopy 调 Java 期间不放解释器锁，
        一条卡住的请求会把停止键、界面轮询与看门狗一起冻住。"""
        deadline, delay = time.monotonic() + timeout, 0.002
        while not job.isDone():
            if time.monotonic() > deadline:
                job.cancel()
                return Result(-1, b"", f"读屏请求超时（{timeout:.0f} 秒）".encode(), True)
            time.sleep(delay)
            delay = min(delay * 2, 0.05)
        r = job.result(False)
        return Result(r.code, bytes(r.out), bytes(r.err))

    def dump(self, display):
        """读屏：命令服务经 UiAutomation 读第 display 块屏的窗口，返回与 uiautomator 同格式的 XML。"""
        return self._await(self.shell.dumpJob(int(display)), 30)

    def size(self, display):
        return self._await(self.shell.sizeJob(int(display)), 10)

    def set_clipboard(self, text):
        """写字走剪贴板：引擎发完粘贴键后由系统粘进输入框。"""
        from java import jclass
        jclass("com.ahuamiao.adcleaner.Native").setClipboard(text)


class AdbBridge:
    """电脑调试用：同一组接口，底下是 `adb -s 序列号 shell`。"""

    def __init__(self, adb, serial):
        self.adb, self.serial = adb, serial
        self.daemons = {}

    def ready(self):
        r = _run([self.adb, "-s", self.serial, "get-state"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "device"

    def ensure(self):
        return self.ready()

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

    def dump(self, display):
        """电脑调试：系统自带的 uiautomator dump 只读主屏（后台屏只在手机上用）。"""
        r = self.exec("uiautomator dump /data/local/tmp/aac-dump.xml >/dev/null "
                      "&& cat /data/local/tmp/aac-dump.xml", None, 30)
        return Result(r.code, r.out, r.err)

    def size(self, display):
        r = self.exec("wm size", None, 10)
        found = re.findall(r"(\d+)x(\d+)", r.out.decode("utf-8", "replace"))
        if not found:
            return Result(1, b"", b"wm size returned nothing")
        w, h = found[-1]
        return Result(0, f"{w} {h}".encode(), b"")

    def set_clipboard(self, text):
        """电脑调试这条路上没有 App 进程可写剪贴板：打字用例只做记录。"""
        print(f"[clipboard] {text}", file=sys.__stderr__)


_bridge = None


def get():
    global _bridge
    if _bridge is None:
        adb = os.environ.get("AAC_BRIDGE_ADB")
        _bridge = AdbBridge(adb, os.environ["AAC_BRIDGE_SERIAL"]) if adb else ShizukuBridge()
    return _bridge
