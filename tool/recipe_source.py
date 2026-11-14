r"""机型脚本的「事实」层：一份源码里发生了哪些调用。纯 AST，不碰手机、不读屏、不 import 任何消费方。

`tool/entries.py`（入口速查）与 `tool/vocab.py`（词库）都从这一份调用点清单投影成各自的形状，
不再各写一套词法读同一批脚本（沿用 #1156 的分工）。事实层只回答「发生了什么」：不认词表、不做分类、不判极性。

解析口径复刻它替掉的两套词法，语义修正留给以后的票；只有一条刻意没抄：

- 名字的值取「文件内、位置之前最后一次同名赋值」，不分作用域；最后一次赋值读不出时返回空，
  不退回更早的旧值——那样会记成别的值（入口速查会把它记成另一个包）。
- 赋值取到的字符串原样返回，不复刻旧词法里 `[\w.$]` 那道字符集卡：那道卡只卡「按位置猜赋值」
  这一条路，同一批串在源码正文里本来就看得见（`hot_news` 这种整条命令串是被正则直接捞到的）。
  收成一份事实后只剩一种读法，再卡会把这类机型的出处读丢；实测放开它，两份生成物一个字不变。
- 形参回填只在同一份源码内做，且只从函数定义之后的调用处取：调用处不在本文件里（实现住在 `recipe_lib`）时
  返回空，由调用方按形参位置传 `bindings` 把两侧合起来（沿用 #1149 的口径）。按名字取外部值同理：
  `externals` 收调用脚本的模块级字符串常量，实现里 `g["HOT"]` 这类写法因此读得出（#1209）。
- 语法错一律抛 `SyntaxError`，不做容错返回：静默少几台机型比崩掉更糟。
- f-string 不解析：`f"am start … {activity}"` 现在算不上入口，这里也不让它算上；页面标签仍按
  `{变量}` 的写法渲染（那是标签的写法，不是值）。

库实现的归属按名字查，不按脚本的 import 解析（#1268）：`library_sources()` 从 `recipe_nav` /
`recipe_strategies` / `recipe_steps` 三个稳定 import 面取实现，归属写函数真正的 `__module__`
（`recipe_lib.<家族>` / `recipe_lib.shared`）；数据里的 `lib` 名由 `_lib_modules()` 在这张表里
唯一定位。没有按 import 归属的三张注册表，也没有同名覆盖：装载时库名先进 `LIBRARY`，例外命名
空间只补库里没有的名字。
"""
import ast
import glob
import json
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

_Function = ast.FunctionDef | ast.AsyncFunctionDef
_Position = tuple[int, int]

# 三个稳定 import 面（#1243、#1269）：实现住在 `recipe_lib`，这三个模块只做重导出，事实层经它们取名字。
NAV_MODULE = "recipe_nav"
STRATEGIES_MODULE = "recipe_strategies"
STEPS_MODULE = "recipe_steps"
SURFACE = (NAV_MODULE, STRATEGIES_MODULE, STEPS_MODULE)


@dataclass(frozen=True)
class Item:
    """名单里的一个字符串，带它自己的行号（词库的出处行就是它）。"""
    text: str
    line: int


@dataclass(frozen=True)
class Arg:
    """一处调用里的一个实参。

    `values` 是解析出的字符串：单个、一列（`only=[…]` 或模块级常量）、空。`text` 是原文，读不出时看它。
    `resolved` 指这个表达式解析成功了——空列表 `[]` 解析成功但 `values` 也是空，与读不出靠它区分。
    `param` 是这个实参是外层函数的第几个形参（从 0 起）；不是形参时是 None。"""
    text: str
    keyword: str | None
    values: tuple[Item, ...]
    param: int | None = None
    resolved: bool = False


@dataclass(frozen=True)
class Call:
    """一个调用点。`injected` 指它是按名字写的调用（裸名、`X.n(…)`，或历史写法 `g["X"]`），
    不是 `p.…` 这类属性调用；事实层用它把库 / 本机函数与设备门面方法分开。

    `module` 是这个名字的归属模块：`import X` 后的 `X.n(…)` 与 `from X import n` 都记成 `X`；
    裸名字没有 import 时记空串。

    实参先按位置排，再排关键字实参；`keyword` 为 None 的才是位置实参。"""
    name: str
    line: int
    function: str
    page: str
    injected: bool
    args: tuple[Arg, ...]
    module: str = ""


@dataclass(frozen=True)
class DictEntry:
    """模块级字典里的一对常量字符串键值。键或值不是字符串时（含 `{**other}` 的 None 键）不收。"""
    key: str
    value: str
    line: int


@dataclass(frozen=True)
class Facts:
    """一份源码的事实：调用点清单、模块级定义的函数名（本地定义优先）、
    模块级字典里的常量键值对（词库拿它筛说明文字，判不判中文留给消费方），模块级字符串
    常量（单串与列表）——扫库实现时，调用方把 `constants` 交回 `scan_source(externals=…)`，
    实现里按名字取的值才读得出——以及导入的名字与归属模块（`{名字: 模块}`，含 `if TYPE_CHECKING:`
    块；`import X` 记成 `{X: X}`，`import X as Y` 记成 `{Y: X}`，消费方按它解析共享实现的归属）
    与导入行号（`{名字: 行号}`，没有调用点可写出处时词库退到这一行，#1253）。"""
    calls: tuple[Call, ...]
    defines: frozenset[str]
    dict_entries: tuple[DictEntry, ...] = ()
    constants: Mapping[str, tuple[Item, ...]] = field(default_factory=dict)
    imports: Mapping[str, str] = field(default_factory=dict)
    import_lines: Mapping[str, int] = field(default_factory=dict)


def _string_value(node: ast.AST) -> str | None:
    """字符串字面量的值；不是字符串常量时 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _string_list(node: ast.AST) -> tuple[Item, ...] | None:
    """纯字符串的列表 / 元组字面量：[每个元素] 或 None。"""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    items = []
    for element in node.elts:
        value = _string_value(element)
        if value is None:
            return None
        items.append(Item(value, element.lineno))
    return tuple(items)


def _label(node: ast.expr | None) -> str:
    """页面标签：字面量原样；f-string 的变量部分写成 `{变量}`；其余写成 `<表达式>`；没写是空串。"""
    if node is None:
        return ""
    literal = _string_value(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append("{" + ast.unparse(value.value) + "}")
        return "".join(parts)
    return f"<{ast.unparse(node)}>"


def _plain_name(func: ast.expr) -> str | None:
    """调用名里的裸名字：`X` 或 `g["X"]` 的 `X`；属性调用返回 None。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Subscript) and isinstance(func.value, ast.Name):
        return _string_value(func.slice)
    return None


def business_args(call: "Call") -> tuple["Arg", ...]:
    """注入调用现在统一带 `(p, rt)` 前缀（#1268），词库与入口速查要的是业务实参。

    前缀只认事实层自己的形状：前两个位置实参的原文正好是 `p` / `rt`。`p.off(...)` 这类方法调用
    不是 injected，原样返回。"""
    args = call.args
    if (call.injected and len(args) >= 2 and args[0].keyword is None and args[1].keyword is None
            and args[0].text == "p" and args[1].text == "rt"):
        return args[2:]
    return args


def _call_name(func: ast.expr, modules: Mapping[str, str],
               names: Mapping[str, str]) -> tuple[str, bool, str]:
    """（归一后的调用名, 是不是按名字写的调用, 归属模块）。

    裸名 `X(…)` 与历史写法 `g["X"](…)` 归一成 `X`；`M.X(…)`（`M` 是库模块的导入别名）同样归一成
    `X`，归属记 `M`，这样 `import recipe_nav` + `recipe_nav.gear(…)` 与 `from recipe_nav import gear`
    两种写法走到同一份实现（#1243）。其余属性调用（`p.start`、`time.sleep`）原样留全名。"""
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and modules.get(func.value.id) in SURFACE):
        return func.attr, True, modules[func.value.id]
    name = _plain_name(func)
    if name is not None:
        return name, True, names.get(name, "")
    return ast.unparse(func), False, ""


def _imports(tree: ast.Module) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    """（名字 → 归属模块, 模块别名 → 模块, 名字 → 导入行号）。

    只收模块级语句与 `if TYPE_CHECKING:` / `try:` 块里的导入：`if TYPE_CHECKING:` 里的那些在运行时
    不执行、静态检查才看得见，正是脚本声明「谁提供这个实现」的地方。函数体里的局部导入不收，
    它只在那一个函数里可见。`from . import x` 这类没有模块名，记空串。

    行号是那个名字在脚本里的唯一落点：实现由库提供、脚本只按名字取（`g["off_exact"]` 那种钩子、或
    模块级别名）时没有调用点可写出处，词库退到这一行（#1253）。"""
    names: dict[str, str] = {}
    modules: dict[str, str] = {}
    lines: dict[str, int] = {}

    def walk(body: Sequence[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    modules[name] = alias.name
                    lines[name] = alias.lineno
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    names[name] = module
                    lines[name] = alias.lineno
            elif isinstance(node, (ast.If, ast.Try)):
                walk(node.body)
                walk(node.orelse)
                for handler in getattr(node, "handlers", ()):
                    walk(handler.body)

    walk(tree.body)
    return names, modules, lines


def _param_names(function: _Function | None) -> tuple[str, ...]:
    if function is None:
        return ()
    return tuple(a.arg for a in function.args.posonlyargs + function.args.args)


def _product(parts: Sequence[Sequence[Item]]) -> list[str]:
    """各段取值的笛卡尔积：同一处实参经过的形参可能有多个调用处，一段对应多个结果。"""
    out = [""]
    for items in parts:
        out = [head + item.text for head in out for item in items]
    return out


def _values(source: "_Source", node: ast.expr, function: _Function | None,
            backfill: bool = True) -> tuple[Item, ...] | None:
    """一个表达式解析出的字符串。读不出返回 None，原文留给调用方；解析成空（`[]`）返回空元组。"""
    literal = _string_value(node)
    if literal is not None:
        return (Item(literal, node.lineno),)
    strings = _string_list(node)
    if strings is not None:
        return strings
    if isinstance(node, ast.Name):
        constant = source.constants.get(node.id)
        if constant is not None:
            return constant
        found = source.last_string(node.id, (node.lineno, node.col_offset))
        if found is not None:
            return (found,)
        params = _param_names(function)
        if function is None or node.id not in params:
            return source.external(node.id)
        if backfill:
            filled = source.param_items(node.id, function)
            if filled:
                return filled
        bound = source.bindings.get(params.index(node.id), ())
        return tuple(Item(text, node.lineno) for text in bound)
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and isinstance(node.slice, ast.Constant)):
        value = source.dicts.get(node.value.id, {}).get(node.slice.value)
        if value is not None:
            return _string_list(value)
        return source.external(node.slice.value)
    # `rt.constants["HOT"]` / `rt.constants.get("HOT")`：注入面拆除后常量从 rt 取，值仍在调用脚本里。
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name) and node.value.value.id == "rt"
            and node.value.attr == "constants" and isinstance(node.slice, ast.Constant)):
        return source.external(node.slice.value)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "rt"
            and node.func.value.attr == "constants" and node.func.attr == "get"
            and node.args and isinstance(node.args[0], ast.Constant)):
        return source.external(node.args[0].value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _values(source, node.left, function, backfill)
        right = _values(source, node.right, function, backfill)
        if left is None or right is None:
            return None
        return tuple(Item(text, node.lineno) for text in _product((left, right)))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format" and isinstance(node.func.value, ast.Name)):
        return _formatted(source, node, node.func.value.id, function, backfill)
    return None


def _formatted(source: "_Source", node: ast.Call, name: str, function: _Function | None,
               backfill: bool) -> tuple[Item, ...] | None:
    """`模板常量.format(包名)`：模板是模块级字符串常量、`{}` 按位置填进去才还原得出（沿用 #956 的写法）。"""
    template = source.last_string(name, (node.lineno, node.col_offset))
    if template is None or "{}" not in template.text:
        return None
    rest, parts = template.text, []
    for argument in node.args:
        values = _values(source, argument, function, backfill)
        if values is None:
            return None
        head, slot, rest = rest.partition("{}")
        if not slot:
            return None
        parts += [(Item(head, node.lineno),), values]
    if "{}" in rest:
        return None
    parts.append((Item(rest, node.lineno),))
    return tuple(Item(text, node.lineno) for text in _product(parts))


class _Source:
    """一份源码的解析上下文：模块级常量、文件内的简单赋值、以及每个调用点所在的函数。"""

    def __init__(self, tree: ast.Module, bindings: Mapping[int, Sequence[str]] | None = None,
                 externals: Mapping[str, Sequence[Item]] | None = None) -> None:
        self.constants: dict[str, tuple[Item, ...]] = {}
        self.dicts: dict[str, dict[object, ast.expr]] = {}
        self.assigns: dict[str, list[tuple[_Position, ast.expr]]] = {}
        self.bindings: Mapping[int, Sequence[str]] = bindings or {}
        self.externals: Mapping[str, Sequence[Item]] = externals or {}
        self.imports, self.modules, self.import_lines = _imports(tree)
        self.calls: list[tuple[ast.Call, _Function | None]] = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                self.assigns.setdefault(node.targets[0].id, []).append(
                    ((node.lineno, node.col_offset), node.value))
        for values in self.assigns.values():
            values.sort(key=lambda entry: entry[0])
        for node in tree.body:
            self._module_constant(node)
        self._visit(tree, None)

    def _module_constant(self, node: ast.stmt) -> None:
        """模块级常量：字符串列表与字典。后赋了别的值的不算，已经不是这份词了。"""
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            self.constants.pop(node.target.id, None)
            return
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            return
        name = node.targets[0].id
        strings = _string_list(node.value)
        if strings is None:
            self.constants.pop(name, None)
        else:
            self.constants[name] = strings
        self.dicts.pop(name, None)
        if isinstance(node.value, ast.Dict):
            keys, values = node.value.keys, node.value.values
            self.dicts[name] = {key.value: value for key, value in zip(keys, values, strict=True)
                                if isinstance(key, ast.Constant)}

    def _visit(self, node: ast.AST, function: _Function | None) -> None:
        if isinstance(node, ast.Call):
            self.calls.append((node, function))
        for child in ast.iter_child_nodes(node):
            self._visit(child, child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        else function)

    def external(self, name: object) -> tuple[Item, ...] | None:
        """另一份源码（调用方脚本）给的模块级常量。注入实现里按名字现取的那些值走这一条：`g["HOT"]`
        的 `HOT` 在实现里没有赋值，脚本里才有。没传 `externals` 时恒返回 None。"""
        if not isinstance(name, str):
            return None
        values = self.externals.get(name)
        return tuple(values) if values is not None else None

    def last_string(self, name: str, pos: _Position) -> Item | None:
        """这个名字在 `pos` 之前最后一次赋值；那次赋值不是字符串字面量时返回 None（不退回旧值）。"""
        found = None
        for where, value in self.assigns.get(name, ()):
            if where < pos:
                found = value
        if found is None:
            return None
        text = _string_value(found)
        return Item(text, found.lineno) if text is not None else None

    def param_items(self, name: str, function: _Function) -> tuple[Item, ...]:
        """变量是外层函数的形参时，从本文件里调用它的地方取对应实参。调用处不在本文件时返回空。"""
        params = _param_names(function)
        if name not in params:
            return ()
        index = params.index(name)
        out: list[Item] = []
        for call, _function in self.calls:
            if call.lineno <= function.lineno:
                continue
            if not (isinstance(call.func, ast.Name) and call.func.id == function.name):
                continue
            if index < len(call.args):
                out += _values(self, call.args[index], None, backfill=False) or ()
        return tuple(out)


def _page(call: ast.Call) -> str:
    """这一处调用报的页面标签：`page=` / `title=` 关键字实参，或 `close_named*` 的第二个位置实参。

    两个消费方都要这一份标签（词库拿它归分组，入口速查不用），写法只在 `_label()` 里有一处。
    `close_named` 与策略库的 `close_named_vivo` 等同族名字都是「名单, 页面」的位置写法（#1263）。"""
    kwargs = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    name = _plain_name(call.func)
    if name is None and isinstance(call.func, ast.Attribute) and call.func.attr.startswith("close_named"):
        name = call.func.attr        # `strategies.close_named_vivo(...)`：模块限定名也要认
    if name is not None and name.startswith("close_named"):
        positional: list[ast.expr | None] = list(call.args)
        if (len(positional) >= 2 and isinstance(positional[0], ast.Name) and positional[0].id == "p"
                and isinstance(positional[1], ast.Name) and positional[1].id == "rt"):
            positional = positional[2:]     # 注入调用统一带 (p, rt) 前缀
        positional += [None, None]
        node = positional[1] or kwargs.get("page") or kwargs.get("title")
    else:
        node = kwargs.get("page") or kwargs.get("title")
    return _label(node)


def _module_values(tree: ast.Module) -> dict[str, tuple[Item, ...]]:
    """模块级字符串常量：单个字符串与纯字符串列表都收，后赋了别的值的不算。

    给 `externals` 用：注入实现里按名字现取的值（`g["HOT"]`）住在调用脚本里，实现这一侧只看得见
    名字。与 `_Source.constants` 的区别只有一条：那份只收列表，包名、页面名这类单个字符串常量
    不在里面，而段体按名字取的两种都要。"""
    out: dict[str, tuple[Item, ...]] = {}
    for node in tree.body:
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            out.pop(node.target.id, None)
            continue
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        literal = _string_value(node.value)
        strings = _string_list(node.value)
        if literal is not None:
            out[name] = (Item(literal, node.value.lineno),)
        elif strings is not None:
            out[name] = strings
        else:
            out.pop(name, None)
    return out


def _dict_entries(tree: ast.Module) -> tuple[DictEntry, ...]:
    """模块级字典里的常量字符串键值对。词库拿它筛「写给人看的说明」；这里不判中文，也不认词条。"""
    out = []
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
            continue
        # ast.Dict 的 keys 与 values 恒等长；`{**other}` 的键是 None
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            key_text = _string_value(key) if key is not None else None
            value_text = _string_value(value)
            if key_text is not None and value_text is not None:
                out.append(DictEntry(key_text, value_text, value.lineno))
    return tuple(out)


def scan_source(src: str, bindings: Mapping[int, Sequence[str]] | None = None,
                externals: Mapping[str, Sequence[Item]] | None = None) -> Facts:
    """一份机型脚本源码的事实：调用点清单 + 模块级定义的函数名。语法错抛 `SyntaxError`。

    `bindings` 是另一份源码（调用方）给的形参取值 `{形参位置: (字符串, …)}`：扫注入实现时，
    实参在脚本里、形参在实现里，本文件找不到调用处，由调用方按位置把两侧合起来传进来
    （沿用 #1154 的做法）。

    `externals` 是另一份源码（调用方）的模块级常量 `{名字: (Item, …)}`：段体搬进注入面之后，
    它依赖的字面量仍住在脚本里，实现里只有 `g["HOT"]` 这样的名字（沿用 #1149 的段体口径，#1209）。缺省不查，
    行为与加这个参数之前逐字相同。"""
    tree = ast.parse(src)
    source = _Source(tree, bindings, externals)
    calls = []
    for node, function in source.calls:
        name, injected, module = _call_name(node.func, source.modules, source.imports)
        params = _param_names(function)
        args = []
        for index, argument in enumerate(node.args):
            values = _values(source, argument, function)
            args.append(Arg(text=ast.unparse(argument), keyword=None, values=values or (),
                            param=index if isinstance(argument, ast.Name) and argument.id in params else None,
                            resolved=values is not None))
        for keyword in node.keywords:
            if keyword.arg is None:
                continue                    # **kwargs：没有名字，也不是形参
            values = _values(source, keyword.value, function)
            args.append(Arg(text=ast.unparse(keyword.value), keyword=keyword.arg, values=values or (),
                            param=params.index(keyword.value.id)
                            if isinstance(keyword.value, ast.Name) and keyword.value.id in params else None,
                            resolved=values is not None))
        calls.append(Call(name=name, line=node.lineno, function=function.name if function else "",
                          page=_page(node), injected=injected, args=tuple(args), module=module))
    calls.sort(key=lambda call: (call.line, call.name))
    return Facts(calls=tuple(calls), defines=frozenset(
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
        dict_entries=_dict_entries(tree), constants=_module_values(tree),
        imports={**source.modules, **source.imports}, import_lines=source.import_lines)


def scan_dir(recipes_dir: str, families: Mapping[str, str] | None = None) -> dict[str, Facts]:
    """一个脚本目录的事实：{相对路径: 事实}，按路径排序。

    每个型号目录（`recipes/<家族>/<型号>/`）只出**一份**事实，两条来源：
    - 有 `recipe*.py`（含 `recipe_android15.py` 这类变体）时读这些源码（迁移期 `.py` 仍是活的，
      `.toml` 只是同目录的等价副本，例如 `V1986A`）；
    - 没有 `recipe*.py`、只有 `<型号>.toml` 时读 catalog 数据（`scan_catalog`，含同目录
      `<型号>.py` 例外函数）。这样转成数据之后脚本不会从词库 / 入口速查里消失（#1270）。

    `families` 给定时只收家族认得出的脚本（词库的入口）；不给就全收（入口速查）。遍历口径
    （目录切分、文件名、家族过滤）只在这里写一次，两个消费方不再各写一份 glob。
    路径的第一段是家族（`recipes/<家族>/<型号>/…`），家族名本身也在 `families` 里。"""
    out = {}
    for model_dir in sorted(glob.glob(os.path.join(recipes_dir, "*", "*"))):
        if not os.path.isdir(model_dir):
            continue
        rel_dir = os.path.relpath(model_dir, recipes_dir).replace(os.sep, "/")
        if families is not None and families.get(rel_dir.split("/", 1)[0].lower()) is None:
            continue
        py = sorted(glob.glob(os.path.join(model_dir, "recipe*.py")))
        if py:
            for path in py:
                rel = os.path.relpath(path, recipes_dir).replace(os.sep, "/")
                with open(path, encoding="utf-8") as handle:
                    out[rel] = scan_source(handle.read())
            continue
        for toml in sorted(glob.glob(os.path.join(model_dir, "*.toml"))):
            rel = os.path.relpath(toml, recipes_dir).replace(os.sep, "/")
            out[rel] = scan_catalog_file(toml)
    return dict(sorted(out.items()))


def _s(value: object) -> str:
    """把 TOML 里的标量写成 Python 字面量（字符串走 json，数字/布尔原样）。"""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else repr(value)


def _catalog_src(data: Mapping[str, Any]) -> str:
    """把一份 catalog 数据降成等价的 Python 源码：每个 op 一行语句，复用 `scan_source` 的读法。

    只关心事实层会读的调用：`p.off`（含 only/keep/page）、`p.start`、`p.entry`（maybe）、
    库调用（`lib` / `require_lib` / `code` 的裸名）。整页关闭 `close_all` 降成不带 only 的
    `p.off`，与旧脚本「整页关闭」同一个事实形状。`back` / `top` / `print` / `return` 不产生事实。"""
    lines: list[str] = []

    def lower(ops: Sequence[Any]) -> None:
        for op in ops:
            if not isinstance(op, Mapping):
                continue
            kind = op.get("kind")
            if kind in ("off", "off_required"):
                args = ""
                if "only" in op:
                    args += f"only={json.dumps(op['only'], ensure_ascii=False)}, "
                elif "only_code" in op:
                    args += f"only={op['only_code']}(), "
                if "keep" in op:
                    args += f"keep={json.dumps(op['keep'], ensure_ascii=False)}, "
                lines.append(f'p.off({args}page={_s(op["page"])})')
            elif kind == "close_all":
                lines.append(f'p.off(page={_s(op["page"])})')
            elif kind == "start":
                extra = f", {_s(op['activity'])}" if "activity" in op else ""
                lines.append(f'p.start({_s(op["pkg"])}{extra})')
            elif kind == "start_or_skip":
                lines.append(f'start_or_skip(p, rt, {_s(op["pkg"])}, {_s(op["activity"])})')
            elif kind == "skip_unless_installed":
                # `p.d.shell("pm path …")` 原样进事实层（不是 am start，不构成入口，只是不丢这条读）。
                lines.append(f"p.d.shell({_s(op['command'])})")
            elif kind in ("entry", "require_entry"):
                lines.append(f"p.entry({_s(op['text'])})")
            elif kind == "enter":
                lines.append(f"p.enter({_s(op['text'])})")
            elif kind in ("require_setting", "if_setting"):
                # 设置搜索直达是入口速查的一档（search），两支都一样要读出来（#1267）。
                extra = f", {_s(op['entry'])}" if "entry" in op else ""
                lines.append(f"p.setting({_s(op['kw'])}{extra})")
                lower(op.get("ops", []))
                lower(op.get("else_ops", []))
            elif kind == "shell":
                # 不经门面的拉起串（`am start …`）也是入口，不降级的话入口速查会漏掉这台机（#1263）。
                lines.append(f"p.d.shell({_s(op['command'])})")
            elif kind == "gated":
                for text in op.get("entries", []):
                    lines.append(f"maybe(p, rt, {_s(text)})")
                lower(op.get("ops", []))
            elif kind == "scoped":
                if "systemui_text" in op:
                    lines.append(f"p.systemui_text = {op['systemui_text']!r}")
                lower(op.get("ops", []))
            elif kind in ("if_find", "if_entry", "if_lib", "if_lib_any", "if_focus", "if_tap"):
                # 带条件分支的 op：两支里的 off / 入口调用一样要读出来，否则词与入口会静默丢（#1263）。
                if kind == "if_lib":
                    args = ", ".join(_s(a) for a in op.get("args", []))
                    lines.append(f"{op['name']}(p, rt, {args})" if args else f"{op['name']}(p, rt)")
                elif kind == "if_lib_any":
                    # 短路的每个助手都调得到：漏一个，入口归属就少一条（#1267）。
                    for call in op.get("calls", []):
                        args = ", ".join(_s(a) for a in call.get("args", []))
                        if "method" in call:
                            lines.append(f"p.{call['method']}({args})")
                        else:
                            lines.append(f"{call['name']}(p, rt, {args})" if args else f"{call['name']}(p, rt)")
                lower(op.get("ops", []))
                lower(op.get("else_ops", []))
            elif kind in ("lib", "require_lib", "code", "return_lib"):
                # 用数据里写得出的真实名字（不折回 close_named），归属才查得准（#1263）。
                args = ", ".join(_s(a) for a in op.get("args", []))
                lines.append(f"{op['name']}(p, rt, {args})" if args else f"{op['name']}(p, rt)")
            elif kind == "close_listed":
                # 候选名单是「这一页要关掉这些名字」，按 `close_named(名单, 页)` 投影进事实层：
                # 词库按 close 那一类读得出这些字面量（旧脚本里 `names` 是运行期变量，读不出，#1265）。
                names = ", ".join(_s(name) for name in op.get("names", []))
                lines.append(f"close_named(p, rt, [{names}], {_s(op['page'])})")
            elif kind in ("page", "skip", "fail", "require_tap"):
                # 落点断言 / 跳过 / 失败出口 / 必需点按不带词条与入口事实：入口本来自 `p.start` / shell /
                # `open_app_settings`，`page` 只是核对。与 `back` / `top` / `print` 同档（#1265）。
                pass

    for segment in data.get("segment", []):
        if "code" in segment:
            lines.append(f"{segment['code']}(p, rt)")
        else:
            lower(segment.get("ops", []))
    return "\n".join(lines) or "pass"


def library_sources() -> dict[str, tuple[str, str]]:
    """机型库数据可调用的实现：{名字: (归属模块, 源码)}。

    名字全局唯一，直接定位实现，不再按脚本 import 做归属解析（#1268）。#1269 拆库后实现按家族住在
    `recipe_lib/<家族>.py` / `recipe_lib/shared.py`，`tool/recipe_nav.py` 等三个只做重导出；这里经
    重导出面拿到函数对象，归属写它真正的 `__module__`（`recipe_lib.shared` 等）。
    词库与入口速查拿它扫实现里的字面量。延迟 import：只有调用它时才加载库。"""
    import inspect
    import recipe_nav
    import recipe_strategies
    import recipe_steps
    found: dict[str, tuple[str, str]] = {}
    for module in (recipe_nav, recipe_strategies, recipe_steps):
        for name in module.__all__:
            function = getattr(module, name)
            found[name] = (function.__module__, inspect.getsource(function))
    # 实现之间用裸名字互调；`inspect.getsource` 只有函数体、没有模块头。补一组
    # `from recipe_lib.<模块> import <名字>`，事实层才给裸调用记上归属模块（`Call.module`）——
    # 词库的逐层下扫按「有归属的注入调用」筛，缺了它整条实现链会被静默跳过（#1269）。
    by_module: dict[str, list[str]] = {}
    for name, (owner, _source) in found.items():
        by_module.setdefault(owner, []).append(name)
    prefix = "\n".join(f"from {owner} import {', '.join(sorted(names))}"
                       for owner, names in sorted(by_module.items())) + "\n"
    return {name: (owner, prefix + source) for name, (owner, source) in found.items()}


def _lib_modules() -> dict[str, str]:
    """数据 `lib` 名 → 归属模块。三个库的 `__all__` 全局唯一（#1268：没有同名覆盖）。"""
    return {name: module for name, (module, _source) in library_sources().items()}


def scan_catalog(data: Mapping[str, Any], exception_src: str | None = None) -> Facts:
    """一份 catalog 数据的事实：把数据降成等价源码交给 `scan_source`，再把库调用的归属补上。

    库调用（`lib` 的 `settings_home` / `off_one` 等）在数据里没有 import 头，归属由 `_lib_modules()`
    在三张注入表里唯一定位后补进 `imports`；同时把 `Call.module` 也盖上同一份归属——`injected_calls()`
    按模块筛调用点，`Call.module` 是空串时脚本这一层一个实现都扫不到，入口速查会静默丢掉机型归属
    （#1263）。数据显式点名实现，归属靠名字查、不靠 import，与 ADR-0038 一致。
    `exception_src` 是同目录 `<型号>.py` 例外函数源码：它与数据是同一台机的两份，合并成一份事实
    （`code=` 段的词住在例外函数里，别丢）。"""
    base = scan_source(_catalog_src(data))
    modules = _lib_modules()
    imports = dict(base.imports)
    import_lines = dict(base.import_lines)
    calls = []
    for call in base.calls:
        if call.injected and call.name not in base.defines:
            module = modules.get(call.name)
            if module is not None:
                imports.setdefault(call.name, module)
                import_lines.setdefault(call.name, call.line)
                call = replace(call, module=module)
        calls.append(call)
    base = replace(base, calls=tuple(calls), imports=imports, import_lines=import_lines)
    if exception_src is None:
        return base
    return _merge_facts(base, scan_source(exception_src))


def scan_catalog_file(toml_path: str) -> Facts:
    """读一份 `<型号>.toml`（含同目录 `<型号>.py` 例外）并给出事实。"""
    with open(toml_path, "rb") as handle:
        data = tomllib.load(handle)
    companion = os.path.splitext(toml_path)[0] + ".py"
    exception_src = None
    if os.path.isfile(companion):
        with open(companion, encoding="utf-8") as handle:
            exception_src = handle.read()
    return scan_catalog(data, exception_src)


def _merge_facts(first: Facts, second: Facts) -> Facts:
    """两份事实并成一份（数据 + 例外函数）：调用点合并、定义并集、常量与导入合并。

    行号在两份里各从 1 起，合并后可能重号——词库的出处行只是定位，重号不影响词条与计数。"""
    return Facts(
        calls=tuple(sorted(first.calls + second.calls, key=lambda call: (call.line, call.name))),
        defines=first.defines | second.defines,
        dict_entries=first.dict_entries + second.dict_entries,
        constants={**first.constants, **second.constants},
        imports={**first.imports, **second.imports},
        import_lines={**first.import_lines, **second.import_lines})

