"""机型脚本的段体注入面（#1209）：跨文件代码逐字相同的 `@step` 段体收在这里。

`recipe_kit.preamble()` 写完生命周期与台账之后调用 `install(p, g)`，把段体补进同一个执行作用域。
脚本侧只留一行调用：`@step("下载管理")` 加 `def _(): downloads()`，段体本身搬到这里。

与 `recipe_nav` 同一形状、同一方向：不 import `recipe_kit`，前导名字一律按 `g` 现取；段体依赖的
模块常量同样按名字现取（`g["HOT"]`），既不内联进实现、也不改成数据参数（沿用 #1149 的定案）。同一段文字在
不同脚本里可能挂着不同的取值，逐字相同的代码不等于相同的数据（小米系 `HOT` 有一份多「千问」）。

`STEPS` 现在为空：家族票逐批往里加，加一批、脚本才删一批本地副本。搬代码不改现有脚本的行为
——脚本本地定义后执行，覆盖注入的名字；删掉本地那份之后才开始走注入版。

字段：名字 → 工厂。工厂收 `(p, g)`，只造闭包、不碰手机，返回写进执行作用域的那个函数。
守卫比对脚本里还留着的 `@step` 段体与注入实现，AST 归一（剥注释、docstring、装饰器与折行）后
相同即红，见 `tests/test_recipe_steps.py`。
"""

from collections.abc import Callable
from typing import Any

STEPS: dict[str, Callable[[Any, Any], Callable[..., Any]]] = {}


def install(p: Any, g: dict[str, Any]) -> None:
    """把段体写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in STEPS.items():
        g[name] = factory(p, g)
