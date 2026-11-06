"""机型脚本只有一个装载入口：`tests/fixtures.py` 的 `load_recipe`。

脚本里的 `time.sleep` 是真等待。用例自己 `exec` 一份脚本、又忘了给 `time` 替身时，
表现只是这条用例慢几秒，不会红 —— 这就是 #630 那条 105 秒 adb 空等与约 37 秒脚本
真 sleep 的来源。这里只读 AST：`tests/` 里除 `fixtures.py` 自己外，不许出现
`runpy.run_path`，也不许直接 exec 一份脚本源码。
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


def _is_call(node, name, dotted=True):
    """名字本身的调用（`exec(...)`），或（dotted 时）任意 `x.<name>(...)`（`runpy.run_path`）。"""
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id == name
    return dotted and isinstance(node.func, ast.Attribute) and node.func.attr == name


def _compile_ast_node(call):
    """`compile(ast.<节点构造>(), ...)`：逐个函数体取一段语法树来跑时用的形状，放行。"""
    if not _is_call(call, "compile", dotted=False) or not call.args:
        return False
    source = call.args[0]
    return (isinstance(source, ast.Call) and isinstance(source.func, ast.Attribute)
            and isinstance(source.func.value, ast.Name) and source.func.value.id == "ast")


def bypasses(tree):
    """[(行号, 说明)]：绕开 load_recipe 的装载点。

    `exec` 的第一实参只接受 `compile(ast.<节点构造>(), …)`；源码先落进变量
    （`source = path.read_text()` 再 `exec(compile(source, …))`）一样要报 ——
    test_redmi_24094rad4c 就是这么写的，判据松一格它就漏网。
    """
    found = []
    for node in ast.walk(tree):
        if _is_call(node, "run_path"):
            found.append((node.lineno, "runpy.run_path 跑机型脚本"))
        elif _is_call(node, "exec", dotted=False):
            source = node.args[0] if node.args else None
            if not _compile_ast_node(source):
                found.append((node.lineno, "exec 直接跑机型脚本源码"))
    return found


class RecipeLoaderGuardTests(unittest.TestCase):
    def test_no_file_under_tests_loads_a_recipe_on_its_own(self):
        checked = 0
        for path in sorted(TESTS.rglob("*.py")):
            if path.name == "fixtures.py":
                continue                                    # 唯一的合法装载点
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for line, reason in bypasses(tree):
                self.fail(f"{path.relative_to(TESTS)}:{line} 绕过了 fixtures.load_recipe：{reason}")
            checked += 1
        self.assertGreater(checked, 10, "没扫到几份用例，这条守卫会变成空转")

    def test_the_guard_rejects_the_shapes_it_used_to_miss(self):
        """判据自己也要有反例：源码先进变量、不带 compile、按名字 import 的 run_path。"""
        for source in (
            "def load(p):\n    exec(compile(self.source, str(path), 'exec'), scope)\n",
            "def load(p):\n    exec(path.read_text(encoding='utf-8'), scope)\n",
            "from runpy import run_path\ndef load(p):\n    run_path(str(path))\n",
            "def load(p):\n    exec(compile(path.read_bytes(), str(path), 'exec'), scope)\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(bypasses(ast.parse(source)), source)

    def test_load_recipe_itself_never_sleeps_for_real(self):
        script = "import time\nBUILD = 'x'\nMODELS = ['x']\ntime.sleep(30)\nVALUE = 1\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            started = time.monotonic()
            scope, _ = load_recipe(object(), path)
            elapsed = time.monotonic() - started
        self.assertEqual(scope["VALUE"], 1)
        self.assertLess(elapsed, 1.0, "装载时真的睡眠了")
        self.assertIsInstance(scope["time"], fixtures.RecipeClock)
        scope["time"].sleep(30)                       # 装载之后脚本里的 sleep 也不占真实时间
        self.assertLess(time.monotonic() - started, 1.0)

    def test_a_deadline_loop_polls_through_the_fake_clock_instead_of_busy_waiting(self):
        """三个读数要成套：只挡 sleep 而让 time() 走真实时钟，这个循环会忙转满 5 秒。"""
        script = ("import time\nBUILD = 'x'\nMODELS = ['x']\nROUNDS = 0\n"
                  "def spin():\n"
                  "    global ROUNDS\n"
                  "    deadline = time.time() + 5\n"
                  "    while time.time() < deadline:\n"
                  "        ROUNDS += 1\n"
                  "        time.sleep(0.2)\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            scope, _ = load_recipe(object(), path)
            started = time.monotonic()
            scope["spin"]()
            elapsed = time.monotonic() - started
        self.assertEqual(scope["ROUNDS"], 25)
        self.assertLess(elapsed, 1.0, "截止时间循环在真实时钟上忙转了")


if __name__ == "__main__":
    unittest.main()
