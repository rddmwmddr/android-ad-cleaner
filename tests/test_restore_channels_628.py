"""还原营销通知合并历次备份里的清单（#628）：最近一次没关渠道时，之前关的也能打开。"""
import json
import tempfile
import unittest
from pathlib import Path

from fixtures import FakeRunner
from gui import app


def write(root, name, rows):
    d = Path(root, "backups", name)
    d.mkdir(parents=True, exist_ok=True)
    if rows is not None:
        (d / "channels.tsv").write_text("# 包名\t渠道id\t渠道名\t应用名\n" + "".join(r + "\n" for r in rows), encoding="utf-8")


class RestoreChannelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []

        def runs(script, *args):
            if script == "run.py" and "status-json" in args:
                return json.dumps({"info": {"model": "M1"}}) + "\n", "", 0
            if script == "chan_fast.py" and args[2] == "on":
                self.sent.append(Path(args[3]).read_text(encoding="utf-8"))
                return "拨了 1 个\n", "", 0
            return None
        self.api = app.Api(self.tmp.name, runner=FakeRunner(runs=runs))

    def tearDown(self):
        self.tmp.cleanup()

    def test_older_list_is_used_when_latest_run_closed_nothing(self):
        write(self.tmp.name, "M1-20261106-1040", ["com.a\tpromo\t推广\tA"])
        write(self.tmp.name, "M1-20261106-1053", None)
        self.api.restore("s", "channels")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("com.a\tpromo\t推广\tA", self.sent[0])

    def test_lists_are_merged_newest_first_without_duplicates(self):
        write(self.tmp.name, "M1-20261106-1040", ["com.a\tpromo\t旧名\tA", "com.b\tnews\t资讯\tB"])
        write(self.tmp.name, "M1-20261106-1053", ["com.a\tpromo\t推广\tA"])
        self.api.restore("s", "channels")
        rows = [r for r in self.sent[0].splitlines() if not r.startswith("#")]
        self.assertEqual(rows, ["com.a\tpromo\t推广\tA", "com.b\tnews\t资讯\tB"])

    def test_no_list_anywhere(self):
        write(self.tmp.name, "M1-20261106-1053", None)
        self.assertEqual(self.api.restore("s", "channels"), "没有找到上次关掉的营销通知清单")
        self.assertEqual(self.sent, [])

    def test_other_models_are_ignored(self):
        write(self.tmp.name, "M10-20261106-1040", ["com.z\tpromo\t推广\tZ"])
        self.assertEqual(self.api.restore("s", "channels"), "没有找到上次关掉的营销通知清单")


if __name__ == "__main__":
    unittest.main()
