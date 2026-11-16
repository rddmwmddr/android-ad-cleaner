"""catalog 的装载入口：「读一个目录/文件 → 可执行对象」（ADR-0038）。

这是数据的唯一执行入口，校验器与解释器共用：`load()` 先 `schema.validate()`，再按同一份数据建出
段 action。返回的 `LoadedCatalog` 与 `recipe_loader.LoadedRecipe` 同形（`.namespace` / `.rt` /
`.steps` / `.run()`），所以 `tests/fixtures.load_recipe` 与调用序列快照驱动不必区分两种格式。

装载只做四件事：读数据、校验、建出例外模块命名空间与这次执行的 `rt`（例外 `.py` 是普通模块，
exec 进一个 dict 供 `code=` 与钩子按名字取）、按段登记 action。真正的执行在 `LoadedCatalog.run()`
里，段一律经 `Runtime.run_step`，段归属不断。
"""
import difflib
import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import recipe_runtime
from recipe_runtime import Step

from . import interpreter, schema
# `recipe_lib` 与 `tool/` 平级，宿主只把 `tool/` 放进 `sys.path`；可达性靠 `interpreter` 顶部那三行
# 垫片（它先被导入），这里不另抄一份（ADR-0040）。
import recipe_lib


class CatalogScope(dict):
    """例外函数的模块命名空间，外加给测试的只读视图。

    字典本体只装例外模块自己定义/导入的名字（`exec` 写名字走本体，CPython 不调子类的
    `__setitem__`）。`ONLY` / `HALTED` 代理到这次执行的 `rt`；其余几个名字（`rt` / `p` / `time` /
    台账 / 库助手）是测试方便读取的视图——**解释器不从这里取实现**（它查 `interpreter.LIBRARY`），
    所以这不是注入面：往这里写同名键不会改变执行。"""

    # 测试读的台账 / 时钟 / 计数器：都是 rt 上同一批对象
    _RT_VIEW = {"rt": lambda rt: rt, "p": lambda rt: rt.p, "time": lambda rt: rt.clock,
                "FAILED_STEPS": lambda rt: rt.failed_steps, "SKIPPED_STEPS": lambda rt: rt.skipped_steps,
                "HALTED_STEPS": lambda rt: rt.halted_steps, "RESULTS": lambda rt: rt.results,
                "VERIFIED_SWITCHES": lambda rt: rt.counter}

    def __init__(self, *args, rt=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.rt = rt

    def __getitem__(self, key):
        # 显式写进来的键优先（测试桩）；没写过才走只读视图。
        try:
            return super().__getitem__(key)
        except KeyError:
            pass
        if key == "ONLY":
            return self.rt.only
        if key == "HALTED":
            return self.rt.halted
        if key == "SkipStep":
            return recipe_runtime.SkipStep
        if key in self._RT_VIEW:
            return self._RT_VIEW[key](self.rt)
        if key in ("page", "require", "skip", "require_switches", "skip_in_safe_mode", "start_or_skip"):
            return getattr(self.rt, key)
        return self._library_view(key)

    def _library_view(self, key):
        """测试读库助手用的视图：数据可点名的实现 + 面助手，都直接在 `recipe_lib` 上取（ADR-0040）。"""
        import functools
        fn = interpreter.LIBRARY.get(key)
        if fn is None and key in recipe_lib.__all__:
            fn = getattr(recipe_lib, key)
        if fn is None:
            raise KeyError(key)
        if isinstance(fn, type):                 # MenuState 这类 namedtuple
            return fn
        if key in ("title_key", "_labelled"):    # 纯函数：不绑协作者
            return fn
        if key == "labels":                      # `labels(p, root=None)`
            return functools.partial(fn, self.rt.p)
        return functools.partial(fn, self.rt.p, self.rt)

    def __setitem__(self, key, value):
        if key == "ONLY":
            self.rt.only = value
            return
        if key == "HALTED":
            self.rt.halted = value
            return
        super().__setitem__(key, value)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


class LoadedCatalog:
    """装载后的数据：这次执行、例外模块命名空间、按书写顺序排好的段。形状对齐 `LoadedRecipe`。"""

    def __init__(self, path: str, namespace: dict, rt: recipe_runtime.Runtime):
        self.path = path
        self.namespace = namespace
        self.rt = rt

    @property
    def steps(self):
        return sorted(self.rt.steps, key=lambda item: item.line)

    def run(self) -> None:
        """执行这次装载的段，最后调用数据声明的尾钩子（没有就不做）。同一时刻只允许一个活动执行。"""
        with self.rt.activate():
            self.rt.run()


def _toml_path(path) -> Path:
    """数据文件：给了目录就在里面找唯一的 `.toml`；给了文件就用它。"""
    target = Path(path)
    if target.is_dir():
        found = sorted(target.glob("*.toml"))
        if len(found) != 1:
            raise FileNotFoundError(f"{target} 里应当恰有一份 .toml，实际 {len(found)} 份")
        return found[0]
    return target


def _exception_source(toml: Path) -> tuple[str, str] | None:
    """同目录同名的 `.py` 是本机例外函数（有才写）；返回 (源码, 路径)，没有则 None。"""
    companion = toml.with_suffix(".py")
    if companion.is_file():
        return companion.read_text(encoding="utf-8"), str(companion)
    return None


# 按名字点名实现的 op：`lib` / `require_lib` / `if_lib` / `return_lib` / `code` 的 `name`、`off` 的
# `only_code`、段级 `code`。名字写错在装载期报（ADR-0037 的承诺，#1289）。
_NAMED_OPS = frozenset({"lib", "require_lib", "if_lib", "return_lib", "code"})


def _named(ops, where):
    """(位置, 名字)：嵌套 `ops` / `else_ops` 一起走，位置是下标链。

    `let` 点名的实现写在 `lib` 上（`name` 是它绑定的名字）；`if_lib_any` 里带 `method` 的调用是
    Phone 门面方法名（另一套集合，属门面），不在这里校验。"""
    for index, op in enumerate(ops):
        place = f"{where}第 {index + 1} 个 op"
        kind = op.get("kind")
        if kind in _NAMED_OPS:
            yield place, op["name"]
        elif kind == "let":
            yield place, op["lib"]
        elif kind == "off" and "only_code" in op:
            yield place, op["only_code"]
        elif kind == "if_lib_any":
            for number, call in enumerate(op["calls"], 1):
                if "method" not in call:
                    yield f"{place} 的第 {number} 个 call", call["name"]
        for key in ("ops", "else_ops"):
            if key in op:
                yield from _named(op[key], f"{place} 的 {key} ")
        # 实参里的回调块（`close_named(..., reopen={ops = [...]})`）：块里的 op 与顶层同规则，写错的
        # 名字同样在装载期报（#1371 的再入，schema 已按同一条白名单校验过形状）。
        args, kwargs = op.get("args"), op.get("kwargs")
        values = (args if isinstance(args, list) else []) + (
            list(kwargs.values()) if isinstance(kwargs, Mapping) else [])
        for value in values:
            if isinstance(value, Mapping) and "ops" in value:
                yield from _named(value["ops"], f"{place} 的实参块 ")


def _legal_names(g) -> set[str]:
    """数据可点名的实现集合：`interpreter.LIBRARY` 的键 ∪ 例外模块命名空间的可调用名字。

    `_resolve` 与 `code=` 都从这两处取，而点名的实现拿到就调，常量与导入的模块指过去只会
    `TypeError`，所以「合法」按 callable 判。"""
    return set(interpreter.LIBRARY) | {
        name for name, value in g.items() if callable(value) and not name.startswith("__")}


def _check_names(data, legal) -> None:
    """把数据点名的名字对一遍库与本机例外函数：写错一个名字在这里就报，不等真机跑到那一段。

    报错带段名、下标链与相近候选（`difflib`，与 `devtools/test_anchors.py` 同一手法）。"""
    ordered = sorted(legal)
    for index, segment in enumerate(data["segment"]):
        where = f"第 {index + 1} 段「{segment['name']}」"
        wanted = [(where, segment["code"])] if "code" in segment else list(_named(segment["ops"], where))
        for place, name in wanted:
            if name in legal:
                continue
            close = difflib.get_close_matches(name, ordered, n=3)
            hint = f"；相近的名字：{'、'.join(close)}" if close else ""
            raise schema.SchemaError(
                f"{place} 点名的 {name!r} 既不在库里，也不是本机例外函数{hint}")


def _var_refs(value) -> list[str]:
    """一张表 / 一组表里所有 `{expr = "var", name = …}` 引用到的名字。"""
    if isinstance(value, Mapping):
        if value.get("expr") == "var":
            return [value["name"]]
        return [name for inner in value.values() for name in _var_refs(inner)]
    if isinstance(value, list):
        return [name for inner in value for name in _var_refs(inner)]
    return []


def _check_block(ops, where, outer, legal) -> None:
    """一块 op（段体，或某一支的 `ops` / `else_ops`）：按书写顺序核对引用与绑定。

    引用只认「这块或外层已经绑过的名字」；分支里绑的名字出了分支就看不见——运行期那一支没走时
    名字根本不存在，装载期放过它就等于把 `KeyError` 推迟到真机上。"""
    bound = set(outer)
    for index, op in enumerate(ops):
        place = f"{where}第 {index + 1} 个 op"
        # `if_var` 的 `name` 也是一个变量引用（它读那个绑定的值），其余引用都写在表形态的实参里。
        refs = [name for key, value in op.items() if key not in ("ops", "else_ops")
                for name in _var_refs(value)]
        if op.get("kind") == "if_var":
            refs.append(op["name"])
        for name in refs:
            if name in bound:
                continue
            known = (f"本段这一处已绑定的是 {sorted(bound)}" if bound
                     else "本段还没有绑定任何名字（先写一条 let）")
            raise schema.SchemaError(f"{place} 引用的名字 {name!r} 在这里还没有绑定；{known}")
        if op.get("kind") == "let":
            if op["name"] in legal:
                raise schema.SchemaError(
                    f"{place} 绑定的名字 {op['name']!r} 与库 / 本机实现同名，读的人分不清；换一个名字")
            bound.add(op["name"])
        for key in ("ops", "else_ops"):
            if key in op:
                _check_block(op[key], f"{place} 的 {key} ", bound, legal)


def _check_bindings(data, legal) -> None:
    """段内变量（#1373）：绑定的名字只在段内、只在绑定它的那条 op 之后可见，引用未绑定的名字装载期报。"""
    for index, segment in enumerate(data["segment"]):
        if "ops" in segment:
            _check_block(segment["ops"], f"第 {index + 1} 段「{segment['name']}」", set(), legal)


def load(path, p, only=(), clock=None, namespace=None) -> LoadedCatalog:
    """装载一份 catalog 数据（不执行任何段）。`only` 为空表示「全部段」。"""
    toml = _toml_path(path)
    data = tomllib.loads(toml.read_text(encoding="utf-8"))
    schema.validate(data)

    rt = recipe_runtime.Runtime(p, list(only), clock)
    # 例外函数的模块命名空间：装载器只往里 exec 本机代码，不注入 p / rt / 常量——那是注入面。
    g: dict = CatalogScope(namespace or {}, rt=rt)
    rt.namespace = g

    exception = _exception_source(toml)
    if exception is not None:
        source, filename = exception
        exec(compile(source, filename, "exec"), g)   # noqa: S102 - 本机例外函数，只此一处

    # 每机型常量：toml 的 `[const]` 与例外模块的全大写模块级名字。只读视图，值是共享对象。
    constants = dict(data.get("const", {}))
    constants.update({key: value for key, value in g.items()
                      if key.isupper() and not callable(value)})
    rt.constants = MappingProxyType(constants)

    for hook in ("tail", "guard", "detail", "wrap"):
        if hook in data:
            g[hook] = g[data[hook]]

    legal = _legal_names(g)
    _check_names(data, legal)
    _check_bindings(data, legal)

    for index, segment in enumerate(data["segment"]):
        rt.steps.append(Step(segment["name"], interpreter.segment_action(segment, p, rt, g), index))
    return LoadedCatalog(str(toml), g, rt)
