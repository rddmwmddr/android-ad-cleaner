"""收集守卫（rule:dev.tests.cases-live-under-tests）：`discover -s tests` 只收 tests/。

tests/ 之外的 .py 里出现 `def test_` 即红，逐文件列出命中数；隐藏目录与 node_modules /
build 不扫。
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 隐藏目录（.git / .venv / .private / .worktrees …）一律不扫，剩下这两个是可见的
SKIP_DIRS = {"node_modules", "build"}
DEF_TEST = re.compile(r"^[ \t]*def test_", re.M)


def offenders_in(root):
    """{相对路径: 命中数}：root/tests 之外定义用例的文件。"""
    found = {}
    tests = root / "tests"
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(files):
            path = Path(folder, name)
            if not name.endswith(".py") or tests in path.parents:
                continue
            hits = DEF_TEST.findall(path.read_text(encoding="utf-8"))
            if hits:
                found[path.relative_to(root).as_posix()] = len(hits)
    return found


class CollectionTests(unittest.TestCase):
    def test_no_test_functions_outside_the_tests_folder(self):
        self.assertEqual(offenders_in(ROOT), {}, "用例只在 tests/ 下定义，别的目录里的 def test_ 收集不到")

    def test_a_stray_test_function_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests/test_ok.py").write_text(
                "class T:\n    def test_ok(self):\n        pass\n", encoding="utf-8")
            (root / "recipes").mkdir()
            (root / "recipes/test_stray.py").write_text(
                "class T:\n    def test_stray(self):\n        pass\n", encoding="utf-8")
            self.assertEqual(offenders_in(root), {"recipes/test_stray.py": 1})


if __name__ == "__main__":
    unittest.main()
