"""拨动策略的注入面（`tool/recipe_strategies.py`，#1244）：前导调用它、脚本不留逐字副本，
以及家族库里按脚本常量选走法的那几处（齿轮 / 浏览器设置）。

判据与 `test_recipe_nav.py` 同形：实现住在工厂里、前导名字按 `g` 现取；脚本侧只留调用点，
本地同名 `def` 不许再留与注入版逐字相同的副本。走法分派用假手机断言「选了哪一份」与
「认不出的值当场报错」——静默回退会点错入口，比报错更难查。
"""
import ast
import inspect
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402
import recipe_kit  # noqa: E402
import recipe_nav  # noqa: E402
import recipe_strategies  # noqa: E402
from fixtures import normalize, phone_mock  # noqa: E402

RECIPES = tuple(sorted((ROOT / "recipes").rglob("recipe*.py")))

GEAR_NODE = ('<hierarchy rotation="0"><node class="android.widget.ImageView" text="设置"'
             ' clickable="true" bounds="[900,100][1020,220]"/></hierarchy>')


def scope(**constants):
    """一次装载的执行作用域：`preamble()` 注入的两个协作者与三张注入面，外加脚本常量。"""
    phone = phone_mock(W=1080, H=2400)
    phone.d = Mock()
    phone.tree.return_value = ET.fromstring('<hierarchy rotation="0"></hierarchy>')
    phone.on_screen.return_value = True
    g = {"time": fixtures.RecipeClock()}
    recipe_kit.preamble(phone, g)
    g.update(constants)
    return phone, g


def injected_sources():
    """注入面此刻写进执行作用域的 {名字: 归一后的源码}（两个模块都算）。"""
    _phone, g = scope()
    return {name: normalize(inspect.getsource(g[name]))
            for name in (*recipe_strategies.STRATEGIES, *recipe_nav.NAV)}


class WiringTests(unittest.TestCase):
    def test_the_preamble_installs_the_strategy_surface(self):
        phone, g = phone_mock(), {}
        with patch.object(recipe_strategies, "install", wraps=recipe_strategies.install) as install:
            recipe_kit.preamble(phone, g)
        self.assertEqual(install.call_count, 1)
        self.assertEqual(install.call_args.args, (phone, g))

    def test_the_strategies_reach_the_scope_under_their_registered_names(self):
        _phone, g = scope()
        self.assertLessEqual(set(recipe_strategies.STRATEGIES), set(g))


class NoCopyTests(unittest.TestCase):
    def test_no_script_keeps_a_byte_identical_copy(self):
        """脚本里与注入面逐字相同的模块级函数即红：搬进库里就要删掉本地那份（沿用 #1150 的口径）。"""
        injected = injected_sources()
        offenders = {}
        for path in RECIPES:
            source = path.read_text(encoding="utf-8")
            local = {node.name: normalize(ast.get_source_segment(source, node) or "")
                     for node in ast.parse(source, str(path)).body
                     if isinstance(node, ast.FunctionDef)}
            dup = sorted(name for name, text in local.items()
                         if name in injected and text == injected[name])
            if dup:
                offenders[path.relative_to(ROOT).as_posix()] = dup
        self.assertEqual(offenders, {})


class GearStyleTests(unittest.TestCase):
    def test_an_unknown_gear_style_fails_instead_of_falling_back(self):
        phone, g = scope(GEAR_STYLE="typo")
        with self.assertRaisesRegex(RuntimeError, "GEAR_STYLE"):
            g["gear"]()
        phone.click.assert_not_called()

    def test_the_checked_style_verifies_the_landing_page(self):
        """`checked` 点完要认设置页：没落进设置页、前台又变了，就退回来（沿用 #331 / #407）。"""
        phone, g = scope(GEAR_STYLE="checked")
        phone.tree.return_value = ET.fromstring(GEAR_NODE)
        phone.focus.side_effect = ["com.example/.Main", "com.example/.Other"]
        phone.in_settings_page.return_value = False
        self.assertFalse(g["gear"]())
        phone.back.assert_called_once()

    def test_the_plain_style_returns_without_a_landing_check(self):
        phone, g = scope()
        phone.tree.return_value = ET.fromstring(GEAR_NODE)
        self.assertTrue(g["gear"]())
        phone.in_settings_page.assert_not_called()
        phone.back.assert_not_called()


class BrowserFlowTests(unittest.TestCase):
    def test_an_unknown_flow_fails_instead_of_falling_back_to_the_vivo_page(self):
        _phone, g = scope(BROWSER_FLOW="typo")
        with self.assertRaisesRegex(RuntimeError, "BROWSER_FLOW"):
            g["browser_settings"]()

    def test_the_default_flow_keeps_the_vivo_page_for_unmigrated_families(self):
        """没写常量时走 vivo 那一套：未迁移家族的脚本行为不变（#1244 的形状约束）。"""
        _phone, g = scope()
        called = []
        g["browser_settings_vivo"] = lambda: called.append("vivo")
        g["browser_settings_xiaomi"] = lambda: called.append("xiaomi")
        g["browser_settings"]()
        self.assertEqual(called, ["vivo"])


class StrategyBehaviourTests(unittest.TestCase):
    def test_close_with_plain_tap_confirms_each_row_and_records_the_change(self):
        """短按被吞的那类页面：用 `input tap` 点，回读确认，并记一行改动台账。"""
        phone, g = scope()
        before = [("推荐", True, (100, 200)), ("保留项", True, (300, 400))]
        after = [("推荐", False, (100, 200)), ("保留项", True, (300, 400))]
        phone.switches.side_effect = [before, before, after]
        g["close_with_plain_tap"](["推荐"], "下载管理·信息流")
        phone.d.shell.assert_called_once_with("input tap 100 200")
        phone.confirm.assert_called_once()
        phone.changed.append.assert_called_once_with(("下载管理·信息流", "推荐"))

    def test_close_with_plain_tap_raises_when_a_switch_did_not_turn_off(self):
        phone, g = scope()
        rows = [("推荐", True, (100, 200))]
        phone.switches.side_effect = [rows, rows, rows]
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭"):
            g["close_with_plain_tap"](["推荐"], "下载管理·信息流")

    def test_gear_tap_falls_back_to_input_tap_and_checks_the_landing(self):
        """引擎短按点不动时改用 `input tap`，落点按包名与页面名核对。"""
        phone, g = scope()
        phone.tree.return_value = ET.fromstring(GEAR_NODE)
        phone.focus.return_value = "com.android.browser/.BrowserSettingsActivity"
        self.assertTrue(g["gear_tap"]("com.android.browser", "BrowserSettingsActivity"))
        phone.d.shell.assert_called_once_with("input tap 960 160")


if __name__ == "__main__":
    unittest.main()
