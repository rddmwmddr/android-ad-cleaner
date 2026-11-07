"""机型脚本拉起主题管理包必须带 activity（#730）。

`com.android.thememanager` 没有 LAUNCHER activity：`Phone.start` 不带 activity 会退到
monkey，一律 `** No activities found to run, monkey aborted.`，主题段必失败。主题商店
（`com.miui.themestore`）不可见的机型正好落在兜底分支上，所以兜底也要带 activity。
"""
import ast
import io
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import entries
from fixtures import load_recipe, phone_mock

# 活动名只认 entries 这一处：它改名时守卫要跟着红，而不是脚本与用例一起静默漂移。
_ENTRY = next(d for d in entries.ENTRIES["xiaomi"]["主题"].direct if d.pkg == "com.android.thememanager")
THEME, DIRECT = _ENTRY.pkg, _ENTRY.activity
SKIP = "本机没有主题商店，跳过"


def recipes():
    return sorted((ROOT / "recipes").glob("*/recipe*.py"))


def literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def monkey_shells(tree):
    """`p.d.shell("… monkey … com.android.thememanager …")`：注定 abort 的那条命令。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "shell"):
            continue
        text = literal(node.args[0])
        if text and "monkey" in text and THEME in text:
            hits.append(node.lineno)
    return hits


def bare_starts(tree):
    """`p.start("com.android.thememanager")`（activity 缺省 / 空）：引擎会退到 monkey。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "start"):
            continue
        if literal(node.args[0]) != THEME:
            continue
        activity = node.args[1] if len(node.args) > 1 else None
        for keyword in node.keywords:
            if keyword.arg == "activity":
                activity = keyword.value
        if activity is None or (isinstance(activity, ast.Constant) and not activity.value):
            hits.append(node.lineno)
    return hits


class ThemeEntryGuardTests(unittest.TestCase):
    def test_recipes_launch_thememanager_with_an_activity(self):
        found = recipes()
        self.assertTrue(found, "recipes/ 下一份机型脚本都没找到")
        for path in found:
            rel = path.relative_to(ROOT)
            with self.subTest(recipe=str(rel)):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                self.assertEqual(monkey_shells(tree), [], f"{rel}: 用 monkey 拉起 {THEME}")
                self.assertEqual(bare_starts(tree), [], f"{rel}: 不带 activity 的 Phone.start")


class ThemeFallbackBehaviourTests(unittest.TestCase):
    """兜底分支的两种结局：已装则直达代理标签页，没装则跳过本段而不是记失败。"""

    def load(self, path, themestore, thememanager):
        p = phone_mock()
        p.locked = lambda: False
        p.tree.return_value.iter.return_value = []
        p.texts.return_value = []
        paths = {"com.miui.themestore": themestore, THEME: thememanager}

        def shell(command, timeout=None):
            for package, output in paths.items():
                if command == f"pm path {package}":
                    return SimpleNamespace(output=output, exit_code=0)
            return SimpleNamespace(output="", exit_code=0)
        p.d.shell.side_effect = shell
        out = io.StringIO()
        scope, _ = load_recipe(p, path, only="主题", out=out)
        return p, out.getvalue(), scope

    def test_installed_thememanager_is_launched_directly(self):
        for path in (ROOT / "recipes/xiaomi-24129PN74C/recipe.py",
                     ROOT / "recipes/xiaomi-24090RA29C/recipe.py"):
            with self.subTest(recipe=path.parent.name):
                p, _, scope = self.load(path, "", "package:/system/app/ThemeManager/ThemeManager.apk")
                self.assertEqual(scope["FAILED_STEPS"], [])
                p.d.shell.assert_any_call(f"pm path {THEME}")
                p.start.assert_called_once_with(THEME, DIRECT)

    def test_missing_thememanager_is_skipped_not_failed(self):
        for path in (ROOT / "recipes/xiaomi-24129PN74C/recipe.py",
                     ROOT / "recipes/redmi-24094RAD4C/recipe.py"):
            with self.subTest(recipe=path.parent.name):
                p, out, scope = self.load(path, "", "")
                self.assertIn(SKIP, out)
                self.assertEqual(scope["FAILED_STEPS"], [])
                p.d.shell.assert_any_call(f"pm path {THEME}")
                p.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
