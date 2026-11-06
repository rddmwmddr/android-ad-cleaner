"""把引擎里的 adb 命令换成本机 shell 执行。

引擎与客户端都是 `subprocess.run([adb, "-s", 序列号, "shell", 命令])` 这一种写法（adb_link、troubleshooting、
run.py）。这里接管 subprocess 的几个函数：第一个参数是本模块的 adb 占位文件时按 adb 的语义自己回答，
是 Python 脚本时交给 inproc 在本进程里跑，其余照旧。
"""
import os
import shlex
import subprocess
import time

from . import bridge, inproc

SERIAL = "local"            # 本机只有一台手机：序列号固定，不读真实序列号（它会进备份路径与日志）
VERSION_TEXT = "Android Debug Bridge version 1.0.41\nVersion 37.0.1-shizuku\n"
NOT_READY = b"error: no devices/emulators found\n"

ADB_PATH = ""               # install() 时定下：一个真实存在的空文件，adb_link 的候选检查要求路径存在


def _split(argv):
    """去掉 -s 序列号这类全局选项，返回 (子命令, 其余参数)。"""
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        i += 2 if argv[i] in ("-s", "-t", "-H", "-P", "-L") else 1
    return (argv[i], list(argv[i + 1:])) if i < len(argv) else ("", [])


def answer(argv, stdin=None, timeout=None):
    """按 adb 命令行的语义执行，返回 (退出码, stdout 字节, stderr 字节)。
    Shizuku 那边抛错时先记进 logcat：客户端有几处调用（devices 取机型）吞掉异常，不记就无从查起。"""
    try:
        return _answer(argv, stdin, timeout)
    except subprocess.TimeoutExpired:
        raise
    except Exception:
        import traceback
        traceback.print_exc(file=inproc._fallback[1])
        raise


def _answer(argv, stdin, timeout):
    b = bridge.get()
    cmd, rest = _split([str(a) for a in argv])
    if cmd == "version":
        return 0, VERSION_TEXT.encode(), b""
    if cmd in ("start-server", "kill-server"):
        return 0, b"", b""
    if cmd == "devices":
        rows = f"{SERIAL}\tdevice\n" if b.ready() else ""
        return 0, ("List of devices attached\n" + rows + "\n").encode(), b""
    if cmd == "get-state":
        return (0, b"device\n", b"") if b.ready() else (1, b"", NOT_READY)
    if cmd == "wait-for-device":
        deadline = time.monotonic() + (timeout or 30)
        while not b.ready():
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(argv, timeout)
            time.sleep(0.5)
        return 0, b"", b""
    if not b.ready():
        return 1, b"", NOT_READY
    if cmd in ("shell", "exec-out"):
        r = b.exec(" ".join(rest), stdin, timeout)
        if r.timed_out:
            raise subprocess.TimeoutExpired(argv, timeout)
        return r.code, r.out, r.err
    if cmd == "push" and len(rest) >= 2:
        local, remote = rest[-2], rest[-1]
        if remote.endswith("/"):
            remote += os.path.basename(local)
        with open(local, "rb") as f:
            data = f.read()
        r = b.exec(f"cat > {shlex.quote(remote)}", data, timeout)
        if r.code:
            return r.code, b"", r.err or b"adb: error: failed to copy\n"
        return 0, f"{local}: 1 file pushed, 0 skipped.\n".encode(), b""
    if cmd == "pull" and len(rest) >= 2:
        r = b.exec(f"cat {shlex.quote(rest[-2])}", None, timeout)
        if r.code:
            return r.code, b"", r.err
        with open(rest[-1], "wb") as f:
            f.write(r.out)
        return 0, f"{rest[-2]}: 1 file pulled.\n".encode(), b""
    return 1, b"", f"adb: 手机版不支持 {cmd}\n".encode()


def _decode(data, kw):
    if kw.get("text") or kw.get("universal_newlines") or kw.get("encoding") or kw.get("errors"):
        return data.decode(kw.get("encoding") or "utf-8", kw.get("errors") or "replace")
    return data


def _input_bytes(kw):
    data = kw.get("input")
    if isinstance(data, str):
        data = data.encode(kw.get("encoding") or "utf-8")
    return data


def _is_adb(argv):
    return bool(ADB_PATH) and isinstance(argv, (list, tuple)) and argv and str(argv[0]) == ADB_PATH


def _is_script(argv):
    """引擎调另一个脚本的两种写法（run.py 的 script_cmd）：[python, 脚本.py, …] 与 [python, --cli, 脚本名, …]。"""
    return (isinstance(argv, (list, tuple)) and len(argv) >= 2 and str(argv[0]) == inproc.EXECUTABLE
            and (argv[1] == "--cli" or str(argv[1]).endswith(".py")))


def _completed(argv, rc, out, err, kw):
    capture = kw.get("capture_output") or kw.get("stdout") == subprocess.PIPE
    stdout = _decode(out, kw) if capture else None
    stderr = _decode(err, kw) if (kw.get("capture_output") or kw.get("stderr") == subprocess.PIPE) else None
    if kw.get("stderr") == subprocess.STDOUT and stdout is not None:
        stdout = stdout + _decode(err, kw)
    if kw.get("check") and rc:
        raise subprocess.CalledProcessError(rc, argv, stdout, stderr)
    return subprocess.CompletedProcess(argv, rc, stdout, stderr)


_orig = {}


def _run(argv, *a, **kw):
    if _is_adb(argv):
        rc, out, err = answer(argv[1:], _input_bytes(kw), kw.get("timeout"))
        return _completed(argv, rc, out, err, kw)
    if _is_script(argv):
        rc, out, err = inproc.call(argv[1:], capture=bool(kw.get("capture_output") or kw.get("stdout")))
        return _completed(argv, rc, out.encode(), err.encode(), kw)
    return _orig["run"](argv, *a, **kw)


def _call(argv, *a, **kw):
    if _is_adb(argv) or _is_script(argv):
        return _run(argv, **{k: v for k, v in kw.items() if k in ("timeout", "input")}).returncode
    return _orig["call"](argv, *a, **kw)


def _check_output(argv, *a, **kw):
    if _is_adb(argv) or _is_script(argv):
        kw = dict(kw, capture_output=True, check=True)
        kw.pop("stdout", None)
        return _run(argv, **kw).stdout
    return _orig["check_output"](argv, *a, **kw)


def install(path):
    """建 adb 占位文件并接管 subprocess。重复调用无副作用。"""
    global ADB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        open(path, "w").close()
    ADB_PATH = path
    if not _orig:
        for name, fn in (("run", _run), ("call", _call), ("check_output", _check_output)):
            _orig[name] = getattr(subprocess, name)
            setattr(subprocess, name, fn)
