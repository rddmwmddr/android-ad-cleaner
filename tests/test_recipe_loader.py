"""机型脚本只有一个装载入口：`tests/fixtures.py` 的 `load_recipe`。

脚本里的 `time.sleep` 是真等待。用例自己 `exec` 一份脚本、又忘了给 `time` 替身时，
表现只是这条用例慢几秒，不会红 —— #630 之前全量 166 秒里约 140 秒是这么来的。
这里只读 AST：`tests/` 里不许出现 `runpy.run_path`，也不许直接 exec 整份脚本源码。
"""
import ast
import tempfile
import time
import unittest
from pathlib import Path

import fixtures
from fixtures import load_recipe

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _exec_source(call):
    """`exec(compile(<源码>, ...))` 里的 <源码>；不是这个形状返回 None。

    逐个函数体取一段 `ast.Module` 来跑（如 test_oppo_pmx110_recipe 的 `action()`）
    传的不是整份脚本源码，形状对不上，这里不拦。
    """
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "exec"):
        return None
    if not call.args:
        return None
    inner = call.args[0]
    if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "compile"):
        return None
    return inner.args[0] if inner.args else None


def _reads_whole_script(node):
    """`<path>.read_text(...)`：把整份脚本源码读出来再 exec。"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_text")


def bypasses(tree):
    """[(行号, 说明)]：绕开 load_recipe 的装载点。"""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "run_path":
            found.append((node.lineno, "runpy.run_path 跑机型脚本"))
        source = _exec_source(node)
        if source is not None and _reads_whole_script(source):
            found.append((node.lineno, "exec(compile(...read_text())) 直接装载机型脚本"))
    return found


class RecipeLoaderGuardTests(unittest.TestCase):
    def test_no_test_file_loads_a_recipe_on_its_own(self):
        checked = 0
        for path in sorted(TESTS.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for line, reason in bypasses(tree):
                self.fail(f"{path.name}:{line} 绕过了 fixtures.load_recipe：{reason}")
            checked += 1
        self.assertGreater(checked, 10, "没扫到几份用例，这条守卫会变成空转")

    def test_load_recipe_itself_never_sleeps_for_real(self):
        script = "import time\nBUILD = 'x'\nMODELS = ['x']\ntime.sleep(30)\nVALUE = 1\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            started = time.monotonic()
            scope, _ = load_recipe(object(), path)
            elapsed = time.monotonic() - started
        self.assertEqual(scope["VALUE"], 1)
        self.assertLess(elapsed, 1.0, "装载时真的 sleeps 了")
        self.assertIsInstance(scope["time"], fixtures.RecipeClock)
        scope["time"].sleep(30)                       # 装载之后脚本里的 sleep 也不占真实时间
        self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
