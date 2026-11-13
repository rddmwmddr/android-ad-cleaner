#!/usr/bin/env python3
"""迁移转换器（**临时工具**，#1260）：把一份旧机型脚本的 `@step` 段体按 catalog schema 分类。

删除条件（ADR-0038）：最后一批 #1267 迁完、验收总表全绿之后删除，不留死代码。删除前是 CI 覆盖对象
（`tests/test_catalog_migrate.py`）。它不是运行时的一部分，只读旧脚本、产出文本与分类，不碰手机、
不改仓库里的任何脚本。

分类口径（与 spike 的「不需要模型知识」一致，可复现）：

- `converted`：段体每个语句都能落到 schema 里已有的 op（`tool/catalog/schema.py` 的白名单）。
- `missing-key`：语句需要一条**有界的运行时语义** op（循环、错误收集、设置搜索、按条件分支、
  具名导航原语……），schema 还没有这一种，但加它是「≥2 机型用法」能论证的扩展，不是机型知识。
- `unrepresentable`：段体调用了该机的**真机型知识**函数（`recipe_audit.classify` 判为 `knowledge`
  档），或含无法用任何通用语义表达的本机逻辑——只能写成 `code = "<本机策略名>"`。

覆盖率 = (`converted` + `missing-key`) / 段体总数。`unrepresentable` 是残余（要 `code=` 兜底）。
这是 spike 的口径：「转得动或只需补一条通用语义」都算不需要模型知识，只有真本机知识才算不了。

    python3 tool/catalog_migrate.py                全量：合计覆盖率 + 逐脚本 rollup
    python3 tool/catalog_migrate.py --script <path>  单份：逐段三列明细 + 产出的 TOML
    python3 tool/catalog_migrate.py --toml          把每份的全量 TOML（converted 段）打出来
"""
import ast
import glob
import os
import sys
from typing import TypeGuard

import recipe_audit
import recipe_source

CONVERTED, MISSING_KEY, UNREPRESENTABLE = "converted", "missing-key", "unrepresentable"
# 严重度：一段按最坏的那条语句定档。
_RANK = {CONVERTED: 0, MISSING_KEY: 1, UNREPRESENTABLE: 2}

# 迁移期的共享库模块：从这些模块导入的裸名字算「库调用」，落到 lib op。
LIB_MODULES = frozenset({"recipe_nav", "recipe_steps", "recipe_strategies"})
# recipe_kit 注入的运行时助手：maybe 映射成 entry/gated，require 映射成必需断言，其余是通用语义。
RUNTIME_HELPERS = frozenset({"maybe", "require", "skip", "page", "require_switches",
                             "start_or_skip", "skip_in_safe_mode"})
# p 的门面方法 → schema op 或「需要补的 op」名。不在表里的 p.* 走 missing-key，键名取方法名。
P_OPS = {
    "off": "off", "start": "start", "back": "back", "top": "top",
}


class Missing(Exception):
    """语句需要一条 schema 还没有的 op；`key` 是建议的新 op 名（有界、可枚举）。"""

    def __init__(self, key: str, detail: str = "") -> None:
        self.key, self.detail = key, detail
        super().__init__(f"{key}: {detail}" if detail else key)


class Cannot(Exception):
    """语句是该机的本机知识，任何通用语义都表达不了——只能 `code=`。"""


def _literal(node: ast.expr) -> TypeGuard[ast.Constant]:
    return isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool))


def _string_list(node) -> list[str] | None:
    """`[ "a", "b" ]` 形态的字面量字符串列表；不是就返回 None。"""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    out: list[str] = []
    for element in node.elts:
        if not _literal(element) or not isinstance(element.value, str):
            return None
        out.append(element.value)
    return out


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


class Converted:
    def __init__(self, ops: list[dict]) -> None:
        self.ops = ops


class Migrator:
    """一份脚本的转换上下文：本地知识函数名、库导入表，以及 `@step` 与段体的对应。"""

    def __init__(self, src: str, path: str = "") -> None:
        self.path = path
        self.src = src
        self.tree = ast.parse(src)
        self.facts = recipe_source.scan_source(src)
        levels = recipe_audit.classify(src)
        self.knowledge_local = frozenset(f.name for f in levels if f.tier == "knowledge")
        self.lib_local = frozenset(f.name for f in levels if f.tier in ("strategy", "vocabulary"))
        self.imports = dict(self.facts.imports)

    def steps(self) -> list[tuple[str, ast.FunctionDef]]:
        out: list[tuple[str, ast.FunctionDef]] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "step" \
                            and dec.args and _literal(dec.args[0]) \
                            and isinstance(dec.args[0].value, str):
                        out.append((dec.args[0].value, node))
        out.sort(key=lambda pair: pair[1].lineno)
        return out

    # ---------- 段体 ----------

    def segment(self, name: str, func: ast.FunctionDef) -> "SegmentReport":
        """一段的三列分类；`ops` 只在 fully converted 时可用。"""
        called = {n.func.id for n in ast.walk(func) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name)}
        hit = called & self.knowledge_local
        if hit:
            return SegmentReport(name, UNREPRESENTABLE, [], f"调用本机知识函数 {sorted(hit)}")
        ops: list[dict] = []
        worst, keys = CONVERTED, []
        for stmt in func.body:
            try:
                ops += self._stmt(stmt)
            except Missing as miss:
                if _RANK[MISSING_KEY] > _RANK[worst]:
                    worst = MISSING_KEY
                keys.append(miss.key)
            except Cannot as why:
                return SegmentReport(name, UNREPRESENTABLE, [], str(why))
        if worst == MISSING_KEY:
            return SegmentReport(name, MISSING_KEY, [], "缺：" + "、".join(sorted(set(keys))))
        return SegmentReport(name, CONVERTED, ops, "")

    def _stmt(self, stmt: ast.stmt) -> list[dict]:
        if isinstance(stmt, ast.Return):
            if stmt.value is not None:
                raise Missing("return_value", "带返回值的 return")
            return [{"kind": "return"}]
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            return self._call(stmt.value)
        if isinstance(stmt, ast.If):
            return self._if(stmt)
        if isinstance(stmt, ast.For):
            raise Missing("for_each", "循环子页 / 重试")
        if isinstance(stmt, ast.Try):
            raise Missing("on_error", "try/except/finally")
        if isinstance(stmt, ast.Raise):
            raise Missing("require", "raise 表达必需断言")
        if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.Global)):
            raise Missing("assign", "局部变量 / 状态")
        if isinstance(stmt, ast.FunctionDef):
            raise Missing("local_def", "段体内定义函数")
        raise Missing("stmt", type(stmt).__name__)

    def _call(self, call: ast.Call) -> list[dict]:
        fun = call.func
        if isinstance(fun, ast.Attribute) and isinstance(fun.value, ast.Name) and fun.value.id == "p":
            return self._p_call(call, fun.attr)
        if isinstance(fun, ast.Name):
            name = fun.id
            if name == "print":
                return self._print(call)
            if name == "maybe":
                return self._maybe(call)
            if name == "require":
                raise Missing("require", "require(…)")
            if name in RUNTIME_HELPERS:
                raise Missing(name, name + "(…)")
            if name in self.imports and self.imports[name] in LIB_MODULES:
                return [self._lib(call, name)]
            if name in self.lib_local:
                return [self._lib(call, name)]
            if name in self.knowledge_local:
                raise Cannot(f"调用本机知识函数 {name}")
            # 其它裸名字：外部函数 / 常量构造，按通用语义记。
            raise Missing("bare_call", f"{name}(…)")
        raise Missing("call_shape", ast.dump(fun)[:40])

    def _p_call(self, call: ast.Call, attr: str) -> list[dict]:
        if attr in P_OPS:
            return [self._p_op(call, P_OPS[attr])]
        if attr == "entry":
            if call.args and _literal(call.args[0]) and isinstance(call.args[0].value, str):
                scrolls = self._scrolls(call)
                op: dict = {"kind": "entry", "text": call.args[0].value}
                if scrolls is not None:
                    op["scrolls"] = scrolls
                return [op]
            raise Missing("entry", "entry 的文字不是字面量")
        raise Missing(attr, f"p.{attr}(…)：schema 还没有这条导航原语")

    def _p_op(self, call: ast.Call, kind: str) -> dict:
        op: dict
        if kind == "off":
            return self._off(call)
        if kind == "start":
            if not call.args or not (_literal(call.args[0]) and isinstance(call.args[0].value, str)):
                raise Missing("start", "start 的包名不是字面量")
            op = {"kind": "start", "pkg": call.args[0].value}
            if len(call.args) > 1:
                if not (_literal(call.args[1]) and isinstance(call.args[1].value, str)):
                    raise Missing("start", "start 的 activity 不是字面量")
                op["activity"] = call.args[1].value
            for key in ("settle", "foreground", "expect", "budget"):
                value = _kwarg(call, key)
                if value is not None:
                    if not _literal(value):
                        raise Missing("start", f"start 的 {key} 不是字面量")
                    op[key] = value.value
            return op
        if kind == "back":
            if not call.args:
                return {"kind": "back"}
            if _literal(call.args[0]):
                return {"kind": "back", "n": call.args[0].value}
            raise Missing("back", "back 的层数不是字面量")
        if kind == "top":
            n = _kwarg(call, "n")
            if n is None and call.args:
                n = call.args[0]
            op = {"kind": "top"}
            if n is not None:
                if not _literal(n):
                    raise Missing("top", "top 的 n 不是字面量")
                op["n"] = n.value
            return op
        raise Missing(kind, kind)

    def _off(self, call: ast.Call) -> dict:
        page = _kwarg(call, "page")
        if not (page and _literal(page) and isinstance(page.value, str)):
            raise Missing("off", "off 的 page 不是字面量")
        only = _kwarg(call, "only")
        keep = _kwarg(call, "keep")
        op: dict = {"kind": "off", "page": page.value}
        if only is None:
            # 没有 only：整页全关（close_all 形状）或未点名——这里当作需要 close_all。
            raise Missing("close_all", "off 没点名 only")
        only_list = _string_list(only)
        if only_list is None:
            raise Missing("off", "off 的 only 不是字面量列表")
        op["only"] = only_list
        if keep is not None:
            keep_list = _string_list(keep)
            if keep_list is None:
                raise Missing("off", "off 的 keep 不是字面量列表")
            op["keep"] = keep_list
        max_screens = _kwarg(call, "max_screens")
        if max_screens is not None:
            if not _literal(max_screens):
                raise Missing("off", "off 的 max_screens 不是字面量")
            op["max_screens"] = max_screens.value
        return op

    def _print(self, call: ast.Call) -> list[dict]:
        if len(call.args) == 1 and _literal(call.args[0]) and isinstance(call.args[0].value, str):
            return [{"kind": "print", "text": call.args[0].value}]
        raise Missing("print", "print 的文案不是单个字面量")

    def _maybe(self, call: ast.Call) -> list[dict]:
        """裸 `maybe("x")` 不是语句（会丢掉返回值）；只在 if 里被 `_if` 消费。看到它当语句是异常。"""
        raise Missing("maybe_stmt", "maybe(…) 作为独立语句，返回值被丢掉")

    def _scrolls(self, call: ast.Call) -> int | None:
        scrolls = _kwarg(call, "scrolls")
        if scrolls is not None and _literal(scrolls) and isinstance(scrolls.value, int):
            return scrolls.value
        return None

    def _lib(self, call: ast.Call, name: str) -> dict:
        args, kwargs = [], {}
        for arg in call.args:
            if not _literal(arg):
                raise Missing("lib", f"{name} 的实参不是字面量")
            args.append(arg.value)
        for kw in call.keywords:
            if kw.arg is None or not _literal(kw.value):
                raise Missing("lib", f"{name} 的关键字实参不是字面量")
            kwargs[kw.arg] = kw.value.value
        op: dict = {"kind": "lib", "name": name}
        if args:
            op["args"] = args
        if kwargs:
            op["kwargs"] = kwargs
        return op

    def _if(self, stmt: ast.If) -> list[dict]:
        """只认两种形状：`if maybe(A) and maybe(B): body`（gated）与 `if not maybe(A): … return`（必需入口）。"""
        if stmt.orelse:
            raise Missing("branch", "if/else 或 elif")
        entries = self._maybe_all(stmt.test)
        if entries is not None:
            body: list[dict] = []
            for inner in stmt.body:
                body += self._stmt(inner)
            return [{"kind": "gated", "entries": entries, "ops": body}]
        text = self._maybe_not(stmt.test)
        if text is not None:
            return [self._require_after(stmt.body, text)]
        raise Missing("branch", "if 的条件不是 maybe 链")

    def _maybe_all(self, node: ast.expr) -> list[str] | None:
        """`maybe(A) and maybe(B)` → [A, B]；不是纯 maybe 链返回 None。"""
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            out: list[str] = []
            for value in node.values:
                got = self._maybe_one(value)
                if got is None:
                    return None
                out.append(got)
            return out
        one = self._maybe_one(node)
        return [one] if one is not None else None

    def _maybe_one(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "maybe" and node.args and _literal(node.args[0]) \
                and isinstance(node.args[0].value, str):
            return node.args[0].value
        return None

    def _maybe_not(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self._maybe_one(node.operand)
        return None

    def _require_after(self, body: list[ast.stmt], text: str) -> dict:
        """`if not maybe(A): print("…"); p.back(n); return` → require_entry op。"""
        miss_print: str = ""
        miss_back: int | None = None
        saw_return = False
        for stmt in body:
            if isinstance(stmt, ast.Return):
                saw_return = True
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) \
                    and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "print" \
                    and len(stmt.value.args) == 1 and _literal(stmt.value.args[0]) \
                    and isinstance(stmt.value.args[0].value, str):
                miss_print = stmt.value.args[0].value
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) \
                    and isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr == "back":
                if stmt.value.args and _literal(stmt.value.args[0]) \
                        and isinstance(stmt.value.args[0].value, int):
                    miss_back = stmt.value.args[0].value
                else:
                    miss_back = 1
            else:
                raise Missing("require_entry", "失败分支里有 print/back/return 之外的东西")
        if not saw_return:
            raise Missing("branch", "if not maybe 之后没有 return")
        op: dict = {"kind": "require_entry", "text": text, "miss_print": miss_print}
        if miss_back is not None:
            op["miss_back"] = miss_back
        return op


class SegmentReport:
    def __init__(self, name: str, status: str, ops: list[dict], reason: str) -> None:
        self.name, self.status, self.ops, self.reason = name, status, ops, reason


def convert(src: str, path: str = "") -> list[SegmentReport]:
    migrator = Migrator(src, path)
    return [migrator.segment(name, func) for name, func in migrator.steps()]


def render_toml(reports: list[SegmentReport], model: str = "") -> str:
    """把已 converted 的段渲染成 TOML 片段；未 converted 的段输出注释占位。"""
    lines = [f'model = "{model}"', ""]
    for report in reports:
        if report.status != CONVERTED:
            lines.append(f'# 段「{report.name}」未自动转换（{report.status}）：{report.reason}')
            continue
        lines.append("[[segment]]")
        lines.append(f'name = "{report.name}"')
        lines.append("ops = [")
        for op in report.ops:
            lines.append("  " + _toml_inline(op) + ",")
        lines.append("]")
        lines.append("")
    return "\n".join(lines)


def _toml_inline(value) -> str:
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_inline(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_inline(v) for v in value) + "]"
    if isinstance(value, str):
        return '"' + value.replace('"', '\\"') + '"'
    return repr(value)


def measure(recipes_dir: str) -> dict:
    """对全部脚本求覆盖率。返回 {total, converted, missing_key, unrepresentable, scripts:{path: {...}}}。"""
    totals = {CONVERTED: 0, MISSING_KEY: 0, UNREPRESENTABLE: 0}
    per_script = {}
    total = 0
    for path in sorted(glob.glob(os.path.join(recipes_dir, "*", "recipe*.py"))):
        src = open(path, encoding="utf-8").read()
        reports = convert(src, path)
        row = {CONVERTED: 0, MISSING_KEY: 0, UNREPRESENTABLE: 0}
        for report in reports:
            row[report.status] += 1
            totals[report.status] += 1
        total += len(reports)
        per_script[os.path.relpath(path, recipes_dir)] = {"counts": row, "total": len(reports),
                                                          "reports": reports}
    cover = totals[CONVERTED] + totals[MISSING_KEY]
    return {"total": total, "converted": totals[CONVERTED], "missing_key": totals[MISSING_KEY],
            "unrepresentable": totals[UNREPRESENTABLE], "covered": cover,
            "coverage": (cover / total) if total else 0.0, "scripts": per_script}


def _print_measure(result: dict) -> None:
    print(f"段体总数：{result['total']}；covered {result['covered']}，"
          f"覆盖率 {result['coverage']:.1%}（converted {result['converted']} + "
          f"missing-key {result['missing_key']}）；unrepresentable {result['unrepresentable']}")
    print()
    for path, row in result["scripts"].items():
        c = row["counts"]
        print(f"  {path}: {row['total']} 段  "
              f"converted {c[CONVERTED]} / missing-key {c[MISSING_KEY]} / "
              f"unrepresentable {c[UNREPRESENTABLE]}")
    print()
    verdict = "采纳、可继续" if result["coverage"] >= 0.80 else "覆盖率跌破 80%：停工回 grilling"
    print(f"判定：{verdict}")


def _print_script(path: str) -> int:
    src = open(path, encoding="utf-8").read()
    reports = convert(src, path)
    for report in reports:
        detail = f"  ({report.reason})" if report.reason else ""
        print(f"[{report.status}] {report.name}{detail}")
    print()
    print(render_toml(reports, model=os.path.basename(path)))
    return 0


def main(argv=()) -> int:
    recipe_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")
    if argv[:1] == ["--script"] and len(argv) == 2:
        return _print_script(argv[1])
    result = measure(recipe_root)
    if argv[:1] == ["--toml"]:
        for path, row in result["scripts"].items():
            print(f"# ===== {path} =====")
            print(render_toml(row["reports"], model=os.path.basename(os.path.dirname(path))))
            print()
        return 0
    _print_measure(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
