"""发版校验清单从 Release 事实生成（`tool/release_meta.py`，#1134）。

只测外部行为：命令的退出码与输出、生成的清单文本、写盘结果。不联网、不需要 `gh`，
`fetch` / `upload` / `draft` 三个取数口都由用例注入。
"""
import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from tool import release_assets, release_meta

VERSION = "1.2.3"
NAMES = {entry_id: f"App-{VERSION}-{suffix}" for entry_id, suffix in release_meta.SUFFIXES}
DIGESTS = {entry_id: hashlib.sha256(entry_id.encode()).hexdigest()
           for entry_id, _ in release_meta.SUFFIXES}


def make_assets(digest=lambda entry_id: f"sha256:{DIGESTS[entry_id]}", skip=()):
    """五条资产，故意按卡片顺序倒着给：清单顺序不该来自 Release 返回的顺序。"""
    return [release_assets.Asset(name=NAMES[entry_id], size=100, digest=digest(entry_id))
            for entry_id, _ in reversed(release_meta.SUFFIXES) if entry_id not in skip]


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


if __name__ == "__main__":
    unittest.main()
