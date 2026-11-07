"""跨运行时符号：`tool/` 在电脑上与手机版跑的是两套依赖，静态引用的名字必须真的存在。

手机版把 `aac_android/u2.py` 经 `install()` 把模块里定义的类动态注册成 `uiautomator2.exceptions`，
所以手机上「有」的名字不等于电脑上（真 `uiautomator2` + `adbutils`）也有。#674 里那行
`except u2.exceptions.ScreenGone` 只在手机版存在——电脑上任何异常走到那个 except 都是
AttributeError，比它要处理的错误更糟，而三个审查代理都没看出来。
"""
import ast
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 只在装得下这两套依赖时才检：手机版的 python 树在 android/ 下，不在这里
SOURCES = sorted([*ROOT.glob("tool/*.py"), *ROOT.glob("gui/*.py")])
ALIASES = {"u2": "uiautomator2", "uiautomator2": "uiautomator2", "adbutils": "adbutils"}


def references(tree):
    """代码里静态引用的 (模块, 名字)：`u2.exceptions.X` 与 `adbutils.X`。

    只认点号链最右边一段，`u2.Device` 这类构造调用不在此列——它们不是异常类，也不保证同名。
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        chain, base = [], node
        while isinstance(base, ast.Attribute):
            chain.append(base.attr)
            base = base.value
        if not isinstance(base, ast.Name):
            continue
        chain.append(base.id)
        chain.reverse()
        module = ALIASES.get(chain[0])
        if module is None or len(chain) < 2:
            continue
        rest = chain[1:]
        if module == "uiautomator2" and len(rest) >= 2 and rest[0] == "exceptions":
            out.add(("uiautomator2.exceptions", rest[1]))
        elif module == "adbutils" and len(rest) == 1:
            out.add(("adbutils", rest[0]))
    return out


class RuntimeSymbolTests(unittest.TestCase):
    def test_every_referenced_name_exists_in_the_desktop_dependency(self):
        missing, seen = [], set()
        for path in SOURCES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module, name in references(tree):
                seen.add((module, name))
                if not hasattr(importlib.import_module(module), name):
                    missing.append(f"{path.name}: {module}.{name}")
        self.assertTrue(seen, "一个引用都没扫到：扫描规则失效时这条用例什么也没守")
        self.assertEqual(sorted(missing), [], "这些名字只在手机版存在，电脑上走到它就是 AttributeError")
