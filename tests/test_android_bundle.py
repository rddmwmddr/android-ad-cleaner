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


def bundle_line(folder):
    """构建脚本里拷某个目录的那一行（`folder` 是 `resolve("...")` 里的目录名）。"""
    lines = [line for line in GRADLE.read_text(encoding="utf-8").splitlines()
             if f'resolve("{folder}")' in line]
    if len(lines) != 1:
        raise AssertionError(f"构建脚本里应只有一处 {folder} 拷贝清单，实际 {len(lines)} 处")
    return lines[0]


def include_names(line):
    match = re.search(r"include\(([^)]*)\)", line)
    if match is None:
        raise AssertionError(f"拷贝清单里没有 include(...)：{line}")
    return [part.strip().strip('"') for part in match.group(1).split(",") if part.strip()]


def exclude_names(line):
    match = re.search(r"exclude\(([^)]*)\)", line)
    if match is None:
        return []
    return [part.strip().strip('"') for part in match.group(1).split(",") if part.strip()]


def ant_match(path, pattern):
    """Ant / Gradle 的 include 口径：`**` 跨目录段（含零段），`*` 只在单段内匹配。"""
    parts, pat = path.split("/"), pattern.split("/")

    def go(i, j):
        if j == len(pat):
            return i == len(parts)
        if pat[j] == "**":
            return go(i, j + 1) or (i < len(parts) and go(i + 1, j))
        if i >= len(parts):
            return False
        return fnmatch.fnmatchcase(parts[i], pat[j]) and go(i + 1, j + 1)

    return go(0, 0)


def packaged(folder):
    """构建脚本对 `<folder>/<相对路径>` 的判定（include 命中且 exclude 未命中）。"""
    line = bundle_line(folder)
    includes = include_names(line)
    excludes = exclude_names(line)

    def covered(rel):
        return (any(ant_match(rel, pattern) for pattern in includes)
                and not any(ant_match(rel, pattern) for pattern in excludes))

    return covered


def gui_bundle_files():
    """按构建脚本原样取出拷进 assets/aac/gui 的文件清单（include 减去 exclude）。"""
    line = bundle_line("gui")
    excluded = re.search(r"exclude\(([^)]*)\)", line)
    patterns = [part.strip().strip('"') for part in excluded.group(1).split(",") if part.strip()] if excluded else []
    return [name for name in include_names(line) if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns)]


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


class AndroidRecipeBundleTests(unittest.TestCase):
    def test_recipes_copy_carries_the_verification_ledger(self):
        """手机宿主也读 `recipes/verified.toml`（status-json 的验证档位，#1124）：漏了这一行，
        手机上跟桌面版就差一个值，而且要到真机跑 status-json 才发现。"""
        self.assertIn("verified.toml", include_names(bundle_line("recipes")))

    def test_recipes_copy_covers_every_recipe_file(self):
        """数据是 `recipes/<家族>/<型号>/<型号>.toml`（含变体），例外是同目录的 `.py`。

        `*/recipe*.py` 那套旧口径在迁移后一份都匹配不到（#1269），这里按真实布局对一遍。"""
        covered = packaged("recipes")
        files = [path for path in sorted((ROOT / "recipes").glob("*/*/*"))
                 if path.is_file() and path.suffix in (".toml", ".py")]
        self.assertTrue(files)
        missing = [path.relative_to(ROOT / "recipes").as_posix()
                   for path in files if not covered(path.relative_to(ROOT / "recipes").as_posix())]
        self.assertEqual(missing, [], "这些机型数据/例外没进 APK")

    def test_recipe_library_is_copied(self):
        """库实现现在住在 `recipe_lib/`（#1269）：不随包发出去，手机上 `import recipe_nav` 就会断。"""
        covered = packaged("recipe_lib")
        files = [path.name for path in sorted((ROOT / "recipe_lib").glob("*.py"))]
        self.assertTrue(files)
        self.assertEqual([name for name in files if not covered(name)], [])


class AndroidToolBundleTests(unittest.TestCase):
    def test_tool_copy_covers_every_module(self):
        covered = packaged("tool")
        files = [path.relative_to(ROOT / "tool").as_posix()
                 for path in sorted((ROOT / "tool").rglob("*.py"))]
        self.assertTrue(files)
        self.assertEqual([rel for rel in files if not covered(rel)], [], "这些引擎模块没进 APK")


if __name__ == "__main__":
    unittest.main()
