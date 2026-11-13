"""机型脚本的唯一装载器（ADR-0037）：`fast.execute` 的 run 分支、`adapt.check_draft`、`tests/fixtures.load_recipe` 都走这里。

装载一份脚本只做两件事：把 `p` / `rt` / `step` 与共享助手写进执行作用域，再 `exec` 模块体。
`@step` 在那一刻只登记段名并原样返回函数，所以导入一份脚本不产生任何设备动作；段过滤与执行
由 `LoadedRecipe.run()` 负责，顺序按函数定义行号。

`adapt gen` 现在产出的草稿带 import 头（`from recipe_kit import step`），与正式脚本走同一个入口；
`#1247` 之前的旧草稿没有 import 头，装载器仍注入 `step`，那句 `@step(...)` 因此照旧可用。

`RecipeScope` 是执行作用域的字典，测试装载（`tests/fixtures.load_recipe`）拿它当返回值：
`scope["rt"]` 是真的执行上下文，`scope["ONLY"]` 代理到 rt 上，`scope["VERIFIED_SWITCHES"]`
是引擎注入的计数器（`recipe_runtime.Counter`，比较时按 rt 上的数算），测试改名单、读回读确认数
时不必再碰脚本里的变量。
"""
from dataclasses import dataclass
from pathlib import Path

import recipe_kit
import recipe_runtime


class RecipeScope(dict):
    """执行作用域。字典本身仍是脚本的模块命名空间；下面两个名字代理到这次执行的 `rt`。

    `exec` 内的名字读写按字典本体走（CPython 不调子类的 `__getitem__`），所以脚本里读到的
    仍是注入进去的那一份；代理只服务测试侧的 `scope["ONLY"] = [...]` / `scope["VERIFIED_SWITCHES"]`。
    """

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


@dataclass
class LoadedRecipe:
    """装载后的脚本：模块命名空间、这次执行、以及按定义行号排好的段。"""
    path: str
    namespace: RecipeScope
    rt: recipe_runtime.Runtime

    @property
    def steps(self):
        return sorted(self.rt.steps, key=lambda item: item.line)

    def run(self):
        """执行这次装载的段，最后调用尾钩子；同一时刻只允许一个活动执行。"""
        with self.rt.activate():
            self.rt.run()


def _module_name(path) -> str:
    """模块名只用于报错与 `__name__`，不参与型号身份（那个来自脚本自己的 `MODELS`）。"""
    folder = Path(path).resolve().parent.name
    stem = Path(path).stem
    return "recipe_" + "_".join(part for part in (folder, stem) if part).replace(" ", "_").replace("-", "_")


def load(path, p, only=(), clock=None, namespace=None) -> LoadedRecipe:
    """装载一份脚本（不执行任何段）。`only` 为空表示「全部段」。"""
    source = Path(path).read_text(encoding="utf-8")
    rt = recipe_runtime.Runtime(p, list(only), clock)
    scope = RecipeScope(rt=rt)
    if namespace:
        scope.update(namespace)
    scope.update({"__name__": _module_name(path), "__file__": str(path)})
    rt.namespace = scope
    with rt.activate():
        recipe_kit.preamble(p, scope, rt)
        exec(compile(source, str(path), "exec"), scope)   # noqa: S102 - 机型脚本按路径装载成模块，入口只此一处
    return LoadedRecipe(str(path), scope, rt)


def run(path, p, only=(), clock=None, namespace=None):
    """装载并跑完一份脚本，返回 `LoadedRecipe`（`fast.execute` 的 run 分支与 `adapt` 自检共用）。"""
    recipe = load(path, p, only=only, clock=clock, namespace=namespace)
    recipe.run()
    return recipe
