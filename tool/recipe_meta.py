"""机型脚本：有哪些文件，以及头部的元数据（录制版本 `BUILD`、机型列表 `MODELS`、段名 `@step`）。

单独成模块是为了让非 CLI 代码读得到：`run.py` 一 import 就注入路径、导 adb、重配输出流、解析备份根目录。
"""
import glob
import os
import re
from typing import TypedDict


class RecipeMeta(TypedDict):
    """脚本头部的三段元数据。调用方按字段名取值，缺省时是空串 / 空列表，不是缺键。"""

    build: str
    steps: list[str]
    models: list[str]


def recipe_files(recipes_dir: str) -> list[str]:
    """`recipes_dir` 下每个机型脚本的路径，含 `recipe_android15.py` 这类变体。"""
    return sorted(glob.glob(os.path.join(recipes_dir, "*", "recipe*.py")))


def recipe_meta(path: str | os.PathLike[str]) -> RecipeMeta:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
    models = re.search(r'^MODELS\s*=\s*\[([^\]]*)\]', src, re.M)
    return {"build": m.group(1) if m else "", "steps": re.findall(r'^@step\("([^"]+)"\)', src, re.M),
            "models": re.findall(r'"([^"]+)"', models.group(1)) if models else []}
