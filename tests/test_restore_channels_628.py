"""还原营销通知合并历次备份里的清单（#628）：最近一次没关渠道时，之前关的也能打开。"""
import json
import tempfile
import unittest
from pathlib import Path

import fixtures
from fixtures import FakeRunner
from gui import app

fixtures.load_tool()
import chan_fast  # noqa: E402


def write(root, name, rows):
    d = Path(root, "backups", name)
    d.mkdir(parents=True, exist_ok=True)
    if rows is not None:
        (d / "channels.tsv").write_text("# 包名\t渠道id\t渠道名\t应用名\n" + "".join(r + "\n" for r in rows), encoding="utf-8")


def write_bytes(root, name, data):
    d = Path(root, "backups", name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "channels.tsv").write_bytes(data)


class RestoreChannelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent, self.paths = [], []

        def runs(script, *args):
            if script == "run.py" and "status-json" in args:
                return json.dumps({"info": {"model": "M1"}}) + "\n", "", 0
            if script == "chan_fast.py" and args[2] == "on":
                self.sent.append(Path(args[3]).read_text(encoding="utf-8"))
                self.paths.append(args[3])
                return "拨了 1 个\n", "", 0
            return None
        self.api = app.Api(self.tmp.name, runner=FakeRunner(runs=runs))

    def tearDown(self):
        self.tmp.cleanup()

    def loaded(self):
        """交给 `chan_fast.py on` 的那份清单按引擎自己的读法解析：写出去的必须真的读得回来。"""
        return chan_fast.load(self.paths[0])

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

    def test_legacy_list_in_the_gui_dir_is_still_merged(self):
        """旧树也绿，守的是不回退：0.4.0 及更早的客户端把关渠道清单写进 `<型号>-gui/channels.tsv`
        （#651 起客户端与 `run.py chan-scan` 都改写快照目录）。老机器上那份不做迁移，
        字典序上排在最前，照旧当「最新那份」合并进来。"""
        write(self.tmp.name, "M1-20261106-1040", ["com.a\tpromo\t推广\tA", "com.b\tnews\t资讯\tB"])
        write(self.tmp.name, "M1-gui", ["com.b\tnews\t资讯\tB", "com.c\tspam\t推广\tC"])
        self.api.restore("s", "channels")
        self.assertEqual(self.loaded(), [("com.b", "news", "资讯"), ("com.c", "spam", "推广"), ("com.a", "promo", "推广")])

    def test_list_saved_with_bom_is_readable(self):
        # AGENTS.md 让人手工删这份清单里的行，编辑器会按系统习惯另存（Windows 上带 BOM + CRLF）。
        # 首行故意是数据行：带 BOM 的表头本来就会被坏行过滤跳过，那样测不出 `utf-8-sig`。
        write_bytes(self.tmp.name, "M1-20261106-1040",
                    "com.a\tpromo\t推广\tA\r\ncom.b\tnews\t资讯\tB\r\n".encode("utf-8-sig"))
        self.api.restore("s", "channels")
        self.assertEqual(self.loaded(), [("com.a", "promo", "推广"), ("com.b", "news", "资讯")])

    def test_bad_row_in_an_old_list_is_skipped(self):
        # 坏行所在的备份从界面删不掉：不跳过就永远卡死这个型号的还原。第二条带 cid、包名里有空格，
        # 只按「有没有 cid」过滤拦不住它 —— 它进清单后 `load()` 会抛错。
        write(self.tmp.name, "M1-20261106-1040", ["残留坏行", "com.a promo\tpromo\t促销\tA", "com.b\tnews\t资讯\tB"])
        self.api.restore("s", "channels")
        self.assertEqual(self.loaded(), [("com.b", "news", "资讯")])

    def test_rows_differing_only_in_spaces_are_one_channel(self):
        write(self.tmp.name, "M1-20261106-1040", ["com.a \tpromo\t旧名\tA"])
        write(self.tmp.name, "M1-20261106-1053", ["com.a\tpromo\t推广\tA"])
        self.api.restore("s", "channels")
        rows = [r for r in self.sent[0].splitlines() if not r.startswith("#")]
        self.assertEqual(rows, ["com.a\tpromo\t推广\tA"])     # 真的合成一行，且用最近那条的名字


if __name__ == "__main__":
    unittest.main()
