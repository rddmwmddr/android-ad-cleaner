"""段体的注入面（#1209）：`preamble()` 调 `recipe_steps.install()`，实现在脚本执行作用域里现取
前导名字与模块常量；脚本本地不许再留与注入段体逐字相同的 `@step` 副本。

副本守卫的判据是代码逐字（AST 归一后再比）：注入面为空时全绿，搬进一个段体而脚本没删副本即红。
注释、文档串、缩进、段名与函数名都不算差异；代码写得不一样的是机型知识，照旧留在脚本里。
"""
import ast
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import recipe_kit  # noqa: E402
import recipe_nav  # noqa: E402
import recipe_steps  # noqa: E402
from fixtures import normalize, phone_mock  # noqa: E402

RECIPES = tuple(sorted((ROOT / "recipes").rglob("recipe*.py")))


def step_surface():
    """注入面此刻写进执行作用域的 {名字: 实现源码}。"""
    phone, scope = phone_mock(), {}
    recipe_kit.preamble(phone, scope)
    return {name: inspect.getsource(scope[name]) for name in recipe_steps.STEPS}


def step_bodies(source):
    """一份源码里带 `@step(...)` 的函数体：{函数名: 归一后的体}。"""
    tree = ast.parse(normalize(source))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
                isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "step" for decorator in node.decorator_list):
            out[node.name] = "\n".join(ast.unparse(stmt) for stmt in node.body)
    return out


def implementation_bodies(sources):
    """注入实现（工厂造出的那个闭包）的体：{注入名: 体}。段体无形参，比的就是这一段代码。"""
    out = {}
    for name, source in sources.items():
        tree = ast.parse(normalize(source))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        out[name] = "\n".join(ast.unparse(stmt) for stmt in node.body)
    return out


def offenders(scripts, injected):
    """脚本里与注入段体同形的 `@step` 段体：{脚本相对路径: [函数名]}。"""
    bodies = implementation_bodies(injected)
    out = {}
    for label, source in scripts:
        dup = sorted(name for name, body in step_bodies(source).items() if body in bodies.values())
        if dup:
            out[label] = dup
    return out


class WiringTests(unittest.TestCase):
    def test_the_preamble_installs_the_public_steps(self):
        phone, scope = phone_mock(), {}
        with patch.object(recipe_steps, "install", wraps=recipe_steps.install) as install:
            recipe_kit.preamble(phone, scope)
        self.assertEqual(install.call_count, 1)
        self.assertEqual(install.call_args.args, (phone, scope))

    def test_every_registered_step_lands_in_the_scope(self):
        def factory(p, g):
            def downloads():
                return p, g["skip"]
            return downloads

        with patch.dict(recipe_steps.STEPS, {"downloads": factory}):
            phone, scope = phone_mock(), {}
            recipe_kit.preamble(phone, scope)
            p, skip = scope["downloads"]()
        self.assertIs(p, phone)
        self.assertIs(skip, scope["skip"])

    def test_step_names_do_not_collide_with_navigation_names(self):
        """两张注册表写同一个执行作用域、`injected_sources()` 又按名字合并：同名会静默覆盖。"""
        self.assertEqual(set(recipe_steps.STEPS) & set(recipe_nav.NAV), set())

    def test_the_steps_module_does_not_import_the_preamble(self):
        tree = ast.parse((ROOT / "tool" / "recipe_steps.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("recipe_kit", imported, "两个模块互相 import 会绕成环")

    def test_the_facts_layer_sees_the_step_surface(self):
        """`injected_sources()` 合并两张注册表，词库只看段体那一张（#1209）。"""
        import recipe_source

        def factory(p, g):
            def downloads():
                p.off(only=["广告推荐"], page="下载管理·设置")
            return downloads

        with patch.dict(recipe_steps.STEPS, {"downloads": factory}):
            self.assertIn("downloads", recipe_source.injected_sources())
            self.assertIn("downloads", recipe_source.step_sources())
        self.assertNotIn("downloads", recipe_source.step_sources())
        self.assertIn("open_app_settings", recipe_source.injected_sources())


class CopyGuardTests(unittest.TestCase):
    def test_no_script_keeps_a_byte_identical_copy(self):
        scripts = [(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
                   for path in RECIPES]
        self.assertGreaterEqual(len(scripts), 43, "脚本没扫到：路径或通配写错了")
        self.assertEqual(offenders(scripts, step_surface()), {},
                         "脚本还留着注入段体的逐字副本：删掉本地那份，让脚本走注入版")

    def test_the_guard_reports_a_copy_and_spares_a_differing_sibling(self):
        injected = {"downloads": '''\
def _():
    p.off(only=["广告推荐"], page="下载管理·设置")
'''}
        script = '''\
@step("下载管理")
def downloads():
    p.off(only=["广告推荐"], page="下载管理·设置")


@step("下载管理（探路）")
def downloads_probe():
    p.off(only=["广告推荐", "热榜"], page="下载管理·设置")
'''
        self.assertEqual(offenders([("sample.py", script)], injected),
                         {"sample.py": ["downloads"]})

    def test_the_guard_ignores_comments_docstrings_and_the_step_name(self):
        """段名、函数名、注释与折行都不改行为：同一段体换个名字搬回来也要认出来。"""
        injected = {"downloads": '''\
def _():
    p.off(only=NAMES, keep=["仅 Wi-Fi 下载"], page="下载管理·设置")
'''}
        script = '''\
@step("下载管理")
def something_else():
    """这一段要关掉资源推荐。"""
    p.off(
        only=NAMES, keep=["仅 Wi-Fi 下载"],
        page="下载管理·设置")
'''
        self.assertEqual(offenders([("sample.py", script)], injected),
                         {"sample.py": ["something_else"]})

    def test_the_guard_sees_through_the_scope_rewrite(self):
        """注入版把模块常量改成 `g["X"]` 现取：旧写法搬回来也要认出来。"""
        injected = {"downloads": '''\
def _():
    p.off(only=g["HOT"], page="负一屏·设置")
'''}
        script = '''\
@step("负一屏")
def hot():
    p.off(only=HOT, page="负一屏·设置")
'''
        self.assertEqual(offenders([("sample.py", script)], injected),
                         {"sample.py": ["hot"]})


if __name__ == "__main__":
    unittest.main()
