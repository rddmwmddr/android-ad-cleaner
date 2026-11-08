"""规则注册表的四条不变式（#842、#845）：`source` 指得到真实出处、`check` 与 `status` 配得上且解析得到真实守卫、
正文锚点与注册表条目双向一致、锚点落在 `source` 点名的那一小节里。四条各是一个用例，
单条不变式失败不影响另外三条；注册表整体读不出（TOML 语法或字段表）时四条一并报，消息带条目标识。
"""
import ast
import re
import tomllib
import unittest
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
        elif isinstance(node, (ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While)):
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


def top_level_names(path):
    """Python 文件里模块层可被 `code:<路径>:<名字>` 点到的名字。只读 AST，不执行。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in module_level(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


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
        name, sep, attr = target.partition(":")
        if not sep or not name or not attr:
            return f"check={check!r} 要写成 `code:<路径>:<名字>`"
        path = ROOT / name
        if not path.is_file():
            return f"{name} 不存在"
        if attr not in top_level_names(path):
            return f"{name} 里没有模块层的名字 {attr}"
        return None
    return f"check={check!r} 的前缀 {kind!r} 不认识"


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


if __name__ == "__main__":
    unittest.main()
