"""一次执行的状态收成 Job、poll 只读锁内快照（ADR-0010）。"""
import tempfile
import threading
import unittest
from unittest.mock import Mock

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
            self.assertEqual(api.poll()["results"], [{"title": "备份", "rc": 0, "sec": 1}])

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
