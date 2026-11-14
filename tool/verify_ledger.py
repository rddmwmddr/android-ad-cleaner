#!/usr/bin/env python3
"""配方验证台账：每份机型脚本最后一次真机验证。

数据在 recipes/verified.toml，key 是相对 recipes/ 的路径——`recipe.py` 与变体
（`recipe_android15.py` 这类）各记一条，不是目录级。一条记录六样：完整系统 build 串、
验证日期、验证人、覆盖度（`tier`）、证据来源（`evidence`）、段体哈希（`body_hash`）。
覆盖度与证据来源是两个正交维度：前者是「跑到什么程度」，后者是「凭什么算跑过」（沿用 #1124）。

  python3 tool/verify_ledger.py       每个配方文件一行，按距今天数降序；末行三档分布
                                      没有记录的写「未记录」，不会从输出里消失
  python3 tool/verify_ledger.py --hash
                                      每份配方一行「路径<TAB>段体哈希」，只打印不写文件；
                                      真机验证或发版后照抄进 recipes/verified.toml

记录的段体哈希与脚本现在算出来的对不上时标「待复核」：判据是段体内容改过没有，不是文件改过
没有（沿用 #916 的台账；判据从提交日期换成哈希见 #1242）。段体哈希把段体解析成 AST，去掉注释
与 docstring，再序列化后拼起来取 sha256 前 16 位；段名参与拼接，所以改段名也会标「待复核」。

两种形态各算各的。`.py` 机型脚本只取 `@step(...)` 段体，注释、折行、函数顺序与装饰器都不进，
把模块级助手搬进库因此不算改。页面树数据取每个 `[[segment]]` 的归一 JSON（键顺序与段的先后不
影响），再整份拼上同名例外 `.py` 的模块体——`code=` 的那些段就住在那儿，按整文件算而不按段
收窄：`code=` 函数还会调用同文件的助手、读模块级常量，按段收窄得把解释器的名字解析再复刻
一遍，漏一个就是又一次「改过看不出来」。整文件那头顺序也算，所以挪函数、把助手搬进 `recipe_lib`
都会翻成待复核（#1276）。

旧记录没有哈希时无从比较，不标「待复核」——那是「尚未建立基线」，不是「改过」。

记录的 build 与脚本声明的 `BUILD` 前缀对不上时标「build 不符」：脚本涨版本而记录还停在旧版，
就该重新验一次，而不是让它继续显示成验过。脚本没声明 `BUILD` 时无从比较，不标。

只读、只打印，不写文件。
"""
import ast
import hashlib
import json
import os
import sys
import tomllib
from dataclasses import dataclass
from datetime import date

from recipe_meta import recipe_files, recipe_meta
from stdio import use_utf8_console

TIERS = ("全部", "部分", "未记录")
EVIDENCE_KINDS = ("用例", "现场", "报告者自述", "机主自测", "未知")
UNRECORDED = TIERS[-1]
UNKNOWN_EVIDENCE = EVIDENCE_KINDS[-1]
BUCKETS = ("30 天以内", "31–90 天", "90 天以上")
REVIEW = "待复核"
BUILD_MISMATCH = "build 不符"
HASH_LEN = 16               # sha256 前 16 个十六进制字符：够区分，也不至于把台账写得太宽


@dataclass(frozen=True)
class Row:
    """一份配方在台账里的样子。没有记录时覆盖度是「未记录」、证据来源是「未知」，其余字段为空。"""
    path: str                   # 相对 recipes/ 的路径，如 xiaomi-M154FF/recipe.py
    build: str                  # 记录的完整系统 build 串
    date: str                   # YYYY-MM-DD
    verifier: str               # @login 或 机主
    tier: str                   # 覆盖度：全部 / 部分 / 未记录
    evidence: str               # 证据来源：用例 / 现场 / 报告者自述 / 机主自测 / 未知
    days: int | None            # 距 today 多少天；没有日期是 None
    review: bool = False        # 记录的段体哈希与现在的脚本对不上，见 _needs_review()
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


class _DocstringFree(ast.NodeTransformer):
    """递归去掉函数 / 类 / 模块体开头的字符串常量：docstring 不是行为，改它不该改哈希。"""

    def _strip(self, node):
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:]
        return self.generic_visit(node)

    visit_Module = _strip
    visit_FunctionDef = _strip
    visit_AsyncFunctionDef = _strip
    visit_ClassDef = _strip


def _canonical(node):
    """把 AST 子树序列化成一行：按字段名与字段值递归展开，空列表等空字段也照样写出。

    不用 `ast.dump()`：它在不同解释器版本下对空字段的取舍不一样（Windows job 跑 3.12、Linux
    与打包跑 3.13），那样同一份脚本会算出两个哈希，台账在 CI 上就会随平台翻成待复核。
    """
    if isinstance(node, ast.AST):
        fields = ",".join(f"{name}={_canonical(value)}" for name, value in ast.iter_fields(node))
        return f"{type(node).__name__}({fields})"
    if isinstance(node, list):
        return "[" + ",".join(_canonical(item) for item in node) + "]"
    return repr(node)


def _step_name(node):
    """`@step("段名")` 里的段名；不是 `step` 装饰器时返回 None。

    参数不是字符串字面量时按装饰器表达式本身取名，让这一段仍参与哈希，而不是被悄悄漏掉。
    """
    for dec in node.decorator_list:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "step"):
            continue
        arg = dec.args[0] if dec.args else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return f"<{ast.unparse(dec)}>"
    return None


def step_bodies(path):
    """脚本里每个段的 (段名, 归一后段体)，按段名排序。

    段体取函数正文并去掉 docstring，再按 AST 结构序列化：注释与折行不在 AST 里，装饰器也不进
    段体，所以改注释 / 折行 / 装饰器、挪函数位置、改函数名都不改这段文本。段名参与拼接，所以重命名
    段会算改（段名出现在用户日志里）。按段名排序，段的先后不影响结果。
    catalog 数据（`.toml`）没有 `@step`：段体取每个 `[[segment]]` 归一后的数据（键排序的 JSON），
    段名取 `name`，判据仍是「段名 + 段体内容变没变」。"""
    if str(path).endswith(".toml"):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return sorted((segment.get("name", ""), json.dumps(segment, ensure_ascii=False, sort_keys=True))
                      for segment in data.get("segment", []))
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(path))
    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = _step_name(node)
        if name is None:
            continue
        body = _DocstringFree().visit(ast.Module(body=list(node.body), type_ignores=[]))
        out.append((name, _canonical(body)))
    return sorted(out)


def _exception_body(path):
    """同名例外 `.py` 归一后的模块体；页面树数据没有这份文件时是 None。

    找法与装载器一致（`.toml` 换后缀）。只有页面树数据才有这一项：旧形态的 `.py` 机型脚本换后缀
    还是它自己，拿自己跟自己拼会把模块级常量也算进段体哈希。

    走 `ast.unparse` 而不复用 `_canonical`：后者按字段名逐项展开，CPython 给节点加字段就整批改
    哈希（3.15 给 `Import` 加了 `is_lazy`，同一份树在 3.13 与 3.15 上 47 行里有 44 行不同），而
    `--hash` 是照抄进台账的基线。`unparse` 由语义重生成源码，3.11–3.15 上 42 份逐字节相同。
    """
    if not str(path).endswith(".toml"):
        return None
    companion = os.path.splitext(os.fspath(path))[0] + ".py"
    if not os.path.isfile(companion):
        return None
    with open(companion, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=companion)
    stripped = _DocstringFree().visit(ast.Module(body=list(tree.body), type_ignores=[]))
    return ast.unparse(stripped)


def body_hash(path):
    """一份脚本的段体哈希：按段名拼起每个段名与归一后段体，页面树数据再接上同名例外 `.py` 的
    归一模块体，取 sha256 前 HASH_LEN 位。"""
    parts = [f"{name}\n{dump}" for name, dump in step_bodies(path)]
    exception = _exception_body(path)
    if exception is not None:
        parts.append(exception)
    return hashlib.sha256("\n\n".join(parts).encode("utf-8")).hexdigest()[:HASH_LEN]


def body_hashes(recipes_dir):
    """每个配方文件现在的段体哈希，{相对路径: 哈希}。纯 AST，不装载脚本、不碰设备。"""
    return {rel: body_hash(os.path.join(recipes_dir, rel)) for rel in recipe_paths(recipes_dir)}


def hash_listing(recipes_dir):
    """`--hash` 的输出：每份配方一行「路径<TAB>哈希」，按路径排序。

    发版或真机验证后拿它刷新 recipes/verified.toml 的 body_hash；只打印，不改文件。
    """
    return "".join(f"{path}\t{value}\n" for path, value in sorted(body_hashes(recipes_dir).items()))


def load(path):
    """已解析的台账：{相对路径: {build, date, by, tier, evidence, body_hash}}。"""
    with open(path, "rb") as f:
        return tomllib.load(f)


def entry(records, path):
    """一份脚本的三样结论：(覆盖度, 证据来源, 验证日期)。

    台账里没有这份脚本（或没有这一条）时是 `(未记录, 未知, "")`，不抛错：引擎要对每份脚本都答得出
    这三样，缺数据本身就是一个结论。`records` 是 `load()` 的返回值，传空字典就是「什么都没记」。
    """
    record = records.get(path) or {}
    return (record.get("tier") or UNRECORDED,
            record.get("evidence") or UNKNOWN_EVIDENCE,
            record.get("date", ""))


def rows(recipes_dir, records, today, hashes=None, builds=None):
    """每个配方文件一行，按距今天数降序；没有可信记录的排在最后。`records` 是已解析的台账，
    `today`、`hashes`（{相对路径: 现在的段体哈希}）与 `builds`（{相对路径: 脚本的 BUILD}）
    都由调用方注入（测试不钉真实日期、不读真实脚本）。

    没有记录的配方照样出行、覆盖度记「未记录」：缺数据不能让配方从输出里消失。覆盖度是「未记录」
    时记录本身不可信，日期不参与天数、分档与待复核判定，build 也不参与前缀校验——没写就是没写，
    不该被读成「脚本涨版本了」。`builds` / `hashes` 里没有的路径不校验。
    """
    hashes = hashes or {}
    builds = builds or {}
    out = []
    for path in recipe_paths(recipes_dir):
        record = records.get(path, {})
        tier, evidence, day = entry(records, path)
        trusted = tier != UNRECORDED
        mismatch = trusted and path in records and not build_matches(record.get("build", ""),
                                                                     builds.get(path, ""))
        out.append(Row(path, record.get("build", ""), day, record.get("by", ""), tier, evidence,
                       _days_since(day, today) if trusted else None,
                       trusted and _needs_review(record.get("body_hash", ""), hashes.get(path, "")),
                       mismatch))
    return sorted(out, key=lambda row: (row.days is None, -(row.days or 0), row.path))


def _days_since(day, today):
    """没有日期返回 None；验证日期在未来时按 0 天算，不让它变成负数。"""
    return None if not day else max((today - date.fromisoformat(day)).days, 0)


def _needs_review(recorded, current):
    """记录的段体哈希与现在算出来的不一致时标「待复核」。

    缺记录哈希（还没建立基线的旧记录）或缺现在的哈希（读不到脚本）时无从比较，不标：把
    「无法比较」当成「改过」会让旧台账一上来全红，反而失去信号。
    """
    if not recorded or not current:
        return False
    return recorded != current


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
    parts = " · ".join(f"{name} {n}" for name, n in zip(BUCKETS, distribution(ledger_rows), strict=True))    # 两边都恒为 3 档
    return f"{parts}（共 {len(ledger_rows)} 份）"


def render(recipes_dir, records, today, hashes=None, builds=None):
    """命令行输出的全文：一行一份配方，列用制表符隔开，距今天数在路径之后、覆盖度与证据来源在最后；
    末尾一行三档分布。待复核与 build 不符接在行尾，两者同时成立时用「 · 」连起来。
    段体哈希不进输出行，只在判定时用。"""
    ledger_rows = rows(recipes_dir, records, today, hashes, builds)
    lines = []
    for row in ledger_rows:
        if row.tier == UNRECORDED:
            lines.append(f"{row.path}\t{UNRECORDED}")
        else:
            marks = [name for name, on in ((REVIEW, row.review), (BUILD_MISMATCH, row.build_mismatch)) if on]
            tail = f"\t{' · '.join(marks)}" if marks else ""
            lines.append(f"{row.path}\t{row.days}\t{row.build}\t{row.date}\t{row.verifier}"
                         f"\t{row.tier}\t{row.evidence}{tail}")
    lines.append(_footer(ledger_rows))
    return "\n".join(lines) + "\n"


def _recipes_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")


if __name__ == "__main__":
    use_utf8_console()
    _dir = _recipes_dir()
    if "--hash" in sys.argv[1:]:
        sys.stdout.write(hash_listing(_dir))
    else:
        sys.stdout.write(render(_dir, load(os.path.join(_dir, "verified.toml")), date.today(),
                                body_hashes(_dir), declared_builds(_dir)))
