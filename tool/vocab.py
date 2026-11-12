#!/usr/bin/env python3
"""品牌词库：从机型脚本现算每个 (家族, 分组) 下的词条和同页保留项，写新机型脚本时先查这里。术语见 CONTEXT.md。

键和 entries.py 同一个。入口怎么进看入口速查，这里只装它没有的那层：开关词条、同页保留项、出处。
机型脚本是唯一来源，不手写词；社区线索在手写的 docs/清单/词条线索.md，要变成词条必须先实测并落进机型脚本。

解析 `p.off()` 的 only= / keep= 和 `close_named()` 的第一个参数，认字面量和模块级常量（列表、元组、字典取值）。
循环变量、运行时算的记为未解析，逐条列名，不静默丢弃。模块级字典里的说明文字单列，不算词条。
同页保留项只在那一页、那一次 off() 里成立，这里不产出跨页的禁词表。

机型脚本只解释一次：调用点与模块级常量由 `recipe_source` 的事实层给出（沿用 #1156 的分工），
这里只做页面到分组的映射、方向判定与统计口径，不再自己 `ast.parse` 脚本。
段体搬进注入面之后（#1209），脚本调了哪个段体就把那份实现也扫一遍：词条归调用它的每一个机型，
出处写调用点。只扫段体那张表，导航助手的名单本来就在调用点的实参里。

  python3 tool/vocab.py > docs/清单/词库.md
  python3 tool/vocab.py gaps <目录名>            查漏：同家族别的机型关过、这份脚本没写的词条
"""
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recipe_source
from entries import ENTRIES, FAMILY, LABEL
from polarity import want_state       # 只取极性与词表；不 import fast，那条链会连带 adbutils（#693）
from stdio import use_utf8_console

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
    ("oppo", "主题商店"): "主题商店",
    ("oppo", "OPPO视频"): "视频",
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
    ("vivo", "手机管家"): "i管家",
    ("vivo", "负一屏"): "负一屏",
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
    ("meizu", "系统"): "系统跟踪",
    ("meizu", "全局搜索"): "全局搜索",
    ("meizu", "浏览器"): "浏览器",
    ("meizu", "应用商店"): "应用商店",
    ("meizu", "主题美化"): "主题美化",
    ("meizu", "天气"): "天气",
    ("meizu", "手机管家"): "手机管家",
    ("meizu", "锁屏画报"): "锁屏画报",
}
# 兜底：占位前缀和没有前缀的标签。都是看过脚本定的，比如 {pkg} 是日历、天气共用的那个循环。
FALLBACK = {
    ("xiaomi", "{pkg}"): "天气和日历",
    ("oppo", "搜索范围"): "下拉搜索",
    ("oppo", "功能管理"): "下拉搜索",
    ("oppo", "消息管理"): "下拉搜索",
    ("oppo", "应用建议"): "小布建议",        # 小布建议 → 其他 → 应用建议
    # PMX110 的无前缀标签，看过所在的 @step。「个性化管理」「隐私」在多个段里都用，归不准，留在未归类
    ("oppo", "广告管理"): "浏览器",
    ("oppo", "个性化推荐"): "软件商店",
    ("oppo", "服务管理"): "软件商店",
    ("oppo", "个性化推荐管理"): "游戏中心",
    ("oppo", "消息与广告"): "主题商店",
    ("oppo", "热点资讯"): "负一屏",
    ("oppo", "资讯服务"): "小布建议",
    ("oppo", "首页卡片管理"): "下拉搜索",
}
OFF, OPEN, NOOP, KEEP = "要关", "要开", "不碰", "同页保留"   # 方向取自 polarity.want_state()，不从调用名猜（#693）
CJK = re.compile(r"[\u4e00-\u9fff]")


def key_of(text):
    """去重用的键：NFKC + 去空格，同 #559 的前两步。收录时照原文写。不 import fast.match_key：它要连带 adbutils。"""
    return "".join(unicodedata.normalize("NFKC", text).split())


def direction_of(text):
    """这条词条要拨到哪：保护类开关「要开」，其余普通广告开关「要关」。

    `want_state()` 为 None 的行（「减少动画」这种既没否定词前缀也不带广告词的）在
    `plan_switches()` 里直接跳过，点名等于没点：标「不碰」把这个死名字显出来，
    不能并进「要关」——那正是这次要修的那类不一致（#693）。"""
    want = want_state(text)
    if want is None:
        return NOOP
    return OPEN if want else OFF


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
    injected: bool = False      # 出处是调用点、词住在注入段体里（#1209）

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


@dataclass(frozen=True)
class Note:
    """模块级字典里的一段说明文字。它是打印给人看的，不是开关名单，所以不算词条。"""
    text: str
    key: str
    script: str
    line: int


@dataclass
class Scan:
    words: list = field(default_factory=list)
    unresolved_only: list = field(default_factory=list)
    unresolved_keep: list = field(default_factory=list)
    unresolved_close: list = field(default_factory=list)
    unclassified: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    silent: list = field(default_factory=list)   # 一条词条都没读出来的脚本
    whole_page: int = 0         # 没有点名的：不带 only= 的 p.off()，close_named(None, …)


def _notes(facts, script):
    """模块级字典里写中文的字符串：比如 WKL-AN20 的 CHANGES，按「、」拆开。没有中文的（包名、页面名）不收。"""
    out = []
    for entry in facts.dict_entries:
        if CJK.search(entry.value):
            out += [Note(part.strip(), entry.key, script, entry.line)
                    for part in entry.value.split("、") if part.strip()]
    return out


def has_page(label):
    """标签是不是真的指到一页：变量、模板页（`{pkg}` 这类 f-string）和没写的都不算。"""
    return bool(label) and not label.startswith("<") and "{" not in label


def group_of(family, label):
    prefix = label.split("·", 1)[0].strip()
    return PAGES.get((family, prefix)) or FALLBACK.get((family, prefix))


def _keyword(call, name):
    """调用里带这个关键字名的实参；没写是 None。"""
    return next((arg for arg in call.args if arg.keyword == name), None)


def _positional(call, index):
    """第几个位置实参（`close_named` 的名单与标签）；没写是 None。"""
    found = [arg for arg in call.args if arg.keyword is None]
    return found[index] if index < len(found) else None


def _strings(arg):
    """名单实参解析出的 (词, 行号)；读不出或形参返回 None。

    形参一律算未解析：旧口径只认字面量和模块级常量，事实层回填出来的值不算数（回填对入口
    速查有用，词库这边不是同一件事）。其余用事实层解出的值，它比旧词法宽——单个字符串、
    `+` 拼接、`.format()` 也算，空名单 `[]` 算解析成零词。现有脚本里没有这几类写法。"""
    if arg.param is not None or not arg.resolved:
        return None
    return [(item.text, item.line) for item in arg.values]


def _word_calls(facts):
    """读词的两类调用，按行号排；同一行先 `p.off()` 再 `close_named()`（沿用旧口径）。"""
    calls = [call for call in facts.calls if call.name in ("p.off", "close_named")]
    calls.sort(key=lambda call: (call.line, call.name != "p.off"))
    return calls


def _absorb(out, family, script, facts, call_site=None):
    """把一份事实里的词条、同页保留项与三类读不出来的收进 `out`。

    `call_site` 给定时出处一律记这个行号：段体搬进注入面之后，词写在实现里、调用点留在脚本里，
    出处要写成那份脚本的调用点（#1209）。"""
    for call in _word_calls(facts):
        if call.name == "p.off":
            names, keep = _keyword(call, "only"), _keyword(call, "keep")
        else:
            names, keep = _positional(call, 0) or _keyword(call, "names"), None
        # 取最内层函数名：close_named 里再套助手、助手内调 p.off 时这里不算，会进未解析
        inside = call.function == "close_named"
        label = call.page
        group = group_of(family, label)
        where = call.line if call_site is None else call_site
        injected = call_site is not None
        here = []
        if names is None or names.text == "None":     # 没写 only= 与写了 None 都是整页
            if not inside:
                out.whole_page += 1
        else:
            strings = _strings(names)
            if strings is not None:
                here += [Word(text, direction_of(text), family, group, label, script,
                              at if call_site is None else call_site, injected)
                         for text, at in strings]
            elif not inside:
                missed = out.unresolved_only if call.name == "p.off" else out.unresolved_close
                missed.append(Call(family, script, where, names.text))
        if keep is not None:
            strings = _strings(keep)
            if strings is not None:
                here += [Word(text, KEEP, family, group, label, script,
                              at if call_site is None else call_site, injected)
                         for text, at in strings]
            else:
                out.unresolved_keep.append(Call(family, script, where, keep.text))
        out.words += here
        if not group and not inside:
            out.unclassified.append(Call(family, script, where, label or "（没写页面）",
                                         tuple(dict.fromkeys(w.text for w in here))))


def scan(recipes_dir, injected=None):
    """读所有机型脚本。认不出品牌的目录不进库（tests/test_entries.py 守着每个品牌都有家族）。

    `injected` 是段体注入面的 {名字: 源码}，缺省取 `recipe_source.step_sources()`。脚本调了哪个
    注入名，就把那份实现也扫一遍：词条归调用它的每一个机型，出处记调用点，未解析与整页同样算在
    这份脚本头上（#1209）。空表时与加接线之前逐字相同。"""
    out = Scan()
    injected = recipe_source.step_sources() if injected is None else injected
    for script, facts in recipe_source.scan_dir(recipes_dir, FAMILY).items():
        family = FAMILY[script.split("-", 1)[0].lower()]
        before = len(out.words)
        out.notes += _notes(facts, script)
        _absorb(out, family, script, facts)
        for name in sorted(injected):
            calls = recipe_source.injected_calls(facts, name)
            if not calls:
                continue
            # 段体无形参，实参不跨文件；只有模块常量住在脚本里，按名字交回去
            impl = recipe_source.scan_source(injected[name], externals=facts.constants)
            for call in calls:
                _absorb(out, family, script, impl, call_site=call.line)
        if len(out.words) == before:
            out.silent.append(script)
    return out


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
    toggles = [w for w in words if w.kind in (OFF, OPEN, NOOP)]
    keep = [w for w in words if w.kind == KEEP]
    lines += ["**出处机型：** " + "、".join(sorted({w.model for w in words})), ""]
    if toggles:
        lines += ["**词条**", ""]
        lines += [f"- {_spelled(same)}：{_sources(same)}" for _key, same in _by_key(toggles)]
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
    """反查表的行：(词, 家族名, 分组, 页面, 类别)。

    页面不是真实一页的（`<变量>`、`{…}` 模板页）不进表：变量标签的词列在「未归类」，模板页的词留在分组节。
    """
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
             "按家族和分组列出机型脚本点名的开关（词条）、每条要拨的方向和同页保留项，都带出处。"
             "入口怎么进看[入口速查](入口速查.md)。"
             "社区上报里还没落进脚本的叫法看[词条线索](词条线索.md)，那边的不算词条。", "",
             "**用之前：** 词条说明别的机型上这个开关叫这个，不代表这台手机上它管同一件事，写脚本要真机核对。"
             "同页保留项只在那一页成立，不是品牌级的禁词表。"
             "「要开」是保护类开关：开头带否定词（`polarity.NEG_PREFIX`）且带广告词，引擎会把它拨到开，"
             "判定在 `polarity.want_state()`；不要把这类词条按普通广告开关处理。"
             "「不碰」是点了名、引擎却不会拨的行（既没否定词也没广告词），出现即说明那条点名没生效。", "",
             "出处写成 `目录:行号`，指 `recipes/<目录>/recipe.py`；别的文件写全文件名。"
             f"这里读 `p.off()` 和 `close_named()`：共 {len(words)} 处词，另有 {found.whole_page} 处没有点名（整页全关，没有词）。", ""]
    for family, groups in ENTRIES.items():
        brands = "、".join(b for b, f in FAMILY.items() if f == family)
        lines += [f"## {LABEL.get(family, family)}（{brands}）", ""]
        for group in groups:
            lines += _group_section(group, by_group[(family, group)])
    lines += [f"## 未解析（only= {len(found.unresolved_only)} 处，close_named {len(found.unresolved_close)} 处，"
              f"keep= {len(found.unresolved_keep)} 处）", "",
              "循环变量和运行时算的，读不出是哪些词。这些脚本里的词不在上面。", ""]
    lines += [f"- `{c.script}:{c.line}` {c.text}" for c in found.unresolved_only]
    lines += [f"- `{c.script}:{c.line}` close_named {c.text}" for c in found.unresolved_close]
    lines += [f"- `{c.script}:{c.line}` keep= {c.text}" for c in found.unresolved_keep]
    lines += ["", f"## 字典常量里的说明文字（{len(found.notes)} 段）", "",
              "模块级字典里写给人看的说明，脚本运行时只打印，不拿去拨开关，所以不算词条。"
              "和上面重复的不再标；没有的可能是别的写法，也可能只是措辞，要去手机上看。", ""]
    known = {key_of(w.text) for w in words}
    lines += [f"- `{n.script}:{n.line}` {n.key}：{n.text}" + ("" if key_of(n.text) in known else "（词条里没有）")
              for n in found.notes]
    lines += ["", f"## 未归类（{len(found.unclassified)} 处）", "",
              "页面标签归不到分组。`<变量>` 是运行时才定的标签，它的词只在下面列名、不进反查表；"
              "其余是脚本里的真实标签，`PAGES` / `FALLBACK` 里没有，这些词仍进反查表、分组记「未归类」。", ""]
    lines += [f"- {LABEL.get(c.family, c.family)} `{c.text}`：`{c.script}:{c.line}`"
              + (f"（{'、'.join(c.words)}）" if c.words else "")
              for c in found.unclassified]
    lines += ["", f"## 读不到的脚本（{len(found.silent)} 份）", "",
              "这些脚本一条词条都没读出来：点名开关的地方不是 `p.off()` 的 `only=` / `keep=` 字面量，"
              "也不是 `close_named()` 的名单（常见是自建函数，或名单运行时才算）。写这些机型的脚本时直接翻脚本。", ""]
    lines += [f"- `{script}`" for script in found.silent]
    lines += ["", "## 反查表", "", "反查只是索引，不构成跨页禁词表：一个词只在它所在的那一页成立。"
              "带 `{…}` 的模板页不进表，它们的词在分组节里。", "",
              "| 词 | 家族 | 分组 | 页面 | 类别 |", "|---|---|---|---|---|"]
    lines += [f"| {word} | {family} | {group} | {page} | {kind} |"
              for word, family, group, page, kind in reverse_rows(words)]
    return "\n".join(lines) + "\n"


def gaps(recipes_dir, folder):
    """查漏：同家族别的机型关过、这份脚本没写的词条，按分组列出。

    `folder` 是 recipes/ 下的目录名（`<品牌>-<型号>`）。只比要关的词条，按 key_of() 归一化后比对：
    同页保留项和「要开」的保护类开关不在这台机上独立成立，同族叫法也可能整组不同。
    这是写脚本之后的自查清单，不是缺陷报告。

    目录名按大小写不敏感匹配、容忍尾斜杠：`isdir` 在 macOS 上本来就大小写不敏感，
    不归一化的话认得出目录、却按原样拼 `startswith` 前缀，这份脚本自己的词全被当成漏项。"""
    folder = _folder_name(recipes_dir, folder)
    family = FAMILY.get(folder.split("-", 1)[0].lower())
    if not family:
        raise ValueError(f"认不出 {folder} 的品牌：目录名要写成 <品牌>-<型号>")
    found = scan(recipes_dir)
    words = found.words
    mine = {key_of(word.text) for word in words if word.script.startswith(folder + "/")}
    missing = [word for word in words
               if word.family == family and word.kind == OFF
               and not word.script.startswith(folder + "/") and key_of(word.text) not in mine]
    label = LABEL.get(family, family)
    lines = [f"# 查漏：{folder}", "",
             f"同家族（{label}）别的机型关过、这份脚本没写的词条。这是写脚本之后的自查清单，不是缺陷报告："
             "同族的词在这台机上可能换了叫法、对应 App 没装，或者有意不关。", ""]
    if any(script.startswith(folder + "/") for script in found.silent):
        lines += ["⚠ 这份脚本一条词条都没读出来（见词库的「读不到的脚本」），下面的清单不能当查漏结果用。", ""]
    peers = [call for call in found.unresolved_only + found.unresolved_close
             if call.family == family and not call.script.startswith(folder + "/")]
    if peers:
        lines += [f"同族另有 {len(peers)} 处点名是变量或运行时才算，读不出词、没参与比对："
                  + "、".join(f"`{call.script}:{call.line}`" for call in peers), ""]
    if not missing:
        return "\n".join(lines + ["没有差异：同家族别的机型关过的词条，这份脚本都写了。", ""])
    by_group = defaultdict(list)
    for word in missing:
        by_group[word.group or "未归类"].append(word)
    order = [g for g in ENTRIES.get(family, {}) if g in by_group]
    order += sorted(set(by_group) - set(order))
    lines += [f"共 {len({key_of(word.text) for word in missing})} 条，按分组列：", ""]
    for group in order:
        lines += [f"## {group}", ""]
        for _key, same in _by_key(by_group[group]):
            sources = "、".join(f"`{word.source}`（{word.model} · {word.page or '没写页面'}）" for word in same)
            lines.append(f"- {_spelled(same)}：{sources}")
        lines.append("")
    return "\n".join(lines)


def _folder_name(recipes_dir, folder):
    """`recipes/` 下的真实目录名：容忍尾斜杠、路径分隔符与大小写差异。找不到就抛 FileNotFoundError。"""
    wanted = folder.strip().replace(os.sep, "/").strip("/").lower()
    for name in sorted(os.listdir(recipes_dir)):
        if name.lower() == wanted and os.path.isdir(os.path.join(recipes_dir, name)):
            return name
    raise FileNotFoundError(f"recipes/ 下没有 {folder} 这个目录")


def _recipes_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")


if __name__ == "__main__":
    use_utf8_console()
    if len(sys.argv) == 1:
        sys.stdout.write(render(_recipes_dir()))
    elif len(sys.argv) == 3 and sys.argv[1] == "gaps":
        try:
            sys.stdout.write(gaps(_recipes_dir(), sys.argv[2]))
        except (FileNotFoundError, ValueError) as error:
            print(error, file=sys.stderr)
            raise SystemExit(1) from None
    else:
        print("用法：python3 tool/vocab.py [gaps <目录名>]", file=sys.stderr)
        raise SystemExit(1)
