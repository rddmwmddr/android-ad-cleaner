"""`import gui.app` 不许有副作用：不建用户数据目录、不改 sys.path、不加载 tool/ 下的模块（#355）。

`gui/toolpath.py` 是那份惰性加载的唯一出口：configure 之后才按名字加载，没 configure 要报可读的错（#1381）。

子进程 + 临时 HOME/APPDATA 跑真正的 import：测的是「导入这个模块本身做了什么」，不是某条路径的返回值。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gui import toolpath

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

# 未 configure 的那条只能在干净进程里测：本进程的 toolpath 早被 gui.app 配好了，reload 会连累别的用例
UNCONFIGURED = """
import json, sys
sys.path.insert(0, sys.argv[1])
import toolpath
try:
    toolpath.tool("plan")
except RuntimeError as e:
    message = str(e)
else:
    message = ""
print(json.dumps({"message": message}))
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


class ToolPathTests(unittest.TestCase):
    """gui/ 到 tool/ 的惰性加载只有一份实现，落在 gui/toolpath.py（#1381）。"""

    def test_configured_root_loads_a_real_tool_module(self):
        toolpath.configure(ROOT)
        self.assertEqual(Path(toolpath.TOOL), ROOT / "tool")
        self.assertTrue(hasattr(toolpath.tool("plan"), "Plan"), "configure 之后要能加载 tool/plan.py")

    def test_loading_before_configure_says_so(self):
        done = subprocess.run([sys.executable, "-c", UNCONFIGURED, str(ROOT / "gui")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        message = json.loads(done.stdout.strip().splitlines()[-1])["message"]
        self.assertIn("configure", message, f"未 configure 时的报错要点明缺的这一步：{message!r}")


if __name__ == "__main__":
    unittest.main()
