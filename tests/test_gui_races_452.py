"""回归：gui/app.py 批处理调度的三处旧竞态（#452，#447 三轴审查的 bug 轴）。

三条都用「钩子强制交错」替代睡眠等待：测试钩在竞态窗口的确切位置上，
_work 走的是当前调用线程，没有第二个写者，断言是确定性的。

1. spawn 返回与 `j.proc` 登记之间用户点停止 → 假 runner 在 spawn 内部就调
   request_stop()（此刻锁还没被 _work 拿回去，正是票面描述的窗口）。
2. 收尾行与 `running=False` 的先后 → 侦包裹住 _log，记录写收尾行那一刻的
   running 值（先收 running 再写行，轮询端就永远看不到这一行）。
3. 收尾行串进下一次执行 → 同一个侦在写收尾行时调 start()：窗口内 running
   已收掉，start() 会换上新 Job，收尾行落进新日志的开头。
"""
import io
import unittest
from unittest.mock import patch

from gui import app
from tests.fixtures import job_stub


class FakeProc:
    """假引擎进程：空输出、rc=0，terminate 记次数。"""

    def __init__(self):
        self.stdout = io.StringIO("")
        self.terminated = 0

    def terminate(self):
        self.terminated += 1

    def wait(self):
        return 0


class RacingRunner:
    """spawn 返回前一刻触发停止：恰好落在 spawn 返回与 proc 登记之间的窗口里。"""

    def __init__(self, api):
        self.api = api
        self.proc = FakeProc()

    def spawn(self, script, *args, env_extra=None):
        self.api.job.request_stop()
        return self.proc


class QuietRunner:
    """正常跑完一步就结束。"""

    def __init__(self):
        self.proc = FakeProc()

    def spawn(self, script, *args, env_extra=None):
        return self.proc


def one_task():
    return [app.Task("存改动前的快照", "run.py", ["-s", "test", "backup"])]


def empty_plan():
    return {"backup": False, "steps": [], "channels": [], "quickapp": False, "ads": []}


class GuiRaces452(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.api = app.Api(self._dir.name)
        self.api.job = job_stub()

    def tearDown(self):
        self._dir.cleanup()

    def test_stop_between_spawn_and_registration_still_kills_the_engine(self):
        runner = RacingRunner(self.api)
        self.api.runner = runner

        with patch.object(app, "chime"):
            self.api._work(one_task())

        self.assertGreaterEqual(
            runner.proc.terminated, 1,
            "停止落在 spawn 返回与 proc 登记之间：引擎进程没被杀，手机仍在被点按",
        )
        self.assertTrue(self.api.job.cancel)

    def test_final_line_is_written_while_the_job_still_counts_as_running(self):
        seen = {}
        original = self.api._log

        def spy(s):
            if "执行结束" in s:
                seen["running"] = self.api.job.running
            return original(s)

        self.api._log = spy
        self.api.runner = QuietRunner()

        with patch.object(app, "chime"):
            self.api._work(one_task())

        self.assertTrue(
            seen.get("running"),
            "写收尾行时 running 已被提前收掉：先看到 !running 的轮询端会停表，这一行永远不显示",
        )
        self.assertIn("执行结束", self.api.job.lines[-1])

    def test_final_line_does_not_leak_into_the_next_job(self):
        seen = {}
        original = self.api._log

        def spy(s):
            if "执行结束" in s and "start_result" not in seen:
                # 收尾行写下的那一刻，用户立刻再点开始：模拟竞态窗口里的接管。
                seen["start_result"] = self.api.start("test", empty_plan())
            return original(s)

        self.api._log = spy
        self.api.runner = QuietRunner()

        with patch.object(app, "chime"):
            self.api._work(one_task())

        self.assertEqual(
            seen.get("start_result"), {"error": "已有任务在运行"},
            "收尾行还没写完就允许新任务接管：上一次的收尾行会混进下一次执行的日志开头",
        )
        self.assertIn("执行结束", self.api.job.lines[-1])
        self.assertNotIn("已停止", self.api.job.lines[0])


if __name__ == "__main__":
    unittest.main()
