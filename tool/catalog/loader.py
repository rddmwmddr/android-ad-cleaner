"""catalog 的装载入口：「读一个目录/文件 → 可执行对象」（ADR-0038）。

这是数据的唯一执行入口，校验器与解释器共用：`load()` 先 `schema.validate()`，再按同一份数据建出
段 action。返回的 `LoadedCatalog` 与 `recipe_loader.LoadedRecipe` 同形（`.namespace` / `.rt` /
`.steps` / `.run()`），所以 `tests/fixtures.load_recipe` 与调用序列快照驱动不必区分两种格式。

装载只做四件事：读数据、校验、把这次的执行作用域建起来（`recipe_kit.preamble()` 照旧装注入面，
迁移期库仍是工厂闭包）、按段登记 action。真正的执行在 `LoadedCatalog.run()` 里，段一律经
`Runtime.run_step`，段归属不断。
"""
import time
import tomllib
from pathlib import Path

import recipe_kit
import recipe_runtime
from recipe_runtime import Step

from . import interpreter, schema


class CatalogScope(dict):
    """catalog 的执行作用域：字典本体是例外函数/注入名的命名空间，`ONLY` / `HALTED` 代理到这次执行的 `rt`。

    与 `recipe_loader.RecipeScope` 同一形状：测试装载（`tests/fixtures.load_recipe`）返回它、拿它当
    脚本命名空间用，`scope["ONLY"] = [...]` 改的是 `rt.only`，`scope["rt"].run_step(...)` 才按新名单跑。
    `exec` 写名字走字典本体（CPython 不调子类的 `__setitem__`），代理只服务测试侧的显式读写。"""

    def __init__(self, *args, rt=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.rt = rt

    def __getitem__(self, key):
        if key == "ONLY":
            return self.rt.only
        if key == "HALTED":
            return self.rt.halted
        return super().__getitem__(key)

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
    """装载后的数据：这次执行、执行作用域、按书写顺序排好的段。形状对齐 `LoadedRecipe`。"""

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
    g: dict = CatalogScope(namespace or {}, rt=rt)
    g["time"] = clock or time
    g.update(data.get("const", {}))
    rt.namespace = g
    recipe_kit.preamble(p, g, rt)

    exception = _exception_source(toml)
    if exception is not None:
        source, filename = exception
        exec(compile(source, filename, "exec"), g)   # noqa: S102 - 本机例外函数，只此一处

    for hook in ("tail", "guard", "detail", "wrap"):
        if hook in data:
            g[hook] = g[data[hook]]

    for index, segment in enumerate(data["segment"]):
        rt.steps.append(Step(segment["name"], interpreter.segment_action(segment, g), index))
    return LoadedCatalog(str(toml), g, rt)
