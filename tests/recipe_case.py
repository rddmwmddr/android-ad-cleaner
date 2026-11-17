"""机型脚本测试的共享助手与检查基类。

非 `test_` 前缀、不进锚点表：这里只有助手与被继承的用例，收集到的 `def test_` 仍长在
`test_*_recipe.py` 的文件名下——子类只给数据（`RECIPE` 等），用例本身在这里写一次。
"""
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
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


def walk(ops):
    """展开带分支的 op（if_entry / if_lib_any …）里的子表。"""
    for op in ops:
        yield op
        yield from walk(op.get("ops", []))
        yield from walk(op.get("else_ops", []))


class RecipeSourceCase(unittest.TestCase):
    """读自己那份脚本源码的机型测试：`RECIPE` 读成 `self.path` / `self.source`。"""

    RECIPE = None

    def setUp(self):
        self.path = self.RECIPE
        self.source = self.path.read_text(encoding="utf-8")


class RecipeSafetyCase(unittest.TestCase):
    """系统广告段的 close_named：缺目标即停、回读翻转不算成功、已关算确认、别的开关被改不算。"""

    RECIPE = None

    def load(self, phone):
        return load(phone, self.RECIPE)

    def test_missing_target_aborts_without_touching_switches(self):
        p = Mock()
        p.switches.return_value = [("其他开关", True, (1, 2))]
        p.scroll_more.return_value = False
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标开关"):
            scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        p.off.assert_not_called()

    def test_reverted_switch_is_failure_not_verified(self):
        p = Mock()
        p.switches.return_value = [("个性化广告推荐", True, (1, 2))]
        p.scroll_more.return_value = False
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭"):
            scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_already_off_target_is_verified(self):
        p = Mock()
        p.switches.return_value = [("个性化广告推荐 个性化广告服务会根据您的喜好进行精准匹配。", False, (1, 2))]
        p.scroll_more.return_value = False
        scope = self.load(p)
        scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)
        p.off.assert_called_once()

    def test_unrelated_switch_changed_is_not_reported_as_verified(self):
        p = Mock()
        p.switches.side_effect = [
            [("个性化广告推荐", True, (1, 2)), ("其他开关", True, (1, 3))],
            [("个性化广告推荐", False, (1, 2)), ("其他开关", False, (1, 3))],
        ]
        p.scroll_more.return_value = False
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named"](["个性化广告推荐"], "系统·广告服务")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)


class StoreSafetyCase(unittest.TestCase):
    """应用商店段的 close_named：目标缺一个即停、回读翻转不算成功、折下目标算确认、别的开关被改不算。"""

    RECIPE = None

    def load(self, phone):
        return load(phone, self.RECIPE)

    def test_missing_target_aborts_without_clicking_any_switch(self):
        p = Mock(); p.switches.return_value = [("WLAN 自动更新应用", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标开关"):
            scope["close_named"](["个性化推荐"], "商店")
        p.off.assert_not_called()

    def test_reverted_switch_is_failure_not_verified(self):
        p = Mock(); p.switches.return_value = [("个性化推荐", True, (1, 2))]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭"):
            scope["close_named"](["个性化推荐"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_target_below_fold_is_verified_and_other_switch_is_preserved(self):
        p = Mock()
        p.scroll_more.return_value = True
        p.switches.side_effect = [
            [("活动弹窗", True, (1, 2)), ("应用安全", True, (1, 3))],
            [("软件福利", True, (1, 2))],
            [("活动弹窗", False, (1, 2)), ("应用安全", True, (1, 3))],
            [("软件福利", False, (1, 2))],
        ]
        scope = self.load(p)
        scope["close_named"](["活动弹窗", "软件福利"], "商店", max_screens=2)
        self.assertEqual(scope["VERIFIED_SWITCHES"], 2)

    def test_unrelated_switch_changed_is_not_reported_as_verified(self):
        p = Mock()
        p.switches.side_effect = [
            [("活动弹窗", True, (1, 2)), ("应用安全", True, (1, 3))],
            [("活动弹窗", False, (1, 2)), ("应用安全", False, (1, 3))],
        ]
        scope = self.load(p)
        with self.assertRaisesRegex(RuntimeError, "其他开关状态变化"):
            scope["close_named"](["活动弹窗"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)


class OfflineSafetyCase(unittest.TestCase):
    """离线装载：不选段就不碰手机、锁屏记未完成、等页拒绝「同意并继续」。"""

    RECIPE = None
    make_phone = None        # 子类填自己模块里的 make_phone：假手机怎么造是各机型的事

    def load(self, phone=None, only=None):
        return load(phone or self.make_phone(), self.RECIPE, only)

    def test_no_selection_does_not_touch_phone(self):
        phone = self.make_phone()
        result = self.load(phone)
        self.assertEqual(result["RESULTS"], [])
        self.assertEqual(phone.commands, [])

    def test_locked_phone_fails_the_step(self):
        """锁屏不再静默跳过：这一段记未完成，退出码由失败台账给出（沿用 #839）。"""
        result = self.load(self.make_phone(locked=True), ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "未完成")])
        self.assertEqual(result["FAILED_STEPS"], ["软件商店"])

    def test_wait_page_rejects_consent_button(self):
        phone = self.make_phone()
        phone.screen.focus = lambda: "example.app/ExampleActivity"
        phone.screen.tree = lambda: None
        phone.screen.texts = lambda root: [("同意并继续", (0, 0, 100, 100), {"class": "android.widget.Button"})]
        function = self.load(phone)["wait_page"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))
