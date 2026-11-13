"""机型脚本：有哪些文件，以及头部的元数据（录制版本 `BUILD`、机型列表 `MODELS`、段名 `@step`）。

单独成模块是为了让非 CLI 代码读得到：`run.py` 一 import 就注入路径、导 adb、重配输出流、解析备份根目录。
"""
import glob
import os
import re
import tomllib
from typing import TypedDict


class RecipeMeta(TypedDict):
    """脚本头部的三段元数据。调用方按字段名取值，缺省时是空串 / 空列表，不是缺键。"""

    build: str
    steps: list[str]
    models: list[str]


def recipe_files(recipes_dir: str) -> list[str]:
    """`recipes_dir` 下每个型号的「活脚本」路径，按型号目录排。

    一个型号目录（`recipes/<家族>/<型号>/`）只出一份活脚本：有 `recipe*.py`（含
    `recipe_android15.py` 这类变体）时读这些；没有 `recipe*.py`、只有 `<型号>.toml` 时读那份数据
    （ADR-0038）。转成数据之后脚本不会从台账 / 类型检查里消失（#1270）。迁移期 `.py` 优先，
    `.toml` 是与它等价的副本（如 `V1986A`）。"""
    out = []
    for model_dir in sorted(glob.glob(os.path.join(recipes_dir, "*", "*"))):
        if not os.path.isdir(model_dir):
            continue
        py = sorted(glob.glob(os.path.join(model_dir, "recipe*.py")))
        out += py if py else sorted(glob.glob(os.path.join(model_dir, "*.toml")))
    return out


def recipe_id(path: str | os.PathLike[str]) -> str:
    """脚本对外的稳定身份：所在型号目录名（`PYB110`）。目录已按家族分组（`recipes/<家族>/<型号>`），身份取型号段。"""
    return os.path.basename(os.path.dirname(os.fspath(path)))


def recipe_meta(path: str | os.PathLike[str]) -> RecipeMeta:
    if str(path).endswith(".toml"):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        steps = [segment.get("name", "") for segment in data.get("segment", [])]
        return {"build": str(data.get("build", "")), "steps": steps,
                "models": [str(model) for model in data.get("models", [])]}
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
    models = re.search(r'^MODELS\s*=\s*\[([^\]]*)\]', src, re.M)
    return {"build": m.group(1) if m else "", "steps": re.findall(r'^@step\("([^"]+)"\)', src, re.M),
            "models": re.findall(r'"([^"]+)"', models.group(1)) if models else []}
