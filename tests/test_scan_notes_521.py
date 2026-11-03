"""#521：扫描的排除计数要经正式入口到达用户。

引擎把三条排除计数写在 scan 成功路径的 stderr；客户端过去只在失败时读它。这里守的是
「成功时也读、原样带出、失败不残留」——不按中文文案挑行，流里给什么就带什么。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import FakeRunner
from gui import app

NOTE = "另有 3 个前台服务渠道未列入清单"


class ScanNotesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)

    def make_api(self, out="", err="", rc=0):
        api = app.Api(self.directory.name, runner=FakeRunner(runs=(out, err, rc)))
        api._adb = Mock(return_value="Android Debug Bridge version 1.0.41")
        return api

    def test_scan_returns_the_engine_notes_alongside_the_candidates(self):
        api = self.make_api(out="com.shop\tpromo\t活动优惠\n", err=NOTE + "\n\n")
        result = api.chan_scan("test")
        self.assertEqual([r["pkg"] for r in result["chans"]], ["com.shop"])
        self.assertEqual(result["notes"], [NOTE])

    def test_notes_are_carried_whatever_their_wording(self):
        api = self.make_api(err="扫描用时 12 秒\n")
        self.assertEqual(api.chan_scan("test")["notes"], ["扫描用时 12 秒"])

    def test_scan_without_notes_returns_an_empty_list(self):
        api = self.make_api(out="com.shop\tpromo\t活动优惠\n")
        self.assertEqual(api.chan_scan("test")["notes"], [])

    def test_failed_scan_does_not_keep_the_previous_notes(self):
        replies = iter([("com.shop\tpromo\t活动优惠\n", NOTE + "\n", 0),
                        ("", "读取失败\n", 1)])
        api = app.Api(self.directory.name, runner=FakeRunner(runs=lambda *a: next(replies)))
        api._adb = Mock(return_value="Android Debug Bridge version 1.0.41")
        api.chan_scan("test")
        self.assertIn("读取失败", api.chan_scan("test")["error"])
        self.assertEqual(api.last_scan_notes, [])
        self.assertNotIn("通知扫描附注", api.diagnostics())

    def test_an_unexpected_failure_does_not_keep_the_previous_notes(self):
        replies = iter([("com.shop\tpromo\t活动优惠\n", NOTE + "\n", 0), ValueError("boom")])
        api = app.Api(self.directory.name, runner=FakeRunner(runs=lambda *a: next(replies)))
        api.chan_scan("test")
        with self.assertRaises(ValueError):
            api.chan_scan("test")
        self.assertEqual(api.last_scan_notes, [])

    def test_diagnostics_carry_the_scan_notes_on_one_line(self):
        locked = "另有 2 个渠道属于系统锁定、不允许关闭的系统应用，未列入清单"
        api = self.make_api(err=NOTE + "\n" + locked + "\n")
        api.chan_scan("test")
        self.assertIn(f"- 通知扫描附注：{NOTE}；{locked}", api.diagnostics())


if __name__ == "__main__":
    unittest.main()
