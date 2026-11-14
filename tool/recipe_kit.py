"""机型脚本的执行作用域：`p`、`rt` 与共享助手由装载器写进来，脚本不再自己定义这些名字（沿用 #838）。

唯一的装载点是 `tool/recipe_loader.py`（ADR-0037）：它建出这次的 `rt`（`recipe_runtime.Runtime`），
调 `preamble(p, g, rt)` 把两个协作者、声明式段装饰器、跳过 / 断言 / 台账出口与三张注入面写进执行
作用域，再 `exec` 模块体。`@step` 只登记段名，真正执行由 `rt.run()` 负责——导入一份脚本不产生任何
设备动作。

脚本顶部那句 `from recipe_kit import step`（静态检查与编辑器用）落到本模块的 `step()`：它按「当前
这次执行」解析，同一时刻只允许一个活动执行（`Runtime.activate()`）。

公共导航助手另住 `recipe_nav`、拨动策略另住 `recipe_strategies`、公共段体另住 `recipe_steps`：
`preamble()` 写完生命周期与台账后依次调它们的 `install()`（导航 → 策略 → 段体，闭包对名字都是
调用时现取，顺序不影响语义），本模块只管生命周期与台账（沿用 #1150、#1209、#1244 的注入面）。
"""

from typing import Any

import recipe_nav
import recipe_strategies
import recipe_steps
from recipe_runtime import DONE as DONE, FAILED as FAILED, NOT_RUN as NOT_RUN, SKIPPED as SKIPPED
from recipe_runtime import LANDING as LANDING, WRONG_LANDING as WRONG_LANDING
from recipe_runtime import SAFE_MODE_PAGE_WIDE as SAFE_MODE_PAGE_WIDE
from recipe_runtime import DuplicateStep as DuplicateStep, MissingPackage as MissingPackage
from recipe_runtime import Runtime, SkipStep

# 静态导入 `from recipe_kit import p, rt, step` 的落点：前两个只给编辑器与类型检查看，真正的对象
# 每次装载由 `preamble()` 换掉；`step()` 按当前执行解析。
# 标成 Any：脚本在这两个名字上调的是 Phone 与 Runtime 的整张面，注解只能写成 Any（#1247）。
p: Any = None
rt: Any = None
_runtime = None


def __getattr__(name: str) -> Any:
    """注入名在类型层面可见（#1247）：`require` / `page` / `require_switches` 这些由 `preamble()`
    写进执行作用域，模块上没有对应的属性。脚本末尾的 `if TYPE_CHECKING:` 块才 import 它们，
    类型检查靠这一条认得出名字；运行时照旧抛 AttributeError，不在这里造一份代理对象。"""
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def preamble(p, g, rt=None):
    """把这次的执行写进 `g` 并原样返回它：`p` / `rt` / 声明式 `step`、出口与两个台账、三张注入面。

    `rt` 由装载器建好传进来（`tool/recipe_loader.py`）；测试直接调用时不传，按 `g` 里现有的
    `ONLY` 建一个新的。台账是 rt 上的同一批列表对象，`g["FAILED_STEPS"]` 等只是给既有调用点与
    测试读的别名——写台账的只有 `Runtime.run_step()`。

    `guard()` / `wrap()` / `detail()` / `tail()` 是四个可选的脚本侧钩子：段入口的型号守卫、
    段内包装（等价于以前 `with safe_ui():`）、失败时的页面摘要、收尾打印。脚本定义了就按它走，
    没定义就什么都不做 —— 大多数脚本不需要，前导也不替它们造一个。
    """
    global _runtime

    if rt is None:
        rt = Runtime(p, list(g.get("ONLY") or []))
    elif "ONLY" in g and g.get("ONLY") is not None:
        rt.only = g["ONLY"]           # 测试传进来的名单对象要保留：装载后改它仍然生效
    rt.namespace = g
    _runtime = rt
    globals()["p"] = p
    globals()["rt"] = rt

    g["p"] = p
    g["rt"] = rt
    g["ONLY"] = rt.only
    g["FAILED_STEPS"] = rt.failed_steps
    g["SKIPPED_STEPS"] = rt.skipped_steps
    g["HALTED_STEPS"] = rt.halted_steps
    g["RESULTS"] = rt.results
    g["step"] = rt.step

    def maybe(name, scrolls=6):
        return p.entry(name, scrolls=scrolls)

    g.update({"SkipStep": SkipStep, "skip": rt.skip, "require": rt.require,
              "maybe": maybe, "start_or_skip": rt.start_or_skip, "page": rt.page,
              "require_switches": rt.require_switches, "skip_in_safe_mode": rt.skip_in_safe_mode,
              "VERIFIED_SWITCHES": rt.counter})
    recipe_nav.install(p, g)
    recipe_strategies.install(p, g)
    recipe_steps.install(p, g)
    return g


def step(name):
    """脚本顶部 `from recipe_kit import step` 的落点：按当前这次执行登记段名。

    装载器先往执行作用域里写一份绑定当次执行的 `step`，脚本的静态导入随后把名字换成这一份；
    两者都只登记、不执行（ADR-0037）。没有活动执行时抛错，而不是把段悄悄丢掉。
    """
    if _runtime is None:
        raise RuntimeError("机型脚本必须在 recipe_loader 装载的执行里运行：当前没有活动执行（rt）")
    return _runtime.step(name)
