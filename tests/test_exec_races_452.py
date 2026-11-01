"""#452 批处理调度的三处旧竞态：停止漏杀、收尾行丢失、收尾行串到新 Job。

三条都用假进程 + 强制交错点，不依赖真实等待，也不连手机。
"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import tempfile
import unittest
from unittest.mock import patch

from fixtures import job_stub
from gui import app


class FakeProc:
    """假引擎进程：wait 返回设定值，terminate 只记一笔。"""

    def __init__(self, rc=0):
        self.stdout = iter(())
        self.returncode = None
        self._rc = rc
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self):
        return self._rc


class FakeRunner:
    """spawn 交出假进程；before_return 在 spawn 返回之前执行，用来把交错点钉死。"""

    def __init__(self, before_return=None, rc=0):
        self.before_return = before_return
        self.rc = rc
        self.procs = []

    def spawn(self, script, *args, env_extra=None):
        proc = FakeProc(self.rc)
        self.procs.append(proc)
        if self.before_return:
            self.before_return()
        return proc


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

        api.runner = FakeRunner(before_return=stop_at_first_spawn)
        api._work([app.Task("关闭营销通知", "chan_fast.py"), app.Task("收尾", "run.py")])
        self.assertTrue(api.runner.procs[0].terminated, "停止后这次执行启动的引擎进程没有被终止")
        self.assertTrue(api.job.results[0].get("stopped"), api.job.results[0])


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
            api._work([app.Task("收尾", "run.py")])
        self.assertTrue(taken, "没有在发布点接管")
        self.assertEqual(len(threads), 1)
        threads[0].join(5)
        self.assertIn("已停止", "\n".join(old.lines))          # 旧执行自己收到了收尾行
        self.assertNotIn("已停止", "\n".join(api.job.lines))


if __name__ == "__main__":
    unittest.main()
