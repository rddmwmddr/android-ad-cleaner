"""#638：结果页把没做成的步骤再跑一遍。

可重试的只有「设备侧没做成」那几档：失败，以及因读屏被占用 / 断线 / 锁屏而跳过的步。
没勾选、这台机本来没有或已关（#577 的 rc=0 跳过）与用户点「停止」的步都不重试。
广告开关步按引擎报的 `failed_steps` 段名只重跑那几段；快照一旦成功就不再重存。
多轮结果按 kind 合并，最新一轮覆盖同一步，已停止的保留。
"""
import ast
import json
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures import FakeProc, FakeRunner
from gui import app

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "#aac:event "


def event(kind, **data):
    return PREFIX + json.dumps({"kind": kind, **data}, ensure_ascii=False)


PLAN = {"backup": True, "steps": ["桌面", "商店"], "ref": True, "model": "M",
        "channels": [{"pkg": "p", "id": "1", "name": "活动"}], "quickapp": True, "ads": ["com.a"]}


def row(kind, rc=0, **fields):
    return {"title": kind, "kind": kind, "rc": rc, **fields}


class RetryableTests(unittest.TestCase):
    def test_only_step_the_device_failed_at_is_retryable(self):
        cases = [({"rc": 1}, True),                                  # 失败
                 ({"rc": 3, "skipped": True}, True),                 # 读屏占用 / 断线 / 锁屏
                 ({"rc": -1}, True),                                  # 起不来子进程
                 ({"rc": 0}, False),                                  # 成功
                 ({"rc": 0, "skipped": True}, False),                 # #577：没勾 / 本来没有
                 ({"rc": 1, "stopped": True}, False),                 # 用户点停止
                 ({}, False)]
        for fields, want in cases:
            with self.subTest(fields=fields):
                self.assertEqual(app.retryable(fields), want)


class RetryPlanTests(unittest.TestCase):
    def test_everything_succeeded_means_nothing_to_retry(self):
        self.assertIsNone(app.retry_plan(PLAN, [row("backup"), row("recipe"), row("finish")]))

    def test_the_ad_switch_step_only_reruns_the_segments_the_engine_named(self):
        plan = app.retry_plan(PLAN, [row("backup"), row("recipe", 1, failed_steps=["商店"]), row("finish")])
        self.assertEqual(plan["steps"], ["商店"])

    def test_a_recipe_that_died_without_naming_segments_reruns_whole(self):
        plan = app.retry_plan(PLAN, [row("backup"), row("recipe", 1), row("finish")])
        self.assertEqual(plan["steps"], PLAN["steps"])

    def test_a_snapshot_that_worked_is_never_stored_again(self):
        self.assertFalse(app.retry_plan(PLAN, [row("backup"), row("recipe", 1)])["backup"])
        self.assertTrue(app.retry_plan(PLAN, [row("backup", 1), row("recipe"), row("finish")])["backup"])

    def test_cleanup_only_reruns_when_it_failed(self):
        self.assertIsNone(app.retry_plan(PLAN, [row("finish")]))
        self.assertTrue(app.retry_plan(PLAN, [row("finish", 1)])["finish"])

    def test_the_other_steps_are_rebuilt_from_the_original_plan(self):
        plan = app.retry_plan(PLAN, [row("channels", 1), row("quickapp", 1), row("ads", 1)])
        self.assertEqual(plan["channels"], PLAN["channels"])
        self.assertTrue(plan["quickapp"])
        self.assertEqual(plan["ads"], PLAN["ads"])
        self.assertTrue(plan["ref"])
        self.assertEqual(plan["model"], "M")

    def test_steps_that_succeeded_are_not_in_the_plan(self):
        plan = app.retry_plan(PLAN, [row("channels", 3, skipped=True), row("quickapp"), row("ads")])
        self.assertEqual(plan["channels"], PLAN["channels"])
        self.assertFalse(plan["quickapp"])
        self.assertEqual(plan["ads"], [])

    def test_a_stopped_or_not_run_step_is_not_retried(self):
        self.assertIsNone(app.retry_plan(PLAN, [row("recipe", 1, stopped=True),
                                                row("channels", 0, skipped=True)]))


class PlanTasksKindTests(unittest.TestCase):
    def test_every_step_carries_its_own_kind(self):
        tasks = app.plan_tasks("S", dict(PLAN, finish=True))
        self.assertEqual([t.kind for t in tasks],
                         ["backup", "recipe", "channels", "quickapp", "ads", "finish"])

    def test_a_retry_round_can_leave_cleanup_out(self):
        tasks = app.plan_tasks("S", {"backup": False, "steps": ["商店"], "ref": True, "finish": False})
        self.assertEqual([t.kind for t in tasks], ["recipe"])

    def test_unchecked_steps_keep_their_kind_too(self):
        offered = {"steps": ["桌面"], "quickapps": [], "ads": [], "channels": None}
        tasks = app.plan_tasks("S", {"backup": False, "finish": False}, offered)
        self.assertEqual([t.kind for t in tasks], ["recipe", "channels", "quickapp", "ads"])


class MergeTests(unittest.TestCase):
    def test_the_latest_round_overwrites_the_same_step_in_place(self):
        job = app.Job(serial="s", t0=0, base_results=[row("backup"), row("recipe", 1), row("finish")])
        job.add_result(row("recipe"))
        self.assertEqual([(r["kind"], r["rc"]) for r in job.results],
                         [("backup", 0), ("recipe", 0), ("finish", 0)])

    def test_a_step_that_was_not_in_the_previous_round_is_appended(self):
        job = app.Job(serial="s", t0=0)
        job.add_result(row("backup"))
        job.add_result(row("recipe"))
        self.assertEqual([r["kind"] for r in job.results], ["backup", "recipe"])

    def test_a_result_without_a_kind_still_lands(self):
        job = app.Job(serial="s", t0=0)
        job.add_result({"title": "手写的行", "rc": 0})
        job.add_result({"title": "再来一行", "rc": 0})
        self.assertEqual(len(job.results), 2)

    def test_the_title_keeps_the_coverage_from_the_first_round(self):
        # 重试轮只跑其中一两段，标题按这一轮重算会把「（3 / 9 段）」抹掉
        job = app.Job(serial="s", t0=0,
                      base_results=[row("recipe", 1, title="关闭各 App 里的广告开关（3 / 9 段）")])
        job.add_result(row("recipe", title="关闭各 App 里的广告开关"))
        self.assertEqual(job.results[0]["title"], "关闭各 App 里的广告开关（3 / 9 段）")
        self.assertEqual(job.results[0]["rc"], 0)


class WorkRecordsTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def make_api(self, **runner):
        api = app.Api(self._dir.name, runner=FakeRunner(**runner))
        return api

    def recipe(self):
        return app.Task("关闭各 App 里的广告开关", "run.py", ["-s", "t", "recipe", "桌面", "商店"],
                        uses_ui=True, kind="recipe")

    def test_the_engine_segment_names_land_on_the_step_result(self):
        api = self.make_api(spawns=[FakeProc(event("failed_steps", steps=["商店"]) + "\n未完成步骤：商店\n", rc=1)])
        api.job = app.Job(serial="t", total=1, t0=0)
        api._work([self.recipe()])
        first = api.job.results[0]
        self.assertEqual(first["kind"], "recipe")
        self.assertEqual(first["failed_steps"], ["商店"])

    def test_a_successful_step_reports_no_failed_segments(self):
        api = self.make_api(spawns=[FakeProc("机型脚本跑完：关了 3 个，9 秒\n", rc=0)])
        api.job = app.Job(serial="t", total=1, t0=0)
        api._work([self.recipe()])
        self.assertEqual(api.job.results[0]["failed_steps"], [])

    def test_a_payload_that_is_not_a_string_list_is_not_split_into_one_letter_segments(self):
        # 载荷来自另一个进程：`"steps": "商店"` 逐字符迭代会变成 `recipe 商 店`，
        # ONLY 一段都匹配不到，上一轮的失败反过来被改写成「成功（关了 0 个）」。
        api = self.make_api(spawns=[FakeProc(event("failed_steps", steps="商店") + "\n未完成步骤：商店\n", rc=1)])
        api.job = app.Job(serial="t", total=1, t0=0)
        api._work([self.recipe()])
        self.assertEqual(api.job.results[0]["failed_steps"], [])

    def test_segment_names_arrive_trimmed(self):
        api = self.make_api(spawns=[FakeProc(event("failed_steps", steps=[" 商店 "]) + "\n", rc=1)])
        api.job = app.Job(serial="t", total=1, t0=0)
        api._work([self.recipe()])
        self.assertEqual(api.job.results[0]["failed_steps"], ["商店"])

    def test_the_segment_names_do_not_leak_into_the_log_or_the_tail(self):
        api = self.make_api(spawns=[FakeProc(event("failed_steps", steps=["商店"]) + "\n未完成步骤：商店\n", rc=1)])
        api.job = app.Job(serial="t", total=1, t0=0)
        api._work([self.recipe()])
        self.assertNotIn("aac:event", "\n".join(api.job.lines))
        self.assertEqual(api.job.results[0]["tail"], ["未完成步骤：商店"])

    def test_the_snapshot_carries_how_many_steps_can_be_retried(self):
        api = self.make_api()
        api.job = app.Job(serial="t", t0=0, base_results=[row("backup"), row("recipe", 1), row("finish")])
        self.assertEqual(api.poll(0)["retry"], 1)
        api.job.results[1] = row("recipe")
        self.assertEqual(api.poll(0)["retry"], 0)


class ApiRetryTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def make_api(self, **runner):
        return app.Api(self._dir.name, runner=FakeRunner(**runner))

    def start_round(self, api):
        """起一轮，把要跑的任务拿回来（线程换成假的，任务在用例里手动跑）。"""
        with patch.object(app.threading, "Thread", autospec=True) as thread:
            result = api.start("SER", dict(PLAN, channels=[], quickapp=False, ads=[]))
        thread.assert_called_once()
        return thread.call_args.kwargs["args"][0], result

    def retry_round(self, api):
        with patch.object(app.threading, "Thread", autospec=True) as thread:
            result = api.retry()
        if thread.called:
            return thread.call_args.kwargs["args"][0], result
        return None, result

    def test_a_retry_round_only_runs_the_segments_the_engine_reported(self):
        api = self.make_api(spawns=[FakeProc("快照已存\n", rc=0),
                                    FakeProc(event("failed_steps", steps=["商店"]) + "\n未完成步骤：商店\n", rc=1),
                                    FakeProc("插电常亮已改动\n", rc=0)])
        tasks, _ = self.start_round(api)
        api._work(tasks)
        self.assertEqual([r["kind"] for r in api.job.results], ["backup", "recipe", "finish"])

        api.runner.spawns = [FakeProc("机型脚本跑完：关了 2 个，9 秒\n", rc=0)]
        tasks, started = self.retry_round(api)
        self.assertEqual([t.kind for t in tasks], ["recipe"])
        self.assertEqual(started["total"], 1)
        self.assertEqual(list(tasks[0].args), ["-s", "SER", "recipe", "商店", "--ref"])

        api._work(tasks)
        self.assertEqual(api.runner.spawn_calls[3].args, ("-s", "SER", "recipe", "商店", "--ref"))
        self.assertEqual([(r["kind"], r["rc"]) for r in api.job.results],
                         [("backup", 0), ("recipe", 0), ("finish", 0)])
        self.assertEqual(api.poll(0)["retry"], 0)

    def test_a_successful_snapshot_is_not_stored_again(self):
        api = self.make_api(spawns=[FakeProc("快照已存\n", rc=0),
                                    FakeProc("未完成步骤：商店\n", rc=1),
                                    FakeProc("插电常亮已改动\n", rc=0),
                                    FakeProc(rc=0)])
        tasks, _ = self.start_round(api)
        api._work(tasks)
        tasks, _ = self.retry_round(api)
        self.assertEqual([t.kind for t in tasks], ["recipe"])   # 没有快照，也没有收尾
        self.assertNotIn("backup", [t.kind for t in tasks])

    def test_the_retry_round_carries_the_previous_log_and_payloads(self):
        # 诊断与上报看的是整场：重试轮另起一个 Job，但日志与页面骨架要接着上一轮
        api = self.make_api(spawns=[FakeProc("快照已存\n", rc=0),
                                    FakeProc("#aac:payload 骨架A\n未完成步骤：商店\n", rc=1),
                                    FakeProc("插电常亮已改动\n", rc=0)])
        tasks, _ = self.start_round(api)
        api._work(tasks)
        lines, payloads = list(api.job.lines), list(api.job.payloads)
        self.assertEqual(payloads, ["骨架A"])
        self.assertIn("快照已存", lines)

        tasks, _ = self.retry_round(api)
        self.assertEqual(api.job.lines[:len(lines)], lines)
        self.assertEqual(api.job.payloads, payloads)

    def test_retrying_until_nothing_is_left_then_says_so(self):
        api = self.make_api(spawns=[FakeProc("快照已存\n", rc=0),
                                    FakeProc("未完成步骤：商店\n", rc=1),
                                    FakeProc("插电常亮已改动\n", rc=0),
                                    FakeProc("机型脚本跑完：关了 2 个，9 秒\n", rc=0)])
        tasks, _ = self.start_round(api)
        api._work(tasks)
        tasks, _ = self.retry_round(api)
        api._work(tasks)
        self.assertEqual(api.poll(0)["retry"], 0)
        tasks, result = self.retry_round(api)
        self.assertIsNone(tasks)
        self.assertIn("error", result)

    def test_before_any_run_there_is_nothing_to_retry(self):
        api = self.make_api()
        self.assertIn("error", api.retry())

    def test_a_retry_keeps_the_hostile_steps_out(self):
        # 用户点过停止的那一轮：stopped 的行留在结果页，不当成可重试
        api = self.make_api()
        api.job = app.Job(serial="SER", t0=0, plan=dict(PLAN),
                          base_results=[row("backup"), row("recipe", 1, stopped=True)])
        tasks, result = self.retry_round(api)
        self.assertIsNone(tasks)
        self.assertIn("error", result)


def emits_failed_steps(tree):
    """`if g.get("FAILED_STEPS"):` 那一支里有 events.emit("failed_steps", …)。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)
                and test.func.attr == "get" and isinstance(test.func.value, ast.Name)
                and test.func.value.id == "g" and test.args
                and getattr(test.args[0], "value", None) == "FAILED_STEPS"):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "emit" and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "events" and inner.args
                    and getattr(inner.args[0], "value", None) == "failed_steps"):
                return True
    return False


class EngineEmitsFailedStepsTests(unittest.TestCase):
    def test_the_run_branch_publishes_the_segment_names(self):
        tree = ast.parse((ROOT / "tool" / "fast.py").read_text(encoding="utf-8"))
        self.assertTrue(emits_failed_steps(tree),
                        "fast.py 的 run 分支要把 FAILED_STEPS 的名字也发成 failed_steps 事件（#638）")


if __name__ == "__main__":
    unittest.main()
