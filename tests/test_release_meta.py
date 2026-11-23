"""发版元数据从 Release 事实生成（`devtools/release_meta.py`，#1135，沿用 #1134）。

只测外部行为：命令的退出码与输出、生成的清单与页面文本、写盘结果。不联网、不需要 `gh`，
`fetch` / `upload` / `draft` / `published` 与写后自检的 `verify` 都由用例注入。
"""
import contextlib
import hashlib
import io
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from string import Template
from unittest import mock

from fixtures import FakeRunner
from devtools import release_assets, release_meta


def _restore_tz(old):
    """用例改过 `TZ` 后恢复本机时区并让 C 库重新读一次。"""
    os.environ.pop("TZ", None)
    if old is not None:
        os.environ["TZ"] = old
    time.tzset()


@contextlib.contextmanager
def _local_timezone(name):
    """临时把本机时区切成 `name`，退出时切回来；`TZ` + `tzset` 只在 POSIX 上生效。

    宿主机本身是 UTC 还是 +08 都不影响结论：`tzset()` 按 `TZ` 重读时区库。
    """
    if os.name == "nt":
        raise unittest.SkipTest("TZ 变量 + tzset 只在 POSIX 上生效")
    old = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        _restore_tz(old)

VERSION = "1.2.3"
RELEASED = "2026-11-12"
NAMES = {entry_id: f"App-{VERSION}-{suffix}" for entry_id, suffix in release_meta.SUFFIXES}
DIGESTS = {entry_id: hashlib.sha256(entry_id.encode()).hexdigest()
           for entry_id, _ in release_meta.SUFFIXES}
SIZES = {"mac-arm64": 40_404_808, "mac-intel": 45_995_322, "win-setup": 1_000_050,
         "win-zip": 2, "android": 52_800_000}

# 与 index.html 同形：卡片跨两行、`baidu` 里套着花括号、win-setup 带 `gitee: false`，
# 图标地址带 `?v=` 缓存键（两处：favicon 与品牌区 logo）。
PAGE = Template("""<link rel="icon" href="images/roudai-icon.png?v=0.4.3">
const REL = {
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
<a class="brand" href="#"><img class="logo" src="images/roudai-icon.png?v=0.4.3" alt="">App</a>
""")

# 教程页没有 REL，只有两处同样的图标地址：缓存的旧 404 要靠同一个键绕开。
TUTORIAL = """<link rel="icon" href="images/roudai-icon.png?v=0.4.3">
<a class="brand" href="index.html"><img class="logo" src="images/roudai-icon.png?v=0.4.3" alt="">App</a>
"""


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
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_sums(make_assets(digest=lambda _: ""))
        message = str(caught.exception)
        self.assertIn("改用 --from-files <目录> 从本地文件重算。", message)
        self.assertTrue(message.endswith("从本地文件重算。"))

    def test_asset_missing_from_the_release_refuses(self):
        """某个卡片 id 在 Release 里找不到对应附件时整份拒绝，不写一份缺条目的清单。"""
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_sums(make_assets(skip=("android",)))
        self.assertIn("android", str(caught.exception))
        self.assertIn("拒绝生成", str(caught.exception), "`select` 的默认 what 只在这里露头")


class MainTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.sums = self.root / "SHA256SUMS.txt"
        self.fetched = []
        self.uploaded = []
        self.drafted = []

    def run_main(self, argv=("sums", "v1.2.3"), assets=None, error=None, draft=True,
                 upload_error=None, state=None, out=None, draft_error=None):
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

        def draft_call(tag):
            self.drafted.append(tag)
            if draft_error:
                raise RuntimeError(draft_error)
            return draft

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = release_meta.main(argv, fetch=fetch, upload=upload, draft=draft_call,
                                     out=self.sums if out is None else out)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_sums_writes_the_manifest(self):
        code, out, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertEqual(self.sums.read_text(encoding="utf-8"), expected_text())
        self.assertEqual(self.fetched, ["v1.2.3"])
        self.assertIn("5", out)

    def test_the_manifest_is_written_as_utf8_with_lf(self):
        """编码 / 换行在 ASCII 清单上没有可观察差异，只能从调用参数上钉住（#1522）。"""
        writes = []
        real = Path.write_text

        def spy(target, *args, **kwargs):
            writes.append(kwargs)
            return real(target, *args, **kwargs)

        with mock.patch.object(Path, "write_text", spy):
            code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertTrue(writes and all(kw == {"encoding": "utf-8", "newline": "\n"}
                                       for kw in writes), writes)

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
        self.assertEqual(self.fetched, ["v1.2.3", "v1.2.3"], "取数、回读都用同一个 tag")
        self.assertEqual(self.drafted, ["v1.2.3"], "查草稿状态用的是同一个 tag")
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

    def test_default_output_lands_in_the_current_directory(self):
        """不给 `out` 时清单落在当前目录，不是落到一个 Path(None) 上。"""
        def fetch(tag):
            return make_assets()

        old = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(("sums", "v1.2.3"), fetch=fetch, out=None)
        self.assertEqual(code, release_meta.EXIT_OK, err.getvalue())
        self.assertEqual((self.root / "SHA256SUMS.txt").read_text(encoding="utf-8"),
                         expected_text())

    def test_a_failed_draft_check_exits_two(self):
        code, _, err = self.run_main(argv=("sums", "v1.2.3", "--upload"),
                                     draft_error="gh: HTTP 502")
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertEqual(err.splitlines()[0].split("：")[0], "读不到 v1.2.3 的发布状态")

    def test_a_failed_readback_exits_two(self):
        calls = {"n": 0}

        def fetch(tag):
            calls["n"] += 1
            if calls["n"] == 1:
                return make_assets()
            raise RuntimeError("network gone")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(("sums", "v1.2.3", "--upload"), fetch=fetch,
                                     upload=lambda tag, path: None, draft=lambda tag: True,
                                     out=self.sums)
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertEqual(err.getvalue().splitlines()[0].split("：")[0],
                         "清单已上传，但回读 v1.2.3 失败")


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
        self.tutorial = Path(self.dir.name) / "android-tutorial.html"
        self.tutorial.write_text(TUTORIAL, encoding="utf-8")
        self.fetched = []
        self.published_tags = []

    def run_main(self, argv=("page", "v1.2.3", "--write"), assets=None, fetch_error=None,
                 published=RELEASED, published_error=None, verify=None):
        def fetch(tag):
            self.fetched.append(tag)
            if fetch_error:
                raise RuntimeError(fetch_error)
            return list(make_assets(sizes=SIZES) if assets is None else assets)

        def stamp(tag):
            self.published_tags.append(tag)
            if published_error:
                raise RuntimeError(published_error)
            if published is None:
                raise release_meta.Refused("还没发布")
            return published

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(argv, fetch=fetch, published=stamp,
                                     pages={"home": self.page, "tutorial": self.tutorial},
                                     verify=verify or release_meta.page_ok)
        return code, out.getvalue(), err.getvalue()

    def text(self):
        return self.page.read_text(encoding="utf-8")

    def tutorial_text(self):
        return self.tutorial.read_text(encoding="utf-8")

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
        self.assertEqual(self.fetched, ["v1.2.3"])
        self.assertEqual(self.published_tags, ["v1.2.3"])
        self.assertIn("index.html、android-tutorial.html 已回填到 v1.2.3", out,
                      "两页的文件名用「、」连接")
        self.assertTrue(any(line.endswith("图标地址的 ?v= 同版本。") for line in out.splitlines()))
        self.assertTrue(any(line.startswith("REL.gitee 没动") for line in out.splitlines()))

    def test_pages_are_read_and_written_as_utf8_with_lf(self):
        """编码 / 换行在 ASCII 页面上没有可观察差异，只能从调用参数上钉住（#1522）。"""
        reads, writes = [], []
        real_read, real_write = Path.read_text, Path.write_text

        def spy_read(target, *args, **kwargs):
            reads.append(kwargs)
            return real_read(target, *args, **kwargs)

        def spy_write(target, *args, **kwargs):
            writes.append(kwargs)
            return real_write(target, *args, **kwargs)

        with mock.patch.object(Path, "read_text", spy_read), \
                mock.patch.object(Path, "write_text", spy_write):
            code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        self.assertTrue(reads and all(kw == {"encoding": "utf-8"} for kw in reads), reads)
        self.assertTrue(writes and all(kw == {"encoding": "utf-8", "newline": "\n"}
                                       for kw in writes), writes)

    def test_backfills_the_icon_cache_key_on_both_pages(self):
        """?v= 是图标的缓存键：两页一起换成本版，否则同一份源码里出现两个版本号。"""
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_OK, err)
        for page, text in (("home", self.text()), ("tutorial", self.tutorial_text())):
            with self.subTest(page=page):
                self.assertEqual(set(re.findall(r'\?v=([^"&\s]+)', text)), {"1.2.3"})

    def test_page_without_an_icon_cache_key_writes_neither_page(self):
        """一页读不到 ?v= 就是结构变了：读不出就不动盘，两页都保持原样。"""
        self.tutorial.write_text(TUTORIAL.replace("?v=0.4.3", ""), encoding="utf-8")
        before = self.text(), self.tutorial_text()
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertIn("?v=", err)
        self.assertEqual((self.text(), self.tutorial_text()), before)

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
        return release_meta.CACHE_KEY.sub(lambda m: m.group(1) + "@", text)

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
        self.assertEqual(err.splitlines()[0].split(" ")[0], "REL.gitee")
        self.assertIn("是空的", err)
        self.assertNotIn("结构变了", err)

    def test_download_prefix_with_a_deeper_path_is_refused(self):
        """前缀里版本段之后还有别的路径时不截断：截掉就是悄悄改掉下载地址。"""
        self.page.write_text(old_page().replace(
            'releases/download/v0.4.3/"', 'releases/download/v0.4.3/extra/"'), encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertEqual(err.splitlines()[0].split(" ")[0], "REL.github")

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
        self.assertEqual(self.tutorial_text(), TUTORIAL)
        self.assertEqual(sorted(p.name for p in Path(self.dir.name).iterdir()),
                         ["android-tutorial.html", "index.html"])

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

    def test_a_registry_without_the_home_page_refuses(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(("page", "v1.2.3"), fetch=lambda tag: make_assets(sizes=SIZES),
                                     published=lambda tag: RELEASED,
                                     pages={"tutorial": self.tutorial})
        self.assertEqual(code, release_meta.EXIT_REFUSED)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue().splitlines()[0].split("：")[0],
                         "页面注册表里没有 home")

    def test_an_unreadable_page_exits_two(self):
        missing = Path(self.dir.name) / "missing.html"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(("page", "v1.2.3", "--write"),
                                     fetch=lambda tag: make_assets(sizes=SIZES),
                                     published=lambda tag: RELEASED,
                                     pages={"home": self.page, "tutorial": missing})
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertEqual(err.getvalue().splitlines()[0].split("：")[0],
                         f"读不到 {missing}")

    def test_an_unwritable_page_exits_two(self):
        """两页都读得到，但有一页写不进去：报「写不进」并退回非零。"""
        target = Path(self.dir.name) / "android-tutorial.html"
        target.write_text(TUTORIAL, encoding="utf-8")
        # `write_checked` 先写同目录 `.tmp`：只让这个临时文件写失败，两端同一路径。
        tmp = target.with_name(target.name + ".tmp")
        real_write_text = Path.write_text

        def write_text(path, *args, **kwargs):
            if path == tmp:
                raise PermissionError("read-only")
            return real_write_text(path, *args, **kwargs)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(Path, "write_text", write_text), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_meta.main(("page", "v1.2.3", "--write"),
                                     fetch=lambda tag: make_assets(sizes=SIZES),
                                     published=lambda tag: RELEASED,
                                     pages={"home": self.page, "tutorial": target})
        self.assertEqual(code, release_meta.EXIT_UNREACHABLE)
        self.assertTrue(err.getvalue().splitlines()[0].startswith("写不进 "))
        self.assertTrue(target.exists(), "写失败不该动原页面")


class PublishedTests(unittest.TestCase):
    def test_takes_the_utc_date_of_the_release(self):
        with mock.patch.object(release_meta, "run_gh",
                               return_value="2026-11-11T20:30:00Z\n") as gh:
            self.assertEqual(release_meta.release_published("v1"), "2026-11-11")
        gh.assert_called_once_with("release", "view", "v1", "--json", "publishedAt",
                                   "--jq", ".publishedAt")

    def test_converts_an_offset_to_utc(self):
        """跨零点时按 UTC 取日期：页面上写的是 UTC 那一天，不是发布者本地时间。"""
        with mock.patch.object(release_meta, "run_gh", return_value="2026-11-12T03:00:00+08:00"):
            self.assertEqual(release_meta.release_published("v1"), "2026-11-11")

    def test_a_naive_timestamp_is_read_as_utc(self):
        """不带时区的读数按 UTC 认：本机时区设成东八区时，跨零点会差一天。"""
        with _local_timezone("Asia/Shanghai"):
            # 02:30 按 UTC 认是 11-11；若按 +08 本机时区换算会退到 11-10
            with mock.patch.object(release_meta, "run_gh", return_value="2026-11-11T02:30:00"):
                self.assertEqual(release_meta.release_published("v1"), "2026-11-11")

    def test_an_aware_timestamp_keeps_the_utc_date_in_a_plus_eight_zone(self):
        """带 Z 的读数按 UTC 取日期：本机是 +08 时，换算成本机时区会挪到第二天。"""
        with _local_timezone("Asia/Shanghai"):
            # 20:30 UTC 在 +08 是次日 04:30；按本机时区取日期会写成 11-12
            with mock.patch.object(release_meta, "run_gh", return_value="2026-11-11T20:30:00Z"):
                self.assertEqual(release_meta.release_published("v1"), "2026-11-11")

    def test_unpublished_release_refuses(self):
        with mock.patch.object(release_meta, "run_gh", return_value="null\n"):
            with self.assertRaises(release_meta.Refused) as caught:
                release_meta.release_published("v1")
        self.assertIn("还没发布", str(caught.exception))


class RunGhTests(unittest.TestCase):
    """搬过来的文本取数壳：成功交回 strip 后的 stdout，三种失败都抛 GhError（#1218）。"""

    def with_runner(self, reply):
        runner = FakeRunner(runs=reply)
        patched = mock.patch.object(release_meta, "runner_for", return_value=runner.run)
        patched.start()
        self.addCleanup(patched.stop)
        return runner

    def test_returns_the_stripped_stdout_and_keeps_the_arguments(self):
        runner = self.with_runner(("  v1.2.3 \n", "", 0))
        self.assertEqual(release_meta.run_gh("release", "view", "v1"), "v1.2.3")
        self.assertEqual((runner.run_calls[0].script, runner.run_calls[0].args),
                         ("gh", ("release", "view", "v1")))

    def test_non_zero_exit_raises_gh_error_carrying_the_code(self):
        """stderr 与 stdout 都空时退出码是唯一线索，不能退成一句「返回非零」。"""
        self.with_runner(("", "", 3))
        with self.assertRaises(release_meta.GhError) as caught:
            release_meta.run_gh("release", "upload", "v1", "SHA256SUMS.txt")
        self.assertIn("gh 退出码 3", str(caught.exception))

    def test_missing_gh_is_a_gh_error(self):
        self.with_runner(OSError("no gh"))
        with self.assertRaises(release_meta.GhError) as caught:
            release_meta.run_gh("release", "view", "v1")
        self.assertIn("跑不了 gh", str(caught.exception))


OK_TEXT = ('const REL = {\n  version: "1.2.3",\n  files: [\n'
           '    { id: "a", file: "A", size: "1.0 MB", sha: "s" },\n  ],\n};\n'
           'const RELEASED = "2026-11-12";\n')
OK_ENTRIES = [release_assets.Entry("a", "A", "1.0 MB", "s")]


class SelectTests(unittest.TestCase):
    def test_two_assets_with_the_same_suffix_refuse_and_name_them(self):
        assets = []
        for entry_id, suffix in release_meta.SUFFIXES:
            assets.append(release_assets.Asset(f"A-{suffix}", 1, "sha256:" + "0" * 64))
            if entry_id == "mac-arm64":
                assets.append(release_assets.Asset(f"B-{suffix}", 1, "sha256:" + "0" * 64))
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.select(assets)
        self.assertIn("匹配到多个附件（A-mac-arm64.dmg、B-mac-arm64.dmg）", str(caught.exception))


class RetagTests(unittest.TestCase):
    def test_the_default_label_names_the_download_prefix(self):
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.retag("", "1.0")
        self.assertIn("下载前缀 是空的", str(caught.exception))

    def test_a_prefix_with_download_twice_retags_the_last_segment(self):
        self.assertEqual(release_meta.retag("https://h/download/a/download/v0/", "1.0"),
                         "https://h/download/a/download/v1.0/")


class ReplaceOnceTests(unittest.TestCase):
    def test_replaces_only_the_first_match_and_checks_the_count(self):
        text = 'version: "a"\nversion: "b"\n'
        self.assertEqual(
            release_meta.replace_once(release_meta.VERSION_LINE, text, lambda _: "c", "REL.version"),
            'version: "c"\nversion: "b"\n')

    def test_nothing_matching_is_refused(self):
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.replace_once(release_meta.VERSION_LINE, "no version", lambda _: "x",
                                      "REL.version")
        self.assertIn("REL.version 在页面里读不到", str(caught.exception))


class SubValueTests(unittest.TestCase):
    def test_replaces_only_the_first(self):
        text = 'version: "a"\nversion: "b"\n'
        self.assertEqual(release_meta.sub_value(release_meta.VERSION_LINE, text, "c"),
                         'version: "c"\nversion: "b"\n')


class FillEntryTests(unittest.TestCase):
    def test_names_the_duplicated_field(self):
        entry = release_assets.Entry("x", "f", "1 MB", "s")
        cases = {
            "file": 'file: "a", file: "b", size: "1", sha: "s"',
            "size": 'file: "f", size: "1", size: "2", sha: "s"',
            "sha": 'file: "f", size: "1", sha: "s", sha: "t"',
        }
        for field, chunk in cases.items():
            with self.subTest(field):
                with self.assertRaises(release_meta.Refused) as caught:
                    release_meta.fill_entry(chunk, entry)
                self.assertIn(f" {field} 不是一个", str(caught.exception))


class PageEntriesTests(unittest.TestCase):
    def test_missing_asset_is_refused_with_the_backfill_label(self):
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.page_entries(make_assets(skip=("android",)), VERSION)
        self.assertIn("拒绝回填", str(caught.exception))

    def test_a_missing_digest_is_named(self):
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.page_entries(make_assets(digest=lambda _: ""), VERSION)
        message = str(caught.exception)
        self.assertIn("Release 没给出这份附件的摘要，页面先不写。", message)
        self.assertTrue(message.endswith("页面先不写。"))


class PlanPageTests(unittest.TestCase):
    def assets(self):
        return make_assets(sizes=SIZES)

    def test_missing_rel_block_is_refused(self):
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page("<html></html>", self.assets(), VERSION, RELEASED)
        self.assertTrue(str(caught.exception).endswith("读不到 REL 块：结构变了，拒绝回填。"))

    def test_card_id_mismatch_names_both_sides_and_ends_with_the_verdict(self):
        text = (old_page().replace('id: "mac-arm64"', 'id: "aaa"')
                .replace('id: "android"', 'id: "bbb"'))
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page(text, self.assets(), VERSION, RELEASED)
        message = str(caught.exception)
        self.assertIn("aaa、mac-intel", message)
        self.assertIn("mac-arm64、mac-intel", message)
        self.assertTrue(message.endswith("对不上：拒绝回填。"))

    def test_incomplete_entries_are_named_and_joined(self):
        text = (old_page().replace(', sha: "old-mac"', '').replace(', sha: "old-apk"', ''))
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page(text, self.assets(), VERSION, RELEASED)
        message = str(caught.exception)
        self.assertIn("读不出完整条目", message)
        self.assertIn("mac-arm64、android", message)

    def test_missing_files_segment_is_refused(self):
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page(old_page().replace("files:", "list:"),
                                   self.assets(), VERSION, RELEASED)
        self.assertTrue(str(caught.exception).endswith("REL 没有 files 段：结构变了，拒绝回填。"))

    def test_version_moved_after_files_is_refused_by_its_label(self):
        text = (old_page().replace('  version: "0.4.3",\n', '')
                .replace('  ],\n};\n', '  ],\n  version: "0.4.3",\n};\n'))
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page(text, self.assets(), VERSION, RELEASED)
        self.assertIn("REL.version 在页面里读不到", str(caught.exception))

    def test_missing_github_line_is_refused_by_its_label(self):
        text = old_page().replace(
            '  github: "https://github.com/x/y/releases/download/v0.4.3/",\n', '')
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page(text, self.assets(), VERSION, RELEASED)
        self.assertIn("REL.github 在页面里读不到", str(caught.exception))

    def test_missing_gitee_line_is_refused_by_its_label_with_the_flag(self):
        text = old_page().replace(
            '  gitee: "https://gitee.com/x/y/releases/download/v0.4.3/",\n', '')
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page(text, self.assets(), VERSION, RELEASED, gitee=True)
        self.assertIn("REL.gitee 在页面里读不到", str(caught.exception))

    def test_missing_released_line_is_refused_by_its_label(self):
        text = old_page().replace('const RELEASED = "2026-01-01";\n', '')
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.plan_page(text, self.assets(), VERSION, RELEASED)
        self.assertIn("RELEASED 在页面里读不到", str(caught.exception))

    def test_gitee_default_is_left_alone(self):
        out = release_meta.plan_page(old_page(), self.assets(), VERSION, RELEASED)
        self.assertIn('https://gitee.com/x/y/releases/download/v0.4.3/', out)


class PageOkTests(unittest.TestCase):
    def test_a_wrong_version_is_not_ok(self):
        self.assertFalse(release_meta.page_ok(OK_TEXT.replace('"1.2.3"', '"9.9.9"'),
                                              "1.2.3", OK_ENTRIES, "2026-11-12"))

    def test_a_wrong_release_date_is_not_ok(self):
        self.assertFalse(release_meta.page_ok(OK_TEXT, "1.2.3", OK_ENTRIES, "2020-01-01"))

    def test_mismatched_entries_are_not_ok(self):
        wrong = [release_assets.Entry("a", "B", "1.0 MB", "s")]
        self.assertFalse(release_meta.page_ok(OK_TEXT, "1.2.3", wrong, "2026-11-12"))


class StampCacheKeyTests(unittest.TestCase):
    def test_a_page_without_a_cache_key_is_refused(self):
        with self.assertRaises(release_meta.Refused) as caught:
            release_meta.stamp_cache_key("no cache key", "1.0")
        self.assertTrue(str(caught.exception).endswith("缓存键：结构变了，拒绝回填。"))


class ReadbackTests(unittest.TestCase):
    def test_a_manifest_asset_with_a_wrong_digest_does_not_match(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / release_meta.MANIFEST
        path.write_bytes(b"abc")
        asset = release_assets.Asset(release_meta.MANIFEST, 3, "sha256:" + "0" * 64)
        self.assertFalse(release_meta.readback_matches([asset], path))


class AtomicWriteTests(unittest.TestCase):
    def read_only_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sub = Path(tmp.name) / "ro"
        sub.mkdir()
        os.chmod(sub, 0o555)
        self.addCleanup(os.chmod, sub, 0o755)
        return sub

    def test_write_atomic_keeps_the_original_error(self):
        """写临时文件失败时就抛原始 OSError，别让 unlink 用 FileNotFoundError 盖掉它。"""
        if os.name != "posix":
            self.skipTest("权限位只在 POSIX 上生效")
        sub = self.read_only_dir()
        with self.assertRaises(PermissionError):
            release_meta.write_atomic(sub / "x.txt", "t")

    def test_write_checked_keeps_the_original_error(self):
        if os.name != "posix":
            self.skipTest("权限位只在 POSIX 上生效")
        sub = self.read_only_dir()
        with self.assertRaises(PermissionError):
            release_meta.write_checked(sub / "x.txt", "t", lambda _: True)


class DraftFlagTests(unittest.TestCase):
    def test_reads_the_boolean_and_keeps_the_arguments(self):
        with mock.patch.object(release_meta, "run_gh", return_value="true\n") as gh:
            self.assertTrue(release_meta.release_is_draft("v1"))
        gh.assert_called_once_with("release", "view", "v1", "--json", "isDraft",
                                   "--jq", ".isDraft")
        with mock.patch.object(release_meta, "run_gh", return_value="false\n"):
            self.assertFalse(release_meta.release_is_draft("v1"))


class UploadAssetTests(unittest.TestCase):
    def test_uploads_with_clobber_and_keeps_the_arguments(self):
        with mock.patch.object(release_meta, "run_gh") as gh:
            release_meta.upload_asset("v1", "SHA256SUMS.txt")
        gh.assert_called_once_with("release", "upload", "v1", "SHA256SUMS.txt", "--clobber")


class ParseTests(unittest.TestCase):
    def message(self, argv):
        with self.assertRaises(ValueError) as caught:
            release_meta.parse(list(argv))
        return str(caught.exception)

    def test_no_subcommand(self):
        self.assertEqual(self.message([]), "缺子命令，只认 sums / page")

    def test_unknown_subcommand(self):
        self.assertEqual(self.message(["foo"]), "不认识的子命令：foo")

    def test_from_files_is_valid_for_sums(self):
        self.assertEqual(release_meta.parse(["sums", "v1", "--from-files", "dir"]).from_dir, "dir")

    def test_from_files_is_rejected_for_page(self):
        self.assertEqual(self.message(["page", "v1", "--from-files", "dir"]),
                         "--from-files 只给 sums 用")

    def test_from_files_needs_a_directory(self):
        self.assertEqual(self.message(["sums", "v1", "--from-files"]), "--from-files 后面要跟目录")

    def test_unknown_option_for_a_subcommand(self):
        self.assertEqual(self.message(["sums", "v1", "--bogus"]), "sums 不认识的参数：--bogus")

    def test_extra_positional_is_rejected(self):
        self.assertEqual(self.message(["sums", "v1", "v2"]), "多余的参数：v2")

    def test_missing_tag(self):
        self.assertEqual(self.message(["sums"]), "缺 tag")


if __name__ == "__main__":
    unittest.main()
