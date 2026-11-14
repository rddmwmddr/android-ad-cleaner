"""Redmi Note 14 5G：专用型号匹配、系统版本锁定和保守的开关范围。"""
from pathlib import Path
import sys
import tomllib
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
import fixtures
from fixtures import load_recipe


def segment_of(data, name):
    return next(s for s in data["segment"] if s["name"] == name)


def ops_of(data, name):
    """`.toml` 里某一段的 op 列表（`code=` 段给空）。"""
    return segment_of(data, name).get("ops", [])


def walk(ops):
    for op in ops:
        yield op
        yield from walk(op.get("ops", []))
        yield from walk(op.get("else_ops", []))


class Redmi24094RAD4CRecipeTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "recipes/xiaomi/24094RAD4C/24094RAD4C.toml"
        with open(self.path, "rb") as handle:
            self.data = tomllib.load(handle)
        self.source = (self.path.with_suffix(".py").read_text(encoding="utf-8"))

    def test_actual_model_selects_own_recipe_and_pins_recorded_build(self):
        path, reference = run.recipe_for("24094RAD4C", "Redmi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "24094RAD4C")
        meta = run.recipe_meta(path)
        self.assertEqual(meta["models"], ["24094RAD4C"])
        self.assertEqual(meta["build"], "OS3.0.306.0")
        self.assertEqual(meta["steps"],
                         ["系统广告", "应用商店", "手机管家", "下载管理",
                          "主题", "浏览器", "全局搜索", "负一屏"])

    def test_build_accepts_this_phone_and_rejects_other_hyperos_generation(self):
        phone = {"build": "BP2A.250605.031.A3", "os": "OS3.0.306.0.WOQCNXM"}
        self.assertTrue(run.build_ok(phone, "OS3.0.306.0"))
        self.assertFalse(run.build_ok(phone, "OS4.0"))

    def test_script_keeps_store_mode_updates_and_functional_browser_entries(self):
        self.assertNotIn("极简模式", self.source)
        self.assertEqual(segment_of(self.data, "应用商店").get("code"), "step_store")
        # 商店的「不碰父开关」名单住在例外函数里，逐字保留。
        self.assertIn('keep=["推送消息", "应用更新"]', self.source)
        theme = [op for op in walk(ops_of(self.data, "主题")) if op.get("kind") == "off_required"]
        self.assertEqual([op.get("keep") for op in theme], [["自动更新"]])
        browser = [op for op in walk(ops_of(self.data, "浏览器")) if op.get("kind") == "off"]
        self.assertIn(["宫格位推送"], [op.get("only") for op in browser])
        self.assertIn(["猜你想搜"], [op.get("only") for op in browser])
        self.assertNotIn(["小说"], [op.get("only") for op in browser])
        plain = [op for op in walk(ops_of(self.data, "浏览器"))
                 if op.get("kind") == "lib" and op.get("name") == "close_with_plain_tap"]
        self.assertIn(["个性化内容推荐", "个性化广告推荐"], [op.get("args")[0] for op in plain])

    def test_theme_handles_the_observed_skippable_splash_ad(self):
        theme = list(walk(ops_of(self.data, "主题")))
        find = [op for op in theme if op.get("kind") == "if_find" and op.get("text") == "跳过广告"]
        self.assertTrue(find, "主题段没有处理开屏广告")
        self.assertIn({"kind": "tap", "text": "跳过广告", "scrolls": 0}, find[0]["ops"])

    def test_theme_waits_for_the_bottom_tab_to_settle(self):
        p = Mock()
        scope, _ = load_recipe(p, self.path)
        fixtures.bridge_scope(self, scope)
        scope["tap_bottom_tab"] = Mock(side_effect=[False, False, True])
        self.assertTrue(scope["wait_bottom_tab"]("我的"))
        self.assertEqual(scope["tap_bottom_tab"].call_count, 3)
        self.assertEqual(p.dismiss.call_count, 3)

    def test_plain_tap_fallback_confirms_and_verifies_only_named_switches(self):
        p = Mock()
        p.changed = []
        p.switches.side_effect = [
            [("资源推荐", True, (1, 2)), ("热榜推荐", True, (3, 4)), ("仅在WLAN下加载", False, (5, 6))],
            [("资源推荐", True, (1, 2)), ("热榜推荐", True, (3, 4))],
            [("热榜推荐", True, (3, 4))],
            [("资源推荐", False, (1, 2)), ("热榜推荐", False, (3, 4)), ("仅在WLAN下加载", False, (5, 6))],
        ]
        scope, _ = load_recipe(p, self.path)
        scope["close_with_plain_tap"](["资源推荐", "热榜推荐"], "下载管理·信息流")
        self.assertEqual(p.d.shell.call_count, 2)
        self.assertEqual(p.confirm.call_count, 2)
        self.assertEqual(p.changed, [("下载管理·信息流", "资源推荐"),
                                     ("下载管理·信息流", "热榜推荐")])

    def test_plain_tap_fallback_records_only_switches_it_turned_off(self):
        p = Mock()
        p.changed = []
        p.switches.side_effect = [
            [("资源推荐", False, (1, 2)), ("热榜推荐", True, (3, 4))],
            [("热榜推荐", True, (3, 4))],
            [("资源推荐", False, (1, 2)), ("热榜推荐", False, (3, 4))],
        ]
        scope, _ = load_recipe(p, self.path)
        scope["close_with_plain_tap"](["资源推荐", "热榜推荐"], "浏览器·隐私和安全")
        self.assertEqual(p.d.shell.call_count, 1)
        self.assertEqual(p.changed, [("浏览器·隐私和安全", "热榜推荐")])

    def test_plain_tap_fallback_aborts_when_target_missing(self):
        p = Mock()
        p.switches.return_value = [("其他开关", True, (1, 2))]
        scope, _ = load_recipe(p, self.path)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标"):
            scope["close_with_plain_tap"](["资源推荐", "热榜推荐"], "下载管理·信息流")
        p.d.shell.assert_not_called()

    def test_note_14_pro_remains_a_separate_recipe(self):
        path, reference = run.recipe_for("24090RA29C", "Redmi")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "24090RA29C")


if __name__ == "__main__":
    unittest.main()
