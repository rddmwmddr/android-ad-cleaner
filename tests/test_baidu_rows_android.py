"""#714：下载页和网盘说明要认得手机版 APK。"""
import os
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


if __name__ == "__main__":
    unittest.main()
