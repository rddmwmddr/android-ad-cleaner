"""词库守卫。运行：PYTHONPATH=tests python -m unittest tests.test_harmony_vocab"""
import re
import unittest
from pathlib import Path

HARMONY = Path(__file__).resolve().parents[1] / "harmony"

from gui import harmony_vocab as vocab

# 分组名和 android-ad-cleaner 的 tool/entries.py 对齐。列在这里的是旧仓库已有的。
UPSTREAM_GROUPS = {'系统广告', '跟踪管理', '下拉搜索', '负一屏', '浏览器', '应用市场'}
# 旧仓库没有对应分组、这边新起的。新增要在这里写明。
NEW_GROUPS = {'用户体验计划'}

# 每种写法各自冻结，避免一种写法的计数盖住另一种（#681 的教训）。
FROZEN_HELPER_CALLS = {'off': 9, 'on': 1, 'offBelow': 1, 'offUnlessMuted': 1, 'choose': 1}

CONSENT_WORDS = ('同意', '允许', '授权')


class VocabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = vocab.RECIPES.read_text('utf-8')
        cls.vocab = vocab.parse()

    def all_words(self):
        return [word for group in self.vocab.groups for word in group.words]

    def test_every_target_helper_is_known(self):
        """新增 Target 写法没进解析面时报错。否则这种写法的词会全部漏掉。"""
        self.assertEqual(set(vocab.target_helpers(self.source)), set(vocab.HELPERS))

    def test_helper_calls_frozen(self):
        self.assertEqual(vocab.helper_calls(self.source), FROZEN_HELPER_CALLS)

    def test_parsed_words_match_helper_calls(self):
        """解析出的词数必须等于调用数，有漏就对不上。"""
        self.assertEqual(len(self.all_words()), sum(FROZEN_HELPER_CALLS.values()))

    def test_nothing_unresolved(self):
        self.assertEqual(self.vocab.unresolved, [])

    def test_no_group_is_empty(self):
        for group in self.vocab.groups:
            self.assertTrue(group.words, f'{group.group} 没有词条')

    def test_every_word_has_source(self):
        for group in self.vocab.groups:
            self.assertTrue(group.sources, f'{group.group} 没有出处机型')
            for source in group.sources:
                self.assertRegex(source, r'^[A-Z0-9-]+ \d+\.\d+\.\d+\.\d+$')
            for word in group.words:
                self.assertGreater(word.line, 0)

    def test_groups_align_with_upstream(self):
        names = {group.group for group in self.vocab.groups}
        self.assertEqual(names - UPSTREAM_GROUPS, NEW_GROUPS)

    def test_keep_is_page_level_and_never_targeted(self):
        """同一页不能既要关又要保留。不同页同名不算冲突。"""
        for word in self.all_words():
            keys = {vocab.key_of(item) for item in word.keep}
            self.assertNotIn(vocab.key_of(word.text), keys, word.text)

    def test_no_duplicate_on_same_page(self):
        seen = set()
        for group in self.vocab.groups:
            for word in group.words:
                key = (group.group, tuple(word.path), vocab.key_of(word.text))
                self.assertNotIn(key, seen, word.text)
                seen.add(key)

    def test_never_targets_consent_words(self):
        """清单里不能出现替机主同意的词。"""
        for group in self.vocab.groups:
            for word in group.words:
                for bad in CONSENT_WORDS:
                    self.assertNotIn(bad, word.text)
            for step in group.entry_path:
                for bad in CONSENT_WORDS:
                    self.assertNotIn(bad, step)

    def test_engine_confirm_words_exclude_consent(self):
        engine = (vocab.RECIPES.parent / 'Phone.ets').read_text('utf-8')
        words = re.search(r"const CONFIRM_WORDS: string\[\] = \[(.*?)\];", engine, re.S).group(1)
        for bad in CONSENT_WORDS:
            self.assertNotIn(bad, words)

    def test_never_opens_system_update(self):
        """系统更新不碰。设置首页的默认右栏就是更新页，只能点左栏。"""
        for group in self.vocab.groups:
            self.assertNotIn('update', group.entry_value.replace('system_and_updates', ''))
            for step in group.entry_path + [s for w in group.words for s in w.path]:
                self.assertNotIn('更新', step)

    def test_key_of_matches_engine(self):
        self.assertEqual(vocab.key_of('USB 调试'), vocab.key_of('USB调试'))
        self.assertEqual(vocab.key_of('ＷｉＦｉ 连接'), 'WiFi连接')
        engine = (vocab.RECIPES.parent / 'Screen.ets').read_text('utf-8')
        self.assertIn("normalize('NFKC')", engine)

    def test_document_in_sync(self):
        self.assertEqual(vocab.VOCAB_DOC.read_text('utf-8'), vocab.render(self.vocab),
                         '跑一次 python3 gui/harmony_vocab.py write')

    def test_reverse_index_rows_all_have_page(self):
        text = vocab.render(self.vocab)
        section = text[text.index('## 反查'):text.index('## 未解析')]
        rows = [line for line in section.splitlines() if line.startswith('| ') and '---' not in line][1:]
        self.assertEqual(len(rows), len(self.all_words()))
        for row in rows:
            cells = [cell.strip() for cell in row.strip('|').split('|')]
            self.assertTrue(all(cells), row)


class CluesTest(unittest.TestCase):
    def test_every_clue_has_four_fields_and_no_duplicates(self):
        text = vocab.CLUES_DOC.read_text('utf-8')
        self.assertIn('线索不是词条，未经真机核实', text)
        blocks = re.split(r'^### ', text, flags=re.M)[1:]
        self.assertTrue(blocks)
        pairs = []
        for block in blocks:
            title = block.splitlines()[0]
            fields = {m.group(1): m.group(2).strip() for m in re.finditer(r'^- (来源|日期|摘录|涉及)：(.*)$', block, re.M)}
            self.assertEqual(set(fields), {'来源', '日期', '摘录', '涉及'}, title)
            self.assertTrue(all(fields.values()), title)
            self.assertTrue(fields['来源'].startswith('https://'), title)
            self.assertRegex(fields['日期'], r'^\d{4}-\d{2}-\d{2}$')
            pairs.append((fields['来源'], title))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_clues_are_not_in_recipes(self):
        """线索不能直接进清单：系统应用没实测过，Recipes 里不该有它们的包名。"""
        source = vocab.RECIPES.read_text('utf-8')
        for bundle in ('himovie', 'hmsapp.music', 'thememanager', 'totemweather', 'gamecenter', 'hmsapp.books'):
            self.assertNotIn(bundle, source)


class ParserSurfaceTest(unittest.TestCase):
    """解析器要能发现自己解不出的写法，不能静默丢弃。"""

    SAMPLE = """
export const FAMILY = '鸿蒙';
const M = 'HOP-AL10 7.0.0.111';
export const SEGMENTS: Segment[] = [
  new Segment('a', '甲', '系统广告', [M],
    uri('x', ['入口']),
    [new Page([], [%s], ['留'])]),
];
"""

    def test_literal_is_parsed(self):
        parsed = vocab.parse(self.SAMPLE % "off('词')")
        self.assertEqual([w.text for w in parsed.groups[0].words], ['词'])
        self.assertEqual(parsed.unresolved, [])

    def test_variable_argument_is_reported(self):
        parsed = vocab.parse(self.SAMPLE % 'off(NAME)')
        self.assertEqual(parsed.groups[0].words, [])
        self.assertEqual(len(parsed.unresolved), 1)
        self.assertIn('不是字面量', parsed.unresolved[0])

    def test_unknown_helper_is_reported(self):
        parsed = vocab.parse(self.SAMPLE % "closeNamed('词')")
        self.assertEqual(parsed.groups[0].words, [])
        self.assertEqual(len(parsed.unresolved), 1)
        self.assertIn('不认识的写法', parsed.unresolved[0])

    def test_nonliteral_segment_identity_is_reported(self):
        """Segment 的 id/name 不是字面量时要报出来，不能静默变成 None。"""
        parsed = vocab.parse(self.SAMPLE % "off('词')")
        self.assertEqual([g.segment_id for g in parsed.groups], ['a'])
        source = self.SAMPLE.replace("new Segment('a', '甲'", "new Segment(ID, NAME")
        broken = vocab.parse(source % "off('词')")
        self.assertEqual(broken.groups, [])
        self.assertTrue(broken.unresolved)

    def test_empty_entry_arguments_are_reported(self):
        """entry() 没有参数时不能抛 IndexError，要记为未解析。"""
        source = self.SAMPLE.replace("uri('x', ['入口'])", "uri()")
        parsed = vocab.parse(source % "off('词')")
        self.assertEqual(parsed.groups, [])
        self.assertTrue(parsed.unresolved)


if __name__ == '__main__':
    unittest.main()
