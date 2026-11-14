#!/usr/bin/env python3
"""本机函数审计：每份机型脚本自己定义了哪些模块级函数、各自归哪一档，以及「本机策略：N 个」从哪来。

只读：扫 `recipes/` 的源码（AST，不 import、不执行、不连手机），不改任何仓库文件。`run.py` 的
`check` 与 `status-json` 取同一份计数（`counts()`），数出来的东西因此只有一个来源。

归属四档，判据是**函数体自己调了哪些名字**（直接调用，不穿透到它调的本机助手）：

- 拨动策略（`strategy`）：`p.off` / `p.setting` / `p.switches` / `p.confirm` 与开关读数这类信号。
  这一档是「怎么把一页开关关掉」的算法：精确匹配、逐行重读、整页全关、标题在行外。
- 引擎词汇（`vocabulary`）：`p.start` / `p.go` / `p.tap` / `p.entry` / `p.find` / `p.texts` 与落点
  确认这类信号。这一档是导航、入口、选择器与等待，引擎本该提供。
- 真机型知识（`knowledge`）：两档信号都不占。剩下的多是读屏库直调、`getprop` 守卫、这一页 /
  这个包的常量——只有这一档该长期留在机型脚本里。
- 声明式钩子（`hook`）：`tail` / `guard` / `wrap` / `detail` 这四个名字。它们由引擎在全部段
  之后 / 段入口 / 段内 / 段失败时调用，内容是这一份脚本的收尾打印与守卫，既不是算法也不是
  页面知识；按名字单列一档，否则「本机策略数」会被十几个 `tail()` 淹没（#1244）。

优先级固定：拨动策略 > 引擎词汇 > 真机型知识（钩子先按名字判，不看调用）。一个函数既导航又
拨开关时算策略，那正是要收走的那一类。命中的信号随每行打印出来，判据可复核；信号表在
`STRATEGY_SIGNALS` / `VOCABULARY_SIGNALS`，是一组调用名，不是一张按函数名写的名册；钩子那张
`HOOK_NAMES` 是唯一按名字判的一档。

`@step` 段体不算本机函数：它们是脚本的段落，不是一份实现（由装载器收集）。「涉及机型数」是
**同名函数**出现在几个型号上：≥2 说明同一份实现被复制到了别的机型，收进共享库还是参数化由人判断。

  python3 tool/recipe_audit.py                       全部：合计、按家族、逐脚本
  python3 tool/recipe_audit.py --summary             只打合计与按家族
  python3 tool/recipe_audit.py --family xiaomi       按家族（也认「小米」）
  python3 tool/recipe_audit.py --model M154FF        按机型（也认目录名 xiaomi-M154FF）
  python3 tool/recipe_audit.py --tier strategy       按归属（也认「拨动策略」）
  python3 tool/recipe_audit.py --json                机器可读
"""
import ast
import json
import os
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recipe_source
from entries import FAMILY, LABEL
from stdio import use_utf8_console

STRATEGY, VOCABULARY, KNOWLEDGE, HOOK = "strategy", "vocabulary", "knowledge", "hook"
TIERS = (STRATEGY, VOCABULARY, KNOWLEDGE, HOOK)
TIER_LABEL = {STRATEGY: "拨动策略", VOCABULARY: "引擎词汇", KNOWLEDGE: "真机型知识",
              HOOK: "声明式钩子"}

# 四个可选的脚本侧钩子（`recipe_kit.preamble` 的 docstring）：收尾打印、段入口守卫、段内包装、
# 失败摘要。按名字判，不看函数体调了什么——它们不是算法，也不是页面知识（#1244）。
HOOK_NAMES = frozenset({"tail", "guard", "wrap", "detail"})

# 拨动策略的信号：关开关的算法会碰到的东西（点名、读回、确认、改动台账）。
STRATEGY_SIGNALS = frozenset({
    "p.off", "p.setting", "p.switches", "switches", "p.confirm",
    "p.changed", "p.changed.append",
    "close_named", "read_switches", "switch_signature", "wait_switches", "require_switches",
    "off_exact", "off_one", "off_unnamed", "read_on_page",
})

# 引擎词汇的信号：导航、入口、选择器、落点确认与等待。
VOCABULARY_SIGNALS = frozenset({
    "p.start", "p.go", "p.tap", "p.tap_icon", "p.entry", "p.enter",
    "p.find", "p.texts", "p.focus", "p.tree", "p.tree().iter", "p.click",
    "p.back", "p.tab", "p.top", "p.scroll", "p.scroll_more", "p.scroll_top",
    "p.on_screen", "p.has_text", "p.settle", "p.await_page", "p.sig", "p.note_miss",
    "p.dismiss", "p.locked", "p.in_settings_page", "p.expect_page",
    "p.page_evidence", "p.page_text",
    # 注入面的导航助手与脚本里同形的本地副本（gear / tap / wait_page 那一族）
    "icon_hit", "reach", "until", "opened", "gear", "gear_top", "goto",
    "tap", "tap_page", "tap_any", "tap_row", "tap_text", "tap_by_scroll",
    "wait_page", "enter", "page", "open_page",
})

_STEP = "step"          # `@step("段名")`：段体，不是本机助手


@dataclass(frozen=True)
class LocalFunction:
    """一份脚本里的一个本机模块级函数：名字、行号、归属、判据信号、函数体调过的名字、
    同名函数出现在哪些型号。信号与调用名都是判据的现场——真机型知识正是「两个信号集都不占」。"""
    name: str
    line: int
    tier: str
    signals: tuple[str, ...]
    calls: tuple[str, ...] = ()
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class Script:
    """一份机型脚本（`recipes/<家族>/<型号>/recipe*.py`）与它的本机函数。"""
    script: str             # recipes 下的相对路径
    family: str
    model: str
    functions: tuple[LocalFunction, ...]

    def counts(self) -> dict[str, int]:
        """{total, strategy, vocabulary, knowledge}：`check` / `status-json` 报的就是这四个数。"""
        out = {"total": len(self.functions)}
        for tier in TIERS:
            out[tier] = sum(1 for function in self.functions if function.tier == tier)
        return out


@dataclass(frozen=True)
class Report:
    """一次审计的全部脚本；`scripts` 已按路径排序。"""
    scripts: tuple[Script, ...]

    @property
    def names(self) -> dict[str, tuple[str, ...]]:
        """{函数名: 用这个名的型号}，型号去重排序。"""
        found = defaultdict(set)
        for script in self.scripts:
            for function in script.functions:
                found[function.name].add(script.model)
        return {name: tuple(sorted(models)) for name, models in found.items()}

    def counts(self) -> dict[str, int]:
        out = {"scripts": len(self.scripts), "total": 0}
        for tier in TIERS:
            out[tier] = 0
        for script in self.scripts:
            for key, value in script.counts().items():
                out[key] += value
        return out


def _is_step(node: ast.expr) -> bool:
    """`@step` 或 `@step("段名")`：段体由装载器收集，不算本机函数。"""
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Name) and target.id == _STEP


def definitions(src: str) -> tuple[tuple[str, int], ...]:
    """模块级的 (函数名, 行号)，`@step` 段体除外。命名空间里嵌套的定义不算「本机函数」——
    脚本调用的是模块级那一份，嵌套的多半是闭包里的临时实现。"""
    tree = ast.parse(src)
    return tuple((node.name, node.lineno) for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and not any(_is_step(decorator) for decorator in node.decorator_list))


def tier_of(calls: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """一个函数体的归属与判据：(档, 命中的信号)。策略优先，都不占是真机型知识。"""
    names = list(calls)
    for tier, signals in ((STRATEGY, STRATEGY_SIGNALS), (VOCABULARY, VOCABULARY_SIGNALS)):
        hit = tuple(sorted({name for name in names if name in signals}))
        if hit:
            return tier, hit
    return KNOWLEDGE, ()


def classify(src: str) -> tuple[LocalFunction, ...]:
    """一份脚本源码的本机函数：按定义顺序，`models` 留空（那是整个 `recipes/` 的账）。

    `@step` 段体不算；四个声明式钩子按名字先判成 `hook`，其余才看函数体调了什么。"""
    facts = recipe_source.scan_source(src)
    body_calls = defaultdict(list)
    for call in facts.calls:
        body_calls[call.function].append(call.name)
    out = []
    for name, line in definitions(src):
        # 出口现在是 rt 上的方法：`rt.require_switches` 与裸名同档
        calls = tuple(sorted({call.removeprefix("rt.") for call in body_calls.get(name, ())}))
        tier, signals = (HOOK, ()) if name in HOOK_NAMES else tier_of(calls)
        out.append(LocalFunction(name, line, tier, signals, calls))
    return tuple(out)


def counts(src: str) -> dict[str, int]:
    """一份脚本源码的计数：{total, strategy, vocabulary, knowledge}。没有脚本时四项都是 0。"""
    out = {"total": 0, **{tier: 0 for tier in TIERS}}
    for function in classify(src):
        out["total"] += 1
        out[function.tier] += 1
    return out


def counts_for(path: str) -> dict[str, int]:
    """一份机型脚本（`.py` 或 catalog `.toml`）的本机函数计数，口径同 `audit()`。

    `.toml` 的助手在同目录同名的 `.py` 例外里；段 `code=` 指向的函数等同旧 `@step` 段体，不计入。
    没有例外文件就是 0 个本机函数（不是「读不到」）。"""
    if not str(path).endswith(".toml"):
        with open(path, encoding="utf-8") as handle:
            return counts(handle.read())
    import tomllib
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    codes = {segment["code"] for segment in data.get("segment", []) if "code" in segment}
    companion = str(path)[:-len(".toml")] + ".py"
    if not os.path.isfile(companion):
        return {"total": 0, **{tier: 0 for tier in TIERS}}
    with open(companion, encoding="utf-8") as handle:
        functions = [f for f in classify(handle.read()) if f.name not in codes]
    out = {"total": len(functions), **{tier: 0 for tier in TIERS}}
    for function in functions:
        out[function.tier] += 1
    return out


def _place(script: str) -> tuple[str, str]:
    """`xiaomi/M154FF/recipe.py` → (家族, 型号)。路径第一段就是家族（`recipes/<家族>/<型号>`），认不出时留空。"""
    parts = script.split("/")
    family, model = parts[0], parts[1] if len(parts) > 1 else parts[0]
    return FAMILY.get(family.lower(), ""), model


def audit(recipes_dir: str) -> Report:
    """扫整个 `recipes/`：每份脚本的本机函数，加上「同名函数出现在几台机型」。"""
    family_of, model_of = {}, {}
    functions_of: dict[str, tuple] = {}
    for script in recipe_source.scan_dir(recipes_dir):
        family, model = _place(script)
        path = os.path.join(recipes_dir, script)
        seg_codes = set()
        if script.endswith(".toml"):
            # catalog 机型：本机函数在同目录同名的 `.py` 例外里；没有例外就没有本机函数。
            import tomllib
            with open(path, "rb") as handle:
                data = tomllib.load(handle)
            # 段 `code=` 指向的函数等同旧 `@step` 段体，不是本机助手，不计入（与原口径一致）。
            seg_codes = {seg["code"] for seg in data.get("segment", []) if "code" in seg}
            path = path[:-len(".toml")] + ".py"
            if not os.path.isfile(path):
                family_of[script], model_of[script], functions_of[script] = family, model, ()
                continue
        with open(path, encoding="utf-8") as handle:
            functions = tuple(f for f in classify(handle.read()) if f.name not in seg_codes)
        family_of[script], model_of[script], functions_of[script] = family, model, functions
    reuse = defaultdict(set)
    for script, functions in functions_of.items():
        for function in functions:
            reuse[function.name].add(model_of[script])
    out = []
    for script in sorted(functions_of):
        functions = tuple(replace(function, models=tuple(sorted(reuse[function.name])))
                          for function in functions_of[script])
        out.append(Script(script, family_of[script], model_of[script], functions))
    return Report(tuple(out))


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _tier_of_argument(text: str) -> str | None:
    for tier in TIERS:
        if text in (tier, TIER_LABEL[tier]):
            return tier
    return None


def _family_of_argument(text: str) -> str | None:
    for family, label in LABEL.items():
        if text in (family, label):
            return family
    return None


def filtered(report: Report, family: str = "", model: str = "", tier: str = "") -> Report:
    """按家族 / 机型 / 归属筛一份报告。三个条件都不给时原样返回。"""
    scripts = []
    for script in report.scripts:
        if family and script.family != family:
            continue
        if model and _norm(model) not in (_norm(script.model), _norm(script.script.split("/", 1)[0])):
            continue
        functions = tuple(f for f in script.functions if not tier or f.tier == tier)
        if tier and not functions:      # 按归属筛时，一个都没有的脚本不算命中
            continue
        scripts.append(replace(script, functions=functions))
    return Report(tuple(scripts))


def _family_totals(report: Report) -> list[dict]:
    """按家族汇总：{family, label, scripts, total, strategy, vocabulary, knowledge}，家族按名字排序。"""
    groups = defaultdict(lambda: {"scripts": 0, **{tier: 0 for tier in TIERS}, "total": 0})
    for script in report.scripts:
        row = groups[script.family]
        row["scripts"] += 1
        for key, value in script.counts().items():
            row[key] += value
    return [{"family": family, "label": LABEL.get(family, family or "未登记"), **groups[family]}
            for family in sorted(groups)]


def as_json(report: Report) -> dict:
    """机器可读的形状：totals / families / scripts。`run.py` 不用它，取 `counts()`。"""
    totals = report.counts()
    names = report.names
    totals["names"] = len(names)
    totals["shared"] = sum(1 for models in names.values() if len(models) >= 2)
    return {
        "totals": totals,
        "families": _family_totals(report),
        "scripts": [{
            "script": script.script, "family": script.family, "model": script.model,
            "functions": [{"name": f.name, "line": f.line, "tier": f.tier,
                           "signals": list(f.signals), "calls": list(f.calls),
                           "models": list(f.models)}
                          for f in script.functions],
        } for script in report.scripts],
    }


def _tier_line(counts_of_tiers: dict) -> str:
    return "、".join(f"{TIER_LABEL[tier]} {counts_of_tiers[tier]}" for tier in TIERS)


def _evidence(function: LocalFunction) -> str:
    """判据现场：命中了哪些信号；真机型知识则给出它调过的名字（两档信号都不占正是由这份清单读出来的）。"""
    if function.tier == HOOK:
        return "声明式钩子，由引擎调用"
    if function.signals:
        return "命中 " + "、".join(function.signals)
    return ("没有判据信号，只调了 " + "、".join(function.calls)) if function.calls else "函数体没有调用"


def render(report: Report, family: str = "", model: str = "", tier: str = "",
           per_script: bool = True) -> str:
    """审计报告全文。过滤条件写进开头，免得把「筛过一遍的数」当成总数读。"""
    totals = report.counts()
    names = report.names
    applied = [text for text in (
        f"家族 {LABEL.get(family, family)}" if family else "",
        f"机型 {model}" if model else "",
        f"归属 {TIER_LABEL[tier]}" if tier else "") if text]
    lines = [f"本机函数：{totals['total']} 个（{_tier_line(totals)}）"
             f" · {totals['scripts']} 份脚本"
             f" · {len(names)} 个名字，其中 {sum(1 for m in names.values() if len(m) >= 2)} 个出现在 ≥2 台机型",
             ""]
    if applied:
        lines = [f"过滤：{'、'.join(applied)}", ""] + lines
    lines += ["## 按家族", "",
              "| 家族 | 脚本 | 本机函数 | " + " | ".join(TIER_LABEL[tier] for tier in TIERS) + " |",
              "|---|---|---|---|---|"]
    lines += [f"| {row['label']} | {row['scripts']} | {row['total']} | "
              + " | ".join(str(row[tier]) for tier in TIERS) + " |"
              for row in _family_totals(report)]
    if not per_script:
        return "\n".join(lines + [""])
    lines += ["", "## 按脚本", ""]
    if not report.scripts:
        lines += ["没有匹配的脚本。", ""]
    for script in report.scripts:
        counts_of = script.counts()
        lines += [f"### {script.script}（{LABEL.get(script.family, script.family or '未登记')} "
                  f"{script.model}）", "",
                  f"本机函数 {counts_of['total']} 个（{_tier_line(counts_of)}）", ""]
        lines += [f"- `{f.name}`：{TIER_LABEL[f.tier]}（{_evidence(f)}）"
                  f" · 机型 {len(f.models)} 台 · 行 {f.line}"
                  for f in script.functions]
        lines.append("")
    return "\n".join(lines)


def main(argv) -> int:
    """`python3 tool/recipe_audit.py`：退出码 0 正常、1 参数值认不出、2 用法写错。"""
    usage = "用法：python3 tool/recipe_audit.py [--family 家族] [--model 机型] [--tier 归属]" \
            " [--summary] [--json]"
    family, model, tier, summary, as_json_flag = "", "", "", False, False
    wanted = {"--family": "family", "--model": "model", "--tier": "tier"}
    rest = list(argv)
    while rest:
        option = rest.pop(0)
        if option in ("-h", "--help"):
            print(usage)
            return 0
        if option == "--summary":
            summary = True
            continue
        if option == "--json":
            as_json_flag = True
            continue
        if option not in wanted:
            print(f"不认识的参数 {option}\n{usage}", file=sys.stderr)
            return 2
        if not rest:
            print(f"{option} 后面要跟一个值\n{usage}", file=sys.stderr)
            return 2
        value = rest.pop(0)
        if option == "--family":
            family = _family_of_argument(value) or ""
            if not family:
                print(f"认不出家族 {value}；可用的：{'、'.join(sorted(set(FAMILY.values())))}",
                      file=sys.stderr)
                return 1
        elif option == "--tier":
            tier = _tier_of_argument(value) or ""
            if not tier:
                print(f"认不出归属 {value}；可用的："
                      + "、".join(f"{key}（{TIER_LABEL[key]}）" for key in TIERS), file=sys.stderr)
                return 1
        else:
            model = value
    report = filtered(audit(_recipes_dir()), family, model, tier)
    if model and not report.scripts:
        print(f"recipes/ 下没有 {model} 这个型号的脚本", file=sys.stderr)
        return 1
    if as_json_flag:
        print(json.dumps(as_json(report), ensure_ascii=False, indent=2))
    elif summary:
        print(render(report, family, model, tier, per_script=False))
    else:
        print(render(report, family, model, tier))
    return 0


def _recipes_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")


if __name__ == "__main__":
    use_utf8_console()
    raise SystemExit(main(sys.argv[1:]))
