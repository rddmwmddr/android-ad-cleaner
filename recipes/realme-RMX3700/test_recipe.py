"""离线测试，不连接 adb、不打开手机页面。"""
import contextlib
import io
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest


RECIPE = Path(__file__).with_name("recipe.py")

STEPS = ["广告跟踪", "软件商店", "浏览器", "下拉搜索", "小布建议", "应用建议"]


class FakePhone:
    W, H = 1240, 2772

    def __init__(self, model="RMX3700", build="RMX3700_16.0.5.1300(CN01)", locked=False):
        self.model, self.build, self.is_locked = model, build, locked
        self.commands, self.changed = [], []
        self.miss = 0
        self.d = SimpleNamespace(shell=self.shell)

    def shell(self, command):
        self.commands.append(command)
        values = {"getprop ro.product.model": self.model, "getprop ro.build.display.id": self.build}
        if command not in values:
            raise AssertionError("Unexpected phone command: " + command)
        return SimpleNamespace(output=values[command])

    def locked(self):
        return self.is_locked


def load(phone=None, only=None):
    with contextlib.redirect_stdout(io.StringIO()):
        return runpy.run_path(str(RECIPE), init_globals={"p": phone or FakePhone(), "ONLY": only or ["__offline__"]})


class RecipeSafetyTests(unittest.TestCase):
    def test_no_selection_does_not_touch_phone(self):
        phone = FakePhone()
        result = load(phone)
        self.assertEqual(result["RESULTS"], [])
        self.assertEqual(phone.commands, [])

    def test_wrong_model_skips_all_steps(self):
        phone = FakePhone(model="OTHER")
        result = load(phone, STEPS)
        self.assertEqual(len(result["RESULTS"]), len(STEPS))
        self.assertTrue(all(state == "version_mismatch" for _, state in result["RESULTS"]))
        self.assertTrue(all(command.startswith("getprop ") for command in phone.commands))

    def test_different_build_skips(self):
        result = load(FakePhone(build="RMX3700_17.0.0"), ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "version_mismatch")])

    def test_locked_phone_skips(self):
        result = load(FakePhone(locked=True), ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "locked")])

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
        phone = FakePhone()
        calls = []
        phone.find = lambda text, exact=False: True
        phone.tap = lambda text, exact=False, scrolls=6: calls.append((text, scrolls)) or True
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(function("资讯服务"))
        self.assertEqual(calls, [("资讯服务", 0)])

    def test_tap_by_scroll_gives_up_when_not_found(self):
        function = load()["tap_by_scroll"]
        phone = FakePhone()
        phone.find = lambda text, exact=False: False
        phone.scroll_more = lambda: False
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("不存在的入口"))

    def test_wait_page_rejects_out_of_screen_coordinates(self):
        function = load()["wait_page"]
        phone = FakePhone()
        phone.focus = lambda: "example.app/ExampleActivity"
        phone.tree = lambda: None
        phone.texts = lambda root: [("设置", (0, 0, 100, 100), {"class": "TextView"})]
        phone.switches = lambda root: [("广告", True, (2294, 600))]
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))

    def test_wait_page_rejects_consent_button(self):
        function = load()["wait_page"]
        phone = FakePhone()
        phone.focus = lambda: "example.app/ExampleActivity"
        phone.tree = lambda: None
        phone.texts = lambda root: [("同意并继续", (0, 0, 100, 100), {"class": "android.widget.Button"})]
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))

    def test_wait_page_requires_matching_activity(self):
        function = load()["wait_page"]
        phone = FakePhone()
        phone.focus = lambda: "example.app/OtherActivity"
        phone.tree = lambda: None
        phone.texts = lambda root: [("设置", (0, 0, 100, 100), {"class": "TextView"})]
        phone.switches = lambda root: []
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))


if __name__ == "__main__":
    unittest.main()
