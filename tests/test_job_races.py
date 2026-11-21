"""#452 批处理调度的三处旧竞态：停止漏杀、收尾行丢失、收尾行串到新 Job。

三条都用假进程 + 强制交错点，不依赖真实等待，也不连手机。
"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import json
import tempfile
import unittest
from unittest.mock import patch

from fixtures import FakeProc, FakeRunner, job_stub
from gui import app


def event(kind):
    return "#aac:event " + json.dumps({"kind": kind})


class ObservingLock:
    """在每次 `with` 退出、锁仍持有时回调一次，用来在状态发布点取样。"""

    def __init__(self, inner, observe):
        self._inner = inner
        self._observe = observe
        self._busy = False

    def __enter__(self):
        self._inner.acquire()
        return self

    def __exit__(self, *exc):
        try:
            if not self._busy:
                self._busy = True
                try:
                    self._observe()
                finally:
                    self._busy = False
        finally:
            self._inner.release()

    def acquire(self, *args, **kwargs):
        return self._inner.acquire(*args, **kwargs)

    def release(self):
        self._inner.release()


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def api(self, **job_fields):
        api = app.Api(self._dir.name)
        api.job = job_stub(serial="test", model="m", t0=0, **job_fields)
        return api

    @staticmethod
    def sample_finished(api, samples):
        """把「已经发布 running=False」的快照收下来。"""
        snap = api.poll()
        if not snap["running"]:
            samples.append(snap)


class StopRaceTests(Base):
    def test_stop_landing_between_spawn_and_registration_still_kills_the_process(self):
        api = self.api(total=2)
        stopped = []

        def stop_at_first_spawn():
            # 停止只落在首个 spawn 上。若第二个 spawn（收尾）也置停止，request_stop 会替那一步
            # 残留的陈旧 proc 补杀，断言就变成「谁杀的都算」，钉不住登记方的补杀
            if stopped:
                return
            stopped.append(True)
            api.job.request_stop()

        api.runner = FakeRunner(on_spawn=stop_at_first_spawn)
        api._work([app.Task("关闭营销通知", "chan_fast.py"), app.Task("收尾", "run.py", always_run=True)])
        self.assertTrue(api.runner.procs[0].terminated, "停止后这次执行启动的引擎进程没有被终止")
        self.assertTrue(api.job.results[0].get("stopped"), api.job.results[0])


class JobScopingTests(Base):
    """`_work()` 写日志、记事件、落结果都认它开始时那一次的 Job：新一轮执行顶上来之后，
    旧执行剩下的话不能写进新一页（#452 的第三条）。"""

    def test_every_line_of_a_run_lands_in_the_job_it_started_with(self):
        api = self.api(total=2)
        old, nxt = api.job, job_stub(serial="next")
        api.runner = FakeRunner(spawns=[
            FakeProc(event("ui_busy") + "\nUIAUTOMATION_BUSY：已占用\n", rc=1), FakeProc()])
        old.lock = ObservingLock(old.lock, lambda: setattr(api, "job", nxt))
        api._work([app.Task("广告开关", "run.py", uses_ui=True),
                   app.Task("通知", "chan_fast.py", uses_ui=True),
                   app.Task("收尾", "run.py", always_run=True)])
        self.assertEqual(nxt.lines, [], "新的那次执行接收到了旧执行的日志")
        self.assertEqual(nxt.results, [], "旧执行的结果落进了新一页")
        self.assertEqual(nxt.step_events, set())
        self.assertIn("读屏服务仍被占用，跳过本步骤；请先解决读屏连接再重试。", old.lines)
        self.assertTrue(any("执行结束，用时" in line for line in old.lines), old.lines)

    def test_a_spawn_that_raises_is_logged_into_the_job_the_run_started_with(self):
        api = self.api(total=1)
        old, nxt = api.job, job_stub(serial="next")
        api.runner = FakeRunner()

        def boom(script, *args, env_extra=None):
            raise OSError("没有这个脚本")

        api.runner.spawn = boom
        old.lock = ObservingLock(old.lock, lambda: setattr(api, "job", nxt))
        api._work([app.Task("广告开关", "run.py")])
        self.assertIn("✗ 没有这个脚本", old.lines)
        self.assertEqual(nxt.lines, [])

    def test_the_steps_skipped_after_a_disconnect_log_into_the_job_the_run_started_with(self):
        api = self.api(total=1)
        old, nxt = api.job, job_stub(serial="next")
        api.runner = FakeRunner(spawns=[
            FakeProc(event("link_lost") + "\n手机和电脑的 adb 连接断开了\n", rc=1)])
        api.dispatcher.adb_present = lambda adb, serial: False
        old.lock = ObservingLock(old.lock, lambda: setattr(api, "job", nxt))
        api._work([app.Task("广告开关", "run.py"), app.Task("收尾", "run.py", always_run=True)])
        self.assertTrue(any(line.startswith("\n▶ 收尾") for line in old.lines), old.lines)
        self.assertEqual(nxt.lines, [])

    def test_the_pause_boundary_writes_to_the_job_it_started_with(self):
        api = self.api(total=2)
        old, nxt = api.job, job_stub(serial="next")
        swapped, slept, paused = [], [], []

        def on_spawn():
            if swapped:
                return
            swapped.append(True)
            api.pause()             # 第一步执行中点「暂停」：暂停点落在下一步的边界上
            api.job = nxt

        def wake(seconds):
            slept.append(seconds)
            paused.append(old.paused)
            old.clear_pause()

        api.runner = FakeRunner(spawns=[FakeProc(), FakeProc()], on_spawn=on_spawn)
        with patch.object(app.time, "sleep", side_effect=wake), patch.object(app, "chime"):
            api._work([app.Task("广告开关", "run.py"), app.Task("收尾", "run.py", always_run=True)])
        self.assertEqual(slept, [0.5], "等待期间按半秒一轮看「继续」有没有被点")
        self.assertEqual(paused, [True], "等待期间要告诉界面「已暂停」")
        self.assertIs(old.paused, False, "继续之后要撤掉暂停标记")
        self.assertIn("⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」", old.lines)
        self.assertIn("▶ 继续执行", old.lines)
        self.assertEqual(nxt.lines, [], "旧执行的暂停提示写进了新一页")


class FinalLineTests(Base):
    def test_the_snapshot_reporting_running_false_already_has_the_final_line(self):
        api = self.api(total=1)
        api.runner = FakeRunner()
        samples = []
        api.job.lock = ObservingLock(api.job.lock, lambda: self.sample_finished(api, samples))
        api._work([app.Task("存改动前的快照", "run.py", ["backup"])])
        self.assertTrue(samples, "没有在发布点取到快照")
        self.assertIn("执行结束", "\n".join(samples[0]["lines"]))

    def test_final_line_of_the_old_run_stays_out_of_the_next_job(self):
        # 已停止的收尾行是「已停止」；接管后的新执行只会写「执行结束」，标记不撞车
        api = self.api(total=1, cancel=True)
        api.runner = FakeRunner()
        old, taken, threads = api.job, [], []
        real_thread = app.threading.Thread

        class RecordingThread(real_thread):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                threads.append(self)

        def take_over():
            if taken or api.job.running:
                return
            taken.append(True)
            api.start("test", {"backup": False})   # 发布 running=False 的那一刻允许接管

        api.job.lock = ObservingLock(api.job.lock, take_over)
        with patch.object(app.threading, "Thread", RecordingThread):
            api._work([app.Task("收尾", "run.py", always_run=True)])
        self.assertTrue(taken, "没有在发布点接管")
        self.assertEqual(len(threads), 1)
        threads[0].join(5)
        self.assertIn("已停止", "\n".join(old.lines))          # 旧执行自己收到了收尾行
        self.assertNotIn("已停止", "\n".join(api.job.lines))


if __name__ == "__main__":
    unittest.main()
