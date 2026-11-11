"""离线测试，不连接 adb、不打开手机页面。"""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest

from fixtures import load_recipe, phone_stub

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes/realme-RMX3700/recipe.py"

STEPS = ["广告跟踪", "软件商店", "浏览器", "下拉搜索", "小布建议", "应用建议"]


def fake_shell(model, build, commands):
    """回答两条 getprop，其余命令当场失败：这一段只该读型号与版本号。"""
    values = {"getprop ro.product.model": model, "getprop ro.build.display.id": build}

    def shell(command, timeout=None):
        commands.append(command)
        if command not in values:
            raise AssertionError("Unexpected phone command: " + command)
        return SimpleNamespace(output=values[command])

    return shell


def make_phone(model="RMX3700", build="RMX3700_16.0.5.1300(CN01)", locked=False):
    commands = []
    d = SimpleNamespace(shell=fake_shell(model, build, commands))
    return phone_stub("RMX3700", d=d, W=1240, H=2772, locked=lambda: locked, commands=commands)


def load(phone=None, only=None):
    return load_recipe(phone or make_phone(), RECIPE, only)[0]


class RecipeSafetyTests(unittest.TestCase):
    def test_no_selection_does_not_touch_phone(self):
        phone = make_phone()
        result = load(phone)
        self.assertEqual(result["RESULTS"], [])
        self.assertEqual(phone.commands, [])

    def test_wrong_model_skips_all_steps(self):
        phone = make_phone(model="OTHER")
        result = load(phone, STEPS)
        self.assertEqual(len(result["RESULTS"]), len(STEPS))
        self.assertTrue(all(state == "跳过" for _, state in result["RESULTS"]))
        self.assertEqual(result["FAILED_STEPS"], [])
        self.assertTrue(all(command.startswith("getprop ") for command in phone.commands))

    def test_different_build_skips(self):
        result = load(make_phone(build="RMX3700_17.0.0"), ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "跳过")])

    def test_locked_phone_fails_the_step(self):
        """锁屏不再静默跳过：这一段记未完成，退出码由失败台账给出（#839）。"""
        result = load(make_phone(locked=True), ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "未完成")])
        self.assertEqual(result["FAILED_STEPS"], ["软件商店"])

    def test_store_keep_holds_protected_features(self):
        keep = load()["STORE_KEEP"]
        for name in ["帮助与客服", "应用安全", "我的专区：应用工具",
                     "我的专区：存储空间清理", "我的专区：我的资产", "我的专区：安全守护",
                     "我的专区：小i客服", "应用使用记录", "首页：AI搜索"]:
            self.assertIn(name, keep)
        # 服务类不能和要关的推广位混在一起
        self.assertNotIn("首页：活动弹窗", keep)
        self.assertNotIn("软件专区：福利", keep)
        self.assertNotIn("游戏专区：活动集合", keep)

    def test_tap_by_scroll_never_uses_top(self):
        """p.tap 内部会先回到页顶；小布建议页回顶会判定「离开了当前页」并抛错。"""
        function = load()["tap_by_scroll"]
        phone = make_phone()
        calls = []
        phone.find = lambda text, exact=False: True
        phone.tap = lambda text, exact=False, scrolls=6: calls.append((text, scrolls)) or True
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(function("资讯服务"))
        self.assertEqual(calls, [("资讯服务", 0)])

    def test_tap_by_scroll_gives_up_when_not_found(self):
        function = load()["tap_by_scroll"]
        phone = make_phone()
        phone.find = lambda text, exact=False: False
        phone.scroll_more = lambda: False
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("不存在的入口"))

    def test_wait_page_rejects_out_of_screen_coordinates(self):
        function = load()["wait_page"]
        phone = make_phone()
        phone.screen.focus = lambda: "example.app/ExampleActivity"
        phone.screen.tree = lambda: None
        phone.screen.texts = lambda root: [("设置", (0, 0, 100, 100), {"class": "TextView"})]
        phone.switches = lambda root: [("广告", True, (2294, 600))]
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))

    def test_wait_page_rejects_consent_button(self):
        function = load()["wait_page"]
        phone = make_phone()
        phone.screen.focus = lambda: "example.app/ExampleActivity"
        phone.screen.tree = lambda: None
        phone.screen.texts = lambda root: [("同意并继续", (0, 0, 100, 100), {"class": "android.widget.Button"})]
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))

    def test_wait_page_requires_matching_activity(self):
        function = load()["wait_page"]
        phone = make_phone()
        phone.screen.focus = lambda: "example.app/OtherActivity"
        phone.screen.tree = lambda: None
        phone.screen.texts = lambda root: [("设置", (0, 0, 100, 100), {"class": "TextView"})]
        phone.switches = lambda root: []
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))


if __name__ == "__main__":
    unittest.main()
