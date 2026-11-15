"""recipe_strategies 是 `recipe_lib` 的稳定 import 面（#1269 拆库、#1344 收名字表）：只剩转发。

名字的唯一 owner 是 `recipe_lib/__init__.py`；机型例外 `.py` 与事实层仍从这里取名字，所以这个模块
要留着。别往这里加实现或名单——加了就与 owner 分叉，`tests/test_recipe_nav.py` 的 `SurfaceTests` 会红。"""
import os as _os, sys as _sys
_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # 仓库根：recipe_lib 在它下面
if _root not in _sys.path:
    _sys.path.insert(0, _root)
from recipe_lib import *  # noqa: F403 - 兼容壳：名单与实现都在 recipe_lib，这里只转发
from recipe_lib import __all__ as __all__
