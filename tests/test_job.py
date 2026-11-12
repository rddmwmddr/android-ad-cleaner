"""一次执行的状态收成 Job、poll 只读锁内快照（ADR-0010）。"""
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from fixtures import FakeRunner
from gui import app


class SnapshotTests(unittest.TestCase):
    def test_snapshot_returns_only_lines_after_the_offset(self):
        job = app.Job(serial="s", t0=0)
        job.lines.extend(["一", "二", "三"])
        snap = job.snapshot(2)
        self.assertEqual(snap["lines"], ["三"])
        self.assertEqual(snap["next"], 3)

    def test_snapshot_carries_the_pause_flags(self):
        job = app.Job(serial="s", t0=0)
        job.pause = True
        job.paused = True
        snap = job.snapshot()
        self.assertTrue(snap["pause"])
        self.assertTrue(snap["paused"])
        self.assertTrue(snap["running"])

    def test_snapshot_keeps_all_results_while_running(self):
        # 执行中点「复制完整诊断」要看已完成步骤，所以快照交全量
        job = app.Job(serial="s", t0=0)
        job.results.append({"title": "备份", "rc": 0, "sec": 1})
        self.assertEqual(job.snapshot()["results"], [{"title": "备份", "rc": 0, "sec": 1}])


class PollTests(unittest.TestCase):
    def test_poll_hides_results_while_running_and_shows_after(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api.job = app.Job(serial="s", t0=0)
            api.job.results.append({"title": "备份", "rc": 0, "sec": 1})
            self.assertEqual(api.poll()["results"], [])
            api.job.running = False
            # poll 给每条结果附一句摘要（#1189）；这一行没有 tail，那句就是空串
            self.assertEqual(api.poll()["results"],
                             [{"title": "备份", "rc": 0, "sec": 1, "summary": ""}])

    def test_poll_before_any_run_is_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(app.Api(directory).poll(), {"running": False, "lines": [], "next": 0})

    def test_diagnostics_shows_results_that_poll_hides_while_running(self):
        # 执行中点「复制完整诊断」要看已完成步骤；界面轮询执行中不显示结果
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api.job = app.Job(serial="s", t0=0)
            api.job.add_result({"title": "备份", "rc": 0, "sec": 1})
            self.assertEqual(api.poll()["results"], [])
            self.assertIn("备份", api.diagnostics())


class RecipeCoverageTests(unittest.TestCase):
    """机型脚本的验证档位由 status-json 现读、随任务快照带给结果页（沿用 #1124 的字段，#1129）。

    值本身不在客户端算：`Api.start()` 从 `last_status` 取、`Job` 存着、`poll()` 原样交出。
    说不说由前端按结果里有没有脚本那一行决定，所以这里不管这次勾没勾脚本都照带。"""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.api = app.Api(self._dir.name, runner=FakeRunner())

    def tearDown(self):
        # 重试那一轮在后台线程里跑：等它收尾再删临时目录，否则会和它写 channels.tsv 抢同一个目录。
        job = self.api.job
        for _ in range(200):
            if not job or not job.running:
                break
            time.sleep(0.005)
        self._dir.cleanup()

    def test_the_coverage_of_the_script_that_runs_reaches_the_snapshot(self):
        self.api.last_status = {"recipe_coverage": "部分"}
        self.api.start("S", {"backup": False, "steps": ["系统广告"], "finish": False})
        self.assertEqual(self.api.job.recipe_coverage, "部分")
        self.assertEqual(self.api.poll()["recipe_coverage"], "部分")

    def test_the_value_is_passed_through_even_when_no_script_runs(self):
        # 档位一律照带；说不说由后端按「结果里有没有脚本那一行」决定（tool/coverage_note.py，#1188）。
        self.api.last_status = {"recipe_coverage": "部分"}
        self.api.start("S", {"backup": False, "finish": False})
        self.assertEqual(self.api.poll()["recipe_coverage"], "部分")

    def test_the_coverage_note_is_computed_with_the_results(self):
        # 桌面侧也在后端算这一行（#1188）：结果里真有脚本那一行、档位是负面时才给
        self.api.job = app.Job(serial="S", t0=0, recipe_coverage="部分",
                               plan={"backup": False, "steps": [], "finish": False})
        self.api.job.running = False
        self.api.job.results.append({"title": "关闭各 App 里的广告开关", "kind": "recipe", "rc": 0})
        note = self.api.poll()["coverage_note"]
        self.assertIn("只在一部分步骤上做过真机验证", note)
        self.assertIn("在 App 里", note, "桌面版措辞引导回 App 里核对")

    def test_a_run_without_the_script_gets_no_coverage_note(self):
        self.api.job = app.Job(serial="S", t0=0, recipe_coverage="部分",
                               plan={"backup": False, "steps": [], "finish": False})
        self.api.job.running = False
        self.api.job.results.append({"title": "关闭营销通知", "kind": "channels", "rc": 0})
        self.assertEqual(self.api.poll()["coverage_note"], "")

    def test_a_retry_round_that_reruns_no_script_keeps_the_previous_value(self):
        # 上一轮的脚本结果行按 kind 合并后还在结果页上，那条提示要跟着它（沿用 #638 的合并口径）。
        self.api.job = app.Job(serial="S", t0=0, recipe_coverage="部分",
                               plan={"backup": False, "steps": ["系统广告"], "finish": False,
                                     "channels": [{"pkg": "p", "id": "1", "name": "活动"}]})
        self.api.job.running = False
        self.api.job.results.append({"title": "关闭各 App 里的广告开关", "kind": "recipe", "rc": 0})
        self.api.job.results.append({"title": "关闭营销通知", "kind": "channels", "rc": 1})
        first = self.api.job
        self.assertEqual(self.api.retry(), {"ok": True, "total": 1})
        self.assertIsNot(self.api.job, first, "重试要起新一轮，别在原 Job 上原地不动")
        self.assertEqual(self.api.job.plan.steps, [], "这一轮只重跑营销通知")
        self.assertEqual(self.api.poll()["recipe_coverage"], "部分")


class StopTests(unittest.TestCase):
    def test_request_stop_is_visible_to_a_snapshot_on_another_thread(self):
        # 控制面在 HTTP 线程置取消，快照读在另一线程要能看到
        job = app.Job(serial="s", t0=0)
        job.proc = Mock()
        self.assertFalse(job.snapshot()["cancel"])
        t = threading.Thread(target=job.request_stop)
        t.start(); t.join()
        self.assertTrue(job.snapshot()["cancel"])
        job.proc.terminate.assert_called_once()
