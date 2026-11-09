#!/usr/bin/env python3
"""配方验证台账：每份机型脚本最后一次真机验证。

数据在 recipes/verified.toml，key 是相对 recipes/ 的路径——`recipe.py` 与变体
（`recipe_android15.py` 这类）各记一条，不是目录级。一条记录四样：完整系统 build 串、
验证日期、验证人、档位。

  python3 tool/verify_ledger.py     每个配方文件一行；没有记录的写「未记录」，不会从输出里消失

只读、只打印，不写文件。
"""
import os
import sys
import tomllib
from dataclasses import dataclass
from datetime import date

from recipe_meta import recipe_files

TIERS = ("已验证", "部分验证", "未记录")
UNRECORDED = TIERS[-1]


@dataclass(frozen=True)
class Row:
    """一份配方在台账里的样子。没有记录时档位是「未记录」，其余字段为空。"""
    path: str                   # 相对 recipes/ 的路径，如 xiaomi-M154FF/recipe.py
    build: str                  # 记录的完整系统 build 串
    date: str                   # YYYY-MM-DD
    verifier: str               # @login 或 机主
    tier: str
    days: int | None            # 距 today 多少天；没有日期是 None


def recipe_paths(recipes_dir):
    """仓库里每个配方文件，相对 recipes/。变体各自成行，同一个目录下可以有多条。"""
    return [os.path.relpath(p, recipes_dir).replace(os.sep, "/") for p in recipe_files(recipes_dir)]


def load(path):
    """已解析的台账：{相对路径: {build, date, by, tier}}。"""
    with open(path, "rb") as f:
        return tomllib.load(f)


def rows(recipes_dir, records, today):
    """每个配方文件一行。`records` 是已解析的台账，`today` 由调用方注入（测试不钉真实日期）。

    没有记录的配方照样出行、档位记「未记录」：缺数据不能让配方从输出里消失。
    """
    out = []
    for path in recipe_paths(recipes_dir):
        record = records.get(path, {})
        day = record.get("date", "")
        out.append(Row(path, record.get("build", ""), day, record.get("by", ""),
                       record.get("tier") or UNRECORDED, _days_since(day, today)))
    return out


def _days_since(day, today):
    """没有日期返回 None。"""
    return None if not day else (today - date.fromisoformat(day)).days


def render(recipes_dir, records, today):
    """命令行输出的全文：一行一份配方，列用制表符隔开。"""
    lines = []
    for row in rows(recipes_dir, records, today):
        if row.tier == UNRECORDED:
            lines.append(f"{row.path}\t{UNRECORDED}")
        else:
            lines.append(f"{row.path}\t{row.build}\t{row.date}\t{row.verifier}\t{row.tier}")
    return "\n".join(lines) + "\n"


def _recipes_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _dir = _recipes_dir()
    sys.stdout.write(render(_dir, load(os.path.join(_dir, "verified.toml")), date.today()))
