"""规则注册表的五条不变式（前四条沿用 #842、#845 的做法，第五条见 #1302）：`source` 指得到真实出处、`check` 与 `status` 配得上且解析得到真实守卫、
正文锚点与注册表条目双向一致、锚点落在 `source` 点名的那一小节里、`code:` 规则点名的符号在实现里只定义一次。
五条各是一个用例，单条不变式失败不影响另外四条；注册表整体读不出（TOML 语法或字段表）时五条一并报，消息带条目标识。
另有一个用例是另一把锁（#1303）：没有守卫的规则条数只许降。

第五条的口径：`status = "code"` 的规则说的是「这件事只在那一处实现，别处不要另写一份」，而 `check` 只证明符号存在。
所以对每条 `code:` 规则点名的符号，在 `tool/` `devtools/` `gui/` `recipe_lib/` 四个目录下按模块层定义计数——
`def` / `async def` / `class` / 赋值 / 带值的 `AnnAssign`，穿过 `if` / `try` / `with` / `for` / `while` / `match`
的块（与 `top_level_names()` 同一口径），只计裸名目标；`import` / `from … import` 的重导出不算定义，
`tool/fast.py` 的 `Screen` 与 `NEG_PREFIX` 就是这一档。
点名的路径里必须有它，其余每一处同名定义都要在 `CODE_SYMBOL_EXEMPT` 里有理由——同名不同义才豁免，
「这是同一个概念的另一份实现」不豁免，那是要开票修掉的复制。
"""
import ast
import re
import tomllib
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/agents/rules.toml"
# 锚点写在条目行尾（ADR-0028）。模板里引用锚点写法时后面还接着正文，那不是登记。
ANCHOR = re.compile(r"<!--\s*rule:([A-Za-z0-9][\w.\-]*)\s*-->\s*$")
ATX = re.compile(r"^#{1,6}\s+(.+?)\s*$")
TRAILING_ANCHOR = re.compile(r"\s*<!--.*?-->\s*$")
TRAILING_HASHES = re.compile(r"\s+#+\s*$")
FENCE = "```"
MODULE = re.compile(r"^[A-Za-z0-9_]+$")
ID = re.compile(r"^[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+$")
DOMAINS = {"dev", "doc", "domain"}
STATUSES = {"enforced", "manual", "advisory", "dead", "code"}
UNGUARDED = {"manual", "advisory", "dead"}
# 没有守卫的规则条数上限，只许降（#1303）。口径是 UNGUARDED，含 dead：dead 是待删的存量，
# 仍是一笔只能靠人记着的债，漏掉它就能靠「把一条 manual 标成 dead」白换一个名额。
# 涨一个必须在这里改数字：那是一次公开的「我又欠了一条只能靠人记着的规则」，评审要看见。
# 守卫化一条（status 改 enforced / code）是还债，改完把这里的数字一起下调。
PROSE_ONLY_BOUND = 71          # manual 59 + advisory 12，dead 0，注册表共 160 条
REQUIRED = ("id", "source", "check", "status", "why", "expires_if")
OPTIONAL = ("since",)


def read_rows():
    """注册表条目；TOML 语法与字段表的问题抛 ValueError，由每条用例各自转成自己的失败。"""
    data = tomllib.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = data.get("rule", [])
    if not isinstance(rows, list):
        raise ValueError("顶层要写成 [[rule]] 数组")
    seen = set()
    for index, row in enumerate(rows, 1):
        label = row.get("id") or f"第 {index} 条"
        unknown = set(row) - set(REQUIRED) - set(OPTIONAL)
        if unknown:
            raise ValueError(f"{label} 有未知字段 {sorted(unknown)}")
        missing = [key for key in REQUIRED if key not in row]
        if missing:
            raise ValueError(f"{label} 缺字段 {missing}")
        if not ID.match(row["id"]):
            raise ValueError(f"id={row['id']!r} 要写成 `域.对象.断言`（小写字母、数字、连字符）")
        if row["id"].split(".")[0] not in DOMAINS:
            raise ValueError(f"{row['id']} 的域不在 {sorted(DOMAINS)}")
        if row["status"] not in STATUSES:
            raise ValueError(f"{label} 的 status={row['status']!r} 不在 {sorted(STATUSES)}")
        if row["id"] in seen:
            raise ValueError(f"重复 id：{row['id']}")
        seen.add(row["id"])
    return rows


def prose_lines(path):
    """文档里不在围栏代码块内的行，给标题与锚点共用的扫描口径。"""
    in_fence = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith(FENCE):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield lineno, line


def headings(path):
    """小节标题文本的集合；行尾的 ATX 收尾 `#` 与 `<!-- … -->` 注释不算标题的一部分。"""
    titles = set()
    for _, line in prose_lines(path):
        match = ATX.match(line)
        if match:
            titles.add(TRAILING_HASHES.sub("", TRAILING_ANCHOR.sub("", match.group(1))).strip())
    return titles


def anchors(path):
    """[(行号, id)]：行尾的 `<!-- rule:<id> -->`。"""
    found = []
    for lineno, line in prose_lines(path):
        match = ANCHOR.search(line)
        if match:
            found.append((lineno, match.group(1)))
    return found


def section_of(path):
    """{行号: 该行所属小节标题}；标题行自己算它开的那一节。围栏代码块内不算（`# 注释` 不是标题）。"""
    owners, stack = {}, []
    for lineno, line in prose_lines(path):
        match = ATX.match(line)
        if match:
            title = TRAILING_HASHES.sub("", TRAILING_ANCHOR.sub("", match.group(1))).strip()
            stack = [item for item in stack if item[0] < len(line) - len(line.lstrip("#"))]
            stack.append((len(line) - len(line.lstrip("#")), title))
        if stack:
            owners[lineno] = stack[-1][1]
    return owners


def module_level(body):
    """模块层可达的语句：穿过 if / try / with / for / while / match 的块，不进入 def / class。"""
    for node in body:
        if isinstance(node, ast.If):
            yield from module_level(node.body)
            yield from module_level(node.orelse)
        elif isinstance(node, ast.Try):
            for handler in node.handlers:
                yield from module_level(handler.body)
            yield from module_level(node.orelse)
            yield from module_level(node.finalbody)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            yield from module_level(node.body)            # with 没有 orelse
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            yield from module_level(node.body)
            yield from module_level(node.orelse)
        elif isinstance(node, ast.Match):
            for case in node.cases:
                yield from module_level(case.body)
        else:
            yield node


def case_names(path):
    """用例模块里可被 `test:<模块>::<用例>` 点到的名字：`Class.method` 与模块层函数。只读 AST。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in module_level(tree.body):
        if isinstance(node, ast.ClassDef):
            names.update(f"{node.name}.{child.name}" for child in node.body
                         if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def workflow_jobs(path):
    """workflow 文件 `jobs:` 下的一级键。缩进扫描，不为一条守卫引入 YAML 依赖。"""
    jobs, inside, indent = set(), False, None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.rstrip() == "jobs:":
            inside, indent = True, None
            continue
        if not inside:
            continue
        if not line.startswith(" "):
            break                                       # 回到顶层键，jobs 段结束
        column = len(line) - len(line.lstrip())
        if indent is None:
            indent = column
        match = re.match(r"^\s+([A-Za-z0-9_-]+):\s*$", line)
        if column == indent and match:
            jobs.add(match.group(1))
    return jobs


def top_level_defs(path):
    """Python 文件里模块层定义的名字与行号：`def` / `async def` / `class` / 赋值 / 带值的 `AnnAssign`。只读 AST，不执行。

    裸注解（`X: int` 没有值）不绑定模块属性，不算定义。`code:<路径>:<名字>` 与唯一性计数共用这一份口径。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in module_level(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.append((node.name, node.lineno))
        elif isinstance(node, ast.Assign):
            found.extend((target.id, node.lineno) for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            found.append((node.target.id, node.lineno))
    return found


def top_level_names(path):
    """Python 文件里模块层可被 `code:<路径>:<名字>` 点到的名字。"""
    return {name for name, _ in top_level_defs(path)}


def code_target(check):
    """`code:<路径>:<名字>` 拆成 (路径, 名字)；不是这个形态返回 None。"""
    kind, sep, target = check.partition(":")
    if kind != "code" or not sep:
        return None
    path, sep, name = target.partition(":")
    if not sep or not path or not name:
        return None
    return path, name


def check_problem(check, status):
    """`check` 与 `status` 配不配得上、指不指得到真实守卫；有问题返回一句，没问题返回 None。"""
    if status in UNGUARDED:
        if check != "none":
            return f"status={status} 的 check 要写 none，{check!r} 指到守卫就该记成 enforced 或 code"
        return None
    if check == "none":
        return f"status={status} 的 check 不能是 none，它要指到一条真实守卫"
    kind, sep, target = check.partition(":")
    if not sep:
        return f"check={check!r} 要写成 `test:<模块>::<用例>` / `ci:<job>` / `code:<路径>:<名字>`"
    if kind == "test":
        module, sep, case = target.partition("::")
        if not sep or not module or not case:
            return f"check={check!r} 要写成 `test:<模块>::<用例>`"
        if not MODULE.match(module):
            return f"check={check!r} 的模块名要写成 tests/ 下的文件名（不带 .py 与 tests. 前缀）"
        path = ROOT / "tests" / f"{module}.py"
        if not path.is_file():
            return f"tests/{module}.py 不存在"
        if case not in case_names(path):
            return f"tests/{module}.py 里没有用例 {case}"
        return None
    if kind == "ci":
        for path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
            if target in workflow_jobs(path):
                return None
        return f".github/workflows/ 里没有 job {target}"
    if kind == "code":
        named = code_target(check)
        if named is None:
            return f"check={check!r} 要写成 `code:<路径>:<名字>`"
        name, attr = named
        path = ROOT / name
        if not path.is_file():
            return f"{name} 不存在"
        if attr not in top_level_names(path):
            return f"{name} 里没有模块层的名字 {attr}"
        return None
    return f"check={check!r} 的前缀 {kind!r} 不认识"


CODE_SCOPE = ("tool", "devtools", "gui", "recipe_lib")

# {(符号, 相对路径): 为什么这一处与规则点名的那一处不是同一个概念}
# 键指向「多出来的那一处」，规则点名的那一处不进这张表。
CODE_SYMBOL_EXEMPT = {
    ("classify", "tool/recipe_audit.py"):
        "同一份脚本源码的「本机函数分级」，与 `tool/channel_policy.py` 的渠道判定只是重名（#1302 票面实测）。",
    ("dispatch", "gui/launch.py"):
        "客户端启动去向的判定（cli / help / usage / window，返回字符串），"
        "与 `tool/run.py` 的命令分派（退出码只在出口，ADR-0005）不是一件事。",
    ("Screen", "gui/harmony_engine.py"):
        "鸿蒙桌面引擎的界面树裁剪（hdc 通道，只留可见层），"
        "与 `tool/phone/screen.py` 的读屏模型（adb + uiautomator2 的当前这一屏）是两套引擎各自的实现；"
        "同类豁免见 `tests/test_rules_guards.py` 对鸿蒙引擎自己 `Phone` 类的处理。",
}


def code_symbol_places():
    """{符号: [(相对路径, 行号)]}：`CODE_SCOPE` 四个目录下每个符号的模块层定义处。"""
    index = {}
    for folder in CODE_SCOPE:
        for path in sorted((ROOT / folder).rglob("*.py")):
            where = path.relative_to(ROOT).as_posix()
            for name, lineno in top_level_defs(path):
                index.setdefault(name, []).append((where, lineno))
    return index


def code_symbol_problems(rows, index, exempt):
    """`index` 与 `exempt` 的形态见模块 docstring，返回问题清单。拆成纯函数是为了让反例用例喂合成数据。"""
    rules_of, declared = {}, {}
    for row in rows:
        if row.get("status") != "code":
            continue
        named = code_target(row.get("check", ""))
        if named is None:
            continue                                # check 的写法由第二条不变式报
        path, name = named
        rules_of.setdefault(name, []).append(row["id"])
        declared.setdefault(name, set()).add(path)

    problems = []
    for name, paths in sorted(declared.items()):
        owners = "、".join(rules_of[name])
        places = index.get(name, [])
        where = "、".join(f"{path}:{lineno}" for path, lineno in places) or "一处都没有"
        for path in sorted(paths):
            if not any(place_path == path for place_path, _ in places):
                problems.append(f"{name}（{owners}）：点名的 {path} 里没有模块层定义；现在定义在 {where}")
        counted = {}
        for path, _ in places:
            counted[path] = counted.get(path, 0) + 1
        for path in sorted(path for path, times in counted.items() if times > 1):
            problems.append(f"{name}（{owners}）：{path} 里定义了不止一次")
        # 两条规则点名同一个符号的不同路径时，两处都是「点名的定义处」，唯一性同样不成立。
        extra = sorted(path for path in counted if (name, path) not in exempt)
        if len(extra) > 1:
            problems.append(f"{name}（{owners}）：除豁免外有 {len(extra)} 处定义（{'、'.join(extra)}），"
                            f"「只在那里定义」不成立；同名不同义才进 CODE_SYMBOL_EXEMPT")
    for (name, path) in sorted(exempt):
        places = index.get(name, [])
        if name not in declared:
            problems.append(f"豁免 {name} @ {path}：没有 `code:` 规则点名这个符号，这条豁免是空转的")
        elif not any(place_path == path for place_path, _ in places):
            problems.append(f"豁免 {name} @ {path}：那里已经不再定义 {name}，该从 CODE_SYMBOL_EXEMPT 里删掉")
        elif path in declared[name]:
            problems.append(f"豁免 {name} @ {path}：那是规则点名的定义处，不是多出来的那一处")
    return problems


class RulesRegistryTests(unittest.TestCase):
    def rows(self):
        try:
            return read_rows()
        except (OSError, ValueError) as error:
            self.fail(f"读不出 docs/agents/rules.toml：{error}")

    def test_source_names_a_real_file_and_heading(self):
        rows = self.rows()
        self.assertTrue(rows, "注册表一条都没有，这条守卫会空转")
        problems = []
        for row in rows:
            name, sep, heading = row["source"].partition("#")
            if not sep or not name or not heading:
                problems.append(f"{row['id']}: source={row['source']!r} 要写成 `<文档>#<小节标题>`")
                continue
            path = ROOT / name
            if not path.is_file():
                problems.append(f"{row['id']}: {name} 不存在")
            elif heading not in headings(path):
                problems.append(f"{row['id']}: {name} 里没有小节「{heading}」")
        self.assertEqual(problems, [], "注册表 source 指不到真实出处：\n" + "\n".join(problems))

    def test_checks_resolve_to_a_real_guard(self):
        rows = self.rows()
        self.assertTrue([row for row in rows if row["status"] == "enforced"],
                        "一条 enforced 都没有，这条守卫会空转")
        problems = []
        for row in rows:
            problem = check_problem(row["check"], row["status"])
            if problem:
                problems.append(f"{row['id']}: {problem}")
        self.assertEqual(problems, [], "check 与 status 配不上，或指不到真实守卫：\n" + "\n".join(problems))

    def test_anchors_and_registry_agree(self):
        rows = self.rows()
        self.assertTrue(rows, "注册表一条都没有，锚点守卫会空转")
        ids = {row["id"] for row in rows}
        documents = set()
        for row in rows:
            name, sep, _ = row["source"].partition("#")
            if sep and name:
                documents.add(name)
        anchored = {}
        for name in sorted(documents):
            path = ROOT / name
            if not path.is_file():
                continue                                # 由第一条不变式报
            for lineno, anchor_id in anchors(path):
                anchored.setdefault(anchor_id, []).append(f"{name}:{lineno}")
        problems = []
        for anchor_id, places in sorted(anchored.items()):
            if anchor_id not in ids:
                problems.append(f"{'、'.join(places)} 的锚点 rule:{anchor_id} 不在注册表里")
            elif len(places) > 1:
                problems.append(f"rule:{anchor_id} 有 {len(places)} 处锚点（{'、'.join(places)}），只该有一处")
        for row in rows:
            if row["id"] in anchored:
                continue
            name, sep, _ = row["source"].partition("#")
            if not sep or not name or not (ROOT / name).is_file():
                continue                                # 出处本身坏了，由第一条不变式报
            problems.append(f"注册表里的 {row['id']} 在正文里没有行尾锚点 `<!-- rule:{row['id']} -->`")
        self.assertEqual(problems, [], "锚点与注册表条目要对得上：\n" + "\n".join(problems))

    def test_each_anchor_sits_under_the_section_it_names(self):
        rows = self.rows()
        self.assertTrue(rows, "注册表一条都没有，这条守卫会空转")
        by_id = {row["id"]: row for row in rows}
        problems = []
        for name in sorted({row["source"].partition("#")[0] for row in rows}):
            path = ROOT / name
            if not path.is_file():
                continue                                # 由第一条不变式报
            owners = section_of(path)
            for lineno, anchor_id in anchors(path):
                row = by_id.get(anchor_id)
                if row is None:
                    continue                            # 由第三条不变式报
                heading = row["source"].partition("#")[2]
                if owners.get(lineno) != heading:
                    problems.append(
                        f"{row['id']}: 锚点在 {name}:{lineno}，那一行属于「{owners.get(lineno)}」，"
                        f"source 却写「{heading}」")
        self.assertEqual(problems, [], "锚点要落在 source 点名的那一小节里：\n" + "\n".join(problems))

    def test_prose_only_rule_count_only_shrinks(self):
        rows = self.rows()
        unguarded = [row for row in rows if row["status"] in UNGUARDED]
        counts = Counter(row["status"] for row in unguarded)
        self.assertLessEqual(
            len(unguarded), PROSE_ONLY_BOUND,
            f"没有守卫的规则 {len(unguarded)} 条，上限 {PROSE_ONLY_BOUND}"
            f"（manual {counts['manual']} + advisory {counts['advisory']}"
            f" + dead {counts['dead']}）。"
            "新增一条 manual / advisory / dead 要先还一条债：把一条旧的守卫化"
            "（status 改 enforced / code，check 指到真实守卫）或删掉一条旧的。"
            "两样都不做就动 PROSE_ONLY_BOUND：那是一次公开的记录，评审要看见。")

    def test_every_code_symbol_is_defined_once(self):
        rows = self.rows()
        self.assertTrue([row for row in rows if row["status"] == "code"],
                        "一条 code 规则都没有，这条守卫会空转")
        index = code_symbol_places()
        self.assertTrue(index, f"{'、'.join(CODE_SCOPE)} 下一个模块层定义都没扫到，这条守卫会空转")
        problems = code_symbol_problems(rows, index, CODE_SYMBOL_EXEMPT)
        self.assertEqual(problems, [], "`code:` 规则点名的符号要只在一处定义：\n" + "\n".join(problems))

    def test_the_uniqueness_check_can_fail(self):
        """反例：判据对合成数据的每一种结局都给出预期的判断，不靠真实仓库恰好合规。"""
        one = [{"id": "dev.demo.one-place", "status": "code", "check": "code:tool/demo.py:Widget"}]
        split = [{"id": "dev.demo.a", "status": "code", "check": "code:tool/demo.py:Widget"},
                 {"id": "dev.demo.b", "status": "code", "check": "code:gui/other.py:Widget"}]
        only = {"Widget": [("tool/demo.py", 3)]}
        twice = {"Widget": [("tool/demo.py", 3), ("gui/other.py", 9)]}
        cases = [
            ("同一处定义", one, only, {}, []),
            ("第二处没有豁免", one, twice, {}, ["除豁免外有 2 处定义"]),
            ("第二处有豁免", one, twice, {("Widget", "gui/other.py"): "另一个东西"}, []),
            ("点名的路径里没有它", one, {"Other": [("tool/demo.py", 3)]}, {},
             ["点名的 tool/demo.py 里没有模块层定义"]),
            ("同一文件里定义了两次", one, {"Widget": [("tool/demo.py", 3), ("tool/demo.py", 20)]}, {},
             ["定义了不止一次"]),
            ("两条规则点名不同的路径", split, twice, {}, ["除豁免外有 2 处定义"]),
            ("豁免空转：没有规则点名它", one, only, {("Gadget", "gui/other.py"): "x"},
             ["没有 `code:` 规则点名这个符号"]),
            ("豁免空转：那里已经不再定义", one, twice, {("Widget", "tool/gone.py"): "x"},
             ["那里已经不再定义 Widget"]),
            ("豁免指向点名的那一处", one, twice, {("Widget", "tool/demo.py"): "x"},
             ["不是多出来的那一处"]),
        ]
        for label, rows, index, exempt, expected in cases:
            with self.subTest(label):
                problems = code_symbol_problems(rows, index, exempt)
                if not expected:
                    self.assertEqual(problems, [], label)
                    continue
                self.assertTrue(problems, f"{label}：判据该报却没报")
                self.assertTrue(any(fragment in problem for problem in problems for fragment in expected),
                                f"{label}：报出的问题里没有 {expected}，实际是 {problems}")

if __name__ == "__main__":
    unittest.main()
