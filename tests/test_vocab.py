"""品牌词库（tool/vocab.py，#681）：词条都有出处、键和入口速查相同、解析不出的不静默丢弃、保留项只在页面上。"""
import ast
import re
import sys
import tempfile
import textwrap
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import entries  # noqa: E402
import vocab  # noqa: E402

RECIPES = str(ROOT / "recipes")
CLUES = ROOT / "docs" / "清单" / "词条线索.md"

# 解析不出的 only=，按脚本冻结。新脚本多了这种写法，先看能不能写成字面量或模块级常量，确实不能再改这里。
UNRESOLVED_ONLY = {
    "honor-WKL-AN20/recipe.py": 1,
    "oneplus-PHK110/recipe.py": 1,
    "oneplus-PJA110/recipe.py": 1,
    "oneplus-PKX110/recipe.py": 1,
    "oppo-PKH110/recipe.py": 1,
    "oppo-PKT110/recipe.py": 1,
    "oppo-PLG110/recipe.py": 3,
    "oppo-PLP120/recipe.py": 1,
    "oppo-PMA110/recipe.py": 2,
    "oppo-PMX110/recipe.py": 1,
    "redmi-23049RAD8C/recipe.py": 1,
    "redmi-23113RKC6C/recipe.py": 1,
    "redmi-23117RK66C/recipe.py": 1,
    "redmi-24122RKC7C/recipe.py": 1,
    "redmi-25060RK16C/recipe.py": 1,
    "vivo-V2303A/recipe.py": 1,
    "vivo-V2417A/recipe.py": 1,
    "vivo-V2547DA/recipe_android17.py": 4,
    "xiaomi-2304FPN6DC/recipe.py": 1,
    "xiaomi-24090RA29C/recipe.py": 1,
    "xiaomi-2410CRP4CC/recipe.py": 1,
    "xiaomi-24129PN74C/recipe.py": 1,
    "xiaomi-24129PN74C/recipe_os4.py": 2,
    "xiaomi-25102RKBEC/recipe.py": 1,
    "xiaomi-2512BPNDAC/recipe.py": 1,
    "xiaomi-M154FF/recipe.py": 1,
}
# 页面标签归不到分组的 p.off()。多出来的先看能不能加进 vocab.PAGES。
UNCLASSIFIED = {
    ("honor", "<title>"): 1,
    ("oppo", "<page>"): 8,
    ("oppo", "<title>"): 1,
    ("vivo", "<page>"): 1,
    ("xiaomi", "<page>"): 4,
}


def recipes(**files):
    """{"xiaomi-A1": 源码} → 临时 recipes 目录。"""
    tmp = tempfile.TemporaryDirectory()
    for name, src in files.items():
        folder = Path(tmp.name, name)
        folder.mkdir()
        folder.joinpath("recipe.py").write_text(textwrap.dedent(src), encoding="utf-8")
    return tmp


class RealRecipesTest(unittest.TestCase):
    """票里定的六条，对着真实脚本。"""

    @classmethod
    def setUpClass(cls):
        cls.scan = vocab.scan(RECIPES)

    def test_every_word_points_at_the_recipe_line_it_came_from(self):
        self.assertGreater(len(self.scan.words), 500)
        cache = {}
        for word in self.scan.words:
            lines = cache.setdefault(word.script, (ROOT / "recipes" / word.script).read_text(encoding="utf-8").splitlines())
            self.assertIn(word.text, lines[word.line - 1], word.source)

    def test_keys_match_the_entry_table(self):
        self.assertEqual(set(vocab.keys()), {(f, g) for f, groups in entries.ENTRIES.items() for g in groups})
        for (family, prefix), group in {**vocab.PAGES, **vocab.FALLBACK}.items():
            self.assertIn(group, entries.ENTRIES[family], f"{family} {prefix}")
        placed = {(w.family, w.group) for w in self.scan.words if w.group}
        self.assertLessEqual(placed, set(vocab.keys()))

    def test_every_key_has_a_section_in_the_doc(self):
        doc = vocab.render(RECIPES)
        for family, groups in entries.ENTRIES.items():
            section = doc.split(f"## {entries.LABEL[family]}（", 1)[1].split("\n## ", 1)[0]
            for group in groups:
                self.assertIn(f"### {group}\n", section, f"{family} {group}")

    def test_unresolved_only_is_frozen_per_script(self):
        self.assertEqual(dict(Counter(c.script for c in self.scan.unresolved_only)), UNRESOLVED_ONLY)

    def test_unresolved_only_is_listed_by_name_in_the_doc(self):
        doc = vocab.render(RECIPES)
        for call in self.scan.unresolved_only:
            self.assertIn(f"`{call.script}:{call.line}` {call.text}", doc)

    def test_unclassified_labels_are_frozen_and_listed(self):
        self.assertEqual(dict(Counter((c.family, c.text) for c in self.scan.unclassified)), UNCLASSIFIED)
        doc = vocab.render(RECIPES)
        for call in self.scan.unclassified:
            self.assertIn(f"`{call.script}:{call.line}`", doc)

    def test_doc_is_in_sync(self):
        doc = (ROOT / "docs" / "清单" / "词库.md").read_text(encoding="utf-8")
        self.assertEqual(doc, vocab.render(RECIPES), "机型脚本变了：跑 python3 tool/vocab.py > docs/清单/词库.md")

    def test_reverse_table_never_has_a_row_without_a_page(self):
        doc = vocab.render(RECIPES)
        table = doc.split("## 反查表", 1)[1]
        self.assertIn("反查只是索引，不构成跨页禁词表", table)
        rows = [r for r in table.splitlines() if r.startswith("| ") and not r.startswith("| 词 ")]
        self.assertGreater(len(rows), 100)
        for row in rows:
            page = row.split(" | ")[3]
            self.assertTrue(vocab.has_page(page), row)


class CluesTest(unittest.TestCase):
    def rows(self):
        return [[c.strip() for c in line.strip("| \n").split(" | ")]
                for line in CLUES.read_text(encoding="utf-8").splitlines()
                if line.startswith("| http")]

    def test_clue_file_says_what_it_is(self):
        text = CLUES.read_text(encoding="utf-8")
        self.assertIn("线索不是词条，未经真机核实", text)
        self.assertIn("| 链接 | 日期 | 原文摘录 | 家族 / 分组 |", text)

    def test_every_clue_has_four_fields(self):
        rows = self.rows()
        self.assertTrue(rows)
        labels = {label: family for family, label in entries.LABEL.items()}
        for row in rows:
            self.assertEqual(len(row), 4, row)
            link, date, quote, place = row
            self.assertRegex(link, r"^https://github\.com/rddmwmddr/android-ad-cleaner/(issues|pull)/\d+$")
            self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(quote, row)
            label, _, group = place.partition(" / ")
            self.assertIn(group, entries.ENTRIES[labels[label]], row)

    def test_no_clue_is_cited_twice(self):
        cited = [(row[0], row[2]) for row in self.rows()]
        self.assertEqual(len(cited), len(set(cited)))

    def test_clues_carry_no_contact_or_serial(self):
        text = CLUES.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"[\w.]+@[\w.]+")
        self.assertNotRegex(text, r"\b[A-Z0-9]{14,}\b")

    def test_the_generator_links_clues_but_does_not_render_them(self):
        doc = vocab.render(RECIPES)
        self.assertIn("(词条线索.md)", doc)
        self.assertNotIn("github.com/rddmwmddr", doc)


class ParseTest(unittest.TestCase):
    def scan(self, src, folder="xiaomi-A1"):
        tmp = recipes(**{folder: src})
        self.addCleanup(tmp.cleanup)
        return vocab.scan(tmp.name)

    def test_literal_only_and_keep(self):
        found = self.scan('p.off(only=["广告", "推荐"], keep=["应用更新"], page="商店·设置")')
        self.assertEqual([(w.text, w.kind) for w in found.words],
                         [("广告", vocab.OFF), ("推荐", vocab.OFF), ("应用更新", vocab.KEEP)])
        self.assertEqual({w.group for w in found.words}, {"应用商店"})
        self.assertEqual({w.page for w in found.words}, {"商店·设置"})

    def test_module_level_list_constant(self):
        found = self.scan('''
            HOT = ["热搜", "资讯"]
            def f():
                p.off(only=HOT, page="搜索·首页")
        ''')
        self.assertEqual([w.text for w in found.words], ["热搜", "资讯"])
        self.assertEqual(found.unresolved_only, [])

    def test_source_line_is_where_the_word_is_written(self):
        found = self.scan('''
            HOT = [
                "热搜",
            ]
            p.off(only=HOT, page="搜索·首页")
        ''')
        self.assertEqual(found.words[0].line, 3)
        self.assertEqual(found.words[0].source, "xiaomi-A1:3")

    def test_loop_variables_and_computed_lists_are_unresolved(self):
        found = self.scan('''
            for only in (["a"], ["b"]):
                p.off(only=only, page="搜索·首页")
            p.off(only=list(targets), page="搜索·首页")
            p.off(only=names, page="搜索·首页")
        ''')
        self.assertEqual(found.words, [])
        self.assertEqual([c.text for c in found.unresolved_only], ["only", "list(targets)", "names"])

    def test_reassigned_constant_is_not_trusted(self):
        found = self.scan('''
            HOT = ["旧词"]
            HOT = helper()
            p.off(only=HOT, page="搜索·首页")
        ''')
        self.assertEqual(found.words, [])
        self.assertEqual([c.text for c in found.unresolved_only], ["HOT"])

    def test_extended_constant_is_not_trusted(self):
        found = self.scan('''
            HOT = ["旧词"]
            HOT += more
            p.off(only=HOT, page="搜索·首页")
        ''')
        self.assertEqual(found.words, [])

    def test_off_without_only_has_no_words_and_is_counted(self):
        found = self.scan('p.off(page="搜索·首页")')
        self.assertEqual(found.words, [])
        self.assertEqual(found.unresolved_only, [])
        self.assertEqual(found.whole_page, 1)

    def test_only_p_off_is_read(self):
        found = self.scan('close_named(["词"], "搜索·首页")\nother.off(only=["别的"], page="搜索·首页")')
        self.assertEqual(found.words, [])

    def test_unknown_label_goes_to_unclassified(self):
        found = self.scan('p.off(only=["词"], page="没见过·这页")')
        self.assertIsNone(found.words[0].group)
        self.assertEqual([c.text for c in found.unclassified], ["没见过·这页"])

    def test_placeholder_prefix_uses_the_fallback(self):
        found = self.scan('p.off(only=["词"], page=f"{pkg}·用户体验计划")')
        self.assertEqual(found.words[0].group, "天气和日历")
        self.assertEqual(found.words[0].page, "{pkg}·用户体验计划")

    def test_sub_brand_uses_the_family(self):
        found = self.scan('p.off(only=["词"], page="商店·设置")', folder="redmi-B2")
        self.assertEqual(found.words[0].family, "xiaomi")
        self.assertEqual(found.words[0].model, "B2")

    def test_page_variable_is_not_a_page(self):
        found = self.scan('p.off(only=["词"], page=page)')
        self.assertEqual(found.words[0].page, "<page>")
        self.assertEqual(vocab.reverse_rows(found.words), [])


class RenderTest(unittest.TestCase):
    def render(self, **files):
        tmp = recipes(**files)
        self.addCleanup(tmp.cleanup)
        return vocab.render(tmp.name)

    def group(self, doc, heading):
        return doc.split(f"### {heading}\n", 1)[1].split("\n###", 1)[0].split("\n## ", 1)[0]

    def test_keep_is_listed_under_its_page_not_across_pages(self):
        # 小米「推送消息」只在商店通知设置页是父开关：词库不能写成「这个品牌不能关」
        doc = self.render(**{"xiaomi-A1": 'p.off(only=["营销"], keep=["推送消息"], page="商店·通知设置")'})
        section = self.group(doc, "应用商店")
        self.assertIn("**同页保留项**", section)
        self.assertIn("- 商店·通知设置 · 推送消息：`xiaomi-A1:1`", section)

    def test_same_word_on_two_pages_gets_two_reverse_rows(self):
        doc = self.render(**{"xiaomi-A1": 'p.off(only=["广告"], page="商店·甲")\np.off(keep=["广告"], only=["x"], page="商店·乙")'})
        table = doc.split("## 反查表", 1)[1]
        self.assertIn("| 广告 | 小米 | 应用商店 | 商店·甲 | 要关 |", table)
        self.assertIn("| 广告 | 小米 | 应用商店 | 商店·乙 | 同页保留 |", table)

    def test_spacing_variants_are_one_word_written_as_found(self):
        doc = self.render(**{"xiaomi-A1": 'p.off(only=["WiFi 连接"], page="商店·甲")',
                             "xiaomi-B2": 'p.off(only=["WiFi连接"], page="商店·甲")'})
        line = next(l for l in self.group(doc, "应用商店").splitlines() if "WiFi" in l)
        self.assertIn("WiFi 连接 / WiFi连接", line)
        self.assertIn("xiaomi-A1:1", line)
        self.assertIn("xiaomi-B2:1", line)

    def test_empty_group_still_has_a_section(self):
        doc = self.render(**{"xiaomi-A1": 'p.off(only=["广告"], page="商店·甲")'})
        self.assertIn("暂无词条", self.group(doc, "负一屏"))

    def test_non_default_file_is_named_in_the_source(self):
        tmp = recipes(**{"vivo-V1": 'p.off(only=["广告"], page="商店·甲")'})
        self.addCleanup(tmp.cleanup)
        Path(tmp.name, "vivo-V1", "recipe_android17.py").write_text('p.off(only=["推荐"], page="商店·甲")', encoding="utf-8")
        doc = vocab.render(tmp.name)
        self.assertIn("`vivo-V1/recipe_android17.py:1`", doc)
        self.assertIn("`vivo-V1:1`", doc)

    def test_html_like_labels_are_in_code_so_markdown_keeps_them(self):
        doc = self.render(**{"xiaomi-A1": 'p.off(only=names, page=title)'})
        self.assertIn("`<title>`", doc)


class SpeedupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = recipes(**{
            "xiaomi-A1": 'p.start("com.android.settings", ".ad.AdServiceSettings")',
            "xiaomi-B2": 'p.start("com.android.settings")',
            "vivo-V1": 'p.start("com.vivo.x")',
        })
        self.addCleanup(self.tmp.cleanup)

    def test_lists_models_of_the_family_without_the_direct(self):
        found = [(f, g, m) for f, g, m, d in entries.speedups(self.tmp.name) if d.activity == ".ad.AdServiceSettings"]
        self.assertEqual(found, [("xiaomi", "系统广告", ["B2"])])

    def test_direct_nobody_used_is_not_a_hint(self):
        self.assertTrue(all(d.activity == ".ad.AdServiceSettings" for _f, _g, _m, d in entries.speedups(self.tmp.name)))

    def test_doc_says_it_is_not_a_defect(self):
        doc = entries.markdown(self.tmp.name)
        hints = doc.split("## 可提速提示", 1)[1]
        self.assertIn("脚本未走这条直达 ≠ 缺陷", hints)
        self.assertIn("- 小米 / 系统广告 / B2 / `com.android.settings/.ad.AdServiceSettings`", hints)


class SourceShapeTest(unittest.TestCase):
    def test_vocab_does_not_keep_a_brand_table_of_its_own(self):
        src = (ROOT / "tool" / "vocab.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        assigned = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        self.assertFalse(assigned & {"FAMILY", "LABEL", "ENTRIES"})
        self.assertFalse(re.search(r"^(BRANDS?|KEEP_WORDS|NEVER)\s*=", src, re.M))


if __name__ == "__main__":
    unittest.main()
