"""诊断报告的「执行结果」栏要写实际记下的跳过原因，不是一律「读屏服务被占用」（#603）。

跳过有两源：读屏服务仍被占用、手机中途从 adb 上消失。两种都在跳过时把原因随结果记了下来
（`results[].tail`），这里守的是报告取的是那一行，而不是按 `skipped` 猜。
"""
import json
import tempfile
import unittest
from unittest.mock import patch

from fixtures import FakeProc, FakeRunner, job_stub
from gui import app


def event(kind):
    return '#aac:event ' + json.dumps({"kind": kind})


class SkipReasonReportTests(unittest.TestCase):
    def report(self, procs, tasks, adb=True):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory, runner=FakeRunner(spawns=procs))
            api.job = job_stub(serial="TESTSERIAL01")
            with patch.object(app, "adb_present", return_value=adb):
                api._work(tasks)
            return api.diagnostics()

    def test_busy_skip_names_the_screen_reader(self):
        text = self.report(
            [FakeProc(event("ui_busy") + "\nUIAUTOMATION_BUSY：已占用\n", rc=1), FakeProc()],
            [app.Task("广告开关", "run.py", uses_ui=True),
             app.Task("通知", "chan_fast.py", uses_ui=True)])
        self.assertIn("- 通知：跳过（读屏服务仍被占用，跳过本步骤），0 秒", text)

    def test_link_lost_skip_does_not_blame_the_screen_reader(self):
        text = self.report(
            [FakeProc(event("link_lost") + "\n手机和电脑的 adb 连接断开了\n", rc=1)],
            [app.Task("广告开关", "run.py"), app.Task("收尾", "run.py")], adb=False)
        self.assertIn("- 收尾：跳过（手机和电脑已断开，这一步没有执行），0 秒", text)
        self.assertNotIn("读屏服务", text)

    def test_skip_without_a_recorded_reason_stays_neutral(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory, runner=FakeRunner())
            api.job = job_stub(serial="TESTSERIAL01", results=[
                {"title": "关闭营销通知", "rc": 3, "sec": 0, "skipped": True}])
            text = api.diagnostics()
        self.assertIn("- 关闭营销通知：跳过，0 秒", text)
        self.assertNotIn("跳过（", text)


if __name__ == "__main__":
    unittest.main()
