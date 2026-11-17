"""机型脚本测试的共享助手与检查基类。

非 `test_` 前缀、不进锚点表：这里只有助手与被继承的用例，收集到的 `def test_` 仍长在
`test_*_recipe.py` 的文件名下——子类只给数据（`RECIPE` 等），用例本身在这里写一次。
"""
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

from fixtures import load_recipe


def load(phone, recipe, only=None):
    """装载机型脚本并返回作用域；`only` 与 `load_recipe()` 同义（None 表示一段都不跑）。"""
    scope, _ = load_recipe(phone, recipe, only)
    return scope


def radios(show=True):
    """OPPO 轮播推荐页：两条单选框，`show` 决定哪一条被选中。"""
    return ET.fromstring(f'''<hierarchy><node text="不显示轮播推荐" clickable="true"/>
      <node><node text="显示轮播推荐"/><node class="android.widget.RadioButton"
        checkable="true" checked="{str(show).lower()}" enabled="true" bounds="[20,30][60,70]"/></node>
      <node><node text="不显示轮播推荐"/><node class="android.widget.RadioButton"
        checkable="true" checked="{str(not show).lower()}" enabled="true" bounds="[200,300][240,340]"/></node>
    </hierarchy>''')


def fake_shell(model, build):
    """只应答两条 getprop 的 shell，连同命令台账一起返回；别的命令当场失败。"""
    values = {"getprop ro.product.model": model, "getprop ro.build.display.id": build}
    commands = []

    def shell(command, timeout=None):
        commands.append(command)
        if command not in values:
            raise AssertionError("Unexpected phone command: " + command)
        return SimpleNamespace(output=values[command])

    return shell, commands


def _walk(ops):
    """展开带分支的 op（if_entry / if_lib_any …）里的子表。"""
    for op in ops:
        yield op
        yield from _walk(op.get("ops", []))
        yield from _walk(op.get("else_ops", []))


class RecipeSourceCase(unittest.TestCase):
    """读自己那份脚本源码的机型测试：`RECIPE` 读成 `self.path` / `self.source`。"""

    RECIPE = None

    def setUp(self):
        self.path = self.RECIPE
        self.source = self.path.read_text(encoding="utf-8")
