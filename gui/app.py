#!/usr/bin/env python3
"""安卓去广告 · 桌面客户端（macOS / Windows）。

界面：gui/web/index.html（pywebview 窗口）
后台：tool/run.py、tool/fast.py、tool/chan_fast.py，以子进程运行，日志实时回传界面。
打包后没有独立的 Python，子进程用「本程序 --cli 脚本名 参数…」的方式启动。
"""
import hashlib, importlib, json, os, platform, re, runpy, subprocess, sys, threading, time, urllib.error, urllib.request, uuid, zipfile
from pathlib import Path

try:                                # 当包导入（测试）；直接跑脚本、打包时它是顶层模块
    from . import winpreflight
except ImportError:
    import winpreflight

APP_NAME = "安卓去广告"
VERSION = "0.3.0"
FROZEN = getattr(sys, "frozen", False)
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(BASE, "tool")
IS_WIN = platform.system() == "Windows"


def _tool(name):
    """tool/ 是命令行脚本目录，不在包里：真要用某个工具模块时才把它加进 sys.path。

    import 这个客户端本身不碰 sys.path、也不加载 tool/ 下的文件，测试用正常 import 拉起来。
    """
    if TOOL not in sys.path:
        sys.path.insert(0, TOOL)
    return importlib.import_module(name)


def data_dir():
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AndroidAdCleaner")
    if platform.system() == "Darwin":
        return os.path.expanduser("~/Library/Application Support/AndroidAdCleaner")
    return os.path.expanduser("~/.local/share/android-ad-cleaner")


class ClientData:
    """客户端数据的落点。构造只算路径，ensure() 才建目录。"""

    def __init__(self, root):
        self.root = os.fspath(root)

    @property
    def backups(self):
        return os.path.join(self.root, "backups")

    @property
    def logs(self):
        return os.path.join(self.root, "logs")

    @property
    def pause(self):
        return os.path.join(self.root, "pause")

    @property
    def install_id(self):
        return os.path.join(self.root, "install-id")

    @property
    def platform_tools(self):
        return os.path.join(self.root, "platform-tools")

    @property
    def adb_zip(self):
        return os.path.join(self.root, "platform-tools.zip")

    def ensure(self):
        os.makedirs(self.root, exist_ok=True)
        return self


# ---------- 命令行模式：打包后子进程走这里 ----------
def _fix_stdio():
    """Windows 窗口程序没有控制台：父进程用管道接输出时，把 1/2 号句柄包成 sys.stdout/stderr。"""
    import io
    for fd, name in ((1, "stdout"), (2, "stderr")):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, io.TextIOWrapper(os.fdopen(fd, "wb", buffering=0), encoding="utf-8",
                                                    errors="replace", line_buffering=True, write_through=True))
            except OSError:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    for st in (sys.stdout, sys.stderr):        # Windows 控制台默认 cp1252/GBK，中文和 ✗ ▶ 会报错；打包后 PYTHONIOENCODING 不生效
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cli_main():
    _fix_stdio()
    script, args = sys.argv[2], sys.argv[3:]
    sys.path.insert(0, TOOL)
    sys.argv = [os.path.join(TOOL, script)] + args
    try:
        runpy.run_path(os.path.join(TOOL, script), run_name="__main__")
    except Exception:
        # 保留完整原因；避免异常逸出 PyInstaller 后只剩「Failed to execute script app」。
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ---------- adb ----------
# adb 下载（#273：从 Google 下载失败）。固定版本先从官网、再从腾讯云镜像下，都核对 SHA-256；
# 校验值按 Google 官方清单 repository2-3.xml 的 SHA-1 核过（2026-10-29，两处文件一致）。都失败再从官网下最新版。
ADB_VERSION = "37.0.1"
ADB_PINNED = {
    "Windows": ("platform-tools_r37.0.1-win.zip", "45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99"),
    "Darwin": ("platform-tools_r37.0.1-darwin.zip", "ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d"),
    "Linux": ("platform-tools_r37.0.1-linux.zip", "d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1"),
}
ADB_MIRRORS = (("Google 官网", "https://dl.google.com/android/repository/"),
               ("腾讯云镜像", "https://mirrors.cloud.tencent.com/AndroidSDK/"))
ADB_LATEST = {
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "Windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}


def adb_ok(path):
    """只用 1.0.41 及以上的 adb。手机助手自带的 1.0.32 等旧版会让挂起、快应用等命令失败，
    和新版同时运行还会互相顶掉服务（#25 #75）。"""
    try:
        out = subprocess.run([path, "version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=8, creationflags=NOWIN).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    m = re.search(r"version 1\.0\.(\d+)", out)
    return bool(m) and int(m.group(1)) >= 41


def find_adb(platform_tools):
    exe = "adb.exe" if IS_WIN else "adb"
    last = (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
            "/opt/homebrew/bin/adb", "/usr/local/bin/adb")
    for c in _tool("adb_link").adb_candidates(first=(os.path.join(platform_tools, exe),), last=last):
        if adb_ok(c):
            return c
    return None


def client_api():
    """入口（窗口与截图脚本）共用的构造：数据目录建好，adb 按既定顺序找。"""
    data = ClientData(data_dir()).ensure()
    return Api(data.root, adb=find_adb(data.platform_tools))


def adb_present(adb, serial):
    """手机此刻是否连着（adb 状态为 device）；先给它 10 秒回来。"""
    if not adb:
        return False
    return _tool("adb_link").Connection(serial, adb=adb).alive(wait=10)


CHIME_GAP = 3       # 秒：几件事挤在一起时只响一次
_last_chime = [0.0]


def chime():
    """提示音（gui/web/chime.wav，两个柔和的音，不到 1 秒，由 gui/make_chime.py 生成）：
    执行结束、暂停生效、手机锁屏要解锁时各响一次。放不出来就算了，不影响执行。"""
    now = time.time()
    if os.environ.get("AAC_NO_SOUND") or now - _last_chime[0] < CHIME_GAP:
        return                          # AAC_NO_SOUND：回归测试不出声
    _last_chime[0] = now
    path = os.path.join(BASE, "gui", "web", "chime.wav")
    try:
        if IS_WIN:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        elif platform.system() == "Darwin":
            subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def child_env(adb, backups):
    e = dict(os.environ)
    # 事件开关只由本客户端在跑任务时打开。用户 shell 里碰巧导出了它也不能生效：
    # `_run()` 那些一次性命令会把输出直接解析（`status()` 取末行当 JSON）。
    e.pop("AAC_EVENTS", None)
    e.update({"ADB": adb or "", "ADBUTILS_ADB_PATH": adb or "", "AAC_BACKUPS": backups,
              "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "AAC_GUI": "1"})
    if adb:
        e["PATH"] = os.path.dirname(adb) + os.pathsep + e.get("PATH", "")
    return e


def cmd_for(script, *args):
    if FROZEN:
        cli = os.path.join(os.path.dirname(sys.executable), "aac-cli.exe")
        exe = cli if IS_WIN and os.path.exists(cli) else sys.executable     # Windows 用命令行版，输出不丢
        return [exe, "--cli", script, *args]
    return [sys.executable, "-u", os.path.join(TOOL, script), *args]


class Runner:
    """启动 tool/ 子进程。环境变量每次启动时现取：下载完 adb 之后不用再同步第二份状态。"""

    def __init__(self, env_for):
        self.env_for = env_for

    def run(self, script, *args, timeout=180):
        r = subprocess.run(cmd_for(script, *args), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=self.env_for(), timeout=timeout, creationflags=NOWIN)
        return r.stdout, r.stderr, r.returncode

    def spawn(self, script, *args, env_extra=None):
        env = dict(self.env_for(), **(env_extra or {}))
        return subprocess.Popen(cmd_for(script, *args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env=env,
                                creationflags=NOWIN, bufsize=1)


class Task:
    """一个步骤。uses_ui：这一步要连读屏，前一步因读屏被占用失败时跳过它。
    channels 非 None 表示这一步是关营销通知：运行前把勾选的渠道写进 channels.tsv，
    args 由 `_work()` 换成 `-s <序列号> off <清单>`。"""

    def __init__(self, title, script, args=(), uses_ui=False, channels=None):
        self.title, self.script, self.args = title, script, args
        self.uses_ui, self.channels = uses_ui, channels


class Job:
    """一次执行的状态（ADR-0010）。工作线程写，HTTP 线程经 snapshot() 读一致视图。"""

    def __init__(self, serial="", model="", total=0, t0=None):
        self.lock = threading.RLock()
        self.running = True
        self.lines = []
        self.idx = 0
        self.total = total
        self.title = ""
        self.results = []
        self.proc = None
        self.cancel = False
        self.t0 = time.time() if t0 is None else t0
        self.serial = serial
        self.model = model
        self.paused = False
        self.pause = False
        self.recovery = ""
        self.step_events = set()
        self.payloads = []

    def add_result(self, result):
        with self.lock:
            self.results.append(result)

    def request_stop(self):
        """用户点「停止」：置取消并杀掉正在跑的引擎进程。"""
        with self.lock:
            self.cancel = True
            proc = self.proc
        if proc:
            proc.terminate()

    def request_pause(self):
        with self.lock:
            self.pause = True

    def clear_pause(self):
        with self.lock:
            self.pause = False

    def snapshot(self, since=0):
        """某一时刻的一致只读视图。lines 只给 since 之后的新行，next 是下一次的偏移。"""
        with self.lock:
            lines = self.lines[since:]
            return {"running": self.running, "lines": lines, "next": since + len(lines),
                    "idx": self.idx, "total": self.total, "title": self.title,
                    "results": list(self.results), "sec": round(time.time() - self.t0),
                    "cancel": self.cancel, "recovery": self.recovery,
                    "pause": self.pause, "paused": self.paused}


def os_name():
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if IS_WIN:
        return f"Windows {platform.release()}（{platform.version()}）"
    return f"{platform.system()} {platform.release()}"


NOWIN = 0x08000000 if IS_WIN else 0     # Windows：子进程不弹黑色控制台窗口


# Windows 上插着、但 adb 看不到的手机：按 USB 厂商号认品牌，给对应的驱动 / 开关提示（#57 #58 #65 #118 等）。
USB_VENDORS = {"04E8": "三星", "12D1": "华为", "339B": "荣耀", "2717": "小米", "22D9": "OPPO / 一加 / realme",
               "2A70": "一加", "2D95": "vivo / iQOO", "18D1": "Google", "2A45": "魅族", "19D2": "中兴 / 努比亚",
               "22B8": "摩托罗拉", "0B05": "华硕", "17EF": "联想", "05C6": "高通方案"}
DRIVER_HINT = {
    "三星": "Windows 要先装三星官方的 Samsung Android USB Driver，装好后重新插线。",
    "华为": "开发者选项里同时打开「仅充电模式下允许 ADB 调试」。驱动可装华为手机助手获取，装好后退出手机助手再用本工具。"
            "已升级 HarmonyOS NEXT（5.0 及以上，原生鸿蒙）的机型不支持 adb。",
    "荣耀": "开发者选项里同时打开「仅充电模式下允许 ADB 调试」。驱动可装荣耀手机助手获取，装好后退出手机助手再用本工具。",
}


def usb_phones():
    """只读：Windows 设备管理器里的手机 USB 设备。返回 [(品牌, 设备名, 状态, 是否 ADB 接口)]；查不到返回空。"""
    if not IS_WIN:
        return []
    script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\\\VID_(" + "|".join(USB_VENDORS) + ")' } | "
              "ForEach-Object { $_.InstanceId + '|' + $_.FriendlyName + '|' + $_.Status + '|' + $_.Class }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=8, creationflags=NOWIN).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.splitlines():
        parts = (line.split("|") + ["", "", "", ""])[:4]
        m = re.match(r"USB\\VID_([0-9A-F]{4})", parts[0], re.I)
        if m:
            adb = bool(re.search(r"adb|android", parts[1] + " " + parts[3], re.I))
            found.append((USB_VENDORS.get(m.group(1).upper(), "安卓"), parts[1], parts[2], adb))
    return found


def usb_hint(found):
    """把设备管理器的结果说成一句人话；没有手机设备时返回空。"""
    if not found:
        return ""
    # 品牌只从带调试接口的设备里取：电脑上还插着别的东西时，列表第一台可能根本不是用户的手机（#357）。
    adb = [f for f in found if f[3]]
    picked = adb or found
    brands = list(dict.fromkeys(f[0] for f in picked))
    if len(brands) > 1:
        # 多台手机同时插着：不猜哪台是用户的，逐台说状态，让用户自己只留一台。
        lines = []
        for b in brands:
            items = [f for f in picked if f[0] == b and f[3]]
            if not items:
                lines.append(f"{b}（没有调试接口）")
            elif any(f[2].upper() != "OK" for f in items):
                lines.append(f"{b}（调试接口的驱动没有装好）")
            else:
                lines.append(f"{b}（调试接口在，但 adb 没连上）")
        return ("电脑识别到多台手机：" + "、".join(lines)
                + "。只留要处理的那一台插着，重新插线后再检测。")
    brand = brands[0]
    if adb and any(f[2].upper() != "OK" for f in adb):
        head = f"电脑识别到{brand}手机的调试接口，但驱动没有装好。"
    elif adb:
        head = f"电脑识别到{brand}手机的调试接口，但 adb 没连上：请退出手机助手类软件和模拟器后重新插线。"
    else:
        head = f"电脑识别到{brand}手机，但没有调试接口：手机上的「USB 调试」还没打开，或没点「允许 USB 调试」。"
    return head + DRIVER_HINT.get(brand, "")


def other_adb():
    """电脑上正在运行的其他 adb（手机助手、模拟器自带）。它们会和本工具抢连接（#126 #140 运行中掉线）。"""
    try:
        if IS_WIN:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-Process | Where-Object { $_.ProcessName -match 'adb' } | ForEach-Object { $_.Path }"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
                                 creationflags=NOWIN).stdout
        else:
            out = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    paths = {line.strip() for line in out.splitlines() if re.search(r"adb", os.path.basename(line.strip()), re.I)}
    return sorted(paths)


def win_clipboard(text):
    """直接写 Unicode 剪贴板。以前经 PowerShell 管道，中文 Windows 按 GBK 解码，粘贴出来是乱码（#33 #50 #128）。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    data = text.encode("utf-16-le") + b"\0\0"
    for _ in range(20):                       # 别的程序可能正占着剪贴板
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("剪贴板被占用")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))    # GMEM_MOVEABLE
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):           # CF_UNICODETEXT
            kernel32.GlobalFree(handle)
            raise OSError("写剪贴板失败")
    finally:
        user32.CloseClipboard()


# 错误日志上报：用户预览并确认后发送；说明见 docs/12-错误日志上报.md
REPORT_URL = "https://supabase.ahuamiao.com/functions/v1/aac-report"
REPORT_LIMIT = 3            # 每小时最多上报几次（服务器另有按 IP / 安装编号 / 全站的配额）
# 新版本提示：先查官网的版本文件（国内能访问），再查 GitHub。只取版本号，请求里不带手机、电脑信息。
LATEST_URLS = ("https://ahuamiao.com/sites/other/android-ad-cleaner-latest.json",
               "https://api.github.com/repos/rddmwmddr/android-ad-cleaner/releases/latest")
DOWNLOAD_PAGE = "https://ahuamiao.com/sites/other/android-ad-removal-intro.html"
# 没执行过任何步骤时只有手机型号，看不出问题（错误日志 10-28：6 份空报告）
EMPTY_REPORT = "还没有执行记录，这份报告只有手机型号，看不出问题。请先执行一次再上报；还没执行就遇到问题，请到 GitHub 反馈，写清楚卡在哪一步。"
PRIVATE = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<邮箱>"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "<手机号>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b(?!\()"), "<IP>"),   # 华为版本号「4.2.0.180(C00…)」不是 IP
    # 用户目录可能不在 C 盘（360「C 盘搬家」等把它挪到 E:\…\Users\名字），整段路径前缀一起换掉
    (re.compile(r"(?:[A-Za-z]:)?[^\s'\"<>|]*?[\\/](?:Users|home)[\\/][^/\\\s'\"<>]+", re.I), "<用户目录>"),
)


def scrub(text, serial=None):
    """序列号、用户目录、邮箱、手机号、IP 换成占位符；服务器收到后再做一遍。"""
    for private, replacement in ((serial, "<序列号>"), (os.path.expanduser("~"), "<用户目录>")):
        if private:
            text = text.replace(private, replacement).replace(private.replace("\\", "\\\\"), replacement)
    for pattern, replacement in PRIVATE:
        text = pattern.sub(replacement, text)
    return text


class Api:
    def __init__(self, data_dir, adb=None, runner=None):
        self.data = ClientData(data_dir)
        self.backups = _tool("backups").Backups(self.data.backups)
        self.adb = adb
        self.runner = runner or Runner(self._child_env)
        self.job = None
        self.lock = threading.Lock()
        self.dl = {"state": "idle", "pct": 0, "msg": ""}
        self.last_status = None
        self.last_error = None
        self.last_devices = ""
        self.report_times = []

    def _child_env(self):
        return child_env(self.adb, self.data.backups)

    # ----- 基础 -----
    def env(self):
        return {"adb": self.adb, "data": self.data.root, "version": VERSION, "os": platform.system(),
                "images": [f for f in sorted(os.listdir(os.path.join(BASE, "images"))) if f.startswith("dev-")]}

    def latest_version(self):
        """有新版时返回 {version, url}，没有或查不到返回 {}。旧版不会自动更新：0.2.6 发布后，
        旧版又报了 21 份新版已经修好的问题（错误日志 10-28）。"""
        current = version_key(VERSION)
        for url in LATEST_URLS:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": f"AndroidAdCleaner/{VERSION}",
                                                               "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=6) as response:
                    data = json.loads(response.read(65536).decode("utf-8"))
                latest = str(data.get("version") or data.get("tag_name") or "")
            except Exception:
                continue
            if not version_key(latest):
                continue
            return {"version": latest.lstrip("v"), "url": DOWNLOAD_PAGE} if version_key(latest) > current else {}
        return {}

    def _run(self, script, *args, timeout=180):
        return self.runner.run(script, *args, timeout=timeout)

    def _adb(self, *args, timeout=20):
        return _tool("adb_link").invoke(self.adb, *args, timeout=timeout)

    # ----- 下载 adb -----
    def download_adb(self):
        if self.dl["state"] == "running":
            return
        threading.Thread(target=self._download, daemon=True).start()

    def adb_sources(self):
        """[(来源名, 网址, sha256 或 None)]：固定版本两处，最后是官网最新版。"""
        name, digest = ADB_PINNED[platform.system()]
        return [(label, base + name, digest) for label, base in ADB_MIRRORS] + \
               [("Google 官网（最新版）", ADB_LATEST[platform.system()], None)]

    def _fetch(self, label, url, digest, zp):
        self.dl = {"state": "running", "pct": 0, "msg": f"正在从{label}下载 platform-tools……"}
        h = hashlib.sha256()
        request = urllib.request.Request(url, headers={"User-Agent": f"AndroidAdCleaner/{VERSION}"})
        with urllib.request.urlopen(request, timeout=20) as r, open(zp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0); got = 0
            while True:
                b = r.read(65536)
                if not b:
                    break
                f.write(b); h.update(b); got += len(b)
                if total:
                    self.dl["pct"] = int(got * 100 / total)
        if digest and h.hexdigest() != digest:
            raise ValueError("文件校验不对，可能下载不完整或被改动")

    def _download(self):
        self.data.ensure()
        zp = self.data.adb_zip
        errors = []
        try:
            for label, url, digest in self.adb_sources():
                try:
                    self._fetch(label, url, digest, zp)
                    break
                except Exception as e:
                    errors.append(f"{label}：{e}")
            else:
                raise RuntimeError("；".join(errors))
            with zipfile.ZipFile(zp) as z:
                z.extractall(self.data.root)
            os.remove(zp)
            adb = os.path.join(self.data.platform_tools, "adb.exe" if IS_WIN else "adb")
            if not IS_WIN:
                os.chmod(adb, 0o755)
            self.adb = adb
            self.dl = {"state": "done", "pct": 100, "msg": "adb 已就绪"}
        except Exception as e:
            self.dl = {"state": "error", "pct": 0, "msg": f"下载失败：{e}"}
            try:
                os.remove(zp)
            except OSError:
                pass

    def download_state(self):
        return self.dl

    # ----- 设备 -----
    def devices(self):
        if not self.adb:
            return {"error": "no-adb", "list": []}
        try:
            out = self._adb("devices", "-l", timeout=10)
        except Exception as e:
            return {"error": str(e), "list": []}
        res = []
        self.last_devices = out
        for line in out.splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split()
            ser, st = parts[0], parts[1]
            if ser.startswith("emulator-"):
                continue
            d = {"serial": ser, "state": st, "model": "", "name": "", "brand": ""}
            if st == "device":
                try:
                    p = self._adb("-s", ser, "shell",
                                  "getprop ro.product.brand; getprop ro.product.model; "
                                  "getprop ro.vendor.oplus.market.name; getprop ro.product.marketname", timeout=8).splitlines()
                    p += [""] * 4
                    d.update(brand=p[0].strip(), model=p[1].strip(), name=(p[2] or p[3]).strip())
                except Exception:
                    pass
            res.append(d)
        return {"error": None, "list": res}

    def usb_hint(self):
        """没有手机出现时调用：只读设备管理器，给出驱动 / 开关提示。"""
        return usb_hint(usb_phones())

    def status(self, serial):
        out, err, rc = self._run("run.py", "-s", serial, "status-json", timeout=90)
        try:
            st = json.loads(out.strip().splitlines()[-1])
            self.last_status = st
            return st
        except Exception:
            return {"error": (err or out)[-600:]}

    def chan_scan(self, serial):
        try:
            out, err, rc = self._run("chan_fast.py", "-s", serial, "scan", timeout=120)
        except (subprocess.TimeoutExpired, OSError) as e:
            return self._remember_error("通知扫描", serial, str(e))
        if rc:
            return self._remember_error("通知扫描", serial, err or out or "通知扫描失败，请检查连接与权限")
        policy = _tool("channel_policy")
        rows = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                pkg, cid, name = parts[0], parts[1], parts[2]
                app = parts[3].strip() if len(parts) > 3 else ""   # 手机上显示的应用名，读不到为空
                judgement = policy.classify(name, cid, package=pkg, app=app)
                if judgement.protected:
                    continue  # 旧扫描结果也不能经「全选」把功能通知勾回去
                rows.append({"pkg": pkg, "id": cid, "name": name, "app": app,
                             "checked": not judgement.default_unchecked})
        return rows

    def _remember_error(self, operation, serial, detail):
        # 本地保留完整异常，分享前替换序列号和用户目录；不再截掉异常开头。
        for private, replacement in ((serial, "<序列号>"), (os.path.expanduser("~"), "<用户目录>")):
            if private:
                detail = detail.replace(private, replacement).replace(private.replace("\\", "\\\\"), replacement)
        self.last_error = {"operation": operation, "detail": detail}
        folder = self.data.logs
        try:
            os.makedirs(folder, exist_ok=True)
            Path(folder, "last-error.txt").write_text(f"客户端 {VERSION} · {operation}\n{detail}\n", encoding="utf-8")
        except OSError:
            pass  # 保存日志失败也要让界面收到原始问题
        lines = detail.splitlines()
        causes = [line.strip() for line in lines if re.search(r"(?:Exception|Error|Caused by:|原始异常：|启动失败)", line)
                  and not line.lstrip().startswith("at ")]
        summary = "\n".join(causes[:4]) or (detail if len(detail) <= 600 else detail[:600] + "…")
        help_ui = _tool("troubleshooting")
        recovery = help_ui.UI_RECOVERY if help_ui.is_ui_connection_error(detail) else ""
        if recovery:
            summary = recovery + "\n\n" + summary
        if len(summary) > 1000:
            summary = summary[:1000] + "…（完整原因见诊断）"
        result = {"error": summary, "detail": detail}
        if recovery:
            result["recovery"] = recovery
        return result

    def ui_check(self, serial):
        with self.lock:
            if self.job and self.job.running:
                return {"error": "任务正在执行，请结束后再检查读屏连接"}
            try:
                # 直接启动读屏进程，超时时终止它；不经额外父进程留下仍在连接的子任务。
                out, err, rc = self._run("fast.py", "-s", serial, "check", timeout=75)
            except (subprocess.TimeoutExpired, OSError) as e:
                return self._remember_error("读屏检查", serial, str(e))
            if rc:
                return self._remember_error("读屏检查", serial, err or out)
            return {"ok": True, "message": out.strip()}

    # ----- 任务 -----
    def start(self, serial, plan):
        """plan: {backup, steps:[段名]|None, channels:[{pkg,id,name}], quickapp:bool, ads:[包名], model}"""
        with self.lock:
            if self.job and self.job.running:
                return {"error": "已有任务在运行"}
            tasks = []
            if plan.get("backup", True):
                tasks.append(Task("存改动前的快照", "run.py", ["-s", serial, "backup"]))
            if plan.get("steps"):
                tasks.append(Task("关闭各 App 里的广告开关", "run.py",
                                  ["-s", serial, "recipe", *plan["steps"], *(["--ref"] if plan.get("ref") else [])],
                                  uses_ui=True))
            if plan.get("channels"):
                tasks.append(Task("关闭营销通知", "chan_fast.py", uses_ui=True, channels=plan["channels"]))
            if plan.get("quickapp"):
                tasks.append(Task("关闭快应用", "run.py", ["-s", serial, "quickapp", "off"]))
            if plan.get("ads"):
                tasks.append(Task("挂起广告组件", "run.py", ["-s", serial, "suspend", *plan["ads"]]))
            tasks.append(Task("收尾", "run.py", ["-s", serial, "finish"]))
            self.job = Job(serial=serial, model=plan.get("model", ""), total=len(tasks))
        threading.Thread(target=self._work, args=(tasks,), daemon=True).start()
        return {"ok": True, "total": len(tasks)}

    def _log(self, s):
        """记一行输出。事件行只改状态、不进日志，返回 None；人话返回存下来的文本。
        载荷行（页面骨架）单独收着，上报时拼在末尾：不进界面日志与步骤摘要，也不会在
        「最近失败的完整诊断」里重复一遍。"""
        s = s.rstrip("\n")
        events = _tool("events")
        if events.is_event(s):
            self._event(events.parse(s))
            return None
        if events.is_payload(s):
            with self.job.lock:
                self.job.payloads.append(events.strip_payload(s))
            return None
        with self.job.lock:
            self.job.lines.append(s)
        return s

    def _event(self, kind):
        """引擎事件（ADR-0004）：暂停 / 继续 / 锁屏改提示状态，其余记进本步骤的事件集合；
        都不进日志、不上报。"""
        if kind is None:                # 前缀对上但解析不出来：当没有这个事件
            return
        if kind == "paused":
            with self.job.lock:
                self.job.paused = True
            chime()                     # 可以拿手机了
        elif kind == "resumed":
            with self.job.lock:
                self.job.paused = False
        elif kind == "locked":
            chime()                     # 要机主来解锁
        else:
            with self.job.lock:
                self.job.step_events.add(kind)

    def _work(self, tasks):
        j = self.job
        ui_busy = False
        self.resume()                   # 上次没清掉的暂停标记不能带进这次
        for i, task in enumerate(tasks):
            with j.lock:
                j.step_events = set()
            if j.pause and not j.cancel:
                # 步骤之间的暂停；步骤里面的暂停由引擎在段与段、渠道与渠道之间处理
                with j.lock:
                    j.paused = True
                chime()                 # 可以拿手机了：与引擎侧暂停点的提醒一致
                self._log("⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」")
                while j.pause and not j.cancel:
                    time.sleep(0.5)
                with j.lock:
                    j.paused = False
                if not j.cancel:
                    self._log("▶ 继续执行")
            if j.cancel and task.title != "收尾":
                continue                # 停止后仍跑收尾：改回插电常亮（以前停止会让手机一直亮着）
            with j.lock:
                j.idx, j.title = i + 1, task.title
            self._log(f"\n▶ {task.title}")
            if ui_busy and task.uses_ui:
                reason = "读屏服务仍被占用，跳过本步骤；请先解决读屏连接再重试。"
                self._log(reason)
                j.add_result({"title": task.title, "rc": 3, "skipped": True, "sec": 0, "tail": [reason]})
                continue
            line_start = len(j.lines)
            t = time.time()
            script, args = task.script, list(task.args)
            if task.channels is not None:
                d = self.backups.latest(j.model) or self.backups.gui(j.model)
                fn = os.path.join(d, "channels.tsv")
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("# 包名\t渠道id\t渠道名\t应用名（客户端勾选）\n")
                    for c in task.channels:
                        name = re.sub(r"[\t\r\n]+", " ", str(c.get("app") or "")).strip()
                        f.write(f"{c['pkg']}\t{c['id']}\t{c['name']}\t{name}\n")
                args = ["-s", j.serial, "off", fn]
            try:
                p = self.runner.spawn(script, *args, env_extra={"AAC_PAUSE_FILE": self.data.pause,
                                                                "AAC_EVENTS": "1"})
                with j.lock:
                    j.proc = p
                tail = []
                for line in p.stdout:
                    shown = self._log(line)     # 事件行返回 None：不进步骤摘要（前端会展示 tail）
                    if shown is not None:
                        tail.append(shown.strip()); tail = tail[-80:]
                rc = p.wait()
            except Exception as e:
                rc, tail = -1, [str(e)]
                self._log(f"✗ {e}")
            if rc and j.cancel and task.title != "收尾":
                # 用户点了停止：不是出错，不记诊断、不提示上报（错误日志 10-28：4 份是停止后上报的）
                j.add_result({"title": task.title, "rc": rc, "stopped": True, "sec": round(time.time() - t), "tail": tail})
                continue
            j.add_result({"title": task.title, "rc": rc, "sec": round(time.time() - t), "tail": tail})
            if rc:
                detail = "\n".join(j.lines[line_start:])
                ui_busy = ui_busy or "ui_busy" in j.step_events
                if "link_lost" in j.step_events and not adb_present(self.adb, j.serial):
                    # 手机已断开：后面每一步都会报同一段排查说明（错误日志 10-27），不再执行
                    self._remember_error(task.title, j.serial, detail)
                    reason = "手机和电脑已断开，这一步没有执行。重新连接手机后点「重试」。"
                    for later in tasks[i + 1:]:
                        self._log(f"\n▶ {later.title}\n{reason}")
                        j.add_result({"title": later.title, "rc": 3, "skipped": True, "sec": 0, "tail": [reason]})
                    break
                error = self._remember_error(task.title, j.serial, detail)
                if error.get("recovery"):
                    with j.lock:
                        j.recovery = error["recovery"]
        self.resume()
        if not j.cancel:
            chime()                     # 执行结束（成功或有步骤没成功都响，提醒回来看结果）
        with j.lock:
            j.running = False
            j.proc = None
        self._log(f"\n执行结束，用时 {round(time.time() - j.t0)} 秒" if not j.cancel else "\n已停止")

    def poll(self, since=0):
        j = self.job
        if not j:
            return {"running": False, "lines": [], "next": 0}
        snap = j.snapshot(since)
        if snap["running"]:
            snap["results"] = []        # 执行中不显示结果（前端契约）；诊断与上报仍读快照里的全量
        return snap

    def stop(self):
        j = self.job
        if j and j.running:
            j.request_stop()
            self.resume()
        return True

    def pause(self):
        """执行中需要操作手机时用：引擎做完手头这一项（一个渠道、机型脚本的一段、一个步骤）就停下等待。"""
        j = self.job
        if not j or not j.running or j.cancel:
            return False
        self.data.ensure()
        Path(self.data.pause).write_text("", encoding="utf-8")
        j.request_pause()
        return True

    def resume(self):
        if self.job:
            self.job.clear_pause()
        try:
            os.remove(self.data.pause)
        except OSError:
            pass
        return True

    # ----- 收尾 / 还原 -----
    def dev_off(self, serial):
        out, err, rc = self._run("run.py", "-s", serial, "dev-off", "--yes", timeout=30)
        return out + err

    def restore(self, serial, what):
        if what == "suspend":
            out, err, rc = self._run("run.py", "-s", serial, "unsuspend")
        elif what == "quickapp":
            out, err, rc = self._run("run.py", "-s", serial, "quickapp", "on")
        elif what == "channels":
            st = self.status(serial)
            d = self.backups.latest(st.get("info", {}).get("model", ""))
            fn = d and os.path.join(d, "channels.tsv")
            if not fn or not os.path.exists(fn):
                return "没有找到上次关掉的营销通知清单"
            out, err, rc = self._run("chan_fast.py", "-s", serial, "on", fn, timeout=600)
        else:
            return "未知的还原项"
        return out + err

    # ----- 反馈 -----
    def diagnostics(self):
        """反馈附带的诊断信息。序列号替换成 <序列号>；不含应用列表和通知内容。"""
        lines = [f"- 客户端：{APP_NAME} {VERSION}（{'打包版' if FROZEN else '源码'}）",
                 f"- 电脑：{os_name()}（{platform.machine()}）"]
        try:
            v = self._adb("version", timeout=8).splitlines()[0] if self.adb else "没有 adb"
        except Exception as e:
            v = f"adb 出错：{e}"
        lines.append(f"- adb：{v}")
        st, serial = self.last_status, (self.job.serial if self.job else None)
        rows = [l.split()[1] for l in self.last_devices.splitlines()[1:] if len(l.split()) > 1]
        lines.append(f"- adb 设备：{len(rows)} 台" + (f"（{'、'.join(rows)}）" if rows else ""))
        others = [o for o in other_adb() if not self.adb or os.path.normcase(o) != os.path.normcase(self.adb)]
        if others:
            lines.append(f"- 其他正在运行的 adb：{'；'.join(others)}")
        if not rows:
            hint = usb_hint(usb_phones())
            if hint:
                lines.append(f"- USB：{hint}")
        if st and "info" in st:
            i = st["info"]
            nm = i.get("name") or i.get("model")
            if not nm.upper().startswith((i.get("brand") or "").upper()):
                nm = f"{i.get('brand')} {nm}"
            lines += [f"- 手机：{nm}（{i.get('model')}）",
                      f"- 系统：{i.get('os') or i.get('build')}（{i.get('build')}），Android {i.get('android')}",
                      f"- 机型脚本：{st.get('recipe') or '无'}"
                      + (f"（录制版本 {st.get('recipe_build')}，{'一致' if st.get('recipe_ok') else '不一致'}）" if st.get('recipe') else ""),
                      f"- 折叠屏展开：{'是' if st.get('fold_open') else '否'}；锁屏：{'是' if st.get('locked') else '否'}"
                      + ("；电脑点击被拒（未开 USB 调试安全设置）" if st.get("input_blocked") else "")]
        else:
            lines.append("- 手机：还没检测")
        j = self.job
        if j:
            snap = j.snapshot(0)
            lines.append("\n**执行结果**\n")
            for r in snap["results"]:
                state = "跳过（读屏服务被占用）" if r.get("skipped") else ("成功" if r["rc"] == 0 else "失败（退出码 %s）" % r["rc"])
                lines.append(f"- {r['title']}：{state}，{r['sec']} 秒")
            tail = [l for l in snap["lines"] if l.strip()][-60:]
            log = "\n".join(tail)
            if serial:
                log = log.replace(serial, "<序列号>")
            lines.append("\n<details><summary>最近的日志</summary>\n\n```text\n" + log + "\n```\n</details>")
        if self.last_error:
            detail = self.last_error["detail"].replace("```", "~~~")
            lines.append(f"\n<details><summary>最近失败的完整诊断：{self.last_error['operation']}</summary>\n\n```text\n{detail}\n```\n</details>")
        report = "\n".join(lines)
        home = os.path.expanduser("~")
        return report.replace(home, "<用户目录>").replace(home.replace("\\", "\\\\"), "<用户目录>")

    # ----- 错误日志上报 -----
    def report_payload(self):
        """要上报的全部内容。界面原样展示给用户，确认后发送同一份。"""
        st, j = self.last_status or {}, self.job
        info = st.get("info") or {}
        serial = j.serial if j else None
        snap = j.snapshot(0) if j else {"lines": [], "results": []}
        log = "\n".join(l for l in snap["lines"] if l.strip())
        if self.last_error:
            log += f"\n\n[最近失败：{self.last_error['operation']}]\n{self.last_error['detail']}"
        payloads = [x for x in (j.payloads if j else []) if x.strip()]
        if payloads:
            # 放在末尾：日志只留最后 2 万字，骨架跟着失败日志一起留下，不会被早先的成功步骤挤掉
            log += "\n\n[页面骨架]\n" + "\n".join(payloads)
        steps = [{"title": scrub(r["title"])[:40], "sec": int(r.get("sec") or 0),
                  "result": "跳过" if r.get("skipped") else "已停止" if r.get("stopped") else ("成功" if r["rc"] == 0 else "失败")}
                 for r in snap["results"]][:12]
        return {
            "client_version": VERSION,
            "platform": f"{os_name()}（{platform.machine()}）"[:80],
            "phone_brand": scrub(info.get("brand") or "")[:40],
            "phone_model": scrub(info.get("name") or info.get("model") or "")[:80],
            "phone_system": scrub(info.get("os") or info.get("build") or "")[:160],
            "android": (info.get("android") or "")[:16],
            "steps": steps,
            "log": scrub(log, serial)[-20000:],      # 只留末尾；开头是早先成功的步骤
        }

    def _install_id(self):
        """第一次上报时随机生成，只用来限频；不取任何设备或电脑标识。"""
        path = Path(self.data.install_id)
        try:
            value = path.read_text(encoding="utf-8").strip()
            if uuid.UUID(value).version == 4:
                return value
        except (OSError, ValueError):
            pass
        value = str(uuid.uuid4())
        self.data.ensure()
        path.write_text(value, encoding="utf-8")
        return value

    def send_report(self, payload):
        now = time.time()
        self.report_times = [t for t in self.report_times if now - t < 3600]
        if len(self.report_times) >= REPORT_LIMIT:
            return {"error": f"一小时内最多上报 {REPORT_LIMIT} 次，请稍后再试"}
        if not isinstance(payload, dict):
            return {"error": "上报内容格式不对"}
        if not payload.get("steps") and not str(payload.get("log") or "").strip():
            return {"error": EMPTY_REPORT}
        body = dict(payload, install_id=self._install_id())
        request = urllib.request.Request(
            REPORT_URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": f"AndroidAdCleaner/{VERSION}"})
        try:
            # 云函数闲置后第一次调用要加载依赖，给足时间
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return {"error": "上报太频繁，请一小时后再试"}
            try:
                message = json.loads(e.read().decode("utf-8")).get("message") or ""
            except (ValueError, OSError):
                message = ""
            return {"error": f"服务器拒绝了这次上报（{e.code}{'：' + message if message else ''}）"}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {"error": f"连不上上报服务器：{getattr(e, 'reason', e)}"}
        self.report_times.append(now)
        if result.get("status") == "duplicate":
            return {"ok": True, "duplicate": True}
        if result.get("status") != "ok":
            return {"error": "服务器没有确认收到"}
        return {"ok": True, "id": result.get("id", "")}

    def copy_text(self, text):
        try:
            if IS_WIN:
                win_clipboard(text)
            else:
                subprocess.run(["pbcopy"], input=text, text=True, encoding="utf-8", timeout=10)
            return True
        except Exception:
            return False

    def open_path(self, which):
        path = {"data": self.data.root, "backups": self.data.backups}.get(which, self.data.root)
        os.makedirs(path, exist_ok=True)
        if IS_WIN:
            os.startfile(path)
        else:
            subprocess.Popen(["open", path])

    def open_url(self, url):
        """网址里的中文先转成 %XX：macOS 经 AppleScript、Windows 经 shell 打开中文网址会出错。"""
        import webbrowser, urllib.parse
        webbrowser.open(urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~"))


def version_key(text):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)$", (text or "").strip())
    return tuple(map(int, m.groups())) if m else ()


def smoke_gui(window, result):
    """验证本地页面、图片、JS→Python 桥和模拟失败提示；不连接或修改手机。"""
    try:
        if not window.events.loaded.wait(30):
            raise RuntimeError("页面加载超时")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            ready = window.evaluate_js("typeof api !== 'undefined' && !!api && !!document.querySelector('#tutbox')")
            if ready:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("JS API 桥初始化超时")
        window.evaluate_js("window.__smokeEnv = null; api.env().then(x => window.__smokeEnv = x.version)")
        while time.monotonic() < deadline:
            report = window.evaluate_js("({url: location.href, version: window.__smokeEnv, images: [...document.querySelectorAll('#tutbox img')].every(i => i.complete && i.naturalWidth > 0)})")
            if report.get("version") == VERSION and report.get("images") and report.get("url", "").startswith("file://"):
                from webview import http
                if http.global_server is not None:
                    raise RuntimeError("不应启动本地 HTTP 服务")
                simulated = {"sec": 0, "cancel": False, "recovery": _tool("troubleshooting").UI_RECOVERY,
                             "results": [{"rc": 1, "title": "读屏检查（模拟）", "sec": 0,
                                          "tail": ["UIAUTOMATION_BUSY: simulated"]}]}
                window.evaluate_js("showDone(" + json.dumps(simulated, ensure_ascii=False) + ")")
                hint_ok = window.evaluate_js("""(() => {
                    const box = document.querySelector('#ui-recovery');
                    return !!box && box.offsetHeight > 0 && box.textContent.includes('GKD') &&
                        box.textContent.includes('自动记账') && box.textContent.includes('检查读屏连接') &&
                        box.textContent.includes('复制完整诊断');
                })()""")
                if not hint_ok:
                    raise RuntimeError("读屏冲突排查提示未显示")
                result["ok"] = True
                print("GUI smoke: file 页面、教程图片、JS API 桥、读屏失败排查提示通过；未启动 HTTP 服务", flush=True)
                return
            time.sleep(0.1)
        raise RuntimeError("教程图片或 JS API 调用未通过")
    except Exception as e:
        print(f"GUI smoke failed: {e}", file=sys.stderr, flush=True)
    finally:
        window.destroy()


def startup_advice(state, blocked, error):
    """窗口起不来时给用户看的文案，以及要不要跳微软官网（#228）。

    以前一律说「缺少 WebView2」，portable 包解压后文件带 MOTW 的现场被指到装不上的东西上。
    """
    if state == "missing":
        return ("这台电脑缺少微软 Edge WebView2 运行时，界面没法显示。\n\n"
                "点「确定」打开微软官网，下载安装「Evergreen Bootstrapper」后重新打开本程序。\n\n"
                f"（{error}）", True)
    if blocked:
        return ("这台电脑可能已经装了 WebView2，但程序文件被 Windows 标记成「来自网络」，"
                "加载时被拦住了。\n\n"
                "办法一：对下载的 zip 压缩包点右键 →「属性」→ 勾选「解除锁定」→ 确定，重新解压后再打开。\n"
                "办法二：zip 已经删了，就在解压出来的文件夹里按住 Shift 点右键 →"
                "「在此处打开 PowerShell 窗口」，粘贴下面这行后回车：\n"
                "Get-ChildItem . -Recurse -File | Unblock-File\n\n"
                f"（{error}）", False)
    if state == "unknown":
        return ("程序启动失败。这台电脑的 WebView2 状态没能确认（多半是注册表读取受限），"
                "所以下面的原因不一定是缺运行时。\n\n"
                "如果这是 Windows 10 且从没装过，先装一个再试：\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
                "装过还这样，把括号里的原文发到 "
                "https://github.com/rddmwmddr/android-ad-cleaner/issues/new 。\n\n"
                f"（{error}）", False)
    return ("程序启动失败。WebView2 运行时在，程序文件也没有被 Windows 锁定，"
            "是按别的原因退出的。\n\n"
            "把下面括号里的原文发到 "
            "https://github.com/rddmwmddr/android-ad-cleaner/issues/new ，我们按它定位。\n\n"
            f"（{error}）", False)


def startup_failed(error, preflight=None, notify=None, open_url=None):
    """按归因弹出提示（#228）。三个协作者可注入，接线本身在非 Windows 上也能验。"""
    import ctypes, webbrowser
    preflight = preflight or winpreflight
    notify = notify or (lambda text: ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x40))
    text, open_site = startup_advice(preflight.webview2_state(),
                                     preflight.blocked_files(BASE), error)
    notify(text)
    if open_site:
        (open_url or webbrowser.open)("https://developer.microsoft.com/microsoft-edge/webview2/")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--cli":
        cli_main(); return
    import webview
    api = client_api()
    smoke = "--smoke-gui" in sys.argv
    if smoke:
        _fix_stdio()
        api.adb = None                     # 不枚举真机，不自动下载 adb
    result = {"ok": False}
    # 明确 file://：裸文件路径会启动 Bottle HTTP 服务，部分 Windows 环境回环连接超时（#18）。
    url = Path(BASE, "gui", "web", "index.html").resolve().as_uri()
    w = webview.create_window(APP_NAME, url, js_api=api, hidden=smoke,
                              width=1080, height=780, min_size=(900, 640))
    options = {"debug": "--debug" in sys.argv, "http_server": False}
    if smoke:
        options.update(func=smoke_gui, args=(w, result))
    if IS_WIN:
        try:
            webview.start(gui="edgechromium", **options)
        except Exception as e:      # 启动失败：缺 WebView2、程序文件被 MOTW 拦、其他（#228）
            if smoke:
                print(f"startup: {winpreflight.describe(BASE)}", flush=True)
                raise
            startup_failed(e)
    else:
        webview.start(**options)
    if smoke:
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
