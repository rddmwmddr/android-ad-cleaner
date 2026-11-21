"""下载页 REL 与 Release 附件的对账（`devtools/release_assets.py`，#1136，沿用 #1003）。

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

from fixtures import FakeRunner
from devtools import release_assets

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
        # 有卡片却没有 version：`not found or not entries` 只认「缺任一」为读不出，别退成 `and`
        broken = 'const REL = {\n  files: [\n    { id: "a", file: "A" },\n  ],\n};\n'
        self.assertEqual(release_assets.read_entries(broken), (None, []))


class MapEntriesTests(unittest.TestCase):
    """`map_entries` 拼回的文本必须逐字等于原文：卡片边界按 `id:` 切，回填只动 `fn` 返回的那段。"""

    def test_a_round_trip_keeps_every_byte(self):
        # 三张卡片：只两张时「取下一张的起点」与「取上一张的起点」对首尾两侧恰好相同，测不出错位
        block = ('version: "1.2.3",\nfiles: [\n'
                 '    { id: "a", file: "A", sha: "1" },\n'
                 '    { id: "b", file: "B", sha: "2" },\n'
                 '    { id: "c", file: "C", sha: "3" },\n  ],\n')
        self.assertEqual(release_assets.map_entries(block, lambda _id, chunk: chunk), block)



class HumanSizeTests(unittest.TestCase):
    def test_keeps_the_historical_page_wording(self):
        """历史页面两个真实值：40.4 与 46.0，格式漂了人眼比对就对不上了。"""
        self.assertEqual(release_assets.human_size(40404808), "40.4 MB")
        self.assertEqual(release_assets.human_size(45995322), "46.0 MB")

    def test_rounds_half_up_not_to_even(self):
        self.assertEqual(release_assets.human_size(1_050_000), "1.1 MB")
        self.assertEqual(release_assets.human_size(2), "0.0 MB")


class FetchTests(unittest.TestCase):
    """取数层：一次 `gh release view --json assets`，执行器由调用方注入，用例不联网（#1218）。"""

    def test_fetch_release_keeps_name_size_and_digest(self):
        rows = {"assets": [{"name": "a.bin", "size": 12, "digest": "sha256:abcd"},
                           {"name": "b.bin", "size": 7}]}
        runner = FakeRunner(runs=(json.dumps(rows), "", 0))
        self.assertEqual(
            release_assets.fetch_release("v1", runner.run),
            [release_assets.Asset("a.bin", 12, "sha256:abcd"),
             release_assets.Asset("b.bin", 7, "")])
        self.assertEqual((runner.run_calls[0].script, runner.run_calls[0].args),
                         ("gh", ("release", "view", "v1", "--json", "assets")))

    def test_fetch_release_failure_raises_gh_error(self):
        """取不到附件：非零退出与输出不是 JSON 都归 GhError，main 只处理一种失败。"""
        for reply in (("boom", "API rate limit exceeded", 1), ("not json", "", 0)):
            with self.subTest(reply=reply):
                runner = FakeRunner(runs=reply)
                with self.assertRaises(release_assets.GhError):
                    release_assets.fetch_release("v1", runner.run)

    def test_unreachable_gh_is_a_gh_error(self):
        """`gh` 不在 PATH 上：OSError 也变成 GhError，调用方不必分辨三种失败。"""
        runner = FakeRunner(runs=OSError("no gh"))
        with self.assertRaises(release_assets.GhError):
            release_assets.fetch_release("v1", runner.run)

    def test_failure_names_the_gh_command(self):
        """报错里要看出是哪条 `gh` 命令失败：source 漏传就只剩「None 退出码非零」。"""
        runner = FakeRunner(runs=("boom", "API rate limit exceeded", 1))
        with self.assertRaises(release_assets.GhError) as caught:
            release_assets.fetch_release("v1", runner.run)
        self.assertIn("`gh release view v1`", str(caught.exception))

    def test_bad_asset_shape_names_the_tag_and_leaves_name_size_defaults(self):
        """行缺 name / size 时留空串与 0；整份形状读不出时报错要带 tag。"""
        runner = FakeRunner(runs=(json.dumps({"assets": [{"digest": "sha256:abcd"}]}), "", 0))
        self.assertEqual(release_assets.fetch_release("v1", runner.run),
                         [release_assets.Asset("", 0, "sha256:abcd")])
        runner = FakeRunner(runs=(json.dumps({"assets": 5}), "", 0))
        with self.assertRaises(release_assets.GhError) as caught:
            release_assets.fetch_release("v1", runner.run)
        self.assertIn("读不出 v1 的附件", str(caught.exception))

    def test_fetch_assets_is_the_name_projection_and_forwards_the_runner(self):
        """名字清单降成 `fetch_release` 的一行投影，注入的执行器要一路传下去。"""
        runner = FakeRunner(runs=("{}", "", 0))
        assets = [release_assets.Asset("a.bin", 1, ""), release_assets.Asset("b.bin", 2, "")]
        with mock.patch.object(release_assets, "fetch_release", return_value=assets) as fetch:
            self.assertEqual(release_assets.fetch_assets("v1", runner.run), ["a.bin", "b.bin"])
        fetch.assert_called_once_with("v1", runner.run)


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


MAC_FILE, APK_FILE = "App-1.2.3-mac.dmg", "App-1.2.3-arm64.apk"
MAC_SHA, APK_SHA = "a" * 64, "b" * 64
MAC_BYTES, APK_BYTES = 40_404_808, 52_800_000     # 页面上写作 40.4 MB / 52.8 MB

META_PAGE = """const REL = {{
  version: "1.2.3",
  github: "https://example.invalid/v1.2.3/",
  files: [
    {{ id: "mac-arm64", file: "{mac}", size: "40.4 MB", sha: "{mac_sha}" }},
    {{ id: "android", file: "{apk}", size: "52.8 MB", sha: "{apk_sha}" }},
  ],
}};
"""


def matching_entries():
    return [release_assets.Entry("mac-arm64", MAC_FILE, "40.4 MB", MAC_SHA),
            release_assets.Entry("android", APK_FILE, "52.8 MB", APK_SHA)]


def matching_assets():
    return [release_assets.Asset(MAC_FILE, MAC_BYTES, "sha256:" + MAC_SHA),
            release_assets.Asset(APK_FILE, APK_BYTES, "sha256:" + APK_SHA)]


class CompareMetaTests(unittest.TestCase):
    """`compare_meta` 把三类差异分开带出来：只在一侧的名字、大小、sha（#1136）。"""

    def test_identical_assets_leave_no_differences(self):
        diff = release_assets.compare_meta(matching_entries(), matching_assets())
        self.assertEqual((diff.only_page, diff.only_release, diff.size, diff.sha, diff.unverified),
                         ([], [], [], [], []))

    def test_size_difference_names_both_sides(self):
        assets = matching_assets()
        assets[1] = assets[1]._replace(size=53_000_000)
        diff = release_assets.compare_meta(matching_entries(), assets)
        self.assertEqual(diff.size, [(APK_FILE, "52.8 MB", "53.0 MB")])
        self.assertEqual((diff.sha, diff.only_page, diff.only_release), ([], [], []))

    def test_sha_difference_names_both_sides(self):
        other = "c" * 64
        assets = matching_assets()
        assets[1] = assets[1]._replace(digest="sha256:" + other)
        diff = release_assets.compare_meta(matching_entries(), assets)
        self.assertEqual(diff.sha, [(APK_FILE, APK_SHA, other)])
        self.assertEqual((diff.size, diff.only_page, diff.only_release), ([], [], []))

    def test_both_classes_are_reported_side_by_side(self):
        other = "c" * 64
        assets = matching_assets()
        assets[1] = release_assets.Asset(APK_FILE, 53_000_000, "sha256:" + other)
        diff = release_assets.compare_meta(matching_entries(), assets)
        self.assertEqual(diff.size, [(APK_FILE, "52.8 MB", "53.0 MB")])
        self.assertEqual(diff.sha, [(APK_FILE, APK_SHA, other)])

    def test_missing_digest_is_unverified_not_a_mismatch(self):
        """Release 没给摘要时 sha 根本没法比：报「取不到数」，不栽赃成不一致。"""
        assets = matching_assets()
        assets[1] = assets[1]._replace(digest="")
        diff = release_assets.compare_meta(matching_entries(), assets)
        self.assertEqual(diff.unverified, [APK_FILE])
        self.assertEqual((diff.size, diff.sha), ([], []))

    def test_page_side_empty_field_is_a_mismatch_not_unverified(self):
        entries = matching_entries()
        entries[0] = entries[0]._replace(sha="")
        diff = release_assets.compare_meta(entries, matching_assets())
        self.assertEqual(diff.sha, [(MAC_FILE, "（空）", MAC_SHA)])
        self.assertEqual(diff.unverified, [])

    def test_name_on_one_side_only_is_not_field_compared(self):
        entries = matching_entries() + [release_assets.Entry("win-zip", "C.zip", "", "")]
        diff = release_assets.compare_meta(entries, matching_assets())
        self.assertEqual(diff.only_page, ["C.zip"])
        self.assertEqual((diff.size, diff.sha), ([], []))

    def test_checksum_manifest_is_not_compared(self):
        assets = matching_assets() + [release_assets.Asset("SHA256SUMS.txt", 100, "")]
        diff = release_assets.compare_meta(matching_entries(), assets)
        self.assertEqual((diff.only_page, diff.only_release, diff.size, diff.sha, diff.unverified),
                         ([], [], [], [], []))


class MainTests(unittest.TestCase):
    page_files = ("App-1.2.3-mac.dmg", "App-1.2.3-arm64.apk")

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.page = Path(self.dir.name) / "index.html"
        self.page.write_text(PAGE.format(mac=self.page_files[0], apk=self.page_files[1]),
                             encoding="utf-8")
        self.calls = []

    @staticmethod
    def assets(*names):
        return [release_assets.Asset(name, 1, "sha256:" + "0" * 64) for name in names]

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
        code, out, err = self.run_main(self.assets(*self.page_files, "SHA256SUMS.txt"))
        self.assertEqual(code, release_assets.EXIT_OK, err)
        self.assertIn("REL.files 一致。", out)

    def test_mismatch_exits_one_and_names_both_lists(self):
        code, _, err = self.run_main(self.assets("App-1.2.3-mac.dmg"), argv=("v9.9.9",))
        self.assertEqual(code, release_assets.EXIT_MISMATCH)
        self.assertIn("v9.9.9", err)
        self.assertIn("index.html", err, "报错里要点出比的是哪一页")
        self.assertIn("页面有、Release 没有：App-1.2.3-arm64.apk", err)
        _, _, reverse = self.run_main(self.assets(*self.page_files, "extra.zip"))
        self.assertIn("Release 有、页面没有：extra.zip", reverse)

    def test_several_names_on_one_side_are_joined(self):
        """一侧缺两个名字时用「、」连接：单个名字看不出分隔符被改坏。"""
        code, _, err = self.run_main(self.assets())
        self.assertEqual(code, release_assets.EXIT_MISMATCH)
        self.assertIn("页面有、Release 没有：App-1.2.3-arm64.apk、App-1.2.3-mac.dmg", err)
        # Release 多两个名字的那一侧同样要连接
        _, _, extra = self.run_main(self.assets(*self.page_files, "a.zip", "b.zip"))
        self.assertIn("Release 有、页面没有：a.zip、b.zip", extra)

    def test_a_duplicate_tag_argument_exits_two_with_usage(self):
        code, _, err = self.run_main(self.assets(), argv=("v1", "v2"))
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("多余的参数：v2", err)
        self.assertIn("用法", err)

    def test_fetch_failure_exits_two_and_says_so(self):
        """取不到数不等于对不上：网络抖动、API 限额与真的不一致要看得出区别。"""
        code, _, err = self.run_main(self.assets(), error="API rate limit exceeded")
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("取不到", err)
        self.assertIn("API rate limit exceeded", err)
        self.assertNotIn("对不上", err)

    def test_unreadable_page_exits_two_without_asking_github(self):
        """读不到 REL 时不该先去取数：剩下的比没有意义，白打一次 API。"""
        self.page.write_text("<html></html>", encoding="utf-8")
        code, _, err = self.run_main(self.assets(*self.page_files))
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("REL", err)
        self.assertEqual(self.calls, [], "读不到 REL 时不该调用 gh")

    def test_tag_defaults_to_the_page_version(self):
        code, _, err = self.run_main(self.assets(*self.page_files))
        self.assertEqual(code, release_assets.EXIT_OK, err)
        self.assertEqual(self.calls, ["v1.2.3"])


class ShaMainTests(unittest.TestCase):
    """`--sha` 下比文件名、大小与 sha 三类，差异分行列出（#1136）。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.page = Path(self.dir.name) / "index.html"
        self.page.write_text(META_PAGE.format(mac=MAC_FILE, mac_sha=MAC_SHA,
                                              apk=APK_FILE, apk_sha=APK_SHA),
                             encoding="utf-8")

    def run_main(self, release, argv=("--sha",), error=None):
        def fetch(tag):
            if error:
                raise RuntimeError(error)
            return list(release)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_assets.main(argv, fetch=fetch, page=self.page)
        return code, out.getvalue(), err.getvalue()

    def test_matching_name_size_and_sha_exits_zero(self):
        code, out, err = self.run_main(matching_assets())
        self.assertEqual(code, release_assets.EXIT_OK, err)
        self.assertIn("REL.files 的名字、大小、sha 一致。", out)

    def test_sha_mismatch_exits_one_and_shows_both_sides(self):
        other = "c" * 64
        assets = matching_assets()
        assets[1] = assets[1]._replace(digest="sha256:" + other)
        code, _, err = self.run_main(assets)
        self.assertEqual(code, release_assets.EXIT_MISMATCH)
        self.assertIn("  sha 对不上：\n", err)
        self.assertIn(f"{APK_FILE}：页面 {APK_SHA} / Release {other}", err)
        self.assertNotIn("大小对不上", err)

    def test_size_mismatch_exits_one_and_shows_the_page_wording(self):
        assets = matching_assets()
        assets[1] = assets[1]._replace(size=53_000_000)
        code, _, err = self.run_main(assets)
        self.assertEqual(code, release_assets.EXIT_MISMATCH)
        self.assertIn("  大小对不上：\n", err)
        self.assertIn(f"{APK_FILE}：页面 52.8 MB / Release 53.0 MB", err)
        self.assertNotIn("sha 对不上", err)

    def test_both_classes_are_listed_apart(self):
        other = "c" * 64
        assets = matching_assets()
        assets[1] = release_assets.Asset(APK_FILE, 53_000_000, "sha256:" + other)
        code, _, err = self.run_main(assets)
        self.assertEqual(code, release_assets.EXIT_MISMATCH)
        self.assertIn("大小对不上", err)
        self.assertIn("sha 对不上", err)
        self.assertLess(err.index("大小对不上"), err.index("sha 对不上"))

    def test_fetch_failure_exits_two_not_mismatch(self):
        """旧树也绿，守的是不回退：网络抖动与真差异必须分得开。"""
        code, _, err = self.run_main([], error="API rate limit exceeded")
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("取不到", err)
        self.assertNotIn("对不上", err)

    def test_missing_digest_exits_two_and_says_which_asset(self):
        """摘要取不到时不能下「一致」的结论，也不能报成对不上。"""
        assets = matching_assets()
        assets[1] = assets[1]._replace(digest="")
        code, _, err = self.run_main(assets)
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("\n  Release 没给出这些附件的摘要，sha 比不了：",
                      "\n" + err, "整行以两个空格开头，不能被包上 XX")
        self.assertIn(APK_FILE, err)
        self.assertNotIn("对不上", err)

    def test_several_unverified_assets_are_joined(self):
        """缺摘要的附件多于一个时用「、」连接：单个名字看不出分隔符被改坏。"""
        assets = matching_assets()
        assets[0] = assets[0]._replace(digest="")
        assets[1] = assets[1]._replace(digest="")
        code, _, err = self.run_main(assets)
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn(f"{APK_FILE}、{MAC_FILE}", err)

    def test_mismatch_wins_over_an_unverified_asset(self):
        """同一轮既有对不上又有附件缺摘要：差异已确证按 1 报，缺摘要那句照打。"""
        assets = matching_assets()
        assets[0] = assets[0]._replace(digest="")            # sha 比不了
        assets[1] = assets[1]._replace(size=53_000_000)      # 大小对不上
        code, _, err = self.run_main(assets)
        self.assertEqual(code, release_assets.EXIT_MISMATCH)
        self.assertIn("大小对不上", err)
        self.assertIn("没给出这些附件的摘要", err)

    def test_without_the_flag_only_names_are_compared(self):
        """默认档仍只比名字：大小与 sha 的差异不该让它红，周一那班带 `--sha` 才比。"""
        assets = matching_assets()
        assets[1] = assets[1]._replace(size=53_000_000, digest="")
        code, _, err = self.run_main(assets, argv=())
        self.assertEqual(code, release_assets.EXIT_OK, err)

    def test_unknown_flag_exits_two_with_usage(self):
        code, _, err = self.run_main(matching_assets(), argv=("--sha", "--bogus"))
        self.assertEqual(code, release_assets.EXIT_UNREACHABLE)
        self.assertIn("--bogus", err)
        self.assertIn("用法", err)


if __name__ == "__main__":
    unittest.main()
