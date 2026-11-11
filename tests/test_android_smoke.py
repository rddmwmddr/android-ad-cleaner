"""真机冒烟 2/3（android/smoke.py）：CI 出包 → 装机 → 启动 → 跑执行段 → 还原 → 报告。

外部命令全由 fixtures 的 FakeRunner 回答，这里不碰 git、gh 与 adb。断言落在脚本实际发出的
命令序列（双次启动、还原三项各一条、只重试一次、未就绪不触发 CI）、三段判定、报告文本与
两个纯函数（状态 JSON → 计划 JSON、logcat 分块 → 结果 JSON）上，不读内部结构。
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import FakeRunner

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("android_smoke", ROOT / "android" / "smoke.py")
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

SHA = "0123456789abcdef0123456789abcdef01234567"
SHORT = SHA[:12]
SERIAL = "ABC123"
REPO = smoke.REPO
WORKFLOW = smoke.WORKFLOW
RUN_ID = 42948451788
APK = "app-debug.apk"

RUN_PY = smoke.tool("run.py")
CHAN_PY = smoke.tool("chan_fast.py")
STATUS_CMD = RUN_PY + ("-s", SERIAL, "status-json")
TAG_LOGCAT = ("adb", "-s", SERIAL, "logcat", "-d", "-s", smoke.SMOKE_TAG + ":I")
RUN_AS = ("adb", "-s", SERIAL, "exec-out", "run-as", smoke.PACKAGE)


def status_json(**over):
    """手机状态 JSON：段名、广告包、快应用都从这台手机现在的情况来（#1072）。"""
    data = {
        "info": {"model": "PJD110", "brand": "OnePlus"},
        "locked": False, "recipe": "recipes/OPPO-ColorOS/PJD110.py", "recipe_ref": False,
        "steps": ["系统广告", "负一屏与搜索"],
        "ads": [{"pkg": "com.opos.ads", "suspended": False},
                {"pkg": "com.heytap.pictorial", "suspended": False}],
        "quickapps": [{"pkg": "com.nearme.instant.platform", "name": "快应用服务",
                       "closed": False, "keep": False}],
    }
    data.update(over)
    return data


def after_run(**over):
    return status_json(ads=[{"pkg": "com.opos.ads", "suspended": True},
                            {"pkg": "com.heytap.pictorial", "suspended": True}], **over)


def result(titles=("系统广告", "负一屏与搜索")):
    return [{"title": title, "rc": 0, "skipped": False, "sec": 3, "summary": "关了 12 个开关"}
            for title in titles]


def export(shell="ready", finished=True, results=None, seq=1, running=None):
    """App 打到 logcat 里的导出：`<组号> <块号>/<块数> <内容>`，一行装不下就分块。"""
    payload = {"shell": shell, "finished": finished,
               "run": {"running": (not finished) if running is None else running, "cancel": False,
                       "results": [] if results is None and not finished
                       else (result() if results is None else results)}}
    text = json.dumps(payload, ensure_ascii=False)
    parts = [text[i:i + 3000] for i in range(0, len(text), 3000)]
    return "".join("11-12 10:00:00.000  1234  1234 I %s: %d %d/%d %s\n"
                   % (smoke.SMOKE_TAG, seq, i + 1, len(parts), part)
                   for i, part in enumerate(parts))


class Replies:
    """按命令回话：同一个命令给一串回答时按顺序用，用完后重复最后一条。

    回答可以是 (out, err, rc)，也可以是返回它的函数——下载那一步要靠它把 APK 落进目录。
    """

    def __init__(self, table):
        self.table = {tuple(key): list(value) for key, value in table.items()}

    def __call__(self, script, *args):
        cmd = (script,) + args
        if cmd not in self.table:
            raise AssertionError("没预料到的命令：%r" % (cmd,))
        queue = self.table[cmd]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return reply() if callable(reply) else reply


def adb(*args):
    return ("adb", "-s", SERIAL) + args


def start(*extra):
    return smoke.start_cmd(SERIAL, *extra)


def base_table(target, conclusion="success"):
    return {
        adb("shell", "pm", "path", smoke.PACKAGE): [("", "", 0)],   # 还没装 App：跳过配对检查
        list_key("main"): [('[{"databaseId": 111}]', "", 0),
                           ('[{"databaseId": %d, "headSha": "%s"}, {"databaseId": 111}]' % (RUN_ID, SHA), "", 0)],
        dispatch_key("main"): [("", "", 0)],
        view_key(): [(json.dumps({"status": "completed", "conclusion": conclusion}), "", 0)],
        download_key(target): [push_apk(target)],
    }


def launched(target, pidof=("4321\n", "", 0), logcat=("", "", 0)):
    table = base_table(target)
    table[install_key(target)] = [("Success\n", "", 0)]
    table[adb("logcat", "-c")] = [("", "", 0)]
    table[start()] = [("Starting: Intent { cmp=... }\n", "", 0)]
    table[adb("shell", "pidof", smoke.PACKAGE)] = [pidof]
    table[adb("logcat", "-d")] = [logcat]
    return table


def happy_table(target, installed=True, channels=True, export_replies=None, restore=None):
    """一条跑通的表：预检 → CI → 装机 → 启动 → 执行段 → 还原。"""
    table = launched(target)
    plan = smoke.plan_from_status(status_json())
    plan_cmd = smoke.plan_cmd(SERIAL, plan)
    table[STATUS_CMD] = [(json.dumps(status_json(), ensure_ascii=False), "", 0),
                         (json.dumps(after_run(), ensure_ascii=False), "", 0)]
    table[plan_cmd] = [("Starting: Intent { ... }\n", "", 0)]
    table[smoke.export_cmd(SERIAL)] = [("Starting: Intent { ... }\n", "", 0)]
    table[TAG_LOGCAT] = export_replies or [(export(), "", 0)]
    table[RUN_AS + ("ls", smoke.APP_BACKUPS)] = [
        ("PJD110-20261112-1010\nPJD110-gui\n", "", 0)] if channels else [("", "", 0)]
    table[RUN_AS + ("cat", smoke.APP_BACKUPS + "/PJD110-20261112-1010/channels.tsv")] = [
        ("# 包名\t渠道id\ncom.taobao.taobao\toffer\t优惠\t淘宝\n", "", 0)] if channels else [("", "", 1)]
    table[RUN_AS + ("cat", smoke.APP_BACKUPS + "/PJD110-gui/channels.tsv")] = [("", "", 1)]
    table[RUN_PY + ("-s", SERIAL, "unsuspend", "com.opos.ads", "com.heytap.pictorial")] = [("", "", 0)]
    table[RUN_PY + ("-s", SERIAL, "quickapp", "on")] = [("", "", 0)]
    table[CHAN_PY + ("-s", SERIAL, "on", str(target / "channels-restore.tsv"))] = [("", "", 0)]
    if restore:
        table.update(restore)
    table[adb("shell", "pm", "path", smoke.PACKAGE)] = [
        ("package:/data/app/x/base.apk\n", "", 0) if installed else ("", "", 0)]
    return table


def list_key(branch):
    return ("gh", "run", "list", "--workflow", WORKFLOW, "--branch", branch,
            "--event", "workflow_dispatch", "--limit", "20", "--json", "databaseId,headSha")


def dispatch_key(ref):
    return ("gh", "workflow", "run", WORKFLOW, "-R", REPO, "--ref", ref)


def view_key():
    return ("gh", "run", "view", str(RUN_ID), "-R", REPO, "--json", "status,conclusion")


def download_key(target):
    return ("gh", "run", "download", str(RUN_ID), "-R", REPO, "-n", smoke.ARTIFACT, "-D", str(target))


def install_key(target):
    return adb("install", "-r", str(target / APK))


def commit_table(target, branch, base=None, delete=("", "", 0)):
    """指定提交时的表：先 rev-parse 认提交、推临时分支，跑完删掉；其余部分沿用 base。"""
    table = base if base is not None else happy_table(target)
    del table[list_key("main")]
    del table[dispatch_key("main")]
    table[("git", "rev-parse", "--verify", SHA + "^{commit}")] = [(SHA + "\n", "", 0)]
    table[("git", "push", "origin", SHA + ":refs/heads/" + branch)] = [("", "", 0)]
    table[list_key(branch)] = [('[{"databaseId": 111}]', "", 0),
                               ('[{"databaseId": %d, "headSha": "%s"}]' % (RUN_ID, SHA), "", 0)]
    table[dispatch_key(branch)] = [("", "", 0)]
    table[("git", "push", "origin", "--delete", branch)] = [delete]
    return table


def push_apk(target):
    """gh run download 的假回答：把 APK 写进脚本要读的目录。"""

    def reply():
        target.mkdir(parents=True, exist_ok=True)
        (target / APK).write_bytes(b"PK\x03\x04")
        return ("", "", 0)

    return reply


class SmokeWorkflowTests(unittest.TestCase):
    """入口与 CI 产物是连着的：脚本按 ARTIFACT 这个名字下载，workflow 就用这个名字上传（#1071）。"""

    def test_entry_point_and_ci_artifact_are_wired(self):
        source = (ROOT / "android/smoke.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":', source, "脚本要能当命令跑")
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            with self.assertRaises(SystemExit) as exited:
                smoke.main(["--help"])
        self.assertEqual(exited.exception.code, 0)
        self.assertIn("--screens", printed.getvalue(), "命令行参数没接上")
        text = (ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        self.assertIn("upload-artifact", text)
        self.assertIn("name: " + smoke.ARTIFACT, text)
        self.assertIn("*.apk", text)
        self.assertIn("workflow_dispatch", text, "脚本靠 workflow_dispatch 触发，删了就触发不了")

    def test_screen_list_matches_the_demo_pages(self):
        text = (ROOT / "android/app/src/debug/java/com/ahuamiao/adcleaner/ui/Demo.kt").read_text(encoding="utf-8")
        pages = text[text.index("页面：") + len("页面："):text.index("面板：")].replace("*", " ").split()
        self.assertEqual(sorted(pages), sorted(smoke.DEFAULT_SCREENS),
                         "--screens 的默认名单要与 Demo.kt 的页面名同步")

    def test_the_debug_export_entry_matches_the_app(self):
        """导出入口只有一处：脚本发的 `--es call smoke` 与 debug 源集里认的那个值、日志标签一致（#1072）。"""
        debug = (ROOT / "android/app/src/debug/java/com/ahuamiao/adcleaner/ui/Demo.kt").read_text(encoding="utf-8")
        release = (ROOT / "android/app/src/release/java/com/ahuamiao/adcleaner/ui/Demo.kt").read_text(encoding="utf-8")
        model = (ROOT / "android/app/src/main/java/com/ahuamiao/adcleaner/ui/AppModel.kt").read_text(encoding="utf-8")
        view = (ROOT / "android/app/src/main/python/aac_android/view.py").read_text(encoding="utf-8")
        self.assertIn('getStringExtra("call") == "smoke"', debug)
        self.assertIn(smoke.SMOKE_TAG, model, "脚本按这个标签读 logcat")
        self.assertIn('"view.smoke_export"', model, "结果与分块在 view.py 里，判断不写进 Kotlin")
        self.assertIn('"smoke_export": smoke_export', view)
        self.assertNotIn("smoke", release, "发布包的入口是空壳")
        self.assertIn('"--es", "call", "smoke"', (ROOT / "android/smoke.py").read_text(encoding="utf-8"))


class PlanTests(unittest.TestCase):
    """状态 JSON → 计划 JSON：段名现算，写死的段名在脚本改名后会静默空跑（#1072）。"""

    def test_segments_and_targets_come_from_the_status(self):
        plan = smoke.plan_from_status(status_json())
        self.assertEqual(plan["steps"], ["系统广告", "负一屏与搜索"])
        self.assertEqual(plan["model"], "PJD110")
        self.assertEqual(plan["ads"], ["com.opos.ads", "com.heytap.pictorial"])
        self.assertTrue(plan["quickapp"])
        self.assertFalse(plan["ref"])
        self.assertTrue(plan["backup"])

    def test_reference_script_is_marked_as_reference(self):
        self.assertTrue(smoke.plan_from_status(status_json(recipe_ref=True))["ref"])

    def test_nothing_to_change_on_this_phone_is_left_out(self):
        plan = smoke.plan_from_status(status_json(
            steps=[], ads=[{"pkg": "com.opos.ads", "suspended": True}],
            quickapps=[{"pkg": "com.nearme.instant.platform", "closed": True},
                       {"pkg": "com.vivo.hybrid", "keep": True}]))
        self.assertEqual(plan["steps"], [], "这台机没有机型脚本时计划里不该有段名")
        self.assertEqual(plan["ads"], [], "已挂起的包不用再挂")
        self.assertFalse(plan["quickapp"], "没有可关的快应用组件")


class ExportTests(unittest.TestCase):
    """App 的导出按块打在 logcat 里：一行约 4 KB 就截断，整份结果装不进一行（#1072）。"""

    def test_chunks_are_reassembled(self):
        text = export(results=result(titles=["第 %d 项" % i for i in range(80)]))
        self.assertGreater(len(text.splitlines()), 1, "这份导出要真的被分成多块")
        seq, blob = smoke.parse_export(text)
        self.assertEqual(seq, 1)
        self.assertTrue(blob["finished"])
        self.assertEqual(len(blob["run"]["results"]), 80)

    def test_the_latest_complete_export_wins(self):
        text = export(finished=False, seq=1) + export(finished=True, seq=2)
        self.assertTrue(smoke.parse_export(text)[1]["finished"])

    def test_an_incomplete_export_is_not_guessed(self):
        text = export().splitlines()
        self.assertIsNone(smoke.parse_export("\n".join(text[:-1])), "缺块时不能拼出半份")

    def test_non_smoke_lines_are_ignored(self):
        self.assertIsNone(smoke.parse_export("11-12 10:00:00.000  1  1 I Other: hello\n"))


class RunnerTests(unittest.TestCase):
    """外部命令的两种常见失败要翻成 SmokeError（退出码 2「没跑起来」），不能抛栈。"""

    def test_missing_command_is_a_smoke_error(self):
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.Runner().run("aac-no-such-command-1071")
        self.assertIn("找不到命令", str(caught.exception))

    def test_timeout_is_a_smoke_error(self):
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.Runner().run(sys.executable, "-c", "import time; time.sleep(5)", timeout=0.2)
        self.assertIn("没返回", str(caught.exception))


class SmokeTests(unittest.TestCase):
    def workdir(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        return root, root / SHORT

    def run_smoke(self, root, table, **kwargs):
        runner = FakeRunner(runs=Replies(table))
        notes = []
        report = smoke.smoke(runner, serial=SERIAL, root=root,
                             sleep=lambda seconds: None, note=notes.append, **kwargs)
        return report, runner, notes

    def calls(self, runner):
        return [(call.script,) + call.args for call in runner.run_calls]

    def assert_no_adb_after_dispatch(self, runner):
        """触发 CI 之后不再碰手机：预检的 adb 在触发之前，不算在内。"""
        calls = self.calls(runner)
        at = calls.index(dispatch_key("main")) if dispatch_key("main") in calls else -1
        self.assertFalse([call for call in calls[at + 1:] if call[0] == "adb"],
                         "触发 CI 之后不该再碰手机")

    # —— 三段判定 ——

    def test_happy_path_passes_three_segments(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, happy_table(target))
        self.assertTrue(report.ok, report.text())
        self.assertEqual([step.name for step in report.steps], ["构建", "安装 + 启动", "真流程 + 还原"])
        self.assertIn("构建：通过", report.text())
        self.assertIn("安装 + 启动：通过", report.text())
        self.assertIn("真流程 + 还原：通过", report.text())
        self.assertIn("关了 2 项（只记录）", report.text())
        self.assertTrue(report.text().strip().endswith(str(target)), "摘要末尾要给出产物目录")

    def test_the_run_is_driven_by_the_status_json_not_hard_coded_segments(self):
        root, target = self.workdir()
        table = happy_table(target)
        other = status_json(steps=["主题", "浏览器"])
        table[STATUS_CMD] = [(json.dumps(other, ensure_ascii=False), "", 0),
                             (json.dumps(after_run(), ensure_ascii=False), "", 0)]
        table[smoke.plan_cmd(SERIAL, smoke.plan_from_status(other))] = [("Starting\n", "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertTrue(report.ok, report.text())
        prefix = smoke.start_cmd(SERIAL, "--es", "plan")
        sent = [call for call in self.calls(runner) if call[:len(prefix)] == prefix]
        self.assertEqual(len(sent), 2, "计划要按下发两次（冷启动第一次会被丢掉）")
        self.assertIn("主题", sent[0][-1])

    def test_a_failed_step_in_the_run_is_recorded_but_does_not_decide(self):
        root, target = self.workdir()
        results = result() + [{"title": "负一屏与搜索", "rc": 1, "skipped": False, "summary": "入口没找到"}]
        table = happy_table(target, export_replies=[(export(results=results), "", 0)])
        report, runner, notes = self.run_smoke(root, table)
        self.assertTrue(report.ok, "「没做成几项」只记录、不判定：" + report.text())
        self.assertIn("1 项没做成（只记录）", report.text())

    def test_build_failure_stops_before_install(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, base_table(target, conclusion="failure"))
        self.assertFalse(report.ok)
        self.assertIn("构建：失败", report.text())
        self.assertIn("安装 + 启动：未执行", report.text())
        self.assertIn("真流程 + 还原：未执行", report.text())
        self.assert_no_adb_after_dispatch(runner)

    def test_build_timeout_is_reported_as_build_failure(self):
        root, target = self.workdir()
        table = base_table(target)
        table[view_key()] = [(json.dumps({"status": "in_progress", "conclusion": ""}), "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertIn("构建：失败", report.text())
        self.assertIn("没跑完", report.text())
        self.assert_no_adb_after_dispatch(runner)

    def test_install_failure_is_reported_and_launch_not_attempted(self):
        root, target = self.workdir()
        table = happy_table(target, installed=False)
        table[install_key(target)] = [
            ("Performing Streamed Install\n"
             "adb: failed to install app-debug.apk: Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n", "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertFalse(report.ok)
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("INSTALL_FAILED_UPDATE_INCOMPATIBLE", report.text(),
                      "adapter 的进度行不能把真正的原因挤掉")
        self.assertIn("Performing Streamed Install", report.text())
        self.assertIn("真流程 + 还原：未执行", report.text())
        self.assertNotIn(start(), self.calls(runner))

    def test_missing_apk_after_download_is_an_install_failure(self):
        root, target = self.workdir()
        table = base_table(target)
        table[download_key(target)] = [("", "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("下载 APK 失败", report.text())
        self.assertNotIn(start(), self.calls(runner))

    def test_download_failure_does_not_reuse_a_stale_apk(self):
        root, target = self.workdir()
        target.mkdir(parents=True, exist_ok=True)
        (target / APK).write_bytes(b"stale")          # 上一次跑留下的包
        table = base_table(target)
        table[download_key(target)] = [("gh: artifact expired\n", "", 1)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("下载 APK 失败", report.text())
        self.assertNotIn(install_key(target), self.calls(runner), "本次没下到包就不能装")

    def test_dead_process_is_a_launch_failure(self):
        root, target = self.workdir()
        table = happy_table(target)
        table[adb("shell", "pidof", smoke.PACKAGE)] = [("", "", 1)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("进程不在", report.text())
        self.assertIn("真流程 + 还原：未执行", report.text())

    def test_fatal_in_logcat_is_a_launch_failure_even_when_process_survived(self):
        logcat = ("01-01 00:00:03.000  4321  4321 E AndroidRuntime: FATAL EXCEPTION: main\n"
                  "01-01 00:00:03.000  4321  4321 E AndroidRuntime: Process: %s, PID: 4321\n"
                  "01-01 00:00:03.000  4321  4321 E AndroidRuntime: java.lang.RuntimeException: boom\n"
                  % smoke.PACKAGE)
        root, target = self.workdir()
        table = happy_table(target)
        table[adb("logcat", "-d")] = [(logcat, "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("FATAL EXCEPTION", report.text())
        self.assertIn("FATAL EXCEPTION", (target / "logcat.txt").read_text(encoding="utf-8"))

    def test_another_apps_crash_in_the_same_window_is_not_ours(self):
        logcat = ("01-01 00:00:03.000   999   999 E AndroidRuntime: FATAL EXCEPTION: main\n"
                  "01-01 00:00:03.000   999   999 E AndroidRuntime: Process: com.example.other, PID: 999\n")
        root, target = self.workdir()
        table = happy_table(target)
        table[adb("logcat", "-d")] = [(logcat, "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertTrue(report.ok, report.text())

    # —— 命令序列 ——

    def test_command_sequence_for_the_default_ref(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, happy_table(target))
        self.assertTrue(report.ok, report.text())
        plan = smoke.plan_cmd(SERIAL, smoke.plan_from_status(status_json()))
        self.assertEqual(self.calls(runner), [
            adb("shell", "pm", "path", smoke.PACKAGE),   # 开跑前判 App 的 shell 状态
            smoke.export_cmd(SERIAL),                    # 冷启动那次可能被丢掉
            TAG_LOGCAT,
            list_key("main"),                            # 触发之前先记下已有的 run
            dispatch_key("main"),
            list_key("main"),                            # 触发之后等新的那条
            view_key(),
            download_key(target),
            install_key(target),
            adb("logcat", "-c"),
            start(),                                     # 装完先验证能起来
            adb("shell", "pidof", smoke.PACKAGE),
            adb("logcat", "-d"),
            STATUS_CMD,                                  # 段名现算
            plan,
            plan,                                        # 冷启动丢 intent：固定发两次
            smoke.export_cmd(SERIAL),                    # 让 App 开始导执行结果
            TAG_LOGCAT,
            adb("logcat", "-d"),
            STATUS_CMD,                                  # 还原要看跑完之后挂起了什么
            RUN_AS + ("ls", smoke.APP_BACKUPS),           # 渠道清单在 App 私有目录里
            RUN_AS + ("cat", smoke.APP_BACKUPS + "/PJD110-gui/channels.tsv"),
            RUN_AS + ("cat", smoke.APP_BACKUPS + "/PJD110-20261112-1010/channels.tsv"),
            RUN_PY + ("-s", SERIAL, "unsuspend", "com.opos.ads", "com.heytap.pictorial"),
            RUN_PY + ("-s", SERIAL, "quickapp", "on"),
            CHAN_PY + ("-s", SERIAL, "on", str(target / "channels-restore.tsv")),
        ])

    def test_restore_runs_one_command_per_item_and_reports_each(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, happy_table(target))
        self.assertEqual([step.name for step in report.restore],
                         ["还原 挂起的包", "还原 快应用组件", "还原 营销通知渠道"])
        self.assertTrue(all(step.ok for step in report.restore), report.text())

    def test_restore_retries_once_then_stops(self):
        root, target = self.workdir()
        table = happy_table(target, restore={
            RUN_PY + ("-s", SERIAL, "quickapp", "on"): [("", "挂起被系统拒绝\n", 1)],
        })
        report, runner, notes = self.run_smoke(root, table)
        self.assertFalse(report.ok)
        calls = self.calls(runner)
        quick = [call for call in calls if call == RUN_PY + ("-s", SERIAL, "quickapp", "on")]
        self.assertEqual(len(quick), 2, "失败只重试一次")
        self.assertNotIn(CHAN_PY + ("-s", SERIAL, "on", str(target / "channels-restore.tsv")), calls,
                         "仍失败就停手，不继续下一项")
        self.assertIn("设备可能残留改动", report.text())
        self.assertIn("真流程 + 还原：失败", report.text())

    def test_a_channels_list_that_cannot_be_read_is_not_reported_as_nothing_to_restore(self):
        """读不到 App 私有目录是失败，不能记成「本来就没有清单」的通过（#1072）。"""
        root, target = self.workdir()
        table = happy_table(target, restore={
            RUN_AS + ("ls", smoke.APP_BACKUPS): [("", "run-as: package not debuggable\n", 1)],
        })
        report, runner, notes = self.run_smoke(root, table)
        self.assertFalse(report.ok)
        channels = [step for step in report.restore if step.name == "还原 营销通知渠道"][0]
        self.assertFalse(channels.ok)
        self.assertIn("读不到 App 私有目录", channels.detail)
        self.assertIn("设备可能残留改动", report.text())
        self.assertNotIn(CHAN_PY + ("-s", SERIAL, "on", str(target / "channels-restore.tsv")),
                         self.calls(runner))

    def test_a_run_still_going_blocks_restore_and_screens(self):
        """导出停住但引擎还在跑：这时还原 / 强停会和执行抢同一块屏，停手并如实说（沿用 #662 的互斥）。"""
        root, target = self.workdir()
        table = happy_table(target, export_replies=[(export(finished=False), "", 0)])
        report, runner, notes = self.run_smoke(root, table, screens=("home",))
        self.assertFalse(report.ok)
        self.assertIn("执行还在跑", report.text())
        calls = self.calls(runner)
        self.assertNotIn(RUN_PY + ("-s", SERIAL, "unsuspend", "com.opos.ads", "com.heytap.pictorial"), calls,
                         "引擎还在跑时不该去还原")
        self.assertNotIn(adb("shell", "am", "force-stop", smoke.PACKAGE), calls, "也不该强停进程")
        self.assertEqual(report.screens, [])

    def test_a_run_that_never_starts_is_reported_as_a_failed_segment(self):
        root, target = self.workdir()
        table = happy_table(target, export_replies=[
            (export(finished=False, shell="ready", running=False), "", 0)])
        report, runner, notes = self.run_smoke(root, table)
        self.assertFalse(report.ok)
        self.assertIn("真流程 + 还原：失败", report.text())
        self.assertIn("没有跑起来", report.text())
        self.assertTrue(report.restore, "执行段没起来也要还原，别把手机留在半截状态")
        prefix = smoke.start_cmd(SERIAL, "--es", "plan")
        plans = [call for call in self.calls(runner) if call[:len(prefix)] == prefix]
        self.assertGreaterEqual(len(plans), 3, "导出停住时要把计划连同导出入口再发一次")

    def test_commit_goes_through_a_temporary_branch_and_cleans_it_up(self):
        root, target = self.workdir()
        branch = "smoke/" + SHORT
        report, runner, notes = self.run_smoke(root, commit_table(target, branch), commit=SHA)
        self.assertTrue(report.ok, report.text())
        calls = self.calls(runner)
        self.assertIn(("git", "push", "origin", SHA + ":refs/heads/" + branch), calls)
        self.assertEqual(calls[-1], ("git", "push", "origin", "--delete", branch), "临时分支用完要删")
        self.assertIn(branch, report.text())

    def test_a_failed_build_still_deletes_the_temporary_branch(self):
        root, target = self.workdir()
        branch = "smoke/" + SHORT
        table = commit_table(target, branch, base=base_table(target, conclusion="failure"))
        report, runner, notes = self.run_smoke(root, table, commit=SHA)
        self.assertIn("构建：失败", report.text())
        self.assertEqual(self.calls(runner)[-1], ("git", "push", "origin", "--delete", branch))

    def test_a_branch_that_cannot_be_deleted_is_reported(self):
        root, target = self.workdir()
        branch = "smoke/" + SHORT
        table = commit_table(target, branch, delete=("", "remote: permission denied\n", 1))
        report, runner, notes = self.run_smoke(root, table, commit=SHA)
        self.assertTrue(report.ok, "删临时分支失败不该把结论改成失败")
        self.assertTrue(any("没删掉" in line and branch in line for line in notes), notes)

    # —— 预检 ——

    def test_no_device_stops_before_ci(self):
        root, target = self.workdir()
        runner = FakeRunner(runs=Replies({("adb", "devices"): [("List of devices attached\n", "", 0)]}))
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertIn("没有可用的手机", str(caught.exception))
        self.assertEqual(self.calls(runner), [("adb", "devices")], "没设备时不该触发 CI")

    def test_an_unauthorized_device_says_so(self):
        root, target = self.workdir()
        listed = "List of devices attached\nAAA\tunauthorized\n"
        runner = FakeRunner(runs=Replies({("adb", "devices"): [(listed, "", 0)]}))
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertIn("unauthorized", str(caught.exception), "要把设备状态说出来，别只说没连手机")

    def test_several_devices_ask_for_a_serial(self):
        root, target = self.workdir()
        two = "List of devices attached\nAAA\tdevice\nBBB\tdevice\n"
        runner = FakeRunner(runs=Replies({("adb", "devices"): [(two, "", 0)]}))
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertIn("--serial", str(caught.exception))

    def test_single_device_is_picked_automatically(self):
        root, target = self.workdir()
        table = happy_table(target, installed=False)
        table[("adb", "devices")] = [("List of devices attached\n%s\tdevice\n" % SERIAL, "", 0)]
        runner = FakeRunner(runs=Replies(table))
        report = smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertTrue(report.ok, report.text())
        self.assertEqual(self.calls(runner)[0], ("adb", "devices"))
        self.assertIn(SERIAL, report.text())

    def test_an_app_that_cannot_run_shell_stops_before_ci(self):
        """配对失效时触发 CI 只会白等一轮，跑出来的「执行失败」也不是代码的问题（#1072）。"""
        root, target = self.workdir()
        table = {("adb", "devices"): [("List of devices attached\n%s\tdevice\n" % SERIAL, "", 0)],
                 adb("shell", "pm", "path", smoke.PACKAGE): [("package:/data/app/x.apk\n", "", 0)],
                 smoke.export_cmd(SERIAL): [("Starting\n", "", 0)],
                 TAG_LOGCAT: [(export(shell="need_pair", finished=False), "", 0)]}
        runner = FakeRunner(runs=Replies(table))
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertIn("need_pair", str(caught.exception))
        self.assertIn("没有触发 CI", str(caught.exception))
        self.assertFalse([call for call in self.calls(runner) if call[0] == "gh"])

    def test_an_app_that_is_not_installed_yet_is_not_a_precheck_failure(self):
        root, target = self.workdir()
        table = happy_table(target, installed=False, channels=False)
        report, runner, notes = self.run_smoke(root, table)
        self.assertTrue(report.ok, report.text())
        self.assertTrue(any("还没装这个 App" in line for line in notes), notes)

    def test_an_older_debug_build_without_the_entry_does_not_block_the_run(self):
        """≤#1071 的调试包没有导出入口；这轮装完才有，不能因为读不到就拦下整轮（#1072）。"""
        runner = FakeRunner(runs=Replies({
            adb("shell", "pm", "path", smoke.PACKAGE): [("package:/data/app/x.apk\n", "", 0)],
            smoke.export_cmd(SERIAL): [("Starting\n", "", 0)],
            TAG_LOGCAT: [("", "", 0)],
        }))
        notes = []
        smoke.check_shell(runner, SERIAL, sleep=lambda seconds: None, note=notes.append)
        self.assertTrue(any("跳过配对检查" in line for line in notes), notes)

    # —— 逐屏 ——

    def screens_table(self, target, names, alive):
        table = happy_table(target)
        for name in names:
            table[adb("shell", "am", "force-stop", smoke.PACKAGE)] = [("", "", 0)]
            table[start("--es", "demo", name)] = [("Starting\n", "", 0)]
        table[adb("shell", "pidof", smoke.PACKAGE)] = [("4321\n", "", 0)] + list(alive)
        return table

    def test_screens_force_stop_between_pages_and_judge_each(self):
        root, target = self.workdir()
        table = self.screens_table(target, ("home", "choose"), [("4321\n", "", 0)])
        report, runner, notes = self.run_smoke(root, table, screens=("home", "choose"))
        self.assertTrue(report.ok, report.text())
        self.assertEqual([step.name for step in report.screens], ["home", "choose"])
        calls = self.calls(runner)
        at = calls.index(adb("shell", "am", "force-stop", smoke.PACKAGE))
        self.assertEqual(calls[at:at + 5], [
            adb("shell", "am", "force-stop", smoke.PACKAGE),
            adb("logcat", "-c"),
            start("--es", "demo", "home"),
            adb("shell", "pidof", smoke.PACKAGE),
            adb("logcat", "-d"),
        ])

    def test_a_crashing_screen_fails_the_report_but_the_walk_continues(self):
        root, target = self.workdir()
        table = self.screens_table(target, ("home", "done"), [("", "", 1), ("4321\n", "", 0)])
        report, runner, notes = self.run_smoke(root, table, screens=("home", "done"))
        self.assertFalse(report.ok)
        self.assertEqual([(step.name, step.ok) for step in report.screens], [("home", False), ("done", True)])
        self.assertIn("home", report.text())

    def test_screens_are_off_by_default(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, happy_table(target))
        self.assertEqual(report.screens, [])
        self.assertNotIn("逐屏", report.text())

    # —— 报告 ——

    def test_result_files_land_in_the_temporary_directory(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, happy_table(target))
        self.assertTrue((target / "report.md").exists())
        self.assertTrue((target / "logcat.txt").exists())
        data = json.loads((target / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(data["sha"], SHA)
        self.assertTrue(data["ok"])
        self.assertEqual([step["name"] for step in data["steps"]],
                         ["构建", "安装 + 启动", "真流程 + 还原"])
        self.assertEqual([step["name"] for step in data["restore"]],
                         ["还原 挂起的包", "还原 快应用组件", "还原 营销通知渠道"])
        self.assertEqual((target / "report.md").read_text(encoding="utf-8").strip(), report.text().strip())

    def test_the_raw_result_is_written_next_to_the_report(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, happy_table(target))
        raw = json.loads((target / "run.json").read_text(encoding="utf-8"))
        self.assertEqual([item["title"] for item in raw["results"]], ["系统广告", "负一屏与搜索"])
        self.assertNotIn("lines", raw, "导出只留执行结果，日志走 logcat")
