#!/usr/bin/env python3
"""肉呆去广告 · 桌面客户端（macOS / Windows）。

界面：gui/web/index.html（pywebview 窗口）
后台：tool/run.py、tool/fast.py、tool/chan_fast.py，以子进程运行，日志实时回传界面。
打包后没有独立的 Python，子进程用「本程序 --cli 脚本名 参数…」的方式启动。
"""
import json, os, platform, re, runpy, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path

try:                                # 当包导入（测试）；直接跑脚本、打包时它是顶层模块
    from . import winpreflight, updates, update_install, harmony_bridge, toolpath, startup
    # adb 那一域的实现都搬进了 gui/adb.py（#1385）。显式 re-export：`app.<名字>` 仍可直取，
    # 本模块自己的调用也走这几个名字（多处桩打在 app 上，比如 Dispatcher 用的 adb_present）。
    from .adb import (AdbDownloader, adb_ok, adb_exe,  # noqa: F401 - 显式 re-export：tests 按 app.adb_exe 取用
                      find_adb, adb_from_input, adb_source, adb_present)
    from .reporter import Reporter
    from .reporter import scrub  # noqa: F401 - 显式 re-export：tests 按 `app.scrub` 取用脱敏口径
except ImportError:
    import winpreflight, updates, update_install, harmony_bridge, toolpath, startup
    from adb import (AdbDownloader, adb_ok, adb_exe,  # noqa: F401 - 同上；打包件里 gui/ 在 sys.path 上
                     find_adb, adb_from_input, adb_source, adb_present)
    from reporter import Reporter
    from reporter import scrub  # noqa: F401 - 同上；打包件里 gui/ 在 sys.path 上

# 启动建议与写剪贴板的实现在 gui/startup.py；这几个名字按 `app.<名字>` 取用的地方（tests/、
# Api.copy_text）照旧，`startup_failed` 另有一个转发壳（弹窗标题要用本模块的 APP_NAME）。
version_key = startup.version_key
startup_advice = startup.startup_advice
_attribution = startup._attribution
win_clipboard = startup.win_clipboard
COPIED_NOTE = startup.COPIED_NOTE
MANUAL_COPY_NOTE = startup.MANUAL_COPY_NOTE


APP_NAME = "肉呆去广告"
VERSION = "0.4.5"
FROZEN = getattr(sys, "frozen", False)
IS_WIN = platform.system() == "Windows"

# 手机版在 import 本模块之前就 configure 过了，这里只给桌面入口的默认值
if not toolpath.BASE:
    toolpath.configure(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def __getattr__(name):
    """BASE / TOOL 的落地在 gui/toolpath.py；这里只转发，别在别处再算一份。"""
    if name in ("BASE", "TOOL"):
        return getattr(toolpath, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _tool(name):
    """tool/ 是命令行脚本目录，不在包里：真要用某个工具模块时才把它加进 sys.path（只走 toolpath）。

    import 这个客户端本身不碰 sys.path、也不加载 tool/ 下的文件，测试用正常 import 拉起来。
    """
    return toolpath.tool(name)


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
    def captures(self):
        """失败现场（#1126）：引擎按任务与段名在里面建子目录，不自动清理。"""
        return os.path.join(self.root, "captures")

    @property
    def updates(self):
        return os.path.join(self.root, "updates")

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

    @property
    def settings(self):
        return os.path.join(self.root, "settings.json")

    def setting(self, key, default=None):
        """settings.json 里的一项。文件不在、读不动或被改坏都按「没设置过」处理。"""
        try:
            with open(self.settings, encoding="utf-8") as f:
                return json.load(f).get(key, default)
        except (OSError, ValueError, AttributeError):
            return default

    def put_setting(self, key, value):
        """写一项设置；value 为 None 表示删掉这一项。先写临时文件再替换，读的时候不会看到半截。"""
        try:
            with open(self.settings, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        if not data:                      # 一项设置都不剩就别留个空文件：「没设置过」就是文件不存在
            try:
                os.remove(self.settings)
            except OSError:
                pass
            return
        self.ensure()
        tmp = self.settings + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.settings)

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
    # Windows 控制台默认 cp1252/GBK，中文和 ✗ ▶ 会报错；打包后 PYTHONIOENCODING 不生效
    _tool("stdio").use_utf8_console()


def cli_main():
    sys.path.insert(0, toolpath.TOOL)
    _fix_stdio()
    script, args = sys.argv[2], sys.argv[3:]
    sys.argv = [os.path.join(toolpath.TOOL, script)] + args
    try:
        runpy.run_path(os.path.join(toolpath.TOOL, script), run_name="__main__")
    except Exception:
        # 保留完整原因；避免异常逸出 PyInstaller 后只剩「Failed to execute script launch」。
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ---------- adb ----------
# adb 下载（#273：从 Google 下载失败）。固定版本先从官网、再从腾讯云镜像下，都核对 SHA-256；
# 校验值按 Google 官方清单 repository2-3.xml 的 SHA-1 核过（2026-10-29，两处文件一致）。都失败再从官网下最新版。
# 发现与下载的实现都在 gui/adb.py（#1385）；这几张表留在本模块当单一来源，构造 `AdbDownloader` 时传进去。
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
ADB_VERSION_HINT = "跑不出 Android Debug Bridge 的版本号，或者版本太旧（需要 1.0.41 及以上）"


def client_api():
    """入口（窗口与截图脚本）共用的构造：数据目录建好，adb 按既定顺序找，手填的那份排第一。"""
    data = ClientData(data_dir()).ensure()
    return Api(data.root, adb=find_adb(data.platform_tools, manual=data.setting("adb")))


CHIME_GAP = 3       # 秒：几件事挤在一起时只响一次
_last_chime = [0.0]


def play_sound(path):
    """放一个 wav：Windows 用 winsound，macOS 用 afplay。放不出来就算了，不影响执行。
    返回 mac 上起的播放进程（Windows 走 winsound，返回 None），调用方可以不管。"""
    if IS_WIN:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return None
    if platform.system() == "Darwin":
        return subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


def chime():
    """提示音（gui/web/chime.wav，两个柔和的音，不到 1 秒，由 gui/make_chime.py 生成）：
    执行结束、暂停生效、手机锁屏要解锁时各响一次。放不出来就算了，不影响执行。"""
    now = time.time()
    if os.environ.get("AAC_NO_SOUND") or now - _last_chime[0] < CHIME_GAP:
        return                          # AAC_NO_SOUND：回归测试不出声
    _last_chime[0] = now
    path = os.path.join(toolpath.BASE, "gui", "web", "chime.wav")
    try:
        play_sound(path)
    except Exception:
        pass


def child_env(adb, backups, captures):
    e = dict(os.environ)
    # 事件开关只由本客户端在跑任务时打开。用户 shell 里碰巧导出了它也不能生效：
    # `_run()` 那些一次性命令会把输出直接解析（`status()` 取末行当 JSON）。
    e.pop("AAC_EVENTS", None)
    # 宿主标记同理：只认客户端自己给的 ENGINE_HOST，不从用户 shell 继承（#747）
    e.pop("AAC_HOST", None)
    if ENGINE_HOST:
        e["AAC_HOST"] = ENGINE_HOST
    e.update({"ADB": adb or "", "ADBUTILS_ADB_PATH": adb or "", "AAC_BACKUPS": backups,
              "AAC_CAPTURES": captures,
              "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "AAC_GUI": "1"})
    if adb:
        e["PATH"] = os.path.dirname(adb) + os.pathsep + e.get("PATH", "")
    return e


def cmd_for(script, *args):
    if FROZEN:
        cli = os.path.join(os.path.dirname(sys.executable), "aac-cli.exe")
        exe = cli if IS_WIN and os.path.exists(cli) else sys.executable     # Windows 用命令行版，输出不丢
        return [exe, "--cli", script, *args]
    return [sys.executable, "-u", os.path.join(toolpath.TOOL, script), *args]


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


# 计划侧（#1386）：这 9 个名字住 `gui/tasks.py`，这里只留显式 re-export，`tests/` 与手机版照旧按
# `app.<名字>` 取用。身份词表在 `tool/plan.py` 的 `StepKind`。
try:
    from .tasks import (UNCHECKED, Task, not_run, not_run_result, plan_tasks,  # noqa: F401 - 显式 re-export
                        retry_plan, retryable, runs_after_stop, step_result)
except ImportError:
    from tasks import (UNCHECKED, Task, not_run, not_run_result, plan_tasks,  # noqa: F401 - 显式 re-export
                       retry_plan, retryable, runs_after_stop, step_result)


# 执行编排（#1383）：`Dispatcher` / `Job` 住 `gui/dispatcher.py`，这里只留显式 re-export；
# 宿主相关的三个钩子（铃声、断线措辞、adb 存活探测）在 `Api.__init__` 里按调用时取值传入。
try:
    from .dispatcher import Dispatcher, Job  # noqa: F401 - 显式 re-export：tests 按 `app.Job` 取用
except ImportError:
    from dispatcher import Dispatcher, Job  # noqa: F401 - 同上；打包件里 gui/ 在 sys.path 上


def os_name():
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if IS_WIN:
        return f"Windows {platform.release()}（{platform.version()}）"
    return f"{platform.system()} {platform.release()}"


NOWIN = 0x08000000 if IS_WIN else 0     # Windows：子进程不弹黑色控制台窗口


# 诊断文本（措辞、排版、脱敏）与 USB 的解析都在 tool/diagnostics.py（#1376）。这四个名字留在
# 本模块是因为 tests/ 直接按 `app.<名字>` 取用，`Api.usb_hint()` 也走这里；跑本机命令的两个外壳
# （usb_phones / other_adb）同理留在这里——那边不碰 subprocess、没有平台分支，才进得了 mypy 严格档。
def usb_hw_id(instance_id):
    return _tool("diagnostics").usb_hw_id(instance_id)


def usb_parse(out):
    return _tool("diagnostics").usb_parse(out)


def usb_facts(found, limit=5):
    return _tool("diagnostics").usb_facts(found, limit)


def usb_hint(found):
    return _tool("diagnostics").usb_hint(found)


def usb_phones():
    """只读：Windows 设备管理器里按 USB 厂商号命中的设备（手机也可能混着同厂外设）。
    返回 [(品牌, 设备名, 状态, 是否 ADB 接口, 硬件 ID, 登记的 GUID 元组或 None)]；查不到返回空。"""
    if not IS_WIN:
        return []
    diag = _tool("diagnostics")
    script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\\\VID_(" + "|".join(diag.USB_VENDORS) + ")' } | "
              "ForEach-Object { $k = 'HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\' + $_.InstanceId + '\\Device Parameters'; "
              "$g = '" + diag.USB_GUID_UNREADABLE + "'; if (Test-Path $k -ErrorAction SilentlyContinue) { "
              "try { $p = Get-ItemProperty -Path $k -ErrorAction Stop; "
              "$g = (@($p.DeviceInterfaceGUID, $p.DeviceInterfaceGUIDs) | Where-Object { $_ } | Select-Object -Unique) -join ',' } "
              "catch { $g = '" + diag.USB_GUID_UNREADABLE + "' } }; "
              "$_.InstanceId + '|' + $_.FriendlyName + '|' + $_.Status + '|' + $_.Class + '|' + $g }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=8, creationflags=NOWIN).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return diag.usb_parse(out)


def other_adb():
    """电脑上正在运行的其他 adb（手机助手、模拟器自带）。它们会和本工具抢连接（#126 #140 运行中掉线）。"""
    try:
        if IS_WIN:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-Process | Where-Object { $_.ProcessName -match 'adb' } | ForEach-Object { $_.Path }"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
                                 creationflags=NOWIN).stdout
        else:
            out = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    paths = {line.strip() for line in out.splitlines() if re.search(r"adb", os.path.basename(line.strip()), re.I)}
    return sorted(paths)


# 错误日志上报：用户预览并确认后发送；说明见 docs/12-错误日志上报.md
REPORT_URL = "https://supabase.ahuamiao.com/functions/v1/aac-report"
REPORT_LIMIT = 3            # 每小时最多上报几次（服务器另有按 IP / 安装编号 / 全站的配额）
# 新版本提示：先查官网的版本文件（国内能访问），再查 GitHub。只取版本号，请求里不带手机、电脑信息。
LATEST_URLS = ("https://ahuamiao.com/sites/other/android-ad-cleaner-latest.json",
               "https://api.github.com/repos/rddmwmddr/android-ad-cleaner/releases/latest")
DOWNLOAD_PAGE = "https://ahuamiao.com/sites/other/android-ad-removal-intro.html"
# 断线后跳过后面各步时写给用户的话；手机版没有电脑，启动时换成自己的说法（aac_android.main.boot，#729）
LINK_LOST = "手机和电脑已断开，这一步没有执行。重新连接手机后点「重试」。"
# 诊断里「点击被拒」那一栏：手机版会整段复制与上报，不能写「电脑」（aac_android.main.boot，#747）
TAP_REFUSED = "；电脑点击被拒（未开 USB 调试安全设置）"
# 传给引擎子进程的宿主标记，手机版由 boot() 设成 "phone"；引擎按它取词（tool/host.py，#747）
ENGINE_HOST = ""
# 没执行过任何步骤时只有手机型号，看不出问题（错误日志 10-28：6 份空报告）
EMPTY_REPORT = "还没有执行记录，这份报告只有手机型号，看不出问题。请先执行一次再上报；还没执行就遇到问题，请到 GitHub 反馈，写清楚卡在哪一步。"


def skip_reason(result):
    """跳过结果记下的那行说明，压成报告里列表的一项：取第一句（#603）。

    原因行后面都跟着一句「接下来怎么办」，整行塞进「跳过（…）」会盖过前面那一栏。没有记下
    说明的结果返回空串，由调用方写成中性的「跳过」。
    """
    tail = [t for t in result.get("tail") or [] if t.strip()]
    if not tail:
        return ""
    return re.split(r"[。！？；\n]", tail[-1].strip())[0].strip()



# 免安装版与旧名安装并存时的那条提示（#872）。必须写明「0.3.2 及更早版本装的名字」：
# 0.4.0 安装包的 AppName 已经换成「肉呆去广告」，只写旧名字用户会对不上号。
OLD_INSTALL_NOTE = (
    "这台电脑上还装着旧版的「安卓去广告」（0.3.2 及更早版本装的名字），"
    "它不会被现在运行的这份替换。"
    "两种做法任选：从官网下载 Windows 安装版覆盖安装，新版会顶掉旧的；"
    "或者先卸载旧的「安卓去广告」。卸载只删程序目录，数据和备份都保留。"
)
OLD_INSTALL_MARK = "old_install_noticed"


class _DiagnosticsProbe:
    """`tool/diagnostics.py` 的 `Probe` 实现：两个跑本机命令的查询留在这里，那边就不碰 `subprocess`。"""

    def __init__(self, api):
        self.api = api

    def adb_version(self):
        try:
            return self.api._adb("version", timeout=8).splitlines()[0] if self.api.adb else "没有 adb"
        except Exception as e:
            return f"adb 出错：{e}"

    def usb_devices(self):
        return usb_phones()


class Api:
    def __init__(self, data_dir, adb=None, runner=None):
        self.data = ClientData(data_dir)
        self.backups = _tool("backups").Backups(self.data.backups)
        # 下载器只认 Data 与 adb 初值；版本号与三张源表从本模块传进去，单一来源仍在上面那张表
        self.downloader = AdbDownloader(self.data, adb, version=VERSION,
                                        pinned=ADB_PINNED, mirrors=ADB_MIRRORS, latest=ADB_LATEST)
        # 上报块只用标准库：版本号、地址、空报告文案与限频从本模块传进去（单一来源仍在这里），
        # 宿主措辞与排查提示给取值函数——手机版在构造之前就把它们换掉了。
        self.reporter = Reporter(self.data, version=VERSION, report_url=REPORT_URL, empty_report=EMPTY_REPORT,
                                 limit=REPORT_LIMIT, os_name=lambda: os_name(),
                                 help_of=lambda: _tool("troubleshooting"))
        self.runner = runner or Runner(self._child_env)
        self.dispatcher = Dispatcher(lambda: self.runner, lambda: self.backups, self.data,
                                     lambda: self.adb, self._on_error,
                                     chime=lambda: chime(), link_lost=lambda: LINK_LOST,
                                     adb_present=lambda adb, serial: adb_present(adb, serial),
                                     summary=_tool("summary"), coverage_note=_tool("coverage_note"),
                                     plan_of=lambda: _tool("plan"))
        update_root = Path(self.data.updates)
        self.updater = updates.Updates(VERSION, update_root, update_install.DesktopInstaller(update_root),
                                       source=self.data.setting("update_source", "gitee"),
                                       claim=lambda: self.dispatcher.claim("安装更新"),
                                       release=self.dispatcher.release,
                                       save_source=lambda source: self.data.put_setting("update_source", source))
        self.last_status = None
        self.last_devices = ""
        self.last_scan_notes = []
        self.last_chans = None        # 上一次通知扫描的候选；None 表示没扫成
        self.harmony_bridge = harmony_bridge.HarmonyBridge(
            self.data.root, self.dispatcher.claim, self.dispatcher.release,
            sys.platform in ("darwin", "win32"))

    @property
    def adb(self):
        return self.downloader.adb

    @adb.setter
    def adb(self, value):
        self.downloader.adb = value

    @property
    def dl(self):
        return self.downloader.dl

    @property
    def last_error(self):
        return self.reporter.last_error

    @last_error.setter
    def last_error(self, value):
        self.reporter.last_error = value

    @property
    def report_times(self):
        return self.reporter.report_times

    @property
    def job(self):
        return self.dispatcher.job

    @job.setter
    def job(self, value):
        self.dispatcher.job = value

    @property
    def lock(self):
        return self.dispatcher.lock

    def _child_env(self):
        return child_env(self.adb, self.data.backups, self.data.captures)

    # ----- 基础 -----
    def env(self):
        update_install.confirm_started(self.data.updates, VERSION, sys.executable)
        return {"adb": self.adb, "data": self.data.root, "version": VERSION, "os": platform.system(),
                "harmony": self.harmony_bridge.enabled,
                "images": [f for f in sorted(os.listdir(os.path.join(toolpath.BASE, "images"))) if f.startswith("dev-")]}

    def harmony(self, action, serial="", mode="clean", segments=None):
        """鸿蒙窗口桥只转发；装配与状态在 `harmony_bridge.HarmonyBridge`（#898）。"""
        return self.harmony_bridge.command(action, serial, mode, segments)

    def old_install_notice(self):
        """旧名安装还在时给一次提示；用户关掉后这一版不再出现（#872）。"""
        if self.data.setting(OLD_INSTALL_MARK) == VERSION:
            return {}
        if not winpreflight.old_install_present():
            return {}
        return {"text": OLD_INSTALL_NOTE}

    def dismiss_old_install(self):
        """用户关掉提示：这一版不再出现，换下一版时再问一次（#872）。"""
        self.data.put_setting(OLD_INSTALL_MARK, VERSION)
        return True

    def check_update(self):
        return self.updater.check()

    def update_state(self):
        return self.updater.snapshot()

    def download_update(self, source="gitee"):
        return self.updater.download(source)

    def cancel_update(self):
        return self.updater.cancel()

    def install_update(self):
        return self.updater.install()

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
        # 线程入口留在门面：调用方 patch `api._download` 时与改前一样生效。
        if self.dl["state"] == "running":
            return
        threading.Thread(target=self._download, daemon=True).start()

    def adb_sources(self):
        return self.downloader.adb_sources()

    def _download(self):
        # 传 callable 而不是先求值：源表构造失败也要落成 dl 的 error 状态。
        self.downloader._download(self.adb_sources)

    def download_state(self):
        return self.downloader.download_state()

    # ----- 手动指定 adb -----
    def adb_info(self):
        """设置里显示的那几项：当前生效的 adb、来源、版本，以及手填的那份是不是已经不可用。"""
        manual = self.data.setting("adb") or ""
        info = {"ok": False, "path": self.adb or "", "source": adb_source(self.adb, manual, self.data.platform_tools),
                "version": "", "error": "", "manual": manual, "manual_error": "",
                "running": self._job_running()}
        if self.adb:
            try:
                m = re.search(r"Android Debug Bridge version ([\d.]+)", self._adb("version", timeout=8))
                info["version"] = m.group(1) if m else ""
                info["ok"] = bool(m)
            except Exception as e:
                info["error"] = str(e)
        if manual and info["source"] != "manual":
            info["manual_error"] = ("你指定的 adb 已不可用（文件不在了）" if not os.path.isfile(manual)
                                    else f"你指定的 adb {ADB_VERSION_HINT}")
        return info

    def _job_running(self):
        with self.dispatcher.exclusive():
            return self.dispatcher.busy()

    def set_adb_path(self, text):
        """保存手填的 adb。校验不通过就不写配置，原设置原样保留（#311）。"""
        path = adb_from_input(text)
        if not path:
            return {"ok": False, "error": "请填写 adb 的完整路径"}
        if not os.path.isfile(path):
            return {"ok": False, "error": f"找不到这个文件：{path}"}
        if not adb_ok(path):
            return {"ok": False, "error": f"这个文件{ADB_VERSION_HINT}。"}
        self.data.put_setting("adb", path)
        self.adb = path                     # 手填的排第一且刚验过，解析结果就是它，不再重跑一遍 adb_ok
        info = self.adb_info()
        info["ok"] = True                   # 界面把 ok 读成「保存成功」；adb 本身能不能用由 version / error 说明
        return info

    def clear_adb_path(self):
        self.data.put_setting("adb", None)
        self.adb = find_adb(self.data.platform_tools)
        return self.adb_info()

    def pick_adb_file(self):
        """文件对话框选 adb。没有窗口（测试、截图脚本）或没装 pywebview 时返回空串，界面退回手填。"""
        try:
            import webview
            picked = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG)
        except Exception:
            return ""
        return picked[0] if picked else ""

    # ----- 设备 -----
    def devices(self):
        if not self.adb:
            return {"error": "no-adb", "list": []}
        naming = _tool("run")   # 候选属性与取法只在 tool/run.py 定义，别在这里再抄一份
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
                    keys = ("ro.product.brand", "ro.product.model") + tuple(naming.NAME_PROPS)
                    p = self._adb("-s", ser, "shell",
                                  "; ".join(f"getprop {k}" for k in keys), timeout=8).splitlines()
                    p += [""] * len(keys)
                    d.update(brand=p[0].strip(), model=p[1].strip(),
                             name=naming.first_nonempty(v.strip() for v in p[2:len(keys)]))
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
        self.last_scan_notes = []     # 任何失败（含未预期的异常）都不留上一次的附注
        self.last_chans = None        # 扫成之前不知道有没有候选（#577 的结果行要分这一档）
        try:
            out, err, rc = self._run("chan_fast.py", "-s", serial, "scan", timeout=120)
        except (subprocess.TimeoutExpired, OSError) as e:
            return self._remember_error("通知扫描", serial, str(e))
        if rc:
            return self._remember_error("通知扫描", serial, err or out or "通知扫描失败，请检查连接与权限")
        # 成功路径上的 stderr 是引擎的排除计数（#521）：不按文案挑行，流里给什么就带什么。
        self.last_scan_notes = [line for line in (err or "").splitlines() if line.strip()]
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
        self.last_chans = rows
        return {"chans": rows, "notes": self.last_scan_notes}

    def _remember_error(self, operation, serial, detail):
        return self.reporter.remember_error(operation, serial, detail)

    def _on_error(self, operation, serial, detail):
        """调度块只问「这段失败要提示什么」：recovery 文案由上报块算。"""
        return self._remember_error(operation, serial, detail).get("recovery", "")

    def ui_check(self, serial):
        with self.dispatcher.exclusive():
            if self.dispatcher.busy():
                return {"error": "任务正在执行，请结束后再检查读屏连接"}
            if self.dispatcher.side:      # 还原正在点手机：检查读屏会和它抢同一块屏（#675）
                return {"error": f"「{self.dispatcher.side}」正在做，结束后再检查读屏连接"}
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
        """前端发来的计划字典在这里收成规格对象，之后的内部一路传 `Plan`（#1106）。"""
        plan = _tool("plan").Plan.from_json(plan)
        # 机型脚本验到什么程度由引擎从台账现读（沿用 #1124 的 status-json 字段），这里只随这次执行
        # 带给结果页（#1129）。说不说由 Dispatcher.poll 按结果里有没有脚本那一行决定（#1188）。
        coverage = (self.last_status or {}).get("recipe_coverage", "")
        return self.dispatcher.start(serial, plan, self._offered(), recipe_coverage=coverage)

    def retry(self):
        """把上一轮没做成的步骤再跑一遍（#638）。结果按步骤合并，快照成功过就绝不再存。

        一次都没跑过、或没有可重试的项时什么都不做，回一句为什么。连续点两次只会有一次生效：
        `Dispatcher.start()` 在锁里看到已有任务在跑就回绝。上一轮的日志与诊断载荷一并交给新
        `Job`：诊断与上报要看的是整场，不是最后那一轮。"""
        j = self.job
        if not j:
            return {"error": "没有需要重试的步骤"}
        view = j.snapshot(0)            # 锁内的一致视图（ADR-0010），别裸读工作线程正在写的列表
        plan = retry_plan(j.plan, view["results"])
        if plan is None:
            return {"error": "没有需要重试的步骤"}
        # 档位无条件沿用上一轮：这一轮可能只重跑别的步，但上一轮的脚本结果行仍按 kind 合并留在
        # 结果页上（沿用 #638 的合并口径），那条提示跟着它走，不能因为这一轮没跑脚本就消失（#1129）。
        return self.dispatcher.start(j.serial, plan, base_results=view["results"],
                                     base_lines=view["lines"], base_payloads=list(j.payloads),
                                     recipe_coverage=view["recipe_coverage"])

    def _offered(self):
        """选择页上摆出来的项：判断「没执行」是用户没勾还是这台机本来就没有（#577）。
        还没检测过就返回 None——那时不知道摆过什么，结果里不加这些行。
        没有 `steps` 的 status 不是一次完整检测（对拍驱动只塞了 `info`），同样按没检测算。"""
        if not self.last_status or "steps" not in self.last_status:
            return None
        return {"steps": self.last_status.get("steps") or [],
                "quickapps": self.last_status.get("quickapps") or [],
                "ads": self.last_status.get("ads") or [],
                "channels": self.last_chans}

    def _log(self, s, job=None):
        return self.dispatcher._log(s, job)

    def _event(self, data, job=None):
        return self.dispatcher._event(data, job)

    def _work(self, tasks):
        return self.dispatcher._work(tasks)

    def poll(self, since=0):
        return self.dispatcher.poll(since)

    def stop(self):
        return self.dispatcher.stop()

    def pause(self):
        return self.dispatcher.pause()

    def resume(self):
        return self.dispatcher.resume()

    def run_mode(self):
        """这次执行在哪块屏上跑、结论出来没有（#618）。桌面版只有主屏；手机版在 `aac_android.main.boot()`
        里换成读后台屏的状态。"""
        return {"background": False, "deciding": False}

    # ----- 收尾 / 还原 -----
    def dev_off(self, serial):
        out, err, rc = self._run("run.py", "-s", serial, "dev-off", "--yes", timeout=30)
        return out + err

    def restore(self, serial, what):
        """还原与执行、与另一次还原互斥（#662）：占不到位置就直接回一句说明，不碰手机。"""
        held = self.dispatcher.claim("还原")
        if held:
            return held
        try:
            return self._restore_work(serial, what)
        finally:
            self.dispatcher.release()

    def _restore_work(self, serial, what):
        if what == "suspend":
            out, err, rc = self._run("run.py", "-s", serial, "unsuspend")
        elif what == "quickapp":
            out, err, rc = self._run("run.py", "-s", serial, "quickapp", "on")
        elif what == "channels":
            st = self.status(serial)
            fn = self._closed_channels(st.get("info", {}).get("model", ""))
            if not fn:
                return "没有找到上次关掉的营销通知清单"
            out, err, rc = self._run("chan_fast.py", "-s", serial, "on", fn, timeout=600)
        else:
            return "未知的还原项"
        return out + err

    def _closed_channels(self, model):
        """这个型号历次关掉的营销渠道，合成一份清单交给 `chan_fast.py on`；一份都没有返回 None。
        以前只看最近一份备份，最近一次没关渠道时，之前关的就打不开了（#628）。按包名 + 渠道 ID 去重，
        最近的那条在前；已经开着的渠道 `on` 本来就跳过。读法照 `chan_fast.load()`：清单是让人手工删行
        的，带 BOM / CRLF 的另存、只剩空格的差异、改坏的行都不能让整次还原失败。"""
        rows, seen = [], set()
        for d in self.backups.all(model):
            fn = os.path.join(d, "channels.tsv")
            if not os.path.exists(fn):
                continue
            with open(fn, encoding="utf-8-sig") as f:
                for line in f:
                    cells = [c.strip() for c in line.rstrip("\r\n").split("\t")]
                    pk, cid = cells[0], cells[1] if len(cells) > 1 else ""
                    if not re.fullmatch(r"[\w.]+", pk) or not cid or (pk, cid) in seen:
                        continue
                    seen.add((pk, cid))
                    rows.append("\t".join(cells))
        if not rows:
            return None
        out = os.path.join(self.backups.gui(model), "channels-restore.tsv")
        with open(out, "w", encoding="utf-8") as f:
            f.write("# 包名\t渠道id\t渠道名\t应用名（历次关掉的合并）\n" + "\n".join(rows) + "\n")
        return out

    # ----- 反馈 -----
    def diagnostics(self):
        """反馈附带的诊断信息。措辞、排版与脱敏在 `tool/diagnostics.py`（#1376）；
        这里只把状态整理成普通映射、注入两个本机查询。"""
        return _tool("diagnostics").diagnostics(self._diagnostics_state(), self._diagnostics_probe())

    def _diagnostics_state(self):
        """诊断文本要的全部输入，按产生者整理：字段从 `Api` 取，执行快照在锁内取一次（ADR-0010）。"""
        rows = tuple(line.split()[1] for line in self.last_devices.splitlines()[1:] if len(line.split()) > 1)
        return {"app": APP_NAME, "version": VERSION, "frozen": FROZEN,
                "os": os_name(), "machine": platform.machine(),
                "adb": self.adb, "other_adb": other_adb(), "devices": rows,
                "status": self.last_status, "scan_notes": list(self.last_scan_notes),
                "job": self._diagnostics_job(), "last_error": self.last_error,
                "tap_refused": TAP_REFUSED, "home": os.path.expanduser("~")}

    def _diagnostics_job(self):
        """执行快照里诊断要的三样：序列号、每条已预渲染跳过原因的结果行、末 60 行日志。"""
        j = self.job
        if not j:
            return None
        snap = j.snapshot(0)
        results = []
        for r in snap["results"]:
            skipped = bool(r.get("skipped"))
            results.append({"title": r["title"], "rc": r["rc"], "sec": r["sec"], "skipped": skipped,
                            "reason": skip_reason(r) if skipped else ""})
        return {"serial": j.serial, "results": results,
                "log": [line for line in snap["lines"] if line.strip()][-60:]}

    def _diagnostics_probe(self):
        return _DiagnosticsProbe(self)

    # ----- 错误日志上报 -----
    def report_payload(self):
        return self.reporter.report_payload(self.last_status, self._report_view())

    def _report_view(self):
        """上报只看这四样：序列号、全量日志、全量结果、载荷行（ADR-0011）。"""
        j = self.job
        if not j:
            return {"serial": None, "lines": [], "results": [], "payloads": []}
        snap = j.snapshot(0)
        return {"serial": j.serial, "lines": snap["lines"], "results": snap["results"],
                "payloads": list(j.payloads)}

    def _install_id(self):
        return self.reporter._install_id()

    def send_report(self, payload):
        return self.reporter.send_report(payload)

    def copy_text(self, text):
        try:
            if IS_WIN:
                startup.win_clipboard(text)          # 与启动失败弹窗同一份实现（gui/startup.py）
            else:
                subprocess.run(["pbcopy"], input=text, text=True, encoding="utf-8", errors="replace", timeout=10)
            return True
        except Exception:
            return False

    def open_path(self, which):
        path = {"data": self.data.root, "backups": self.data.backups,
                "harmony": os.path.join(self.data.root, "harmony")}.get(which, self.data.root)
        os.makedirs(path, exist_ok=True)
        if IS_WIN:
            os.startfile(path)
        else:
            subprocess.Popen(["open", path])

    def open_url(self, url):
        """网址里的中文先转成 %XX：macOS 经 AppleScript、Windows 经 shell 打开中文网址会出错。"""
        import webbrowser, urllib.parse
        webbrowser.open(urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~"))


def startup_failed(error, preflight=None, notify=None, open_url=None, clipboard=None):
    """转发到 gui/startup.py；弹窗标题用本模块的 APP_NAME（它的单一来源在这里）。"""
    return startup.startup_failed(error, preflight=preflight, notify=notify,
                                  open_url=open_url, clipboard=clipboard, app_name=APP_NAME)


if __name__ == "__main__":          # `python -m gui.app` / `python gui/app.py` 仍从这里进
    if __package__:
        from .launch import main
    else:
        # 直接跑本文件时它是 `__main__`；登记成 `app` 免得 launch 把本模块再执行一遍
        sys.modules.setdefault("app", sys.modules[__name__])
        from launch import main
    main()
