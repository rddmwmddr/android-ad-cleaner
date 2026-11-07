"""关渠道清单写进本次运行的快照目录，不再写历次共用的 `<型号>-gui`（#651）。

客户端每次运行开始时有一步 `run.py backup`，它会新建一个 `<型号>-<时间>` 目录；关营销通知的清单
跟着写进这一份，历次清单才各自留得住。都写进 `<型号>-gui` 时后一次会覆盖前一次，还原只能找回最后一批。
"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import datetime
import json
import tempfile
import unittest
from pathlib import Path

import fixtures
from fixtures import FakeRunner, job_stub
from gui import app

fixtures.load_tool()
import chan_fast  # noqa: E402
from backups import Backups  # noqa: E402

MODEL = "M1"


def batch(*rows):
    return [{"pkg": pkg, "id": cid, "name": name, "app": app_} for pkg, cid, name, app_ in rows]


class ChannelsListLandingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name, "backups")
        self.paths = []

        def runs(script, *args):
            if script == "run.py" and "status-json" in args:
                return json.dumps({"info": {"model": MODEL}}) + "\n", "", 0
            if script == "chan_fast.py" and args[2] == "on":
                self.paths.append(args[3])
                return "拨了 1 个\n", "", 0
            return None

        self.api = app.Api(self.tmp.name, runner=FakeRunner(runs=runs))
        self.api.job = job_stub(model=MODEL)

    def run_once(self, channels):
        self.api._work([app.Task("关闭营销通知", "chan_fast.py", uses_ui=True, channels=channels)])

    def snapshot_dirs(self):
        return sorted(p for p in self.root.iterdir() if p.name != f"{MODEL}-gui")

    def test_two_runs_keeping_different_batches_are_both_restorable(self):
        # 跑过一次还原的机器上有 `<型号>-gui`（放合并后的 channels-restore.tsv）；
        # 每次运行开头的 `run.py backup` 又会新建一份快照目录。两次运行各在自己的目录里留一份清单。
        Path(self.root, f"{MODEL}-gui").mkdir(parents=True)
        Backups(self.root).create(MODEL, when=datetime.datetime(2026, 11, 6, 10, 40))
        self.run_once(batch(("com.a", "promo", "推广", "A")))
        Backups(self.root).create(MODEL, when=datetime.datetime(2026, 11, 6, 10, 53))
        self.run_once(batch(("com.b", "news", "资讯", "B")))

        self.api.restore("s", "channels")

        self.assertEqual(len(self.paths), 1)
        self.assertEqual(chan_fast.load(self.paths[0]),
                         [("com.b", "news", "资讯"), ("com.a", "promo", "推广")])

    def test_list_goes_to_a_new_snapshot_when_there_is_none(self):
        self.run_once(batch(("com.a", "promo", "推广", "A")))

        dirs = self.snapshot_dirs()
        self.assertEqual(len(dirs), 1, f"应新建一份快照目录，实际 {[p.name for p in self.root.iterdir()]}")
        self.assertRegex(dirs[0].name, rf"^{MODEL}-\d{{8}}-\d{{4}}$")
        self.assertEqual(chan_fast.load(str(dirs[0] / "channels.tsv")), [("com.a", "promo", "推广")])

    def test_restore_scratch_dir_never_receives_the_list(self):
        # 跑过一次还原的机器都有 `<型号>-gui`（放合并后的 channels-restore.tsv）。
        # 它不能接关渠道的清单：那是历次共用的目录，后一次会覆盖前一次。
        gui = Path(self.root, f"{MODEL}-gui")
        gui.mkdir(parents=True)
        (gui / "channels-restore.tsv").write_text("# 上一次还原的合并清单\n", encoding="utf-8")

        self.run_once(batch(("com.a", "promo", "推广", "A")))

        self.assertFalse((gui / "channels.tsv").exists())
        self.assertEqual(chan_fast.load(str(self.snapshot_dirs()[0] / "channels.tsv")),
                         [("com.a", "promo", "推广")])


if __name__ == "__main__":
    unittest.main()
