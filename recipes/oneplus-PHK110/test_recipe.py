"""离线测试，不连接 adb、不打开手机页面。"""
import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


RECIPE = Path(__file__).with_name("recipe.py")
sys.path.insert(0, str(RECIPE.parents[2] / "tests"))
from fixtures import load_recipe  # noqa: E402  装载器与引擎注入同一份前导


class FakePhone:
    W, H = 1240, 2772

    def __init__(self, model="PHK110", build="PHK110_16.0.5.1201(CN01)", locked=False):
        self.model, self.build, self.is_locked = model, build, locked
        self.commands, self.changed = [], []
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
    return load_recipe(phone or FakePhone(), RECIPE, only)[0]


class RecipeSafetyTests(unittest.TestCase):
    def test_no_selection_does_not_touch_phone(self):
        phone = FakePhone()
        result = load(phone)
        self.assertEqual(result["RESULTS"], [])
        self.assertEqual(phone.commands, [])

    def test_wrong_model_skips_all_steps(self):
        phone = FakePhone(model="OTHER")
        result = load(phone, ["广告跟踪", "软件商店", "浏览器首页", "浏览器广告", "浏览器个性化"])
        self.assertEqual(len(result["RESULTS"]), 5)
        self.assertTrue(all(state == "跳过" for _, state in result["RESULTS"]))
        self.assertEqual(result["FAILED_STEPS"], [])
        self.assertTrue(all(command.startswith("getprop ") for command in phone.commands))

    def test_different_build_skips(self):
        result = load(FakePhone(build="PHK110_17.0.0"), ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "跳过")])

    def test_locked_phone_fails_the_step(self):
        """锁屏不再静默跳过：这一段记未完成，退出码由失败台账给出（#839）。"""
        result = load(FakePhone(locked=True), ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "未完成")])
        self.assertEqual(result["FAILED_STEPS"], ["软件商店"])

    def test_protected_store_features_not_selected(self):
        targets = load()["STORE_PROMOTIONS"]
        self.assertEqual(len(targets), 26)
        self.assertEqual(len(set(targets)), 26)
        for name in ["帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：我的资产",
                     "我的专区：安全守护", "应用使用记录", "首页：AI搜索", "我的专区：小i客服"]:
            self.assertNotIn(name, targets)

    def test_permission_denial_does_not_retry_with_privileges(self):
        namespace = load()
        phone = FakePhone()
        phone.d.shell = lambda command: SimpleNamespace(output="Permission Denial: not exported")
        function = namespace["open_app_settings"]
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("example.app", "ExampleActivity", "设置"))

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

    def test_missing_switch_is_not_reported_completed(self):
        function = load()["off_exact"]
        phone = FakePhone()
        phone.tree = lambda: None
        phone.switches = lambda root=None: [("帮助与客服", True, (1000, 600))]
        phone.scroll_more = lambda: False
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function(["开屏广告"], "test"))

    def test_failed_switch_is_not_reported_completed(self):
        function = load()["off_exact"]
        phone = FakePhone()
        phone.tree = lambda: None
        phone.switches = lambda root=None: [("开屏广告", True, (1000, 600))]
        phone.off = lambda **kwargs: 0
        function.__globals__["p"] = phone
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function(["开屏广告"], "test"))

    def test_similar_unknown_service_is_explicitly_preserved(self):
        function = load()["off_exact"]
        phone = FakePhone()
        calls = []
        phone.tree = lambda: None
        phone.switches = lambda root=None: [
            ("开屏广告", False, (1000, 600)),
            ("开屏广告权限提醒", True, (1000, 900)),
        ]
        phone.off = lambda **kwargs: calls.append(kwargs)
        function.__globals__["p"] = phone
        self.assertTrue(function(["开屏广告"], "test"))
        self.assertEqual(calls[0]["only"], ["开屏广告"])
        self.assertIn("开屏广告权限提醒", calls[0]["keep"])


if __name__ == "__main__":
    unittest.main()
