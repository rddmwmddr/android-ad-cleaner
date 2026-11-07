"""#662：还原与执行互斥、停止 / 暂停在锁内判断。

手机版上两件事都被 `in_front()` 包着（开前台服务、悬浮胶囊、后台屏）。以前还原不看是否在执行：
执行页「更多 → 还原改动」照样能点，还原先结束就把执行的保活撤了（小米会冻结它），两边还在同一块屏上点按。
"""
import tempfile
import threading
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

    def test_restore_refuses_instead_of_queueing_behind_a_ui_check(self):
        """#675：读屏检查持锁最长 75 秒，还原不能把界面线程按在那里等，要立刻回一句。"""
        holding, release = threading.Event(), threading.Event()

        def hold():
            with self.api.dispatcher.exclusive():
                holding.set()
                release.wait(5)

        h = threading.Thread(target=hold)
        h.start()
        self.assertTrue(holding.wait(5), "没能占住锁")
        out = []
        w = threading.Thread(target=lambda: out.append(self.api.restore("test", "quickapp")))
        w.start()
        try:
            w.join(1.0)
            self.assertFalse(w.is_alive(), "锁在别人手里时要立刻回一句")
        finally:
            release.set()
            h.join(5)
            w.join(5)
        self.assertEqual(out[0], "正在检查读屏连接，等它结束后再还原")
        self.assertEqual(self.ran, [], "都没占到位置，不该碰手机")

    def test_ui_check_is_refused_while_a_restore_is_going(self):
        """#675：还原正在点手机时不能去跑读屏检查，两边会抢同一块屏。"""
        self.api._run = lambda *a, **k: self.ran.append(a) or ("", "", 0)
        self.api.dispatcher.side = "还原"
        self.assertIn("还原", self.api.ui_check("test")["error"])
        self.assertEqual(self.ran, [], "不该起检查进程")

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

    def wait_for_the_dispatcher_lock(self, call):
        """别人持着锁时这条调用必须等：立刻返回就说明「取 job、判 running、置标记」不在锁里。"""
        d = self.api.dispatcher
        holding, release, done = threading.Event(), threading.Event(), threading.Event()

        def hold():
            with d.exclusive():
                holding.set()
                release.wait(5)

        def run():
            call()
            done.set()

        h = threading.Thread(target=hold)
        h.start()
        self.assertTrue(holding.wait(5), "没能占住锁")
        t = threading.Thread(target=run)
        t.start()
        try:
            self.assertFalse(done.wait(0.1), "别人持着锁它就返回了：判断跑在临界区外面")
        finally:
            release.set()
            h.join(5)
            t.join(5)
        self.assertTrue(done.is_set())

    def test_stop_reads_the_job_under_the_dispatcher_lock(self):
        self.api.dispatcher.job = job_stub(running=True)
        self.wait_for_the_dispatcher_lock(self.api.stop)

    def test_pause_reads_the_job_under_the_dispatcher_lock(self):
        self.api.dispatcher.job = job_stub(running=True)
        self.wait_for_the_dispatcher_lock(self.api.pause)


if __name__ == "__main__":
    unittest.main()
