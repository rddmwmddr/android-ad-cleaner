#!/usr/bin/env python3
"""肉呆去广告 · 桌面客户端（macOS / Windows）。

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

APP_NAME = "肉呆去广告"
VERSION = "0.4.0"
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
        # 保留完整原因；避免异常逸出 PyInstaller 后只剩「Failed to execute script launch」。
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
        out = _tool("adb_link").invoke(path, "version", timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    m = re.search(r"version 1\.0\.(\d+)", out)
    return bool(m) and int(m.group(1)) >= 41


def adb_exe():
    return "adb.exe" if IS_WIN else "adb"


ADB_VERSION_HINT = "跑不出 Android Debug Bridge 的版本号，或者版本太旧（需要 1.0.41 及以上）"


def find_adb(platform_tools, manual=None):
    """手动指定的 adb 排第一：用户填了就是要它压过客户端下载的那份和其他来源（#311）。
    不存在或版本不够的候选由 adb_candidates / adb_ok 跳过，于是自动回退到后面的来源。"""
    last = (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
            "/opt/homebrew/bin/adb", "/usr/local/bin/adb")
    first = tuple(p for p in (manual, os.path.join(platform_tools, adb_exe())) if p)
    for c in _tool("adb_link").adb_candidates(first=first, last=last):
        if adb_ok(c):
            return c
    return None


def adb_from_input(text):
    """手填或文件对话框给的路径 → adb 可执行文件。目录补上 adb / adb.exe，去掉粘贴时带进来的引号。"""
    path = (text or "").strip().strip("\"'")
    if not path:
        return ""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(path):
        path = os.path.join(path, adb_exe())
    return path


def adb_source(adb, manual, platform_tools):
    """当前生效的这份 adb 从哪来：manual / downloaded / system / none。"""
    if not adb:
        return "none"
    if manual and os.path.normcase(adb) == os.path.normcase(manual):
        return "manual"
    if os.path.normcase(adb) == os.path.normcase(os.path.join(platform_tools, adb_exe())):
        return "downloaded"
    return "system"


def client_api():
    """入口（窗口与截图脚本）共用的构造：数据目录建好，adb 按既定顺序找，手填的那份排第一。"""
    data = ClientData(data_dir()).ensure()
    return Api(data.root, adb=find_adb(data.platform_tools, manual=data.setting("adb")))


def adb_present(adb, serial):
    """手机此刻是否连着（adb 状态为 device）；先给它 10 秒回来。"""
    if not adb:
        return False
    return _tool("adb_link").Connection(serial, adb=adb).alive(wait=10)


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
    path = os.path.join(BASE, "gui", "web", "chime.wav")
    try:
        play_sound(path)
    except Exception:
        pass


def child_env(adb, backups):
    e = dict(os.environ)
    # 事件开关只由本客户端在跑任务时打开。用户 shell 里碰巧导出了它也不能生效：
    # `_run()` 那些一次性命令会把输出直接解析（`status()` 取末行当 JSON）。
    e.pop("AAC_EVENTS", None)
    # 宿主标记同理：只认客户端自己给的 ENGINE_HOST，不从用户 shell 继承（#747）
    e.pop("AAC_HOST", None)
    if ENGINE_HOST:
        e["AAC_HOST"] = ENGINE_HOST
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
    args 由 `_work()` 换成 `-s <序列号> off <清单>`。
    skip_reason 非空表示这一步这次不跑：照样占结果里的一行，说明为什么（#577）。
    kind 是这一步的固定身份（backup / recipe / channels / quickapp / ads / finish），
    重试与多轮结果合并都按它对齐，不认标题（#638；标题里的「（3 / 9 段）」会变）。"""

    def __init__(self, title, script, args=(), uses_ui=False, channels=None, skip_reason="", kind=""):
        self.title, self.script, self.args = title, script, args
        self.uses_ui, self.channels = uses_ui, channels
        self.skip_reason, self.kind = skip_reason, kind


def runs_after_stop(task):
    """停止后仍要跑的一步：收尾（把手机改回插电常亮，以前停止会让手机一直亮着）。"""
    return task.title == "收尾"


UNCHECKED = "未勾选，本次没有执行"


def not_run(title, reason, kind=""):
    """这次不跑的步骤：不碰手机，只在结果里留一行（#577）。"""
    return Task(title, "", skip_reason=reason, kind=kind)


def step_result(task, **fields):
    """结果里的一行：标题与 kind 从任务上取，其余字段各有各的。合并多轮结果时按 kind 对齐（#638）。"""
    return {"title": task.title, "kind": task.kind, **fields}


def not_run_result(job, task):
    """没执行的项进结果：rc=0 表示这一步没出错，界面按「跳过」显示、上报也写「跳过」；
    原因放 tail，摘要函数认不出模式时直接拿它当摘要。诊断里由 `skip_reason()` 压成一句。"""
    job.add_result(step_result(task, rc=0, skipped=True, sec=0, tail=[task.skip_reason]))


def plan_tasks(serial, plan, offered=None):
    """这次排哪些任务。勾了的照旧起脚本；没勾的留一行「跳过」并说明原因（#577）。

    `offered` 是选择页上摆出来的项（调用方从检测结果与上一次通知扫描里取），用来区分
    「用户没勾」和「这台机本来就没有」；给 None 时不知道摆过什么，就不留这些行。"""
    tasks = []
    if plan.get("backup", True):
        tasks.append(Task("存改动前的快照", "run.py", ["-s", serial, "backup"], kind="backup"))
    steps = list(plan.get("steps") or [])
    if steps:
        title = "关闭各 App 里的广告开关"
        total = len(offered.get("steps") or []) if offered else 0
        if total > len(steps):
            title += f"（{len(steps)} / {total} 段）"
        tasks.append(Task(title, "run.py",
                          ["-s", serial, "recipe", *steps, *(["--ref"] if plan.get("ref") else [])],
                          uses_ui=True, kind="recipe"))
    elif offered is not None:
        tasks.append(not_run("关闭各 App 里的广告开关",
                             UNCHECKED if offered.get("steps") else "没有专用脚本，这一步要照清单手动做",
                             kind="recipe"))
    channels = list(plan.get("channels") or [])
    if channels:
        tasks.append(Task("关闭营销通知", "chan_fast.py", uses_ui=True, channels=channels, kind="channels"))
    elif offered is not None:
        seen = offered.get("channels")          # None 表示通知没扫成
        tasks.append(not_run("关闭营销通知",
                             "通知扫描没有完成，本次没有关闭营销通知" if seen is None
                             else "没有扫描到可关闭的营销渠道" if not seen else UNCHECKED,
                             kind="channels"))
    if plan.get("quickapp"):
        tasks.append(Task("关闭快应用", "run.py", ["-s", serial, "quickapp", "off"], kind="quickapp"))
    elif offered is not None:
        apps = offered.get("quickapps") or []
        tasks.append(not_run("关闭快应用",
                             "没有检测到快应用组件" if not apps
                             else "可关闭的快应用组件都已关闭" if all(q.get("closed") or q.get("keep") for q in apps)
                             else UNCHECKED,
                             kind="quickapp"))
    ads = list(plan.get("ads") or [])
    if ads:
        tasks.append(Task("挂起广告组件", "run.py", ["-s", serial, "suspend", *ads], kind="ads"))
    elif offered is not None:
        seen = offered.get("ads") or []
        tasks.append(not_run("挂起广告组件",
                             "没有已知的广告组件" if not seen
                             else "广告组件已经挂起" if all(a.get("suspended") for a in seen)
                             else UNCHECKED,
                             kind="ads"))
    # 重试轮只在收尾上一轮没做成时才跑它（#638）；首次执行没有这个键，照旧收尾
    if plan.get("finish", True):
        tasks.append(Task("收尾", "run.py", ["-s", serial, "finish"], kind="finish"))
    return tasks


def retryable(result):
    """这一步是不是没做成：失败，或因读屏被占用 / 断线 / 锁屏而跳过（#638）。

    除设备侧的原因外，子进程起不来（rc=-1）也算——这类重跑一次多半就好了。
    没勾选、这台机本来没有或已关、通知没扫成的那几档（#577）是 rc=0 的跳过，用户点「停止」的步带
    stopped，两者都不重试。
    """
    return bool(result.get("rc")) and not result.get("stopped")


def retry_plan(plan, results):
    """上一轮没做成的步骤组成的计划；一项都不剩时返回 None（#638）。

    广告开关步只重跑 `failed_steps` 里的段——脚本中途退出、没留下段名时才整段重跑。
    快照一旦成功就不再重存：重存会把已经关掉的状态当成原状，还原就还原不回去了。
    「通知没扫成」那一行不算可重试：扫描在选择页上就失败了，重跑这一步时的渠道清单本来就是空的，
    要重扫只能回选择页（#577 的第三档）。
    """
    plan = plan or {}
    again = {r.get("kind"): retryable(r) for r in results if r.get("kind")}
    recipe = next((r for r in results if r.get("kind") == "recipe"), {})
    steps = list(recipe.get("failed_steps") or plan.get("steps") or []) if again.get("recipe") else []
    out = {"backup": again.get("backup", False),
           "steps": steps, "ref": plan.get("ref"), "model": plan.get("model"),
           "channels": list(plan.get("channels") or []) if again.get("channels") else [],
           "quickapp": bool(plan.get("quickapp")) and again.get("quickapp", False),
           "ads": list(plan.get("ads") or []) if again.get("ads") else [],
           "finish": again.get("finish", False)}
    if not any(out[k] for k in ("backup", "steps", "channels", "quickapp", "ads", "finish")):
        return None
    return out


class Job:
    """一次执行的状态（ADR-0010）。工作线程写，HTTP 线程经 snapshot() 读一致视图。

    `plan` 是这一轮跑的原始计划，`retry_plan()` 拿它重建下一轮；重试轮的 `results` / `lines` /
    `payloads` 从上一轮接管过来，每一步按 kind 覆盖同一步的旧结果，日志与上报仍是整场的（#638）。"""

    def __init__(self, serial="", model="", total=0, t0=None, plan=None,
                 base_results=(), base_lines=(), base_payloads=()):
        self.lock = threading.RLock()
        self.running = True
        self.lines = list(base_lines)
        self.idx = 0
        self.total = total
        self.title = ""
        self.results = list(base_results)
        self.plan = dict(plan) if plan else None
        self.failed_steps = []          # 本步骤里引擎报的未完成段名
        self.proc = None
        self.cancel = False
        self.t0 = time.time() if t0 is None else t0
        self.serial = serial
        self.model = model
        self.paused = False
        self.pause = False
        self.recovery = ""
        self.step_events = set()
        self.payloads = list(base_payloads)

    def add_result(self, result):
        """记一行的结果。重试轮里同 kind 的那一行被就地覆盖，界面看到的始终是各步最新一轮（#638）。

        标题留着上一轮的：`关闭各 App 里的广告开关（3 / 9 段）` 说的是用户勾了哪几段，重试轮只跑其中
        一两段，按这一轮重算会把覆盖范围从界面上抹掉。"""
        with self.lock:
            kind = result.get("kind")
            if kind:
                for i, old in enumerate(self.results):
                    if old.get("kind") == kind:
                        self.results[i] = {**result, "title": old.get("title", result["title"])}
                        return
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
        """某一时刻的一致只读视图。lines 只给 since 之后的新行，next 是下一次的偏移。

        `retry` 是此刻还能重试的步数，结果页的按钮按它取 N（#638）。"""
        with self.lock:
            lines = self.lines[since:]
            return {"running": self.running, "lines": lines, "next": since + len(lines),
                    "idx": self.idx, "total": self.total, "title": self.title,
                    "results": list(self.results), "sec": round(time.time() - self.t0),
                    "cancel": self.cancel, "recovery": self.recovery,
                    "pause": self.pause, "paused": self.paused,
                    "retry": sum(1 for r in self.results if retryable(r))}


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
# adb 在 Windows 上只按 android_winusb.inf 里登记的这个 GUID 枚举 USB 接口；手机只登记了厂商
# 自己的 GUID 时，接口状态正常、`adb devices` 却静默为 0 台（#702）。
ADB_INTERFACE_GUID = "f72fe0d4-cbcb-407d-8814-9ed673d0dd6b"
USB_GUID_UNREADABLE = "-"   # PowerShell 与 usb_parse() 之间的约定：注册表没读到


def usb_hw_id(instance_id):
    """InstanceId 里认得出设备的那一段：`USB\\VID_xxxx&PID_xxxx` 加可选的 `&MI_xx`，
    最后一个反斜杠之后的设备序列号丢掉（诊断「序列号一律替换」的口径不能破）。认不出格式返回空。"""
    parts = (instance_id or "").split("\\")
    prefix = "\\".join(parts[:2])
    return prefix if re.fullmatch(r"USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}(&MI_[0-9A-F]{2})?", prefix, re.I) else ""


def usb_parse(out):
    """把 Get-PnpDevice 那段输出解析成设备表：品牌、设备名、状态、是不是调试接口、硬件 ID、
    登记的 device interface GUID 元组。末字段是 `-` 或整段缺失时算没读到（None），
    空字段算读到了但一个都没登记（空元组）。"""
    found = []
    for line in out.splitlines():
        parts = line.split("|")
        m = re.match(r"USB\\VID_([0-9A-F]{4})", parts[0], re.I)
        if not m:
            continue
        name = parts[1] if len(parts) > 1 else ""
        status = parts[2] if len(parts) > 2 else ""
        cls = parts[3] if len(parts) > 3 else ""
        raw = parts[4] if len(parts) > 4 else USB_GUID_UNREADABLE
        adb = bool(re.search(r"adb|android", name + " " + cls, re.I))
        guids = None if raw.strip() == USB_GUID_UNREADABLE else tuple(
            g.strip() for g in raw.split(",") if g.strip())
        found.append((USB_VENDORS.get(m.group(1).upper(), "安卓"), name, status, adb,
                      usb_hw_id(parts[0]), guids))
    return found


def usb_phones():
    """只读：Windows 设备管理器里按 USB 厂商号命中的设备（手机也可能混着同厂外设）。
    返回 [(品牌, 设备名, 状态, 是否 ADB 接口, 硬件 ID, 登记的 GUID 元组或 None)]；查不到返回空。"""
    if not IS_WIN:
        return []
    script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\\\VID_(" + "|".join(USB_VENDORS) + ")' } | "
              "ForEach-Object { $k = 'HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\' + $_.InstanceId + '\\Device Parameters'; "
              "$g = '" + USB_GUID_UNREADABLE + "'; if (Test-Path $k -ErrorAction SilentlyContinue) { "
              "try { $p = Get-ItemProperty -Path $k -ErrorAction Stop; "
              "$g = (@($p.DeviceInterfaceGUID, $p.DeviceInterfaceGUIDs) | Where-Object { $_ } | Select-Object -Unique) -join ',' } "
              "catch { $g = '" + USB_GUID_UNREADABLE + "' } }; "
              "$_.InstanceId + '|' + $_.FriendlyName + '|' + $_.Status + '|' + $_.Class + '|' + $g }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=8, creationflags=NOWIN).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return usb_parse(out)


def usb_guid_note(guids):
    """这个接口登记的 device interface GUID 里有没有 adb 要的那个；没有时把它实际登记的 GUID 说出来。"""
    if ADB_INTERFACE_GUID in {g.strip().strip("{}").lower() for g in guids}:
        return "已登记 adb 需要的 device interface GUID"
    registered = "、".join(g for g in guids if g.strip())
    trail = f"（实际登记的 GUID：{registered}）" if registered else "，也没有登记任何 GUID"
    return "未登记 adb 需要的 device interface GUID" + trail


def usb_facts(found, limit=5):
    """把命中的设备逐台说成诊断行：品牌、设备名、状态、是不是调试接口、硬件 ID。
    只截断设备台数，不替用户判断哪台是手机；带调试接口的排前面，先被截掉的是别的外设（#673）。
    调试接口后面再跟一行它登记的 device interface GUID，所以输出最多两倍 limit 行；读不到就不写（#702）。"""
    ordered = [f for f in found if f[3]] + [f for f in found if not f[3]]
    lines = []
    for brand, name, status, adb, hw, guids in ordered[:limit]:
        lines.append(f"{brand} {name}（{status}，{'调试接口' if adb else '非调试接口'}）硬件 ID：{hw or '未识别'}")
        if adb and guids is not None:
            lines.append(f"{brand} {name} {usb_guid_note(guids)}")
    return lines


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
            out = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5).stdout
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
# 断线后跳过后面各步时写给用户的话；手机版没有电脑，启动时换成自己的说法（aac_android.main.boot，#729）
LINK_LOST = "手机和电脑已断开，这一步没有执行。重新连接手机后点「重试」。"
# 诊断里「点击被拒」那一栏：手机版会整段复制与上报，不能写「电脑」（aac_android.main.boot，#747）
TAP_REFUSED = "；电脑点击被拒（未开 USB 调试安全设置）"
# 传给引擎子进程的宿主标记，手机版由 boot() 设成 "phone"；引擎按它取词（tool/host.py，#747）
ENGINE_HOST = ""
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


def skip_reason(result):
    """跳过结果记下的那行说明，压成报告里列表的一项：取第一句（#603）。

    原因行后面都跟着一句「接下来怎么办」，整行塞进「跳过（…）」会盖过前面那一栏。没有记下
    说明的结果返回空串，由调用方写成中性的「跳过」。
    """
    tail = [t for t in result.get("tail") or [] if t.strip()]
    if not tail:
        return ""
    return re.split(r"[。！？；\n]", tail[-1].strip())[0].strip()


class AdbDownloader:
    """下载并校验 platform-tools（#273）。下载源表、校验、落盘与下载状态都在这里（ADR-0011）。"""

    def __init__(self, data, adb=None):
        self.data = data
        self.adb = adb
        self.dl = {"state": "idle", "pct": 0, "msg": ""}

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

    def _download(self, sources=None):
        self.data.ensure()
        zp = self.data.adb_zip
        errors = []
        try:
            # sources 传 callable：源表构造失败也要被下面这支 except 收成 dl 的 error 状态
            for label, url, digest in (sources or self.adb_sources)():
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
            adb = os.path.join(self.data.platform_tools, adb_exe())
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


class Reporter:
    """错误诊断与上报：记下最近一次失败、组织上报内容、发送与限频（docs/12，ADR-0011）。"""

    def __init__(self, data):
        self.data = data
        self.last_error = None
        self.report_times = []

    def remember_error(self, operation, serial, detail):
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

    def report_payload(self, status, view):
        """要上报的全部内容。界面原样展示给用户，确认后发送同一份。"""
        info = (status or {}).get("info") or {}
        serial = view.get("serial")
        log = "\n".join(l for l in view.get("lines", []) if l.strip())
        if self.last_error:
            log += f"\n\n[最近失败：{self.last_error['operation']}]\n{self.last_error['detail']}"
        payloads = [x for x in view.get("payloads", []) if x.strip()]
        if payloads:
            # 放在末尾：日志只留最后 2 万字，骨架跟着失败日志一起留下，不会被早先的成功步骤挤掉
            log += "\n\n[诊断载荷]\n" + "\n".join(payloads)
        steps = [{"title": scrub(r["title"])[:40], "sec": int(r.get("sec") or 0),
                  "result": "跳过" if r.get("skipped") else "已停止" if r.get("stopped") else ("成功" if r["rc"] == 0 else "失败")}
                 for r in view.get("results", [])][:12]
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


class Dispatcher:
    """排任务步骤、起引擎子进程、收日志与事件（ADR-0004 / ADR-0010 / ADR-0011）。

    `on_error(operation, serial, detail)` 只回 recovery 文案，不认识上报块；
    `adb_of()` / `runner_of()` / `backups_of()` 在真正要用时取值：下载后 adb 路径会变，
    门面上的 runner / backups 也允许被调用方整体替换，两处必须读同一份。
    """

    def __init__(self, runner_of, backups_of, data, adb_of, on_error):
        self.runner_of = runner_of
        self.backups_of = backups_of
        self.data = data
        self.adb_of = adb_of
        self.on_error = on_error
        self.job = None
        self.lock = threading.Lock()
        self.side = ""                  # 正在跑的旁路操作（还原），与执行互斥（#662）

    def exclusive(self):
        """`ui_check()` 与 `start()` 互斥：持锁期间不许开新任务。"""
        return self.lock

    def busy(self):
        """调用方须持 `exclusive()` 的锁。"""
        return bool(self.job and self.job.running)

    def claim(self, name, wait=0.2):
        """占住「旁路操作」的位置（还原）：执行中或已有旁路操作时返回占着它的那件事的说明，占到了返回空串。
        还原与执行同时跑会互相点乱同一块屏，手机版上还原先结束还会把执行的保活一起撤掉（#662）。

        拿锁只等 `wait` 秒：`ui_check()` 持着同一把锁最长 75 秒，按界面按钮的线程不该被按在那里等，
        拿不到就直接回一句。"""
        if not self.lock.acquire(timeout=wait):
            return "正在检查读屏连接，等它结束后再还原"
        try:
            if self.busy():
                return "正在执行去广告，等它结束后再还原"
            if self.side:
                return f"「{self.side}」还没做完，请稍后"
            self.side = name
            return ""
        finally:
            self.lock.release()

    def release(self):
        with self.lock:
            self.side = ""

    def start(self, serial, plan, offered=None, base_results=(), base_lines=(), base_payloads=()):
        """plan: {backup, steps:[段名]|None, channels:[{pkg,id,name}], quickapp:bool, ads:[包名], model, finish}
        offered: 选择页上摆出来的项，给没勾的项定「没执行」的原因（#577）；None 表示不知道。
        三个 base_*: 重试轮从上一轮接管的快照（#638）；首次执行都是空的。"""
        with self.lock:
            if self.job and self.job.running:
                return {"error": "已有任务在运行"}
            if self.side:
                return {"error": f"「{self.side}」还没做完，请稍后再开始"}
            tasks = plan_tasks(serial, plan, offered)
            total = sum(1 for t in tasks if not t.skip_reason)
            self.job = Job(serial=serial, model=plan.get("model", ""), total=total, plan=plan,
                           base_results=base_results, base_lines=base_lines,
                           base_payloads=base_payloads)
        threading.Thread(target=self._work, args=(tasks,), daemon=True).start()
        return {"ok": True, "total": total}

    def _log(self, s, job=None):
        """记一行输出。事件行只改状态、不进日志，返回 None；人话返回存下来的文本。
        载荷行（页面骨架、通知权限模式等机器数据）单独收着，上报时拼在末尾：不进界面日志与步骤摘要，也不会在
        「最近失败的完整诊断」里重复一遍。工作线程传入自己那一次的 Job：它比 `Api.job`
        活得久，收尾时不能写进下一次执行。"""
        job = self.job if job is None else job
        s = s.rstrip("\n")
        events = _tool("events")
        if events.is_event(s):
            self._event(events.parse_data(s), job)
            return None
        if events.is_payload(s):
            with job.lock:
                job.payloads.append(events.strip_payload(s))
            return None
        with job.lock:
            job.lines.append(s)
        return s

    def _event(self, data, job=None):
        """引擎事件（ADR-0004）：暂停 / 继续 / 锁屏改提示状态，`failed_steps` 记下段名，
        其余记进本步骤的事件集合；都不进日志、不上报。`data` 是 `events.parse_data()` 给出的整份字典。"""
        job = self.job if job is None else job
        if not data:                    # 前缀对上但解析不出来：当没有这个事件
            return
        kind = data["kind"]
        if kind == "paused":
            with job.lock:
                job.paused = True
            chime()                     # 可以拿手机了
        elif kind == "resumed":
            with job.lock:
                job.paused = False
        elif kind == "locked":
            chime()                     # 要机主来解锁
        elif kind == "failed_steps":
            # 载荷来自另一个进程：只认字符串列表，别的形状当没报（单个字符串会被逐字符拆成段名）
            steps = data.get("steps")
            named = isinstance(steps, list) and all(isinstance(s, str) for s in steps)
            with job.lock:
                job.failed_steps = [s.strip() for s in steps if s.strip()] if named else []
        else:
            with job.lock:
                job.step_events.add(kind)

    def _work(self, tasks):
        j = self.job
        ui_busy = False
        done = 0                        # 真正跑过的步数：没执行的项不进「第 N / M 步」
        self.resume()                   # 上次没清掉的暂停标记不能带进这次
        for i, task in enumerate(tasks):
            if task.skip_reason:
                not_run_result(j, task)
                continue
            done += 1
            with j.lock:
                j.step_events = set()
                j.failed_steps = []
            if j.pause and not j.cancel:
                # 步骤之间的暂停；步骤里面的暂停由引擎在段与段、渠道与渠道之间处理
                with j.lock:
                    j.paused = True
                chime()                 # 可以拿手机了：与引擎侧暂停点的提醒一致
                self._log("⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」", j)
                while j.pause and not j.cancel:
                    time.sleep(0.5)
                with j.lock:
                    j.paused = False
                if not j.cancel:
                    self._log("▶ 继续执行", j)
            if j.cancel and not runs_after_stop(task):
                continue
            with j.lock:
                j.idx, j.title = done, task.title
            self._log(f"\n▶ {task.title}", j)
            if ui_busy and task.uses_ui:
                reason = "读屏服务仍被占用，跳过本步骤；请先解决读屏连接再重试。"
                self._log(reason, j)
                j.add_result(step_result(task, rc=3, skipped=True, sec=0, tail=[reason]))
                continue
            line_start = len(j.lines)
            t = time.time()
            script, args = task.script, list(task.args)
            if task.channels is not None:
                d = self.backups_of().snapshot(j.model)
                fn = os.path.join(d, "channels.tsv")
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("# 包名\t渠道id\t渠道名\t应用名（客户端勾选）\n")
                    for c in task.channels:
                        name = re.sub(r"[\t\r\n]+", " ", str(c.get("app") or "")).strip()
                        f.write(f"{c['pkg']}\t{c['id']}\t{c['name']}\t{name}\n")
                args = ["-s", j.serial, "off", fn]
            killed = False
            try:
                p = self.runner_of().spawn(script, *args, env_extra={"AAC_PAUSE_FILE": self.data.pause,
                                                                     "AAC_EVENTS": "1"})
                with j.lock:
                    j.proc = p
                    # 停止落在 spawn 返回、登记之前：request_stop 看不到这个进程，由登记的一方补杀
                    killed = j.cancel and not runs_after_stop(task)
                if killed:
                    p.terminate()
                tail = []
                for line in p.stdout:
                    shown = self._log(line, j)  # 事件行返回 None：不进步骤摘要（前端会展示 tail）
                    if shown is not None:
                        tail.append(shown.strip()); tail = tail[-80:]
                rc = p.wait()
            except Exception as e:
                rc, tail = -1, [str(e)]
                self._log(f"✗ {e}", j)
            if (rc or killed) and j.cancel and not runs_after_stop(task):
                # 用户点了停止：不是出错、不重试，也不记诊断、不提示上报（错误日志 10-28：4 份是停止后上报的）
                j.add_result(step_result(task, rc=rc, stopped=True, sec=round(time.time() - t), tail=tail))
                continue
            j.add_result(step_result(task, rc=rc, sec=round(time.time() - t), tail=tail,
                                     failed_steps=list(j.failed_steps)))
            if rc:
                detail = "\n".join(j.lines[line_start:])
                ui_busy = ui_busy or "ui_busy" in j.step_events
                if "link_lost" in j.step_events and not adb_present(self.adb_of(), j.serial):
                    # 手机已断开：后面每一步都会报同一段排查说明（错误日志 10-27），不再执行
                    self.on_error(task.title, j.serial, detail)
                    reason = LINK_LOST
                    for later in tasks[i + 1:]:
                        if later.skip_reason:      # 本来就不跑的项：原因照旧，不写成断线
                            not_run_result(j, later)
                            continue
                        self._log(f"\n▶ {later.title}\n{reason}", j)
                        j.add_result(step_result(later, rc=3, skipped=True, sec=0, tail=[reason]))
                    break
                recovery = self.on_error(task.title, j.serial, detail)
                if recovery:
                    with j.lock:
                        j.recovery = recovery
        self.resume()
        if not j.cancel:
            chime()                     # 执行结束（成功或有步骤没成功都响，提醒回来看结果）
        with j.lock:
            # 收尾行与「结束」同一个临界区：看到 running=False 的快照一定已经带着这一行，
            # 且下一次执行要等它发布完才能接管。收尾行按同一个临界区里的 cancel 取，别在锁外算
            final = f"\n执行结束，用时 {round(time.time() - j.t0)} 秒" if not j.cancel else "\n已停止"
            self._log(final, j)
            j.running = False
            j.proc = None

    def poll(self, since=0):
        j = self.job
        if not j:
            return {"running": False, "lines": [], "next": 0}
        snap = j.snapshot(since)
        if snap["running"]:
            snap["results"] = []        # 执行中不显示结果（前端契约）；诊断与上报仍读快照里的全量
        return snap

    def stop(self):
        # 取 job、判 running 与置停止在同一把锁里：不然判完之后新一次执行顶上来，停掉的是它（#662）
        with self.lock:
            j = self.job
            if not (j and j.running):
                return True
            j.request_stop()
        self.resume()
        return True

    def pause(self):
        """执行中需要操作手机时用：引擎做完手头这一项（一个渠道、机型脚本的一段、一个步骤）就停下等待。"""
        with self.lock:
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


class Api:
    def __init__(self, data_dir, adb=None, runner=None):
        self.data = ClientData(data_dir)
        self.backups = _tool("backups").Backups(self.data.backups)
        self.downloader = AdbDownloader(self.data, adb)
        self.reporter = Reporter(self.data)
        self.runner = runner or Runner(self._child_env)
        self.dispatcher = Dispatcher(lambda: self.runner, lambda: self.backups, self.data,
                                     lambda: self.adb, self._on_error)
        self.last_status = None
        self.last_devices = ""
        self.last_scan_notes = []
        self.last_chans = None        # 上一次通知扫描的候选；None 表示没扫成

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
        return self.dispatcher.start(serial, plan, self._offered())

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
        return self.dispatcher.start(j.serial, plan, base_results=view["results"],
                                     base_lines=view["lines"], base_payloads=list(j.payloads))

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
            found = usb_phones()
            hint = usb_hint(found)
            if hint:
                lines.append(f"- USB：{hint}")
            lines += [f"- USB 设备：{line}" for line in usb_facts(found)]
        if st and "info" in st:
            i = st["info"]
            nm = i.get("name") or i.get("model")
            if not nm.upper().startswith((i.get("brand") or "").upper()):
                nm = f"{i.get('brand')} {nm}"
            # 借用同品牌参考脚本时 recipe_ok 恒为假（run.py 的 `(not ref) and build_ok(...)`），
            # 检测页与手机版都先看 recipe_ref 再谈版本：这里同样分三档（#778）。
            recipe = st.get("recipe")
            if not recipe:
                script = "无"
            elif st.get("recipe_ref"):
                script = f"{recipe}（同品牌参考脚本，录制版本 {st.get('recipe_build') or '未标'}）"
            else:
                script = f"{recipe}（录制版本 {st.get('recipe_build')}，{'一致' if st.get('recipe_ok') else '不一致'}）"
            lines += [f"- 手机：{nm}（{i.get('model')}）",
                      f"- 系统：{i.get('os') or i.get('build')}（{i.get('build')}），Android {i.get('android')}",
                      f"- 机型脚本：{script}",
                      f"- 折叠屏展开：{'是' if st.get('fold_open') else '否'}；锁屏：{'是' if st.get('locked') else '否'}"
                      + (TAP_REFUSED if st.get("input_blocked") else "")]
        else:
            lines.append("- 手机：还没检测")
        if self.last_scan_notes:
            # 用户报「候选比预期少」时，判据就是这几条排除计数（#521）。
            lines.append("- 通知扫描附注：" + "；".join(self.last_scan_notes))
        j = self.job
        if j:
            snap = j.snapshot(0)
            lines.append("\n**执行结果**\n")
            for r in snap["results"]:
                if r.get("skipped"):
                    reason = skip_reason(r)
                    state = f"跳过（{reason}）" if reason else "跳过"
                else:
                    state = "成功" if r["rc"] == 0 else "失败（退出码 %s）" % r["rc"]
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
                win_clipboard(text)
            else:
                subprocess.run(["pbcopy"], input=text, text=True, encoding="utf-8", errors="replace", timeout=10)
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


# 启动失败弹窗是原生 MessageBox：文字选不中，用户只能手抄命令、拍照识别（#811）。
# 整段先替用户复制好；复制不进去才退回 Ctrl+C——有焦点时 Windows 的弹窗能整段复制。
COPIED_NOTE = "这段文字已复制到剪贴板，可以直接粘贴到反馈里，不用手抄或拍照。"
MANUAL_COPY_NOTE = "自动复制没成功，在这个弹窗上按 Ctrl+C 也能复制整段文字。"


def startup_advice(state, blocked, error, rejected, copied=None):
    """窗口起不来时给用户看的文案，以及要不要跳微软官网。

    copied: None 还没试过写剪贴板；True 已写入；False 写入失败（#811）。
    """
    text, open_site = _attribution(state, blocked, error, rejected)
    if copied is not None:
        text += "\n\n" + (COPIED_NOTE if copied else MANUAL_COPY_NOTE)
    return text, open_site


def _attribution(state, blocked, error, rejected):
    """按结论选文案（#228、#597）。

    以前一律说「缺少 WebView2」，portable 包解压后文件带 MOTW 的现场被指到装不上的东西上。
    带 MOTW 的 dll 与被判成「远程来源」的 dll 报的是同一句 `Failed to resolve`，所以先看
    `blocked` 再认原文——前者的出路是解锁文件，不是补 config。
    """
    if state == "missing":
        return (
            "这台电脑缺少微软 Edge WebView2 运行时，界面没法显示。\n\n"
            "点「确定」打开微软官网，下载安装「Evergreen Bootstrapper」后重新打开本程序。\n\n"
            f"（{error}）", True)
    if blocked:
        return (
            "这台电脑可能已经装了 WebView2，但程序文件被 Windows 标记成「来自网络」，"
            "加载时被拦住了。\n\n"
            "办法一：对下载的 zip 压缩包点右键 →「属性」→ 勾选「解除锁定」→ 确定，重新解压后再打开。\n"
            "办法二：zip 已经删了，就在解压出来的文件夹里按住 Shift 点右键 →"
            "「在此处打开 PowerShell 窗口」，粘贴下面这行后回车：\n"
            "Get-ChildItem . -Recurse -File | Unblock-File\n\n"
            f"（{error}）", False)
    if rejected:
        return (
            "这台电脑的 .NET Framework 把程序自带的 dll 判成了「远程来源」，加载时被拦住了。\n\n"
            "办法一：确认程序文件夹里 AndroidAdCleaner.exe 旁边有 AndroidAdCleaner.exe.config，"
            "别把它删掉或改名。\n"
            "办法二：没有这个文件，或者有了还是这样，从官方 Release 重新下载最新版，"
            "完整解压后再打开。\n\n"
            f"（{error}）", False)
    if state == "unknown":
        return (
            "程序启动失败。这台电脑的 WebView2 状态没能确认（多半是注册表读取受限），"
            "所以下面的原因不一定是缺运行时。\n\n"
            "如果这是 Windows 10 且从没装过，先装一个再试：\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            "装过还这样，把括号里的原文发到 "
            "https://github.com/rddmwmddr/android-ad-cleaner/issues/new 。\n\n"
            f"（{error}）", False)
    return (
        "程序启动失败。WebView2 运行时在，程序文件也没有被 Windows 锁定，"
        "是按别的原因退出的。\n\n"
        "把下面括号里的原文发到 "
        "https://github.com/rddmwmddr/android-ad-cleaner/issues/new ，我们按它定位。\n\n"
        f"（{error}）", False)


def startup_failed(error, preflight=None, notify=None, open_url=None, clipboard=None):
    """先替用户复制、再按归因弹提示（#228、#811）。四个协作者可注入，接线本身在非 Windows 上也能验。"""
    import ctypes, webbrowser
    preflight = preflight or winpreflight
    notify = notify or (lambda text: ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x40))
    clipboard = clipboard or win_clipboard
    verdict = (preflight.webview2_state(), preflight.blocked_files(BASE), error,
               preflight.load_rejected(error))
    text, open_site = startup_advice(*verdict, copied=True)
    try:
        clipboard(text)                       # 写进去的就是弹窗里那句，多一个字都不差
    except Exception:                         # 复制失败不能连弹窗一起吞掉：这里没有控制台
        text, open_site = startup_advice(*verdict, copied=False)
    notify(text)
    if open_site:
        (open_url or webbrowser.open)("https://developer.microsoft.com/microsoft-edge/webview2/")


if __name__ == "__main__":          # `python -m gui.app` / `python gui/app.py` 仍从这里进
    if __package__:
        from .launch import main
    else:
        # 直接跑本文件时它是 `__main__`；登记成 `app` 免得 launch 把本模块再执行一遍
        sys.modules.setdefault("app", sys.modules[__name__])
        from launch import main
    main()
