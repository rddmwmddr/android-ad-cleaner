#!/usr/bin/env python3
"""品牌词库：从所有机型脚本现算每个品牌的开关叫法、入口词、搜索词和组件，写新机型脚本时先查这里。

机型脚本是唯一来源：这里不手写词，避免和脚本两边对不上。同一个词在不同品牌、甚至同品牌不同机型上
意思可能不同（小米「推送消息」是父开关），所以按品牌分，并标出「有的机型关、有的机型留」的词。
词库用来提速，不代替真机核对。

  python3 tool/vocab.py > docs/清单/词库.md
  python3 tool/vocab.py gaps honor-CLE-AN00   同品牌别的机型关过、这份脚本没写的词，写完脚本拿它查漏
  python3 tool/vocab.py community issues.json prs.json > docs/清单/词库-社区线索.md
      issues.json、prs.json 来自 gh issue list / gh pr list --json number,title,body。社区线索未经核实。
"""
import ast
import glob
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entries import FAMILY, LABEL, full, used_by

# 这些调用的字符串参数都是「点进去的入口」。tab / go 也算：都是脚本认得的页面文字。
ENTRY_CALLS = {"maybe", "tap_any", "enter", "open_entry", "tap", "entry", "tab", "go"}
# 到处都有、对找广告开关没有帮助的词。
GENERIC = {"设置", "我的", "更多", "关于", "确定", "取消", "首页", "同意", "允许"}
# 名字像设置页的才算「直达入口」；MarketTabActivity 这类只是 App 首页，直达了也省不了路。
SETTING_PAGE = re.compile(r"setting|prefer|custom|experience|privacy|advert|oaid|recommend|\.ad\.|magazine|adand", re.I)


@dataclass
class Brand:
    """一个品牌家族的词。每个词对应用过它的机型集合。"""
    models: set = field(default_factory=set)
    off: dict = field(default_factory=lambda: defaultdict(set))         # 要关的开关
    keep: dict = field(default_factory=lambda: defaultdict(set))        # 点名不能关的开关
    entries: dict = field(default_factory=lambda: defaultdict(set))     # 入口文字
    search: dict = field(default_factory=lambda: defaultdict(set))      # 设置搜索词
    packages: dict = field(default_factory=lambda: defaultdict(set))    # 脚本打开过的 App


def _strings(node, names):
    """把 AST 节点还原成字符串列表：字面量列表，或脚本里赋过值的变量。其他写法读不出来就算了。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [s for item in node.elts for s in _strings(item, names)]
    if isinstance(node, ast.Name):
        return names.get(node.id, [])
    return []


def _collect_names(tree):
    """脚本里变量对应的词表（`HOT = [...]`、`for name in [...]`）。同名多次赋值的合在一起：只用来收词。"""
    names = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] += _strings(node.value, {})
        elif (isinstance(node, ast.For) and isinstance(node.target, ast.Name)
              and isinstance(node.iter, (ast.List, ast.Tuple))):
            names[node.target.id] += _strings(node.iter, {})
    return names


def _call_name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def read_recipe(src):
    """一份脚本的词：{"off": [...], "keep": [...], "entries": [...], "search": [...], "packages": [...]}。"""
    out = {"off": [], "keep": [], "entries": [], "search": [], "packages": []}
    tree = ast.parse(src)
    names = _collect_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.List, ast.Tuple)):
            # for page, only in [("主页设置", ["宫格位推送"]), …]：入口和要关的词写在一张表里
            for row in node.iter.elts:
                if isinstance(row, ast.Tuple) and len(row.elts) == 2 and isinstance(row.elts[1], ast.List):
                    out["entries"] += _strings(row.elts[0], names)
                    out["off"] += _strings(row.elts[1], names)
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        kwargs = {k.arg: k.value for k in node.keywords if k.arg}
        if name == "off":
            if "only" in kwargs:
                out["off"] += _strings(kwargs["only"], names)
            if "keep" in kwargs:
                out["keep"] += _strings(kwargs["keep"], names)
        elif name == "close_named" and node.args:      # honor-WKL-AN20 的写法：第一个参数是开关名单
            out["off"] += _strings(node.args[0], names)
        elif name in ENTRY_CALLS:
            out["entries"] += [s for arg in node.args for s in _strings(arg, names)]
        elif name == "setting" and node.args:
            out["search"] += _strings(node.args[0], names)
        elif name == "start" and node.args:
            out["packages"] += _strings(node.args[0], names)[:1]
    return out


def scan(recipes_dir):
    """{家族: Brand}。目录名 <品牌>-<型号>，品牌按 FAMILY 归到家族；认不出的品牌不进库。"""
    brands = defaultdict(Brand)
    for path in sorted(glob.glob(os.path.join(recipes_dir, "*", "recipe*.py"))):
        folder = os.path.basename(os.path.dirname(path))
        maker, _, model = folder.partition("-")
        family = FAMILY.get(maker.lower())
        if not family or not model or maker.startswith("zz"):
            continue
        with open(path, encoding="utf-8") as f:
            words = read_recipe(f.read())
        brand = brands[family]
        brand.models.add(model)
        for key, found in words.items():
            for word in found:
                getattr(brand, key)[word].add(model)
    return dict(brands)


def conflicts(brand):
    """同一品牌里有的机型关、有的机型留的词：用之前一定要看清这台手机上它管什么。"""
    return sorted(set(brand.off) & set(brand.keep))


def common_words(brands, least=3):
    """至少 least 个品牌都关过的开关叫法：新品牌可以先找这些词。"""
    seen = defaultdict(set)
    for family, brand in brands.items():
        for word in brand.off:
            seen[word].add(family)
    return {word: families for word, families in seen.items() if len(families) >= least}


def directs_by_family(recipes_dir):
    """{家族: {(包名, 完整页面名): {用过的机型}}}。直接用 entries.used_by 的结果，不另算一份。"""
    out = defaultdict(lambda: defaultdict(set))
    model_family = {}
    for path in glob.glob(os.path.join(recipes_dir, "*", "recipe*.py")):
        maker, _, model = os.path.basename(os.path.dirname(path)).partition("-")
        family = FAMILY.get(maker.lower())
        if family:
            model_family[model] = family
    for key, models in used_by(recipes_dir).items():
        if key[0] != "direct":
            continue
        for model in models:
            family = model_family.get(model)
            if family:
                out[family][(key[1], key[2])].add(model)
    return out


def speedups(recipes_dir):
    """同品牌有机型直达过、别的机型也开这个 App 却没用这一页：
    {家族: [(页面, 已验证机型, 可以试的机型)]}。只是候选，每台都要真机试过才能换。"""
    brands = scan(recipes_dir)
    out = defaultdict(list)
    for family, pages in directs_by_family(recipes_dir).items():
        brand = brands.get(family)
        if not brand:
            continue
        for (pkg, page), proven in sorted(pages.items()):
            if not SETTING_PAGE.search(page):
                continue
            candidates = brand.packages.get(pkg, set()) - proven
            if candidates:
                out[family].append((page, sorted(proven), sorted(candidates)))
    return dict(out)


def gaps(recipes_dir, folder):
    """同品牌别的机型关过、这份脚本（recipes/ 下的目录名）没写的词：{词: 关过它的机型}。
    这台手机上不一定有这个词，只是该去核对的清单。品牌或目录不认识时返回 None。"""
    maker, _, model = folder.partition("-")
    brand = scan(recipes_dir).get(FAMILY.get(maker.lower()))
    if not brand or model not in brand.models:
        return None
    return {word: models for word, models in brand.off.items() if model not in models}


def _line(words, skip=()):
    """按用过的机型数从多到少；括号里是机型数，1 台的不写。"""
    items = sorted(((w, len(m)) for w, m in words.items() if w not in skip), key=lambda x: (-x[1], x[0]))
    return "、".join(f"{w}（{n}）" if n > 1 else w for w, n in items) or "—"


def markdown(recipes_dir):
    """docs/清单/词库.md 的全文。"""
    brands = scan(recipes_dir)
    ups = speedups(recipes_dir)
    lines = ["# 品牌词库：广告入口、开关叫法和组件", "",
             "由 `tool/vocab.py` 从所有机型脚本现算（`python3 tool/vocab.py > docs/清单/词库.md`），不要手改。",
             "括号里是用过这个词的机型数，没写就是 1 台。社区上报里还没进脚本的词在 [词库-社区线索](词库-社区线索.md)。", "",
             "**用之前：** 这些词只说明「别的机型上叫这个」，不代表这台手机上它管的是同一件事。写脚本要真机核对。", ""]
    shared = common_words(brands)
    if shared:
        lines += ["## 多个品牌都用的开关叫法", "",
                  "新品牌可以先找这些词。", "",
                  "、".join(sorted(shared, key=lambda w: (-len(shared[w]), w))), ""]
    for family in sorted(brands, key=lambda f: -len(brands[f].models)):
        brand = brands[family]
        lines += [f"## {LABEL.get(family, family)}（{len(brand.models)} 个机型）", "",
                  f"**要关的开关：** {_line(brand.off)}", "",
                  f"**点名不能关的开关：** {_line(brand.keep)}", ""]
        mixed = conflicts(brand)
        if mixed:
            lines += [f"**⚠️ 有的机型关、有的机型留，先看清它管什么：** {'、'.join(mixed)}", ""]
        lines += [f"**入口文字：** {_line(brand.entries, GENERIC)}", "",
                  f"**设置搜索词：** {_line(brand.search)}", "",
                  f"**脚本打开过的 App：** {_line(brand.packages)}", ""]
        if ups.get(family):
            lines += ["**可以试试直达（同品牌已验证，这些机型还没用）：**", ""]
            lines += [f"- `{page}`：{'、'.join(proven)} 用过；可以试 {'、'.join(candidates)}"
                      for page, proven, candidates in ups[family]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- 社区线索 ---------- #

_ACTIVITY = re.compile(r"\b((?:com|cn)\.[a-z0-9_.]+)/(\.?[A-Za-z0-9_.$]+)")
_QUOTED = re.compile(r"「([^」\n]{2,14})」")
_AD_WORD = re.compile(r"广告|推荐|个性化|热搜|资讯|推送|营销|开屏|OAID|信息流|活动|优惠")
# 引号里常是在转述或下判断，不是页面上的叫法：「没有关闭任何广告」「不是营销」
_NOT_A_NAME = re.compile(r"^(没有|不是|未|仍|把|要|已|这|让|各|营销渠道|关闭各)|[→,，、：:。！？\d]")
_PKG_FAMILY = (("com.miui.", "xiaomi"), ("com.xiaomi.", "xiaomi"), ("com.android.thememanager", "xiaomi"),
               ("com.android.browser", "xiaomi"), ("com.android.quicksearchbox", "xiaomi"),
               ("com.vivo.", "vivo"), ("com.bbk.", "vivo"), ("com.iqoo.", "vivo"),
               ("com.heytap.", "oppo"), ("com.oplus.", "oppo"), ("com.coloros.", "oppo"), ("com.nearme.", "oppo"),
               ("com.hihonor.", "honor"), ("com.honor.", "honor"),
               ("com.huawei.", "huawei"), ("com.samsung.", "samsung"), ("com.sec.", "samsung"), ("com.meizu.", "meizu"))
_BRAND_WORD = (("小米", "xiaomi"), ("红米", "xiaomi"), ("Redmi", "xiaomi"), ("REDMI", "xiaomi"), ("HyperOS", "xiaomi"),
               ("vivo", "vivo"), ("iQOO", "vivo"), ("OriginOS", "vivo"),
               ("OPPO", "oppo"), ("一加", "oppo"), ("realme", "oppo"), ("ColorOS", "oppo"),
               ("荣耀", "honor"), ("MagicOS", "honor"), ("华为", "huawei"), ("三星", "samsung"), ("魅族", "meizu"))


def _families_in(text):
    return {family for word, family in _BRAND_WORD if word in text}


def community(items, recipes_dir):
    """从 issue、PR 里提还没进机型脚本的线索：{家族: {"words": {词: {编号}}, "activities": {页面: {编号}}}}。
    只提广告相关的引号词和 Activity 名，不碰正文其他内容，所以带不进用户名、序列号和应用列表。
    一条里提到多个品牌时词归不准，就不收词，只收能按包名归属的 Activity。"""
    brands = scan(recipes_dir)
    known_pages = {key[2] for key in used_by(recipes_dir) if key[0] == "direct"}
    out = defaultdict(lambda: {"words": defaultdict(set), "activities": defaultdict(set)})
    for item in items:
        number, text = item["number"], (item.get("title") or "") + "\n" + (item.get("body") or "")
        for match in _ACTIVITY.finditer(text):
            pkg, activity = match.group(1), match.group(2)
            family = next((f for prefix, f in _PKG_FAMILY if pkg.startswith(prefix)), None)
            page = full(pkg, activity if "." in activity else "." + activity)
            # 末段小写的是包名片段（com.heytap.browser/.settings），不是页面
            if family and page not in known_pages and page.rsplit(".", 1)[-1][:1].isupper():
                out[family]["activities"][page].add(number)
        families = _families_in(text)
        if len(families) != 1:
            continue
        family = next(iter(families))
        known = brands[family].off.keys() | brands[family].keep.keys() if family in brands else set()
        for word in _QUOTED.findall(text):
            if _AD_WORD.search(word) and word not in known and not _NOT_A_NAME.search(word):
                out[family]["words"][word].add(number)
    return out


def community_markdown(items, recipes_dir):
    found = community(items, recipes_dir)
    lines = ["# 词库：社区线索", "",
             "**未经核实。** 从 GitHub 的 issue 和 PR 里提取、还没进机型脚本的广告相关叫法和页面。写脚本时可以当线索去手机上找，",
             "不能直接用。括号里是出处编号。重新生成见 `tool/vocab.py` 开头的说明。", ""]
    for family in sorted(found, key=lambda f: LABEL.get(f, f)):
        section = found[family]
        lines += [f"## {LABEL.get(family, family)}", ""]
        if section["words"]:
            words = sorted(section["words"].items(), key=lambda x: (-len(x[1]), x[0]))
            lines += ["**叫法：** " + "、".join(f"{w}（{' '.join(f'#{n}' for n in sorted(refs)[:3])}）" for w, refs in words), ""]
        if section["activities"]:
            lines += ["**页面：**", ""]
            lines += [f"- `{page}`（{' '.join(f'#{n}' for n in sorted(refs)[:3])}）"
                      for page, refs in sorted(section["activities"].items())]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv):
    recipes = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")
    if argv and argv[0] == "gaps":
        found = gaps(recipes, argv[1]) if len(argv) == 2 else None
        if found is None:
            print("用法：vocab.py gaps <recipes 下的目录名>，比如 honor-CLE-AN00", file=sys.stderr)
            return 2
        for word, models in sorted(found.items(), key=lambda x: (-len(x[1]), x[0])):
            print(f"{word}\t{'、'.join(sorted(models))}")
        return 0
    if argv and argv[0] == "community":
        items = []
        for path in argv[1:]:
            with open(path, encoding="utf-8") as f:
                items += json.load(f)
        sys.stdout.write(community_markdown(items, recipes))
        return 0
    sys.stdout.write(markdown(recipes))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main(sys.argv[1:]))
