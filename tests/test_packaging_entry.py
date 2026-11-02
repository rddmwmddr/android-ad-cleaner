"""打包入口指向的文件必须存在、能 import、并给出 `main`。

`gui/windows.spec`、`gui/build_mac.sh`、`gui/version.py` 里的路径都是字符串，写错了本地全绿、
只有真打包才暴露——而 `build-windows.yml` 不守 PR（#391）。这里只读文件与语法树，不跑打包。
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def spec_entry():
    """windows.spec 里交给 Analysis 的那份脚本。"""
    src = (ROOT / "gui" / "windows.spec").read_text(encoding="utf-8")
    m = re.search(r'Analysis\(\[\s*os\.path\.join\(ROOT,\s*"gui",\s*"([^"]+)"\)', src)
    return m.group(1) if m else ""


def mac_entry():
    """build_mac.sh 里交给 pyinstaller 的那份脚本（行尾重定向到日志）。"""
    src = (ROOT / "gui" / "build_mac.sh").read_text(encoding="utf-8")
    m = re.search(r"(?m)^\s*(gui/[\w./-]+\.py)\s+>/dev/null", src)
    return m.group(1)[len("gui/"):] if m else ""


def version_source():
    """version.py 从哪个文件里读版本号。"""
    src = (ROOT / "gui" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'os\.path\.join\(.*?"([\w.]+\.py)"\)', src)
    return m.group(1) if m else ""


def defines_main(name):
    tree = ast.parse((ROOT / "gui" / name).read_text(encoding="utf-8"))
    return any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)


class PackagingEntryTests(unittest.TestCase):
    def test_windows_spec_entry_exists_and_defines_main(self):
        name = spec_entry()
        self.assertTrue(name, "windows.spec 里找不到 Analysis([... gui/<文件>.py ...])")
        self.assertTrue((ROOT / "gui" / name).exists(), f"gui/{name} 不存在")
        self.assertTrue(defines_main(name), f"gui/{name} 里没有 main()，打包出来的程序没有入口")

    def test_mac_build_entry_exists_and_defines_main(self):
        name = mac_entry()
        self.assertTrue(name, "build_mac.sh 里找不到 pyinstaller 的入口脚本")
        self.assertTrue((ROOT / "gui" / name).exists(), f"gui/{name} 不存在")
        self.assertTrue(defines_main(name), f"gui/{name} 里没有 main()，打包出来的程序没有入口")

    def test_both_packaging_entries_package_the_same_file(self):
        self.assertEqual(spec_entry(), mac_entry(), "Windows 与 Mac 打了不同的入口文件")

    def test_version_source_defines_version(self):
        name = version_source()
        self.assertTrue(name, "version.py 里找不到读取版本号的目标文件")
        src = (ROOT / "gui" / name).read_text(encoding="utf-8")
        self.assertRegex(src, r'(?m)^VERSION = "([^"]+)"', f"gui/{name} 里没有 VERSION，版本号会读空")

    def test_entry_module_imports_without_a_window(self):
        """启动模块在没装 pywebview 的机器上也要能 import：窗口库只在 main() 里才加载。"""
        import importlib
        module = importlib.import_module("gui." + Path(spec_entry()).stem)
        self.assertTrue(callable(getattr(module, "main", None)))


if __name__ == "__main__":
    unittest.main()
