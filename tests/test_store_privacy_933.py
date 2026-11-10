"""#933：OPPO / 一加 / realme 五支脚本的软件商店隐私入口。

商店 App 独立升级，设置页那一行在有的版本里叫「隐私」，有的叫「隐私授权管理」；#907 只改了
PMX110 / PLZ110，这五支仍写死单一文案，认不到就是整段 0 项或整段失败。这里一次守住五支：
两种文案都认、「隐私」优先、点进去按落点页面判、认不到时留下停在哪个页面与结构摘要。
真机落点仍要另验。
"""
import ast
import contextlib
import io
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock

PRIVACY = ("隐私", "隐私授权管理")
MARKET = "com.heytap.market/com.heytap.market.mine.cn.setting.ui."
PRIVACY_PAGE = MARKET + "PrivacyActivity"
RECIPES = {
    "PLG110": ROOT / "recipes/oppo-PLG110/recipe.py",
    "PMA110": ROOT / "recipes/oppo-PMA110/recipe.py",
    "PKX110": ROOT / "recipes/oneplus-PKX110/recipe.py",
    "RMX3700": ROOT / "recipes/realme-RMX3700/recipe.py",
    "PHK110": ROOT / "recipes/oneplus-PHK110/recipe_android15.py",
}


def load(phone, recipe):
    scope, _ = load_recipe(phone, recipe)
    return scope


def action(scope, recipe, name):
    """取真实分段的函数体，以便给它的协作者注入替身；不复制分段实现。"""
    node = next(n for n in ast.parse(recipe.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.decorator_list
                and n.decorator_list[0].args[0].value == name)
    node.decorator_list, node.name = [], "selected_action"
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(recipe), "exec"), scope)
    return scope["selected_action"]


def tapping_phone(present):
    """只在 `present` 里的文案点得动的假手机。"""
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.tap.side_effect = lambda text, **kwargs: text in present
    return p


def segment_phone():
    """商店段自己的点击（「我的」→「设置」这些）一律成功，只让入口方法被断言。"""
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.tap.return_value = True
    return p


def store_page(title):
    """停在商店隐私页：标题按本机商店版本叫「隐私」或「隐私授权管理」，页上没有开关。"""
    p = phone_mock(W=1080, H=2340)
    p.locked.return_value = False
    p.focus.return_value = PRIVACY_PAGE
    p.tree.return_value = ET.fromstring(
        f'<hierarchy><node text="{title}" bounds="[0,0][1080,150]"/></hierarchy>')
    p.texts.return_value = [(title, (40, 40), {})]
    p.switches.return_value = []
    return p


class TapPageEntryTests(unittest.TestCase):
    """PLG110 与 PMA110 的 `tap_page(text, activity, title=None, scrolls=4)`。"""

    RECIPES = {name: RECIPES[name] for name in ("PLG110", "PMA110")}

    def entry(self, recipe, present):
        p = tapping_phone(present)
        scope = load(p, recipe)
        scope["wait_page"] = Mock()
        return p, scope

    def test_each_wording_opens_the_store_privacy_page(self):
        for name, recipe in self.RECIPES.items():
            for wording in PRIVACY:
                with self.subTest(recipe=name, wording=wording):
                    p, scope = self.entry(recipe, {wording})
                    scope["tap_page"](PRIVACY, PRIVACY_PAGE, scrolls=8)
                    scope["wait_page"].assert_called_once_with(PRIVACY_PAGE, wording)
                    p.note_miss.assert_not_called()

    def test_privacy_wording_wins_when_both_are_on_the_page(self):
        for name, recipe in self.RECIPES.items():
            with self.subTest(name):
                p, scope = self.entry(recipe, set(PRIVACY))
                scope["tap_page"](PRIVACY, PRIVACY_PAGE, scrolls=8)
                self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["隐私"])

    def test_neither_wording_keeps_the_page_scene_and_the_sentence(self):
        for name, recipe in self.RECIPES.items():
            with self.subTest(name):
                p, scope = self.entry(recipe, set())
                with self.assertRaisesRegex(RuntimeError, "未找到入口「隐私」"):
                    scope["tap_page"](PRIVACY, PRIVACY_PAGE, scrolls=8)
                p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")
                scope["wait_page"].assert_not_called()

    def test_a_single_name_still_works_and_keeps_the_old_message(self):
        """这两份脚本的其余十来处入口仍是单字面量，行为与失败句不能跟着变。"""
        for name, recipe in self.RECIPES.items():
            with self.subTest(name):
                p, scope = self.entry(recipe, {"搜索范围"})
                scope["tap_page"]("搜索范围", MARKET + "ServeManagerActivity")
                scope["wait_page"].assert_called_once_with(MARKET + "ServeManagerActivity", "搜索范围")
                p.tap.assert_called_once_with("搜索范围", exact=True, scrolls=4, quiet=False)

                p, scope = self.entry(recipe, set())
                with self.assertRaisesRegex(RuntimeError, "未找到入口「搜索范围」"):
                    scope["tap_page"]("搜索范围", MARKET + "ServeManagerActivity")
                p.note_miss.assert_called_once_with("搜索范围")


class Pkx110EntryTests(unittest.TestCase):
    def entry(self, present):
        p = tapping_phone(present)
        scope = load(p, RECIPES["PKX110"])
        scope["wait_page"] = Mock(return_value=True)
        return p, scope

    def test_each_wording_opens_the_store_privacy_page(self):
        for wording in PRIVACY:
            with self.subTest(wording):
                p, scope = self.entry({wording})
                self.assertTrue(scope["tap_page"](PRIVACY, PRIVACY_PAGE, PRIVACY))
                scope["wait_page"].assert_called_once_with(PRIVACY_PAGE, PRIVACY)
                p.note_miss.assert_not_called()

    def test_privacy_wording_wins_when_both_are_on_the_page(self):
        p, scope = self.entry(set(PRIVACY))
        scope["tap_page"](PRIVACY, PRIVACY_PAGE, PRIVACY)
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["隐私"])

    def test_neither_wording_keeps_the_page_scene(self):
        p, scope = self.entry(set())
        self.assertFalse(scope["tap_page"](PRIVACY, PRIVACY_PAGE, PRIVACY))
        p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")
        scope["wait_page"].assert_not_called()

    def test_page_title_accepts_either_wording(self):
        for wording in PRIVACY:
            with self.subTest(wording):
                scope = load(store_page(wording), RECIPES["PKX110"])
                self.assertTrue(scope["wait_page"]("PrivacyActivity", PRIVACY))

    def test_failed_landing_is_not_retried_on_the_next_wording(self):
        """点开了但没落到隐私页：就此停段，不在别的页面上再点一次同名行。"""
        p, scope = self.entry(set(PRIVACY))
        scope["wait_page"] = Mock(return_value=False)
        self.assertFalse(scope["tap_page"](PRIVACY, PRIVACY_PAGE, PRIVACY))
        p.tap.assert_called_once_with("隐私", exact=True, quiet=True)


class Phk110EntryTests(unittest.TestCase):
    def entry(self, present):
        p = tapping_phone(present)
        scope = load(p, RECIPES["PHK110"])
        scope["page"] = Mock(return_value=True)
        return p, scope

    def test_each_wording_opens_the_store_privacy_page(self):
        for wording in PRIVACY:
            with self.subTest(wording):
                p, scope = self.entry({wording})
                self.assertTrue(scope["navigate"](PRIVACY, "PrivacyActivity", PRIVACY))
                scope["page"].assert_called_once_with("PrivacyActivity", PRIVACY)
                p.note_miss.assert_not_called()

    def test_privacy_wording_wins_when_both_are_on_the_page(self):
        p, scope = self.entry(set(PRIVACY))
        scope["navigate"](PRIVACY, "PrivacyActivity", PRIVACY)
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["隐私"])

    def test_neither_wording_keeps_the_page_scene(self):
        p, scope = self.entry(set())
        self.assertFalse(scope["navigate"](PRIVACY, "PrivacyActivity", PRIVACY))
        p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")
        scope["page"].assert_not_called()

    def test_page_title_accepts_either_wording(self):
        for wording in PRIVACY:
            with self.subTest(wording):
                scope = load(store_page(wording), RECIPES["PHK110"])
                self.assertTrue(scope["page"]("PrivacyActivity", PRIVACY))


class Rmx3700EntryTests(unittest.TestCase):
    def test_tap_by_scroll_tries_both_wordings(self):
        for wording in PRIVACY:
            with self.subTest(wording):
                p = phone_mock(W=1080, H=2340)
                p.find.side_effect = lambda text, exact=False: text == wording  # noqa: B023 - 当轮创建当轮消费，tap_by_scroll 同步调用
                scope = load(p, RECIPES["RMX3700"])
                self.assertTrue(scope["tap_by_scroll"](PRIVACY))
                p.tap.assert_called_once_with(wording, exact=True, scrolls=0)

    def test_privacy_wording_is_tried_first(self):
        p = phone_mock(W=1080, H=2340)
        p.find.return_value = True
        scope = load(p, RECIPES["RMX3700"])
        scope["tap_by_scroll"](PRIVACY)
        self.assertEqual(p.find.call_args_list[0].args[0], "隐私")

    def test_neither_wording_ends_the_scroll(self):
        p = phone_mock(W=1080, H=2340)
        p.find.return_value = False
        p.scroll_more.return_value = False
        scope = load(p, RECIPES["RMX3700"])
        self.assertFalse(scope["tap_by_scroll"](PRIVACY))
        p.tap.assert_not_called()
        p.scroll_more.assert_called_once_with()

    def test_page_title_accepts_either_wording(self):
        for wording in PRIVACY:
            with self.subTest(wording):
                scope = load(store_page(wording), RECIPES["RMX3700"])
                self.assertTrue(scope["wait_page"]("PrivacyActivity", PRIVACY))


class StoreSegmentTests(unittest.TestCase):
    """商店段把两种文案一起交给本脚本的入口方法 —— 撤掉实现这几条就红。"""

    def segment(self, name, step, **stubs):
        scope = load(segment_phone(), RECIPES[name])
        for helper, value in stubs.items():
            scope[helper] = Mock(return_value=value)
        action(scope, RECIPES[name], step)()
        return scope

    def test_plg110_passes_both_wording(self):
        scope = self.segment("PLG110", "软件商店",
                             app_settings=None, tap_page=None, close_named=None, read_switches={})
        self.assertEqual(scope["tap_page"].call_args_list[0].args[0], PRIVACY)

    def test_pma110_passes_both_wording(self):
        scope = self.segment("PMA110", "软件商店", app_settings=None, tap_page=None, close_named=None)
        self.assertEqual(scope["tap_page"].call_args_list[0].args[0], PRIVACY)

    def test_pkx110_passes_both_wording(self):
        scope = self.segment("PKX110", "软件商店·个性化",
                             open_app_settings=True, tap_page=True, off_exact=True)
        self.assertEqual(scope["tap_page"].call_args_list[0].args[0], PRIVACY)

    def test_rmx3700_passes_both_wording(self):
        scope = self.segment("RMX3700", "软件商店", tap_by_scroll=True, wait_page=True)
        self.assertIn(PRIVACY, [c.args[0] for c in scope["tap_by_scroll"].call_args_list])

    def test_phk110_passes_both_wording(self):
        scope = self.segment("PHK110", "软件商店个性化",
                             open_settings=True, navigate=True, off_exact=True)
        self.assertEqual(scope["navigate"].call_args_list[0].args[0], PRIVACY)

    def test_rmx3700_missing_row_keeps_the_original_line_and_the_scene(self):
        p = segment_phone()
        scope = load(p, RECIPES["RMX3700"])
        scope["tap_by_scroll"] = Mock(return_value=False)
        scope["wait_page"] = Mock(return_value=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            action(scope, RECIPES["RMX3700"], "软件商店")()
        self.assertIn("没找到「隐私授权管理」", out.getvalue())
        p.note_miss.assert_called_once_with("隐私 / 隐私授权管理")


if __name__ == "__main__":
    unittest.main()
