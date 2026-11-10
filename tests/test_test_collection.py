"""用例只在 tests/ 下定义（#972）：`discover -s tests` 收不到别处的 `def test_`。

`recipes/` 下两份社区配方的 test_recipe.py 就这样白跑了 16 天 —— 收集只看 tests/，
`.coveragerc` 的 source 是 tool/gui，ruff 的范围也不含 recipes，三道关一个都没看见。
守卫只认名字不认归属：tests/ 之外的任何 .py 里出现 `def test_` 都算越界。
"""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
# 隐藏目录（.git / .venv / .private / .worktrees …）一律不扫，剩下这两个是可见的
SKIP_DIRS = {"node_modules", "build"}
DEF_TEST = re.compile(r"^[ \t]*def test_", re.M)


def python_sources(root=ROOT):
    """仓库里所有非隐藏、非依赖目录下的 .py。"""
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(folder, name)


class CollectionTests(unittest.TestCase):
    def test_no_test_functions_outside_the_tests_folder(self):
        offenders = {}
        for path in python_sources():
            if TESTS in path.parents:
                continue
            found = DEF_TEST.findall(path.read_text(encoding="utf-8"))
            if found:
                offenders[path.relative_to(ROOT).as_posix()] = len(found)
        self.assertEqual(offenders, {}, "用例只在 tests/ 下定义，别的目录里的 def test_ 不会被收集到")


if __name__ == "__main__":
    unittest.main()
