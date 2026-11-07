#!/usr/bin/env python3
"""品牌词库：从机型脚本现算每个 (家族, 分组) 下的词条和同页保留项，写新机型脚本时先查这里。术语见 CONTEXT.md。

键和 entries.py 同一个。入口怎么进看入口速查，这里只装它没有的那层：开关词条、同页保留项、出处。
机型脚本是唯一来源，不手写词；社区线索在手写的 docs/清单/词条线索.md，要变成词条必须先实测并落进机型脚本。

只解析 `p.off()` 的 only= / keep=，只认字面量列表和模块级列表常量。循环变量、运行时算的记为未解析，
逐条列名，不静默丢弃。同页保留项只在那一页、那一次 off() 里成立，这里不产出跨页的禁词表。

  python3 tool/vocab.py > docs/清单/词库.md
"""
import ast
import glob
import os
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entries import ENTRIES, FAMILY, LABEL

# (家族, 页面标签前缀) → 分组。前缀是 page= 里「·」前面那段，是脚本内部写法，只在这里翻译成分组。
PAGES = {
    ("xiaomi", "系统"): "系统广告",
    ("xiaomi", "商店"): "应用商店",
    ("xiaomi", "管家"): "手机管家",
    ("xiaomi", "下载管理"): "下载管理",
    ("xiaomi", "主题"): "主题",
    ("xiaomi", "浏览器"): "浏览器",
    ("xiaomi", "搜索"): "全局搜索",
    ("xiaomi", "负一屏"): "负一屏",
    ("xiaomi", "日历"): "天气和日历",
    ("xiaomi", "天气"): "天气和日历",
    ("oppo", "广告跟踪"): "广告跟踪",
    ("oppo", "下拉搜索"): "下拉搜索",
    ("oppo", "商店"): "软件商店",
    ("oppo", "软件商店"): "软件商店",
    ("oppo", "浏览器"): "浏览器",
    ("oppo", "小布建议"): "小布建议",
    ("oppo", "负一屏"): "负一屏",
    ("oppo", "主题"): "主题商店",
    ("oppo", "视频"): "视频",
    ("oppo", "游戏中心"): "游戏中心",
    ("vivo", "系统"): "系统广告",
    ("vivo", "阅图锁屏"): "阅图锁屏",
    ("vivo", "锁屏"): "阅图锁屏",
    ("vivo", "全局搜索"): "全局搜索",
    ("vivo", "商店"): "应用商店",
    ("vivo", "i管家"): "i管家",
    ("vivo", "天气"): "天气",
    ("vivo", "浏览器"): "浏览器",
    ("honor", "广告与隐私"): "智能推荐服务",
    ("honor", "YOYO 建议"): "YOYO",
    ("honor", "魔法画报"): "魔法画报",
    ("honor", "精品应用"): "桌面文件夹",
    ("honor", "热门推荐管理"): "桌面文件夹",
    ("honor", "系统管家"): "系统管家",
    ("honor", "视频"): "视频",
    ("honor", "搜索"): "下拉搜索",
    ("honor", "负一屏"): "负一屏",
    ("honor", "市场"): "应用市场",
    ("honor", "浏览器"): "浏览器",
    ("honor", "主题"): "主题",
    ("honor", "音乐"): "音乐",
    ("honor", "阅读"): "阅读",
}
# 兜底：占位前缀和没有前缀的标签。都是看过脚本定的，比如 {pkg} 是日历、天气共用的那个循环。
FALLBACK = {
    ("xiaomi", "{pkg}"): "天气和日历",
    ("oppo", "搜索范围"): "下拉搜索",
    ("oppo", "功能管理"): "下拉搜索",
    ("oppo", "消息管理"): "下拉搜索",
    ("oppo", "应用建议"): "小布建议",        # 小布建议 → 其他 → 应用建议
}
OFF, KEEP = "要关", "同页保留"


def key_of(text):
    """去重用的键：NFKC + 去空格，同 #559 的前两步。收录时照原文写。不 import fast.match_key：它要连带 adbutils。"""
    return "".join(unicodedata.normalize("NFKC", text).split())


@dataclass(frozen=True)
class Word:
    """一个词条或同页保留项，在某份脚本的某一行。"""
    text: str
    kind: str
    family: str
    group: str | None           # None：页面标签归不到分组
    page: str
    script: str                 # recipes/ 下的相对路径，比如 xiaomi-M154FF/recipe.py
    line: int

    @property
    def model(self):
        return self.script.split("/", 1)[0].split("-", 1)[-1]

    @property
    def source(self):
        """短写的出处：默认文件 recipe.py 不写文件名。"""
        folder, name = self.script.split("/", 1)
        return f"{folder}:{self.line}" if name == "recipe.py" else f"{folder}/{name}:{self.line}"


@dataclass(frozen=True)
class Call:
    """一处解析不出词的 p.off()，或页面标签归不到分组的 p.off()。"""
    family: str
    script: str
    line: int
    text: str                   # 解析不出的表达式，或者那个页面标签
    words: tuple = ()           # 归不到分组时，这一处读得出的词


@dataclass
class Scan:
    words: list = field(default_factory=list)
    unresolved_only: list = field(default_factory=list)
    unresolved_keep: list = field(default_factory=list)
    unclassified: list = field(default_factory=list)
    whole_page: int = 0         # 不带 only= 的 p.off()：整页全关，没有词


def _constants(tree):
    """模块级的字符串列表常量：{名字: [字符串节点]}。后面又赋了别的值的不算，已经不是这份词了。"""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    literal = _literal(node.value)
                    if literal is None:
                        found.pop(target.id, None)
                    else:
                        found[target.id] = literal
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            found.pop(node.target.id, None)
    return found


def _literal(node):
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    if not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return None
    return list(node.elts)


def _resolve(node, constants):
    """only= / keep= 的字符串节点；解析不出返回 None。"""
    literal = _literal(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _page_label(node):
    """page= 的标签。f-string 的变量部分写成 {变量}；不是字面量的写成 <表达式>；没写 page= 是空串。"""
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            parts.append(value.value if isinstance(value, ast.Constant) else "{" + ast.unparse(value.value) + "}")
        return "".join(parts)
    return f"<{ast.unparse(node)}>"


def has_page(label):
    """标签是不是真的指到一页：变量和没写的都不算。"""
    return bool(label) and not label.startswith("<")


def group_of(family, label):
    prefix = label.split("·", 1)[0].strip()
    return PAGES.get((family, prefix)) or FALLBACK.get((family, prefix))


def _off_calls(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "off"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "p"):
            yield node


def scan(recipes_dir):
    """读所有机型脚本。认不出品牌的目录不进库（tests/test_entries.py 守着每个品牌都有家族）。"""
    out = Scan()
    paths = [os.path.relpath(p, recipes_dir).replace(os.sep, "/")
             for p in glob.glob(os.path.join(recipes_dir, "*", "recipe*.py"))]
    for script in sorted(paths):
        family = FAMILY.get(script.split("-", 1)[0].lower())
        if not family:
            continue
        with open(os.path.join(recipes_dir, script), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        constants = _constants(tree)
        for call in sorted(_off_calls(tree), key=lambda c: c.lineno):
            kwargs = {k.arg: k.value for k in call.keywords if k.arg}
            label = _page_label(kwargs.get("page"))
            group = group_of(family, label)
            here = []
            for arg, kind, missed in (("only", OFF, out.unresolved_only), ("keep", KEEP, out.unresolved_keep)):
                node = kwargs.get(arg)
                if node is None:
                    if arg == "only":
                        out.whole_page += 1
                    continue
                strings = _resolve(node, constants)
                if strings is None:
                    missed.append(Call(family, script, call.lineno, ast.unparse(node)))
                    continue
                here += [Word(s.value, kind, family, group, label, script, s.lineno) for s in strings]
            out.words += here
            if not group:
                out.unclassified.append(Call(family, script, call.lineno, label or "（没写 page=）",
                                             tuple(dict.fromkeys(w.text for w in here))))
    return out


def keys():
    """词库的键，和入口速查同一套。"""
    return [(family, group) for family, groups in ENTRIES.items() for group in groups]


def _spelled(words):
    """同一个键的几种原文写法，常见的在前。"""
    counts = Counter(w.text for w in words)
    return " / ".join(sorted(counts, key=lambda text: (-counts[text], text)))


def _sources(words):
    return "、".join(f"`{s}`" for s in sorted({w.source for w in words}))


def _by_key(words):
    """{键: [Word]}，用的机型多的在前。"""
    merged = defaultdict(list)
    for word in words:
        merged[key_of(word.text)].append(word)
    return sorted(merged.items(), key=lambda item: (-len({w.model for w in item[1]}), item[0]))


def _group_section(group, words):
    lines = [f"### {group}", ""]
    if not words:
        return lines + ["暂无词条。", ""]
    off = [w for w in words if w.kind == OFF]
    keep = [w for w in words if w.kind == KEEP]
    lines += ["**出处机型：** " + "、".join(sorted({w.model for w in words})), ""]
    if off:
        lines += ["**词条**", ""]
        lines += [f"- {_spelled(same)}：{_sources(same)}" for _key, same in _by_key(off)]
        lines.append("")
    if keep:
        lines += ["**同页保留项**（只在这一页成立）", ""]
        pages = defaultdict(list)
        for word in keep:
            pages[word.page].append(word)
        for page in sorted(pages):
            lines += [f"- {page} · {_spelled(same)}：{_sources(same)}" for _key, same in _by_key(pages[page])]
        lines.append("")
    return lines


def reverse_rows(words):
    """反查表的行：(词, 家族名, 分组, 页面, 类别)。没有真实页面的词不进表，它们列在「未归类」。"""
    rows = set()
    for word in words:
        if has_page(word.page):
            rows.add((key_of(word.text), word.text, LABEL.get(word.family, word.family),
                      word.group or "未归类", word.page, word.kind))
    return [row[1:] for row in sorted(rows)]


def render(recipes_dir):
    """docs/清单/词库.md 的全文。"""
    found = scan(recipes_dir)
    words = found.words
    by_group = defaultdict(list)
    for word in words:
        by_group[(word.family, word.group)].append(word)
    lines = ["# 品牌词库：开关词条与同页保留项", "",
             "由 `tool/vocab.py` 从机型脚本现算（`python3 tool/vocab.py > docs/清单/词库.md`），不要手改。", "",
             "按家族和分组列出机型脚本要关的开关（词条）和同页保留项，都带出处。入口怎么进看[入口速查](入口速查.md)。"
             "社区上报里还没落进脚本的叫法看[词条线索](词条线索.md)，那边的不算词条。", "",
             "**用之前：** 词条说明别的机型上这个开关叫这个，不代表这台手机上它管同一件事，写脚本要真机核对。"
             "同页保留项只在那一页成立，不是品牌级的禁词表。", "",
             "出处写成 `目录:行号`，指 `recipes/<目录>/recipe.py`；别的文件写全文件名。"
             f"这里只读 `p.off()`：共 {len(words)} 处词，另有 {found.whole_page} 处不带 `only=`（整页全关，没有词）。", ""]
    for family, groups in ENTRIES.items():
        brands = "、".join(b for b, f in FAMILY.items() if f == family)
        lines += [f"## {LABEL.get(family, family)}（{brands}）", ""]
        for group in groups:
            lines += _group_section(group, by_group[(family, group)])
    lines += [f"## 未解析（only= {len(found.unresolved_only)} 处，keep= {len(found.unresolved_keep)} 处）", "",
              "循环变量和运行时算的，读不出是哪些词。这些脚本里的词不在上面。", ""]
    lines += [f"- `{c.script}:{c.line}` {c.text}" for c in found.unresolved_only]
    lines += [f"- `{c.script}:{c.line}` keep= {c.text}" for c in found.unresolved_keep]
    lines += ["", f"## 未归类（{len(found.unclassified)} 处）", "",
              "页面标签归不到分组：`<变量>` 是运行时才定的标签。这些调用里读得出的词列在这里，不进反查表。", ""]
    lines += [f"- {LABEL.get(c.family, c.family)} `{c.text}`：`{c.script}:{c.line}`"
              + (f"（{'、'.join(c.words)}）" if c.words else "")
              for c in found.unclassified]
    lines += ["", "## 反查表", "", "反查只是索引，不构成跨页禁词表：一个词只在它所在的那一页成立。", "",
              "| 词 | 家族 | 分组 | 页面 | 类别 |", "|---|---|---|---|---|"]
    lines += [f"| {word} | {family} | {group} | {page} | {kind} |"
              for word, family, group, page, kind in reverse_rows(words)]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.stdout.write(render(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")))
