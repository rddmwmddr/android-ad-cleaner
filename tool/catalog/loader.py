"""catalog 的装载入口：「读一个目录/文件 → 可执行对象」（ADR-0038）。

这是数据的唯一执行入口，校验器与解释器共用：`load()` 先 `schema.validate()`，再按同一份数据建出
段 action。返回的 `LoadedCatalog` 与 `recipe_loader.LoadedRecipe` 同形（`.namespace` / `.rt` /
`.steps` / `.run()`），所以 `tests/fixtures.load_recipe` 与调用序列快照驱动不必区分两种格式。

装载只做四件事：读数据、校验、建出例外模块命名空间与这次执行的 `rt`（例外 `.py` 是普通模块，
exec 进一个 dict 供 `code=` 与钩子按名字取）、按段登记 action。真正的执行在 `LoadedCatalog.run()`
里，段一律经 `Runtime.run_step`，段归属不断。
"""
import tomllib
from pathlib import Path
from types import MappingProxyType

import recipe_runtime
from recipe_runtime import Step

from . import interpreter, schema


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
        """测试读库助手用的视图：`__all__` 里的实现 + 提升进库的本机助手。"""
        import functools
        import recipe_nav
        import recipe_steps
        import recipe_strategies
        fn = interpreter.LIBRARY.get(key)
        if fn is None:
            for module in (recipe_nav, recipe_strategies, recipe_steps):
                value = getattr(module, key, None)
                if value is not None and not key.startswith("__"):
                    fn = value
                    break
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

    for index, segment in enumerate(data["segment"]):
        rt.steps.append(Step(segment["name"], interpreter.segment_action(segment, p, rt, g), index))
    return LoadedCatalog(str(toml), g, rt)
