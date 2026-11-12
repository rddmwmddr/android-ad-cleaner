"""结果摘要的唯一定义（#1189）：一段 tail 怎么说成一句话，两个宿主调同一份。

纯函数接缝 `summary.summarize()` 跑共享样例集；两个链路接缝各自断言结果行带的是同一句。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "android" / "app" / "src" / "main" / "python"))

from gui import app  # noqa: E402
import events  # noqa: E402
import summary  # noqa: E402
from aac_android import view  # noqa: E402


def cases():
    return json.loads((ROOT / "tests" / "summary_cases.json").read_text(encoding="utf-8"))


class PureFunctionTest(unittest.TestCase):
    """一句话从 tail 里怎么算出来：共享样例、已知行、认不出时的末行兜底。"""

    def test_shared_cases(self):
        """tests/summary_cases.json 是这个函数的样例集，两个宿主的链路用例再对同一批串。"""
        for case in cases():
            with self.subTest(case=case["name"]):
                tail = list(case["tail"]) + list(case.get("machine", []))
                self.assertEqual(summary.summarize({"tail": tail}), case["want"])

    def test_known_lines(self):
        known = [(["机型脚本跑完：关了 12 个，34 秒"], "关了 12 个开关"),
                 (["拨了 5 个", "仍开着: 1 个"], "关了 5 个渠道，复查仍开着 1 个"),
                 (["拨了 5 个"], "关了 5 个渠道"),
                 (["快照已存"], "已保存")]
        for tail, want in known:
            self.assertEqual(summary.summarize({"tail": tail}), want)

    def test_plugged_in_lines(self):
        """插电常亮两条只有桌面版会产出（收尾步），但口径归这里——手机版说同一句话（#1189）。"""
        self.assertEqual(summary.summarize({"tail": ["插电常亮已改回 1"]}), "插电常亮已改回 1")
        self.assertEqual(summary.summarize({"tail": ["插电常亮未改动"]}), "插电常亮未改动")

    def test_quickapp_counts_lines(self):
        tail = ["  快应用 com.a 已关闭", "  快应用 com.b 已关闭",
                "快应用组件已关闭（保留项除外）。请按常用入口核对效果；恢复：quickapp on"]
        self.assertEqual(summary.summarize({"tail": tail}), "2 个组件已关闭")

    def test_falls_back_to_last_line(self):
        self.assertEqual(summary.summarize({"tail": ["甲", "乙", ""]}), "乙")
        self.assertEqual(summary.summarize({"tail": []}), "")

    def test_machine_prefix_is_derived_from_events(self):
        """机器行记号只有一处定义：tool/events.py 两个前缀的公共段，别再写字面量。"""
        self.assertEqual(summary.MACHINE_PREFIX,
                         os.path.commonprefix([events.PREFIX, events.PAYLOAD_PREFIX]))
        for line in (events.PREFIX + '{"kind": "ui_busy"}',
                     events.PAYLOAD_PREFIX + '{"skeleton": "<node text=…>"}'):
            with self.subTest(line=line):
                self.assertEqual(summary.summarize({"tail": ["开始执行", line]}), "开始执行")


class HostLinksTest(unittest.TestCase):
    """两条链路接缝：桌面调度器的 poll 与手机版的 view.poll 给的都是同一句。"""

    ROWS = [
        {"title": "关闭各 App 里的广告开关", "kind": "recipe", "rc": 0, "sec": 3,
         "tail": ["  · 商店：核对 1 项，调整 0 项", "", "机型脚本跑完：关了 3 个，170 秒",
                  "未完成步骤：系统广告"]},
        {"title": "关闭快应用", "kind": "quickapp", "rc": 0, "skipped": True, "sec": 0,
         "tail": ["未勾选，本次没有执行"]},
        {"title": "收尾", "kind": "finish", "rc": 0, "sec": 1, "tail": ["插电常亮已改回 1"]},
        {"title": "关闭营销通知", "kind": "channels", "rc": 1, "sec": 8,
         "tail": ["拨了 2 个", "仍开着: 4 个"]},
    ]

    def test_desktop_poll_attaches_summary_to_every_result(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api.job = app.Job(serial="s", t0=0)
            api.job.running = False
            api.job.results = [dict(row) for row in self.ROWS]
            snap = api.poll()
        self.assertEqual([r["summary"] for r in snap["results"]],
                         [summary.summarize(row) for row in self.ROWS])
        self.assertEqual(snap["results"][1]["summary"], "未勾选，本次没有执行",
                         "跳过行的 tail 是原因文本，摘要就该是那一句")

    def test_phone_poll_gives_the_same_line(self):
        rows = self.ROWS

        class Api:
            def poll(self, since):
                return {"results": [dict(row) for row in rows], "cancel": False}

        run = view.poll(Api())
        self.assertEqual([r["summary"] for r in run["results"]],
                         [summary.summarize(row) for row in self.ROWS])

    def test_both_hosts_agree(self):
        """同一步在两块屏上给出同一句话——本票要修的就是这条。"""
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api.job = app.Job(serial="s", t0=0)
            api.job.running = False
            api.job.results = [dict(row) for row in self.ROWS]
            desktop = api.poll()["results"]

        rows = self.ROWS

        class Api:
            def poll(self, since):
                return {"results": [dict(row) for row in rows], "cancel": False}

        phone = view.poll(Api())["results"]
        self.assertEqual([r["summary"] for r in desktop], [r["summary"] for r in phone])


if __name__ == "__main__":
    unittest.main()
