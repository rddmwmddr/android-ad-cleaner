#!/usr/bin/env python3
"""鸿蒙版词库：从 Recipes.ets 现算，生成 harmony/docs/词库.md。

做法取自 android-ad-cleaner #681 和 #690：
- 词条挂 (家族, 分组) 和出处机型，不绑页面标签。
- 解析面要盖住所有写法。漏一种写法，那一组的词库就是空的，查漏也跟着失效，
  所以新增 Target 写法而这里没收录时，tests/test_harmony_vocab.py 会失败。
- 解不出来的调用记为「未解析」，列出来并冻结计数，不静默丢弃。
- 比较文字用 key_of（NFKC + 去空格），和引擎的 keyOf 同一个口径。
- 线索写在 harmony/docs/词条线索.md，手写，这里只链接不渲染。

用法：python3 gui/harmony_vocab.py        打印词库全文
      python3 gui/harmony_vocab.py write  写入 harmony/docs/词库.md
"""
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

HARMONY = Path(__file__).resolve().parents[1] / 'harmony'
RECIPES = HARMONY / 'entry/src/main/ets/engine/Recipes.ets'
VOCAB_DOC = HARMONY / 'docs/词库.md'
CLUES_DOC = HARMONY / 'docs/词条线索.md'

INVISIBLE = re.compile('[\u200b-\u200f\u202a-\u202e\u2060\ufeff]')

# 每种写法对应的词条类型。新增写法要在这里登记。
HELPERS = {
    'off': '关',
    'on': '开（保护类）',
    'offBelow': '关（开关在文字下方）',
    'offUnlessMuted': '关（通知已关时不用拨）',
    'choose': '单选',
}


def key_of(text):
    """比较用的键：去零宽字符 + NFKC + 去空格，和引擎的 keyOf 同一个口径。收录时仍照原文写。"""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', INVISIBLE.sub('', text)))


@dataclass
class Word:
    text: str
    kind: str
    helper: str
    path: list
    keep: list
    line: int
    radio: int = -1


@dataclass
class Group:
    family: str
    group: str
    segment_id: str
    name: str
    sources: list
    entry_kind: str
    entry_value: str
    entry_path: list
    entry_ability: str = ''
    words: list = field(default_factory=list)
    keeps: list = field(default_factory=list)


@dataclass
class Vocab:
    family: str
    groups: list
    unresolved: list


def _strip_comments(source):
    return re.sub(r'^\s*//.*$', lambda m: ' ' * len(m.group(0)), source, flags=re.M)


def _balanced(source, start):
    """source[start] 是开括号，返回匹配的闭括号位置。字符串里的括号不算。"""
    pairs = {'(': ')', '[': ']'}
    closing = pairs[source[start]]
    opening = source[start]
    depth = 0
    in_string = False
    at = start
    while at < len(source):
        char = source[at]
        if in_string:
            if char == '\\':
                at += 1
            elif char == "'":
                in_string = False
        elif char == "'":
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return at
        at += 1
    raise ValueError(f'括号不配对：{source[start:start + 40]}')


def _split_args(text):
    """按顶层逗号切参数。"""
    args, depth, in_string, current = [], 0, False, []
    at = 0
    while at < len(text):
        char = text[at]
        if in_string:
            current.append(char)
            if char == '\\':
                at += 1
                current.append(text[at])
            elif char == "'":
                in_string = False
        elif char == "'":
            in_string = True
            current.append(char)
        elif char in '([{':
            depth += 1
            current.append(char)
        elif char in ')]}':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
        at += 1
    tail = ''.join(current).strip()
    if tail:
        args.append(tail)
    return args


def _literal(text):
    match = re.fullmatch(r"'((?:[^'\\]|\\.)*)'", text.strip())
    return match.group(1) if match else None


def _literal_list(text):
    """解析 ['a', 'b']。解不出返回 None。"""
    text = text.strip()
    if not (text.startswith('[') and text.endswith(']')):
        return None
    out = []
    for arg in _split_args(text[1:-1]):
        value = _literal(arg)
        if value is None:
            return None
        out.append(value)
    return out


def _constants(source):
    """模块级字符串常量。"""
    return {m.group(1): m.group(2) for m in re.finditer(r"^(?:export )?const (\w+) = '([^']*)';", source, re.M)}


def _line_of(source, offset):
    return source.count('\n', 0, offset) + 1


def target_helpers(source):
    """文件里所有返回 Target 的函数名。"""
    return re.findall(r'^function (\w+)\([^)]*\): Target \{', source, re.M)


def helper_calls(source):
    """SEGMENTS 里每种写法出现的次数。"""
    body = source[source.index('export const SEGMENTS'):]
    return {name: len(re.findall(rf'\b{name}\(', body)) for name in target_helpers(source)}


def parse(source=None):
    source = _strip_comments(source if source is not None else RECIPES.read_text('utf-8'))
    constants = _constants(source)
    family = constants['FAMILY']
    start = source.index('export const SEGMENTS')
    groups, unresolved = [], []
    for match in re.finditer(r'new Segment\(', source[start:]):
        open_at = start + match.end() - 1
        close_at = _balanced(source, open_at)
        args = _split_args(source[open_at + 1:close_at])
        if len(args) != 6:
            unresolved.append(f'第 {_line_of(source, open_at)} 行：Segment 参数个数 {len(args)}')
            continue
        ident = [_literal(a) for a in args[:3]]
        if any(value is None for value in ident):
            unresolved.append(f'第 {_line_of(source, open_at)} 行：Segment 的 id/名称/分组不是字面量')
            continue
        segment_id, name, group = ident
        sources_arg = args[3].strip()
        if not (sources_arg.startswith('[') and sources_arg.endswith(']')):
            unresolved.append(f'第 {_line_of(source, open_at)} 行：出处机型不是列表')
            continue
        sources = [constants.get(a.strip(), a.strip()) for a in _split_args(sources_arg[1:-1])]
        entry = re.fullmatch(r'(\w+)\((.*)\)', args[4], re.S)
        if entry is None:
            unresolved.append(f'第 {_line_of(source, open_at)} 行：入口不是 名称(参数) 形式')
            continue
        entry_args = _split_args(entry.group(2))
        if not entry_args:
            unresolved.append(f'第 {_line_of(source, open_at)} 行：入口没有参数')
            continue
        entry_value = _literal(entry_args[0]) if entry.group(1) != 'home' else ''
        if entry.group(1) != 'home' and entry_value is None:
            unresolved.append(f'第 {_line_of(source, open_at)} 行：入口值不是字面量')
            continue
        entry_path = _literal_list(entry_args[-1])
        if entry_path is None:
            unresolved.append(f'第 {_line_of(source, open_at)} 行：入口路径不是字面量')
            continue
        ability = (_literal(entry_args[1]) or '') if entry.group(1) == 'app' and len(entry_args) > 1 else ''
        record = Group(family, group, segment_id, name, sources, entry.group(1), entry_value or '', entry_path, ability)
        groups.append(record)
        pages_text = source[source.index(args[5], open_at):]
        for page_match in re.finditer(r'new Page\(', pages_text[:len(args[5])]):
            page_open = page_match.end() - 1
            page_close = _balanced(pages_text, page_open)
            page_args = _split_args(pages_text[page_open + 1:page_close])
            path = _literal_list(page_args[0])
            keep = _literal_list(page_args[2]) if len(page_args) > 2 else None
            offset = source.index(args[5], open_at) + page_open
            if path is None or keep is None:
                unresolved.append(f'第 {_line_of(source, offset)} 行：页面路径或保留项不是字面量')
                continue
            record.keeps.extend((word, path) for word in keep)
            for call in _split_args(page_args[1].strip()[1:-1]):
                call_match = re.fullmatch(r'(\w+)\((.*)\)', call, re.S)
                helper = call_match.group(1) if call_match else ''
                if helper not in HELPERS:
                    unresolved.append(f'第 {_line_of(source, offset)} 行：不认识的写法 {call[:40]}')
                    continue
                call_args = _split_args(call_match.group(2))
                word = _literal(call_args[0])
                if word is None:
                    unresolved.append(f'第 {_line_of(source, offset)} 行：{helper} 的词不是字面量')
                    continue
                radio = int(call_args[1]) if helper == 'choose' else -1
                record.words.append(Word(word, HELPERS[helper], helper, path, keep, _line_of(source, offset), radio))
    return Vocab(family, groups, unresolved)


def render(vocab=None):
    vocab = vocab or parse()
    lines = [
        '# 鸿蒙词库',
        '',
        '> 生成物，不要手改。生成命令：`python3 gui/harmony_vocab.py write`',
        '',
        '从 `entry/src/main/ets/engine/Recipes.ets` 现算。每个词都在下面的出处机型上实测过。',
        '没实测的不在这里，记在 [词条线索](词条线索.md)。',
        '',
    ]
    for group in vocab.groups:
        lines += [f'## {vocab.family} / {group.group}（{group.name}）', '']
        lines += [f'出处：{"、".join(group.sources)}', '']
        where = {'uri': f'设置页 URI `{group.entry_value}`', 'home': '设置首页', 'app': f'App `{group.entry_value}`'}
        path = ' → '.join(group.entry_path)
        lines += [f'入口：{where[group.entry_kind]}' + (f' → {path}' if path else ''), '']
        lines += ['| 词条 | 操作 | 所在页 | 同页保留项 | Recipes 行 |', '|---|---|---|---|---|']
        for word in group.words:
            page = ' → '.join(word.path) or '入口页'
            keep = '、'.join(word.keep) or '无'
            lines.append(f'| {word.text} | {word.kind} | {page} | {keep} | {word.line} |')
        lines.append('')
    lines += [
        '## 反查',
        '',
        '反查只是索引，不构成跨页禁词表。保留项只约束它所在的那一页。',
        '',
        '| 词 | 分组 | 所在页 |',
        '|---|---|---|',
    ]
    rows = []
    for group in vocab.groups:
        for word in group.words:
            rows.append((key_of(word.text), word.text, group.group, ' → '.join(word.path) or '入口页'))
    for _, text, name, page in sorted(rows):
        lines.append(f'| {text} | {name} | {page} |')
    lines += ['', '## 未解析', '']
    lines += [f'- {item}' for item in vocab.unresolved] or ['无']
    return '\n'.join(lines) + '\n'


def main(argv):
    text = render()
    if argv[1:] == ['write']:
        VOCAB_DOC.write_text(text, 'utf-8')
        return 0
    if argv[1:]:
        print(__doc__, file=sys.stderr)
        return 1
    print(text, end='')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
