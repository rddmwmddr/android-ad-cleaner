"""脚本面的 AST 对账（rule:dev.phone.script-surface、#1477）。

判据只有一份：`tool/phone/surface.py` 的 `SCRIPT_SURFACE`。这里只把 `recipes/` 与
`recipe_lib/` 里真实出现的 `p.<名字>` 抽出来与它比。

为什么不按文本 grep：`p.d.shell` 与 `p.d(...)` 在正则下是两回事，注释里提到旧名字、文档串里
写示例、同名变量 `page.p` 都会误伤。AST 只看得见真正的属性访问，读与写两种上下文都在同一个
`Attribute` 节点上，`p.d(...)` 这种「属性即调用」也一样落在 `p.d` 上。

`violations(root)` 对给定根目录求值，不依赖真实仓库状态——反例用临时目录构造。
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))   # 声明留在引擎目录

from phone.surface import SCRIPT_SURFACE


def script_files(root):
    """要扫的脚本：`recipes/` 下全部 `.py`，加 `recipe_lib/*.py`（家族库实现）。

    catalog 的 `.toml` 不在这里：它是数据，执行时走解释器的 op 分派，不是脚本源码；
    把它们降成源码再扫会把「数据用了哪个 op」当成「脚本碰了哪个名字」。
    """
    base = Path(root)
    return sorted(list((base / "recipes").rglob("*.py")) + list((base / "recipe_lib").glob("*.py")))


def accesses(path):
    """一份脚本里 `p.<名字>` 的 (名字, 行号)，读写两种上下文都算。"""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "p"):
            yield node.attr, node.lineno


def violations(root, surface=SCRIPT_SURFACE):
    """[(相对路径, 行号, 名字)]：脚本面里出现、声明里没有的 `p.<名字>`。"""
    base = Path(root)
    found = []
    for path in script_files(base):
        for name, lineno in accesses(path):
            if name not in surface:
                # 路径按 `/` 归一：报告形状与平台无关，Windows 上也报 `recipe_lib/honor.py`
                found.append((path.relative_to(base).as_posix(), lineno, name))
    return found


def main(argv=()):
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[1]
    found = violations(root)
    for path, lineno, name in found:
        print(f"{path}:{lineno}  p.{name} 不在脚本面声明里（tool/phone/surface.py）")
    print(f"{len(script_files(root))} 份脚本，声明外名字 {len(found)} 处")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
