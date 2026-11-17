"""离线测试，不连接 adb、不打开手机页面。"""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest

from fixtures import phone_stub, shell_result
import recipe_case
from recipe_case import fake_shell, load

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes/oppo/PHK110/PHK110.toml"


def make_phone(model="PHK110", build="PHK110_16.0.5.1201(CN01)", locked=False):
    shell, commands = fake_shell(model, build)
    d = SimpleNamespace(shell=shell)
    return phone_stub("PHK110", reader=d, W=1240, H=2772, locked=lambda: locked, commands=commands)


class RecipeSafetyTests(recipe_case.OfflineSafetyCase):
    RECIPE = RECIPE
    make_phone = staticmethod(make_phone)

    def test_wrong_model_skips_all_steps(self):
        phone = make_phone(model="OTHER")
        result = load(phone, RECIPE, ["广告跟踪", "软件商店", "浏览器首页", "浏览器广告", "浏览器个性化"])
        self.assertEqual(len(result["RESULTS"]), 5)
        self.assertTrue(all(state == "跳过" for _, state in result["RESULTS"]))
        self.assertEqual(result["FAILED_STEPS"], [])
        self.assertTrue(all(command.startswith("getprop ") for command in phone.commands))

    def test_different_build_skips(self):
        result = load(make_phone(build="PHK110_17.0.0"), RECIPE, ["软件商店"])
        self.assertEqual(result["RESULTS"], [("软件商店", "跳过")])

    def test_protected_store_features_not_selected(self):
        targets = load(make_phone(), RECIPE)["STORE_PROMOTIONS"]
        self.assertEqual(len(targets), 26)
        self.assertEqual(len(set(targets)), 26)
        for name in ["帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：我的资产",
                     "我的专区：安全守护", "应用使用记录", "首页：AI搜索", "我的专区：小i客服"]:
            self.assertNotIn(name, targets)

    def test_permission_denial_does_not_retry_with_privileges(self):
        """`open_app_settings` 走的是注入版（#1153）：闭包拿的是装载时的 Phone，
        所以改装要在装载前把同一个对象传进去，不能再走 `__globals__["p"]`。"""
        phone = make_phone()
        namespace = load(phone, RECIPE)
        phone.shell = lambda command: shell_result("Permission Denial: not exported", 0)
        function = namespace["open_app_settings"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("example.app", "ExampleActivity", "设置"))

    def test_wait_page_rejects_out_of_screen_coordinates(self):
        """`wait_page` 走注入版（#1148）：闭包拿的是装载时的 Phone，改装要在装载前把同一个对象传进去。"""
        phone = make_phone()
        phone.screen.focus = lambda: "example.app/ExampleActivity"
        phone.screen.tree = lambda: None
        phone.screen.texts = lambda root: [("设置", (0, 0, 100, 100), {"class": "TextView"})]
        phone.switches = lambda root: [("广告", True, (2294, 600))]
        function = load(phone, RECIPE)["wait_page"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function("ExampleActivity", "设置", timeout=0.01))

    def test_missing_switch_is_not_reported_completed(self):
        """`off_exact` 现在是注入版（#1253）：闭包拿的是装载时的 Phone，桩要在装载前装好。"""
        phone = make_phone()
        phone.screen.tree = lambda: None
        phone.switches = lambda root=None: [("帮助与客服", True, (1000, 600))]
        phone.scroll_more = lambda: False
        function = load(phone, RECIPE)["off_exact_paged"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function(["开屏广告"], "test"))

    def test_failed_switch_is_not_reported_completed(self):
        phone = make_phone()
        phone.screen.tree = lambda: None
        phone.switches = lambda root=None: [("开屏广告", True, (1000, 600))]
        phone.off = lambda **kwargs: 0
        function = load(phone, RECIPE)["off_exact_paged"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(function(["开屏广告"], "test"))

    def test_similar_unknown_service_is_explicitly_preserved(self):
        phone = make_phone()
        calls = []
        phone.screen.tree = lambda: None
        phone.switches = lambda root=None: [
            ("开屏广告", False, (1000, 600)),
            ("开屏广告权限提醒", True, (1000, 900)),
        ]
        phone.off = lambda **kwargs: calls.append(kwargs)
        function = load(phone, RECIPE)["off_exact_paged"]
        self.assertTrue(function(["开屏广告"], "test"))
        self.assertEqual(calls[0]["only"], ["开屏广告"])
        self.assertIn("开屏广告权限提醒", calls[0]["keep"])


class AdTrackingPagedTests(unittest.TestCase):
    """`ad_tracking_close_paged`（#1363）：等列表真正加载再回页顶整页关，加载不出来不空跑。"""

    def test_list_that_never_loads_is_not_reported_completed(self):
        phone = make_phone()
        phone.switches = lambda root=None: []
        top, off = [], []
        phone.top = lambda *args, **kwargs: top.append((args, kwargs))
        phone.off = lambda **kwargs: off.append(kwargs)
        function = load(phone, RECIPE)["ad_tracking_close_paged"]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(function())
        self.assertIn("列表未加载", out.getvalue())
        self.assertEqual((top, off), ([], []))

    def test_loaded_list_starts_from_the_top_of_forty_screens(self):
        phone = make_phone()
        phone.switches = lambda root=None: [("广告", True, (0, 0))]
        top, off = [], []
        phone.top = lambda *args, **kwargs: top.append((args, kwargs))
        phone.off = lambda **kwargs: off.append(kwargs) or 1
        function = load(phone, RECIPE)["ad_tracking_close_paged"]
        self.assertTrue(function())
        self.assertEqual(top, [((), {"n": 16})])
        self.assertEqual(off, [{"page": "广告跟踪", "max_screens": 40}])


if __name__ == "__main__":
    unittest.main()
