"""`import gui.app` 不许有副作用：不建用户数据目录、不改 sys.path、不加载 tool/ 下的模块（#355）。

子进程 + 临时 HOME/APPDATA 跑真正的 import：测的是「导入这个模块本身做了什么」，不是某条路径的返回值。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CODE = """
import json, os, sys
before = list(sys.path)
import gui.app
tool = os.path.join(gui.app.BASE, "tool") + os.sep
loaded = sorted(m.__name__ for m in list(sys.modules.values())
                if getattr(m, "__file__", None) and str(m.__file__).startswith(tool))
print(json.dumps({"path_changed": sys.path != before, "tool_modules": loaded, "data": gui.app.data_dir()}))
"""


class ImportSideEffectTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.home = Path(self.dir.name, "home")
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), APPDATA=str(Path(self.dir.name, "AppData")))

    def run_import(self):
        done = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, env=self.env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_import_does_not_touch_disk_or_sys_path(self):
        seen = self.run_import()
        self.assertFalse(seen["path_changed"], "import gui.app 改了 sys.path")
        self.assertEqual(seen["tool_modules"], [], "import gui.app 加载了 tool/ 下的模块")
        # 三个平台的数据目录都不许出现（子进程里的 data_dir() 走的是哪个，取决于跑测试的系统）
        for leftover in (Path(self.home, "Library/Application Support/AndroidAdCleaner"),
                         Path(self.home, ".local/share/android-ad-cleaner"),
                         Path(self.dir.name, "AppData/AndroidAdCleaner")):
            self.assertFalse(leftover.exists(), f"import gui.app 建了 {leftover}")

    def test_data_dir_points_at_the_same_place_as_before(self):
        # data_dir() 只换了「建不建目录」，位置判定逐字不变
        seen = self.run_import()
        self.assertEqual(Path(seen["data"]), Path(
            self.dir.name, "AppData/AndroidAdCleaner") if os.name == "nt" else
            (Path(self.home, "Library/Application Support/AndroidAdCleaner") if sys.platform == "darwin"
             else Path(self.home, ".local/share/android-ad-cleaner")))


if __name__ == "__main__":
    unittest.main()
