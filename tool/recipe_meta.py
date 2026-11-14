"""机型脚本：有哪些文件，以及头部的元数据（录制版本 `build`、机型列表 `models`、段名）。

单独成模块是为了让非 CLI 代码读得到：`run.py` 一 import 就注入路径、导 adb、重配输出流、解析备份根目录。
"""
import glob
import os
import tomllib
from typing import TypedDict


class RecipeMeta(TypedDict):
    """脚本头部的三段元数据。调用方按字段名取值，缺省时是空串 / 空列表，不是缺键。"""

    build: str
    steps: list[str]
    models: list[str]


def recipe_files(recipes_dir: str) -> list[str]:
    """`recipes_dir` 下每个型号的页面树数据路径，按型号目录排。

    一个型号目录（`recipes/<家族>/<型号>/`）只出一份 `<型号>.toml`（ADR-0038）；`.py` 机型脚本
    已随注入面删除（#1268），装载器也不再收它。"""
    out = []
    for model_dir in sorted(glob.glob(os.path.join(recipes_dir, "*", "*"))):
        if not os.path.isdir(model_dir):
            continue
        out += sorted(glob.glob(os.path.join(model_dir, "*.toml")))
    return out


def recipe_id(path: str | os.PathLike[str]) -> str:
    """脚本对外的稳定身份：所在型号目录名（`PYB110`）。目录已按家族分组（`recipes/<家族>/<型号>`），身份取型号段。"""
    return os.path.basename(os.path.dirname(os.fspath(path)))


def recipe_meta(path: str | os.PathLike[str]) -> RecipeMeta:
    """一份页面树数据的头部元数据；`build` / `models` / 段名缺省时是空串 / 空列表。"""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    steps = [segment.get("name", "") for segment in data.get("segment", [])]
    return {"build": str(data.get("build", "")), "steps": steps,
            "models": [str(model) for model in data.get("models", [])]}
