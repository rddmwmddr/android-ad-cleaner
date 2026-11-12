"""#1106：执行侧从计划字典换成 `Plan` 规格，排出来的任务与重试范围不变。

前端 JSON 只在 `Api.start()` 收成对象；`Dispatcher.start()` / `plan_tasks()` / `Job` 收到字典时
只是宽容收（`Plan.from_json` 幂等）。任务清单的期望取自改前实现：旧树与新树的 12 个计划样本里
10 个逐字一致，差异只在列表字段被传成字符串的畸形输入（旧实现按字符展开，两个前端都不会发）。
"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures import FakeRunner
from gui import app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
from plan import Plan                      # noqa: E402

PLAN = {"backup": True, "steps": ["桌面", "商店"], "ref": True, "model": "M",
        "channels": [{"pkg": "p", "id": "1", "name": "活动"}], "quickapp": True, "ads": ["com.a"]}
OFFERED = {"steps": ["桌面", "商店", "浏览器"], "quickapps": [{"name": "x"}],
           "ads": [{"pkg": "p"}], "channels": [{"pkg": "p", "id": "1", "name": "活动"}]}
UNCHECKED = "未勾选，本次没有执行"


def row(kind, rc=0, **fields):
    return {"title": kind, "kind": kind, "rc": rc, **fields}


def rows(tasks):
    """任务清单的可观察形状：标题、脚本、参数、身份、跳过原因、停止后是否仍跑。"""
    return [(t.title, t.script, tuple(t.args), t.kind, t.skip_reason, t.always_run) for t in tasks]


class TaskListTests(unittest.TestCase):
    def test_a_full_selection_keeps_the_steps_order_and_titles(self):
        """旧树也绿，守的是不回退：同一份勾选排出的清单与改前逐字一致（#1106 的对拍样本）。"""
        self.assertEqual(rows(app.plan_tasks("SER", PLAN, OFFERED)), [
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
        self.assertEqual(rows(app.plan_tasks("SER", {"backup": False}, OFFERED)), [
            ("挂起广告组件", "", (), "ads", UNCHECKED, False),
            ("关闭各 App 里的广告开关", "", (), "recipe", UNCHECKED, False),
            ("关闭营销通知", "", (), "channels", UNCHECKED, False),
            ("关闭快应用", "", (), "quickapp", UNCHECKED, False),
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
        api.start("SER", dict(PLAN))
        self.assertIsInstance(seen[0], Plan)
        self.assertEqual(seen[0].steps, ["桌面", "商店"])

    def test_the_run_state_keeps_a_spec(self):
        api = self.make_api()
        with patch.object(app.threading, "Thread", autospec=True):
            api.start("SER", dict(PLAN))
        self.assertIsInstance(api.job.plan, Plan)

    def test_the_retry_round_hands_a_spec_with_only_the_named_segments(self):
        api = self.make_api()
        api.job = app.Job(serial="SER", t0=0, plan=Plan.from_json(PLAN),
                          base_results=[row("backup"), row("recipe", 1, failed_steps=["商店"]),
                                        row("finish")])
        seen = self.capture_start(api)
        api.retry()
        self.assertIsInstance(seen[0], Plan)
        self.assertEqual(seen[0].steps, ["商店"], "重试轮只带引擎点名的那一段")


class RetrySpecTests(unittest.TestCase):
    def test_the_retry_round_rebuilds_a_spec_object(self):
        plan = app.retry_plan(Plan.from_json(PLAN),
                              [row("backup"), row("recipe", 1, failed_steps=["商店"]), row("finish")])
        self.assertIsInstance(plan, Plan)
        self.assertEqual(plan.steps, ["商店"])

    def test_the_retry_round_holds_the_same_keys_as_the_first(self):
        first = Plan.from_json(PLAN)
        plan = app.retry_plan(first, [row("channels", 1), row("recipe")])
        self.assertEqual(set(plan.to_json()), set(first.to_json()))
        self.assertEqual(Plan.from_json(plan.to_json()), plan, "重试轮的计划要能原样往返")

    def test_a_dict_from_the_previous_round_still_comes_back_as_a_spec(self):
        # 直接喂上一轮的字典也收（`from_json` 幂等），返回的仍是对象
        self.assertIsInstance(app.retry_plan(dict(PLAN), [row("recipe", 1)]), Plan)

    def test_nothing_left_returns_none(self):
        self.assertIsNone(app.retry_plan(Plan.from_json(PLAN), [row("backup"), row("recipe"), row("finish")]))


if __name__ == "__main__":
    unittest.main()
