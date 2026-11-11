"""真机冒烟 1/3（android/smoke.py）：CI 出包 → 装机 → 启动 → 报告。

外部命令全由 fixtures 的 FakeRunner 回答，这里不碰 git、gh 与 adb。断言落在脚本实际发出的
命令序列、两段判定（构建 / 安装 + 启动）与报告文本上，不读内部结构。
"""
import importlib.util
import json
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


def base_table(target, conclusion="success"):
    return {
        ("git", "fetch", "origin", "main"): [("", "", 0)],
        ("git", "rev-parse", "origin/main"): [(SHA + "\n", "", 0)],
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
    table[adb("shell", "am", "start", "-n", smoke.ACTIVITY)] = [("Starting: Intent { cmp=... }\n", "", 0)]
    table[adb("shell", "pidof", smoke.PACKAGE)] = [pidof]
    table[adb("logcat", "-d")] = [logcat]
    return table


def list_key(branch):
    return ("gh", "run", "list", "--workflow", WORKFLOW, "--branch", branch,
            "--limit", "20", "--json", "databaseId,headSha")


def dispatch_key(ref):
    return ("gh", "workflow", "run", WORKFLOW, "-R", REPO, "--ref", ref)


def view_key():
    return ("gh", "run", "view", str(RUN_ID), "-R", REPO, "--json", "status,conclusion")


def download_key(target):
    return ("gh", "run", "download", str(RUN_ID), "-R", REPO, "-n", smoke.ARTIFACT, "-D", str(target))


def install_key(target):
    return adb("install", "-r", str(target / APK))


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
        self.assertTrue(callable(smoke.main), "android/smoke.py 要能当命令跑")
        self.assertTrue(callable(smoke.smoke), "编排入口要能注入执行器")
        text = (ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        self.assertIn("upload-artifact", text)
        self.assertIn("name: " + smoke.ARTIFACT, text)
        self.assertIn("*.apk", text)


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

    # —— 两段判定 ——

    def test_happy_path_passes_both_segments(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, launched(target))
        self.assertTrue(report.ok, report.text())
        self.assertEqual([step.name for step in report.steps], ["构建", "安装 + 启动"])
        self.assertIn("构建：通过", report.text())
        self.assertIn("安装 + 启动：通过", report.text())
        self.assertTrue(report.text().strip().endswith(str(target)), "摘要末尾要给出产物目录")

    def test_build_failure_stops_before_install(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, base_table(target, conclusion="failure"))
        self.assertFalse(report.ok)
        self.assertIn("构建：失败", report.text())
        self.assertIn("安装 + 启动：未执行", report.text())
        self.assertFalse([call for call in self.calls(runner) if call[0] == "adb"],
                         "构建失败后不该再碰手机")

    def test_build_timeout_is_reported_as_build_failure(self):
        root, target = self.workdir()
        table = base_table(target)
        table[view_key()] = [(json.dumps({"status": "in_progress", "conclusion": ""}), "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertIn("构建：失败", report.text())
        self.assertIn("没跑完", report.text())
        self.assertFalse([call for call in self.calls(runner) if call[0] == "adb"])

    def test_install_failure_is_reported_and_launch_not_attempted(self):
        root, target = self.workdir()
        table = launched(target)
        table[install_key(target)] = [
            ("adb: failed to install app-debug.apk: Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n", "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertFalse(report.ok)
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("INSTALL_FAILED_UPDATE_INCOMPATIBLE", report.text())
        self.assertNotIn(adb("shell", "am", "start", "-n", smoke.ACTIVITY), self.calls(runner))

    def test_missing_apk_after_download_is_an_install_failure(self):
        root, target = self.workdir()
        table = base_table(target)
        table[download_key(target)] = [("", "", 0)]
        report, runner, notes = self.run_smoke(root, table)
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("没找到 APK", report.text())
        self.assertNotIn(adb("shell", "am", "start", "-n", smoke.ACTIVITY), self.calls(runner))

    def test_dead_process_is_a_launch_failure(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, launched(target, pidof=("", "", 1)))
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("进程不在", report.text())

    def test_fatal_in_logcat_is_a_launch_failure_even_when_process_survived(self):
        logcat = ("01-01 00:00:03.000  4321  4321 E AndroidRuntime: FATAL EXCEPTION: main\n"
                  "01-01 00:00:03.000  4321  4321 E AndroidRuntime: java.lang.RuntimeException: boom\n")
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, launched(target, logcat=(logcat, "", 0)))
        self.assertIn("安装 + 启动：失败", report.text())
        self.assertIn("FATAL EXCEPTION", report.text())
        self.assertIn("FATAL EXCEPTION", (target / "logcat.txt").read_text(encoding="utf-8"))

    # —— 命令序列 ——

    def test_command_sequence_for_the_default_ref(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, launched(target))
        self.assertTrue(report.ok, report.text())
        self.assertEqual(self.calls(runner), [
            list_key("main"),                     # 触发之前先记下已有的 run
            dispatch_key("main"),
            list_key("main"),                     # 触发之后等新的那条
            view_key(),
            download_key(target),
            install_key(target),
            adb("logcat", "-c"),
            adb("shell", "am", "start", "-n", smoke.ACTIVITY),
            adb("shell", "pidof", smoke.PACKAGE),
            adb("logcat", "-d"),
        ])

    def test_commit_goes_through_a_temporary_branch_and_cleans_it_up(self):
        root, target = self.workdir()
        branch = "smoke/" + SHORT
        table = launched(target)
        for key in (("git", "fetch", "origin", "main"), ("git", "rev-parse", "origin/main"), list_key("main"),
                    dispatch_key("main")):
            del table[key]
        table[("git", "rev-parse", "--verify", SHA + "^{commit}")] = [(SHA + "\n", "", 0)]
        table[("git", "push", "origin", SHA + ":refs/heads/" + branch)] = [("", "", 0)]
        table[list_key(branch)] = [('[{"databaseId": 111}]', "", 0),
                                   ('[{"databaseId": %d, "headSha": "%s"}]' % (RUN_ID, SHA), "", 0)]
        table[dispatch_key(branch)] = [("", "", 0)]
        table[("git", "push", "origin", "--delete", branch)] = [("", "", 0)]
        report, runner, notes = self.run_smoke(root, table, commit=SHA)
        self.assertTrue(report.ok, report.text())
        calls = self.calls(runner)
        self.assertIn(("git", "push", "origin", SHA + ":refs/heads/" + branch), calls)
        self.assertEqual(calls[-1], ("git", "push", "origin", "--delete", branch), "临时分支用完要删")
        self.assertIn(branch, report.text())

    def test_a_failed_build_still_deletes_the_temporary_branch(self):
        root, target = self.workdir()
        branch = "smoke/" + SHORT
        table = base_table(target, conclusion="failure")
        for key in (("git", "fetch", "origin", "main"), ("git", "rev-parse", "origin/main"), list_key("main"),
                    dispatch_key("main")):
            del table[key]
        table[("git", "rev-parse", "--verify", SHA + "^{commit}")] = [(SHA + "\n", "", 0)]
        table[("git", "push", "origin", SHA + ":refs/heads/" + branch)] = [("", "", 0)]
        table[list_key(branch)] = [('[{"databaseId": 111}]', "", 0),
                                   ('[{"databaseId": %d, "headSha": "%s"}]' % (RUN_ID, SHA), "", 0)]
        table[dispatch_key(branch)] = [("", "", 0)]
        table[("git", "push", "origin", "--delete", branch)] = [("", "", 0)]
        report, runner, notes = self.run_smoke(root, table, commit=SHA)
        self.assertIn("构建：失败", report.text())
        self.assertEqual(self.calls(runner)[-1], ("git", "push", "origin", "--delete", branch))

    # —— 预检 ——

    def test_no_device_stops_before_ci(self):
        root, target = self.workdir()
        runner = FakeRunner(runs=Replies({("adb", "devices"): [("List of devices attached\n", "", 0)]}))
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertIn("没有连着手机", str(caught.exception))
        self.assertEqual(self.calls(runner), [("adb", "devices")], "没设备时不该触发 CI")

    def test_several_devices_ask_for_a_serial(self):
        root, target = self.workdir()
        two = "List of devices attached\nAAA\tdevice\nBBB\tdevice\n"
        runner = FakeRunner(runs=Replies({("adb", "devices"): [(two, "", 0)]}))
        with self.assertRaises(smoke.SmokeError) as caught:
            smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertIn("--serial", str(caught.exception))

    def test_single_device_is_picked_automatically(self):
        root, target = self.workdir()
        table = launched(target)
        table[("adb", "devices")] = [("List of devices attached\n%s\tdevice\n" % SERIAL, "", 0)]
        runner = FakeRunner(runs=Replies(table))
        report = smoke.smoke(runner, sleep=lambda seconds: None, note=lambda line: None, root=root)
        self.assertTrue(report.ok, report.text())
        self.assertEqual(self.calls(runner)[0], ("adb", "devices"))
        self.assertIn(SERIAL, report.text())

    # —— 逐屏 ——

    def screens_table(self, target, names, alive):
        table = launched(target)
        for name in names:
            table[adb("shell", "am", "force-stop", smoke.PACKAGE)] = [("", "", 0)]
            table[adb("shell", "am", "start", "-n", smoke.ACTIVITY, "--es", "demo", name)] = [("Starting\n", "", 0)]
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
            adb("shell", "am", "start", "-n", smoke.ACTIVITY, "--es", "demo", "home"),
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
        report, runner, notes = self.run_smoke(root, launched(target))
        self.assertEqual(report.screens, [])
        self.assertNotIn("逐屏", report.text())

    # —— 报告 ——

    def test_result_files_land_in_the_temporary_directory(self):
        root, target = self.workdir()
        report, runner, notes = self.run_smoke(root, launched(target))
        self.assertTrue((target / "report.md").exists())
        self.assertTrue((target / "logcat.txt").exists())
        data = json.loads((target / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(data["sha"], SHA)
        self.assertTrue(data["ok"])
        self.assertEqual([step["name"] for step in data["steps"]], ["构建", "安装 + 启动"])
        self.assertEqual((target / "report.md").read_text(encoding="utf-8").strip(), report.text().strip())
