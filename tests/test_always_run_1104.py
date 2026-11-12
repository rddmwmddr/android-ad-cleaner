"""#1104：停止后仍要跑的步骤由构造处声明，不再按「收尾」这个标题认。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import tempfile
import unittest

from fixtures import FakeProc, FakeRunner, job_stub
from gui import app as client


class Base(unittest.TestCase):
    def make_api(self, **runner):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        api = client.Api(directory.name, runner=FakeRunner(**runner))
        api.job = job_stub()
        return api

    def stopped_in_first_step(self, tasks):
        """第一步跑到一半点「停止」，返回跑完之后的 api。"""
        api = self.make_api()
        api.runner.spawns = [FakeProc("正在连接手机读屏服务……\n",
                                      wait=lambda: (api.job.request_stop(), -15)[1]),
                             FakeProc("插电常亮已改回 0\n")]
        api._work(tasks)
        return api


class AlwaysRunTests(Base):
    def test_a_declared_step_still_runs_after_stop_whatever_its_title(self):
        api = self.stopped_in_first_step([client.Task("广告开关", "run.py"),
                                          client.Task("随便什么标题", "run.py", always_run=True)])
        self.assertEqual([c.script for c in api.runner.spawn_calls], ["run.py", "run.py"])
        self.assertEqual(api.job.results[1]["title"], "随便什么标题")
        self.assertEqual(api.job.results[1]["rc"], 0)
        self.assertFalse(api.job.results[1].get("stopped", False))

    def test_an_undeclared_step_does_not_run_after_stop(self):
        api = self.stopped_in_first_step([client.Task("广告开关", "run.py"),
                                          client.Task("收尾", "run.py")])
        self.assertEqual(len(api.runner.spawn_calls), 1, "没声明「停止后仍跑」的步骤不该再起子进程")
        self.assertEqual([r["title"] for r in api.job.results], ["广告开关"])

    def test_the_planned_finish_step_declares_it(self):
        finish = next(t for t in client.plan_tasks("S", {"backup": False}) if t.kind == "finish")
        self.assertTrue(finish.always_run)

    def stopped_when_the_declared_step_is_spawned(self, first):
        """停止恰好落在声明「仍跑」那一步的 spawn 与登记之间。"""
        api = self.make_api()
        stopped = []

        def stop_once():
            if len(api.runner.spawn_calls) == 2 and not stopped:
                stopped.append(True)
                api.job.request_stop()

        api.runner = FakeRunner(spawns=[FakeProc(), first], on_spawn=stop_once)
        api._work([client.Task("广告开关", "run.py"),
                   client.Task("收尾", "run.py", always_run=True)])
        return api

    def test_a_declared_step_is_not_killed_when_stop_lands_at_its_spawn(self):
        api = self.stopped_when_the_declared_step_is_spawned(FakeProc("插电常亮已改回 0\n"))
        self.assertFalse(api.runner.procs[1].terminated, "停止后不该把「仍跑」的步骤当成要杀的子进程")
        self.assertEqual(api.job.results[1]["rc"], 0)
        self.assertFalse(api.job.results[1].get("stopped", False))

    def test_a_declared_step_that_fails_after_stop_is_still_a_failure(self):
        api = self.stopped_when_the_declared_step_is_spawned(FakeProc("✗ 收尾没有完成\n", rc=1))
        row = api.job.results[1]
        self.assertEqual(row["rc"], 1)
        self.assertFalse(row.get("stopped", False), "停止后仍跑的收尾真失败时不能记成「已停止」")


if __name__ == "__main__":
    unittest.main()
