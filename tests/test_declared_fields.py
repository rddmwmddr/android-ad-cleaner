"""构造处声明过的字段要直接读：类自己的 `__init__` 里赋过 `self.x`，类里就不该再写 `getattr(self, "x", 默认值)`。

`getattr` 兜底把「忘了初始化」变成静默默认值：`.__new__` 装配与 `Mock()` 冒充都发现不了漏掉的字段
（#344：六个字段收进 Phone 时 `locked()` 里留了一处）。守卫只看 `tool/`；`aac_android` 的替换层读的是
上游库对象，字段不由本仓库的 `__init__` 声明，不在规则范围内。
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def descendants(nodes):
    """从给定节点往下走，不进入嵌套类：内层类的字段集与本类无关。"""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, ast.ClassDef):
                stack.append(child)


def assigned_names(targets):
    """赋值目标里 `self.<名字>` 的名字；`self.W, self.H = …` 这类解包按元素展开。"""
    names = set()
    for target in targets:
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                and target.value.id == "self":
            names.add(target.attr)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names |= assigned_names(target.elts)
        elif isinstance(target, ast.Starred):
            names |= assigned_names([target.value])
    return names


def declared_in_init(classdef):
    """类自己 `__init__` 里声明的字段；不追父类，`super().__init__()` 设置的属性看不见。"""
    for node in classdef.body:
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            names = set()
            for sub in descendants([node]):
                if isinstance(sub, ast.Assign):
                    names |= assigned_names(sub.targets)
                elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)):
                    names |= assigned_names([sub.target])
            return names
    return set()


def fallback_reads(classdef):
    """该类里对声明字段的 `getattr(self, "<名字>", …)`：[(行号, 字段名)]。默认值写成位置参数或 `default=` 都算兜底。"""
    fields = declared_in_init(classdef)
    hits = []
    for node in descendants(classdef.body):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "getattr":
            continue
        has_default = len(node.args) >= 3 or any(keyword.arg == "default" for keyword in node.keywords)
        if len(node.args) < 2 or not has_default:
            continue
        target, name = node.args[0], node.args[1]
        if isinstance(target, ast.Name) and target.id == "self" and isinstance(name, ast.Constant) \
                and isinstance(name.value, str) and name.value in fields:
            hits.append((node.lineno, name.value))
    return hits


class DeclaredFieldTests(unittest.TestCase):
    def test_declared_fields_are_read_directly(self):
        """旧树也绿，守的是不回退：当前代码没有这处兜底，新增一处就红。"""
        hits = []
        for path in sorted((ROOT / "tool").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for lineno, field in fallback_reads(node):
                        hits.append(f"{path.relative_to(ROOT)}:{lineno}: self.{field}")
        self.assertEqual(hits, [], "构造处声明过的字段直接读 self.x，漏了就让它当场 AttributeError：\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
