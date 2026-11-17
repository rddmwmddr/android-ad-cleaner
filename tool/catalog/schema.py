"""catalog 数据的 schema 与校验（ADR-0038）：种类白名单，未知键直接报错。

schema 只装机型知识（有哪些页面、有哪些行、怎么进去、关哪些、留哪些）；编排语义（重试、收尾、
失败收集、台账、页面快照）不进数据，归运行时。校验器与解释器共用同一份装载入口（`catalog.load`），
所以这里只判定「数据是不是合法的页面树」，不执行任何设备动作。

封闭清单：顶层键、段的键都写死在这里；每种 op 的词汇约束是 `OPS` 里的一条 `OpSpec`——允许哪些键、
必须带哪些键、哪些键装着子 op、产不产出词条 / 入口事实、哪些键要抽成词条。出现名单外的键或缺键即
`SchemaError`。扩展一种新知识先在那里登记，判据是「≥2 机型用法」，不是数字上限（ADR-0038）。
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from . import launch

# 顶层允许的键：身份（model / models / build）、四个可选钩子的名字（指向该机例外函数），以及段表。
TOP_KEYS = frozenset({"model", "models", "build", "const", "tail", "guard", "detail", "wrap", "segment"})
# 一段要么 `code = "<本机策略名>"`（整段交给例外函数），要么给一串 `ops`；两者只能选一个。
SEGMENT_KEYS = frozenset({"name", "code", "ops"})

# `if_focus` 的比法：前台窗口原文与数据里的 text 怎么比。缺省 contains（与 `require_focus` 同档）。
FOCUS_MATCHES = frozenset({"equals", "starts", "contains", "icontains"})

# `p.start` 的落点参数：只有那条路会等前台回目标 App 并核落点，命令形状不经它。
LANDING_KEYS = ("settle", "foreground", "expect", "budget")


class SchemaError(ValueError):
    """数据不合法：缺键、多了名单外的键、`only` 与 `keep` 重叠之类。装载期就报，不等真机。"""


@dataclass(frozen=True)
class OpSpec:
    """一种 op 的全部词汇约束。校验器与抽词条都只读这一条记录，`OPS` 是唯一 owner。"""

    keys: frozenset[str]                        # 允许的键，含 "kind"
    required: tuple[str, ...] = ()              # 有序：缺多个键时的报错顺序与今天一致
    nested: tuple[str, ...] = ()                # 装着子 op 列表的键（"ops" / "else_ops"）
    no_fact: bool = False                       # 不产出词条 / 入口事实
    word_keys: tuple[tuple[str, str], ...] = ()  # (键名, 来源档 literal|strategy)，供抽词条用
    check: Callable[[Mapping[str, Any], str], None] | None = None


def _require(op: Mapping, key: str, where: str) -> None:
    if key not in op:
        raise SchemaError(f"{where} 缺 {key}")


def _reject_extra(op: Mapping, allowed: frozenset, where: str) -> None:
    extra = set(op) - allowed
    if extra:
        raise SchemaError(f"{where} 出现名单外的键：{sorted(extra)}；允许的是 {sorted(allowed)}")


def _validate_off(op: Mapping, where: str) -> None:
    """`off` 三种形态：内联字面量 `only` / `only_code` 指向本机策略 / 都不给 = 整页全关（`p.off` 无 only）。

    `only` 与 `only_code` 是「点名」（安全模式不抑制）；都不给时按 `p.off(page=…)` 的整页全关，与
    UI 按钮式的 `close_all` 是两条不同的路（前者是引擎的 plan_switches 没有 only，后者点屏幕上的按钮）。"""
    _require(op, "page", where)  # pragma: no mutate 不可达：`OPS["off"].required` 已含 page，通用必填循环在 check 之前就拦了
    has_only, has_code = "only" in op, "only_code" in op
    if has_only and has_code:
        raise SchemaError(f"{where} 的 off 不能同时给 only 与 only_code")
    if not has_only and not has_code and not op.get("page_wide"):
        raise SchemaError(f"{where} 的 off 没点名：整页全关请加 page_wide=true，或用 close_all")
    if has_only:
        only = op["only"]
        if not isinstance(only, list) or not only:
            raise SchemaError(f"{where} 的 off 的 only 必须是非空数组（整页全关就写 page_wide=true）")
        overlap = set(only) & set(op.get("keep", []))
        if overlap:
            raise SchemaError(f"{where} 的 off 里 only 与 keep 重叠：{sorted(overlap)}")


def _validate_off_required(op: Mapping, where: str) -> None:
    """`off_required`：跨翻页读齐开关、点名断言都在再关。`only` 必填且非空，`keep` 不许与它重叠。"""
    _require(op, "only", where)  # pragma: no mutate 不可达：`OPS["off_required"].required` 已含 only
    _require(op, "page", where)  # pragma: no mutate 不可达：同上，page 也在 required 里，check 跑不到这里
    only = op["only"]
    if not isinstance(only, list) or not only:
        raise SchemaError(f"{where} 的 off_required 的 only 必须是非空数组")
    overlap = set(only) & set(op.get("keep", []))
    if overlap:
        raise SchemaError(f"{where} 的 off_required 里 only 与 keep 重叠：{sorted(overlap)}")


def _validate_calls(op: Mapping, where: str, allowed: tuple, required: str | tuple) -> None:
    """`calls` 表：短路 OR 的几次调用，每次只允许 `allowed` 里的键、必须给 `required`。

    `required` 是元组时要求「恰好一个」：`if_lib_any` 的每次调用要么是注入助手（`name`），要么是
    页面门面方法（`method`）——旧脚本的短路链两种都串过。`require_expect` 的每个调用要 `args`
    （`p.expect_page` 的第一个实参）。实参逐条照原样下发，位置 / 关键字不合并。"""
    calls = op.get("calls")
    if "calls" not in op:
        raise SchemaError(f"{where} 缺 calls")
    if not isinstance(calls, list) or not calls:
        raise SchemaError(f"{where} 的 calls 必须是非空的数组")
    for index, call in enumerate(calls):
        place = f"{where} 的第 {index + 1} 个 call"
        if not isinstance(call, Mapping):
            raise SchemaError(f"{place} 必须是表")
        _reject_extra(call, frozenset(allowed), place)
        if isinstance(required, tuple):
            present = [key for key in required if key in call]  # pragma: no mutate 语义等价：元组只有 ("name", "method") 两项，len(present) 与 len(缺席) 同真同假
            if len(present) != 1:
                raise SchemaError(f"{place} 要给「{' / '.join(required)}」里的恰好一个")
        elif required not in call:
            raise SchemaError(f"{place} 缺 {required}")
        if "args" in call and (not isinstance(call["args"], list) or not call["args"]):
            raise SchemaError(f"{place} 的 args 必须是非空数组")


def _validate_focus_match(op: Mapping, where: str) -> None:
    """`if_focus` 的 `match` 取值封闭：写错的比法装载期就报，不等到真机发现「永远不匹配」。"""
    if op.get("match", "contains") not in FOCUS_MATCHES:
        raise SchemaError(f"{where} 的 match={op['match']!r} 认不出；可用的是 "
                          f"{sorted(FOCUS_MATCHES)}")


def _validate_gated_entries(op: Mapping, where: str) -> None:
    """`gated` 的 `entries` 是入口候选清单，空清单等于什么都不试，装载期就报。"""
    entries = op.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SchemaError(f"{where} 的 gated 需要非空的 entries")


def _validate_return(op: Mapping, where: str) -> None:
    """`return` 的 `value` 是段的结局，只有 true / false 两态；不写 value 表示默认结局。"""
    if "value" in op and not isinstance(op["value"], bool):
        raise SchemaError(f"{where} 的 value 只能是 true / false（段的结局）")


def _validate_tap_id(op: Mapping, where: str) -> None:
    """`tap_id` 按 u2 选择器点一个控件：资源 id 与文字至少要给一个，两个都空等于没得点。"""
    if "resource_id" not in op and "text" not in op:
        raise SchemaError(f"{where} 的 tap_id 至少要有 resource_id 或 text")


def _validate_gesture(op: Mapping, where: str) -> None:
    """`gesture` 的两端各是 `[x, y]`，按屏宽 / 屏高的比例给；`ms` 是 swipe 的毫秒数。

    只收比例：按读到的控件位置现算的坐标属 docs/04 的「坐标算法」，留在例外 `.py` 里。"""
    for key in ("start", "end"):
        point = op[key]
        if (not isinstance(point, list) or len(point) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1
                           for v in point)):
            raise SchemaError(f"{where} 的 {key} 要是两个 0–1 的比例 [x, y]")
    if not isinstance(op["ms"], int) or isinstance(op["ms"], bool) or op["ms"] <= 0:
        raise SchemaError(f"{where} 的 ms 要是正的整数毫秒")


def _validate_let(op: Mapping, where: str) -> None:
    """`let` 把库助手的返回值绑成段内名字（#1373）：`name` 是绑定的名字，`lib` 是要调的实现。

    `lib` 与 `lib` op 的 `name` 是同一个集合（装载器在 `_check_names` 里核对）；两者都要非空，
    绑定的名字与实现名重名由装载器按库名表拒绝。"""
    for key in ("name", "lib"):
        if not isinstance(op[key], str) or not op[key]:
            raise SchemaError(f"{where} 的 {key} 必须是非空字符串")


def _validate_if_var(op: Mapping, where: str) -> None:
    """`if_var` 按绑定的名字分岔（#1373）：不写 `not_none` 按真假值，写了按「不是 None」。

    `not_none` 只有 true / false 两态；写 false 与不写同义（显式写出「按真假值」）。"""
    if not isinstance(op["name"], str) or not op["name"]:
        raise SchemaError(f"{where} 的 name 必须是非空字符串")
    if "not_none" in op and not isinstance(op["not_none"], bool):
        raise SchemaError(f"{where} 的 not_none 只能是 true / false")


def _validate_require_switches(op: Mapping, where: str) -> None:
    """`require_switches` 把段内读到的开关表交给点名核对（#1373）：`before` 只收 `{expr = "var"}`。

    直接写一张字面量开关表在数据里没有意义（状态是运行期读出来的）；缺一项就整段不动那条出口
    归 `Runtime.require_switches()`，这里只判定数据写得出一个读得到的名字。"""
    before = op["before"]
    if (not isinstance(before, Mapping) or before.get("expr") != "var"
            or not isinstance(before.get("name"), str) or not before.get("name")):
        raise SchemaError(f'{where} 的 before 要写成 {{expr = "var", name = "…"}}')
    names = op["names"]
    if (not isinstance(names, list) or not names
            or not all(isinstance(name, str) and name for name in names)):
        raise SchemaError(f"{where} 的 names 必须是非空的字符串数组")
    if not isinstance(op["title"], str) or not op["title"]:
        raise SchemaError(f"{where} 的 title 必须是非空字符串")


def _validate_arg_blocks(op: Mapping, where: str) -> None:
    """实参里的 `{ops = [...]}`：库在两步之间回调的子段表（`close_named(..., reopen=…)`，#1371）。

    实参内容对 schema 一般是不透明的（标题、Activity、超时秒数），只有带 `ops` 的表是数据再入，
    所以它按同一条白名单校验——块里的 op 与顶层 op 共用 `OPS`，不校验的话嵌套里的错键要等真机跑
    到那一步才发现。"""
    args, kwargs = op.get("args"), op.get("kwargs")
    values = (args if isinstance(args, list) else []) + (
        list(kwargs.values()) if isinstance(kwargs, Mapping) else [])
    for value in values:
        if isinstance(value, Mapping) and "ops" in value:
            place = f"{where} 的实参块"
            _reject_extra(value, frozenset({"ops"}), place)
            _validate_ops(value["ops"], place)


# `calls` 表的两处用法：各自允许哪些键、每次调用必须给哪个键，仍与 `_validate_calls` 同源。
def _validate_expect(op: Mapping[str, Any], where: str) -> None:
    """`require_expect`：先给 `calls` 表定形，再要一句 `miss_print`——原先分派就是这个先后。

    它不把 `miss_print` 放进 `required`：那会排到 `calls` 定形之前，两处同时写错时报的字段就变了。"""
    _validate_calls(op, where, ("args", "kwargs"), required="args")
    _require(op, "miss_print", where)


def _validate_any_calls(op: Mapping[str, Any], where: str) -> None:
    """`if_lib_any` 的短路链：每次调用要么点注入助手（`name`），要么点门面方法（`method`）。"""
    _validate_calls(op, where, ("name", "method", "args", "kwargs"), required=("name", "method"))


def _validate_start(op: Mapping, where: str) -> None:
    """`start` 的两种写法：`p.start`（包 + 页面 + 落点参数）与原始命令（Intent / URI / 窗口模式 / 裸启动 / monkey）。

    `pkg` 不是无条件必填：`am start -a android.settings.SETTINGS` 这种公开 Intent 不带 `-p`，数据里
    没有包名可写。落点参数（`settle` / `foreground` / `expect` / `budget`）只属于 `p.start` 那条路，
    与命令形状同写会让数据以为有落点校验、实际没有。"""
    for key in ("pkg", "activity", "action", "data", "flags"):
        if key in op and (not isinstance(op[key], str) or not op[key]):
            raise SchemaError(f"{where} 的 {key} 必须是非空字符串")
    for key in ("clear_task", "launcher"):
        if key in op and not isinstance(op[key], bool):
            raise SchemaError(f"{where} 的 {key} 只能是 true / false")
    if "launcher" in op and not op["launcher"]:
        raise SchemaError(f"{where} 的 launcher 只有 true 一种写法（不发 monkey 就不写）")
    if op.get("launcher"):
        extra = sorted(set(op) & ({"activity", "action", "data", "flags"} | set(LANDING_KEYS)))
        if extra:
            raise SchemaError(f"{where} 的 start 用 launcher 拉起时不能再给 {extra}")
        if "pkg" not in op:
            raise SchemaError(f"{where} 的 start 用 launcher 拉起时 launcher 要有 pkg")
    else:
        if not any(key in op for key in ("pkg", "action", "data")):
            raise SchemaError(f"{where} 的 start 至少要给 pkg / action / data / launcher 之一")
        if "activity" in op and "pkg" not in op:
            raise SchemaError(f"{where} 的 start 的 activity 要配 pkg")
        if any(key in op for key in launch.SHAPE_KEYS):
            landing = sorted(set(op) & set(LANDING_KEYS))
            if landing:
                raise SchemaError(f"{where} 的 {landing} 只走 p.start 那条路，不能与命令形状同写")
            if "pkg" in op and not any(key in op for key in ("activity", "action")):
                # `am start -p <包>` 不是一次拉起：包名只在 `-n <包/页面>` 或 `-a <动作> -p <包>` 里有用。
                raise SchemaError(f"{where} 的 start 只有 pkg 拉不起来：写形状键时要再给 activity 或 action")
        if "data" in op and "action" not in op:
            raise SchemaError(f"{where} 的 start 的 data 要配 action（单独的 -d 没有 Intent 可寻址）")
    if "flags" in op:
        flag = op["flags"].split()
        if not flag or flag[0] not in launch.LAUNCH_FLAGS:
            raise SchemaError(f"{where} 的 flags 只放行 {sorted(launch.LAUNCH_FLAGS)}，"
                              f"收到 {flag[0] if flag else op['flags']!r}")


def _keys(names: str) -> frozenset[str]:
    """`"kind name args"` → 键集合：一条记录一行写完，读一列就是完整的允许键。"""
    return frozenset(names.split())


# 每种 op 一条记录。加一种 op 只改这里一条，加一条降级分支（事实层）或让它的 `no_fact=True`。
OPS: dict[str, OpSpec] = {
    "lib": OpSpec(_keys("kind name args kwargs"), required=("name",)),
    "let": OpSpec(_keys("kind name lib args kwargs"), required=("name", "lib"), check=_validate_let),
    "require_switches": OpSpec(_keys("kind before names title"),
                               required=("before", "names", "title"),
                               check=_validate_require_switches, no_fact=True),
    "off": OpSpec(_keys("kind only only_code keep page max_screens page_wide"),
                  required=("page",),
                  word_keys=(("only", "literal"), ("only_code", "strategy"), ("keep", "literal")),
                  check=_validate_off),
    "off_required": OpSpec(_keys("kind only keep page contains"),
                           required=("only", "page"),
                           word_keys=(("only", "literal"), ("keep", "literal")),
                           check=_validate_off_required),
    "close_all": OpSpec(_keys("kind page button"), required=("page",)),
    "close_listed": OpSpec(_keys("kind names page miss_print"),
                           required=("names", "page", "miss_print"),
                           word_keys=(("names", "literal"),)),
    "start": OpSpec(_keys("kind pkg activity action data flags clear_task launcher "
                          "settle foreground expect budget"),
                    check=_validate_start),
    "start_or_skip": OpSpec(_keys("kind pkg activity dead_ends reason"),
                            required=("pkg", "activity", "dead_ends", "reason")),
    "skip_unless_installed": OpSpec(_keys("kind command contains text"),
                                    required=("command", "contains", "text")),
    "await_page": OpSpec(_keys("kind"), no_fact=True),
    "entry": OpSpec(_keys("kind text scrolls"), required=("text",)),
    "enter": OpSpec(_keys("kind text scrolls"), required=("text",)),
    "gated": OpSpec(_keys("kind entries scrolls ops"), nested=("ops",),
                    check=_validate_gated_entries),
    "require_entry": OpSpec(_keys("kind text scrolls miss_print miss_back"),
                            required=("text", "miss_print")),
    "require_lib": OpSpec(_keys("kind name args kwargs miss_print miss_back fail evidence at_focus"),
                          required=("name", "miss_print")),
    "require_tab": OpSpec(_keys("kind name settle miss_print evidence at_focus"),
                          required=("name", "miss_print"), no_fact=True),
    "require_tap": OpSpec(_keys("kind text exact scrolls miss_print evidence at_focus"),
                          required=("text", "miss_print"), no_fact=True),
    "require_go": OpSpec(_keys("kind text expect miss_print evidence at_focus"),
                         required=("text", "expect", "miss_print"), no_fact=True),
    "require_expect": OpSpec(_keys("kind calls miss_print evidence at_focus"),
                             check=_validate_expect, no_fact=True),
    "require_unlocked": OpSpec(_keys("kind miss_print"), no_fact=True),
    "shell": OpSpec(_keys("kind command"), required=("command",)),
    "sleep": OpSpec(_keys("kind seconds"), required=("seconds",), no_fact=True),
    "press": OpSpec(_keys("kind key"), required=("key",), no_fact=True),
    "app_stop": OpSpec(_keys("kind pkg"), required=("pkg",), no_fact=True),
    "note_miss": OpSpec(_keys("kind text"), required=("text",), no_fact=True),
    "miss_reset": OpSpec(_keys("kind"), no_fact=True),
    "tap": OpSpec(_keys("kind text exact scrolls kwargs"), required=("text",), no_fact=True),
    "tap_id": OpSpec(_keys("kind resource_id text optional miss_print"), check=_validate_tap_id,
                     no_fact=True),
    "gesture": OpSpec(_keys("kind start end ms"), required=("start", "end", "ms"),
                      check=_validate_gesture, no_fact=True),
    "go": OpSpec(_keys("kind text expect"), required=("text", "expect"), no_fact=True),
    "dismiss": OpSpec(_keys("kind"), no_fact=True),
    "skip_in_safe_mode": OpSpec(_keys("kind"), no_fact=True),
    "require_setting": OpSpec(_keys("kind kw entry miss_print"), required=("kw", "miss_print")),
    "require_focus": OpSpec(_keys("kind contains miss_print"), required=("contains", "miss_print"),
                            no_fact=True),
    "require_find": OpSpec(_keys("kind text exact miss_print"), required=("text", "miss_print"),
                           no_fact=True),
    "if_find": OpSpec(_keys("kind text exact edge_ok nav ops else_ops"), required=("text",),
                      nested=("ops", "else_ops")),
    "if_entry": OpSpec(_keys("kind text scrolls ops else_ops"), required=("text",),
                       nested=("ops", "else_ops")),
    "if_lib": OpSpec(_keys("kind name args kwargs ops else_ops"), required=("name",),
                     nested=("ops", "else_ops")),
    "if_var": OpSpec(_keys("kind name not_none ops else_ops"), required=("name",),
                     nested=("ops", "else_ops"), check=_validate_if_var),
    "if_lib_any": OpSpec(_keys("kind calls ops else_ops"), nested=("ops", "else_ops"),
                         check=_validate_any_calls),
    "if_setting": OpSpec(_keys("kind kw entry ops else_ops"), required=("kw",),
                         nested=("ops", "else_ops")),
    "if_focus": OpSpec(_keys("kind text match ops else_ops"), required=("text",),
                       nested=("ops", "else_ops"), check=_validate_focus_match),
    "if_tap": OpSpec(_keys("kind text exact scrolls ops else_ops"), required=("text",),
                     nested=("ops", "else_ops")),
    "back": OpSpec(_keys("kind n"), no_fact=True),
    "top": OpSpec(_keys("kind n"), no_fact=True),
    "page": OpSpec(_keys("kind args kwargs"), required=("args",), no_fact=True),
    "skip": OpSpec(_keys("kind text"), required=("text",), no_fact=True),
    "fail": OpSpec(_keys("kind text evidence"), required=("text",), no_fact=True),
    "scoped": OpSpec(_keys("kind systemui_text ops"), nested=("ops",)),
    "code": OpSpec(_keys("kind name args"), required=("name",)),
    "print": OpSpec(_keys("kind text focus"), required=("text",), no_fact=True),
    "return": OpSpec(_keys("kind value"), check=_validate_return, no_fact=True),
    "return_lib": OpSpec(_keys("kind name args kwargs"), required=("name",)),
}

# 三个旧名字是 `OPS` 的派生视图：外部与文档仍按这些名字取，读的永远是同一条记录。
OP_KEYS = {kind: spec.keys for kind, spec in OPS.items()}
OP_KINDS = frozenset(OPS)
# 不产出词条 / 入口事实的 op：事实层（`recipe_source._catalog_src`）见到这些 kind 直接跳过。
# 加一种 op 时，要么在事实层给它一条降级分支（产出词条 / 入口），要么让它的 `no_fact=True`
# （它本来就不产出事实）；两样都没做，投影函数末尾的总 `else` 会在装载期外点名它——不让数据
# 静默少一条记录。这些 kind 的允许键都不含 `ops` / `else_ops`：跳过就不往里递归，带子 op 的
# kind 必须走降级分支。
NO_FACT_KINDS = frozenset(kind for kind, spec in OPS.items() if spec.no_fact)


def validate(data: object) -> None:
    """校验一份解析后的 TOML 数据；不合法抛 `SchemaError`。校验器与解释器共用（`catalog.load`）。"""
    if not isinstance(data, Mapping):
        raise SchemaError("数据顶层必须是表（table）")
    _reject_extra(data, TOP_KEYS, "顶层")
    segments = data.get("segment")
    if not isinstance(segments, list) or not segments:
        raise SchemaError("至少要有 [[segment]]（一份数据至少一段）")
    names = []
    for index, segment in enumerate(segments):
        where = f"第 {index + 1} 段"
        if not isinstance(segment, Mapping):
            raise SchemaError(f"{where} 必须是表")
        _reject_extra(segment, SEGMENT_KEYS, where)
        name = segment.get("name")
        if not isinstance(name, str) or not name:
            raise SchemaError(f"{where} 缺段名 name")
        names.append(name)
        has_code, has_ops = "code" in segment, "ops" in segment
        if has_code and has_ops:
            raise SchemaError(f"{where}「{name}」不能同时有 code 与 ops")
        if not has_code and not has_ops:
            raise SchemaError(f"{where}「{name}」既没有 code 也没有 ops")
        if has_ops:
            _validate_ops(segment["ops"], f"{where}「{name}」")
    if len(set(names)) != len(names):
        raise SchemaError(f"段名重复：{names}；失败段与重试都按段名定位，必须唯一")


def _validate_ops(ops: object, where: str) -> None:
    if not isinstance(ops, list):
        raise SchemaError(f"{where} 的 ops 必须是数组")
    for index, op in enumerate(ops):
        _validate_op(op, f"{where} 第 {index + 1} 个 op")


def _validate_op(op: object, where: str) -> None:
    """一条 op：查记录、查键、查必填、跑形状校验、查实参块、递归子 op——顺序即报错顺序。"""
    if not isinstance(op, Mapping):
        raise SchemaError(f"{where} 必须是表")
    kind = op.get("kind")
    if kind not in OP_KINDS:
        raise SchemaError(f"{where} 的 kind={kind!r} 不在白名单里：{sorted(OP_KINDS)}")
    spec = OPS[kind]
    _reject_extra(op, spec.keys, where)
    for key in spec.required:
        _require(op, key, where)
    if spec.check is not None:
        spec.check(op, where)
    _validate_arg_blocks(op, where)
    for key in spec.nested:
        _validate_ops(op.get(key, []), where)


def words(data: Mapping) -> list[tuple[str, str]]:
    """把数据里「要关的 / 要留的」名单提成 (文本, 来源) 的清单，供词库按**名单来源**记账。

    来源两档：`literal`（内联 `only` / `keep` 的字面量）与 `strategy`（`only_code` 指向的本机策略名）。
    抽哪个键、算什么来源档写在 `OPS` 的 `word_keys` 里；值是列表就出多条、是字符串就出一条。
    这是 #1259 的最小实现——词库本体仍从脚本源码投影，本函数只让 catalog 数据也能按来源说出自己的词。
    """
    found: list[tuple[str, str]] = []
    for segment in data.get("segment", []):
        for op in _walk(segment.get("ops", [])):
            kind = op.get("kind")
            if not isinstance(kind, str) or kind not in OPS:
                continue
            spec = OPS[kind]
            for key, source in spec.word_keys:
                value = op.get(key)
                if isinstance(value, str):
                    found.append((value, source))
                elif isinstance(value, Sequence):
                    found += [(text, source) for text in value]
    return found


def _walk(ops: Sequence) -> list[Mapping]:
    """展开 ops（含 gated / scoped 子表），只保留 op 表本身。"""
    flat: list[Mapping] = []
    for op in ops:
        if not isinstance(op, Mapping):
            continue  # pragma: no mutate 不可达：words 只接经 validate 的页面树，ops 逐项都是表
        flat.append(op)
        flat += _walk(op.get("ops", []))
    return flat
