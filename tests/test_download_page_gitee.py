"""#718：上传脚本从 GitHub 取包、核 SHA256，Gitee 拒收的安装版不进上传清单，匿名下载回验。"""
import importlib.util
import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_uploader():
    spec = importlib.util.spec_from_file_location("upload_gitee", ROOT / "gui" / "upload_gitee.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def test_only_version_tags_reach_gitee(self):
        seen = []

        def fake_run(*cmd, **_kw):
            seen.append(cmd)

        with patch.object(self.up, "run", fake_run):
            self.up.push_code("1.0.0")
        pushed = [c for c in seen if "push" in c]
        self.assertEqual(len(pushed), 1)
        self.assertIn("refs/heads/main:refs/heads/main", pushed[0])
        self.assertIn("refs/tags/v*:refs/tags/v*", pushed[0])
        self.assertNotIn("refs/tags/*:refs/tags/*", pushed[0])

    def test_a_tampered_public_download_stops_the_release(self):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        with patch.object(self.up.urllib.request, "urlopen", lambda *_a, **_kw: Resp(b"x")):
            with self.assertRaises(SystemExit) as caught:
                self.up.verify_public("1.0.0", [], {}, "0" * 64)
        self.assertIn("SHA256SUMS.txt", str(caught.exception))

    def test_a_rejected_upload_reports_the_status_and_the_platform_message(self):
        path = self.stage / "a.exe"
        path.write_bytes(b"x")
        refused = urllib.error.HTTPError("u", 400, "Bad Request", {},
                                         io.BytesIO(b"malicious file detected and rejected"))
        with patch.object(self.up, "call", side_effect=refused):
            with self.assertRaises(SystemExit) as caught:
                self.up.upload(1, path)
        self.assertIn("400", str(caught.exception))
        self.assertIn("malicious file detected", str(caught.exception))


if __name__ == "__main__":
    sys.exit(unittest.main())
