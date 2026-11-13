"""tests/ 自身的两道守卫。

`CollectionTests`（rule:dev.tests.cases-live-under-tests）：`discover -s tests` 只收 tests/，
tests/ 之外的 .py 里出现 `def test_` 即红，逐文件列出命中数；隐藏目录与 node_modules /
build 不扫。

`AnchorTests`（rule:dev.tests.anchor-registry）：每个测试文件要么是已声明的锚点、要么是
机型脚本的专用测试。判据正文在 docs/agents/test-anchors.md。
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


def fake_root(tmp, *names, recipes=()):
    """临时根目录：tests/ 下放这些文件名，`recipes/<家族>/<型号>/recipe.py` 写进给定的正文。

    `recipes` 的键仍写 `<品牌>-<型号>`，这里按 `entries.FAMILY` 拆成家族/型号两层（#1261）。"""
    import entries
    root = Path(tmp)
    (root / "tests").mkdir()
    for name in names:
        (root / "tests" / name).write_text("", encoding="utf-8")
    for folder, body in recipes:
        brand, _, model = folder.partition("-")
        script = root / "recipes" / entries.FAMILY.get(brand.lower(), brand) / (model or folder) / "recipe.py"
        script.parent.mkdir(parents=True)
        script.write_text(body, encoding="utf-8")
    return root


class AnchorTests(unittest.TestCase):
    def violations(self, anchors, *names, recipes=()):
        """在一棵只有这些文件的临时树上求值；反例不必碰真实仓库。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_root(tmp, *names, recipes=recipes)
            return test_anchors.violations(root, anchors)

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
        found = self.violations({"test_row.py": "行定界"}, "test_row.py", "test_row_1234.py")
        self.assertTrue(found)
        self.assertIn("test_row_1234.py 没有登记锚点", "\n".join(found))
        self.assertIn("test_row.py", "\n".join(found))

    def test_an_anchor_without_its_file_is_reported(self):
        """清单里有的文件必须存在——双向一致真的双向。"""
        found = self.violations({"test_row.py": "行定界"})
        self.assertEqual(len(found), 1)
        self.assertIn("锚点 test_row.py 在文件树里不存在", found[0])

    def test_there_is_no_third_way_to_own_a_test_file(self):
        """合法的只有锚点与机型脚本测试两种来源：登记表里不许再有别的逃生口。"""
        self.assertFalse(hasattr(test_anchors, "PENDING"))
        self.assertFalse(hasattr(test_anchors, "PENDING_CAP"))

    def test_a_recipe_named_test_is_exempt(self):
        """机型脚本的专用测试不登记也不红：目录名的型号段与脚本里的市场名都算点名。"""
        found = self.violations(
            {}, "test_rmx3888_recipe.py", "test_k70_recipe.py", "test_honor_wkl_recipe.py",
            recipes=[("realme-RMX3888", "BUILD = ''\n"),
                     ("redmi-23113RKC6C", "# Redmi K70（23113RKC6C），HyperOS。\n"),
                     ("honor-WKL-AN20", "BUILD = ''\n")])
        self.assertEqual(found, [])

    def test_a_brand_level_test_is_exempt(self):
        found = self.violations({}, "test_honor_recipe.py",
                                recipes=[("honor-CLE-AN00", "BUILD = ''\n")])
        self.assertEqual(found, [])

    def test_a_brand_word_alone_does_not_buy_an_exemption(self):
        """名字里只有品牌（`vivo`）却没有点名任何一份脚本：仍要落到锚点。"""
        found = self.violations({}, "test_vivo_chan_page.py",
                                recipes=[("vivo-V1986A", "BUILD = 'Funtouch 13'\n")])
        self.assertEqual(len(found), 1)
        self.assertIn("test_vivo_chan_page.py 没有登记锚点", found[0])

    def test_a_plain_english_word_in_a_recipe_does_not_buy_an_exemption(self):
        """正文里出现过 `row` 不算点名：豁免只认型号形态（带数字的市场名或目录段）。"""
        found = self.violations({}, "test_row.py",
                                recipes=[("honor-CLE-AN00", "# 这一行 row 是普通单词\n")])
        self.assertEqual(len(found), 1)
        self.assertIn("test_row.py 没有登记锚点", found[0])

    def test_a_file_outside_the_test_pattern_is_not_examined(self):
        """共享资产（夹具、驱动器、js 用例）不是测试文件，不受锚点规则约束。"""
        self.assertEqual(self.violations({}, "fixtures.py", "compare_chan_pages.py"), [])


if __name__ == "__main__":
    unittest.main()
