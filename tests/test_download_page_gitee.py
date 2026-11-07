"""#714：下载页的国内下载走 Gitee，页面上不出现百度网盘；Gitee 不可用时留空 gitee 就能退回网盘。"""
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "index.html").read_text(encoding="utf-8")


def load_uploader():
    spec = importlib.util.spec_from_file_location("upload_gitee", ROOT / "gui" / "upload_gitee.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PageTest(unittest.TestCase):
    def test_gitee_path_follows_the_version(self):
        version = re.search(r'version: "([^"]+)"', PAGE).group(1)
        self.assertIn(f'gitee: "https://gitee.com/rddmw/android-ad-cleaner/releases/download/v{version}/"', PAGE)

    def test_no_netdisk_link_or_wording_is_shown(self):
        self.assertNotIn("pan.baidu.com", PAGE)
        lead = re.search(r'id="dl-lead">([^<]+)<', PAGE).group(1)
        self.assertIn("Gitee", lead)
        self.assertNotIn("百度", lead)
        self.assertNotIn("提取码", lead)

    def test_the_installer_gitee_rejects_gets_no_gitee_link(self):
        row = re.search(r'\{ id: "win-setup",[^\n]*\n[^\n]*', PAGE).group(0)
        self.assertIn("gitee: false", row)
        self.assertIn('f.gitee !== false', PAGE)
        self.assertIn("国内网络建议下载免安装版", PAGE)

    def test_every_file_keeps_an_empty_slot_so_the_netdisk_script_can_restore_it(self):
        rows = re.findall(r'\{ id: "[\w-]+", folder: "[^"]+", baidu: \{ url: "", code: "" \}', PAGE)
        self.assertEqual(len(rows), len(re.findall(r'\{ id: "[\w-]+", folder:', PAGE)))
        self.assertTrue(rows)


class UploaderTest(unittest.TestCase):
    def setUp(self):
        self.up = load_uploader()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stage = Path(self.tmp.name)

    def fake_download(self, content, digest):
        def run(*_cmd, **_kw):
            (self.stage / "a.dmg").write_bytes(content)
            (self.stage / "SHA256SUMS.txt").write_text(f"{digest}  a.dmg\n", encoding="utf-8")
        return run

    def test_a_package_that_does_not_match_its_checksum_stops_the_upload(self):
        with patch.object(self.up, "run", self.fake_download(b"x", "0" * 64)):
            with self.assertRaises(SystemExit) as caught:
                self.up.fetch_release("1.0.0", self.stage)
        self.assertIn("校验不一致", str(caught.exception))

    def test_checksums_file_itself_is_not_a_package(self):
        digest = "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
        with patch.object(self.up, "run", self.fake_download(b"x", digest)):
            files, sums = self.up.fetch_release("1.0.0", self.stage)
        self.assertEqual([p.name for p in files], ["a.dmg"])
        self.assertEqual(sums, {"a.dmg": digest})

    def test_the_rejected_installer_is_not_uploaded(self):
        names = ["a-mac-arm64.dmg", "a-windows-portable.zip", "a-windows-setup.exe", "a-android-arm64.apk"]
        kept = self.up.for_gitee([Path(n) for n in names])
        self.assertEqual([p.name for p in kept], ["a-mac-arm64.dmg", "a-windows-portable.zip", "a-android-arm64.apk"])

    def test_missing_token_says_where_to_put_it(self):
        with patch.object(self.up, "TOKEN_FILE", self.stage / "nope"):
            with self.assertRaises(SystemExit) as caught:
                self.up.token()
        self.assertIn("私人令牌", str(caught.exception))


if __name__ == "__main__":
    sys.exit(unittest.main())
