"""机型库（#1269）：按家族拆开的词汇与策略，外加跨家族共享的 `shared.py`。

一个家族一个文件（`huawei` / `samsung` 目前没有实现，就不建文件）；文件内分「词汇 / 策略」两节。
归属按家族数算：只被一个家族用到的进 `recipe_lib/<家族>.py`，被 ≥2 个家族用到的进 `shared.py`。
`tool/recipe_nav.py` / `recipe_strategies.py` / `recipe_steps.py` 是稳定 import 面，只做重导出。
"""
from . import shared
from . import xiaomi, oppo, vivo, honor, meizu

MODULES = (shared, xiaomi, oppo, vivo, honor, meizu)
