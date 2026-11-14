"""拨动策略的注入面（`tool/recipe_strategies.py`，#1244）：前导调用它、脚本不留逐字副本，
以及家族库里按脚本常量选走法的那几处（齿轮 / 浏览器设置）。

判据与 `test_recipe_nav.py` 同形：实现住在工厂里、前导名字按 `g` 现取；脚本侧只留调用点，
本地同名 `def` 不许再留与注入版逐字相同的副本。走法分派用假手机断言「选了哪一份」与
「认不出的值当场报错」——静默回退会点错入口，比报错更难查。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import phone_mock  # noqa: E402

GEAR_NODE = ('<hierarchy rotation="0"><node class="android.widget.ImageView" text="设置"'
             ' clickable="true" bounds="[900,100][1020,220]"/></hierarchy>')


def scope(**constants):
    """一次执行的视图：假手机 + `rt`（带脚本常量）+ 按执行绑好的库函数。"""
    import functools
    from types import MappingProxyType
    import catalog.interpreter as interpreter
    import recipe_runtime
    phone = phone_mock(W=1080, H=2400)
    phone.d = Mock()
    phone.tree.return_value = ET.fromstring('<hierarchy rotation="0"></hierarchy>')
    phone.on_screen.return_value = True
    rt = recipe_runtime.Runtime(phone)
    rt.constants = MappingProxyType(dict(constants))
    g = {"time": rt.clock, "rt": rt, "p": phone}
    for name, fn in interpreter.LIBRARY.items():
        g[name] = functools.partial(fn, phone, rt)
    return phone, g




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


    def test_an_unknown_wait_page_style_fails_instead_of_falling_back(self):
        _phone, g = scope(WAIT_PAGE_STYLE="typo")
        with self.assertRaisesRegex(RuntimeError, "WAIT_PAGE_STYLE"):
            g["wait_page"]("example.app/Activity", "标题")

    def test_an_unknown_read_switch_style_fails_instead_of_falling_back(self):
        _phone, g = scope(READ_SWITCHES_STYLE="typo")
        with self.assertRaisesRegex(RuntimeError, "READ_SWITCHES_STYLE"):
            g["read_switches"](1)

    def test_an_unknown_close_named_style_fails_instead_of_falling_back(self):
        _phone, g = scope(CLOSE_NAMED_STYLE="typo")
        with self.assertRaisesRegex(RuntimeError, "CLOSE_NAMED_STYLE"):
            g["close_named"](["甲"], "页")

    def test_the_wait_page_default_keeps_the_old_page_wait(self):
        """没写常量时走 bool 档：空页面上等到预算用完返回 False，不抛（未迁移家族的行为）。"""
        _phone, g = scope()
        self.assertFalse(g["wait_page"]("example.app/Activity", "标题", timeout=0))

    def test_the_exact_tap_style_names_the_current_page(self):
        """PKT110 那一档把当前页文字写进失败句：查「没找到入口」时分得清是改名还是没进页。"""
        _phone, g = scope(TAP_STYLE="exact")
        _phone.tap.return_value = False
        _phone.page_text.return_value = "com.example/.Main"
        with self.assertRaisesRegex(RuntimeError, "未找到入口「多选」；当前页：com.example/.Main"):
            g["tap"]("多选", scrolls=0)


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
