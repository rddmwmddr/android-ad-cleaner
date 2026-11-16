"""发现式 glob 的反空转守卫（#1280）。

`for x in <发现>: ...` 后面接 `assertEqual(offenders, [])`，在发现集为空时与「全仓合规」
不可区分。机型脚本从 `recipes/<家族>/<型号>/recipe*.py` 改成同目录的 `<型号>.toml` 之后，
三处守卫的发现模式匹配 0 份、断言恒真，CI 全绿而没有人看着它们保护的东西。

判据：把 `tests/`、`tool/` 与 `devtools/` 里每一处对仓库目录做发现的 glob / rglob
**对真实仓库求值一次**，匹配 0 份即报红。基路径与模式从同一文件的模块常量、函数内局部常量、字面量循环变量与
`形参 or 默认值` 还原；还原不出来（形参、运行时数据目录、f-string、生成器表达式）的调用
不在判据范围内，记进 `Report.skipped`，不报红——它们指向的不是仓库现状，求值没有意义。
循环变量按名字取全文件并集，同名变量在一处是字面量、另一处是动态值时会一并按字面量求值
（方向是可能的误报，不是静默放过）。

豁免只在「这个模式就该匹配 0 份」时使用，键是 (文件相对路径, 相对仓库根的模式)，理由写在
`EXEMPT` 里——两处都是相对路径，换 worktree 或换 CI 机器时不用改。`tests/test_glob_scan.py`
的 `ExemptionTests` 要求每条豁免仍对得上一个真的空匹配：模式不再为空就该把它从清单里删掉，
不让清单腐烂成第二层静默。
"""
import ast
import glob as globmod
import os
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

FOLDERS = ("tests", "tool", "devtools")

# {(文件相对路径, 相对仓库根的模式): 为什么这个模式本来就该匹配 0 份}
EXEMPT: dict[tuple[str, str], str] = {
    ("tests/fixtures.py", "recipes/*/*/recipe*.py"):
        "迁移期兼容：机型脚本已全部转成页面树，旧的 `recipe*.py` 一份不剩；"
        "这一支留着认还没转的目录，现行的发现口径是同函数的 `recipes/*/*/*.toml`。",
}

_GLOB_FUNCS = ("glob", "iglob")
_OS_PATH_FUNCS = ("join", "dirname", "abspath", "normpath", "fspath")


@dataclass(frozen=True)
class Idle:
    """一处匹配 0 份的发现式扫描。`key` 是它相对仓库根的模式，与 `EXEMPT` 的键同名。"""
    where: str
    lineno: int
    how: str
    pattern: str
    base: str
    key: str


@dataclass(frozen=True)
class Skipped:
    """一处静态还原不出仓库路径的调用，附原因。"""
    where: str
    lineno: int
    how: str
    why: str


@dataclass
class Report:
    offenders: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    covered: list = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.covered)

    def cover(self, where: str, pattern: str) -> None:
        self.covered.append((where, pattern))


_UNKNOWN = object()


def scan(root):
    """对 root 下的 tests/ 与 tool/ 现算一遍发现式 glob 的匹配数。"""
    root = Path(root).resolve()
    report = Report()
    for folder in FOLDERS:
        for path in sorted((root / folder).rglob("*.py")):
            _scan_file(path, root, report)
    return report


def _scan_file(path, root, report):
    where = path.relative_to(root).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module_env = _module_constants(tree)
    loops = _loop_values(tree)
    funcs = _function_constants(tree)
    for call, receiver, how, arg, recursive in _glob_calls(tree):
        # 调用点所在函数（由内向外）的局部常量叠在模块常量之上；
        # `recipe_sources()` 的 `root = Path(folder or ROOT) / "recipes"` 是这一档。
        env = dict(module_env)
        for node, local in funcs:
            if node.lineno <= call.lineno <= (node.end_lineno or node.lineno):
                env.update(local)
        ctx = {"file": str(path), "env": env, "loops": loops, "seen": set()}
        if arg is None:
            report.skipped.append(Skipped(where, call.lineno, how, "没有模式实参"))
            continue
        patterns = _evaluate(arg, ctx)
        if patterns is _UNKNOWN:
            report.skipped.append(Skipped(where, call.lineno, how, "模式还原不出来"))
            continue
        if receiver is None:
            for pattern in sorted(patterns):
                _check_full_pattern(call, how, pattern, root, path, report, recursive)
            continue
        bases = _evaluate(receiver, ctx)
        if bases is _UNKNOWN:
            report.skipped.append(
                Skipped(where, call.lineno, how, f"基路径 {_source(receiver)} 还原不出来"))
            continue
        bases = sorted(Path(base) for base in bases)
        bases = [base for base in bases if _inside(base, root)]
        if not bases:
            report.skipped.append(
                Skipped(where, call.lineno, how, f"基路径 {_source(receiver)} 不在仓库内"))
            continue
        for base, pattern in product(bases, sorted(patterns)):
            hits = base.rglob(pattern) if how == "rglob" else base.glob(pattern)
            report.cover(where, pattern)
            if any(True for _ in hits):
                continue
            key = _repo_relative(str(base / pattern), root)
            if (where, key) in EXEMPT:
                continue
            report.offenders.append(Idle(where, call.lineno, how, pattern, str(base), key))


def _check_full_pattern(call, how, full, root, path, report, recursive):
    where = path.relative_to(root).as_posix()
    if not _inside_text(full, root):
        report.skipped.append(Skipped(where, call.lineno, how, f"模式 {full} 不在仓库内"))
        return
    key = _repo_relative(full, root)
    report.cover(where, key)
    # 必须照调用点的实参求值：`glob.glob` 的 `recursive` 默认是 False，`**` 只等价一层。
    if globmod.glob(full, recursive=recursive):
        return
    if (where, key) in EXEMPT:
        return
    report.offenders.append(Idle(where, call.lineno, how, full, "", key))


def _repo_relative(pattern, root):
    """把模式换回相对仓库根的写法，豁免键才不会写死本机路径。"""
    return os.path.relpath(pattern, str(root)).replace(os.sep, "/")


def _inside(path, root):
    return path == root or root in path.parents


def _inside_text(text, root):
    return text == str(root) or text.startswith(str(root) + os.sep)


def _glob_calls(tree):
    """[(调用节点, 接收者或 None, 'glob'/'rglob', 模式实参, 是否递归)]。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        arg = node.args[0] if node.args else None
        if not isinstance(func, ast.Attribute):
            continue
        # `glob.glob(...)` / `glob.iglob(...)`：模块函数，第一个实参就是完整模式。
        # 这一档必须先判，否则 `glob.glob(...)` 会被下面的方法档抓成「接收者叫 glob」。
        if isinstance(func.value, ast.Name) and func.value.id == "glob" and func.attr in _GLOB_FUNCS:
            yield node, None, func.attr, arg, _recursive_flag(node)
        elif func.attr in ("glob", "rglob"):
            yield node, func.value, func.attr, arg, True


def _recursive_flag(node):
    """`glob.glob(..., recursive=...)` 的实参；省掉或不是字面量 `True` 就按默认的 False。"""
    for keyword in node.keywords:
        if keyword.arg == "recursive":
            return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
    return False


def _module_constants(tree):
    return _constants_in(tree.body)


def _function_constants(tree):
    """[(函数节点, 函数体内的顶层赋值)]，按 lineno 升序：外层先铺，内层后覆盖。"""
    out = [(node, _constants_in(node.body)) for node in ast.walk(tree)
           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return sorted(out, key=lambda item: item[0].lineno)


def _constants_in(body):
    env = {}
    for node in body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                env[target.id] = node.value
    return env


def _loop_values(tree):
    """`for x in ("a", "b"):` 这种字面量序列：{x: {"a", "b"}}。

    全仓扫描都写成 `for folder in ("tool", "gui", "tests")` 再 `(ROOT / folder).rglob(...)`，
    不认识循环变量就等于放过了最典型的一批反空转守卫。"""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        values = _string_literals(node.iter)
        if values is not None:
            out.setdefault(node.target.id, set()).update(values)
    return out


def _string_literals(node):
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return None
    out = set()
    for elt in node.elts:
        if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
            return None
        out.add(elt.value)
    return out


def _source(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "<表达式>"


def _evaluate(node, ctx):
    """把一个表达式还原成一组字符串路径；还原不出来返回 `_UNKNOWN`。

    循环变量的值域是字面量集合，所以求值结果也是集合；`? / x` 这类组合按笛卡尔积展开。"""
    env = ctx["env"]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return {ctx["file"]}
        if node.id in env:
            if node.id in ctx["seen"]:
                return _UNKNOWN
            ctx["seen"].add(node.id)
            try:
                return _evaluate(env[node.id], ctx)
            finally:
                ctx["seen"].discard(node.id)
        if node.id in ctx["loops"]:
            return set(ctx["loops"][node.id])
        return _UNKNOWN
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _combine(node.left, node.right, ctx, lambda left, right: Path(left) / right)
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _evaluate(node.value, ctx)
        return _UNKNOWN if base is _UNKNOWN else {str(Path(item).parent) for item in base}
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "parents":
        base = _evaluate(node.value.value, ctx)
        index = node.slice
        if base is _UNKNOWN or not isinstance(index, ast.Constant) or not isinstance(index.value, int):
            return _UNKNOWN
        try:
            return {str(Path(item).parents[index.value]) for item in base}
        except IndexError:
            return _UNKNOWN
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        # `folder or ROOT`：形参取不到时运行的就是默认值，那才是「对仓库求值」的对象。
        # 未知支必须是裸名（形参 / 局部变量）才这么读；`root_from_env() or <默认>` 的运行时
        # 值可能根本不在仓库里（用户数据目录），对它求值没有意义。
        values = [(_evaluate(item, ctx), item) for item in node.values]
        known = [value for value, _ in values if value is not _UNKNOWN]
        if not known:
            return _UNKNOWN
        if any(value is _UNKNOWN and not isinstance(item, ast.Name) for value, item in values):
            return _UNKNOWN
        return set().union(*known)
    if isinstance(node, ast.Call):
        return _evaluate_call(node, ctx)
    return _UNKNOWN


def _evaluate_call(node, ctx):
    func = node.func
    if isinstance(func, ast.Name) and func.id == "str" and node.args:
        return _evaluate(node.args[0], ctx)
    if isinstance(func, ast.Name) and func.id == "Path" and node.args:
        # `Path(ROOT, "tests")` 与 `Path(ROOT / "tests")` 等价，只取第一个实参会把基路径
        # 读成仓库根。
        return _combine_chain(node.args, ctx, lambda parts: Path(*parts))
    if isinstance(func, ast.Attribute) and func.attr == "resolve" and not node.args:
        base = _evaluate(func.value, ctx)
        if base is _UNKNOWN:
            return _UNKNOWN
        try:
            return {str(Path(item).resolve()) for item in base}
        except (OSError, RuntimeError):
            return _UNKNOWN
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute) \
            and func.value.attr == "path" and func.attr in _OS_PATH_FUNCS:
        return _os_path_call(node, ctx, func.attr)
    return _UNKNOWN


def _os_path_call(node, ctx, name):
    parts = [_evaluate(arg, ctx) for arg in node.args]
    if not parts or any(part is _UNKNOWN for part in parts):
        return _UNKNOWN
    if name == "join":
        return {os.path.join(*combo) for combo in product(*[sorted(part) for part in parts])}
    return {getattr(os.path, name)(item) for item in parts[0]}


def _combine(left_node, right_node, ctx, build):
    left, right = _evaluate(left_node, ctx), _evaluate(right_node, ctx)
    if left is _UNKNOWN or right is _UNKNOWN:
        return _UNKNOWN
    try:
        return {str(build(litem, ritem)) for litem, ritem in product(sorted(left), sorted(right))}
    except (TypeError, ValueError):
        return _UNKNOWN


def _combine_chain(nodes, ctx, build):
    parts = [_evaluate(node, ctx) for node in nodes]
    if not parts or any(part is _UNKNOWN for part in parts):
        return _UNKNOWN
    try:
        return {str(build(combo)) for combo in product(*[sorted(part) for part in parts])}
    except (TypeError, ValueError):
        return _UNKNOWN
