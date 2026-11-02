"""adb 连接中断：等手机回来重试一次；仍不在就停下并说明原因，不把空结果当成功。

社区反馈 #126 #140 #147 #158：执行到一半报 device not found，后面的步骤读到空结果仍显示「成功」。
"""
import os
import re
import shutil
import subprocess

import events

# adb 客户端自己的错误（远端命令的 stderr 不会带这些前缀）。
# Windows 上程序名有时显示成「adb.」（错误日志 10-27）。
CLIENT_GONE = re.compile(r"(?mi)^(?:adb[\w.]*|error): .*(?:not found|offline|no devices|unauthorized|authorizing"
                         r"|cannot connect|closed|protocol fault|connection reset)")
# uiautomator2 / adbutils 直接连 adb 服务，错误没有前缀。整条消息只有「closed」是 adb 服务关掉了连接（错误日志 10-28）。
# 外部 adb server 退出后 u2 报的是连接层错误（requests 的 Connection refused / Max retries exceeded，#293）。
LIB_GONE = re.compile(r"device '[^']*' not found|device offline|no devices/emulators found|device still authorizing"
                      r"|\Aclosed\Z|connection refused|max retries exceeded|newconnectionerror|remotedisconnected"
                      r"|cannot connect to|couldn't connect to|failed to establish", re.I)

HINT = ("手机和电脑的 adb 连接断开了，本步骤没有完成。请逐项排查后重试：\n"
        "· 退出电脑上的手机助手类软件（各品牌手机助手、应用宝、360 手机助手、豌豆荚、爱思助手、刷机工具）和安卓模拟器。"
        "它们自带另一个版本的 adb，会和本工具抢连接\n"
        "· 换原装或可传数据的线，直接插电脑接口，不经过扩展坞或 USB Hub\n"
        "· 看手机有没有弹出 USB 用途选择或「允许 USB 调试」授权框\n"
        "· 用无线调试时，手机息屏或换网络后端口会变，要重新连接")

# 一轮内已经确认断线：后面的段只报这一句，不重复上面整段排查说明，也不再逐段重试（#293）。
REPEAT = "手机和电脑的 adb 连接已断开，本段跳过；原因和排查办法见第一次报错"
NO_ADB = "找不到 adb。安装方法见 docs/01-准备工作.md"

NOWIN = 0x08000000 if os.name == "nt" else 0


def invoke(adb, *args, timeout=20):
    """跑一条不绑串号的命令（devices / version），返回 stdout。手机连接本身走 Connection。"""
    return _adb_run(adb, args, timeout).stdout


def adb_candidates(first=(), last=()):
    """按优先级排好的候选 adb（去重、只留存在的）。`first` 是客户端要紧挨着排在最前的几份
    （用户手动指定的、客户端自己下载的），`last` 是客户端独有的兜底位置（Windows 默认安装目录、
    homebrew 等），排在共用候选之后。"""
    seen, found = set(), []
    for c in (*first, os.environ.get("ADB"), os.environ.get("ADBUTILS_ADB_PATH"), shutil.which("adb"),
              os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
              os.path.expanduser("~/platform-tools/adb"),
              os.path.expanduser("~/android-tools/platform-tools/adb"), *last):
        if c and c not in seen and os.path.exists(c):
            seen.add(c)
            found.append(c)
    return found


def adb_path(first=()):
    found = adb_candidates(first)
    return found[0] if found else None


def client_gone(stderr):
    return bool(CLIENT_GONE.search(stderr or ""))


def lib_gone(message):
    return bool(LIB_GONE.search(message or ""))


def wait_for(serial, adb=None, timeout=15):
    """短暂掉线（另一个 adb 服务重启、接口抖动）时等手机回来；不重启 adb 服务。"""
    adb = adb or adb_path()
    if not adb:
        return False
    try:
        result = subprocess.run([adb, "-s", serial, "wait-for-device"], capture_output=True,
                                timeout=timeout, creationflags=NOWIN)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class DeviceLost(RuntimeError):
    """已确认断线；构造即发 link_lost（ADR-0004）。谁把它转成退出码都不影响事件。"""

    def __init__(self, message):
        super().__init__(message)
        events.emit("link_lost")


def present(serial, adb=None):
    """手机此刻是否在 adb 设备列表里（状态为 device）。"""
    adb = adb or adb_path()
    if not adb:
        return False
    try:
        result = subprocess.run([adb, "-s", serial, "get-state"], capture_output=True, text=True,
                                timeout=8, creationflags=NOWIN)
        return result.stdout.strip() == "device"
    except (OSError, subprocess.TimeoutExpired):
        return False


def detached(serial, adb=None):
    """adb 客户端自己回答「这台设备不在」。只认有据可查的断连：
    找不到 adb、get-state 超时或执行失败都算状态未知，返回 False，不能据此说手机断开了（#293 审查）。"""
    adb = adb or adb_path()
    if not adb:
        return False
    try:
        result = subprocess.run([adb, "-s", serial, "get-state"], capture_output=True, text=True,
                                timeout=8, creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode != 0 and client_gone(result.stderr or result.stdout or "")


# 锁屏判断。只认字段名，不整行找 true（HyperOS 3 同一行有别的 =true 字段，#115）。
# ColorOS 16（realme RMX3700 / 16.0.5.1300 / Android 16，2026-11-02 实测）：解锁态输出里有
# `isKeyguardShowing=false` 和 `mDreamingLockscreen=false`；锁屏且息屏时是 `mDreamingLockscreen=true`
# 加焦点 `NotificationShade`。两种状态 keyguard_showing() 都判对。ColorOS 17 是否有该字段未测。
# 管道末端不能提前退出（head -n / grep -m）：dumpsys 会收到 SIGPIPE 并报 Broken pipe，
# adbutils 因此判「shell output invalid」整段中断（#205 HyperOS 3 / Android 16）。
# sed 会读完整个输入再输出前几行，所以能截断行数而不提前退出。
KEYGUARD_CMD = ("dumpsys window | grep -E 'mCurrentFocus|isKeyguardShowing|mDreamingLockscreen|mIsShowing='"
                " | sed -n '1,12p'")
SHADE_WINDOWS = {"NotificationShade", "StatusBar", "Keyguard", "KeyguardBouncer", "Bouncer"}


def focus_window(out):
    m = re.search(r"mCurrentFocus=.*? u0 ([^\s}]+)", out or "") or re.search(r"mCurrentFocus=Window\{\S+ ([^\s}]+)\}", out or "")
    return m.group(1) if m else ""


LOCK_FIELD = re.compile(r"(?:isKeyguardShowing|mDreamingLockscreen)[=:]\s*true")
UNLOCK_FIELD = re.compile(r"isKeyguardShowing[=:]\s*false|\bmIsShowing=false")


def keyguard_showing(out):
    """KEYGUARD_CMD 的输出 → 是否锁屏。焦点在通知栏窗口时：有锁屏字段按字段判断；字段都没有，按锁屏处理。"""
    out = out or ""
    if LOCK_FIELD.search(out):
        return True
    if focus_window(out) not in SHADE_WINDOWS:
        return False
    return bool(re.search(r"\bmIsShowing=true", out)) or not UNLOCK_FIELD.search(out)


def lost(detail=""):
    detail = (detail or "").strip()
    return DeviceLost(HINT + (f"\n原始错误：{detail[-200:]}" if detail else ""))


class ShellResult:
    """`adb` 命令行的 shell 结果。`.output` 是读屏库那边的读法，两种调用点都不用改。"""
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

    output = property(lambda self: self.stdout)


def _adb_run(adb, argv, timeout):
    result = subprocess.run([adb, *argv], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, creationflags=NOWIN)
    return ShellResult(result.stdout, result.stderr, result.returncode)


class LinkBroken(Exception):
    """传输层看到「这次失败像是连接断了」。重试还是收场由 Connection 决定，适配器不给结论。"""

    def __init__(self, error):
        super().__init__(str(error))
        self.error = error if isinstance(error, BaseException) else RuntimeError(str(error))


class Connection:
    """连着一台手机：带 -s 执行、认断线、等它回来一次；确认断开后只报 REPEAT。

    transport 是适配器：`adb` 命令行这一条本模块自带，读屏库的 shell 由调用方注入，
    也可以换成任意可编排的假实现。两个开关都只为保住原有入口的差别：
    `lost_on_retry=False` —— 手机回来了、第二轮仍断时抛原异常，不判成断开（读屏库那条路径）；
    `sticky=False` —— 一次掉线不写进连接状态，后面的调用重新试（一个 reader 跑一整批时用）。
    """

    def __init__(self, serial, adb=None, transport=None, lost_on_retry=True, sticky=True):
        self.serial, self.adb, self.lost = serial, adb, False
        self.lost_on_retry, self.sticky = lost_on_retry, sticky
        self._transport = transport

    def _executable(self):
        adb = self.adb or adb_path()
        if not adb:
            raise RuntimeError(NO_ADB)
        return adb

    def _run(self, argv, timeout):
        return _adb_run(self._executable(), argv, timeout)

    def _send(self, command, timeout):
        if self._transport is not None:
            return self._transport(command, timeout=timeout)
        result = self._run(["-s", self.serial, "shell", command], timeout)
        if result.returncode and client_gone(result.stderr):
            raise LinkBroken(result.stderr)
        return result

    def shell(self, command, timeout=None):
        self.check_alive()
        for attempt in (0, 1):
            try:
                return self._send(command, timeout)
            except LinkBroken as broken:
                if attempt and not self.lost_on_retry:
                    raise broken.error
                if attempt or not wait_for(self.serial, self.adb):
                    self.mark_lost()
                    raise lost(str(broken.error)) from broken.error

    def push(self, local, remote, timeout=30):
        """传文件只有 `adb` 命令行这一条路，读屏库不过手。"""
        return self._run(["-s", self.serial, "push", local, remote], timeout)

    def alive(self, wait=0):
        """手机此刻连着吗。wait 是等它回来的秒数：等超时就直接算不在，不再追一次状态查询。"""
        adb = self.adb or adb_path()
        if not adb:
            return False
        if wait:
            try:
                _adb_run(adb, ["-s", self.serial, "wait-for-device"], wait)
            except (OSError, subprocess.TimeoutExpired):
                return False
        return present(self.serial, adb)

    def lost_reason(self):
        """本轮已经确认断线时该报的那一句；还没断线返回 None。"""
        return REPEAT if self.lost else None

    def check_alive(self):
        reason = self.lost_reason()
        if reason:
            raise DeviceLost(reason)

    def mark_lost(self):
        self.lost = self.sticky


def lost_from(error, serial, adb=None):
    """读屏库的异常（HTTPError、AdbShellError 等，不是 RuntimeError）说设备不在、手机也确实不在列表里
    → 返回 DeviceLost，由调用方抛出；否则返回 None。以前这类异常一路带着堆栈打到界面上（错误日志 10-28）。"""
    seen, e = set(), error
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, DeviceLost):
            return e
        if lib_gone(str(e)) and serial and not present(serial, adb):
            return lost(f"{type(error).__name__}: {error}")
        e = e.__cause__ or e.__context__
    return None
