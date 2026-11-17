"""tests/ 自身的四道守卫。

`CollectionTests`（rule:dev.tests.cases-live-under-tests）：`discover -s tests` 只收 tests/，
tests/ 之外的 .py 里出现 `def test_` 即红，逐文件列出命中数；隐藏目录与 node_modules /
build 不扫。

`AnchorTests`（rule:dev.tests.anchor-registry）：每个测试文件要么是已声明的锚点、要么是
机型脚本的专用测试。判据正文在 docs/agents/test-anchors.md。

`DomainTests`：七个按批次组织的回归文件里，每个测试类声明行为域 `DOMAIN`，且词表与
docs/agents/test-anchors.md 的「行为域」一节逐项对拍。

`DuplicationTests`：测试文件之间不许出现源码逐字节相同的 `def test_`，继承了基类的用例也不许
在文件里再写一份——共用的那份应该收进共享模块或基类，复制一份就多一个 owner。#1406
"""
import ast
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from devtools import test_anchors  # noqa: E402

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


def duplicate_cases(root):
    """测试文件之间逐字节相同的 `def test_`：[[(文件, 用例名), …], …]。

    同一文件里的副本不算：那份归文件自己管；跨文件才是「改一处漏一处」。"""
    seen = {}
    for path in sorted((root / "tests").glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            seen.setdefault(ast.get_source_segment(source, node), set()).add(
                (path.name, node.name))
    return sorted(sorted(owners) for owners in seen.values()
                  if len({file for file, _ in owners}) > 1)


def shadowed_cases(root):
    """继承了基类的用例、又在文件里写一份同名 `def test_`：[(文件, 类, 用例名), …]。

    基类里的用例只在 recipe_case.py 写一次；文件里再写一份会静默盖掉它，两份从此各走各的。"""
    base_cases = {}
    shared = root / "tests/recipe_case.py"
    if shared.exists():
        for node in ast.walk(ast.parse(shared.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                base_cases[node.name] = {
                    item.name for item in node.body
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test_")}
    found = []
    for path in sorted((root / "tests").glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ClassDef):
                continue
            inherited = set()
            for base in node.bases:
                if (isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name)
                        and base.value.id == "recipe_case"):
                    inherited |= base_cases.get(base.attr, set())
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in inherited:
                    found.append((path.name, node.name, item.name))
    return sorted(found)


class DuplicationTests(unittest.TestCase):
    def test_no_case_body_is_copied_between_device_tests(self):
        found = duplicate_cases(ROOT)
        detail = "\n".join(
            "、".join(f"{name}::{case}" for name, case in owners) + " 逐字节相同"
            for owners in found)
        self.assertEqual(found, [], detail +
                         "\n共用的那份收进共享模块或基类，或者只留一份")

    def test_a_copied_case_is_reported_with_both_files(self):
        body = "    def test_same(self):\n        self.assertTrue(True)\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            for name in ("test_a_recipe.py", "test_b_recipe.py"):
                (root / "tests" / name).write_text(f"class T:\n{body}", encoding="utf-8")
            self.assertEqual(duplicate_cases(root),
                             [[("test_a_recipe.py", "test_same"),
                               ("test_b_recipe.py", "test_same")]])

    def test_no_inherited_case_is_written_again_in_the_file(self):
        found = shadowed_cases(ROOT)
        self.assertEqual(found, [], "\n".join(
            f"{file}::{owner} 重写了继承来的 {case}" for file, owner, case in found) +
            "\n基类那份才是 owner，删掉文件里的副本")

    def test_a_case_shadowing_its_base_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests/recipe_case.py").write_text(
                "import unittest\n\nclass Base(unittest.TestCase):\n"
                "    def test_shared(self):\n        pass\n", encoding="utf-8")
            (root / "tests/test_a_recipe.py").write_text(
                "import recipe_case\n\nclass T(recipe_case.Base):\n"
                "    def test_shared(self):\n        pass\n", encoding="utf-8")
            self.assertEqual(shadowed_cases(root),
                             [("test_a_recipe.py", "T", "test_shared")])


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
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")
NO_CAP = "—"


def anchor_table(text):
    """`## 锚点登记` 表：{文件名: (why, 断言数上限)}；上限列写 `—` 表示不设预算。"""
    found, inside = {}, False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == TABLE_SECTION
            continue
        if not inside:
            continue
        match = ROW.match(line)
        if match:
            cap_text = match.group(3)
            try:
                cap = None if cap_text == NO_CAP else int(cap_text)
            except ValueError:
                raise ValueError(f"{match.group(1)} 的断言数上限 {cap_text!r} 不是整数："
                                 f"写数字，或写 {NO_CAP} 表示不设预算") from None
            found[match.group(1)] = (match.group(2), cap)
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
                         "锚点清单与文档登记表不一致：两处一起改（文件名、why 与断言数上限都逐字）")

    def test_a_ticket_named_file_is_reported_with_a_suggestion(self):
        """新开一个票号命名的文件即红，且文案指出它可能属于哪个锚点。"""
        found = self.violations({"test_row.py": ("行定界", None)}, "test_row.py", "test_row_1234.py")
        self.assertTrue(found)
        self.assertIn("test_row_1234.py 没有登记锚点", "\n".join(found))
        self.assertIn("test_row.py", "\n".join(found))

    def test_an_anchor_without_its_file_is_reported(self):
        """清单里有的文件必须存在——双向一致真的双向。"""
        found = self.violations({"test_row.py": ("行定界", None)})
        self.assertEqual(len(found), 1)
        self.assertIn("锚点 test_row.py 在文件树里不存在", found[0])

    def test_the_cap_column_is_parsed_or_read_as_unlimited(self):
        """第三列是断言数上限；写 `—` 表示不设预算，两种形态都要解析得出来。"""
        text = ("## 锚点登记\n\n| 文件 | 为什么 | 断言数上限 |\n|---|---|---:|\n"
                "| `test_a.py` | 守甲。 | 12 |\n| `test_b.py` | 守乙。 | — |\n")
        self.assertEqual(anchor_table(text),
                         {"test_a.py": ("守甲。", 12), "test_b.py": ("守乙。", None)})

    def test_an_over_budget_anchor_is_not_a_violation(self):
        """旧树也绿，守的是不回退：体量超限只是可见（软预算），不进 violations、不阻断合并。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_root(tmp, "test_row.py")
            (root / "tests/test_row.py").write_text(
                "class T:\n    def test_x(self):\n        self.assertTrue(1)\n", encoding="utf-8")
            self.assertEqual(test_anchors.violations(root, {"test_row.py": ("行定界", 0)}), [])

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


DOMAIN_SECTION = "## 行为域"
DOMAIN_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")


def domain_table(text):
    """`## 行为域` 表：{英文标识: 这个域在守什么}。中文名那一列只给人看，不进对拍。"""
    found, inside = {}, False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == DOMAIN_SECTION
            continue
        if not inside:
            continue
        match = DOMAIN_ROW.match(line)
        if match:
            found[match.group(1)] = match.group(3)
    return found


def domain_root(tmp, files, extra=None):
    """临时根目录：七个按批次组织的回归文件都在，正文按 files 给定。"""
    root = Path(tmp)
    (root / "tests").mkdir()
    for name in test_anchors.DOMAIN_FILES:
        (root / "tests" / name).write_text(files.get(name, ""), encoding="utf-8")
    for name, body in (extra or {}).items():
        (root / "tests" / name).write_text(body, encoding="utf-8")
    return root


def a_class(body):
    return f"import unittest\n\nclass T(unittest.TestCase):\n{body}"


class DomainTests(unittest.TestCase):
    def violations(self, files, extra=None):
        """在一棵只有七个回归文件（外加 extra）的临时树上求值；反例不必碰真实仓库。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = domain_root(tmp, files, extra)
            return test_anchors.domain_violations(root)

    def test_the_real_tree_has_no_domain_violation(self):
        self.assertEqual(test_anchors.domain_violations(ROOT), [],
                         "七个回归文件里有用例的类没落到词表内的行为域，或别的文件自造了域")

    def test_the_domain_table_matches_the_code(self):
        registered = domain_table(DOC.read_text(encoding="utf-8"))
        self.assertTrue(registered, "文档里的 `## 行为域` 表一条都没解析出来，这条对拍会空转")
        self.assertEqual(registered, test_anchors.DOMAINS,
                         "行为域词表与文档表不一致：标识、顺序与说明都要逐字同步")

    def test_a_class_without_a_domain_is_reported(self):
        """用例类不声明 DOMAIN 即红，文案点名文件与类。"""
        found = self.violations({test_anchors.DOMAIN_FILES[0]: a_class(
            "    def test_x(self):\n        pass\n")})
        self.assertTrue(found)
        self.assertIn("类 T 没有声明 DOMAIN", "\n".join(found))

    def test_a_domain_outside_the_vocabulary_is_reported(self):
        """声明一个词表外的域即红，文案给出可选词表。"""
        found = self.violations({test_anchors.DOMAIN_FILES[0]: a_class(
            '    DOMAIN = "explode"\n\n    def test_x(self):\n        pass\n')})
        self.assertTrue(found)
        self.assertIn('DOMAIN = \'explode\' 不在词表里', "\n".join(found))

    def test_a_module_level_test_in_a_domain_file_is_reported(self):
        """七个文件里模块层的 def test_ 不属于任何类，即红。"""
        found = self.violations({test_anchors.DOMAIN_FILES[0]: "def test_x():\n    pass\n"})
        self.assertTrue(found)
        self.assertIn("模块层的 def test_x 不属于任何类", "\n".join(found))

    def test_a_domain_outside_the_seven_files_is_reported(self):
        """别的测试文件不许自造行为域：域只属于七个按批次组织的回归文件。"""
        found = self.violations(
            {name: a_class('    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')
             for name in test_anchors.DOMAIN_FILES},
            extra={"test_row.py": a_class('    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')})
        self.assertTrue(found)
        self.assertIn("只有七个按批次组织的回归文件", "\n".join(found))

    def test_a_valid_class_passes(self):
        """正例：七个文件里每个类都声明词表内的域时零违规，守卫不是恒红。"""
        files = {name: a_class('    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')
                 for name in test_anchors.DOMAIN_FILES}
        self.assertEqual(self.violations(files), [])


if __name__ == "__main__":
    unittest.main()
