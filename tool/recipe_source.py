r"""机型脚本的「事实」层：一份源码里发生了哪些调用。纯 AST，不碰手机、不读屏、不 import 任何消费方。

`tool/entries.py`（入口速查）与 `tool/vocab.py`（词库）都从这一份调用点清单投影成各自的形状，
不再各写一套词法读同一批脚本（沿用 #1156 的分工）。事实层只回答「发生了什么」：不认词表、不做分类、不判极性。

解析口径复刻它替掉的两套词法，语义修正留给以后的票；只有一条刻意没抄：

- 名字的值取「文件内、位置之前最后一次同名赋值」，不分作用域；最后一次赋值读不出时返回空，
  不退回更早的旧值——那样会记成别的值（入口速查会把它记成另一个包）。
- 赋值取到的字符串原样返回，不复刻旧词法里 `[\w.$]` 那道字符集卡：那道卡只卡「按位置猜赋值」
  这一条路，同一批串在源码正文里本来就看得见（`hot_news` 这种整条命令串是被正则直接捞到的）。
  收成一份事实后只剩一种读法，再卡会把这类机型的出处读丢；实测放开它，两份生成物一个字不变。
- 形参回填只在同一份源码内做，且只从函数定义之后的调用处取：调用处不在本文件里（注入实现）时
  返回空，由调用方按形参位置传 `bindings` 把两侧合起来（沿用 #1149 的口径）。按名字取外部值同理：
  `externals` 收调用脚本的模块级字符串常量，实现里 `g["HOT"]` 这类写法因此读得出（#1209）。
- 语法错一律抛 `SyntaxError`，不做容错返回：静默少几台机型比崩掉更糟。
- f-string 不解析：`f"am start … {activity}"` 现在算不上入口，这里也不让它算上；页面标签仍按
  `{变量}` 的写法渲染（那是标签的写法，不是值）。
"""
import ast
import glob
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

_Function = ast.FunctionDef | ast.AsyncFunctionDef
_Position = tuple[int, int]


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
    """一个调用点。`injected` 指它调的是执行作用域里的名字（裸名或 `g["X"]`），不是 `p.…` 这类属性。

    实参先按位置排，再排关键字实参；`keyword` 为 None 的才是位置实参。"""
    name: str
    line: int
    function: str
    page: str
    injected: bool
    args: tuple[Arg, ...]


@dataclass(frozen=True)
class DictEntry:
    """模块级字典里的一对常量字符串键值。键或值不是字符串时（含 `{**other}` 的 None 键）不收。"""
    key: str
    value: str
    line: int


@dataclass(frozen=True)
class Facts:
    """一份源码的事实：调用点清单、模块级定义的函数名（本地定义会盖住注入版的那份）、
    模块级字典里的常量键值对（词库拿它筛说明文字，判不判中文留给消费方），以及模块级字符串
    常量（单串与列表）——扫注入实现时，调用方把 `constants` 交回 `scan_source(externals=…)`，
    实现里按名字取的值才读得出。"""
    calls: tuple[Call, ...]
    defines: frozenset[str]
    dict_entries: tuple[DictEntry, ...] = ()
    constants: Mapping[str, tuple[Item, ...]] = field(default_factory=dict)


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


def _call_name(func: ast.expr) -> tuple[str, bool]:
    """（归一后的调用名, 是不是执行作用域里的名字）。`g["X"](…)` 与裸名 `X(…)` 归一成 `X`。"""
    name = _plain_name(func)
    if name is not None:
        return name, True
    return ast.unparse(func), False


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
    """这一处调用报的页面标签：`page=` / `title=` 关键字实参，或 `close_named` 的第二个位置实参。

    两个消费方都要这一份标签（词库拿它归分组，入口速查不用），写法只在 `_label()` 里有一处。"""
    kwargs = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    if _plain_name(call.func) == "close_named":
        positional = list(call.args) + [None, None]
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
        name, injected = _call_name(node.func)
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
                          page=_page(node), injected=injected, args=tuple(args)))
    calls.sort(key=lambda call: (call.line, call.name))
    return Facts(calls=tuple(calls), defines=frozenset(
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
        dict_entries=_dict_entries(tree), constants=_module_values(tree))


def scan_dir(recipes_dir: str, families: Mapping[str, str] | None = None) -> dict[str, Facts]:
    """一个脚本目录的事实：{相对路径: 事实}，只读 `recipe*.py`，按路径排序。

    `families` 给定时只收品牌认得出的脚本（词库的入口）；不给就全收（入口速查）。遍历口径
    （文件名、相对路径、品牌过滤）只在这里写一次，两个消费方不再各写一份 glob。"""
    out = {}
    for path in glob.glob(os.path.join(recipes_dir, "*", "recipe*.py")):
        rel = os.path.relpath(path, recipes_dir).replace(os.sep, "/")
        if families is not None and families.get(rel.split("-", 1)[0].lower()) is None:
            continue
        with open(path, encoding="utf-8") as handle:
            out[rel] = scan_source(handle.read())
    return dict(sorted(out.items()))


def injected_calls(facts: Facts, name: str) -> tuple[Call, ...]:
    """脚本里调用到某个注入名的调用点。脚本本地定义了同名实现的走本地那份，注入版不算（沿用 #1153 的做法）。

    两个消费方（入口速查、词库）都按这一条筛，判据不再各写一份。"""
    return tuple(call for call in facts.calls
                 if call.injected and call.name == name and name not in facts.defines)


def injected_sources() -> dict[str, str]:
    """注入面（`tool/recipe_nav.py` 与 `tool/recipe_steps.py`）里各实现的源码：{注入名: 源码}。

    注入实现里的入口写在实现里、脚本只剩一行调用；要事实就交给 `scan_source`，跨文件的形参
    取值由调用方按位置传 `bindings`、模块常量按名字传 `externals`（沿用 #1153、#1154、#1209）。
    两张注册表合并返回：入口速查不分「导航助手」与「段体」，脚本调了哪个名字就扫哪份实现。
    延迟 import：只有调用它时才加载这两张表，事实层本身不连带它们。"""
    import inspect
    import recipe_nav
    import recipe_steps
    return {name: inspect.getsource(factory)
            for table in (recipe_nav.NAV, recipe_steps.STEPS)
            for name, factory in table.items()}


def step_sources() -> dict[str, str]:
    """段体注入面（`recipe_steps.STEPS`）的源码：{注入名: 源码}，词库只扫这一张表。

    导航助手的开关名单写在调用点的实参里（`close_named(NAMES, page=…)`），扫它们的实现只会
    读到形参、记成一串没读出来的未解析；词住在实现里的只有段体那张表（#1209）。"""
    import inspect
    import recipe_steps
    return {name: inspect.getsource(factory) for name, factory in recipe_steps.STEPS.items()}
