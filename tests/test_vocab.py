"""品牌词库（tool/vocab.py，#681）：词条都有出处、键和入口速查相同、解析不出的不静默丢弃、保留项只在页面上。"""
import ast
import re
import subprocess
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
    "honor-CLE-AN00/recipe.py": 1,
    "oneplus-PHK110/recipe.py": 1,
    "oneplus-PKX110/recipe.py": 1,
    "oppo-PKH110/recipe.py": 1,
    "oppo-PLG110/recipe.py": 2,
    "oppo-PLP120/recipe.py": 1,
    "oppo-PMA110/recipe.py": 1,
    "redmi-23049RAD8C/recipe.py": 1,
    "redmi-25060RK16C/recipe.py": 1,
    "vivo-V2303A/recipe.py": 1,
    "vivo-V2547DA/recipe_android17.py": 4,
    "xiaomi-2304FPN6DC/recipe.py": 1,
    "xiaomi-24090RA29C/recipe.py": 1,
    "xiaomi-2410CRP4CC/recipe.py": 1,
    "xiaomi-24129PN74C/recipe_os4.py": 2,
    "xiaomi-25102RKBEC/recipe.py": 1,
    "xiaomi-2512BPNDAC/recipe.py": 1,
    "xiaomi-M154FF/recipe.py": 1,
    "xiaomi-M332BF/recipe.py": 1,
}
# close_named() 第一个参数解析不出的，和上面分开冻结，免得一个口径盖住另一个。
UNRESOLVED_CLOSE = {
    "oppo-PKT110/recipe.py": 3,
    "oppo-PMX110/recipe.py": 2,
    "redmi-23117RK66C/recipe.py": 1,
    "vivo-V2417A/recipe.py": 1,
}
# 解析不出的 keep=，同样按脚本冻结：它只影响同页保留项，读不出时那页的约束就整段丢了。
UNRESOLVED_KEEP = {
    "oneplus-PHK110/recipe.py": 1,
    "oneplus-PKX110/recipe.py": 1,
    "oppo-PKH110/recipe.py": 1,
    "oppo-PLG110/recipe.py": 2,
    "oppo-PMA110/recipe.py": 1,
    "oppo-PMX110/recipe.py": 1,
    "vivo-V2417A/recipe.py": 1,
}
# 模块级字典里的说明文字，按脚本冻结。
DICT_NOTES = {
    "honor-WKL-AN20/recipe.py": 37,
}
# 一条词条都读不出来的脚本（判据就是零词条）：开关点名散在自建函数里（vivo-V2547A 的 off()、
# oneplus-PHK110 的 off_exact()、samsung-SM-N9760 的 protect()），或者名单运行时才算。
SILENT = (
    "oneplus-PHK110/recipe.py",
    "oneplus-PHK110/recipe_android15.py",
    "samsung-SM-N9760/recipe.py",
    "vivo-V2547A/recipe.py",
)
# 页面标签归不到分组的调用。多出来的先看能不能加进 vocab.PAGES。
UNCLASSIFIED = {
    ("oppo", "<page>"): 7,
    ("oppo", "个性化管理"): 2,
    ("oppo", "隐私"): 2,
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

    def test_doc_sections_cover_every_entry_key(self):
        """旧树也绿，守的是词库文档不会少一节或多一节：从标题反解出来的键集必须与 entries.ENTRIES 相等。"""
        label_of = {label: family for family, label in entries.LABEL.items()}
        found, family = set(), None
        for line in vocab.render(RECIPES).splitlines():
            if line.startswith("## "):
                family = label_of.get(line[3:].split("（", 1)[0])
            elif line.startswith("### ") and family:
                found.add((family, line[4:]))
        self.assertEqual(found, {(f, g) for f, groups in entries.ENTRIES.items() for g in groups})

    def test_page_mapping_points_at_real_groups(self):
        """旧树也绿，守的是 PAGES / FALLBACK 不指到 entries 里不存在的分组。"""
        for (family, prefix), group in {**vocab.PAGES, **vocab.FALLBACK}.items():
            self.assertIn(group, entries.ENTRIES[family], f"{family} {prefix}")
        placed = {(w.family, w.group) for w in self.scan.words if w.group}
        self.assertLessEqual(placed, {(f, g) for f, groups in entries.ENTRIES.items() for g in groups})

    def test_unresolved_only_is_frozen_per_script(self):
        self.assertEqual(dict(Counter(c.script for c in self.scan.unresolved_only)), UNRESOLVED_ONLY)

    def test_unresolved_close_named_is_frozen_per_script(self):
        self.assertEqual(dict(Counter(c.script for c in self.scan.unresolved_close)), UNRESOLVED_CLOSE)

    def test_unresolved_keep_is_frozen_per_script(self):
        """守卫用例，旧树也绿：守的是这 8 处 keep= 不回退，不被静默读成别的词、也不被悄悄丢掉。"""
        self.assertEqual(dict(Counter(c.script for c in self.scan.unresolved_keep)), UNRESOLVED_KEEP)
        doc = vocab.render(RECIPES)
        for call in self.scan.unresolved_keep:
            self.assertIn(f"`{call.script}:{call.line}` keep= {call.text}", doc)

    def test_dict_notes_are_frozen_per_script(self):
        self.assertEqual(dict(Counter(n.script for n in self.scan.notes)), DICT_NOTES)

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

    def test_reverse_table_never_has_a_row_without_a_real_page(self):
        """只看行里的实际页面：模板页（含 `{…}`）和 `<变量>` 都不许出现，不能用同一个 has_page 自证。"""
        doc = vocab.render(RECIPES)
        table = doc.split("## 反查表", 1)[1]
        self.assertIn("反查只是索引，不构成跨页禁词表", table)
        rows = [r for r in table.splitlines() if r.startswith("| ") and not r.startswith("| 词 ")]
        self.assertGreater(len(rows), 100)
        for row in rows:
            page = row.split(" | ")[3]
            self.assertNotIn("{", page, row)
            self.assertFalse(page.startswith("<"), row)

    def test_unclassified_real_labels_do_get_reverse_rows(self):
        """旧树也绿，守的是这 4 行不被「未归类」措辞改动顺手带掉。"""
        doc = vocab.render(RECIPES)
        table = doc.split("## 反查表", 1)[1]
        self.assertIn("| 个性化推荐 | OPPO | 未归类 | 隐私 | 要关 |", table)
        self.assertNotIn("<page>", table)

    def test_unclassified_section_says_which_ones_reach_the_table(self):
        section = vocab.render(RECIPES).split("## 未归类", 1)[1].split("\n## ", 1)[0]
        self.assertIn("真实标签", section)
        self.assertIn("进反查表", section)

    def test_protection_note_points_at_the_engine_list(self):
        """保护类前缀只认极性模块那一份词表，不在文档里另抄（抄漏过「减少」）。"""
        note = next(line for line in vocab.render(RECIPES).splitlines() if "保护类开关" in line)
        self.assertIn("polarity.NEG_PREFIX", note)
        self.assertNotIn("减少", note)

    def test_protection_switch_gets_its_own_direction(self):
        """引擎会打开保护类开关，词库不能跟着 p.off() 一律标「要关」（#693）。"""
        tmp = recipes(**{"xiaomi-A1": 'p.off(only=["个性化广告推荐", "减少广告"], page="商店·设置")'})
        self.addCleanup(tmp.cleanup)
        self.assertEqual([(w.text, w.kind) for w in vocab.scan(tmp.name).words],
                         [("个性化广告推荐", vocab.OFF), ("减少广告", vocab.OPEN)])
        self.assertIn("| 减少广告 | 小米 | 应用商店 | 商店·设置 | 要开 |", vocab.render(tmp.name))

    def test_named_but_ignored_row_is_marked_as_such(self):
        """引擎对 want_state 为 None 的行直接跳过，词库不能把死名字标成「要关」（#693）。"""
        tmp = recipes(**{"xiaomi-A1": 'p.off(only=["广告", "减少动画"], page="商店·设置")'})
        self.addCleanup(tmp.cleanup)
        self.assertEqual([(w.text, w.kind) for w in vocab.scan(tmp.name).words],
                         [("广告", vocab.OFF), ("减少动画", vocab.NOOP)])
        self.assertIn("| 减少动画 | 小米 | 应用商店 | 商店·设置 | 不碰 |", vocab.render(tmp.name))

    def test_scripts_without_any_word_are_named(self):
        """整份脚本一条词条都读不出来时，文档必须点名，不能让人以为这台机没有词。"""
        self.assertEqual(tuple(self.scan.silent), SILENT)
        section = vocab.render(RECIPES).split("## 读不到的脚本", 1)[1].split("\n## ", 1)[0]
        for script in SILENT:
            self.assertIn(f"`{script}`", section)


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


class CloseNamedTest(unittest.TestCase):
    """#681：荣耀 WKL-AN20 的词全在 close_named() 里，只读 p.off() 荣耀家族几乎是空的。"""

    def scan(self, src, folder="honor-A1"):
        tmp = recipes(**{folder: src})
        self.addCleanup(tmp.cleanup)
        return vocab.scan(tmp.name)

    def test_first_argument_and_label_are_read(self):
        found = self.scan('close_named(["朋友页显示推荐动态"], "音乐·消息和隐私设置", package, "消息和隐私设置")')
        self.assertEqual([(w.text, w.kind, w.group, w.page) for w in found.words],
                         [("朋友页显示推荐动态", vocab.OFF, "音乐", "音乐·消息和隐私设置")])

    def test_module_constant_is_read(self):
        found = self.scan('NAMES = ["甲"]\nclose_named(NAMES, "音乐·页")')
        self.assertEqual([w.text for w in found.words], ["甲"])

    def test_dict_value_with_a_literal_key_is_read(self):
        found = self.scan('T = {"a": ["甲", "乙"]}\nclose_named(T["a"], "音乐·页")\np.off(only=T["a"], page="音乐·页")')
        self.assertEqual([w.text for w in found.words], ["甲", "乙", "甲", "乙"])

    def test_dict_value_with_a_variable_key_is_unresolved(self):
        found = self.scan('T = {"a": ["甲"]}\nclose_named(T[k], "音乐·页")')
        self.assertEqual(found.words, [])
        self.assertEqual([c.text for c in found.unresolved_close], ["T[k]"])

    def test_local_names_are_unresolved_on_their_own_list(self):
        found = self.scan('close_named(names, "音乐·页")\np.off(only=names, page="音乐·页")')
        self.assertEqual([c.text for c in found.unresolved_close], ["names"])
        self.assertEqual([c.text for c in found.unresolved_only], ["names"])

    def test_none_means_the_whole_page(self):
        found = self.scan('close_named(None, "音乐·页")')
        self.assertEqual(found.words, [])
        self.assertEqual(found.unresolved_close, [])
        self.assertEqual(found.whole_page, 1)

    def test_off_inside_the_helper_is_not_counted_twice(self):
        found = self.scan('''
            def close_named(names, title):
                p.off(only=sorted(names), page=title)
            close_named(["甲"], "音乐·页")
        ''')
        self.assertEqual([w.text for w in found.words], ["甲"])
        self.assertEqual(found.unresolved_only, [])
        self.assertEqual(found.unclassified, [])

    def test_unknown_label_is_unclassified(self):
        found = self.scan('close_named(["甲"], "没见过·页")')
        self.assertEqual([(c.text, c.words) for c in found.unclassified], [("没见过·页", ("甲",))])

    def test_prose_in_a_dict_is_a_note_not_a_word(self):
        found = self.scan('CHANGES = {"音乐": "朋友页显示推荐动态、个性化广告推荐", "浏览器首页": "模式选择 → 简洁首页"}')
        self.assertEqual(found.words, [])
        self.assertEqual([n.text for n in found.notes], ["朋友页显示推荐动态", "个性化广告推荐", "模式选择 → 简洁首页"])

    def test_dict_without_chinese_is_ignored(self):
        self.assertEqual(self.scan('START_ACTIVITIES = {"com.a": ".Main"}').notes, [])


class RealHonorTest(unittest.TestCase):
    def test_the_words_that_caught_a_real_miss_are_in_the_vocabulary(self):
        # 真实发生过：CLE-AN00 的音乐段漏了这两个，是拿 WKL-AN20 的 close_named 词对照发现的
        words = [w for w in vocab.scan(RECIPES).words if w.script.startswith("honor-WKL-AN20/")]
        self.assertIn(("音乐", "展示“摇一摇”类开屏广告"), {(w.group, w.text) for w in words})
        self.assertIn(("音乐", "个性化广告推荐"), {(w.group, w.text) for w in words})

    def test_reduce_ads_is_marked_open_in_the_real_vocabulary(self):
        """#693：这条方向相反，词库要跟引擎说的一致。"""
        self.assertIn("| 减少广告 | 荣耀 | 音乐 | 音乐·广告推荐 | 要开 |", vocab.render(RECIPES))


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

    def test_off_on_something_else_is_not_read(self):
        found = self.scan('other.off(only=["别的"], page="搜索·首页")\nfast_close(["也不读"], "搜索·首页")')
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

    def test_polarity_word_lists_are_defined_in_one_module(self):
        """极性词表只定义一处（#693）：别的 tool/ 模块只能取用或转发，不能各留副本。"""
        owners = {}
        for path in ROOT.glob("tool/*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id in ("NEG_PREFIX", "AD_WORDS", "TRACK_WORDS"):
                            owners.setdefault(target.id, []).append(path.name)
        self.assertEqual(owners, {name: ["polarity.py"] for name in ("NEG_PREFIX", "AD_WORDS", "TRACK_WORDS")})

    def test_importing_vocab_does_not_pull_the_device_stack(self):
        """生成器要能单独跑：极性判据从 polarity 取，不经过 fast（那条链会连带 adbutils）。

        旧树也绿（vocab 本来只 import entries），守的是不回退：以后有人图省事改成 `import fast`
        就会把 adbutils 拉进文档生成器（#693）。"""
        code = ("import sys; sys.path.insert(0, 'tool'); import vocab; "
                "print(sorted(m for m in ('adbutils', 'uiautomator2') if m in sys.modules))")
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
