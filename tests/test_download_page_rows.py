"""#714：下载页和网盘说明要认得手机版 APK。"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "gui" / "baidu_rows.py"
PAGE = '''
  baidu: { url: "https://pan.baidu.com/s/all", code: "aaaa" },
  files: [
    { id: "mac-arm64", folder: "Mac-Apple芯片", baidu: { url: "", code: "" }, title: "Mac · Apple 芯片", sub: "M1 及以后", file: "AndroidAdCleaner-0.4.0-mac-arm64.dmg", size: "33 MB",
      note: "双击打开", sha: "1" },
    { id: "android", folder: "安卓手机", baidu: { url: "", code: "" }, title: "安卓手机 · 手机版", sub: "安卓 11 及以上", file: "AndroidAdCleaner-0.4.0-android-arm64.apk", size: "50 MB",
      note: "不用连电脑", sha: "2" },
  ],
'''
SUMS = "1  AndroidAdCleaner-0.4.0-mac-arm64.dmg\n2  AndroidAdCleaner-0.4.0-android-arm64.apk\n"


def load_rows():
    spec = importlib.util.spec_from_file_location("baidu_rows", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RealPageTest(unittest.TestCase):
    def test_every_id_on_the_real_page_has_setup_and_check(self):
        rows = load_rows()
        ids = [item[0] for item in rows.ITEM.findall((ROOT / "index.html").read_text(encoding="utf-8"))]
        self.assertTrue(ids)
        for key in [*ids, "android"]:
            kind = rows.kind_of(key)
            self.assertIn(kind, rows.SETUP, key)
            self.assertIn(kind, rows.CHECK, key)


class AndroidRowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "index.html").write_text(PAGE, encoding="utf-8")
        (self.dir / "sums.txt").write_text(SUMS, encoding="utf-8")

    def run_script(self, *args):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.dir, env=env, check=True,
                              capture_output=True, text=True, encoding="utf-8", errors="replace").stdout

    def test_rows_list_the_apk_and_count_the_files(self):
        out = self.run_script("0.4.0", "guide.txt")
        self.assertIn("android\t安卓手机\tAndroidAdCleaner-0.4.0-android-arm64.apk", out)
        self.assertIn("2 个文件", (self.dir / "guide.txt").read_text(encoding="utf-8"))

    def test_an_unregistered_id_stops_before_anything_is_uploaded(self):
        # 真实风险：写成 android-arm64 时，以前要等安装包传完、分享链接建好才 KeyError
        page = self.dir / "index.html"
        page.write_text(PAGE.replace('id: "android"', 'id: "android-arm64"'), encoding="utf-8")
        done = subprocess.run([sys.executable, str(SCRIPT), "0.4.0", "guide.txt"], cwd=self.dir,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("android-arm64", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_legacy_guide_for_the_phone_does_not_talk_about_cables(self):
        out_dir = self.dir / "legacy"
        out_dir.mkdir()
        self.run_script("--legacy", "0.4.0", str(out_dir), "sums.txt")
        phone = (out_dir / "安卓手机" / "安装说明.txt").read_text(encoding="utf-8")
        self.assertIn("不用连电脑", phone)
        self.assertNotIn("数据线", phone)
        self.assertIn("SHA-256：2", phone)
        desktop = (out_dir / "Mac-Apple芯片" / "安装说明.txt").read_text(encoding="utf-8")
        self.assertIn("数据线", desktop)

    def test_links_are_written_back_for_the_apk(self):
        subprocess.run([sys.executable, str(SCRIPT), "--write"], cwd=self.dir, check=True, capture_output=True,
                       input="android\thttps://pan.baidu.com/s/x\tabcd\n", text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertIn('id: "android", folder: "安卓手机", baidu: { url: "https://pan.baidu.com/s/x", code: "abcd" }',
                      (self.dir / "index.html").read_text(encoding="utf-8"))

    def run_raw(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.dir, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    def test_unknown_page_id_fails_with_the_id_not_a_traceback(self):
        """id 写成 android-arm64 这类：要在生成说明前停下，并说出是哪个 id。"""
        (self.dir / "index.html").write_text(PAGE.replace('id: "android"', 'id: "android-arm64"'),
                                             encoding="utf-8")
        (self.dir / "legacy").mkdir()
        result = self.run_raw("--legacy", "0.4.0", str(self.dir / "legacy"), "sums.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("android-arm64", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_file_missing_from_the_sums_fails_instead_of_writing_a_blank_digest(self):
        """APK 没写进 SHA256SUMS.txt：安装说明里的校验值不能空着。"""
        (self.dir / "sums.txt").write_text("1  AndroidAdCleaner-0.4.0-mac-arm64.dmg\n", encoding="utf-8")
        (self.dir / "legacy").mkdir()
        result = self.run_raw("--legacy", "0.4.0", str(self.dir / "legacy"), "sums.txt")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AndroidAdCleaner-0.4.0-android-arm64.apk", result.stderr)

    def test_sums_written_in_binary_mode_still_match(self):
        """`sha256sum -b` 写成「hash *文件名」，这一类清单也要认得。"""
        (self.dir / "sums.txt").write_text(
            "1  *AndroidAdCleaner-0.4.0-mac-arm64.dmg\n2  *AndroidAdCleaner-0.4.0-android-arm64.apk\n",
            encoding="utf-8")
        out = self.dir / "legacy"
        out.mkdir()
        result = self.run_raw("--legacy", "0.4.0", str(out), "sums.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        phone = (out / "安卓手机" / "安装说明.txt").read_text(encoding="utf-8")
        self.assertIn("SHA-256：2", phone)

    def test_every_entry_on_the_real_download_page_has_a_legacy_guide(self):
        """旧树也绿，守的是不回退：真实下载页里的每个 id 都要能生成安装说明。

        发版第 6 步给 REL.files 补条目时，id 写法与 SETUP / CHECK 对不上会在这里红。
        """
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        ver = re.search(r'version: "([^"]+)"', page).group(1)
        files = re.findall(r'file: "([^"]+)"', page)
        (self.dir / "index.html").write_text(page, encoding="utf-8")
        (self.dir / "sums.txt").write_text("".join(f"{'0' * 64}  {name}\n" for name in files),
                                           encoding="utf-8")
        out = self.dir / "legacy"
        out.mkdir()
        result = self.run_raw("--legacy", ver, str(out), "sums.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        guides = sorted(p.parent.name for p in out.glob("*/安装说明.txt"))
        self.assertEqual(len(guides), len(files), f"每个条目都要有一份安装说明，实际 {guides}")


if __name__ == "__main__":
    unittest.main()
