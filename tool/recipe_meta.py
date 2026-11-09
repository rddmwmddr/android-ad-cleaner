"""机型脚本头部的元数据：录制版本（`BUILD`）、机型列表（`MODELS`）与段名（`@step`）。

单独成模块是为了让非 CLI 代码读得到：`run.py` 一 import 就注入路径、导 adb、重配输出流。
"""
import re


def recipe_meta(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
    models = re.search(r'^MODELS\s*=\s*\[([^\]]*)\]', src, re.M)
    return {"build": m.group(1) if m else "", "steps": re.findall(r'^@step\("([^"]+)"\)', src, re.M),
            "models": re.findall(r'"([^"]+)"', models.group(1)) if models else []}
