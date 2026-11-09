#!/usr/bin/env python3
"""配方验证台账：每份机型脚本最后一次真机验证。

数据在 recipes/verified.toml，key 是相对 recipes/ 的路径——`recipe.py` 与变体
（`recipe_android15.py` 这类）各记一条，不是目录级。一条记录四样：完整系统 build 串、
验证日期、验证人、档位。

  python3 tool/verify_ledger.py     每个配方文件一行，按距今天数降序；末行三档分布
                                    没有记录的写「未记录」，不会从输出里消失

脚本最后一次改动晚于验证日期的行标「待复核」：只看日期先后，不判改动性质（改一行注释也算）。
改动日期取 git 的作者日期，rebase 不改写它，换机器与重新 clone 也都一样。

记录的 build 与脚本声明的 `BUILD` 前缀对不上时标「build 不符」：脚本涨版本而记录还停在旧版，
就该重新验一次，而不是让它继续显示成验过。脚本没声明 `BUILD` 时无从比较，不标。

只读、只打印，不写文件。
"""
import os
import sys
import tomllib
from dataclasses import dataclass
from datetime import date

from commits import git
from recipe_meta import recipe_files, recipe_meta

TIERS = ("已验证", "部分验证", "未记录")
UNRECORDED = TIERS[-1]
BUCKETS = ("30 天以内", "31–90 天", "90 天以上")
REVIEW = "待复核"
BUILD_MISMATCH = "build 不符"


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
    build_mismatch: bool = False  # 记录的 build 不以脚本声明的 BUILD 开头，见 build_matches()


def recipe_paths(recipes_dir):
    """仓库里每个配方文件，相对 recipes/。变体各自成行，同一个目录下可以有多条。"""
    return [os.path.relpath(p, recipes_dir).replace(os.sep, "/") for p in recipe_files(recipes_dir)]


def declared_builds(recipes_dir):
    """每个配方文件声明的 BUILD 前缀，{相对路径: BUILD}。脚本没写 BUILD 时是空串。"""
    return {rel: recipe_meta(os.path.join(recipes_dir, rel))["build"] for rel in recipe_paths(recipes_dir)}


def build_matches(record_build, script_build):
    """记录的 build 串要以脚本声明的 BUILD 打头，脚本没声明 BUILD 时无从校验、一律算匹配。

    只做裸前缀比较，比引擎的 `run.build_ok()` 少一条 HyperOS 版本号回退：记录写的是设备
    实际报出来的 build，对不上就该有人去看一眼，而不是换个字段再比一次。
    """
    return not script_build or record_build.startswith(script_build)


def load(path):
    """已解析的台账：{相对路径: {build, date, by, tier}}。"""
    with open(path, "rb") as f:
        return tomllib.load(f)


def rows(recipes_dir, records, today, changed=None, builds=None):
    """每个配方文件一行，按距今天数降序；没有可信记录的排在最后。`records` 是已解析的台账，
    `today`、`changed`（{相对路径: 最后一次改动日期}）与 `builds`（{相对路径: 脚本的 BUILD}）
    都由调用方注入（测试不钉真实日期、不读真实脚本）。

    没有记录的配方照样出行、档位记「未记录」：缺数据不能让配方从输出里消失。档位是「未记录」
    时记录本身不可信，日期不参与天数、分档与待复核判定，build 也不参与前缀校验——没写就是没写，
    不该被读成「脚本涨版本了」。`builds` 里没有的路径不校验。
    """
    changed = changed or {}
    builds = builds or {}
    out = []
    for path in recipe_paths(recipes_dir):
        record = records.get(path, {})
        tier = record.get("tier") or UNRECORDED
        day = record.get("date", "")
        changed_on = changed.get(path, "")
        trusted = tier != UNRECORDED
        mismatch = trusted and path in records and not build_matches(record.get("build", ""),
                                                                     builds.get(path, ""))
        out.append(Row(path, record.get("build", ""), day, record.get("by", ""), tier,
                       _days_since(day, today) if trusted else None,
                       changed_on, trusted and _needs_review(day, changed_on), mismatch))
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


def render(recipes_dir, records, today, changed=None, builds=None):
    """命令行输出的全文：一行一份配方，列用制表符隔开，距今天数在路径之后；末尾一行三档分布。
    待复核与 build 不符接在行尾，两者同时成立时用「 · 」连起来。"""
    ledger_rows = rows(recipes_dir, records, today, changed, builds)
    lines = []
    for row in ledger_rows:
        if row.tier == UNRECORDED:
            lines.append(f"{row.path}\t{UNRECORDED}")
        else:
            marks = [name for name, on in ((REVIEW, row.review), (BUILD_MISMATCH, row.build_mismatch)) if on]
            tail = f"\t{' · '.join(marks)}" if marks else ""
            lines.append(f"{row.path}\t{row.days}\t{row.build}\t{row.date}\t{row.verifier}\t{row.tier}{tail}")
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
                            changed_dates(_dir), declared_builds(_dir)))
