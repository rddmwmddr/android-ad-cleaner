"""离线测试，不连接 adb、不打开手机页面。"""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest

from fixtures import keep_list, phone_stub
import recipe_case
from recipe_case import fake_shell, load

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes/oppo/RMX3700/RMX3700.toml"

STEPS = ["广告跟踪", "软件商店", "浏览器", "下拉搜索", "小布建议", "应用建议"]


def make_phone(model="RMX3700", build="RMX3700_16.0.5.1300(CN01)", locked=False):
    shell, commands = fake_shell(model, build)
    d = SimpleNamespace(shell=shell)
    return phone_stub("RMX3700", reader=d, W=1240, H=2772, locked=lambda: locked, commands=commands)


class RecipeSafetyTests(recipe_case.OfflineSafetyCase):
    RECIPE = RECIPE
    make_phone = staticmethod(make_phone)

    def test_wrong_model_skips_all_steps(self):
        phone = make_phone(model="OTHER")
        result = load(phone, RECIPE, STEPS)
        self.assertEqual(len(result["RESULTS"]), len(STEPS))
        self.assertTrue(all(state == "跳过" for _, state in result["RESULTS"]))
        self.assertEqual(result["FAILED_STEPS"], [])
        self.assertTrue(all(command.startswith("getprop ") for command in phone.commands))

    def test_different_build_skips(self):
        result = load(make_phone(build="RMX3700_17.0.0"), RECIPE, ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "跳过")])

    def test_store_keep_holds_protected_features(self):
        keep = keep_list(RECIPE, "软件商店")
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
        phone = make_phone()
        calls = []
        phone.find = lambda text, exact=False: True
        phone.tap = lambda text, exact=False, scrolls=6: calls.append((text, scrolls)) or True
        function = load(phone, RECIPE)["tap_by_scroll"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(function("资讯服务"))
        self.assertEqual(calls, [("资讯服务", 0)])

    def test_tap_by_scroll_gives_up_when_not_found(self):
        phone = make_phone()
        phone.find = lambda text, exact=False: False
        phone.scroll_more = lambda: False
        function = load(phone, RECIPE)["tap_by_scroll"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("不存在的入口"))

    def test_wait_page_rejects_out_of_screen_coordinates(self):
        phone = make_phone()
        phone.screen.focus = lambda: "example.app/ExampleActivity"
        phone.screen.tree = lambda: None
        phone.screen.texts = lambda root: [("设置", (0, 0, 100, 100), {"class": "TextView"})]
        phone.switches = lambda root: [("广告", True, (2294, 600))]
        function = load(phone, RECIPE)["wait_page"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))

    def test_wait_page_requires_matching_activity(self):
        phone = make_phone()
        phone.screen.focus = lambda: "example.app/OtherActivity"
        phone.screen.tree = lambda: None
        phone.screen.texts = lambda root: [("设置", (0, 0, 100, 100), {"class": "TextView"})]
        phone.switches = lambda root: []
        function = load(phone, RECIPE)["wait_page"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))


if __name__ == "__main__":
    unittest.main()
