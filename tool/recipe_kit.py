"""机型脚本运行时的显式 re-export（#1268 拆除注入面之后只剩这一层）。

`preamble()` / `install()` / `@step` 与执行作用域都已删除：例外函数是普通模块级函数，收 `(p, rt)`；
库实现住在 `recipe_nav` / `recipe_strategies` / `recipe_steps`，由 `tool/catalog` 按名字分派。
本模块只保留引擎名词的 re-export，`fast.recipe_kit` 与既有 import 不需要跟着改名。
"""
from recipe_runtime import DONE as DONE, FAILED as FAILED, NOT_RUN as NOT_RUN, SKIPPED as SKIPPED
from recipe_runtime import LANDING as LANDING, WRONG_LANDING as WRONG_LANDING
from recipe_runtime import SAFE_MODE_PAGE_WIDE as SAFE_MODE_PAGE_WIDE
from recipe_runtime import DuplicateStep as DuplicateStep, MissingPackage as MissingPackage
from recipe_runtime import Runtime as Runtime, SkipStep as SkipStep

__all__ = ["DONE", "FAILED", "NOT_RUN", "SKIPPED", "LANDING", "WRONG_LANDING",
           "SAFE_MODE_PAGE_WIDE", "DuplicateStep", "MissingPackage", "Runtime", "SkipStep"]
