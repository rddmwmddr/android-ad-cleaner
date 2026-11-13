"""机型脚本目录化（catalog）的内核：schema 校验 + 解释器 + 唯一装载入口（ADR-0038）。

用法只有一处：`catalog.load(path, p, only=…, clock=…)`，返回与 `recipe_loader.LoadedRecipe` 同形的
`LoadedCatalog`。`tool/recipe_loader.py` 的 `load()` 按路径分派到这里（`.toml` 或目录走 catalog，
`.py` 走现装载器），引擎、适配自检、测试装载因此仍只有一处入口。
"""
from .loader import LoadedCatalog, load
from .schema import SchemaError, validate, words

__all__ = ["LoadedCatalog", "SchemaError", "load", "validate", "words"]
