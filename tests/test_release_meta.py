"""发版元数据从 Release 事实生成（`tool/release_meta.py`，#1135，沿用 #1134）。

只测外部行为：命令的退出码与输出、生成的清单与页面文本、写盘结果。不联网、不需要 `gh`，
`fetch` / `upload` / `draft` / `published` 与写后自检的 `verify` 都由用例注入。
"""
import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from string import Template
from unittest import mock

from tool import release_assets, release_meta

VERSION = "1.2.3"
RELEASED = "2026-11-12"
NAMES = {entry_id: f"App-{VERSION}-{suffix}" for entry_id, suffix in release_meta.SUFFIXES}
DIGESTS = {entry_id: hashlib.sha256(entry_id.encode()).hexdigest()
           for entry_id, _ in release_meta.SUFFIXES}
SIZES = {"mac-arm64": 40_404_808, "mac-intel": 45_995_322, "win-setup": 1_000_050,
         "win-zip": 2, "android": 52_800_000}

# 与 index.html 同形：卡片跨两行、`baidu` 里套着花括号、win-setup 带 `gitee: false`。
PAGE = Template("""const REL = {
  version: "0.4.3",
  github: "https://github.com/x/y/releases/download/v0.4.3/",
  gitee: "https://gitee.com/x/y/releases/download/v0.4.3/",
  baidu: { url: "", code: "" },
  files: [
    { id: "mac-arm64", folder: "Mac-Apple芯片", baidu: { url: "", code: "" }, title: "Mac · Apple 芯片", sub: "M1 / M2", file: "App-0.4.3-mac-arm64.dmg", size: "1.0 MB",
      note: "公证", sha: "$mac" },
    { id: "mac-intel", folder: "Mac-Intel芯片", baidu: { url: "", code: "" }, title: "Mac · Intel 芯片", sub: "2020 年及以前", file: "App-0.4.3-mac-intel.dmg", size: "2.0 MB",
      note: "公证", sha: "$intel" },
    { id: "win-setup", folder: "Windows-安装版", baidu: { url: "", code: "" }, title: "Windows · 安装版", sub: "Windows 10 / 11", file: "App-0.4.3-windows-setup.exe", size: "3.0 MB",
      note: "安全提示", sha: "$setup", gitee: false },
    { id: "win-zip", folder: "Windows-免安装版", baidu: { url: "", code: "" }, title: "Windows · 免安装", sub: "Windows 10 / 11", file: "App-0.4.3-windows-portable.zip", size: "4.0 MB",
      note: "解压后双击", sha: "$zip" },
    { id: "android", folder: "安卓手机", baidu: { url: "", code: "" }, title: "安卓手机 · 手机版", sub: "安卓 11 及以上", file: "App-0.4.3-android-arm64.apk", size: "5.0 MB",
      note: "不用连电脑", sha: "$apk" },
  ],
};
const RELEASED = "2026-01-01";
""")


def old_page():
    return PAGE.substitute(mac="old-mac", intel="old-intel", setup="old-setup",
                           zip="old-zip", apk="old-apk")


def make_assets(digest=lambda entry_id: f"sha256:{DIGESTS[entry_id]}", skip=(),
                sizes=None, version=VERSION):
    """五条资产，故意按卡片顺序倒着给：清单顺序不该来自 Release 返回的顺序。"""
    sizes = {entry_id: 100 for entry_id, _ in release_meta.SUFFIXES} if sizes is None else sizes
    return [release_assets.Asset(name=f"App-{version}-{suffix}", size=sizes[entry_id],
                                 digest=digest(entry_id))
            for entry_id, suffix in reversed(release_meta.SUFFIXES) if entry_id not in skip]


def expected_text():
    return "".join(f"{DIGESTS[entry_id]}  {NAMES[entry_id]}\n"
                   for entry_id, _ in release_meta.SUFFIXES)


class PlanSumsTests(unittest.TestCase):
    def test_lists_five_entries_in_card_order_with_two_spaces(self):
        self.assertEqual(release_meta.plan_sums(make_assets()), expected_text())

    def test_manifest_order_is_the_download_card_order(self):
        """清单给人眼比对下载页：两边的顺序漂了，逐行核对的余量就没了。

        卡片的文件名也必须以清单用的后缀结尾，否则 `select()` 在发版当天才以
        「找不到附件」拒绝，回归里看不出来。
        """
        root = Path(__file__).resolve().parents[1]
        _, entries = release_assets.read_page((root / "index.html").read_text(encoding="utf-8"))
        self.assertEqual([entry_id for entry_id, _ in entries],
                         [entry_id for entry_id, _ in release_meta.SUFFIXES])
        stray = [f"{entry_id}: {name}" for (entry_id, name), (_, suffix)
                 in zip(entries, release_meta.SUFFIXES, strict=True)   # 上面刚比过 id 序列，两条等长
                 if not name.endswith(suffix)]
        self.assertEqual(stray, [], "下载卡片的文件名不再以清单用的后缀结尾：\n" + "\n".join(stray))

    def test_asset_without_digest_refuses_instead_of_writing_blank(self):
        with self.assertRaises(release_meta.Refused):
            release_meta.plan_sums(make_assets(digest=lambda _: ""))

    def test_asset_missing_from_the_release_refuses(self):
        """某个卡片 id 在 Release 里找不到对应附件时整份拒绝，不写一份缺条目的清单。"""
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_sums(make_assets(skip=("android",)))
        self.assertIn("android", str(caught.exception))


class MainTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.sums = self.root / "SHA256SUMS.txt"
        self.fetched = []
        self.uploaded = []

    def run_main(self, argv=("sums", "v1.2.3"), assets=None, error=None, draft=True,
                 upload_error=None, state=None, out=None):
        state = list(make_assets() if assets is None else assets) if state is None else state

        def fetch(tag):
            self.fetched.append(tag)
            if error:
                raise RuntimeError(error)
            return list(state)

        def upload(tag, path):
            self.uploaded.append((tag, Path(path)))
            if upload_error:
                raise RuntimeError(upload_error)
            path = Path(path)
            state[:] = [asset for asset in state if asset.name != release_meta.MANIFEST]
            state.append(release_assets.Asset(
                name=release_meta.MANIFEST, size=path.stat().st_size,
                digest="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()))

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = release_meta.main(argv, fetch=fetch, upload=upload,
                                     draft=lambda tag: draft,
                                     out=self.sums if out is None else out)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_sums_writes_the_manifest(self):
        code, out, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertEqual(self.sums.read_text(encoding="utf-8"), expected_text())
        self.assertIn("5", out)

    def test_missing_digest_exits_one_and_leaves_no_file(self):
        code, _, err = self.run_main(assets=make_assets(digest=lambda _: ""))
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("摘要", err)
        self.assertFalse(self.sums.exists(), "拒绝生成时不该留下半份文件")

    def test_unmatched_card_id_exits_one_and_leaves_no_file(self):
        code, _, err = self.run_main(assets=make_assets(skip=("win-zip",)))
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("win-zip", err)
        self.assertFalse(self.sums.exists())

    def test_fetch_failure_exits_two_and_leaves_no_file(self):
        """取不到数不等于事实不完整：网络抖动、限额与真的缺条目要分得开。"""
        code, _, err = self.run_main(error="API rate limit exceeded")
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertIn("API rate limit exceeded", err)
        self.assertFalse(self.sums.exists())

    def test_unknown_arguments_exit_two(self):
        code, _, err = self.run_main(argv=("sums",))
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertIn("用法", err)

    def test_upload_into_a_draft_is_read_back(self):
        code, out, err = self.run_main(argv=("sums", "v1.2.3", "--upload"))
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertEqual(self.uploaded, [("v1.2.3", self.sums)])
        self.assertEqual(len(self.fetched), 2, "上传后要回读一次 Release")
        self.assertIn("回读", out)

    def test_upload_is_refused_once_the_release_is_public(self):
        """公开之后换文件，用户手里的校验值就对不上了。"""
        code, _, err = self.run_main(argv=("sums", "v1.2.3", "--upload"), draft=False)
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertEqual(self.uploaded, [])
        self.assertIn("已公开", err)

    def test_readback_mismatch_exits_one(self):
        state = make_assets()

        def fetch(tag):
            self.fetched.append(tag)
            return list(state)

        def upload(tag, path):
            self.uploaded.append((tag, Path(path)))

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(("sums", "v1.2.3", "--upload"), fetch=fetch,
                                     upload=upload, draft=lambda tag: True, out=self.sums)
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn(release_meta.MANIFEST, err.getvalue())

    def test_unwritable_output_exits_two(self):
        """写盘失败也归「给不出结论」，不是「拒绝生成」，更不该打整段堆栈。"""
        code, _, err = self.run_main(out=self.root / "missing-dir" / "SHA256SUMS.txt")
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertIn("写不进", err)

    def test_upload_failure_exits_two(self):
        code, _, err = self.run_main(argv=("sums", "v1.2.3", "--upload"),
                                     upload_error="gh: HTTP 502")
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertIn("HTTP 502", err)


class FromFilesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.sums = self.root / "SHA256SUMS.txt"
        self.packages = self.root / "packages"
        self.packages.mkdir()

    def fill_packages(self, skip=()):
        for entry_id, _ in release_meta.SUFFIXES:
            if entry_id in skip:
                continue
            (self.packages / NAMES[entry_id]).write_bytes(entry_id.encode())

    def run_main(self, argv=("sums", "v1.2.3", "--from-files")):
        assets = make_assets()

        def fetch(tag):
            return list(assets)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main((*argv, str(self.packages)), fetch=fetch,
                                     upload=lambda tag, path: None,
                                     draft=lambda tag: True, out=self.sums)
        return code, out.getvalue(), err.getvalue()

    def test_recomputes_digests_from_local_files(self):
        """Release 没给摘要时，从本地安装包重算，清单仍逐字可用。"""
        self.fill_packages()
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertEqual(self.sums.read_text(encoding="utf-8"), expected_text())

    def test_missing_local_file_refuses(self):
        self.fill_packages(skip=("mac-intel",))
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn(NAMES["mac-intel"], err)
        self.assertFalse(self.sums.exists())


class PageTests(unittest.TestCase):
    """`page --write`：只动数据字段，先校验再用，写后回读一致才落盘。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.page = Path(self.dir.name) / "index.html"
        self.page.write_text(old_page(), encoding="utf-8")

    def run_main(self, argv=("page", "v1.2.3", "--write"), assets=None, fetch_error=None,
                 published=RELEASED, published_error=None, verify=None):
        def fetch(tag):
            if fetch_error:
                raise RuntimeError(fetch_error)
            return list(make_assets(sizes=SIZES) if assets is None else assets)

        def stamp(tag):
            if published_error:
                raise RuntimeError(published_error)
            if published is None:
                raise release_meta.Refused("还没发布")
            return published

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(argv, fetch=fetch, published=stamp, page=self.page,
                                     verify=verify or release_meta.page_ok)
        return code, out.getvalue(), err.getvalue()

    def text(self):
        return self.page.read_text(encoding="utf-8")

    def test_backfills_every_data_field_and_the_release_date(self):
        code, out, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        version, entries = release_assets.read_entries(self.text())
        self.assertEqual(version, "1.2.3")
        self.assertEqual([(e.id, e.file, e.size, e.sha) for e in entries],
                         [(entry_id, NAMES[entry_id], release_assets.human_size(SIZES[entry_id]),
                           DIGESTS[entry_id]) for entry_id, _ in release_meta.SUFFIXES])
        self.assertIn('releases/download/v1.2.3/"', self.text())
        self.assertIn(f'const RELEASED = "{RELEASED}";', self.text())
        self.assertIn("回填", out)

    def test_copy_fields_and_structure_are_untouched(self):
        """回填只替换值：卡片上的 folder / title / sub / note 与整段结构逐字留给页面。

        做法是把新旧两份文本里的数据值都抹成同一个占位符再比——除了数据字段，
        剩下的每一个字节都必须相同。
        """
        before = self.text()
        self.assertEqual(self.run_main()[0], release_meta.EXIT_OK)
        self.assertEqual(self.strip_data(before), self.strip_data(self.text()))

    @staticmethod
    def strip_data(text):
        for pattern in (release_meta.VERSION_LINE, release_meta.GITHUB_LINE,
                        release_meta.GITEE_LINE, release_meta.FILE_LINE,
                        release_meta.SIZE_LINE, release_meta.SHA_LINE,
                        release_meta.RELEASED_LINE):
            text = pattern.sub(lambda m: m.group(1) + "@" + m.group(3), text)
        return text

    def test_gitee_is_left_alone_unless_asked(self):
        code, out, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertIn('releases/download/v0.4.3/"', self.text())
        self.assertIn("REL.gitee", out)

    def test_gitee_flag_retags_the_mirror_prefix(self):
        self.assertEqual(self.run_main(argv=("page", "v1.2.3", "--write", "--gitee"))[0],
                         release_meta.EXIT_OK)
        self.assertIn('https://gitee.com/x/y/releases/download/v1.2.3/"', self.text())

    def test_empty_gitee_prefix_is_named_instead_of_called_a_structure_change(self):
        """Gitee 不可用时页面按流程留空：`--gitee` 撞上它要说清是空值，不是结构漂了。"""
        self.page.write_text(old_page().replace(
            'gitee: "https://gitee.com/x/y/releases/download/v0.4.3/"', 'gitee: ""'),
            encoding="utf-8")
        code, _, err = self.run_main(argv=("page", "v1.2.3", "--write", "--gitee"))
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("REL.gitee", err)
        self.assertIn("空的", err)
        self.assertNotIn("结构变了", err)

    def test_download_prefix_with_a_deeper_path_is_refused(self):
        """前缀里版本段之后还有别的路径时不截断：截掉就是悄悄改掉下载地址。"""
        self.page.write_text(old_page().replace(
            'releases/download/v0.4.3/"', 'releases/download/v0.4.3/extra/"'), encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("REL.github", err)

    def test_card_id_that_matches_no_asset_writes_nothing(self):
        self.page.write_text(old_page().replace('id: "win-zip"', 'id: "win-portable"'),
                             encoding="utf-8")
        before = self.text()
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("win-zip", err)
        self.assertEqual(self.text(), before)

    def test_asset_missing_from_the_release_writes_nothing(self):
        code, _, err = self.run_main(assets=make_assets(sizes=SIZES, skip=("android",)))
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("android", err)
        self.assertNotIn("v1.2.3", self.text())

    def test_incomplete_page_entry_writes_nothing(self):
        self.page.write_text(old_page().replace(' size: "5.0 MB",', ""), encoding="utf-8")
        before = self.text()
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("android", err)
        self.assertEqual(self.text(), before)

    def test_self_check_mismatch_leaves_the_page_alone(self):
        """写后回读对不上就删掉临时文件：页面要么整份新、要么原样，不留半份。"""
        before = self.text()
        code, _, err = self.run_main(verify=lambda *args: False)
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("回读", err)
        self.assertEqual(self.text(), before)
        self.assertEqual(sorted(p.name for p in Path(self.dir.name).iterdir()), ["index.html"])

    def test_version_that_does_not_match_the_assets_writes_nothing(self):
        code, _, err = self.run_main(argv=("page", "v2.0.0", "--write"))
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("2.0.0", err)
        self.assertNotIn("v2.0.0", self.text())

    def test_dry_run_validates_without_writing(self):
        before = self.text()
        code, out, err = self.run_main(argv=("page", "v1.2.3"))
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertIn("--write", out)
        self.assertEqual(self.text(), before)

    def test_unpublished_release_refuses(self):
        code, _, err = self.run_main(published=None)
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("还没发布", err)

    def test_fetch_failure_exits_two(self):
        code, _, err = self.run_main(fetch_error="API rate limit exceeded")
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertIn("API rate limit exceeded", err)

    def test_published_failure_exits_two(self):
        code, _, err = self.run_main(published_error="gh: HTTP 502")
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertIn("HTTP 502", err)

    def test_flags_of_the_other_subcommand_exit_two(self):
        code, _, err = self.run_main(argv=("page", "v1.2.3", "--upload"))
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertIn("用法", err)


class PublishedTests(unittest.TestCase):
    def test_takes_the_utc_date_of_the_release(self):
        with mock.patch.object(release_meta, "run_gh", return_value="2026-11-11T20:30:00Z\n"):
            self.assertEqual(release_meta.release_published("v1"), "2026-11-11")

    def test_converts_an_offset_to_utc(self):
        """跨零点时按 UTC 取日期：页面上写的是 UTC 那一天，不是发布者本地时间。"""
        with mock.patch.object(release_meta, "run_gh", return_value="2026-11-12T03:00:00+08:00"):
            self.assertEqual(release_meta.release_published("v1"), "2026-11-11")

    def test_a_naive_timestamp_is_read_as_utc(self):
        """不带时区的读数按 UTC 认：拿本机时区去换算会让日期在东八区差一天。"""
        with mock.patch.object(release_meta, "run_gh", return_value="2026-11-11T20:30:00"):
            self.assertEqual(release_meta.release_published("v1"), "2026-11-11")

    def test_unpublished_release_refuses(self):
        with mock.patch.object(release_meta, "run_gh", return_value="null\n"):
            with self.assertRaises(release_meta.Refused):
                release_meta.release_published("v1")


if __name__ == "__main__":
    unittest.main()
