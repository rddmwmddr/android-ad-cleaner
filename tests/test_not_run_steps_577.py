"""#577：选择页上有、这次没有执行的项，也要在执行结果里留一行，说清是没勾还是本来就没有。

以前计划里只放勾选的项，未勾的项在结果里整行不存在：跑完四步全「成功」，用户以为该做的都做了。
这一行不参与失败判定（rc=0），只让「全部成功」不再盖住没做的事。
"""
import json
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import tempfile
import unittest
from unittest.mock import patch

from fixtures import FakeProc, FakeRunner, job_stub
from gui import app

PREFIX = "#aac:event "


def event(kind):
    return PREFIX + json.dumps({"kind": kind})


def offered(steps=("桌面",), quickapps=(), ads=(), channels=None):
    """选择页上摆出来的项。channels=None 表示通知没扫成。"""
    return {"steps": list(steps), "quickapps": list(quickapps), "ads": list(ads), "channels": channels}


class PlanTasksTests(unittest.TestCase):
    def reason_of(self, tasks, title):
        return next(t.skip_reason for t in tasks if t.title == title)

    def test_unchecked_recipe_gets_a_row_saying_it_was_not_ticked(self):
        tasks = app.plan_tasks("S", {"backup": False}, offered())
        self.assertEqual(self.reason_of(tasks, "关闭各 App 里的广告开关"), "未勾选，本次没有执行")

    def test_a_phone_without_a_recipe_says_so_instead_of_not_ticked(self):
        tasks = app.plan_tasks("S", {"backup": False}, offered(steps=()))
        self.assertEqual(tasks[0].skip_reason, "没有专用脚本，这一步要照清单手动做")

    def test_partly_ticked_segments_show_how_many_ran(self):
        tasks = app.plan_tasks("S", {"backup": False, "steps": ["桌面"]}, offered(steps=("桌面", "浏览器", "商店")))
        self.assertEqual(tasks[0].title, "关闭各 App 里的广告开关（1 / 3 段）")
        self.assertEqual(tasks[0].skip_reason, "")

    def test_all_segments_ticked_keep_the_plain_title(self):
        tasks = app.plan_tasks("S", {"backup": False, "steps": ["桌面", "浏览器"]}, offered(steps=("桌面", "浏览器")))
        self.assertEqual(tasks[0].title, "关闭各 App 里的广告开关")

    def test_channels_are_told_apart_unchecked_from_none_found(self):
        unchecked = app.plan_tasks("S", {"backup": False}, offered(channels=[{"pkg": "p", "id": "1", "name": "活动"}]))
        none = app.plan_tasks("S", {"backup": False}, offered(channels=[]))
        unscanned = app.plan_tasks("S", {"backup": False}, offered(channels=None))
        self.assertEqual(self.reason_of(unchecked, "关闭营销通知"), "未勾选，本次没有执行")
        self.assertEqual(self.reason_of(none, "关闭营销通知"), "没有扫描到可关闭的营销渠道")
        self.assertEqual(self.reason_of(unscanned, "关闭营销通知"), "通知扫描没有完成，本次没有关闭营销通知")

    def test_quickapp_and_ads_say_why_they_did_nothing(self):
        closed = app.plan_tasks("S", {"backup": False}, offered(quickapps=[{"name": "x", "closed": True}]))
        absent = app.plan_tasks("S", {"backup": False}, offered())
        hung = app.plan_tasks("S", {"backup": False}, offered(ads=[{"pkg": "p", "suspended": True}]))
        self.assertEqual(self.reason_of(closed, "关闭快应用"), "可关闭的快应用组件都已关闭")
        self.assertEqual(self.reason_of(absent, "关闭快应用"), "没有检测到快应用组件")
        self.assertEqual(self.reason_of(absent, "挂起广告组件"), "没有已知的广告组件")
        self.assertEqual(self.reason_of(hung, "挂起广告组件"), "广告组件已经挂起")

    def test_rows_keep_the_order_the_run_would_have_had(self):
        tasks = app.plan_tasks("S", {"backup": True}, offered())
        self.assertEqual([t.title for t in tasks],
                         ["存改动前的快照", "关闭各 App 里的广告开关", "关闭营销通知",
                          "关闭快应用", "挂起广告组件", "收尾"])

    def test_without_a_detection_nothing_is_claimed(self):
        # 没有检测结果就不知道选择页摆过什么，不能凭空说「没勾」
        self.assertEqual([t.title for t in app.plan_tasks("S", {"backup": False})], ["收尾"])


class WorkTests(unittest.TestCase):
    def make_api(self, **runner):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        api = app.Api(self._dir.name, runner=FakeRunner(**runner))
        api.job = job_stub()
        return api

    def skip_task(self, title="关闭营销通知", reason="未勾选，本次没有执行"):
        return app.Task(title, "", skip_reason=reason)

    def test_a_not_run_step_spawns_nothing_and_lands_as_skipped(self):
        api = self.make_api()
        api._work([self.skip_task(), app.Task("收尾", "run.py", ["-s", "t", "finish"])])
        self.assertEqual(len(api.runner.spawn_calls), 1, "没勾的项不该起子进程")
        first = api.job.results[0]
        self.assertEqual(first["rc"], 0, "没执行不算失败")
        self.assertTrue(first["skipped"])
        self.assertEqual(first["tail"], ["未勾选，本次没有执行"])

    def test_not_run_steps_stay_out_of_the_step_counter(self):
        api = self.make_api()
        api.job.total = 1
        api._work([self.skip_task(),
                   app.Task("收尾", "run.py", ["-s", "t", "finish"]),
                   self.skip_task("挂起广告组件")])
        self.assertEqual(api.job.idx, 1)
        self.assertEqual(api.job.title, "收尾")

    def test_a_lost_phone_keeps_each_not_run_step_its_own_reason(self):
        api = self.make_api(spawns=[FakeProc(event("link_lost") + "\n手机和电脑的 adb 连接断开了\n", rc=1)])
        with patch.object(app, "adb_present", return_value=False):
            api._work([app.Task("广告开关", "run.py"),
                       self.skip_task("关闭快应用"),
                       app.Task("收尾", "run.py")])
        self.assertEqual(api.job.results[1]["tail"], ["未勾选，本次没有执行"])


class StartTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def started_tasks(self, api, plan):
        with patch.object(app.threading, "Thread", autospec=True) as thread:
            api.start("S", plan)
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()
        return thread.call_args.kwargs["args"][0]

    def test_start_hands_the_detection_and_the_scan_to_the_planner(self):
        api = app.Api(self._dir.name, runner=FakeRunner())
        api.last_status = {"steps": ["桌面"], "quickapps": [], "ads": []}
        api.last_chans = []
        tasks = self.started_tasks(api, {"backup": False})
        self.assertEqual([t.title for t in tasks],
                         ["关闭各 App 里的广告开关", "关闭营销通知", "关闭快应用", "挂起广告组件", "收尾"])
        self.assertEqual(tasks[1].skip_reason, "没有扫描到可关闭的营销渠道")

    def test_start_counts_only_the_steps_that_run(self):
        api = app.Api(self._dir.name, runner=FakeRunner())
        api.last_status = {"steps": ["桌面"], "quickapps": [], "ads": []}
        api.last_chans = []
        with patch.object(app.threading, "Thread", autospec=True) as thread:
            result = api.start("S", {"backup": True})
        thread.assert_called_once()
        self.assertEqual(result["total"], 2, "只有备份和收尾会跑")

    def test_without_a_detection_start_adds_no_not_run_rows(self):
        api = app.Api(self._dir.name, runner=FakeRunner())
        tasks = self.started_tasks(api, {"backup": False})
        self.assertEqual([t.title for t in tasks], ["收尾"])

    def test_a_status_without_steps_is_not_a_full_detection(self):
        # 对拍驱动只塞了 info（tests/compare_api.py）：不能凭空多出四行，否则基线对不上
        api = app.Api(self._dir.name, runner=FakeRunner())
        api.last_status = {"info": {"brand": "Xiaomi"}}
        tasks = self.started_tasks(api, {"backup": False})
        self.assertEqual([t.title for t in tasks], ["收尾"])


class DiagnosticsTests(unittest.TestCase):
    def make_api(self, results):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        api = app.Api(self._dir.name, runner=FakeRunner())
        api.job = job_stub(results=results)
        return api

    def test_skipped_rows_name_the_reason_instead_of_guessing_the_ui_was_busy(self):
        api = self.make_api([
            {"title": "关闭营销通知", "rc": 0, "skipped": True, "sec": 0, "tail": ["未勾选，本次没有执行"]},
            {"title": "收尾", "rc": 0, "sec": 1}])
        text = api.diagnostics()
        self.assertIn("关闭营销通知：跳过（未勾选，本次没有执行）", text)
        self.assertIn("收尾：成功", text)


if __name__ == "__main__":
    unittest.main()
