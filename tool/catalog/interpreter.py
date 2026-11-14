"""catalog 解释器：把页面树数据翻成对 `p` 的调用（ADR-0038）。

一条硬约束：每段的段体都包成一个 action，由 `recipe_runtime.Runtime.run_step` 执行，段归属钩子
`OBSERVER` 照样拿得到段名——13,484 条调用序列快照的段维靠它对齐。

页面算法一律复用，不新写：关一页走 `p.off()`（`plan_switches` / `readback` 不动），等页面走
`p.entry()` / `p.start()`（内部都是 `wait.until`），入口回落走 `entries.reach`（经库保留）。解释器
只把「该调哪个 p 方法、带哪些实参」按数据的书写顺序发出去，不碰这些算法本身。

复用注入面：迁移期 `settings_home` / `my_tab` / `tap_row` / `off_one` 等仍是 `NAV` / `STEPS` /
`STRATEGIES` 的工厂 `(p, g) -> closure`。装载器已经把 `g` 喂给 `recipe_kit.preamble()`，`lib` /
`require_lib` 就按名字从 `g` 里取那份闭包直接调——调用序列因此与旧脚本逐条相同。
"""
from collections.abc import Callable, Mapping
from typing import Any


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


def segment_action(segment: Mapping, g: dict[str, Any]) -> Callable[[], Any]:
    """把一段声明包成段体 action：整段交给 `code=` 例外函数，或按 `ops` 逐个执行。"""
    if "code" in segment:
        function = g[segment["code"]]

        def run_code() -> Any:
            try:
                return function(g["p"], g["rt"])
            except _Abort as stop:
                return stop.value

        return run_code

    ops = segment.get("ops", [])

    def run_ops() -> Any:
        try:
            _run(ops, g)
        except _Abort as stop:
            return stop.value
        return None

    return run_ops


def _run(ops: Any, g: dict[str, Any]) -> None:
    for op in ops:
        _run_op(op, g)


def _run_op(op: Mapping, g: dict[str, Any]) -> None:
    kind = op["kind"]
    handler = _HANDLERS[kind]
    handler(op, g)


def _arg(value: Any, g: dict[str, Any]) -> Any:
    """实参里的动态取值：`{expr = "focus"}` → `p.focus()`，`{expr = "tree"}` → `p.tree()`。

    段体常把当前前台 / 页面树当实参传给库助手（`close_named(..., p.focus())`）。这些读也是一次
    `p.*` 调用、进调用序列，所以必须照原样求值、不能换成字面量，否则对拍就少了那一条。除表形态外
    一律按字面量传（字符串 / 数字 / 列表）。"""
    if isinstance(value, Mapping) and "expr" in value:
        name = value["expr"]
        if name == "focus":
            return g["p"].focus()
        if name == "tree":
            return g["p"].tree()
        raise KeyError(f"未知的实参表达式 expr={name!r}")
    return value


def _lib(op: Mapping, g: dict[str, Any]) -> None:
    g[op["name"]](*[_arg(a, g) for a in op.get("args", [])],
                  **{k: _arg(v, g) for k, v in op.get("kwargs", {}).items()})


def _require_lib(op: Mapping, g: dict[str, Any]) -> None:
    """本机策略返回假时按「这一段没做成」早退：先打现场，再回退，再停（沿用脚本里的写法）。

    `fail=true` 改成按这一段失败收尾（旧脚本 `raise RuntimeError` 的出口，进失败段台账）；
    `evidence=true` 把当次页面现场接在文案后面（`…；停在 …`）。"""
    result = g[op["name"]](*[_arg(a, g) for a in op.get("args", [])],
                           **{k: _arg(v, g) for k, v in op.get("kwargs", {}).items()})
    if not result:
        message = _miss_message(op, g)
        if op.get("fail"):
            raise RuntimeError(message)
        print(message, flush=True)
        if op.get("miss_back"):
            g["p"].back(op["miss_back"])
        raise _Abort


def _off(op: Mapping, g: dict[str, Any]) -> None:
    """按实参是否出现原样下发：段体写 `p.off(only=…, page=…)` 就只带这两个键，调用序列才逐条一致。"""
    kwargs: dict[str, Any] = {"page": op["page"]}
    if "only_code" in op:
        kwargs["only"] = g[op["only_code"]]()
    elif "only" in op:
        kwargs["only"] = list(op["only"])
    if "keep" in op:
        kwargs["keep"] = list(op["keep"])
    if "max_screens" in op:
        kwargs["max_screens"] = op["max_screens"]
    g["p"].off(**kwargs)


def _close_all(op: Mapping, g: dict[str, Any]) -> None:
    """UI 上的「全部关闭」按钮：单列一种动作，登记为 page-wide。

    安全模式下整页全关不点（只关点名的开关，沿用 ADR-0008 / #909），与 `skip_in_safe_mode` 同一判据。
    """
    rt = g["rt"]
    if rt.safe_mode:
        rt.skip("安全模式不做整页全关：本段没有可点名的开关，请按清单手动关")
        return
    page = g["p"]
    page.tap(op.get("button", "全部关闭"), exact=True)
    page.confirm()


def _start(op: Mapping, g: dict[str, Any]) -> None:
    args = [op["pkg"]]
    kwargs: dict[str, Any] = {}
    if "activity" in op:
        args.append(op["activity"])
    for key in ("settle", "foreground", "expect", "budget"):
        if key in op:
            kwargs[key] = op[key]
    g["p"].start(*args, **kwargs)


def _start_or_skip(op: Mapping, g: dict[str, Any]) -> None:
    """`start_or_skip(pkg, activity, dead_ends=…, reason=…)`：落点被系统转去别处时按跳过收尾。"""
    g["start_or_skip"](op["pkg"], op["activity"], dead_ends=_arg(op["dead_ends"], g),
                       reason=op["reason"])


def _skip_unless_installed(op: Mapping, g: dict[str, Any]) -> None:
    """`if marker not in p.d.shell(command).output: print(text); return`：本机没装这个包就整段收尾（完成）。"""
    output = g["p"].d.shell(op["command"]).output
    if op["contains"] not in output:
        print(op["text"], flush=True)
        raise _Abort


def _await_page(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].await_page()


def _entry(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].entry(op["text"], scrolls=op.get("scrolls", 6))


def _enter(op: Mapping, g: dict[str, Any]) -> None:
    """`p.enter(text, scrolls=…)`：只带数据里写了的实参，调用序列才与旧脚本逐条一致。"""
    if "scrolls" in op:
        g["p"].enter(op["text"], scrolls=op["scrolls"])
    else:
        g["p"].enter(op["text"])


def _require_entry(op: Mapping, g: dict[str, Any]) -> None:
    if not g["p"].entry(op["text"], scrolls=op.get("scrolls", 6)):
        print(op["miss_print"], flush=True)
        if op.get("miss_back"):
            g["p"].back(op["miss_back"])
        raise _Abort


def _gated(op: Mapping, g: dict[str, Any]) -> None:
    """逐个认入口（`p.entry`），任一个认不出就跳过整块（对应 `if maybe(A) and maybe(B): …`）。"""
    scrolls = op.get("scrolls", 6)
    for text in op["entries"]:
        if not g["p"].entry(text, scrolls=scrolls):
            return
    _run(op.get("ops", []), g)


def _scoped(op: Mapping, g: dict[str, Any]) -> None:
    """作用域内设一个页面属性、退出恢复（对应段体里的 try/finally，例如锁屏页的 `systemui_text`）。"""
    page = g["p"]
    saved = {}
    if "systemui_text" in op:
        saved["systemui_text"] = page.systemui_text
        page.systemui_text = op["systemui_text"]
    try:
        _run(op.get("ops", []), g)
    finally:
        for name, value in saved.items():
            setattr(page, name, value)


def _back(op: Mapping, g: dict[str, Any]) -> None:
    if "n" in op:
        g["p"].back(op["n"])
    else:
        g["p"].back()


def _top(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].top(op.get("n"))


def _code(op: Mapping, g: dict[str, Any]) -> None:
    g[op["name"]](*[_arg(a, g) for a in op.get("args", [])])


def _page(op: Mapping, g: dict[str, Any]) -> None:
    """`page(title, …)` 落点三段判据：实参照 `lib` 的样子原样下发，位置/关键字逐条保真（#1265）。"""
    g["page"](*[_arg(a, g) for a in op.get("args", [])],
              **{k: _arg(v, g) for k, v in op.get("kwargs", {}).items()})


def _skip(op: Mapping, g: dict[str, Any]) -> None:
    """按约定跳过这一段：交给注入的 `skip`，它抛命名空间的跳过类，结局记「跳过」（#1265）。"""
    g["skip"](op["text"])


def _fail(op: Mapping, g: dict[str, Any]) -> None:
    """这一段失败并带一句原因：走注入的 `require`（抛 RuntimeError），结局「未完成」且进失败段台账（#1265）。

    与 `return value=false` 的区别：后者只改分段结局、不进 `failed_steps`；旧脚本用 `raise` 的失败出口
    要进台账（重试按失败段定位），用这条。"""
    g["require"](False, op["text"])


def _print(op: Mapping, g: dict[str, Any]) -> None:
    print(op["text"], flush=True)


def _return(op: Mapping, g: dict[str, Any]) -> None:
    """`return` / `return False`：段的结局由 `value` 定，没写就与旧 `return` 一样（完成）。"""
    raise _Abort(op.get("value"))


def _return_lib(op: Mapping, g: dict[str, Any]) -> None:
    """`return <库助手>(…)`：段的结局就是这个调用的返回值（假时记「未完成」，与段体 `return` 同档）。"""
    result = g[op["name"]](*[_arg(a, g) for a in op.get("args", [])],
                           **{k: _arg(v, g) for k, v in op.get("kwargs", {}).items()})
    if not result:
        raise _Abort(False)


def _if_focus(op: Mapping, g: dict[str, Any]) -> None:
    """`if p.focus() <比法> text: … else: …`：`match` 明写 equals / starts / contains，缺省 contains。"""
    where = g["p"].focus()
    match = op.get("match", "contains")
    hit = {"equals": where == op["text"],
           "starts": where.startswith(op["text"]),
           "contains": op["text"] in where,
           "icontains": op["text"].lower() in where.lower()}[match]
    _run(op.get("ops", []) if hit else op.get("else_ops", []), g)


def _shell(op: Mapping, g: dict[str, Any]) -> None:
    """不经门面的读屏命令（`p.d.shell`）：拉起设置页、`input swipe`、`getprop` 这类原样下发。"""
    g["p"].d.shell(op["command"])


def _sleep(op: Mapping, g: dict[str, Any]) -> None:
    g["time"].sleep(op["seconds"])


def _press(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].d.press(op["key"])


def _app_stop(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].d.app_stop(op["pkg"])


def _note_miss(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].note_miss(op["text"])


def _miss_reset(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].miss = 0


def _require_unlocked(op: Mapping, g: dict[str, Any]) -> None:
    if g["p"].locked():
        raise RuntimeError(op.get("miss_print", "手机锁屏，请机主解锁"))


def _miss_message(op: Mapping, g: dict[str, Any]) -> str:
    """失败文案的两种现场尾巴，与旧脚本两种写法对应。

    `evidence=true` 接上 `p.page_evidence()`（`…；+ p.page_evidence()` 同形）；`at_focus=true` 读一次
    前台接成 `…；停在 <前台>`（老脚本的 `f"…；停在 {p.focus()}"`）。那次 `focus()` 也是脚本发出的
    调用，对拍要能对上；两者都不写时只有文案。"""
    message = op["miss_print"]
    if op.get("evidence"):
        message += g["p"].page_evidence()
    if op.get("at_focus"):
        message += "；停在 " + g["p"].focus()
    return message


def _require_tab(op: Mapping, g: dict[str, Any]) -> None:
    if not g["p"].tab(op["name"]):
        raise RuntimeError(_miss_message(op, g))


def _require_go(op: Mapping, g: dict[str, Any]) -> None:
    if not g["p"].go(op["text"], op["expect"]):
        raise RuntimeError(_miss_message(op, g))


def _tap(op: Mapping, g: dict[str, Any]) -> None:
    kwargs: dict[str, Any] = {}
    for key in ("exact", "scrolls"):
        if key in op:
            kwargs[key] = op[key]
    kwargs.update(op.get("kwargs", {}))
    g["p"].tap(op["text"], **kwargs)


def _go(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].go(op["text"], op["expect"])


def _dismiss(op: Mapping, g: dict[str, Any]) -> None:
    g["p"].dismiss()


def _skip_in_safe_mode(op: Mapping, g: dict[str, Any]) -> None:
    g["skip_in_safe_mode"]()


def _require_setting(op: Mapping, g: dict[str, Any]) -> None:
    args = [op["kw"]]
    if "entry" in op:
        args.append(op["entry"])
    if not g["p"].setting(*args):
        raise RuntimeError(op["miss_print"])


def _require_tap(op: Mapping, g: dict[str, Any]) -> None:
    """`require(p.tap(text, exact=…, scrolls=…), 文案)`：点不到就按这一段失败（#1265）。"""
    kwargs: dict[str, Any] = {}
    for key in ("exact", "scrolls"):
        if key in op:
            kwargs[key] = op[key]
    if not g["p"].tap(op["text"], **kwargs):
        raise RuntimeError(_miss_message(op, g))


def _close_listed(op: Mapping, g: dict[str, Any]) -> None:
    """读回这一页的开关 → 只留点名的、页上真有的行 → 整表关（#1265）。

    与旧脚本逐字同形：`read_switches(page)` → 按候选名单过滤 → 空的按失败收尾 → `close_named`。"""
    available = g["read_switches"](op["page"])
    names = [name for name in op["names"] if name in available]
    g["require"](names, op["miss_print"])
    g["close_named"](names, op["page"], snapshot=available)


def _off_required(op: Mapping, g: dict[str, Any]) -> None:
    """跨两屏把这一页的开关读齐 → 回页顶 → 点名断言都在（缺了带现场失败）→ 点名关（#1266）。

    与旧脚本逐字同形：`before = {}` / `for _ in range(2): …switches(); if not scroll_more(): break` /
    `p.top(2)` / `require_switches(before, only, page, contains=…)` / `p.off(only=…, keep=…, page=…)`。"""
    page = g["p"]
    before: dict[str, Any] = {}
    for _ in range(2):
        before.update({title: on for title, on, _ in page.switches()})
        if not page.scroll_more():
            break
    page.top(2)
    g["require_switches"](before, list(op["only"]), op["page"], contains=op.get("contains", False))
    kwargs: dict[str, Any] = {"only": list(op["only"]), "page": op["page"]}
    if "keep" in op:
        kwargs["keep"] = list(op["keep"])
    page.off(**kwargs)


def _require_focus(op: Mapping, g: dict[str, Any]) -> None:
    """`require("<片段>" in p.focus(), 文案)`：读一次前台再断言，前台读取照旧进调用序列。"""
    g["require"](op["contains"] in g["p"].focus(), op["miss_print"])


def _require_find(op: Mapping, g: dict[str, Any]) -> None:
    """`require(p.find(text, exact=…), 文案)`：找一次再断言。"""
    kwargs: dict[str, Any] = {}
    if "exact" in op:
        kwargs["exact"] = op["exact"]
    g["require"](g["p"].find(op["text"], **kwargs), op["miss_print"])


def _if_find(op: Mapping, g: dict[str, Any]) -> None:
    """`if p.find(text, exact=…[, edge_ok=…][, nav=…]): … else …`。"""
    kwargs: dict[str, Any] = {}
    for key in ("exact", "edge_ok", "nav"):
        if key in op:
            kwargs[key] = op[key]
    if g["p"].find(op["text"], **kwargs):
        _run(op.get("ops", []), g)
    else:
        _run(op.get("else_ops", []), g)


def _if_tap(op: Mapping, g: dict[str, Any]) -> None:
    """`if p.tap(text, exact=…, scrolls=…): … else: …`：门面自己的返回值决定走哪支。"""
    kwargs: dict[str, Any] = {}
    for key in ("exact", "scrolls"):
        if key in op:
            kwargs[key] = op[key]
    if g["p"].tap(op["text"], **kwargs):
        _run(op.get("ops", []), g)
    else:
        _run(op.get("else_ops", []), g)


def _if_entry(op: Mapping, g: dict[str, Any]) -> None:
    """`if p.entry(text, scrolls=…): … else …`（与 `gated` 的区别是带 else 分支）。"""
    if g["p"].entry(op["text"], scrolls=op.get("scrolls", 6)):
        _run(op.get("ops", []), g)
    else:
        _run(op.get("else_ops", []), g)


def _if_lib(op: Mapping, g: dict[str, Any]) -> None:
    """`if <库助手>(…): … else …`（如 `if tap_row("消息提醒"): …`）。返回值决定走哪支。"""
    if g[op["name"]](*[_arg(a, g) for a in op.get("args", [])],
                     **{k: _arg(v, g) for k, v in op.get("kwargs", {}).items()}):
        _run(op.get("ops", []), g)
    else:
        _run(op.get("else_ops", []), g)


def _if_setting(op: Mapping, g: dict[str, Any]) -> None:
    """`if p.setting(kw[, entry]): … else …`：设置搜索直达的成败决定走哪一支（#1267）。"""
    args = [op["kw"]] + ([op["entry"]] if "entry" in op else [])
    if g["p"].setting(*args):
        _run(op.get("ops", []), g)
    else:
        _run(op.get("else_ops", []), g)


def _if_lib_any(op: Mapping, g: dict[str, Any]) -> None:
    """`<助手A>(…) or <助手B>(…)`：短路取第一个成功的助手（#1267）。

    旧脚本用 `or` 串两个入口助手（`gear(toolbar_only=True) or gear()`）：第一个成真时第二个不调，
    这个调用序列按数据里的顺序原样发出，与旧脚本逐条相同。"""
    for call in op["calls"]:
        if g[call["name"]](*[_arg(a, g) for a in call.get("args", [])],
                           **{k: _arg(v, g) for k, v in call.get("kwargs", {}).items()}):
            _run(op.get("ops", []), g)
            return
    _run(op.get("else_ops", []), g)


def _require_expect(op: Mapping, g: dict[str, Any]) -> None:
    """`require(p.expect_page(…), 文案)`：几个调用短路 OR，全落空按这一段失败收尾（#1267）。

    实参按数据里的形态原样下发（位置 / 关键字不合并）：旧脚本既有
    `p.expect_page("x", 3)` 也有 `p.expect_page("x", timeout=3)`，两条都要逐条对上。"""
    page = g["p"]
    for call in op["calls"]:
        kwargs = {k: _arg(v, g) for k, v in call.get("kwargs", {}).items()}
        if page.expect_page(*[_arg(a, g) for a in call["args"]], **kwargs):
            return
    raise RuntimeError(_miss_message(op, g))


_HANDLERS: dict[str, Callable[[Mapping, dict[str, Any]], None]] = {
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
