"""APK 里那批 gui 文件必须覆盖 gui/app.py 的导入期依赖（#1054）。

手机入口启动早期就 `import app`，漏一个模块就是启动即崩；桌面端与回归都在
完整的 gui/ 上跑，抓不到这类清单漂移。
"""
import fnmatch
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"


def gui_bundle_files():
    """按构建脚本原样取出拷进 assets/aac/gui 的文件清单（include 减去 exclude）。"""
    lines = [line for line in GRADLE.read_text(encoding="utf-8").splitlines()
             if 'resolve("gui")' in line]
    if len(lines) != 1:
        raise AssertionError(f"构建脚本里应只有一处 gui 拷贝清单，实际 {len(lines)} 处")
    line = lines[0]
    match = re.search(r"include\(([^)]*)\)", line)
    if match is None:
        raise AssertionError(f"gui 拷贝清单里没有 include(...)：{line}")
    names = [part.strip().strip('"') for part in match.group(1).split(",") if part.strip()]
    excluded = re.search(r"exclude\(([^)]*)\)", line)
    patterns = [part.strip().strip('"') for part in excluded.group(1).split(",") if part.strip()] if excluded else []
    return [name for name in names if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns)]


class AndroidGuiBundleTests(unittest.TestCase):
    def test_listed_files_exist(self):
        missing = [name for name in gui_bundle_files() if not (ROOT / "gui" / name).exists()]
        self.assertEqual(missing, [])

    def test_desktop_client_imports_from_the_android_bundle(self):
        names = gui_bundle_files()
        modules = [Path(name).stem for name in names if name.endswith(".py")]
        with tempfile.TemporaryDirectory() as tmp:
            gui = Path(tmp) / "gui"
            for name in names:
                dest = gui / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((ROOT / "gui" / name).read_bytes())
            # -I 只屏蔽 cwd、PYTHONPATH 与 user site，解释器自带的 site-packages 仍可 import；
            # 所以逐个核对这些模块确实来自临时目录，免得同名已装包把缺的那个补上、测成假绿
            proc = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import importlib, sys\n"
                 "sys.path.insert(0, sys.argv[1])\n"
                 "mods = [importlib.import_module(name) for name in sys.argv[2:]]\n"
                 "print(''.join('FILE ' + mod.__file__ + '\\n' for mod in mods))",
                 str(gui), *modules],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            files = [line[len("FILE "):] for line in proc.stdout.splitlines() if line.startswith("FILE ")]
            self.assertEqual(len(files), len(modules), proc.stdout)
            outside = [path for path in files if not path.startswith(str(gui))]
            self.assertEqual(outside, [], "这些模块不是从 APK 会带的那份目录里加载的")


if __name__ == "__main__":
    unittest.main()
