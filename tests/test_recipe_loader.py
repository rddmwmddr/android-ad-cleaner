"""机型脚本只有一个装载入口：`tests/fixtures.py` 的 `load_recipe`。

脚本里的 `time.sleep` 是真等待。用例自己 `exec` 一份脚本、又忘了给 `time` 替身时，
表现只是这条用例慢几秒，不会红 —— 这就是 #630 那条 105 秒 adb 空等与约 37 秒脚本
真 sleep 的来源。这里只读 AST：`tests/` 里除 `fixtures.py` 自己外，不许出现
`runpy.run_path`，也不许直接 exec 一份脚本源码。
"""
import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

import fixtures

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
# 47 份数据（`verified.toml` 是台账不是机型数据）。迁移后没有 `recipe*.py` 了：glob 那个模式
# 匹配 0 份，下面「装载时不许碰手机」的循环就一次都不跑（#1268）。
RECIPES = tuple(sorted(toml for toml in (ROOT / "recipes").rglob("*.toml")
                       if toml.name != "verified.toml"))
# 型号目录的判据是「里面有配方文件」，不是「是个目录」：迁移前的旧布局目录
# （`recipes/<家族>-<型号>/`）可能只留下 `__pycache__`，按目录数会把它们算成缺数据的型号。
MODEL_DIRS = tuple(sorted(d for d in (ROOT / "recipes").glob("*/*")
                          if d.is_dir() and any(f.suffix in (".toml", ".py") for f in d.iterdir()
                                                if f.is_file())))

fixtures.load_tool()
import recipe_loader  # noqa: E402


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


    def test_every_model_directory_is_loaded(self):
        """发现本身要有内容：每个型号目录都得出至少一份数据，别让下面那条循环静默空转。

        判据是目录与数据的对应关系，不是写死的份数——数据增删时这条不用跟着改。
        """
        covered = {toml.parent for toml in RECIPES}
        missing = [str(d.relative_to(ROOT)) for d in MODEL_DIRS if d not in covered]
        self.assertEqual(missing, [], "这些型号目录没有可装载的数据文件")

    def test_loading_any_recipe_makes_no_device_calls(self):
        """导入零动作：装载全部数据，`Phone` 上一个方法都不许被调用（段只在 `run()` 里跑）。

        这条同时守住「段只登记、不执行」：任何一份把动作写在模块体里、或让装载器在装载时
        执行段体，这里都会看到 `mock_calls` 非空。例外 `.py` 的模块体也在装载时 exec，
        所以它们的形状另外由 `test_exception_modules_have_no_import_time_statements` 钉。
        """
        self.assertGreaterEqual(len(RECIPES), len(MODEL_DIRS), "发现到的数据比型号目录还少")
        for path in RECIPES:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                phone = Mock()
                recipe_loader.load(path, phone)
                self.assertEqual(phone.mock_calls, [],
                                 f"{path.relative_to(ROOT)} 在装载时碰了手机")

    def test_exception_modules_have_no_import_time_statements(self):
        """例外 `.py` 由装载器 `exec` 进一个 dict，模块体里多一句就会在装载时执行。

        形状判据在 `module_body_offenders()`：只允许导入 / 定义 / 常量 / `if TYPE_CHECKING:`
        与模块 docstring。
        """
        sources = fixtures.recipe_sources()
        self.assertTrue(sources, "没扫到例外 .py：`recipe_sources()` 的口径或数据搬家了")
        offenders = []
        for path in sources:
            for line, kind in module_body_offenders(path.read_text(encoding="utf-8"), str(path)):
                offenders.append(f"{path.relative_to(ROOT)}:{line} 模块体里写了 {kind}")
        self.assertEqual(offenders, [], "装载时就会执行的语句不在允许的形状里")






if __name__ == "__main__":
    unittest.main()
