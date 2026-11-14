"""catalog 解释器：把页面树数据翻成对 `p` 的调用（ADR-0038）。

一条硬约束：每段的段体都包成一个 action，由 `recipe_runtime.Runtime.run_step` 执行，段归属钩子
`OBSERVER` 照样拿得到段名——13,484 条调用序列快照的段维靠它对齐。

页面算法一律复用，不新写：关一页走 `p.off()`（`plan_switches` / `readback` 不动），等页面走
`p.entry()` / `p.start()`（内部都是 `wait.until`），入口回落走 `entries.reach`（经库保留）。解释器
只把「该调哪个 p 方法、带哪些实参」按数据的书写顺序发出去，不碰这些算法本身。

库调用按名字解析：`lib` / `require_lib` / `if_lib` / `return_lib` 查本模块的 `LIBRARY`（三个库的
`__all__`），查不到再查本机例外命名空间；实现是普通函数，收 `(p, rt, …)`，调用序列与旧脚本逐条相同。
"""
from collections.abc import Callable, Mapping
from typing import Any

import recipe_nav
import recipe_strategies
import recipe_steps

# 数据可调用的实现：三个库的 `__all__`。`lib` / `require_lib` / `if_lib` / `return_lib` 按名字查这张表。
LIBRARY: dict[str, Callable[..., Any]] = {}
for _module in (recipe_nav, recipe_strategies, recipe_steps):
    for _name in _module.__all__:
        LIBRARY[_name] = getattr(_module, _name)


def _resolve(name: str, g: dict[str, Any]) -> Callable[..., Any]:
    """`lib` 的名字先查库，再查本机例外函数的命名空间（数据显式点名，不靠同名覆盖）。"""
    fn = LIBRARY.get(name)
    return fn if fn is not None else g[name]


class _Abort(Exception):
    """段内早退（`require_*` 没找到、`return` op）：停在当前段，剩下的 op 不再做。

    它不是失败：段体自己 `return` 也是这个结局（只影响分段落点，不影响退出码，沿用 #838）。
    在段 action 的边界被吞掉，不会漏到 `Runtime.run_step` 的失败分支。

    `value` 是段体的返回值：`return value=false` 与 `return_lib` 靠它把「这一段没做全」交给
    `Runtime.run_step`（`outcome is False` 记「未完成」），默认 None 与旧 `return` 逐字相同。
    """

    def __init__(self, value: Any = None) -> None:
        super().__init__()
        self.value = value


def segment_action(segment: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> Callable[[], Any]:
    """把一段声明包成段体 action：整段交给 `code=` 例外函数，或按 `ops` 逐个执行。"""
    if "code" in segment:
        function = g[segment["code"]]

        def run_code() -> Any:
            try:
                return function(p, rt)
            except _Abort as stop:
                return stop.value

        return run_code

    ops = segment.get("ops", [])

    def run_ops() -> Any:
        try:
            _run(ops, p, rt, g)
        except _Abort as stop:
            return stop.value
        return None

    return run_ops


def _run(ops: Any, p: Any, rt: Any, g: dict[str, Any]) -> None:
    for op in ops:
        _run_op(op, p, rt, g)


def _run_op(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    kind = op["kind"]
    handler = _HANDLERS[kind]
    handler(op, p, rt, g)


def _arg(value: Any, p: Any, rt: Any, g: dict[str, Any]) -> Any:
    """实参里的动态取值：`{expr = "focus"}` → `p.focus()`，`{expr = "tree"}` → `p.tree()`。

    段体常把当前前台 / 页面树当实参传给库助手（`close_named(..., p.focus())`）。这些读也是一次
    `p.*` 调用、进调用序列，所以必须照原样求值、不能换成字面量，否则对拍就少了那一条。除表形态外
    一律按字面量传（字符串 / 数字 / 列表）。"""
    if isinstance(value, Mapping) and "expr" in value:
        name = value["expr"]
        if name == "focus":
            return p.focus()
        if name == "tree":
            return p.tree()
        raise KeyError(f"未知的实参表达式 expr={name!r}")
    return value


def _lib(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    _resolve(op["name"], g)(p, rt, *[_arg(a, p, rt, g) for a in op.get("args", [])],
                  **{k: _arg(v, p, rt, g) for k, v in op.get("kwargs", {}).items()})


def _require_lib(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """本机策略返回假时按「这一段没做成」早退：先打现场，再回退，再停（沿用脚本里的写法）。

    `fail=true` 改成按这一段失败收尾（旧脚本 `raise RuntimeError` 的出口，进失败段台账）；
    `evidence=true` 把当次页面现场接在文案后面（`…；停在 …`）。"""
    result = _resolve(op["name"], g)(p, rt, *[_arg(a, p, rt, g) for a in op.get("args", [])],
                           **{k: _arg(v, p, rt, g) for k, v in op.get("kwargs", {}).items()})
    where = _focus_note(op, p, rt, g)
    if not result:
        message = _miss_message(op, p, g, where)
        if op.get("fail"):
            raise RuntimeError(message)
        print(message, flush=True)
        if op.get("miss_back"):
            p.back(op["miss_back"])
        raise _Abort


def _off(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """按实参是否出现原样下发：段体写 `p.off(only=…, page=…)` 就只带这两个键，调用序列才逐条一致。"""
    kwargs: dict[str, Any] = {"page": op["page"]}
    if "only_code" in op:
        kwargs["only"] = g[op["only_code"]](p, rt)
    elif "only" in op:
        kwargs["only"] = list(op["only"])
    if "keep" in op:
        kwargs["keep"] = list(op["keep"])
    if "max_screens" in op:
        kwargs["max_screens"] = op["max_screens"]
    done = p.off(**kwargs)
    if isinstance(done, int):
        # `Toggler.off()` 的返回值是回读确认到目标态的条数（它只在回读给出 reached / vanished
        # 之后才 +1），正好是 `rt.confirm()` 要的那一个数，不是「扫过几项」。
        rt.confirm(done)


def _close_all(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """UI 上的「全部关闭」按钮：单列一种动作，登记为 page-wide。

    安全模式下整页全关不点（只关点名的开关，沿用 ADR-0008 / #909）：出口就是 `rt.skip_in_safe_mode()`，
    跳过原因只在那里定义，不在解释器里另抄一份。
    """
    rt.skip_in_safe_mode()
    page = p
    page.tap(op.get("button", "全部关闭"), exact=True)
    page.confirm()


def _start(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    args = [op["pkg"]]
    kwargs: dict[str, Any] = {}
    if "activity" in op:
        args.append(op["activity"])
    for key in ("settle", "foreground", "expect", "budget"):
        if key in op:
            kwargs[key] = op[key]
    p.start(*args, **kwargs)


def _start_or_skip(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`start_or_skip(pkg, activity, dead_ends=…, reason=…)`：落点被系统转去别处时按跳过收尾。"""
    rt.start_or_skip(op["pkg"], op["activity"], dead_ends=_arg(op["dead_ends"], p, rt, g),
                       reason=op["reason"])


def _skip_unless_installed(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`if marker not in p.d.shell(command).output: print(text); return`：本机没装这个包就整段收尾（完成）。"""
    output = p.d.shell(op["command"]).output
    if op["contains"] not in output:
        print(op["text"], flush=True)
        raise _Abort


def _await_page(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.await_page()


def _entry(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.entry(op["text"], scrolls=op.get("scrolls", 6))


def _enter(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`p.enter(text, scrolls=…)`：只带数据里写了的实参，调用序列才与旧脚本逐条一致。"""
    if "scrolls" in op:
        p.enter(op["text"], scrolls=op["scrolls"])
    else:
        p.enter(op["text"])


def _require_entry(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    if not p.entry(op["text"], scrolls=op.get("scrolls", 6)):
        print(op["miss_print"], flush=True)
        if op.get("miss_back"):
            p.back(op["miss_back"])
        raise _Abort


def _gated(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """逐个认入口（`p.entry`），任一个认不出就跳过整块（对应 `if maybe(A) and maybe(B): …`）。"""
    scrolls = op.get("scrolls", 6)
    for text in op["entries"]:
        if not p.entry(text, scrolls=scrolls):
            return
    _run(op.get("ops", []), p, rt, g)


def _scoped(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """作用域内设一个页面属性、退出恢复（对应段体里的 try/finally，例如锁屏页的 `systemui_text`）。"""
    page = p
    saved = {}
    if "systemui_text" in op:
        saved["systemui_text"] = page.systemui_text
        page.systemui_text = op["systemui_text"]
    try:
        _run(op.get("ops", []), p, rt, g)
    finally:
        for name, value in saved.items():
            setattr(page, name, value)


def _back(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    if "n" in op:
        p.back(op["n"])
    else:
        p.back()


def _top(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.top(op.get("n"))


def _code(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    g[op["name"]](p, rt, *[_arg(a, p, rt, g) for a in op.get("args", [])])


def _page(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`page(title, …)` 落点三段判据：实参照 `lib` 的样子原样下发，位置/关键字逐条保真（#1265）。"""
    rt.page(*[_arg(a, p, rt, g) for a in op.get("args", [])],
              **{k: _arg(v, p, rt, g) for k, v in op.get("kwargs", {}).items()})


def _skip(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """按约定跳过这一段：交给注入的 `skip`，它抛命名空间的跳过类，结局记「跳过」（#1265）。"""
    rt.skip(op["text"])


def _fail(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """这一段失败并带一句原因：走注入的 `require`（抛 RuntimeError），结局「未完成」且进失败段台账（#1265）。

    与 `return value=false` 的区别：后者只改分段结局、不进 `failed_steps`；旧脚本用 `raise` 的失败出口
    要进台账（重试按失败段定位），用这条。`evidence=true` 接上页面现场，与
    `raise RuntimeError("…；" + p.page_evidence())` 同形（只在真走到失败时读，#1267）。"""
    text = op["text"] + p.page_evidence() if op.get("evidence") else op["text"]
    rt.require(False, text)


def _print(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    print(op["text"], flush=True)


def _return(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`return` / `return False`：段的结局由 `value` 定，没写就与旧 `return` 一样（完成）。"""
    raise _Abort(op.get("value"))


def _return_lib(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`return <库助手>(…)`：段的结局就是这个调用的返回值（假时记「未完成」，与段体 `return` 同档）。"""
    result = _resolve(op["name"], g)(p, rt, *[_arg(a, p, rt, g) for a in op.get("args", [])],
                           **{k: _arg(v, p, rt, g) for k, v in op.get("kwargs", {}).items()})
    if not result:
        raise _Abort(False)


def _if_focus(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`if p.focus() <比法> text: … else: …`：`match` 明写 equals / starts / contains，缺省 contains。"""
    where = p.focus()
    match = op.get("match", "contains")
    hit = {"equals": where == op["text"],
           "starts": where.startswith(op["text"]),
           "contains": op["text"] in where,
           "icontains": op["text"].lower() in where.lower()}[match]
    _run(op.get("ops", []) if hit else op.get("else_ops", []), p, rt, g)


def _shell(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """不经门面的读屏命令（`p.d.shell`）：拉起设置页、`input swipe`、`getprop` 这类原样下发。"""
    p.d.shell(op["command"])


def _sleep(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    rt.clock.sleep(op["seconds"])


def _press(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.d.press(op["key"])


def _app_stop(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.d.app_stop(op["pkg"])


def _note_miss(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.note_miss(op["text"])


def _miss_reset(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.miss = 0


def _require_unlocked(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    if p.locked():
        raise RuntimeError(op.get("miss_print", "手机锁屏，请机主解锁"))


def _focus_note(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> str | None:
    """`at_focus=true` 时先读一次前台，返回它；不写则返回 None。

    老脚本把现场写进 require 的**实参**（`require(cond, f"…；停在 {p.focus()}")`），前台是无论成败
    都先读的。这里保持同样的时机：先读、再判定。"""
    return p.focus() if op.get("at_focus") else None


def _miss_message(op: Mapping, p: Any, g: dict[str, Any], where: str | None = None) -> str:
    """失败文案的两种现场尾巴，与旧脚本两种写法对应。

    `evidence=true` 接上 `p.page_evidence()`（`…；+ p.page_evidence()` 同形）；`at_focus` 的读数由
    调用方先取好（`_focus_note`），成 `…；停在 <前台>`。两者都不写时只有文案。"""
    message = op["miss_print"]
    if op.get("evidence"):
        message += p.page_evidence()
    if where is not None:
        message += "；停在 " + where
    return message


def _require_tab(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    result = p.tab(op["name"])
    where = _focus_note(op, p, rt, g)
    if not result:
        raise RuntimeError(_miss_message(op, p, g, where))


def _require_go(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    result = p.go(op["text"], op["expect"])
    where = _focus_note(op, p, rt, g)
    if not result:
        raise RuntimeError(_miss_message(op, p, g, where))


def _tap(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    kwargs: dict[str, Any] = {}
    for key in ("exact", "scrolls"):
        if key in op:
            kwargs[key] = op[key]
    kwargs.update(op.get("kwargs", {}))
    p.tap(op["text"], **kwargs)


def _go(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.go(op["text"], op["expect"])


def _dismiss(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    p.dismiss()


def _skip_in_safe_mode(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    rt.skip_in_safe_mode()


def _require_setting(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    args = [op["kw"]]
    if "entry" in op:
        args.append(op["entry"])
    if not p.setting(*args):
        raise RuntimeError(op["miss_print"])


def _require_tap(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`require(p.tap(text, exact=…, scrolls=…), 文案)`：点不到就按这一段失败（#1265）。"""
    kwargs: dict[str, Any] = {}
    for key in ("exact", "scrolls"):
        if key in op:
            kwargs[key] = op[key]
    result = p.tap(op["text"], **kwargs)
    where = _focus_note(op, p, rt, g)
    if not result:
        raise RuntimeError(_miss_message(op, p, g, where))


def _close_listed(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """读回这一页的开关 → 只留点名的、页上真有的行 → 整表关（#1265）。

    与旧脚本逐字同形：`read_switches(page)` → 按候选名单过滤 → 空的按失败收尾 → `close_named`。"""
    available = LIBRARY["read_switches"](p, rt, op["page"])
    names = [name for name in op["names"] if name in available]
    rt.require(names, op["miss_print"])
    close = (LIBRARY["close_named_optional"] if rt.constants.get("CLOSE_NAMED_OPTIONAL")
             else LIBRARY["close_named"])
    close(p, rt, names, op["page"], snapshot=available)


def _off_required(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """跨两屏把这一页的开关读齐 → 回页顶 → 点名断言都在（缺了带现场失败）→ 点名关（#1266）。

    与旧脚本逐字同形：`before = {}` / `for _ in range(2): …switches(); if not scroll_more(): break` /
    `p.top(2)` / `require_switches(before, only, page, contains=…)` / `p.off(only=…, keep=…, page=…)`。"""
    page = p
    before: dict[str, Any] = {}
    for _ in range(2):
        before.update({title: on for title, on, _ in page.switches()})
        if not page.scroll_more():
            break
    page.top(2)
    rt.require_switches(before, list(op["only"]), op["page"], contains=op.get("contains", False))
    kwargs: dict[str, Any] = {"only": list(op["only"]), "page": op["page"]}
    if "keep" in op:
        kwargs["keep"] = list(op["keep"])
    done = page.off(**kwargs)
    if isinstance(done, int):
        rt.confirm(done)


def _require_focus(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`require("<片段>" in p.focus(), 文案)`：读一次前台再断言，前台读取照旧进调用序列。"""
    rt.require(op["contains"] in p.focus(), op["miss_print"])


def _require_find(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`require(p.find(text, exact=…), 文案)`：找一次再断言。"""
    kwargs: dict[str, Any] = {}
    if "exact" in op:
        kwargs["exact"] = op["exact"]
    rt.require(p.find(op["text"], **kwargs), op["miss_print"])


def _if_find(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`if p.find(text, exact=…[, edge_ok=…][, nav=…]): … else …`。"""
    kwargs: dict[str, Any] = {}
    for key in ("exact", "edge_ok", "nav"):
        if key in op:
            kwargs[key] = op[key]
    if p.find(op["text"], **kwargs):
        _run(op.get("ops", []), p, rt, g)
    else:
        _run(op.get("else_ops", []), p, rt, g)


def _if_tap(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`if p.tap(text, exact=…, scrolls=…): … else: …`：门面自己的返回值决定走哪支。"""
    kwargs: dict[str, Any] = {}
    for key in ("exact", "scrolls"):
        if key in op:
            kwargs[key] = op[key]
    if p.tap(op["text"], **kwargs):
        _run(op.get("ops", []), p, rt, g)
    else:
        _run(op.get("else_ops", []), p, rt, g)


def _if_entry(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`if p.entry(text, scrolls=…): … else …`（与 `gated` 的区别是带 else 分支）。"""
    if p.entry(op["text"], scrolls=op.get("scrolls", 6)):
        _run(op.get("ops", []), p, rt, g)
    else:
        _run(op.get("else_ops", []), p, rt, g)


def _if_lib(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`if <库助手>(…): … else …`（如 `if tap_row("消息提醒"): …`）。返回值决定走哪支。"""
    if _resolve(op["name"], g)(p, rt, *[_arg(a, p, rt, g) for a in op.get("args", [])],
                     **{k: _arg(v, p, rt, g) for k, v in op.get("kwargs", {}).items()}):
        _run(op.get("ops", []), p, rt, g)
    else:
        _run(op.get("else_ops", []), p, rt, g)


def _if_setting(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`if p.setting(kw[, entry]): … else …`：设置搜索直达的成败决定走哪一支（#1267）。"""
    args = [op["kw"]] + ([op["entry"]] if "entry" in op else [])
    if p.setting(*args):
        _run(op.get("ops", []), p, rt, g)
    else:
        _run(op.get("else_ops", []), p, rt, g)


def _if_lib_any(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`<助手A>(…) or <助手B>(…)`：短路取第一个成功的助手（#1267）。

    旧脚本用 `or` 串入口助手（`gear(toolbar_only=True) or gear()`），短路链里也会混门面的布尔方法
    （`tab_bot("我的") or p.tap("我的", …)`）：第一个成真时后面的不调，调用序列与旧脚本逐条相同。"""
    for call in op["calls"]:
        target = getattr(p, call["method"]) if "method" in call else _resolve(call["name"], g)
        if target(*([] if "method" in call else [p, rt]) + [_arg(a, p, rt, g) for a in call.get("args", [])],
                  **{k: _arg(v, p, rt, g) for k, v in call.get("kwargs", {}).items()}):
            _run(op.get("ops", []), p, rt, g)
            return
    _run(op.get("else_ops", []), p, rt, g)


def _require_expect(op: Mapping, p: Any, rt: Any, g: dict[str, Any]) -> None:
    """`require(p.expect_page(…), 文案)`：几个调用短路 OR，全落空按这一段失败收尾（#1267）。

    实参按数据里的形态原样下发（位置 / 关键字不合并）：旧脚本既有
    `p.expect_page("x", 3)` 也有 `p.expect_page("x", timeout=3)`，两条都要逐条对上。"""
    page = p
    hit = False
    for call in op["calls"]:
        kwargs = {k: _arg(v, p, rt, g) for k, v in call.get("kwargs", {}).items()}
        if page.expect_page(*[_arg(a, p, rt, g) for a in call["args"]], **kwargs):
            hit = True
            break
    where = _focus_note(op, p, rt, g)
    if not hit:
        raise RuntimeError(_miss_message(op, p, g, where))


_HANDLERS: dict[str, Callable[[Mapping, Any, Any, dict[str, Any]], None]] = {
    "lib": _lib,
    "require_lib": _require_lib,
    "off": _off,
    "close_all": _close_all,
    "start": _start,
    "start_or_skip": _start_or_skip,
    "skip_unless_installed": _skip_unless_installed,
    "await_page": _await_page,
    "off_required": _off_required,
    "entry": _entry,
    "enter": _enter,
    "if_focus": _if_focus,
    "if_tap": _if_tap,
    "return_lib": _return_lib,
    "require_entry": _require_entry,
    "gated": _gated,
    "scoped": _scoped,
    "back": _back,
    "top": _top,
    "page": _page,
    "skip": _skip,
    "fail": _fail,
    "code": _code,
    "print": _print,
    "return": _return,
    "shell": _shell,
    "sleep": _sleep,
    "press": _press,
    "app_stop": _app_stop,
    "note_miss": _note_miss,
    "miss_reset": _miss_reset,
    "require_unlocked": _require_unlocked,
    "require_tab": _require_tab,
    "require_tap": _require_tap,
    "close_listed": _close_listed,
    "require_go": _require_go,
    "tap": _tap,
    "go": _go,
    "dismiss": _dismiss,
    "skip_in_safe_mode": _skip_in_safe_mode,
    "require_setting": _require_setting,
    "require_focus": _require_focus,
    "require_find": _require_find,
    "if_find": _if_find,
    "if_entry": _if_entry,
    "if_lib": _if_lib,
    "if_lib_any": _if_lib_any,
    "if_setting": _if_setting,
    "require_expect": _require_expect,
}
