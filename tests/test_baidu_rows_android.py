"""#714：下载页和网盘说明要认得手机版 APK。"""
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
