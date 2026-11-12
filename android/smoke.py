#!/usr/bin/env python3
"""真机冒烟：CI 出 debug 包 → 装到开发机 → 启动 → 从首页点到底 → 还原 → 报告。

  .venv/bin/python android/smoke.py [--serial 序列号] [--ref 分支或标签] [--commit 提交] [--fast] [--screens]

构建留在 CI：触发 android.yml、等它跑完、下载 debug APK，再用本机的 adb 装到开发机并启动。
之后默认走完整主流程（检测 → 扫描 → 确认 → 开始 → 完成）：桌面侧读屏认文字、点按驱动，完全
不改 App；`--fast` 换成只跑执行段的快速档（按手机状态现算一份计划交给 debug 计划入口）。两条路
最后都自动还原三项（挂起的包、快应用组件、营销通知渠道），并把 logcat 缓冲交回原来那一档，
给出「构建」「安装 + 启动」
「真流程 + 还原」三段的结论。产物（人读摘要、结果 JSON、原始结果、logcat）按 commit 落在临时
目录，不入库。用法与首次配对步骤见 android/README.md。
"""
import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
from stdio import use_utf8_console  # noqa: E402

REPO = "rddmwmddr/android-ad-cleaner"
WORKFLOW = "android.yml"
ARTIFACT = "debug-apk"
PACKAGE = "com.ahuamiao.adcleaner"
ACTIVITY = PACKAGE + "/.MainActivity"
TOOL = Path(__file__).resolve().parents[1] / "tool"
DEFAULT_REF = "main"
DEFAULT_ROOT = Path(tempfile.gettempdir()) / "aac-smoke"
POLL_SECONDS = 15
LAND_SECONDS = 5
BUILD_TIMEOUT = 45 * 60
DISPATCH_TIMEOUT = 120
LOGCAT_SIZE = "16M"     # 默认 256 KiB 在 PYB110 上只留约 110 秒，一轮引擎 215 秒；调大后整轮都在（实测 #1116）

# App 那边的 debug 导出入口（android/app/src/debug/.../Demo.kt 的 `--es call smoke`）
SMOKE_TAG = "AACSmoke"
SHELL_READY = "ready"
# 数据根是手机版 `AacApp` 给的 `files/data`（`ClientData` 的 root），备份目录名见 `tool/backups.py`
APP_BACKUPS = "files/data/backups"      # debug 包可以用 run-as 读
EXPORT_POLL = 3                         # 读导出的间隔
EXPORT_WAIT = 60                        # 敲一次入口后等它打出第一份结果的预算
RUN_TIMEOUT = 20 * 60                   # 执行段本身的预算
RUN_QUIET = 60                          # 导出停了这么久就重敲一次入口，再停就判没跑起来
RESTORE_TIMEOUT = 600
RESTORE_WAIT = 5                        # 还原失败后重试之前的停顿

# `--es demo` 认的页面名（android/app/src/debug/.../Demo.kt）：不连手机逐屏验收界面
DEFAULT_SCREENS = (
    "setup1", "setup2", "setup3", "setup3mi", "old", "stopped-sh", "ask", "denied", "nodev",
    "home", "prepare0", "prepare1", "choose", "blocked", "norecipe", "scanfail",
    "run", "paused", "pausing", "stalled", "fgmode", "stopping", "done", "failed", "failed2", "stopped",
    "coverage",
)

PASS, FAIL, SKIP = "通过", "失败", "未执行"

# 完整主流程的锚点文字（#1073）：App 界面上的文案，改文案会让这条路失效——`--fast` 是兜底。
# 「再做一次」「重新开始」只出现在完成页，执行页与确认页都没有，比页面标题稳妥。
HOME_CTA = "一键去广告"
START_CTA = "开始"
DONE_MARKS = ("再做一次", "重新开始")
DONE_FAILED, DONE_STOPPED = "有步骤没成功", "已停止"
NOTHING_CHOSEN = "已选 0 项"            # 这台机之前已经关过：确认页没有可勾的项，走不到执行
PAGE_WAIT = 240                          # 点完一键去广告到确认页的预算：检测 + 通知扫描
DONE_WAIT = 45                           # 认完成页的预算：跑完后 App 自己还占着 UiAutomation，
                                         # 主屏读不到就按导出的结局算，别在这里耗满一整段
PAGE_POLL = 5                            # 认页面的间隔
SCREEN_TIMEOUT = 90                      # 一次读屏的预算：起服务要十几秒；被占时等这么久就够判死
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


class SmokeError(Exception):
    """跑不起来：没有设备、找不到提交、命令本身失败。早退且不触发 CI。"""


class Runner:
    """外部命令的唯一出口：脚本发出的每条 git / gh / adb 命令都经过它，测试注入假实现。

    返回 (stdout, stderr, 返回码)，与 gui/app.py 的 Runner 同形。
    """

    def run(self, *cmd, timeout=600):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=timeout)
        except FileNotFoundError:
            raise SmokeError("找不到命令 %s：装好它或放进 PATH" % cmd[0]) from None
        except subprocess.TimeoutExpired:
            raise SmokeError("命令 %s 超过 %d 秒没返回" % (" ".join(cmd), timeout)) from None
        return result.stdout, result.stderr, result.returncode


@dataclass(frozen=True)
class Step:
    name: str
    status: str
    detail: str

    @property
    def ok(self):
        return self.status == PASS

    def as_dict(self):
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class Report:
    sha: str
    ref: str
    serial: str
    steps: list
    screens: list
    logcat: str
    directory: Path
    restore: list = ()
    run: dict = None

    @property
    def ok(self):
        return all(step.ok for step in self.steps) and all(step.ok for step in self.screens)

    def text(self):
        lines = [f"冒烟 {self.sha[:12]}（{self.ref}）@ {self.serial}"]
        lines += [f"{step.name}：{step.status}  {step.detail}" for step in self.steps]
        lines += [f"{step.name}：{step.status}  {step.detail}" for step in self.restore]
        if self.screens:
            bad = [step.name for step in self.screens if not step.ok]
            lines.append(f"逐屏：{FAIL}  {'、'.join(bad)} 没起来" if bad
                         else f"逐屏：{PASS}  {len(self.screens)} 屏都活着")
        lines.append(f"产物：{self.directory}")
        return "\n".join(lines)

    def as_dict(self):
        return {"sha": self.sha, "ref": self.ref, "serial": self.serial, "ok": self.ok,
                "steps": [step.as_dict() for step in self.steps],
                "restore": [step.as_dict() for step in self.restore],
                "screens": [step.as_dict() for step in self.screens]}

    def write(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "report.md").write_text(self.text() + "\n", encoding="utf-8")
        (self.directory / "result.json").write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.directory / "logcat.txt").write_text(self.logcat, encoding="utf-8")
        if self.run is not None:
            (self.directory / "run.json").write_text(
                json.dumps(self.run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pick_serial(runner):
    """只连一台就自动取；零台或多台都不猜。"""
    out, err, rc = runner.run("adb", "devices")
    if rc != 0:
        raise SmokeError("adb 跑不起来：" + first_line(err or out))
    listed = [line.split() for line in out.splitlines()[1:] if len(line.split()) == 2]
    devices = [parts[0] for parts in listed if parts[1] == "device"]
    if not devices:
        seen = "、".join("%s（%s）" % (parts[0], parts[1]) for parts in listed)
        raise SmokeError("没有可用的手机：%s。授权 USB 调试后 `adb devices` 里的状态要是 device"
                         % (seen or "一台都没连上"))
    if len(devices) > 1:
        raise SmokeError("连着 %d 台手机，用 --serial 指定一台：%s" % (len(devices), "、".join(devices)))
    return devices[0]


def resolve_commit(runner, commit):
    out, err, rc = runner.run("git", "rev-parse", "--verify", commit + "^{commit}")
    if rc != 0:
        raise SmokeError("找不到提交 %s：%s" % (commit, first_line(err or out)))
    return out.strip()


def first_line(text):
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return "（没有输出）"


def last_line(text):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def output_detail(text, limit=300):
    """命令输出压成一行给报告：多行都留着（进度行不是原因），过长才截断。"""
    joined = "；".join(line.strip() for line in text.splitlines() if line.strip())
    return joined if len(joined) <= limit else joined[:limit] + "…"


def runs(runner, branch):
    """该分支上手动触发的 CI 运行（按创建时间倒序）。

    只要 workflow_dispatch：并行会话往 main push 也会建运行，混进来就会被当成「本次」，
    等错构建、下载错包，报告里的 SHA 也是别人的。
    """
    out, err, rc = runner.run("gh", "run", "list", "--workflow", WORKFLOW, "--branch", branch,
                              "--event", "workflow_dispatch", "--limit", "20",
                              "--json", "databaseId,headSha")
    if rc != 0:
        raise SmokeError("列不出 CI 运行记录：" + first_line(err or out))
    return json.loads(out or "[]")


def run_ids(runner, branch):
    """触发之前先记一份已有的运行，之后靠差集认出本次那条。"""
    return {run["databaseId"] for run in runs(runner, branch)}


def await_new_run(runner, branch, before, sleep, poll, timeout):
    waited = 0
    while waited <= timeout:
        fresh = [run for run in runs(runner, branch) if run["databaseId"] not in before]
        if fresh:
            return fresh[0]
        sleep(poll)
        waited += poll
    raise SmokeError("%d 秒内没等到新的 CI 运行，手动看一眼 actions 页面" % timeout)


def await_build(runner, run_id, sleep, poll, timeout):
    """等 CI 跑完，返回 conclusion；超时返回 None。"""
    waited = 0
    while waited <= timeout:
        out, err, rc = runner.run("gh", "run", "view", str(run_id), "-R", REPO,
                                  "--json", "status,conclusion")
        if rc != 0:
            raise SmokeError("读不到 CI 运行 %s：%s" % (run_id, first_line(err or out)))
        state = json.loads(out)
        if state["status"] == "completed":
            return state.get("conclusion") or "未知"
        sleep(poll)
        waited += poll
    return None


def crashes(logcat):
    """logcat 里属于本 App 的 FATAL 行；没有返回 None。

    按崩溃块里有没有包名收敛：开发机上别的 App 崩在同一个 5 秒窗口里，不该算到本次头上。
    """
    lines = logcat.splitlines()
    for index, line in enumerate(lines):
        if "FATAL EXCEPTION" in line and PACKAGE in "\n".join(lines[index:index + 6]):
            return line
    return None


def logcat_size(runner, serial):
    """main 缓冲当前那一档（`256 KiB` → `256K`，能原样交回 `logcat -G`）；读不到返回 None。"""
    out, _, rc = runner.run("adb", "-s", serial, "shell", "logcat", "-g")
    found = re.search(r"main: ring buffer is (\d+)\s*([KMGT])i?B", out or "")
    return "%s%s" % (found.group(1), found.group(2)) if found else None


def widen_logcat(runner, serial, note):
    """把 logcat 环形缓冲调大，返回调之前那一档（收尾时交回去）。

    默认的 256 KiB 在 PYB110 上只留约 110 秒，而引擎一轮 215 秒、产物取的是跑完那一份 dump：
    引擎行与 `AACSmoke` 导出块都会被系统日志滚掉（#1116）。`-G` 同时作用于四个缓冲，交回时按
    main 那一档下发——`logcat` 没有按缓冲设尺寸的入口。

    调不动要在 note 里说出来：静默失败会让空的 `logcat.txt` 被当成回归。
    """
    before = logcat_size(runner, serial)
    _, err, rc = runner.run("adb", "-s", serial, "shell", "logcat", "-G", LOGCAT_SIZE)
    after = logcat_size(runner, serial)
    if rc != 0 or (after is not None and after != LOGCAT_SIZE):
        note("logcat 缓冲没能调到 %s（%s），产物可能只剩系统日志"
             % (LOGCAT_SIZE, first_line(err) or "读数没变"))
        return None
    if after is None:
        note("logcat 缓冲调到 %s 了（读不出当前档位，无法确认，跑完也不会改回去）" % LOGCAT_SIZE)
        return None
    note("logcat 缓冲 %s → %s%s" % (before or "读不到", LOGCAT_SIZE,
                                    "" if before else "（读不到原档位，跑完不会改回去）"))
    return before


def launch(runner, serial, land, sleep, dumps, demo=None):
    """清日志 → 启动 → 等页面站稳 → 收 logcat。返回 judge_launch 的四个实参。

    demo 非空时走 `--es demo <页面>`。demo 会把后端换成假实现且不还原，所以逐屏之间必须先强停
    （Demo.kt 的已知约束），那一步由调用方发。
    """
    runner.run("adb", "-s", serial, "logcat", "-c")
    extra = ("--es", "demo", demo) if demo else ()
    out, err, rc = runner.run("adb", "-s", serial, "shell", "am", "start", "-n", ACTIVITY, *extra)
    started = rc == 0 and "Error" not in (out + err)
    sleep(land)
    pid, _, _ = runner.run("adb", "-s", serial, "shell", "pidof", PACKAGE)
    dump, _, _ = runner.run("adb", "-s", serial, "logcat", "-d")
    dumps.append("== %s ==\n%s\n" % (demo or "启动", dump))
    return started, (out + err).strip(), pid.strip(), dump


def judge_launch(started, started_output, pid, logcat, land):
    """启动这一段的结论：(通过与否, 人读说明)。"""
    fatal = crashes(logcat)
    if not started:
        return False, "启动失败：am start 没起来（%s）" % first_line(started_output)
    if not pid:
        return False, "启动失败：启动后 %d 秒进程不在" % land
    if fatal:
        return False, "启动失败：logcat 有 " + fatal.split("AndroidRuntime:", 1)[-1].strip()
    return True, "启动后 %d 秒进程存活（pid %s），logcat 无 FATAL" % (land, pid)


# ---------- 执行段与还原（#1072） ----------

def tool(name):
    """引擎脚本与冒烟用同一个解释器：本机 `.venv` 里才有 adbutils，系统 python 会缺。"""
    return (sys.executable, str(TOOL / name))


def start_cmd(serial, *extra):
    return ("adb", "-s", serial, "shell", "am", "start", "-n", ACTIVITY, *extra)


def export_cmd(serial):
    """敲一下 App 的 debug 导出入口：shell 状态 + 这一轮执行结果（一次导出只走这一个入口）。"""
    return start_cmd(serial, "--es", "call", "smoke")


def plan_cmd(serial, plan):
    # 计划 JSON 要过设备上的 sh 才到得了 am：单引号包住，空格与引号都不会被拆开
    return start_cmd(serial, "--es", "plan", shlex.quote(json.dumps(plan, ensure_ascii=False)))


def status_of(runner, serial):
    """手机上现算的状态 JSON（与检测页同一份）。段名从这里取，绝不写死：脚本改名后写死的段名会静默空跑。"""
    out, err, rc = runner.run(*tool("run.py"), "-s", serial, "status-json", timeout=120)
    lines = [line for line in out.splitlines() if line.strip()]
    if rc != 0 or not lines:
        raise SmokeError("读不到手机状态：" + output_detail(err or out))
    try:
        return json.loads(lines[-1])
    except ValueError:
        raise SmokeError("手机状态不是 JSON：" + output_detail(lines[-1])) from None


def plan_from_status(status):
    """手机状态 JSON → 计划 JSON（纯函数，可离线测）。

    字段与手机版确认页的 `Selection.plan()` 同形，取舍不同：冒烟是要把引擎真跑一遍，所以机型脚本的
    段名全下发、这台机上还没挂起的广告包都挂上；快应用只在这台机真有可关的组件时才勾。已挂起的包
    与已关闭的组件不进计划——再挂一次没有意义，还原也只会把本来就没动的东西报成已恢复。
    """
    ads = [a["pkg"] for a in status.get("ads") or [] if not a.get("suspended")]
    quickapps = [q for q in status.get("quickapps") or [] if not q.get("closed") and not q.get("keep")]
    return {"backup": True,
            "model": (status.get("info") or {}).get("model", ""),
            "steps": list(status.get("steps") or []),
            "ref": bool(status.get("recipe_ref")),
            "channels": [],                      # 快速档不扫描通知，渠道由「还原」一项单独处理
            "quickapp": bool(quickapps),
            "ads": ads}


def parse_export(text):
    """logcat 里的导出块拼回 JSON，返回 (组号, 内容)；一份完整的都没有就返回 None。

    App 按块发：`<组号> <块号>/<块数> <内容>`，组号是当时的毫秒时间戳。一行 logcat 约 4 KB
    就截断，整份结果装不进一行。最近一份可能还没打全（读的瞬间正在写），那就退到最近一份完整的。
    """
    groups = {}
    for line in text.splitlines():
        at = line.find(SMOKE_TAG + ": ")
        if at < 0:
            continue
        head, _, body = line[at + len(SMOKE_TAG) + 2:].partition(" ")
        part, _, chunk = body.partition(" ")
        index, _, total = part.partition("/")
        if not (head.isdigit() and index.isdigit() and total.isdigit()):
            continue
        groups.setdefault(int(head), {})[int(index)] = chunk
    for seq in sorted(groups, reverse=True):
        parts = groups[seq]
        if len(parts) != max(parts):
            continue                          # 这一份还没打全，往更早的找
        try:
            return seq, json.loads("".join(parts[i] for i in sorted(parts)))
        except ValueError:
            continue
    return None


def read_export(runner, serial):
    out, err, rc = runner.run("adb", "-s", serial, "logcat", "-d", "-s", SMOKE_TAG + ":I")
    return parse_export(out) if rc == 0 else None


def await_export(runner, serial, *, sleep, poll=EXPORT_POLL, wait=EXPORT_WAIT, tries=2, field=""):
    """敲入口，等 App 打出一份完整的结果；读不到返回 None（旧包没有这个入口、App 没起来都算读不到）。

    `field` 非空时只认填了这个字段的导出：shell 状态在 App 那边是旁路算的，头一两份可能还是空的。
    """
    for _ in range(tries):
        runner.run(*export_cmd(serial))
        waited = 0
        while waited < wait:
            sleep(poll)
            waited += poll
            got = read_export(runner, serial)
            if got and (not field or got[1].get(field) not in (None, "")):
                return got[1]
    return None


def installed(runner, serial):
    out, err, rc = runner.run("adb", "-s", serial, "shell", "pm", "path", PACKAGE)
    return rc == 0 and out.strip().startswith("package:")


def check_shell(runner, serial, *, sleep, note=print):
    """开跑前判 App 自己的 shell 通道是不是 ready；不是就停下，不触发 CI（#1072）。

    没装 App 就没什么可判的：这一轮装完再按 README 首次配对一次。
    """
    if not installed(runner, serial):
        note("手机上还没装这个 App，跳过配对检查（首次跑装好后要配对一次，见 android/README.md）")
        return
    blob = await_export(runner, serial, sleep=sleep, field="shell")
    if blob is None:
        # 旧版调试包 / 正式包都没有这个入口；这一轮装完才有。不能因此拦下整轮。
        note("读不到 App 的状态（可能还装着旧版）：跳过配对检查，执行段会照实报")
        return
    state = str(blob.get("shell") or "")
    if not state:                             # 导出出错 / 没有这个字段：判不了，别拦整轮
        note("App 的状态里没有 shell 信息，跳过配对检查，执行段会照实报")
        return
    if state != SHELL_READY:
        raise SmokeError("App 现在不能以 shell 身份执行（状态 %s）。在手机上重新走一遍「开始授权」再跑；"
                         "这一轮没有触发 CI。" % state)


def launch_plan(runner, cmd, *, sleep, land):
    """下发计划。冷启动时界面在 onCreate 里先处理 intent，那时设备还没就绪，第一份会被丢掉（#1072），
    所以固定发两次；App 已经起来时第二次只是接上正在跑的那一轮。"""
    for _ in range(2):
        out, err, rc = runner.run(*cmd)
        if rc != 0 or "Error" in (out + err):
            raise SmokeError("计划没发出去：" + first_line(out + err))
        sleep(land)


def await_run(runner, serial, *, sleep, cmd=None, poll=EXPORT_POLL, timeout=RUN_TIMEOUT,
              quiet=RUN_QUIET):
    """等执行段跑完。App 在跑的时候会连着导出，导出停了就是这一轮没起来（或 App 卡死了）。

    冷启动比两次下发之间的间隔还慢时，两份计划都可能被丢掉：导出停了就连计划一起重发（App 已经
    在跑时再发只会接上那一轮），再停才判没跑起来。
    """
    runner.run(*export_cmd(serial))
    seen, waited, still, resent = None, 0, 0, False
    while waited <= timeout:
        sleep(poll)
        waited += poll
        got = read_export(runner, serial)
        if got and got[1].get("finished"):
            return got[1]
        if got and got[1].get("error"):
            raise SmokeError("App 的导出报错：" + str(got[1]["error"]))
        if got and got[0] != seen:
            seen, still = got[0], 0
            continue
        still += poll
        if still < quiet:
            continue
        if resent:
            raise SmokeError("执行段没有跑起来：App 的导出停在 %d 秒前，先看一眼手机上是不是停在首页" % still)
        if cmd:
            out, err, rc = runner.run(*cmd)
            if rc != 0 or "Error" in (out + err):
                raise SmokeError("计划没发出去：" + first_line(out + err))
            sleep(poll)
        runner.run(*export_cmd(serial))
        still, resent = 0, True
    raise SmokeError("执行段 %d 分钟没跑完" % (timeout // 60))


def running_now(runner, serial, *, sleep):
    """此刻引擎还在手机上没有。导出停住时用它区分「没跑起来」与「还在跑、只是脚本没等到」。"""
    runner.run(*export_cmd(serial))
    sleep(EXPORT_POLL)
    got = read_export(runner, serial)
    return bool(got and (got[1].get("run") or {}).get("running"))


def app_channels(runner, serial, directory):
    """从 App 私有目录取出历次关掉的营销渠道，合并去重写成一份清单。

    返回 `(清单路径, 读不到的原因)`：两者都是 None 表示 App 里本来就没有清单（还没关过渠道）。
    手机版跑出来的清单只在 App 里（`files/data/backups/*/channels.tsv`），电脑侧的 backups 是
    空的（`Api._closed_channels` 读的是本机目录），所以这里用 debug 包的 `run-as` 逐份取、
    按包名 + 渠道 ID 合并；不认型号目录名，也不依赖电脑侧备份（#1072）。
    """
    out, err, rc = runner.run("adb", "-s", serial, "exec-out", "run-as", PACKAGE,
                              "ls", APP_BACKUPS, timeout=30)
    if rc != 0:
        reason = (err or out).strip()
        if re.search(r"run-as:|not debuggable|unknown package|permission denied", reason, re.I):
            return None, "读不到 App 私有目录：" + first_line(reason)
        return None, None                     # 还没备份过：目录不存在，不是失败
    names = sorted((name.strip() for name in out.splitlines() if name.strip()), reverse=True)
    rows, seen = [], set()
    for name in names:
        found, err, code = runner.run("adb", "-s", serial, "exec-out", "run-as", PACKAGE,
                                      "cat", APP_BACKUPS + "/" + name + "/channels.tsv", timeout=30)
        if code != 0:
            continue                          # 这一份没有清单（例如 `<型号>-gui` 临时目录）
        for line in found.splitlines():
            cells = [cell.strip() for cell in line.rstrip("\r").split("\t")]
            pkg, cid = (cells + ["", ""])[:2]
            if not re.fullmatch(r"[\w.]+", pkg) or not cid or (pkg, cid) in seen:
                continue
            seen.add((pkg, cid))
            rows.append("\t".join(cells))
    if not rows:
        return None, None
    path = directory / "channels-restore.tsv"
    path.write_text("# 包名\t渠道id\t渠道名\t应用名（App 私有目录里历次关掉的合并）\n"
                    + "\n".join(rows) + "\n", encoding="utf-8")
    return path, None


@dataclass(frozen=True)
class Restore:
    """一项还原：要么有命令，要么说明「没什么可还原的」，要么是读不到（problem 非空即失败）。"""
    name: str
    command: tuple = None
    note: str = ""
    problem: str = ""


def restore_items(runner, serial, status, directory):
    """三项还原各自的命令；命令在发出去之前就定好。"""
    pkgs = [a["pkg"] for a in status.get("ads") or [] if a.get("suspended")]
    channels, problem = app_channels(runner, serial, directory)
    return [
        Restore("挂起的包", tool("run.py") + ("-s", serial, "unsuspend", *pkgs) if pkgs else None,
                note="没有挂起的广告包"),
        Restore("快应用组件", tool("run.py") + ("-s", serial, "quickapp", "on")),
        Restore("营销通知渠道",
                tool("chan_fast.py") + ("-s", serial, "on", str(channels)) if channels else None,
                note="App 里没有关过的渠道清单", problem=problem or ""),
    ]


def restore_all(runner, items, *, note=print, sleep=time.sleep, wait=RESTORE_WAIT):
    """逐项还原；失败重试一次，仍失败就报「设备可能残留改动」并停手，不自动重跑（#1072）。"""
    def attempt(cmd):
        try:
            return runner.run(*cmd, timeout=RESTORE_TIMEOUT)
        except SmokeError as failure:         # 超时、找不到命令也只是一项没做成，不能吞掉别的结论
            return "", str(failure), 1

    steps = []
    for index, item in enumerate(items):
        if item.problem:
            steps.append(Step("还原 " + item.name, FAIL, item.problem))
            steps += [Step("还原 " + rest.name, SKIP, "已停手") for rest in items[index + 1:]]
            return steps
        if item.command is None:
            steps.append(Step("还原 " + item.name, PASS, item.note or "没有要还原的"))
            continue
        out, err, rc = attempt(item.command)
        if rc != 0:
            note("还原 %s 没成功，重试一次" % item.name)
            sleep(wait)
            out, err, rc = attempt(item.command)
            if rc != 0:
                steps.append(Step("还原 " + item.name, FAIL, output_detail(out + err)))
                steps += [Step("还原 " + rest.name, SKIP, "已停手") for rest in items[index + 1:]]
                return steps
        steps.append(Step("还原 " + item.name, PASS, first_line(out) or "已完成"))
    return steps


def judge_run(blob, restore, error="", flow="执行段", outcome="ok", how="完成页"):
    """第三段：跑完没有 + 还原完成没有。走了几步只记录、不判定。

    `flow` 只影响措辞。完整主流程的结局由完成页的标题给（`outcome`，`how` 说从哪儿认的）；
    快速档没有完成页，按导出里的 `finished` 判（#1072）。
    """
    run = (blob or {}).get("run") or {}
    results = run.get("results") or []
    done = [r for r in results if r.get("rc") == 0 and not r.get("skipped")]
    unfinished = [r for r in results if r.get("rc") != 0 and not r.get("skipped")]
    bad = [step for step in restore if not step.ok]
    if bad:
        return False, "设备可能残留改动：%s %s" % (bad[0].name, bad[0].detail)
    if outcome == "failed":
        return False, "%s是「%s」，完成 %d 步（只记录）；还原完成" % (how, DONE_FAILED, len(done))
    if outcome == "stopped":
        return False, "%s是「%s」；还原完成" % (how, DONE_STOPPED)
    if outcome != "ok":
        return False, "%s认不出结局（%s）；还原完成" % (how, outcome)
    if not (blob or {}).get("finished"):
        return False, "%s没跑完：" % flow + (error or run.get("error") or (blob or {}).get("error")
                                            or "App 没给出这一轮的结局")
    detail = "%s跑完，完成 %d 步（只记录）" % (flow, len(done))
    if unfinished:
        detail += "，%d 步没做成（只记录）" % len(unfinished)
    if how and how != "完成页":
        detail += "，结局取自" + how
    return True, detail + "；还原完成"


# ---------- 完整主流程（#1073） ----------

@dataclass(frozen=True)
class Node:
    """dump 里一个带文字的节点。点它的 bounds 中心，等于点这段文字。"""
    text: str
    bounds: tuple
    package: str = ""
    clickable: bool = False
    enabled: bool = True

    @property
    def center(self):
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2


def screen_nodes(xml):
    """uiautomator 格式的 dump → 带文字的节点。解析不了就抛，不当成「这一屏是空的」。

    文字有两个落点：`text` 与 `content-desc`（Compose 的图标按钮把标签放后者）。
    包名留着：认文字之前先确认这一屏是本 App，否则会点到别人身上。
    """
    start = xml.find("<hierarchy")
    if start < 0:
        raise SmokeError("读屏输出里没有 <hierarchy>：" + output_detail(xml, 160))
    try:
        root = ElementTree.fromstring(xml[start:].strip())
    except ElementTree.ParseError as error:
        raise SmokeError("读屏输出不是完整的 XML（%s）：%s" % (error, output_detail(xml, 160))) from None
    nodes = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip() or (node.get("content-desc") or "").strip()
        box = BOUNDS.search(node.get("bounds") or "")
        if not text or not box:
            continue
        nodes.append(Node(text, tuple(int(value) for value in box.groups()), node.get("package") or "",
                          node.get("clickable") == "true", node.get("enabled") != "false"))
    return nodes


def find_text(nodes, label):
    """按文字找节点：先精确、再包含；都能命中时优先可点的那个。

    包含匹配是为了「已选 12 项」这类带数的文案；精确优先是为了不把提示语里的「开始」当成按钮。
    """
    exact = [node for node in nodes if node.text == label]
    if exact:
        return next((node for node in exact if node.clickable), exact[0])
    hits = [node for node in nodes if label in node.text]
    if hits:
        return next((node for node in hits if node.clickable), hits[0])
    return None


def screen_lines(nodes, limit=8):
    """这一屏上看到的文字：找不到目标时给人看的现场。"""
    seen = []
    for node in nodes:
        if node.text not in seen:
            seen.append(node.text)
    return "、".join(seen[:limit]) or "（这一屏没有文字）"


def tap_cmd(serial, node):
    """按坐标点按。不用 App 的自动化接口：这条路不改 App，界面怎么画就怎么点。"""
    x, y = node.center
    return ("adb", "-s", serial, "shell", "input", "tap", str(x), str(y))


def screen_cmd(serial):
    """一次读屏起一个子进程，走引擎同一个读屏 adapter（`ui_session.connect`）。

    不直连 `uiautomator dump`：这台一加上它会被系统 kill（rc=137），引擎那条路才通得过。
    """
    return (sys.executable, str(Path(__file__).resolve()), "--read-screen", serial)


def read_screen(runner, serial):
    out, err, rc = runner.run(*screen_cmd(serial), timeout=SCREEN_TIMEOUT)
    if rc != 0 or "<hierarchy" not in out:
        # 子进程的 stderr 是整段栈，原因在最后一行：「另一个任务正占着读屏」就长这样
        raise SmokeError("读屏失败：" + (last_line(err) or last_line(out) or "没有输出"))
    return screen_nodes(out)


def dump_screen(serial):
    """`--read-screen` 的实现：起一次读屏会话、打一份 dump、退出前释放。

    与引擎共用 `ui_session.connect`：同一台电脑同一时刻只有一个读屏使用者，另一处正在跑
    （比如另一个会话在执行）就抛出来，等页面的那边会接着重试。
    """
    sys.path.insert(0, str(TOOL))
    import ui_session                       # 只有这条路要 uiautomator2，与引擎共用一份
    device = ui_session.connect(serial)
    try:
        sys.stdout.write(device.dump_hierarchy())
        sys.stdout.flush()
    finally:
        device.close()
    return 0


def await_nodes(runner, serial, marks, *, sleep, poll=PAGE_POLL, timeout=PAGE_WAIT,
                relaunch=None, relaunch_every=30):
    """等本 App 的这一屏出现 marks 里的任意一个文字，返回 (命中的标记, 这一屏的节点)。

    读屏被占（App 正在扫通知 / 正在跑引擎）不算失败，接着等：UiAutomation 同一时刻只给一个
    使用者。前台是别的 App 时只认「不在本 App」这一条，不按坐标点——否则会点到别人身上；
    `relaunch` 是把它拉回前台的命令，隔一阵发一次。超时把最后的原因和最后读到的文字一起
    报出来，别只说「没等到」。
    """
    waited, reason, next_launch = 0, "", 0
    while True:
        try:
            nodes = read_screen(runner, serial)
        except SmokeError as failure:
            reason = "最后一次读屏失败：" + str(failure)
        else:
            mine = [node for node in nodes if node.package == PACKAGE]
            if mine:
                for mark in marks:
                    if find_text(mine, mark):
                        return mark, mine
                reason = "最后一次读到的这一屏上有：" + screen_lines(mine)
            else:
                reason = "前台不是这个 App：" + screen_lines(nodes)
                if relaunch and waited >= next_launch:
                    relaunch()
                    next_launch = waited + relaunch_every
        if waited >= timeout:
            raise SmokeError("%d 秒内没等到「%s」。%s" % (timeout, "」「".join(marks), reason))
        sleep(poll)
        waited += poll


def tap(runner, serial, node, label, *, note=print):
    if not node.enabled:
        raise SmokeError("「%s」是灰的（当前不能点）：先处理手机上的提示再跑" % label)
    note("点「%s」@%d,%d" % ((label,) + node.center))
    out, err, rc = runner.run(*tap_cmd(serial, node))
    if rc != 0 or "Error" in (out + err):
        raise SmokeError("点「%s」没点成：%s" % (label, first_line(out + err)))


def walk_flow(runner, serial, *, sleep, note=print, poll=PAGE_POLL, page=PAGE_WAIT,
              timeout=RUN_TIMEOUT, done_wait=DONE_WAIT):
    """从首页点到底：一键去广告 → 确认页 → 开始 → 完成页。返回 (结局, 这一轮的导出, 结局出处)。

    桌面侧只做两件事：读屏认文字、按坐标点按。认不出就带着这一屏上的文字停下，绝不猜。
    点之前先确认这一屏是本 App 的：系统把 App 切到后台时，按坐标点会点到别人身上。

    执行本身靠 App 的导出判结束（`await_run`）：那条路不占 UiAutomation，读屏才腾得出来。
    后台屏模式下完成页不在主屏——这时结局取自导出里的 `outcome`，报告里说明出处。
    """
    def show_app():
        out, err, rc = runner.run(*start_cmd(serial))
        if rc != 0 or "Error" in (out + err):
            raise SmokeError("把 App 拉回前台没成功：" + first_line(out + err))

    note("等首页")
    _, nodes = await_nodes(runner, serial, (HOME_CTA,), sleep=sleep, poll=poll, timeout=page,
                           relaunch=show_app)
    tap(runner, serial, find_text(nodes, HOME_CTA), HOME_CTA, note=note)

    note("等确认页")
    _, nodes = await_nodes(runner, serial, (START_CTA,), sleep=sleep, poll=poll, timeout=page,
                           relaunch=show_app)
    if find_text(nodes, NOTHING_CHOSEN):
        raise SmokeError("确认页上没有可勾选的项（这台机之前已经关过）：点「开始」只会提示「还没选任何一项」，"
                         "执行链路走不到。先把这一台的改动还原再跑")
    tap(runner, serial, find_text(nodes, START_CTA), START_CTA, note=note)

    note("等主流程跑完")
    blob = await_run(runner, serial, sleep=sleep, timeout=timeout)
    exported = str(((blob or {}).get("run") or {}).get("outcome") or "")
    note("认完成页")
    try:
        _, nodes = await_nodes(runner, serial, DONE_MARKS, sleep=sleep, poll=poll,
                               timeout=done_wait, relaunch=show_app)
    except SmokeError:
        if exported not in ("ok", "failed", "stopped"):
            raise
        note("完成页不在主屏（导出说这一轮是 %s），结局取自导出" % exported)
        return exported, blob, "导出（完成页不在主屏）"
    if find_text(nodes, DONE_FAILED):
        return "failed", blob, "完成页"
    if find_text(nodes, DONE_STOPPED):
        return "stopped", blob, "完成页"
    return "ok", blob, "完成页"


def smoke(runner, *, ref=None, commit=None, serial=None, fast=False, screens=(), root=None,
          sleep=time.sleep, note=print, poll=POLL_SECONDS, land=LAND_SECONDS,
          build_timeout=BUILD_TIMEOUT, dispatch_timeout=DISPATCH_TIMEOUT):
    """预检 → 触发 CI → 等 → 下载 → 装机 → 启动 → 跑主流程 → 还原 → 报告。

    默认跑完整主流程（从首页点到底）；`fast=True` 换成只跑执行段的快速档。
    跑不起来时抛 SmokeError；跑起来了但某一段失败，写进报告并返回。
    """
    serial = serial or pick_serial(runner)
    check_shell(runner, serial, sleep=sleep, note=note)
    temporary, saved_log = None, None
    if commit:
        sha = resolve_commit(runner, commit)
        ref = temporary = "smoke/" + sha[:12]
        note("把 %s 推成临时分支 %s" % (sha[:12], ref))
        out, err, rc = runner.run("git", "push", "origin", "%s:refs/heads/%s" % (sha, ref))
        if rc != 0:
            raise SmokeError("推不了临时分支：%s" % first_line(err or out))
    ref = ref or DEFAULT_REF
    try:
        before = run_ids(runner, ref)
        note("触发 %s @ %s" % (WORKFLOW, ref))
        out, err, rc = runner.run("gh", "workflow", "run", WORKFLOW, "-R", REPO, "--ref", ref)
        if rc != 0:
            raise SmokeError("触发不了 CI：" + first_line(err or out))
        run = await_new_run(runner, ref, before, sleep, poll, dispatch_timeout)
        run_id, sha = run["databaseId"], run["headSha"]
        directory = (Path(root) if root else DEFAULT_ROOT) / sha[:12]
        built = Step("构建", PASS, "%s run %s" % (REPO, run_id))

        note("等 CI 跑完（run %s）" % run_id)
        conclusion = await_build(runner, run_id, sleep, poll, build_timeout)
        if conclusion is None:
            return finished(sha, ref, serial, directory, [
                Step("构建", FAIL, "%d 分钟内没跑完（run %s）" % (build_timeout // 60, run_id)),
                Step("安装 + 启动", SKIP, "构建没跑完"),
                Step("真流程 + 还原", SKIP, "构建没跑完")])
        if conclusion != "success":
            return finished(sha, ref, serial, directory, [
                Step("构建", FAIL, "CI 结论 %s（run %s）" % (conclusion, run_id)),
                Step("安装 + 启动", SKIP, "构建失败"),
                Step("真流程 + 还原", SKIP, "构建失败")])

        note("下载 APK（run %s）" % run_id)
        shutil.rmtree(directory, ignore_errors=True)      # 同一个 commit 重跑时别拿上一次的包
        directory.mkdir(parents=True, exist_ok=True)
        out, err, rc = runner.run("gh", "run", "download", str(run_id), "-R", REPO,
                                  "-n", ARTIFACT, "-D", str(directory))
        apks = sorted(directory.glob("**/*.apk"))
        if rc != 0 or not apks:
            return finished(sha, ref, serial, directory, [
                built, Step("安装 + 启动", FAIL, "下载 APK 失败：" + output_detail(err or out)),
                Step("真流程 + 还原", SKIP, "没装成")])

        note("装到 %s" % serial)
        out, err, rc = runner.run("adb", "-s", serial, "install", "-r", str(apks[0]))
        if rc != 0 or "Success" not in out:
            return finished(sha, ref, serial, directory, [
                built, Step("安装 + 启动", FAIL, "安装失败：" + output_detail(out + err)),
                Step("真流程 + 还原", SKIP, "没装成")])

        note("启动")
        saved_log = widen_logcat(runner, serial, note)
        dumps = []
        ok, detail = judge_launch(*launch(runner, serial, land, sleep, dumps), land)
        steps = [built, Step("安装 + 启动", PASS if ok else FAIL, detail)]
        if not ok:
            steps.append(Step("真流程 + 还原", SKIP, "启动失败"))
            return finished(sha, ref, serial, directory, steps, (), "".join(dumps))

        # 两档判定的是同一件事：「这一轮真的跑完了」。完整主流程还要多一步认完成页的结局。
        flow, outcome, how, blob, error = ("执行段（快速档）" if fast else "完整主流程"), "ok", "", None, ""
        try:
            if fast:
                note("跑执行段（快速档）")
                plan = plan_from_status(status_of(runner, serial))
                note("计划：%s" % ("、".join(plan["steps"]) or "（这台机器型脚本段名为空）"))
                cmd = plan_cmd(serial, plan)
                launch_plan(runner, cmd, sleep=sleep, land=land)
                blob = await_run(runner, serial, sleep=sleep, cmd=cmd)
            else:
                note("跑完整主流程")
                outcome, blob, how = walk_flow(runner, serial, sleep=sleep, note=note)
        except SmokeError as failure:
            error = str(failure)

        dump, _, _ = runner.run("adb", "-s", serial, "logcat", "-d")
        dumps.append("== %s ==\n%s\n" % (flow, dump))

        # 导出停住但引擎还在手机上跑：这时还原会和执行抢同一块屏，停手并如实说（沿用 #662 的互斥）
        running = blob is None and running_now(runner, serial, sleep=sleep)
        note("还原")
        restore = []
        if running:
            restore = [Step("还原", SKIP, "执行还在跑，等它自己结束再还原")]
        else:
            try:
                items = restore_items(runner, serial, status_of(runner, serial), directory)
                restore = restore_all(runner, items, note=note, sleep=sleep)
            except SmokeError as failure:
                restore = [Step("还原", FAIL, "读不到手机状态，没能还原：%s" % failure)]
        ok, detail = judge_run(blob, restore, error, flow, outcome, how or "完成页")
        steps.append(Step("真流程 + 还原", PASS if ok else FAIL, detail))

        walked = []
        if not running:                       # 还在跑时强停进程会把执行杀在半截
            for name in screens:
                note("逐屏 %s" % name)
                runner.run("adb", "-s", serial, "shell", "am", "force-stop", PACKAGE)
                ok, detail = judge_launch(*launch(runner, serial, land, sleep, dumps, name), land)
                walked.append(Step(name, PASS if ok else FAIL, detail))
        return finished(sha, ref, serial, directory, steps, walked, "".join(dumps),
                        restore, (blob or {}).get("run"))
    finally:
        if saved_log:
            runner.run("adb", "-s", serial, "shell", "logcat", "-G", saved_log)
        if temporary:
            out, err, rc = runner.run("git", "push", "origin", "--delete", temporary)
            if rc != 0:
                note("临时分支 %s 没删掉（%s），手动删一下" % (temporary, first_line(err or out)))


def finished(sha, ref, serial, directory, steps, screens=(), logcat="", restore=(), run=None):
    report = Report(sha, ref, serial, steps, list(screens), logcat, directory, list(restore), run)
    report.write()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="真机冒烟：CI 出 debug 包 → 装开发机 → 启动 → 从首页点到底 → 还原 → 报告")
    parser.add_argument("--serial", help="设备序列号；只连一台时可以省")
    parser.add_argument("--ref", help="分支，默认 %s；标签与提交用 --commit" % DEFAULT_REF)
    parser.add_argument("--commit", help="指定提交或标签（SHA / 短 SHA / 分支名 / tag），会推一个临时分支")
    parser.add_argument("--fast", action="store_true",
                        help="只跑执行段（快速档）：界面改动让全流程自动化失效时用")
    parser.add_argument("--screens", nargs="?", const=",".join(DEFAULT_SCREENS), metavar="页面",
                        help="把 demo 逐屏走一遍并逐页判存活；不给值就是全部页面，逗号分隔")
    parser.add_argument("--root", help="产物父目录，默认 %s" % DEFAULT_ROOT)
    parser.add_argument("--read-screen", metavar="序列号", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    use_utf8_console()
    if args.read_screen:                  # 完整主流程的读屏子进程，不对外
        return dump_screen(args.read_screen)
    screens = tuple(name for name in (args.screens or "").split(",") if name)
    try:
        report = smoke(Runner(), ref=args.ref, commit=args.commit, serial=args.serial,
                       fast=args.fast, screens=screens,
                       root=Path(args.root) if args.root else None,
                       note=lambda line: print(line, flush=True))   # 重定向到文件时也要能看进度
    except SmokeError as error:
        print("跑不了：%s" % error, file=sys.stderr)
        return 2
    print(report.text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
