"""每份机型脚本都要把段内异常记进 FAILED_STEPS（#583）。

fast.py 的 run 分支只认这个名单决定退出码：段里抛了异常却没记名，CLI 与客户端的退出码
仍是 0，界面按成功处理。名单的语义与「未确认」「安全模式」的边界见 CONTEXT.md。

判据走 AST 而不是驱动脚本的 step：各脚本的 step 前置条件不同（有的先查 CHANGES 表，
有的先读机型 / 版本），拿同一个探针段名驱动会在前置条件上就炸，测不到记录那一步。
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def recipes():
    return sorted((ROOT / "recipes").glob("*/recipe*.py"))


def tree_of(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def declares_failed_steps(tree):
    """模块级把 FAILED_STEPS 绑成名字：append 到未定义的名字会 NameError。"""
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == "FAILED_STEPS" for t in targets):
            return True
    return False


def step_records_failed_steps(tree):
    """step 装饰器（含它返回的嵌套函数）里有 FAILED_STEPS.append(…)。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "step":
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "append"
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "FAILED_STEPS"):
                return True
    return False


class EveryRecipeRecordsFailedSteps(unittest.TestCase):
    def test_step_declares_the_list_and_appends_the_segment_name(self):
        for path in recipes():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                tree = tree_of(path)
                self.assertTrue(declares_failed_steps(tree), "模块级没有 FAILED_STEPS")
                self.assertTrue(step_records_failed_steps(tree), "step 的异常路径没有记录段名")


if __name__ == "__main__":
    unittest.main()
