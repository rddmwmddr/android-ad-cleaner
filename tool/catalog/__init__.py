"""机型脚本目录化（catalog）的内核：schema 校验 + 解释器 + 唯一装载入口（ADR-0038）。

用法只有一处：`catalog.load(path, p, only=…, clock=…)`，返回与 `recipe_loader.LoadedRecipe` 同形的
`LoadedCatalog`。`tool/recipe_loader.py` 是唯一的装载入口，它把路径转到这里：数据形态只认 catalog
（`.toml` 或目录），`.py` 脚本分支已删除（#1268），传 `.py` 会直接失败。
"""
from .loader import LoadedCatalog, load
from .schema import SchemaError, validate, words

__all__ = ["LoadedCatalog", "SchemaError", "load", "validate", "words"]
