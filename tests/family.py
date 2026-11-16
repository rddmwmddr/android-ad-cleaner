"""族容器（#1395）：一张 case 表，加几个把它绑到被测代码上的可调用对象。

一个族由「case 行表 + 四个可调用对象」组成：

* ``handles(case)``  -> 这条 case 依赖的结构项，
* ``structure()``    -> 此刻真实存在的结构项，
* ``produce(case)``  -> 每条 case 的可比较产出（可选），
* ``expected()``     -> 从结构反推「每条结构项都该有 case」的集合（可选）。

容器只管生命周期：case id 与快照比对、声明的句柄与结构比对、产出与快照比对，以及结构里的缺口。
它不知道被测代码怎么跑，也不知道任何具体族的数据形状或断言方法。

族模块长这样::

    import sys
    from family import Family, cli

    CASES = [{"id": "...", ...}, ...]
    FAMILY = Family("名字", CASES, handles=..., structure=..., produce=..., expected=...)

    if __name__ == "__main__":
        sys.exit(cli())

快照在 ``tests/snapshots/<族名>.json``，只能经
``python3 tests/<族模块>.py --update --reason "…(#票号)"`` 写盘。理由必填，并且必须带一个票号引用：
更新快照要能对到一张票，不能只靠人读 diff。不带参数跑模块会把四项检查打给人读。
"""
import ast
import json
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]

_PURE_SCALARS = (str, int, float, bool, type(None))

# 快照更新要能对到一张票：只写「调整」这类理由等于橡皮图章。
_TICKET = re.compile(r"#\d+")

# 模块层改写容器的方法：调用它们等于往 case 表里追加或改写行，纯数据检查必须看得见。
_MUTATING_METHODS = frozenset(
    {"append", "extend", "insert", "update", "setdefault", "pop", "remove"}
)


class Family:
    """一张 case 行表，以及让它保持诚实的几项检查。

    ``--update`` 写盘时 ``--reason`` 必须带一个票号引用（形如 ``#1395``）：快照的每一次更新
    都要能对到一张票，只靠人读 diff 不够。
    """

    def __init__(self, name, cases, *, handles, structure, produce=None, expected=None, root=None):
        self.name = name
        self.cases = list(cases)
        self._handles = handles
        self._structure = structure
        self._produce = produce
        self._expected = expected
        self.root = DEFAULT_ROOT if root is None else Path(root)

    # ---------- 快照文件 ----------

    def snapshot_path(self):
        return self.root / "tests" / "snapshots" / f"{self.name}.json"

    def snapshot(self, reason):
        """当前这些行该落盘的样子（排序固定，逐字节稳定）。"""
        ordered = sorted(self.cases, key=lambda case: case["id"])
        document = {"reason": reason, "ids": [case["id"] for case in ordered]}
        if self._produce is not None:
            document["outputs"] = {case["id"]: self._produce(case) for case in ordered}
        return document

    def read(self):
        path = self.snapshot_path()
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, reason):
        path = self.snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.snapshot(reason), ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        return path

    # ---------- 四项检查：各自返回违规清单 ----------

    def id_violations(self, snapshot=None):
        snapshot = self.read() if snapshot is None else snapshot
        if snapshot is None:
            return [self._no_snapshot()]
        found = []
        seen = set()
        for index, case in enumerate(self.cases):
            case_id = case.get("id")
            if not isinstance(case_id, str) or not case_id:
                found.append(f"{self.name}: 第 {index} 条 case 没有稳定的字符串 id")
            elif case_id in seen:
                found.append(f"{self.name}: case id {case_id!r} 重复")
            else:
                seen.add(case_id)
        recorded = set(snapshot.get("ids", []))
        for case_id in sorted(seen - recorded):
            found.append(f"{self.name}: case id {case_id!r} 不在快照里"
                         "（新增了 case：用 --reason 更新快照）")
        for case_id in sorted(recorded - seen):
            found.append(f"{self.name}: 快照里的 id {case_id!r} 没有对应的 case"
                         "（删了 case：用 --reason 更新快照）")
        return found

    def handle_violations(self):
        actual = set(self._structure())
        found = []
        for case in self.cases:
            case_id = case.get("id")
            for handle in self._handles(case):
                if handle not in actual:
                    found.append(f"{self.name}: case {case_id!r} 声明依赖 {handle!r}，"
                                 "但结构里已经没有它")
        return found

    def output_violations(self, snapshot=None):
        if self._produce is None:
            return []
        snapshot = self.read() if snapshot is None else snapshot
        if snapshot is None:
            return [self._no_snapshot()]
        recorded = snapshot.get("outputs", {})
        found = []
        for case in self.cases:
            case_id = case.get("id")
            if not isinstance(case_id, str):
                continue
            if case_id not in recorded:
                found.append(f"{self.name}: case {case_id!r} 在快照里没有产出")
                continue
            produced = self._produce(case)
            if produced != recorded[case_id]:
                found.append(f"{self.name}: case {case_id!r} 的产出是 {produced!r}，"
                             f"快照里是 {recorded[case_id]!r}")
        return found

    def gap_violations(self):
        if self._expected is None:
            return []
        covered = set()
        for case in self.cases:
            covered.update(self._handles(case))
        missing = self._expected() - covered
        return [f"{self.name}: 结构项 {handle!r} 没有对应的 case（补一条）"
                for handle in sorted(missing, key=repr)]

    def violations(self):
        snapshot = self.read()
        return (self.id_violations(snapshot) + self.handle_violations()
                + self.output_violations(snapshot) + self.gap_violations())

    def _no_snapshot(self):
        return (f"{self.name}: 没有快照文件 {self.snapshot_path()}"
                "（用 --update --reason … 创建）")


def _family_from_main():
    main = sys.modules.get("__main__")
    return getattr(main, "FAMILY", None) if main is not None else None


def _parse(argv):
    """返回 (update, reason, error)；error 是提示语或 None。"""
    update, reason, index = False, None, 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--update":
            update = True
        elif argument == "--reason":
            index += 1
            if index >= len(argv):
                return update, reason, "--reason 需要一个值"
            reason = argv[index]
        elif argument.startswith("--reason="):
            reason = argument[len("--reason="):]
        else:
            return update, reason, f"认不出的参数 {argument!r}（只有 --update / --reason）"
        index += 1
    return update, reason, None


def cli(argv=None, family=None):
    """更新或体检一个族的快照；返回进程退出码。

    ``--update`` 要配一个非空、且带票号引用（``#1395``）的 ``--reason``；不带参数时打印四项检查。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    chosen = family if family is not None else _family_from_main()
    if chosen is None:
        print("family: 没有可操作的族；要通过定义了模块级 FAMILY 的族模块运行", file=sys.stderr)
        return 2
    update, reason, error = _parse(argv)
    if error:
        print(f"family: {error}", file=sys.stderr)
        return 2
    if update:
        text = (reason or "").strip()
        if not text:
            print("family: --update 需要非空的 --reason", file=sys.stderr)
            return 2
        if not _TICKET.search(text):
            print('family: --reason 必须带一个票号引用（形如 "#1395"）：'
                  "快照更新要能对到一张票", file=sys.stderr)
            return 2
        path = chosen.write(text)
        print(f"family: 已写入 {path}")
        return 0
    checks = (
        ("ids", chosen.id_violations()),
        ("handles", chosen.handle_violations()),
        ("outputs", chosen.output_violations()),
        ("gaps", chosen.gap_violations()),
    )
    failures = 0
    for label, found in checks:
        print(f"[{label}]")
        if not found:
            print(f"{chosen.name}: {label} ok")
        for line in found:
            print(line)
        failures += len(found)
    return 0 if not failures else 1


def _is_family_construction(node):
    if not isinstance(node, ast.Call):
        return False
    target = node.func
    return ((isinstance(target, ast.Name) and target.id == "Family")
            or (isinstance(target, ast.Attribute) and target.attr == "Family"))


def _impure(node):
    """`node` 不是纯数据字面量时返回一句原因，否则返回 None。"""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, _PURE_SCALARS):
            return None
        return f"类型为 {type(node.value).__name__} 的常量"
    if isinstance(node, ast.Set):
        # set 不可 JSON 序列化，与快照写盘口径不一致（ADR-0042）。
        return "一个 set 字面量（不能写进快照 JSON）"
    if isinstance(node, (ast.List, ast.Tuple)):
        for item in node.elts:
            if isinstance(item, ast.Starred):
                return "一个带星号的展开"
            bad = _impure(item)
            if bad:
                return bad
        return None
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                return "一个字典展开"
            bad = _impure(key) or _impure(value)
            if bad:
                return bad
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = node.operand
        if (isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float))
                and not isinstance(operand.value, bool)):
            return None
        return "对非数字的一元运算"
    if isinstance(node, ast.Name):
        return f"对名字 {node.id!r} 的引用"
    return f"一个 {type(node).__name__} 节点"


def _imported_names(tree):
    """模块顶部 import 进来的绑定名：对它们调方法不算「改写 case 表」。"""
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _root_name(node):
    """`a.b.c` / `a` 的根名字；根不是裸名字（如 `f()`）时返回 None。"""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _mutation_violations(node, label, imported):
    """模块级表达式里对非导入名调变异方法的调用——这类调用能往 case 表里追加行。"""
    found = []
    for call in ast.walk(node.value):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr not in _MUTATING_METHODS:
            continue
        root = _root_name(call.func.value)
        if root is not None and root in imported:
            continue
        found.append(f"{label}: 第 {call.lineno} 行在模块层对 {root or '一个表达式'!r} 调了 "
                     f"{call.func.attr}()；case 表只能是纯字面量，模块层不许再追加或改写行")
    return found


def pure_data_violations(module_or_path):
    """case 行必须是纯字面量：不许 lambda、不许调用、不许引用别的名字。

    检查模块级的每一条赋值（``Family(...)`` 构造本身除外），以及模块级表达式里对非导入名
    调变异方法的写法——两者都能把行为偷渡进 case 表。允许的类型是 str / 数字 / list / dict /
    tuple / bool / None；set 不在内（不可 JSON 序列化）。赋值目标不是裸名字时同样算违规：
    纯数据检查看不见它，等于给出一个绕过口。
    """
    path = Path(getattr(module_or_path, "__file__", module_or_path))
    label = getattr(module_or_path, "__name__", path.stem)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return [f"{label}: 读不出 {path}：{exc}"]
    imported = _imported_names(tree)
    found = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not all(isinstance(target, ast.Name) for target in node.targets):
                found.append(f"{label}: 第 {node.lineno} 行的赋值目标不是裸名字；"
                             "case 表只能是「名字 = 纯字面量」，别的写法纯数据检查看不见")
                continue
            names = [target.id for target in node.targets]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                found.append(f"{label}: 第 {node.lineno} 行的赋值目标不是裸名字；"
                             "case 表只能是「名字 = 纯字面量」，别的写法纯数据检查看不见")
                continue
            if node.value is None:
                continue
            names = [node.target.id]
            value = node.value
        elif isinstance(node, ast.Expr):
            found.extend(_mutation_violations(node, label, imported))
            continue
        else:
            continue
        if _is_family_construction(value):
            continue
        reason = _impure(value)
        if reason:
            for name in names:
                found.append(f"{label}: 模块级数据 {name!r}（第 {node.lineno} 行）里有{reason}；"
                             "case 行必须是纯字面量")
    return found
