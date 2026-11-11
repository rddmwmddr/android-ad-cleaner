#!/usr/bin/env python3
"""真机冒烟 1/3：CI 出 debug 包 → 装到开发机 → 启动 → 报告。

  .venv/bin/python android/smoke.py [--serial 序列号] [--ref 分支或标签] [--commit 提交] [--screens]

构建留在 CI：触发 android.yml、等它跑完、下载 debug APK，再用本机的 adb 装到开发机并启动，
给出「构建」「安装 + 启动」两段的结论。产物（人读摘要、结果 JSON、logcat）按 commit 落在临时目录，
不入库。用法与首次配对步骤见 android/README.md，执行段与还原见 #1072。
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
from stdio import use_utf8_console  # noqa: E402

REPO = "rddmwmddr/android-ad-cleaner"
WORKFLOW = "android.yml"
ARTIFACT = "debug-apk"
PACKAGE = "com.ahuamiao.adcleaner"
ACTIVITY = PACKAGE + "/.MainActivity"
DEFAULT_REF = "main"
DEFAULT_ROOT = Path(tempfile.gettempdir()) / "aac-smoke"
POLL_SECONDS = 15
LAND_SECONDS = 5
BUILD_TIMEOUT = 45 * 60
DISPATCH_TIMEOUT = 120

# `--es demo` 认的页面名（android/app/src/debug/.../Demo.kt）：不连手机逐屏验收界面
DEFAULT_SCREENS = (
    "setup1", "setup2", "setup3", "setup3mi", "old", "stopped-sh", "ask", "denied", "nodev",
    "home", "prepare0", "prepare1", "choose", "blocked", "norecipe", "scanfail",
    "run", "paused", "pausing", "stalled", "fgmode", "stopping", "done", "failed", "failed2", "stopped",
)

PASS, FAIL, SKIP = "通过", "失败", "未执行"


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

    @property
    def ok(self):
        return all(step.ok for step in self.steps) and all(step.ok for step in self.screens)

    def text(self):
        lines = [f"冒烟 {self.sha[:12]}（{self.ref}）@ {self.serial}"]
        lines += [f"{step.name}：{step.status}  {step.detail}" for step in self.steps]
        if self.screens:
            bad = [step.name for step in self.screens if not step.ok]
            lines.append(f"逐屏：{FAIL}  {'、'.join(bad)} 没起来" if bad
                         else f"逐屏：{PASS}  {len(self.screens)} 屏都活着")
        lines.append(f"产物：{self.directory}")
        return "\n".join(lines)

    def as_dict(self):
        return {"sha": self.sha, "ref": self.ref, "serial": self.serial, "ok": self.ok,
                "steps": [step.as_dict() for step in self.steps],
                "screens": [step.as_dict() for step in self.screens]}

    def write(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "report.md").write_text(self.text() + "\n", encoding="utf-8")
        (self.directory / "result.json").write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.directory / "logcat.txt").write_text(self.logcat, encoding="utf-8")


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


def smoke(runner, *, ref=None, commit=None, serial=None, screens=(), root=None,
          sleep=time.sleep, note=print, poll=POLL_SECONDS, land=LAND_SECONDS,
          build_timeout=BUILD_TIMEOUT, dispatch_timeout=DISPATCH_TIMEOUT):
    """预检 → 触发 CI → 等 → 下载 → 装机 → 启动 → 报告。跑不起来时抛 SmokeError。"""
    serial = serial or pick_serial(runner)
    temporary = None
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
                Step("安装 + 启动", SKIP, "构建没跑完")])
        if conclusion != "success":
            return finished(sha, ref, serial, directory, [
                Step("构建", FAIL, "CI 结论 %s（run %s）" % (conclusion, run_id)),
                Step("安装 + 启动", SKIP, "构建失败")])

        note("下载 APK（run %s）" % run_id)
        shutil.rmtree(directory, ignore_errors=True)      # 同一个 commit 重跑时别拿上一次的包
        directory.mkdir(parents=True, exist_ok=True)
        out, err, rc = runner.run("gh", "run", "download", str(run_id), "-R", REPO,
                                  "-n", ARTIFACT, "-D", str(directory))
        apks = sorted(directory.glob("**/*.apk"))
        if rc != 0 or not apks:
            return finished(sha, ref, serial, directory, [
                built, Step("安装 + 启动", FAIL, "下载 APK 失败：" + output_detail(err or out))])

        note("装到 %s" % serial)
        out, err, rc = runner.run("adb", "-s", serial, "install", "-r", str(apks[0]))
        if rc != 0 or "Success" not in out:
            return finished(sha, ref, serial, directory, [
                built, Step("安装 + 启动", FAIL, "安装失败：" + output_detail(out + err))])

        note("启动")
        dumps = []
        ok, detail = judge_launch(*launch(runner, serial, land, sleep, dumps), land)
        steps = [built, Step("安装 + 启动", PASS if ok else FAIL, detail)]
        walked = []
        for name in screens:
            note("逐屏 %s" % name)
            runner.run("adb", "-s", serial, "shell", "am", "force-stop", PACKAGE)
            ok, detail = judge_launch(*launch(runner, serial, land, sleep, dumps, name), land)
            walked.append(Step(name, PASS if ok else FAIL, detail))
        return finished(sha, ref, serial, directory, steps, walked, "".join(dumps))
    finally:
        if temporary:
            out, err, rc = runner.run("git", "push", "origin", "--delete", temporary)
            if rc != 0:
                note("临时分支 %s 没删掉（%s），手动删一下" % (temporary, first_line(err or out)))


def finished(sha, ref, serial, directory, steps, screens=(), logcat=""):
    report = Report(sha, ref, serial, steps, list(screens), logcat, directory)
    report.write()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="真机冒烟：CI 出 debug 包 → 装开发机 → 启动 → 报告")
    parser.add_argument("--serial", help="设备序列号；只连一台时可以省")
    parser.add_argument("--ref", help="分支，默认 %s；标签与提交用 --commit" % DEFAULT_REF)
    parser.add_argument("--commit", help="指定提交或标签（SHA / 短 SHA / 分支名 / tag），会推一个临时分支")
    parser.add_argument("--screens", nargs="?", const=",".join(DEFAULT_SCREENS), metavar="页面",
                        help="把 demo 逐屏走一遍并逐页判存活；不给值就是全部页面，逗号分隔")
    parser.add_argument("--root", help="产物父目录，默认 %s" % DEFAULT_ROOT)
    args = parser.parse_args(argv)
    use_utf8_console()
    screens = tuple(name for name in (args.screens or "").split(",") if name)
    try:
        report = smoke(Runner(), ref=args.ref, commit=args.commit, serial=args.serial,
                       screens=screens, root=Path(args.root) if args.root else None)
    except SmokeError as error:
        print("跑不了：%s" % error, file=sys.stderr)
        return 2
    print(report.text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
