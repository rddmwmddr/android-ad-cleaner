"""tests/ 自身的两道守卫。

`CollectionTests`（rule:dev.tests.cases-live-under-tests）：`discover -s tests` 只收 tests/，
tests/ 之外的 .py 里出现 `def test_` 即红，逐文件列出命中数；隐藏目录与 node_modules /
build 不扫。

`AnchorTests`（rule:dev.tests.anchor-registry）：每个测试文件要么是已声明的锚点、要么在
待归并名单里、要么是机型脚本的专用测试。判据正文在 docs/agents/test-anchors.md。
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import test_anchors  # noqa: E402

# 隐藏目录（.git / .venv / .private / .worktrees …）一律不扫，剩下这两个是可见的
SKIP_DIRS = {"node_modules", "build"}
DEF_TEST = re.compile(r"^[ \t]*def test_", re.M)


def offenders_in(root):
    """{相对路径: 命中数}：root/tests 之外定义用例的文件。"""
    found = {}
    tests = root / "tests"
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(files):
            path = Path(folder, name)
            if not name.endswith(".py") or tests in path.parents:
                continue
            hits = DEF_TEST.findall(path.read_text(encoding="utf-8"))
            if hits:
                found[path.relative_to(root).as_posix()] = len(hits)
    return found


class CollectionTests(unittest.TestCase):
    def test_no_test_functions_outside_the_tests_folder(self):
        self.assertEqual(offenders_in(ROOT), {}, "用例只在 tests/ 下定义，别的目录里的 def test_ 收集不到")

    def test_a_stray_test_function_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests/test_ok.py").write_text(
                "class T:\n    def test_ok(self):\n        pass\n", encoding="utf-8")
            (root / "recipes").mkdir()
            (root / "recipes/test_stray.py").write_text(
                "class T:\n    def test_stray(self):\n        pass\n", encoding="utf-8")
            self.assertEqual(offenders_in(root), {"recipes/test_stray.py": 1})


DOC = ROOT / "docs/agents/test-anchors.md"
TABLE_SECTION = "## 锚点登记"
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$")


def anchor_table(text):
    """`## 锚点登记` 表：{文件名: why}。这一节是锚点清单在文档里的登记处。"""
    found, inside = {}, False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == TABLE_SECTION
            continue
        if not inside:
            continue
        match = ROW.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def tree(tmp, *names, recipes=()):
    """临时根目录：tests/ 下放这些文件名，recipes/<folder>/recipe.py 写进给定的正文。"""
    root = Path(tmp)
    (root / "tests").mkdir()
    for name in names:
        (root / "tests" / name).write_text("", encoding="utf-8")
    for folder, body in recipes:
        script = root / "recipes" / folder / "recipe.py"
        script.parent.mkdir(parents=True)
        script.write_text(body, encoding="utf-8")
    return root


def messages(found):
    return "\n".join(found)


class AnchorTests(unittest.TestCase):
    def test_the_real_tree_has_no_violation(self):
        self.assertEqual(test_anchors.violations(ROOT), [],
                         "有测试文件没落到锚点，或者登记与文件树对不上")

    def test_the_anchor_table_matches_the_code(self):
        registered = anchor_table(DOC.read_text(encoding="utf-8"))
        self.assertTrue(registered, "文档里的 `## 锚点登记` 表一条都没解析出来，这条对拍会空转")
        self.assertEqual(registered, test_anchors.ANCHORS,
                         "锚点清单与文档登记表不一致：两处一起改（文件名与 why 都逐字）")

    def test_a_ticket_named_file_is_reported_with_a_suggestion(self):
        """新开一个票号命名的文件即红，且文案指出它可能属于哪个锚点。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "test_row.py", "test_row_1234.py")
            found = test_anchors.violations(root, {"test_row.py": "行定界"}, {})
        self.assertTrue(found)
        self.assertIn("test_row_1234.py 没有登记锚点", messages(found))
        self.assertIn("test_row.py", messages(found))

    def test_an_anchor_without_its_file_is_reported(self):
        """清单里有的文件必须存在——双向一致真的双向。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            found = test_anchors.violations(root, {"test_row.py": "行定界"}, {})
        self.assertEqual(len(found), 1)
        self.assertIn("锚点 test_row.py 在文件树里不存在", found[0])

    def test_a_pending_entry_without_its_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp)
            found = test_anchors.violations(root, {}, {"test_row_1234.py": "test_row.py"})
        self.assertIn("已经并掉", messages(found))

    def test_a_pending_target_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "test_row_1234.py")
            found = test_anchors.violations(root, {}, {"test_row_1234.py": "test_row.py"})
        self.assertEqual(len(found), 1)
        self.assertIn("归并目标 test_row.py 不存在", found[0])

    def test_one_more_pending_entry_breaks_the_frozen_cap(self):
        """名单只能缩不能长：多一条就超过冻结上限。"""
        anchors = {"test_row.py": "行定界"}
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "test_row.py", "test_a_1.py", "test_b_2.py")
            pending = {"test_a_1.py": "test_row.py", "test_b_2.py": "test_row.py"}
            ok = test_anchors.violations(root, anchors, pending, cap=2)
            over = test_anchors.violations(root, anchors, pending, cap=1)
        self.assertEqual(ok, [])
        self.assertIn("超过冻结上限", messages(over))

    def test_the_same_file_cannot_be_anchor_and_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "test_row.py")
            found = test_anchors.violations(
                root, {"test_row.py": "行定界"}, {"test_row.py": "test_row.py"})
        self.assertIn("既登记为锚点又在待归并名单里", messages(found))

    def test_a_recipe_named_test_is_exempt(self):
        """机型脚本的专用测试不登记也不红：目录名的型号段与脚本里的市场名都算点名。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "test_rmx3888_recipe.py", "test_k70_recipe.py",
                        recipes=[("realme-RMX3888", "BUILD = ''\n"),
                                 ("redmi-23113RKC6C", "# Redmi K70（23113RKC6C），HyperOS。\n")])
            found = test_anchors.violations(root, {}, {})
        self.assertEqual(found, [])

    def test_a_brand_level_test_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "test_honor_recipe.py",
                        recipes=[("honor-CLE-AN00", "BUILD = ''\n")])
            found = test_anchors.violations(root, {}, {})
        self.assertEqual(found, [])

    def test_a_plain_english_word_in_a_recipe_does_not_buy_an_exemption(self):
        """正文里出现过 `row` 不算点名：豁免只认型号形态（带数字的市场名或目录段）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "test_row.py",
                        recipes=[("honor-CLE-AN00", "# 这一行 row 是普通单词\n")])
            found = test_anchors.violations(root, {}, {})
        self.assertEqual(len(found), 1)
        self.assertIn("test_row.py 没有登记锚点", found[0])

    def test_a_file_outside_the_test_pattern_is_not_examined(self):
        """共享资产（夹具、驱动器、js 用例）不是测试文件，不受锚点规则约束。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = tree(tmp, "fixtures.py", "compare_api.py")
            found = test_anchors.violations(root, {}, {})
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
