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
import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_the_unregistered_message_pins_its_wording(self):
        """未登记锚点的整句是 CI 报红时唯一的指引：两处文档与上限这一句都要逐字。"""
        found = self.violations({"test_row.py": ("行定界", None)}, "test_row.py", "test_row_1234.py")
        self.assertEqual(found, [
            "test_row_1234.py 没有登记锚点。新增用例要落进已声明的锚点（相近的：test_row.py）；"
            "确实要新开一个的话，在 ANCHORS 与 docs/agents/test-anchors.md 里同时登记，"
            "写一句 why 与断言数上限"])

    def test_a_missing_tests_dir_is_not_a_crash(self):
        """没有 `tests/` 时 present 为空、原样给结论，不要在列文件时崩掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(test_anchors.violations(Path(tmp), {}), [])

    def test_an_exempt_file_does_not_stop_the_scan(self):
        """机型测试豁免之后，排在它后面的普通文件仍要被报出来（`continue` 不是 `break`）。"""
        found = self.violations(
            {}, "test_k70_recipe.py", "test_plain.py",
            recipes=[("redmi-23113RKC6C", "# Redmi K70（23113RKC6C），HyperOS。\n")])
        self.assertEqual(len(found), 1)
        self.assertIn("test_plain.py 没有登记锚点", found[0])


class AnchorTokenTests(unittest.TestCase):
    """`recipe_tokens` / `base_of` / `recipe_owned` / `suggest`：文件名与脚本正文怎么归成豁免判据。"""

    def test_a_tree_without_recipes_has_empty_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            self.assertEqual(test_anchors.recipe_tokens(root), (frozenset(), frozenset(), ""))

    def test_tokens_cover_recipe_toml_and_extra_py_sources(self):
        """三处来源都要读：`recipe*.py`、`*.toml`、同目录其余 `*.py`，归一化后按读入顺序拼接。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            folder = root / "recipes" / "demo" / "model"
            folder.mkdir(parents=True)
            (folder / "recipe.py").write_text("ABC", encoding="utf-8")
            (folder / "page.toml").write_text("DEF", encoding="utf-8")
            (folder / "notes.py").write_text("GHI", encoding="utf-8")
            _, models, text = test_anchors.recipe_tokens(root)
            self.assertEqual(models, {"model"})
            self.assertEqual(text, "abcdefghi")

    def test_sources_are_read_as_utf8_with_replacement(self):
        """脚本正文按 utf-8 读、坏字节替换：与日志同一口径，非 UTF-8 注释不能把锚点发现打崩。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "recipes" / "demo" / "model"
            folder.mkdir(parents=True)
            (folder / "recipe.py").write_bytes(b"AB\xff")
            real = Path.read_text
            seen = {}

            def spy(path_self, *args, **kwargs):
                seen.update(kwargs)
                return real(path_self, *args, **kwargs)

            with mock.patch.object(Path, "read_text", spy):
                test_anchors.recipe_tokens(root)
            self.assertEqual(seen, {"encoding": "utf-8", "errors": "replace"})

    def test_base_of_strips_prefix_suffix_and_ticket_tail(self):
        self.assertEqual(test_anchors.base_of("fixtures.py"), "fixturespy")
        self.assertEqual(test_anchors.base_of("test_x_1234.py"), "x")

    def test_a_name_shorter_than_three_chars_cannot_own_a_recipe(self):
        self.assertFalse(test_anchors.recipe_owned("test_ab.py", set(), set(), ""))

    def test_a_model_contained_in_the_name_counts(self):
        """名字比型号长、型号仅是它的子串：任一方向的包含都算点名，`and` 会漏掉这一档。"""
        self.assertTrue(test_anchors.recipe_owned("test_xoppox.py", set(), {"oppo"}, ""))

    def test_a_three_digit_run_shared_with_a_model_counts(self):
        """三位以上数字串是型号的一部分即算点名，`not in` 会把这一档反过来。"""
        self.assertTrue(test_anchors.recipe_owned("test_abc110def.py", set(), {"phk110"}, ""))

    def test_suggest_lists_two_candidates_from_a_dissimilar_anchor_set(self):
        """候选上限是 2、相似度门槛是 0：差得远的名字也要给出两个最近项。"""
        self.assertEqual(
            len(test_anchors.suggest("test_xyz.py", {"foo.py", "bar.py", "baz.py"}).split("、")), 2)

    def test_suggest_says_so_when_the_anchor_list_is_empty(self):
        self.assertEqual(test_anchors.suggest("test_x.py", {}), "锚点清单里没有相近的名字")

    def test_suggest_joins_candidates_with_the_full_separator(self):
        self.assertEqual(test_anchors.suggest("test_row.py", {"test_row.py", "test_row2.py"}),
                         "test_row.py、test_row2.py")


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

    def test_the_vocabulary_can_be_injected(self):
        """词表是参数：注入一个不含 `startup` 的词表，声明 `startup` 的类就该被判出词表。"""
        first = test_anchors.DOMAIN_FILES[0]
        files = {name: a_class('    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')
                 for name in test_anchors.DOMAIN_FILES[1:]}
        files[first] = a_class('    DOMAIN = "startup"\n\n    def test_x(self):\n        pass\n')
        with tempfile.TemporaryDirectory() as tmp:
            found = test_anchors.domain_violations(domain_root(tmp, files), {"channel"})
        self.assertEqual(len(found), 1)
        self.assertIn("不在词表里", found[0])

    def test_a_missing_tests_dir_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(test_anchors.domain_violations(Path(tmp)),
                             ["tests/ 目录不存在；行为域守卫没有可检查的对象"])

    def test_every_missing_domain_file_is_reported(self):
        """七个文件缺了几个就报几条，第一条之后不停止扫描。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            self.assertEqual(test_anchors.domain_violations(root), [
                f"{name} 不存在；七个按批次组织的回归文件缺一，行为域守卫会空转"
                for name in test_anchors.DOMAIN_FILES])

    def test_domain_files_are_read_as_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 额外一份非域文件，让「别的文件自造域」那段遍历也走到 read_text。
            root = domain_root(tmp, {}, {"test_row.py": ""})
            real = Path.read_text
            seen = []

            def spy(path_self, *args, **kwargs):
                seen.append(kwargs)
                return real(path_self, *args, **kwargs)

            with mock.patch.object(Path, "read_text", spy):
                test_anchors.domain_violations(root)
            self.assertTrue(seen)
            self.assertTrue(all(kwargs == {"encoding": "utf-8"} for kwargs in seen))

    def test_the_module_level_message_pins_its_wording(self):
        name = test_anchors.DOMAIN_FILES[0]
        found = self.violations({name: "def test_x():\n    pass\n"})
        self.assertEqual(found, [
            f"{name}: 模块层的 def test_x 不属于任何类；"
            "挪进一个测试类，并让该类声明 DOMAIN"])

    def test_each_class_without_a_domain_is_reported(self):
        """没有用例的类跳过之后、两个缺 DOMAIN 的类仍各报一条，整句逐字。"""
        name = test_anchors.DOMAIN_FILES[0]
        source = ("import unittest\n\n"
                  "class Empty(unittest.TestCase):\n    pass\n\n"
                  "class A(unittest.TestCase):\n    def test_a(self):\n        pass\n\n"
                  "class B(unittest.TestCase):\n    def test_b(self):\n        pass\n")
        found = self.violations({name: source})
        self.assertEqual(found, [
            f"{name}: 类 {cls} 没有声明 DOMAIN；在类里加一行 "
            "DOMAIN = \"<域名>\"，词表见 docs/agents/test-anchors.md 的「行为域」"
            for cls in ("A", "B")])

    def test_a_non_constant_domain_falls_out_of_the_vocabulary(self):
        found = self.violations({test_anchors.DOMAIN_FILES[0]: a_class(
            "    DOMAIN = SOME\n\n    def test_x(self):\n        pass\n")})
        self.assertEqual(len(found), 1)
        self.assertIn("不在词表里", found[0])

    def test_the_unknown_domain_message_lists_the_vocabulary(self):
        found = self.violations({test_anchors.DOMAIN_FILES[0]: a_class(
            '    DOMAIN = "explode"\n\n    def test_x(self):\n        pass\n')})
        self.assertEqual(found, [
            f"{test_anchors.DOMAIN_FILES[0]}: 类 T 的 DOMAIN = 'explode' 不在词表里；"
            f"从 {', '.join(test_anchors.DOMAINS)} 里选一个"])

    def test_a_non_test_file_declaring_a_domain_is_not_examined(self):
        """只有 `test_*.py` 会被查自造域：`tests/` 下的共享资产不归这条规则管。"""
        files = {name: a_class('    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')
                 for name in test_anchors.DOMAIN_FILES}
        with tempfile.TemporaryDirectory() as tmp:
            found = test_anchors.domain_violations(
                domain_root(tmp, files, {"helper.py": a_class(
                    '    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')}))
        self.assertEqual(found, [])

    def test_the_self_made_domain_message_pins_its_wording(self):
        files = {name: a_class('    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')
                 for name in test_anchors.DOMAIN_FILES}
        with tempfile.TemporaryDirectory() as tmp:
            found = test_anchors.domain_violations(
                domain_root(tmp, files, {"test_row.py": a_class(
                    '    DOMAIN = "channel"\n\n    def test_x(self):\n        pass\n')}))
        self.assertEqual(found, [
            "test_row.py: 类 T 声明了 DOMAIN，但只有七个按批次组织的回归文件"
            "按行为域归属；新文件落进已有的锚点，不要自造域"])


class AnchorMainTests(unittest.TestCase):
    """`test_anchors.main` 的进程内调用点：退出码与两路输出（mutmut 只认进程内命中，#1519）。"""

    def expected_root(self):
        """`main` 从 `__file__` 的上一级取仓库根：这里独立算一遍，改错层级会被下面的断言抓到。"""
        return Path(test_anchors.__file__).resolve().parents[1]

    def call(self, argv=()):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = test_anchors.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_clean_exit_says_how_many_anchors_and_domains(self):
        with mock.patch.object(test_anchors, "violations", return_value=[]), \
                mock.patch.object(test_anchors, "domain_violations", return_value=[]):
            code, out, err = self.call()
        self.assertEqual(code, 0)
        self.assertEqual(out, f"{len(test_anchors.ANCHORS)} 个锚点、"
                              f"{len(test_anchors.DOMAINS)} 个行为域，全部合规。\n")
        self.assertEqual(err, "")

    def test_violations_are_printed_with_a_count_on_stderr(self):
        expected = self.expected_root()

        def violations(root):
            self.assertEqual(root, expected, "main 该把仓库根原样交给 violations")
            return ["甲", "乙"]

        def domain_violations(root):
            self.assertEqual(root, expected, "main 该把仓库根原样交给 domain_violations")
            return ["丙"]

        with mock.patch.object(test_anchors, "violations", violations), \
                mock.patch.object(test_anchors, "domain_violations", domain_violations):
            code, out, err = self.call()
        self.assertEqual(code, 1)
        self.assertEqual(out, "甲\n乙\n丙\n")
        self.assertEqual(err, "3 处违规。\n")

    def test_arguments_are_rejected(self):
        # 两个参数：报错把收到的参数原样列出来，改分隔符就该红。
        code, out, err = self.call(["x", "y"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err, "不认识的参数 x y；这个脚本没有参数\n")


if __name__ == "__main__":
    unittest.main()
