"""安全模式下的整页关闭段落：整段跳过并说明原因，不记失败（#909）。

整页关闭的段落（逐 App 的广告跟踪列表、应用建议卡片、文件夹底部的更多推荐）在安全模式下
一个开关都点不到：`off()` 按设计只关脚本点名的开关。段落随后回读「必须全关」就必然把这一段
记成语义错误的失败，而它其实什么都没做。现在这类段落在安全模式下一律按「跳过」结束，
非安全模式下的行为与改前一致。
"""
import ast
import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import fast
from fixtures import load_recipe, phone_mock

# 整段只做整页关闭的段：安全模式下必须走跳过出口
PAGE_WIDE = [
    ("recipes/oppo-PKT110/recipe.py", "广告跟踪"),
    ("recipes/oppo-PKT110/recipe.py", "应用建议"),
    ("recipes/oppo-PLP120/recipe.py", "广告跟踪"),
    ("recipes/oneplus-PLR110/recipe.py", "广告跟踪"),
    ("recipes/oneplus-PHK110/recipe.py", "广告跟踪"),
    ("recipes/oneplus-PKX110/recipe.py", "广告跟踪"),
    ("recipes/oppo-PKH110/recipe.py", "广告跟踪"),
    ("recipes/realme-RMX3700/recipe.py", "广告跟踪"),
    ("recipes/realme-RMX3700/recipe.py", "应用建议"),
    ("recipes/honor-PNM-AN10/recipe.py", "广告跟踪"),
    ("recipes/honor-PNM-AN10/recipe.py", "桌面文件夹"),
    ("recipes/honor-PNM-AN10/recipe.py", "主题"),
]

# 这几份脚本自带 `guard()`：安全模式下它们在段入口就先按「型号 / 版本不同」跳过，
# 走不到整页关闭那一段，跳过原因不是本票这一句。
GUARDED = {
    "recipes/oneplus-PHK110/recipe.py",
    "recipes/oneplus-PKX110/recipe.py",
    "recipes/oppo-PKH110/recipe.py",
    "recipes/realme-RMX3700/recipe.py",
}


def load(phone, path, only):
    scope, out = load_recipe(phone, ROOT / path, only)
    return scope, out.getvalue()


def touchless():
    """安全模式下这一段本该一步都不做：所有动作都留在 Mock 上，可以逐个查。"""
    p = phone_mock()
    p.safe_mode = True
    p.locked.return_value = False
    return p


class SafeModeSkipTests(unittest.TestCase):
    def test_every_page_wide_step_skips_in_safe_mode(self):
        for path, name in PAGE_WIDE:
            with self.subTest(recipe=path, step=name):
                p = touchless()
                scope, printed = load(p, path, [name])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(scope["SKIPPED_STEPS"], [name])
                if path not in GUARDED:
                    self.assertIn("安全模式不做整页全关", printed)
                p.off.assert_not_called()

    def test_the_run_still_exits_zero(self):
        """跳过台账不参与退出码：这一段没做成，但也没出错。"""
        p = touchless()
        scope, _ = load(p, "recipes/oppo-PKT110/recipe.py", ["广告跟踪"])
        self.assertEqual(fast.report_run(scope, p), 0)

    def test_untitled_switches_are_left_alone_in_safe_mode(self):
        """vivo 的「个性化推荐」页只有无标题开关：自己按坐标点的那条路同样不进安全模式（#909）。

        它不是 `p.off(page=…)`，所以不受引擎那条限制；段落里还关着点名开关，不能整段跳过。"""
        for path in ("recipes/vivo-V2303A/recipe.py",
                     "recipes/vivo-V2547DA/recipe_android17.py"):
            with self.subTest(recipe=path):
                p = touchless()
                p.switches.return_value = [("", True, (1, 2))]
                scope, _ = load(p, path, only=None)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(scope["off_unnamed"]("商店·个性化推荐"), 0)
                self.assertIn("安全模式不做整页全关", out.getvalue())
                p.click.assert_not_called()

    def test_nothing_on_the_page_is_touched_before_the_skip(self):
        """跳过发生在进页之前：不拉起 App、不点入口、不读开关。"""
        p = touchless()
        load(p, "recipes/oppo-PKT110/recipe.py", ["广告跟踪"])
        p.start.assert_not_called()
        p.d.shell.assert_not_called()
        p.switches.assert_not_called()


class AdTrackingTests(unittest.TestCase):
    """PKT110 的广告跟踪 / 应用建议：安全模式下不再「先声明不关、再判没关掉」。"""

    def make(self):
        state = [("示例应用", True, (1, 2))]
        p = phone_mock()
        p.locked.return_value = False
        p.switches.side_effect = lambda *a, **k: list(state)
        p.scroll_more.return_value = False

        def off(only=None, keep=(), page="", max_screens=40, **kw):
            state[:] = [(t, False, xy) for t, _, xy in state]

        p.off.side_effect = off
        return p, state

    def test_ad_tracking_reports_a_skip_instead_of_a_failure_in_safe_mode(self):
        p, state = self.make()
        p.safe_mode = True
        p.locked.return_value = False
        scope, printed = load(p, "recipes/oppo-PKT110/recipe.py", ["广告跟踪"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], ["广告跟踪"])
        self.assertIn("安全模式不做整页全关", printed)
        p.off.assert_not_called()
        self.assertTrue(state[0][1], "安全模式下不该点开关")

    def test_ad_tracking_still_closes_the_page_without_safe_mode(self):
        """旧树也绿，守的是不回退：跳过出口在非安全模式下必须是惰性的。"""
        p, state = self.make()
        scope, _ = load(p, "recipes/oppo-PKT110/recipe.py", ["广告跟踪"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertEqual(state[0][1], False)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_app_suggestions_reports_a_skip_instead_of_a_failure_in_safe_mode(self):
        p, state = self.make()
        p.safe_mode = True
        p.locked.return_value = False
        scope, printed = load(p, "recipes/oppo-PKT110/recipe.py", ["应用建议"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(scope["SKIPPED_STEPS"], ["应用建议"])
        self.assertIn("安全模式不做整页全关", printed)
        self.assertTrue(state[0][1])

    def test_app_suggestions_still_closes_the_page_without_safe_mode(self):
        """旧树也绿，守的是不回退：跳过出口在非安全模式下必须是惰性的。"""
        p, state = self.make()
        scope, _ = load(p, "recipes/oppo-PKT110/recipe.py", ["应用建议"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(state[0][1], False)


def whole_page_steps(source):
    """段名 → 是否「整段只做整页关闭」。

    整页关闭 = 不带 `only` 的 `p.off(...)`。段体直接调它、或经脚本自己的助手调它都算；
    段里只要还出现带 `only` 的 `p.off`（点名的开关），这一段就不整段都是整页关闭。
    """
    tree = ast.parse(source)
    # 段函数全都叫 `_`，认人只能按节点本身，不能按函数名
    calls, wide, narrow = {}, set(), set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        here = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "off"
                    and isinstance(fn.value, ast.Name) and fn.value.id == "p"):
                if any(kw.arg == "only" for kw in sub.keywords):
                    narrow.add(node)
                else:
                    wide.add(node)
            elif isinstance(fn, ast.Name):
                here.add(fn.id)
        calls[node] = here
    for target in (wide, narrow):
        names = {node.name for node in target}
        growing = True
        while growing:
            growing = False
            for node, here in calls.items():
                if node not in target and here & names:
                    target.add(node)
                    names.add(node.name)
                    growing = True
    steps = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.decorator_list:
            continue
        first = node.decorator_list[0]
        if not (isinstance(first, ast.Call) and isinstance(first.func, ast.Name)
                and first.func.id == "step"):
            continue
        name = first.args[0].value if first.args else node.name
        steps[name] = (node in wide and node not in narrow, node)
    return steps


def first_call_name(node):
    body = node.body[1:] if ast.get_docstring(node) is not None else node.body
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
        fn = first.value.func
        return fn.id if isinstance(fn, ast.Name) else None
    return None


class GuardTests(unittest.TestCase):
    def test_the_detector_follows_calls_into_local_helpers(self):
        """判据自己要立得住：段体经助手间接整页关闭也算，混着点名开关的不算。"""
        indirect = '''
@step("整页关闭")
def _():
    close_page("页")

def close_page(page):
    p.off(page=page)
'''
        mixed = '''
@step("混着")
def _():
    p.off(only=["甲"], page="页")
    p.off(page="页")
'''
        self.assertTrue(whole_page_steps(indirect)["整页关闭"][0])
        self.assertFalse(whole_page_steps(mixed)["混着"][0])

    def test_page_wide_segments_start_with_the_safe_mode_exit(self):
        """整页关闭的段落要把跳过出口写在第一句：写在后面等于先翻页、再判没关掉。"""
        checked = []
        for path in sorted((ROOT / "recipes").rglob("recipe*.py")):
            steps = whole_page_steps(path.read_text(encoding="utf-8"))
            for name, (is_wide, node) in steps.items():
                if not is_wide:
                    continue
                checked.append((str(path), name))
                self.assertEqual(first_call_name(node), "skip_in_safe_mode",
                                 f"{path} 的「{name}」整页关闭，安全模式下要整段跳过")
        self.assertTrue(checked, "一个整页关闭的段都没认出来：判据本身坏了")
        self.assertEqual(sorted(checked), sorted((str(ROOT / p), n) for p, n in PAGE_WIDE),
                         "整页关闭的段变了：行为用例的名单要一起更新")


if __name__ == "__main__":
    unittest.main()
