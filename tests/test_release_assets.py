"""下载页 REL 与 Release 附件的对账（`tool/release_assets.py`，#1003）。

静态那一半（`REL.files` 的 id 冻结、file 里的版本号）在 `tests/test_rules_guards.py` 的
`ReleaseGuards`；这里只测解析、比对与退出码，不联网、不需要 `gh`。
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tool import release_assets

PAGE = """const REL = {{
  version: "1.2.3",
  github: "https://example.invalid/v1.2.3/",
  files: [
    {{ id: "mac-arm64", file: "{mac}", sha: "1" }},
    {{ id: "android", file: "{apk}", sha: "2" }},
  ],
}};
"""


class ReadPageTests(unittest.TestCase):
    def test_reads_version_and_pairs_each_entry_with_its_file(self):
        version, entries = release_assets.read_page(
            PAGE.format(mac="App-1.2.3-mac.dmg", apk="App-1.2.3-arm64.apk"))
        self.assertEqual(version, "1.2.3")
        self.assertEqual(entries, [("mac-arm64", "App-1.2.3-mac.dmg"),
                                   ("android", "App-1.2.3-arm64.apk")])

    def test_missing_block_reads_as_empty(self):
        """页面结构变了要当场看得出来，不能让空清单冒充「一致」。"""
        self.assertEqual(release_assets.read_page("<html></html>"), (None, []))

    def test_unpaired_entry_reads_as_empty(self):
        """id 与 file 条数对不上时不配对：宁可报「读不到」，也不给一份错位清单。"""
        broken = 'const REL = {\n  version: "1.2.3",\n  files: [\n    { id: "a" },\n' \
                 '    { id: "b", file: "B" },\n  ],\n};\n'
        self.assertEqual(release_assets.read_page(broken), (None, []))


class ReadEntriesTests(unittest.TestCase):
    """回填页面要的是四个字段，`read_entries` 是这一层的唯一入口（#1135）。"""

    PAGE = """const REL = {
  version: "1.2.3",
  github: "https://example.invalid/v1.2.3/",
  files: [
    { id: "mac-arm64", title: "Mac", file: "App-1.2.3-mac-arm64.dmg", size: "40.4 MB",
      note: "公证", sha: "aa" },
    { id: "android", title: "安卓", file: "App-1.2.3-android-arm64.apk", size: "52.8 MB",
      note: "不用连电脑", sha: "bb" },
  ],
};
"""

    def test_reads_every_data_field_of_a_card(self):
        version, entries = release_assets.read_entries(self.PAGE)
        self.assertEqual(version, "1.2.3")
        self.assertEqual(entries, [
            release_assets.Entry("mac-arm64", "App-1.2.3-mac-arm64.dmg", "40.4 MB", "aa"),
            release_assets.Entry("android", "App-1.2.3-android-arm64.apk", "52.8 MB", "bb"),
        ])

    def test_missing_field_comes_back_empty(self):
        """字段缺失不在这里拒绝，由回填那一层判完整性：解析只负责如实报出读到什么。"""
        broken = self.PAGE.replace(' size: "40.4 MB",', "")
        _, entries = release_assets.read_entries(broken)
        self.assertEqual(entries[0].size, "")

    def test_duplicate_field_reads_as_missing(self):
        """同一张卡片里出现两个 `file:`：分不清哪个是真的，按读不出处理，不挑第一个。"""
        doubled = self.PAGE.replace(
            'file: "App-1.2.3-mac-arm64.dmg"',
            'file: "App-1.2.3-mac-arm64.dmg", file: "dup"')
        _, entries = release_assets.read_entries(doubled)
        self.assertEqual(entries[0].file, "")
        self.assertEqual(release_assets.read_page(doubled), (None, []))

    def test_missing_block_reads_as_empty(self):
        self.assertEqual(release_assets.read_entries("<html></html>"), (None, []))


class HumanSizeTests(unittest.TestCase):
    def test_keeps_the_historical_page_wording(self):
        """历史页面两个真实值：40.4 与 46.0，格式漂了人眼比对就对不上了。"""
        self.assertEqual(release_assets.human_size(40404808), "40.4 MB")
        self.assertEqual(release_assets.human_size(45995322), "46.0 MB")

    def test_rounds_half_up_not_to_even(self):
        self.assertEqual(release_assets.human_size(1_050_000), "1.1 MB")
        self.assertEqual(release_assets.human_size(2), "0.0 MB")


class FetchTests(unittest.TestCase):
    def test_fetch_release_keeps_name_size_and_digest(self):
        rows = {"assets": [{"name": "a.bin", "size": 12, "digest": "sha256:abcd"},
                           {"name": "b.bin", "size": 7}]}
        with mock.patch.object(release_assets, "run_gh", return_value=json.dumps(rows)):
            self.assertEqual(
                release_assets.fetch_release("v1"),
                [release_assets.Asset("a.bin", 12, "sha256:abcd"),
                 release_assets.Asset("b.bin", 7, "")])

    def test_fetch_assets_is_the_name_projection(self):
        """名字清单降成 `fetch_release` 的一行投影：调用方与用例都不用改。"""
        assets = [release_assets.Asset("a.bin", 1, ""), release_assets.Asset("b.bin", 2, "")]
        with mock.patch.object(release_assets, "fetch_release", return_value=assets):
            self.assertEqual(release_assets.fetch_assets("v1"), ["a.bin", "b.bin"])


class CompareTests(unittest.TestCase):
    def test_consistent_sets_are_empty(self):
        self.assertEqual(release_assets.compare(["a", "b"], ["b", "a"]), ([], []))

    def test_page_side_name_missing_from_release(self):
        """页面上有的附件名在 Release 里找不到——用户点下去就是 404。"""
        self.assertEqual(release_assets.compare(["a", "b"], ["a"]), (["b"], []))

    def test_release_side_name_missing_from_page(self):
        self.assertEqual(release_assets.compare(["a"], ["a", "c"]), ([], ["c"]))

    def test_checksum_manifest_is_not_a_download_card(self):
        """`SHA256SUMS.txt` 每次都随版本上传，页面上没有入口，不算「多了个附件」。"""
        self.assertEqual(release_assets.compare(["a"], ["a", "SHA256SUMS.txt"]), ([], []))


class MainTests(unittest.TestCase):
    page_files = ("App-1.2.3-mac.dmg", "App-1.2.3-arm64.apk")

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.page = Path(self.dir.name) / "index.html"
        self.page.write_text(PAGE.format(mac=self.page_files[0], apk=self.page_files[1]),
                             encoding="utf-8")
        self.calls = []

    def run_main(self, release, argv=(), error=None):
        """返回 (退出码, stdout, stderr)；`fetch` 换成给定清单或抛出，调用记进 self.calls。"""
        def fetch(tag):
            self.calls.append(tag)
            if error:
                raise RuntimeError(error)
            return list(release)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_assets.main(argv, fetch=fetch, page=self.page)
        return code, out.getvalue(), err.getvalue()

    def test_consistent_exits_zero(self):
        code, out, err = self.run_main(self.page_files + ("SHA256SUMS.txt",))
        self.assertEqual(code, release_assets.EXIT_OK, err)
        self.assertIn("一致", out)

    def test_mismatch_exits_one_and_names_both_lists(self):
        code, _, err = self.run_main(("App-1.2.3-mac.dmg",), argv=("v9.9.9",))
        self.assertEqual(code, release_assets.EXIT_MISMATCH)
        self.assertIn("v9.9.9", err)
        self.assertIn("页面有、Release 没有：App-1.2.3-arm64.apk", err)
        _, _, reverse = self.run_main(self.page_files + ("extra.zip",))
        self.assertIn("Release 有、页面没有：extra.zip", reverse)

    def test_fetch_failure_exits_two_and_says_so(self):
        """取不到数不等于对不上：网络抖动、API 限额与真的不一致要看得出区别。"""
        code, _, err = self.run_main((), error="API rate limit exceeded")
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("取不到", err)
        self.assertIn("API rate limit exceeded", err)
        self.assertNotIn("对不上", err)

    def test_unreadable_page_exits_two_without_asking_github(self):
        """读不到 REL 时不该先去取数：剩下的比没有意义，白打一次 API。"""
        self.page.write_text("<html></html>", encoding="utf-8")
        code, _, err = self.run_main(self.page_files)
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("REL", err)
        self.assertEqual(self.calls, [], "读不到 REL 时不该调用 gh")

    def test_tag_defaults_to_the_page_version(self):
        code, _, err = self.run_main(self.page_files)
        self.assertEqual(code, release_assets.EXIT_OK, err)
        self.assertEqual(self.calls, ["v1.2.3"])


if __name__ == "__main__":
    unittest.main()
