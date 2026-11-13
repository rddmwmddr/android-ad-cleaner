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
from unittest.mock import Mock

import fixtures
from fixtures import load_recipe

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
RECIPES = tuple(sorted((ROOT / "recipes").rglob("recipe*.py")))

fixtures.load_tool()
import adapt  # noqa: E402
import recipe_loader  # noqa: E402
import recipe_runtime  # noqa: E402


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


def module_body_offenders(source, filename="<script>"):
    """模块体里不属于「导入 / 定义 / 常量 / `if TYPE_CHECKING:` / 模块 docstring」的语句。

    返回 [(行号, 语句类型)]；空表示形状合规。脚本的顺序与钩子都由装载器驱动，模块体里多写一句
    `print` / `for` / `p…()` 就会在导入时执行，破坏「导入零动作」。
    """
    allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
               ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    found = []
    for node in ast.parse(source, filename).body:
        if isinstance(node, allowed):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue                                  # 模块 docstring
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) \
                and node.test.id == "TYPE_CHECKING":
            continue
        found.append((node.lineno, type(node).__name__))
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

    def test_loading_any_recipe_makes_no_device_calls(self):
        """导入零动作：装载 47 份脚本，`Phone` 上一个方法都不许被调用（段只在 `run()` 里跑）。

        这条同时守住「`@step` 只登记、不执行」：任何一份把动作写在模块体里、或让装饰器在装载时
        执行段体，这里都会看到 `mock_calls` 非空。
        """
        for path in RECIPES:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                phone = Mock()
                recipe_loader.load(path, phone)
                self.assertEqual(phone.mock_calls, [],
                                 f"{path.relative_to(ROOT)} 在装载时碰了手机")

    def test_module_body_has_only_definitions_and_constants(self):
        """模块体里除导入 / 定义 / 常量 / `if TYPE_CHECKING:` / docstring 之外不许多余语句。

        多余语句在导入时执行，等于把执行顺序藏进模块体；钩子与顺序由装载器驱动（ADR-0037）。
        """
        offenders = {}
        for path in RECIPES:
            found = module_body_offenders(path.read_text(encoding="utf-8"), str(path))
            if found:
                offenders[path.relative_to(ROOT).as_posix()] = found
        self.assertEqual(offenders, {},
                         "模块体里有会被导入执行的语句：搬进 `tail()` / 段体 / 模块级助手，"
                         "或确属声明式钩子")

    def test_the_shape_guard_reports_the_statement_it_used_to_allow(self):
        """判据自己也要有反例：旧脚本结尾的模块级打印与手写循环都要被这条挡住。"""
        for source in (
            "print('收尾')\n",
            "for name, state in RESULTS:\n    print(name, state)\n",
            "p.start('com.example')\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(module_body_offenders(source), source)
        self.assertFalse(module_body_offenders("BUILD = 'x'\ndef helper():\n    pass\n"))

    def test_duplicate_step_names_are_rejected_at_load(self):
        """段名进失败段与客户端重试，必须唯一；重名在装载时就报，而不是让两段互相覆盖。"""
        script = ('BUILD = "x"\n\n@step("同名")\ndef _a():\n    pass\n\n'
                  '@step("同名")\ndef _b():\n    pass\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "recipe.py")
            path.write_text(script, encoding="utf-8")
            with self.assertRaisesRegex(recipe_runtime.DuplicateStep, "段名重复"):
                recipe_loader.load(path, Mock())

    def test_the_generated_draft_loads_through_the_same_loader(self):
        """`adapt gen` 的草稿带 import 头，仍走同一个装载入口；旧草稿没有 import 头也一样装得进去
        （`step` 由装载器注入）。"""
        draft = adapt.render_draft([("com.example", "设置 > 隐私", ["个性化推荐"])],
                                   "PLP120", "PLP120_16.0.9", "探路.tsv")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "草稿.py")
            path.write_text(draft, encoding="utf-8")
            recipe = recipe_loader.load(path, Mock(), only=["com.example · 设置 > 隐私"])
        self.assertEqual([step.name for step in recipe.steps], ["com.example · 设置 > 隐私"])
        self.assertTrue(callable(recipe.namespace.get("tail")))


if __name__ == "__main__":
    unittest.main()
