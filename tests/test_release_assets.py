"""下载页 REL 与 Release 附件的对账（`tool/release_assets.py`，#1003）。

静态那一半（`REL.files` 的 id 冻结、file 里的版本号）在 `tests/test_rules_guards.py` 的
`ReleaseGuards`；这里只测解析、比对与退出码，不联网、不需要 `gh`。
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

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
    def test_reads_version_ids_and_files(self):
        version, ids, files = release_assets.read_page(PAGE.format(mac="App-1.2.3-mac.dmg",
                                                                   apk="App-1.2.3-arm64.apk"))
        self.assertEqual(version, "1.2.3")
        self.assertEqual(ids, ["mac-arm64", "android"])
        self.assertEqual(files, ["App-1.2.3-mac.dmg", "App-1.2.3-arm64.apk"])

    def test_missing_block_reads_as_empty(self):
        """页面结构变了要当场看得出来，不能让空清单冒充「一致」。"""
        self.assertEqual(release_assets.read_page("<html></html>"), (None, [], []))


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

    def run_main(self, release, argv=(), error=None):
        """返回 (退出码, stdout, stderr)；`fetch` 换成给定清单或抛出。"""
        def fetch(tag):
            if error:
                raise RuntimeError(error)
            return list(release)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_assets.main(("tool", *argv), fetch=fetch, page=self.page)
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
        _, _, reverse = self.run_main(("App-1.2.3-mac.dmg", "App-1.2.3-arm64.apk", "extra.zip"))
        self.assertIn("Release 有、页面没有：extra.zip", reverse)

    def test_fetch_failure_exits_two_and_says_so(self):
        """取不到数不等于对不上：网络抖动、API 限额与真的不一致要看得出区别。"""
        code, _, err = self.run_main((), error="API rate limit exceeded")
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("取不到", err)
        self.assertIn("API rate limit exceeded", err)
        self.assertNotIn("对不上", err)

    def test_unreadable_page_exits_two(self):
        self.page.write_text("<html></html>", encoding="utf-8")
        code, _, err = self.run_main(self.page_files)
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("REL", err)

    def test_tag_defaults_to_the_page_version(self):
        seen = []

        def fetch(tag):
            seen.append(tag)
            return list(self.page_files)

        with contextlib.redirect_stdout(io.StringIO()):
            code = release_assets.main(("tool",), fetch=fetch, page=self.page)
        self.assertEqual(code, release_assets.EXIT_OK)
        self.assertEqual(seen, ["v1.2.3"])


if __name__ == "__main__":
    unittest.main()
