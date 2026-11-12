"""公共导航的注入面（#1150）：`preamble()` 调 `recipe_nav.install()`，实现从执行作用域取前导
名字；脚本本地不许再留与注入面逐字相同的副本；调用序列对拍驱动自己管基线 worktree。

副本守卫的判据是代码逐字（AST 归一后再比）：注入面为空时全绿，搬进一个簇而脚本没删副本即红。
注释与文档串不算差异；同名多簇照旧合法 —— 代码写得不一样的是机型知识。
"""
import ast
import inspect
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402
import recipe_kit  # noqa: E402
import recipe_nav  # noqa: E402
from fixtures import normalize, phone_mock  # noqa: E402

RECIPES = tuple(sorted((ROOT / "recipes").rglob("recipe*.py")))
DRIVER = ROOT / "tests" / "compare_recipe_calls.py"


def surface():
    """注入面此刻写进执行作用域的 {名字: 实现源码}。"""
    phone = phone_mock()
    scope = {}
    recipe_kit.preamble(phone, scope)
    return {name: normalize(inspect.getsource(scope[name])) for name in recipe_nav.NAV}


def kept_copies(scripts, injected):
    """脚本里与注入面逐字相同的模块级函数：{脚本相对路径: [名字]}。"""
    offenders = {}
    for label, source in scripts:
        local = {}
        for node in ast.parse(source, label).body:
            if isinstance(node, ast.FunctionDef):
                local[node.name] = normalize(ast.get_source_segment(source, node) or "")
        dup = sorted(name for name, text in local.items()
                     if name in injected and text == injected[name])
        if dup:
            offenders[label] = dup
    return offenders


class WiringTests(unittest.TestCase):
    def test_the_preamble_installs_the_public_navigation(self):
        phone, scope = phone_mock(), {}
        with patch.object(recipe_nav, "install", wraps=recipe_nav.install) as install:
            recipe_kit.preamble(phone, scope)
        self.assertEqual(install.call_count, 1)
        self.assertEqual(install.call_args.args, (phone, scope))

    def test_the_xiaomi_family_helpers_are_installed(self):
        """#1151 收的五个簇都在注入面里：脚本删了本地定义，靠的就是这几个名字。"""
        phone, scope = phone_mock(), {}
        recipe_kit.preamble(phone, scope)
        self.assertLessEqual({"tap_any", "gear", "close_named", "read_switches", "security_tab"},
                             set(scope))

    def test_the_remaining_navigation_clusters_are_installed(self):
        """按代码逐字判据翻出来的六个簇（#1148）：脚本侧同名定义已删，靠的就是这几个名字。"""
        phone, scope = phone_mock(), {}
        recipe_kit.preamble(phone, scope)
        self.assertLessEqual({"wait_page", "off_unnamed", "opened", "popup_row", "tap_tab",
                              "hide_carousel"}, set(scope))

    def test_injected_helpers_read_the_preamble_names_from_the_scope(self):
        """实现从执行作用域取 `skip` / `require`，所以 `recipe_nav` 不用 import `recipe_kit`。"""
        phone = phone_mock()

        def factory(p, g):
            def sample_helper():
                return p, g["skip"], g["require"]
            return sample_helper

        with patch.dict(recipe_nav.NAV, {"sample_helper": factory}):
            scope = {}
            recipe_kit.preamble(phone, scope)
            p, skip, require = scope["sample_helper"]()
        self.assertIs(p, phone)
        self.assertIs(skip, scope["skip"])
        self.assertIs(require, scope["require"])

    def test_the_navigation_module_does_not_import_the_preamble(self):
        tree = ast.parse((ROOT / "tool" / "recipe_nav.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("recipe_kit", imported, "两个模块互相 import 会绕成环")


class CopyGuardTests(unittest.TestCase):
    def test_no_script_keeps_a_byte_identical_copy(self):
        scripts = [(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
                   for path in RECIPES]
        self.assertGreaterEqual(len(scripts), 43, "脚本没扫到：路径或通配写错了")
        self.assertEqual(kept_copies(scripts, surface()), {},
                         "脚本还留着注入面的逐字副本：删掉本地定义，让脚本走注入版")

    def test_the_guard_reports_a_copy_and_spares_a_differing_sibling(self):
        script = '''\
def gear(toolbar_only=False):
    return p.find("设置", exact=True)


def close_named(names, page):
    return p.off(only=names, page=page)
'''
        injected = {
            "gear": normalize('''\
def gear(toolbar_only=False):
    return p.find("设置", exact=True)
'''),
            "close_named": normalize('''\
def close_named(names, page):
    return p.off(only=names, page=page, max_screens=12)
'''),
        }
        self.assertEqual(kept_copies([("sample.py", script)], injected),
                         {"sample.py": ["gear"]})

    def test_the_guard_sees_through_the_scope_rewrite(self):
        """注入版把脚本全局改成 `g["X"]` 现取：旧写法搬回来也要认出来（#1151）。"""
        script = '''\
def tap_any(*names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(n, scrolls) for n in names)
'''
        injected = {"tap_any": normalize('''\
def tap_any(*names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(g["maybe"](n, scrolls) for n in names)
''')}
        self.assertEqual(kept_copies([("sample.py", script)], injected),
                         {"sample.py": ["tap_any"]})

    def test_the_guard_ignores_comments_docstrings_and_wrapping(self):
        """代码相同、注释与折行不同也算副本（#1153）：V2309A 那份就是被文本判据漏掉的。"""
        injected = {"gear": normalize('''\
def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标。"""
    return p.find("设置", exact=True)
''')}
        script = '''\


def gear(toolbar_only=False):
    # 注释与文档串各写各的
    return p.find(
        "设置", exact=True)
'''
        self.assertEqual(kept_copies([("sample.py", script)], injected),
                         {"sample.py": ["gear"]})


class DriverTests(unittest.TestCase):
    def setUp(self):
        probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        if probe.returncode:
            self.skipTest("git archive 出来的干净副本没有 .git；这条只在 git 工作区里跑")

    def worktrees(self):
        return subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=True).stdout

    def test_unknown_sha_fails_without_leaving_a_worktree(self):
        before = self.worktrees()
        # 驱动自己把 stdio 转成 UTF-8；这里只负责按 UTF-8 解码（Windows 管道默认 cp1252）
        proc = subprocess.run([sys.executable, str(DRIVER), "--baseline", "0" * 40],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("找不到提交", proc.stderr)     # 守卫：走到了「拉基线失败」这一支
        self.assertEqual(self.worktrees(), before)

    def test_the_recorder_catches_a_script_calling_the_phone(self):
        """记录器真的记到了门面方法与 `p.d.shell`：一份脚本装载后既有段首的拉起，也有直发命令。"""
        import compare_recipe_calls as driver
        import fast
        calls = driver.run_script(fast, recipe_kit, fixtures,
                                  ROOT / "recipes" / "xiaomi-24090RA29C" / "recipe.py", "present")
        names = [call[0] for call in calls]
        self.assertIn("start", names)
        self.assertIn("entry", names)
        self.assertIn("d.shell", names)
        self.assertGreater(len(calls), 40)

    def test_the_comparison_reports_drift_and_the_empty_comparison(self):
        """驱动自己的三条结论：序列不同、某个场景一条都没记到、总量低于下限 —— 都要报出来。"""
        import compare_recipe_calls as driver
        calls = [["start", ["com.example.app"], {}]]
        base = {"a.py": {"present": calls, "absent": calls}}
        drifted = {"a.py": {"present": calls + [["click", [1, 2], {}]], "absent": calls}}
        found, _ = driver.problems(base, drifted)
        self.assertTrue(any(summary.startswith("a.py[present]") for summary, _ in found), found)

        silent = {"a.py": {"present": calls, "absent": []}}
        found, _ = driver.problems(silent, silent)
        self.assertIn("一条调用都没记到", [summary for summary, _ in found])

        found, total = driver.problems(base, base)
        self.assertIn("对拍没测到东西", [summary for summary, _ in found])
        self.assertLess(total, driver.MIN_CALLS)


if __name__ == "__main__":
    unittest.main()
