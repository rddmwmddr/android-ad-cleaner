#!/usr/bin/env python3
"""配方验证台账：每份机型脚本最后一次真机验证。

数据在 recipes/verified.toml，key 是相对 recipes/ 的路径——`recipe.py` 与变体
（`recipe_android15.py` 这类）各记一条，不是目录级。一条记录四样：完整系统 build 串、
验证日期、验证人、档位。

  python3 tool/verify_ledger.py     每个配方文件一行，按距今天数降序；末行三档分布
                                    没有记录的写「未记录」，不会从输出里消失

脚本最后一次改动晚于验证日期的行标「待复核」：只看日期先后，不判改动性质（改一行注释也算）。
改动日期取 git 的作者日期，rebase 不改写它，换机器与重新 clone 也都一样。

只读、只打印，不写文件。
"""
import os
import sys
import tomllib
from dataclasses import dataclass
from datetime import date

from commits import git
from recipe_meta import recipe_files

TIERS = ("已验证", "部分验证", "未记录")
UNRECORDED = TIERS[-1]
BUCKETS = ("30 天以内", "31–90 天", "90 天以上")
REVIEW = "待复核"


@dataclass(frozen=True)
class Row:
    """一份配方在台账里的样子。没有记录时档位是「未记录」，其余字段为空。"""
    path: str                   # 相对 recipes/ 的路径，如 xiaomi-M154FF/recipe.py
    build: str                  # 记录的完整系统 build 串
    date: str                   # YYYY-MM-DD
    verifier: str               # @login 或 机主
    tier: str
    days: int | None            # 距 today 多少天；没有日期是 None
    changed_on: str = ""        # 脚本最后一次改动的提交日期；取不到为空
    review: bool = False        # 脚本改动晚于验证日期，见 _needs_review()


def recipe_paths(recipes_dir):
    """仓库里每个配方文件，相对 recipes/。变体各自成行，同一个目录下可以有多条。"""
    return [os.path.relpath(p, recipes_dir).replace(os.sep, "/") for p in recipe_files(recipes_dir)]


def load(path):
    """已解析的台账：{相对路径: {build, date, by, tier}}。"""
    with open(path, "rb") as f:
        return tomllib.load(f)


def rows(recipes_dir, records, today, changed=None):
    """每个配方文件一行，按距今天数降序；没有可信记录的排在最后。`records` 是已解析的台账，
    `today` 与 `changed`（{相对路径: 最后一次改动日期}）都由调用方注入（测试不钉真实日期）。

    没有记录的配方照样出行、档位记「未记录」：缺数据不能让配方从输出里消失。档位是「未记录」
    时记录本身不可信，日期不参与天数、分档与待复核判定。
    """
    changed = changed or {}
    out = []
    for path in recipe_paths(recipes_dir):
        record = records.get(path, {})
        tier = record.get("tier") or UNRECORDED
        day = record.get("date", "")
        changed_on = changed.get(path, "")
        trusted = tier != UNRECORDED
        out.append(Row(path, record.get("build", ""), day, record.get("by", ""), tier,
                       _days_since(day, today) if trusted else None,
                       changed_on, trusted and _needs_review(day, changed_on)))
    return sorted(out, key=lambda row: (row.days is None, -(row.days or 0), row.path))


def _days_since(day, today):
    """没有日期返回 None；验证日期在未来时按 0 天算，不让它变成负数。"""
    return None if not day else max((today - date.fromisoformat(day)).days, 0)


def _needs_review(day, changed_on):
    """脚本最后一次改动晚于验证日期时标「待复核」。只看日期先后，不判定改动性质；
    缺验证日期或缺改动日期时无从比较，不标。"""
    if not day or not changed_on:
        return False
    return date.fromisoformat(changed_on) > date.fromisoformat(day)


def distribution(ledger_rows):
    """三档计数：(30 天以内, 31–90 天, 90 天以上)。没有天数的行并入最后一档，
    三档之和因此等于行数。"""
    counts = [0, 0, 0]
    for row in ledger_rows:
        counts[_bucket(row.days)] += 1
    return tuple(counts)


def _bucket(days):
    if days is not None and days <= 30:
        return 0
    if days is not None and days <= 90:
        return 1
    return 2


def _footer(ledger_rows):
    parts = " · ".join(f"{name} {n}" for name, n in zip(BUCKETS, distribution(ledger_rows)))
    return f"{parts}（共 {len(ledger_rows)} 份）"


def render(recipes_dir, records, today, changed=None):
    """命令行输出的全文：一行一份配方，列用制表符隔开，距今天数在路径之后；末尾一行三档分布。"""
    ledger_rows = rows(recipes_dir, records, today, changed)
    lines = []
    for row in ledger_rows:
        if row.tier == UNRECORDED:
            lines.append(f"{row.path}\t{UNRECORDED}")
        else:
            mark = f"\t{REVIEW}" if row.review else ""
            lines.append(f"{row.path}\t{row.days}\t{row.build}\t{row.date}\t{row.verifier}\t{row.tier}{mark}")
    lines.append(_footer(ledger_rows))
    return "\n".join(lines) + "\n"


def changed_dates(recipes_dir):
    """每个配方文件最后一次改动的日期，{相对路径: YYYY-MM-DD}。

    取 git 的作者日期（`%as`）而不是文件 mtime 或提交日期：mtime 被 clone / checkout 刷成当下，
    提交日期被 rebase 改写，只有作者日期在两者下都不变。取不到 git 时返回空字典，输出就不标「待复核」。
    """
    root = os.path.dirname(os.path.abspath(recipes_dir))
    prefix = os.path.basename(os.path.abspath(recipes_dir))
    out = {}
    for rel in recipe_paths(recipes_dir):
        try:
            stamp = git("-C", root, "log", "-1", "--format=%as", "--", f"{prefix}/{rel}").strip()
        except (OSError, RuntimeError):
            return {}
        if stamp:
            out[rel] = stamp
    return out


def _recipes_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _dir = _recipes_dir()
    sys.stdout.write(render(_dir, load(os.path.join(_dir, "verified.toml")), date.today(),
                            changed_dates(_dir)))
