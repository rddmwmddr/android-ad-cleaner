"""catalog 数据的 schema 与校验（ADR-0038）：种类白名单，未知键直接报错。

schema 只装机型知识（有哪些页面、有哪些行、怎么进去、关哪些、留哪些）；编排语义（重试、收尾、
失败收集、台账、页面快照）不进数据，归运行时。校验器与解释器共用同一份装载入口（`catalog.load`），
所以这里只判定「数据是不是合法的页面树」，不执行任何设备动作。

封闭清单：顶层键、段的键、每种 op 的键都写死在这里，出现名单外的键即 `SchemaError`。扩展一种新
知识要先在这里登记，判据是「≥2 机型用法」，不是数字上限（ADR-0038）。
"""
from collections.abc import Mapping, Sequence

# 顶层允许的键：身份（model / models / build）、四个可选钩子的名字（指向该机例外函数），以及段表。
TOP_KEYS = frozenset({"model", "models", "build", "const", "tail", "guard", "detail", "wrap", "segment"})
# 一段要么 `code = "<本机策略名>"`（整段交给例外函数），要么给一串 `ops`；两者只能选一个。
SEGMENT_KEYS = frozenset({"name", "code", "ops"})

# 每种 op 允许的键。白名单：出现名单外的键即报错。
OP_KEYS = {
    "lib": frozenset({"kind", "name", "args", "kwargs"}),
    "off": frozenset({"kind", "only", "only_code", "keep", "page", "max_screens", "page_wide"}),
    "off_required": frozenset({"kind", "only", "keep", "page", "contains"}),
    "close_all": frozenset({"kind", "page", "button"}),
    "close_listed": frozenset({"kind", "names", "page", "miss_print"}),
    "start": frozenset({"kind", "pkg", "activity", "settle", "foreground", "expect", "budget"}),
    "start_or_skip": frozenset({"kind", "pkg", "activity", "dead_ends", "reason"}),
    "skip_unless_installed": frozenset({"kind", "command", "contains", "text"}),
    "await_page": frozenset({"kind"}),
    "entry": frozenset({"kind", "text", "scrolls"}),
    "enter": frozenset({"kind", "text", "scrolls"}),
    "gated": frozenset({"kind", "entries", "scrolls", "ops"}),
    "require_entry": frozenset({"kind", "text", "scrolls", "miss_print", "miss_back"}),
    "require_lib": frozenset({"kind", "name", "args", "kwargs", "miss_print", "miss_back",
                              "fail", "evidence", "at_focus"}),
    "require_tab": frozenset({"kind", "name", "miss_print", "evidence", "at_focus"}),
    "require_tap": frozenset({"kind", "text", "exact", "scrolls", "miss_print", "evidence",
                              "at_focus"}),
    "require_go": frozenset({"kind", "text", "expect", "miss_print", "evidence", "at_focus"}),
    "require_expect": frozenset({"kind", "calls", "miss_print", "evidence", "at_focus"}),
    "require_unlocked": frozenset({"kind", "miss_print"}),
    "shell": frozenset({"kind", "command"}),
    "sleep": frozenset({"kind", "seconds"}),
    "press": frozenset({"kind", "key"}),
    "app_stop": frozenset({"kind", "pkg"}),
    "note_miss": frozenset({"kind", "text"}),
    "miss_reset": frozenset({"kind"}),
    "tap": frozenset({"kind", "text", "exact", "scrolls", "kwargs"}),
    "go": frozenset({"kind", "text", "expect"}),
    "dismiss": frozenset({"kind"}),
    "skip_in_safe_mode": frozenset({"kind"}),
    "require_setting": frozenset({"kind", "kw", "entry", "miss_print"}),
    "require_focus": frozenset({"kind", "contains", "miss_print"}),
    "require_find": frozenset({"kind", "text", "exact", "miss_print"}),
    "if_find": frozenset({"kind", "text", "exact", "edge_ok", "nav", "ops", "else_ops"}),
    "if_entry": frozenset({"kind", "text", "scrolls", "ops", "else_ops"}),
    "if_lib": frozenset({"kind", "name", "args", "kwargs", "ops", "else_ops"}),
    "if_lib_any": frozenset({"kind", "calls", "ops", "else_ops"}),
    "if_setting": frozenset({"kind", "kw", "entry", "ops", "else_ops"}),
    "if_focus": frozenset({"kind", "text", "match", "ops", "else_ops"}),
    "if_tap": frozenset({"kind", "text", "exact", "scrolls", "ops", "else_ops"}),
    "back": frozenset({"kind", "n"}),
    "top": frozenset({"kind", "n"}),
    "page": frozenset({"kind", "args", "kwargs"}),
    "skip": frozenset({"kind", "text"}),
    "fail": frozenset({"kind", "text", "evidence"}),
    "scoped": frozenset({"kind", "systemui_text", "ops"}),
    "code": frozenset({"kind", "name", "args"}),
    "print": frozenset({"kind", "text"}),
    "return": frozenset({"kind", "value"}),
    "return_lib": frozenset({"kind", "name", "args", "kwargs"}),
}
OP_KINDS = frozenset(OP_KEYS)

# `if_focus` 的比法：前台窗口原文与数据里的 text 怎么比。缺省 contains（与 `require_focus` 同档）。
FOCUS_MATCHES = frozenset({"equals", "starts", "contains", "icontains"})


class SchemaError(ValueError):
    """数据不合法：缺键、多了名单外的键、`only` 与 `keep` 重叠之类。装载期就报，不等真机。"""


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
    if not isinstance(op, Mapping):
        raise SchemaError(f"{where} 必须是表")
    kind = op.get("kind")
    if kind not in OP_KINDS:
        raise SchemaError(f"{where} 的 kind={kind!r} 不在白名单里：{sorted(OP_KINDS)}")
    _reject_extra(op, OP_KEYS[kind], where)
    if kind == "off":
        _validate_off(op, where)
    elif kind == "off_required":
        _validate_off_required(op, where)
    elif kind == "close_all":
        _require(op, "page", where)
    elif kind == "page":
        _require(op, "args", where)
    elif kind == "skip":
        _require(op, "text", where)
    elif kind == "fail":
        _require(op, "text", where)
    elif kind in ("lib", "require_lib", "code", "return_lib"):
        _require(op, "name", where)
        if kind == "require_lib":
            _require(op, "miss_print", where)
    elif kind in ("entry", "require_entry", "enter"):
        _require(op, "text", where)
        if kind == "require_entry":
            _require(op, "miss_print", where)
    elif kind == "require_tab":
        _require(op, "name", where)
        _require(op, "miss_print", where)
    elif kind == "require_tap":
        _require(op, "text", where)
        _require(op, "miss_print", where)
    elif kind == "close_listed":
        _require(op, "names", where)
        _require(op, "page", where)
        _require(op, "miss_print", where)
    elif kind == "require_go":
        _require(op, "text", where)
        _require(op, "expect", where)
        _require(op, "miss_print", where)
    elif kind == "shell":
        _require(op, "command", where)
    elif kind == "sleep":
        _require(op, "seconds", where)
    elif kind == "press":
        _require(op, "key", where)
    elif kind == "app_stop":
        _require(op, "pkg", where)
    elif kind == "note_miss":
        _require(op, "text", where)
    elif kind == "tap":
        _require(op, "text", where)
    elif kind == "go":
        _require(op, "text", where)
        _require(op, "expect", where)
    elif kind == "require_setting":
        _require(op, "kw", where)
        _require(op, "miss_print", where)
    elif kind == "if_setting":
        _require(op, "kw", where)
        _validate_ops(op.get("ops", []), where)
        _validate_ops(op.get("else_ops", []), where)
    elif kind == "require_expect":
        _validate_calls(op, where, ("args", "kwargs"), required="args")
        _require(op, "miss_print", where)
    elif kind == "if_lib_any":
        _validate_calls(op, where, ("name", "method", "args", "kwargs"), required=("name", "method"))
        _validate_ops(op.get("ops", []), where)
        _validate_ops(op.get("else_ops", []), where)
    elif kind == "require_focus":
        _require(op, "contains", where)
        _require(op, "miss_print", where)
    elif kind == "require_find":
        _require(op, "text", where)
        _require(op, "miss_print", where)
    elif kind in ("if_find", "if_entry", "if_focus", "if_tap"):
        _require(op, "text", where)
        if kind == "if_focus" and op.get("match", "contains") not in FOCUS_MATCHES:
            raise SchemaError(f"{where} 的 match={op['match']!r} 认不出；可用的是 "
                              f"{sorted(FOCUS_MATCHES)}")
        _validate_ops(op.get("ops", []), where)
        _validate_ops(op.get("else_ops", []), where)
    elif kind == "if_lib":
        _require(op, "name", where)
        _validate_ops(op.get("ops", []), where)
        _validate_ops(op.get("else_ops", []), where)
    elif kind == "start":
        _require(op, "pkg", where)
    elif kind == "start_or_skip":
        for key in ("pkg", "activity", "dead_ends", "reason"):
            _require(op, key, where)
    elif kind == "skip_unless_installed":
        for key in ("command", "contains", "text"):
            _require(op, key, where)
    elif kind == "gated":
        entries = op.get("entries")
        if not isinstance(entries, list) or not entries:
            raise SchemaError(f"{where} 的 gated 需要非空的 entries")
        _validate_ops(op.get("ops", []), where)
    elif kind == "scoped":
        _validate_ops(op.get("ops", []), where)
    elif kind == "return" and "value" in op and not isinstance(op["value"], bool):
        raise SchemaError(f"{where} 的 value 只能是 true / false（段的结局）")


def _validate_off(op: Mapping, where: str) -> None:
    """`off` 三种形态：内联字面量 `only` / `only_code` 指向本机策略 / 都不给 = 整页全关（`p.off` 无 only）。

    `only` 与 `only_code` 是「点名」（安全模式不抑制）；都不给时按 `p.off(page=…)` 的整页全关，与
    UI 按钮式的 `close_all` 是两条不同的路（前者是引擎的 plan_switches 没有 only，后者点屏幕上的按钮）。"""
    _require(op, "page", where)
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
    _require(op, "only", where)
    _require(op, "page", where)
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
            present = [key for key in required if key in call]
            if len(present) != 1:
                raise SchemaError(f"{place} 要给「{' / '.join(required)}」里的恰好一个")
        elif required not in call:
            raise SchemaError(f"{place} 缺 {required}")
        if "args" in call and (not isinstance(call["args"], list) or not call["args"]):
            raise SchemaError(f"{place} 的 args 必须是非空数组")
        if required == "args" and not isinstance(call.get("args"), list):
            raise SchemaError(f"{place} 的 args 必须是数组")


def _require(op: Mapping, key: str, where: str) -> None:
    if key not in op:
        raise SchemaError(f"{where} 缺 {key}")


def _reject_extra(op: Mapping, allowed: frozenset, where: str) -> None:
    extra = set(op) - allowed
    if extra:
        raise SchemaError(f"{where} 出现名单外的键：{sorted(extra)}；允许的是 {sorted(allowed)}")


def words(data: Mapping) -> list[tuple[str, str]]:
    """把数据里「要关的 / 要留的」名单提成 (文本, 来源) 的清单，供词库按**名单来源**记账。

    来源两档：`literal`（内联 `only` / `keep` 的字面量）与 `strategy`（`only_code` 指向的本机策略名）。
    这是 #1259 的最小实现——词库本体仍从脚本源码投影，本函数只让 catalog 数据也能按来源说出自己的词。
    """
    found: list[tuple[str, str]] = []
    for segment in data.get("segment", []):
        for op in _walk(segment.get("ops", [])):
            kind = op.get("kind")
            if kind in ("off", "off_required"):
                if "only" in op:
                    found += [(text, "literal") for text in op["only"]]
                elif "only_code" in op:
                    found.append((op["only_code"], "strategy"))
                found += [(text, "literal") for text in op.get("keep", [])]
            elif kind == "close_listed":
                # 「读回名单→过滤→整表关」的候选名单也是「这一页要关的名字」，与 `close_named` 同档（#1265）。
                found += [(text, "literal") for text in op.get("names", [])]
    return found


def _walk(ops: Sequence) -> list[Mapping]:
    """展开 ops（含 gated / scoped 子表），只保留 op 表本身。"""
    flat: list[Mapping] = []
    for op in ops:
        if not isinstance(op, Mapping):
            continue
        flat.append(op)
        flat += _walk(op.get("ops", []))
    return flat
