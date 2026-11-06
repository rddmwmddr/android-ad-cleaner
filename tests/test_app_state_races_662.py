"""#662：还原与执行互斥、停止 / 暂停在锁内判断。

手机版上两件事都被 `in_front()` 包着（开前台服务、悬浮胶囊、后台屏）。以前还原不看是否在执行：
执行页「更多 → 还原改动」照样能点，还原先结束就把执行的保活撤了（小米会冻结它），两边还在同一块屏上点按。
"""
import tempfile
import unittest

from fixtures import FakeRunner, job_stub
from gui import app


class RestoreExclusionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = app.Api(self.tmp.name, runner=FakeRunner())
        self.ran = []
        self.api._restore_work = lambda serial, what: self.ran.append(what) or "已还原"

    def tearDown(self):
        self.tmp.cleanup()

    def test_restore_is_refused_while_a_run_is_going(self):
        self.api.dispatcher.job = job_stub(running=True)
        self.assertIn("正在执行去广告", self.api.restore("test", "quickapp"))
        self.assertEqual(self.ran, [], "执行中不能碰手机")

    def test_run_is_refused_while_restoring(self):
        def restoring(serial, what):
            self.ran.append(self.api.dispatcher.start("test", {"backup": False}))
            return "已还原"
        self.api._restore_work = restoring
        self.api.restore("test", "quickapp")
        self.assertIn("还原", self.ran[0]["error"])

    def test_second_restore_is_refused_while_the_first_runs(self):
        def restoring(serial, what):
            self.ran.append(self.api.restore("test", "channels"))
            return "已还原"
        self.api._restore_work = restoring
        self.assertEqual(self.api.restore("test", "quickapp"), "已还原")
        self.assertIn("还没做完", self.ran[0])

    def test_slot_is_released_even_when_restore_fails(self):
        def boom(serial, what):
            raise RuntimeError("手机断开")
        self.api._restore_work = boom
        with self.assertRaises(RuntimeError):
            self.api.restore("test", "quickapp")
        self.assertEqual(self.api.dispatcher.claim("还原"), "", "出错后位置要放出来")


class StopPauseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = app.Api(self.tmp.name, runner=FakeRunner())

    def tearDown(self):
        self.tmp.cleanup()

    def test_stop_without_a_running_job_is_a_no_op(self):
        finished = job_stub(running=False)
        self.api.dispatcher.job = finished
        self.assertTrue(self.api.stop())
        self.assertFalse(finished.cancel, "结束了的那一次不该被标成停止")

    def test_pause_refused_after_stop(self):
        self.api.dispatcher.job = job_stub(running=True, cancel=True)
        self.assertFalse(self.api.pause())


if __name__ == "__main__":
    unittest.main()
