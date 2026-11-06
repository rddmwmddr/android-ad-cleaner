"""在本进程里跑 tool/ 的脚本，代替桌面版的子进程。

手机上没有可单独启动的 Python。桌面版一步一个子进程（干净的模块状态、自己的 stdout、sys.exit 当退出码），
这里逐条还原：
- 同一时刻只跑一个顶层脚本（可重入锁；脚本里再调脚本在同一线程里嵌套）；
- 顶层脚本开跑前清掉 tool/ 下已加载的模块，效果等同新进程；
- stdout / stderr 按线程分流（引擎不起线程），别的线程照旧写到原来的 stdout；
- 环境变量在脚本运行期间换成调用方给的那一份，结束后换回；
- SystemExit 的 code 就是退出码，未捕获的异常打印堆栈后记 1；
- 停止：向脚本线程投递 KeyboardInterrupt（下一条 Python 字节码生效，阻塞中的命令自带超时）。
"""
import ctypes
import io
import os
import queue
import runpy
import sys
import threading
import traceback

EXECUTABLE = sys.executable or "python"     # 引擎拼 [sys.executable, 脚本, …]，adb.py 按它认出脚本调用
TOOL = ""                                    # setup() 时定下

_lock = threading.RLock()
_sinks = {}                                  # 线程 id → [(out, err)]（嵌套捕获时压栈）
_fallback = (sys.stdout, sys.stderr)         # setup() 时换成当时的输出（Chaquopy 接到 logcat 的那一对）
after_run = []                               # 每个顶层脚本结束后调用（u2 用它停掉读屏服务）


class _Router(io.TextIOBase):
    def __init__(self, index):
        self.index = index

    def _target(self):
        stack = _sinks.get(threading.get_ident())
        return stack[-1][self.index] if stack else _fallback[self.index]

    def write(self, s):
        target = self._target()
        if target is None:
            return len(s)
        return target.write(s)

    def flush(self):
        target = self._target()
        if target is not None and hasattr(target, "flush"):
            target.flush()

    def writable(self):
        return True

    @property
    def encoding(self):
        return "utf-8"


def setup(tool_dir):
    global TOOL
    TOOL = os.path.abspath(tool_dir)
    if TOOL not in sys.path:
        sys.path.insert(0, TOOL)
    global _fallback
    if not isinstance(sys.stdout, _Router):
        _fallback = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = _Router(0), _Router(1)


def _purge():
    prefix = TOOL + os.sep
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None) or ""
        if f.startswith(prefix):
            del sys.modules[name]


def _script_path(arg):
    return arg if os.path.isabs(arg) else os.path.join(TOOL, arg)


def _exec(argv):
    """在当前线程跑一个脚本，返回退出码。argv[0] 是脚本路径（或 --cli 脚本名）。"""
    if argv and argv[0] == "--cli":
        argv = argv[1:]
    path = _script_path(argv[0])
    saved_argv = sys.argv
    sys.argv = [path, *argv[1:]]
    try:
        runpy.run_path(path, run_name="__main__")
        return 0
    except SystemExit as e:
        if e.code is None:
            return 0
        if isinstance(e.code, int):
            return e.code
        print(e.code, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已停止", file=sys.stderr)
        return -15
    except BaseException:
        traceback.print_exc()
        return 1
    finally:
        sys.argv = saved_argv


def _push(out, err):
    _sinks.setdefault(threading.get_ident(), []).append((out, err))


def _pop():
    stack = _sinks.get(threading.get_ident())
    if stack:
        stack.pop()
    if not stack:
        _sinks.pop(threading.get_ident(), None)


def call(argv, capture=False):
    """脚本里再调脚本（run.py 的 py() / scan）：同一线程嵌套，输出照旧或单独收集。
    返回 (退出码, stdout, stderr)；不捕获时后两项为空串。"""
    with _lock:
        if not capture:
            return _exec(list(argv)), "", ""
        out, err = io.StringIO(), io.StringIO()
        _push(out, err)
        try:
            rc = _exec(list(argv))
        finally:
            _pop()
        return rc, out.getvalue(), err.getvalue()


def _watchdog(ident, name, done):
    """脚本跑了 60 秒还没完：每 60 秒把它卡在哪一行写进 logcat（只进系统日志，不进界面和上报）。"""
    while not done.wait(60):
        frame = sys._current_frames().get(ident)
        if frame is not None:
            print(f"[watchdog] {name} 仍在运行：\n" + "".join(traceback.format_stack(frame)[-12:]),
                  file=_fallback[1], flush=True)


def top(argv, env, out, err):
    """顶层脚本：清模块、换环境变量、跑完换回。out / err 是可写对象。"""
    done = threading.Event()
    threading.Thread(target=_watchdog, args=(threading.get_ident(), " ".join(map(str, argv[:4])), done),
                     daemon=True).start()
    try:
        return _top(argv, env, out, err)
    finally:
        done.set()


def _top(argv, env, out, err):
    with _lock:
        _purge()
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        _push(out, err)
        try:
            return _exec(list(argv))
        finally:
            _pop()
            for fn in after_run:
                try:
                    fn()
                except Exception:
                    traceback.print_exc(file=_fallback[1])
            os.environ.clear()
            os.environ.update(saved)


class _LineSink:
    """spawn 的 stdout：写进来的文本按行放进队列，供 `for line in proc.stdout` 读。"""

    def __init__(self, q):
        self.q, self.buf = q, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.q.put(line + "\n")
        return len(s)

    def flush(self):
        pass

    def close(self):
        if self.buf:
            self.q.put(self.buf)
            self.buf = ""


class Proc:
    """subprocess.Popen 的替身：Dispatcher 只用 stdout 迭代、wait()、terminate()。"""
    _END = object()

    def __init__(self, argv, env):
        self.q = queue.Queue()
        self.returncode = None
        sink = _LineSink(self.q)

        def work():
            try:
                self.returncode = top(argv, env, sink, sink)
            finally:
                sink.close()
                self.q.put(self._END)

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self.stdout = iter(self._lines())

    def _lines(self):
        while True:
            line = self.q.get()
            if line is self._END:
                return
            yield line

    def wait(self, timeout=None):
        self.thread.join(timeout)
        return self.returncode

    def poll(self):
        return None if self.thread.is_alive() else self.returncode

    def terminate(self):
        if self.thread.is_alive():
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(self.thread.ident),
                                                       ctypes.py_object(KeyboardInterrupt))

    kill = terminate


class Runner:
    """gui/app.py 的 Runner 接口（Api(runner=…) 注入）：run 收集输出，spawn 返回 Proc。"""

    def __init__(self, env_for):
        self.env_for = env_for

    def run(self, script, *args, timeout=180):
        out, err = io.StringIO(), io.StringIO()
        rc = top([script, *args], self.env_for(), out, err)
        return out.getvalue(), err.getvalue(), rc

    def spawn(self, script, *args, env_extra=None):
        return Proc([script, *args], dict(self.env_for(), **(env_extra or {})))
