"""一次执行跑哪些步骤：`tool/plan.py` 的 `Plan` 规格，以及按规格排出的任务与重试轮。

前半守规格本身（八个键、默认值、宽容收、JSON 往返）；后半是消费它的执行侧——
未执行的项进结果、停止后仍跑的声明、默认勾选与重试轮。票号写在每段注释里。
"""
import dataclasses
import json
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import plan as plan_module
import run
from fixtures import FakeProc, FakeRunner, job_stub
from gui import app
from gui import app as client
from test_issue_regressions import AdPackagesHarness

Plan = plan_module.Plan

# 冻结的键集合：只遍历 Plan 自己的字段时，删掉一个键连样例一起消失，用例照样绿。
FROZEN_KEYS = {"backup", "model", "steps", "ref", "channels", "quickapp", "ads", "finish"}


def keys_of(instance):
    return {f.name for f in dataclasses.fields(instance)}


class DefaultsTests(unittest.TestCase):
    def test_a_bare_plan_is_a_first_run(self):
        p = Plan()
        self.assertTrue(p.backup)
        self.assertTrue(p.finish)
        self.assertEqual((p.steps, p.channels, p.ads), ([], [], []))
        self.assertFalse(p.ref)
        self.assertFalse(p.quickapp)
        self.assertEqual(p.model, "")

    def test_the_spec_holds_exactly_the_eight_keys(self):
        self.assertEqual(keys_of(Plan()), FROZEN_KEYS)

    def test_an_empty_payload_is_a_first_run(self):
        self.assertEqual(Plan.from_json({}), Plan())


class FromJsonTests(unittest.TestCase):
    def test_missing_keys_take_their_defaults(self):
        p = Plan.from_json({"backup": False})
        self.assertFalse(p.backup)
        self.assertTrue(p.finish, "没收到的键取默认，不跟着相邻的键一起关")
        self.assertEqual(p.steps, [])

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(Plan.from_json({"nope": 1, "backup": False}).to_json(),
                         Plan(backup=False).to_json())

    def test_values_are_coerced_to_the_declared_shape(self):
        p = Plan.from_json({"backup": 0, "model": 5, "steps": None, "ref": "",
                            "channels": ({"pkg": "p"},), "quickapp": 1, "ads": None, "finish": "x"})
        self.assertIs(p.backup, False)
        self.assertIs(p.finish, True)
        self.assertIs(p.quickapp, True)
        self.assertIs(p.ref, False)
        self.assertEqual(p.model, "5")
        self.assertEqual(p.steps, [])
        self.assertEqual(p.ads, [])
        self.assertEqual(p.channels, [{"pkg": "p"}])
        self.assertIsInstance(p.channels, list)

    def test_a_string_in_a_list_field_is_dropped_not_split_into_characters(self):
        p = Plan.from_json({"steps": "桌面", "ads": "com.a"})
        self.assertEqual((p.steps, p.ads), ([], []))

    def test_direct_construction_lands_on_the_same_shape(self):
        p = Plan(steps=None, channels=None, ads=None)
        self.assertEqual((p.steps, p.channels, p.ads), ([], [], []))

    def test_a_plan_is_returned_as_is(self):
        p = Plan(steps=["桌面"], ads=["com.a"])
        self.assertIs(Plan.from_json(p), p)


class RoundTripTests(unittest.TestCase):
    def full(self):
        return Plan(backup=False, model="M", steps=["桌面", "商店"], ref=True,
                    channels=[{"pkg": "p", "id": "1", "name": "活动"}], quickapp=True,
                    ads=["com.a"], finish=False)

    def test_json_round_trips(self):
        p = self.full()
        self.assertEqual(Plan.from_json(p.to_json()), p)

    def test_the_json_shape_is_the_eight_keys(self):
        self.assertEqual(set(self.full().to_json()), FROZEN_KEYS)

    def test_to_json_copies_so_callers_cannot_mutate_the_plan_through_it(self):
        p = self.full()
        p.to_json()["steps"].append("快应用")
        self.assertEqual(p.steps, ["桌面", "商店"])


# ---------- 后并入的票号文件：按规格排任务、执行与重试 ----------
# ---------- 来源 tests/test_always_run_1104.py ----------
#   #1104：停止后仍要跑的步骤由构造处声明，不再按「收尾」这个标题认。
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声



class AlwaysRunBase(unittest.TestCase):
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


class AlwaysRunTests(AlwaysRunBase):
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


# ---------- 来源 tests/test_msa_default_973.py ----------
#   #973：选择页「挂起广告组件」的默认值来自 status-json 的 `default_on`。
#   
#   小米族的两个 msa 包在**未挂起**时默认勾上（直接开始就挂，省掉 OS4 主题段被开屏窗
#   打断的首轮）；已挂起的不预勾（走「广告组件已经挂起」的跳过行）；其他品牌维持不勾。
#   判据只认包名，不按 brand 字段或机型字符串。
class MsaDefaultTests(AdPackagesHarness, unittest.TestCase):
    """国行包（本 harness 的 INSTALLED 只有 com.miui.systemAdSolution）。"""

    def ads(self, brand, suspended=False):
        return {a["pkg"]: a for a in self.status_json(brand, suspended=suspended)["ads"]}

    def test_unsuspended_china_msa_is_default_on(self):
        self.assertIs(self.ads("Redmi")["com.miui.systemAdSolution"]["default_on"], True)

    def test_already_suspended_msa_is_not_default_on(self):
        """预勾与否在引擎侧就算好：已挂起的项不给勾选框，消费者不必再读 suspended。"""
        self.assertIs(self.ads("Redmi", suspended=True)["com.miui.systemAdSolution"]["default_on"], False)


class OtherBrandDefaultTests(AdPackagesHarness, unittest.TestCase):
    INSTALLED = ("com.opos.ads", "com.heytap.pictorial")

    def test_oppo_ads_stay_off_by_default(self):
        ads = {a["pkg"]: a for a in self.status_json("OPPO")["ads"]}
        self.assertIs(ads["com.opos.ads"]["default_on"], False)
        self.assertIs(ads["com.heytap.pictorial"]["default_on"], False)


class DefaultOnTableTests(unittest.TestCase):
    """默认勾选的包名集合是显式的：AD_PKGS 里给小米族加新包时这条会红，
    逼着回来想清楚它该不该跟着默认勾上。"""

    def test_default_on_is_exactly_the_two_msa_packages(self):
        self.assertEqual(set(run.DEFAULT_ON), {"com.miui.systemAdSolution", "com.miui.msa.global"})


# ---------- 来源 tests/test_not_run_steps_577.py ----------
#   #577：选择页上有、这次没有执行的项，也要在执行结果里留一行，说清是没勾还是本来就没有。
#   
#   以前计划里只放勾选的项，未勾的项在结果里整行不存在：跑完四步全「成功」，用户以为该做的都做了。
#   这一行不参与失败判定（rc=0），只让「全部成功」不再盖住没做的事。
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声


PREFIX_577 = "#aac:event "


def event_577(kind):
    return PREFIX_577 + json.dumps({"kind": kind})


def offered_577(steps=("桌面",), quickapps=(), ads=(), channels=None):
    """选择页上摆出来的项。channels=None 表示通知没扫成。"""
    return {"steps": list(steps), "quickapps": list(quickapps), "ads": list(ads), "channels": channels}


class PlanTasksTests(unittest.TestCase):
    def reason_of(self, tasks, title):
        return next(t.skip_reason for t in tasks if t.title == title)

    def recipe_row(self, tasks):
        return next(t for t in tasks if t.kind == "recipe")

    def test_unchecked_recipe_gets_a_row_saying_it_was_not_ticked(self):
        tasks = app.plan_tasks("S", {"backup": False}, offered_577())
        self.assertEqual(self.reason_of(tasks, "关闭各 App 里的广告开关"), "未勾选，本次没有执行")

    def test_a_phone_without_a_recipe_says_so_instead_of_not_ticked(self):
        tasks = app.plan_tasks("S", {"backup": False}, offered_577(steps=()))
        self.assertEqual(self.recipe_row(tasks).skip_reason, "没有专用脚本，这一步要照清单手动做")

    def test_partly_ticked_segments_show_how_many_ran(self):
        tasks = app.plan_tasks("S", {"backup": False, "steps": ["桌面"]}, offered_577(steps=("桌面", "浏览器", "商店")))
        self.assertEqual(self.recipe_row(tasks).title, "关闭各 App 里的广告开关（1 / 3 段）")
        self.assertEqual(self.recipe_row(tasks).skip_reason, "")

    def test_all_segments_ticked_keep_the_plain_title(self):
        tasks = app.plan_tasks("S", {"backup": False, "steps": ["桌面", "浏览器"]}, offered_577(steps=("桌面", "浏览器")))
        self.assertEqual(self.recipe_row(tasks).title, "关闭各 App 里的广告开关")

    def test_channels_are_told_apart_unchecked_from_none_found(self):
        unchecked = app.plan_tasks("S", {"backup": False}, offered_577(channels=[{"pkg": "p", "id": "1", "name": "活动"}]))
        none = app.plan_tasks("S", {"backup": False}, offered_577(channels=[]))
        unscanned = app.plan_tasks("S", {"backup": False}, offered_577(channels=None))
        self.assertEqual(self.reason_of(unchecked, "关闭营销通知"), "未勾选，本次没有执行")
        self.assertEqual(self.reason_of(none, "关闭营销通知"), "没有扫描到可关闭的营销渠道")
        self.assertEqual(self.reason_of(unscanned, "关闭营销通知"), "通知扫描没有完成，本次没有关闭营销通知")

    def test_quickapp_and_ads_say_why_they_did_nothing(self):
        closed = app.plan_tasks("S", {"backup": False}, offered_577(quickapps=[{"name": "x", "closed": True}]))
        absent = app.plan_tasks("S", {"backup": False}, offered_577())
        hung = app.plan_tasks("S", {"backup": False}, offered_577(ads=[{"pkg": "p", "suspended": True}]))
        self.assertEqual(self.reason_of(closed, "关闭快应用"), "可关闭的快应用组件都已关闭")
        self.assertEqual(self.reason_of(absent, "关闭快应用"), "没有检测到快应用组件")
        self.assertEqual(self.reason_of(absent, "挂起广告组件"), "没有已知的广告组件")
        self.assertEqual(self.reason_of(hung, "挂起广告组件"), "广告组件已经挂起")

    def test_rows_keep_the_order_the_run_would_have_had(self):
        tasks = app.plan_tasks("S", {"backup": True}, offered_577())
        self.assertEqual([t.title for t in tasks],
                         ["存改动前的快照", "挂起广告组件", "关闭各 App 里的广告开关", "关闭营销通知",
                          "关闭快应用", "收尾"])

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
        api._work([self.skip_task(), app.Task("收尾", "run.py", ["-s", "t", "finish"], always_run=True)])
        self.assertEqual(len(api.runner.spawn_calls), 1, "没勾的项不该起子进程")
        first = api.job.results[0]
        self.assertEqual(first["rc"], 0, "没执行不算失败")
        self.assertTrue(first["skipped"])
        self.assertEqual(first["tail"], ["未勾选，本次没有执行"])

    def test_not_run_steps_stay_out_of_the_step_counter(self):
        api = self.make_api()
        api.job.total = 1
        api._work([self.skip_task(),
                   app.Task("收尾", "run.py", ["-s", "t", "finish"], always_run=True),
                   self.skip_task("挂起广告组件")])
        self.assertEqual(api.job.idx, 1)
        self.assertEqual(api.job.title, "收尾")

    def test_a_lost_phone_keeps_each_not_run_step_its_own_reason(self):
        api = self.make_api(spawns=[FakeProc(event_577("link_lost") + "\n手机和电脑的 adb 连接断开了\n", rc=1)])
        with patch.object(app, "adb_present", return_value=False):
            api._work([app.Task("广告开关", "run.py"),
                       self.skip_task("关闭快应用"),
                       app.Task("收尾", "run.py", always_run=True)])
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
                         ["挂起广告组件", "关闭各 App 里的广告开关", "关闭营销通知", "关闭快应用", "收尾"])
        self.assertEqual(tasks[2].skip_reason, "没有扫描到可关闭的营销渠道")

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
        # 对拍驱动只塞了 info：不能凭空多出四行，否则基线对不上
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


# ---------- 来源 tests/test_plan_exec_1106.py ----------
#   #1106：执行侧从计划字典换成 `Plan` 规格，排出来的任务与重试范围不变。
#   
#   前端 JSON 只在 `Api.start()` 收成对象；`Dispatcher.start()` / `plan_tasks()` / `Job` 收到字典时
#   只是宽容收（`Plan.from_json` 幂等）。任务清单的期望取自改前实现：旧树与新树的 12 个计划样本里
#   10 个逐字一致，差异只在列表字段被传成字符串的畸形输入（旧实现按字符展开，两个前端都不会发）。
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声



PLAN_1106 = {"backup": True, "steps": ["桌面", "商店"], "ref": True, "model": "M",
        "channels": [{"pkg": "p", "id": "1", "name": "活动"}], "quickapp": True, "ads": ["com.a"]}
OFFERED_1106 = {"steps": ["桌面", "商店", "浏览器"], "quickapps": [{"name": "x"}],
           "ads": [{"pkg": "p"}], "channels": [{"pkg": "p", "id": "1", "name": "活动"}]}
UNCHECKED_1106 = "未勾选，本次没有执行"


def row_1106(kind, rc=0, **fields):
    return {"title": kind, "kind": kind, "rc": rc, **fields}


def rows_1106(tasks):
    """任务清单的可观察形状：标题、脚本、参数、身份、跳过原因、停止后是否仍跑。"""
    return [(t.title, t.script, tuple(t.args), t.kind, t.skip_reason, t.always_run) for t in tasks]


class TaskListTests(unittest.TestCase):
    def test_a_full_selection_keeps_the_steps_order_and_titles(self):
        """旧树也绿，守的是不回退：同一份勾选排出的清单与改前逐字一致（#1106 的对拍样本）。"""
        self.assertEqual(rows_1106(app.plan_tasks("SER", PLAN_1106, OFFERED_1106)), [
            ("存改动前的快照", "run.py", ("-s", "SER", "backup"), "backup", "", False),
            ("挂起广告组件", "run.py", ("-s", "SER", "suspend", "com.a"), "ads", "", False),
            ("关闭各 App 里的广告开关（2 / 3 段）", "run.py",
             ("-s", "SER", "recipe", "桌面", "商店", "--ref"), "recipe", "", False),
            ("关闭营销通知", "chan_fast.py", (), "channels", "", False),
            ("关闭快应用", "run.py", ("-s", "SER", "quickapp", "off"), "quickapp", "", False),
            ("收尾", "run.py", ("-s", "SER", "finish"), "finish", "", True),
        ])

    def test_unchecked_steps_keep_their_skip_rows(self):
        """旧树也绿，守的是不回退：没勾的项仍各占一行并写明原因（#577）。"""
        self.assertEqual(rows_1106(app.plan_tasks("SER", {"backup": False}, OFFERED_1106)), [
            ("挂起广告组件", "", (), "ads", UNCHECKED_1106, False),
            ("关闭各 App 里的广告开关", "", (), "recipe", UNCHECKED_1106, False),
            ("关闭营销通知", "", (), "channels", UNCHECKED_1106, False),
            ("关闭快应用", "", (), "quickapp", UNCHECKED_1106, False),
            ("收尾", "run.py", ("-s", "SER", "finish"), "finish", "", True),
        ])


class EntryBoundaryTests(unittest.TestCase):
    """`Api.start()` 是唯一收前端 JSON 的地方；交给调度器的必须是对象，不能是字典。"""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def make_api(self):
        return app.Api(self._dir.name, runner=FakeRunner())

    def capture_start(self, api):
        seen = []
        api.dispatcher.start = lambda serial, plan, *a, **kw: seen.append(plan) or {"ok": True}
        return seen

    def test_the_entry_hands_the_dispatcher_a_spec(self):
        api = self.make_api()
        seen = self.capture_start(api)
        api.start("SER", dict(PLAN_1106))
        self.assertIsInstance(seen[0], Plan)
        self.assertEqual(seen[0].steps, ["桌面", "商店"])

    def test_the_run_state_keeps_a_spec(self):
        api = self.make_api()
        with patch.object(app.threading, "Thread", autospec=True):
            api.start("SER", dict(PLAN_1106))
        self.assertIsInstance(api.job.plan, Plan)

    def test_the_retry_round_hands_a_spec_with_only_the_named_segments(self):
        api = self.make_api()
        api.job = app.Job(serial="SER", t0=0, plan=Plan.from_json(PLAN_1106),
                          base_results=[row_1106("backup"), row_1106("recipe", 1, failed_steps=["商店"]),
                                        row_1106("finish")])
        seen = self.capture_start(api)
        api.retry()
        self.assertIsInstance(seen[0], Plan)
        self.assertEqual(seen[0].steps, ["商店"], "重试轮只带引擎点名的那一段")


class RetrySpecTests(unittest.TestCase):
    def test_the_retry_round_rebuilds_a_spec_object(self):
        plan = app.retry_plan(Plan.from_json(PLAN_1106),
                              [row_1106("backup"), row_1106("recipe", 1, failed_steps=["商店"]), row_1106("finish")])
        self.assertIsInstance(plan, Plan)
        self.assertEqual(plan.steps, ["商店"])

    def test_the_retry_round_holds_the_same_keys_as_the_first(self):
        first = Plan.from_json(PLAN_1106)
        plan = app.retry_plan(first, [row_1106("channels", 1), row_1106("recipe")])
        self.assertEqual(set(plan.to_json()), set(first.to_json()))
        self.assertEqual(Plan.from_json(plan.to_json()), plan, "重试轮的计划要能原样往返")

    def test_a_dict_from_the_previous_round_still_comes_back_as_a_spec(self):
        # 直接喂上一轮的字典也收（`from_json` 幂等），返回的仍是对象
        self.assertIsInstance(app.retry_plan(dict(PLAN_1106), [row_1106("recipe", 1)]), Plan)

    def test_nothing_left_returns_none(self):
        self.assertIsNone(app.retry_plan(Plan.from_json(PLAN_1106), [row_1106("backup"), row_1106("recipe"), row_1106("finish")]))


if __name__ == "__main__":
    unittest.main()
