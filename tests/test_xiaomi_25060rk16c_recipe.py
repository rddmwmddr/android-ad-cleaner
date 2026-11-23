"""REDMI K80 Ultra（25060RK16C）：OS4 变体的选择与浏览器入口（#1527）。

HyperOS 2 与 OS4 的浏览器入口布局不同，主本 `<型号>.toml` 留给 HyperOS 2（工具栏齿轮），
OS4 走 `-os4` 变体（底栏「菜单」）。这两条路径分别由 recipe_for 与家族库决定。
"""
import contextlib
import io
from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import fast
import run
from fixtures import Clock, clocked, fake_phone, load_recipe, stub

RECIPE_DIR = ROOT / "recipes/xiaomi/25060RK16C"
MAIN = RECIPE_DIR / "25060RK16C.toml"
VARIANT = RECIPE_DIR / "25060RK16C-os4.toml"

BROWSER = "com.android.browser/com.android.browser.BrowserActivity"
BROWSER_SETTINGS = "com.android.browser/com.android.browser.BrowserSettingsActivity"

BOTTOM_WITH_MENU = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="后退" bounds="[0,2280][216,2400]" />
    <node class="android.widget.TextView" text="菜单" bounds="[648,2280][864,2400]" />
  </node>
</hierarchy>"""

MENU_POPUP = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="设置" clickable="true" bounds="[720,730][1020,790]" />
  </node>
</hierarchy>"""

SETTINGS_PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="隐私和安全" clickable="true" bounds="[48,320][600,420]" />
  </node>
</hierarchy>"""

MENU_CENTER = (756, 2340)


def _browser_ops(path):
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data["const"], next(s for s in data["segment"] if s["name"] == "浏览器")["ops"]


class K80UltraOs4VariantTests(unittest.TestCase):
    def test_os4_picks_the_variant_and_hyperos2_picks_the_main(self):
        os4 = {"build": "CP2A.260605.016", "os": "OS4.0.3.0.XONCNXM"}
        path, reference = run.recipe_for("25060RK16C", "Xiaomi", os4)
        self.assertFalse(reference)
        self.assertEqual(Path(path).name, "25060RK16C-os4.toml")
        os2 = {"build": "BP2A.250605.031.A3", "os": "OS2.0.1.0.VOCNMXM"}
        path2, _ = run.recipe_for("25060RK16C", "Xiaomi", os2)
        self.assertEqual(Path(path2).name, "25060RK16C.toml")

    def test_variant_pins_the_hyperos_version_and_main_stays_unpinned(self):
        self.assertEqual(run.recipe_meta(VARIANT)["build"], "OS4.0")
        self.assertEqual(run.recipe_meta(MAIN)["build"], "")

    def test_variant_exception_module_supplies_the_search_constants(self):
        """变体与主本共用家族库的全局搜索段：没有同名 `.py`，`only=rt.constants['HOT']` 会 KeyError。"""
        p = fake_phone()
        scope, _out = load_recipe(p, VARIANT)
        self.assertIn("HOT", scope["rt"].constants)

    def test_variant_enters_the_settings_page_through_lib(self):
        const, ops = _browser_ops(VARIANT)
        self.assertEqual(const["BROWSER_FLOW"], "menu")
        entries = [op for op in ops if op.get("name") == "browser_settings"]
        self.assertEqual([op["kind"] for op in entries], ["lib"])

    def test_main_keeps_the_toolbar_flow_and_require_lib(self):
        const, ops = _browser_ops(MAIN)
        self.assertEqual(const["BROWSER_FLOW"], "toolbar")
        entries = [op for op in ops if op.get("name") == "browser_settings"]
        self.assertEqual([op["kind"] for op in entries], ["require_lib"])

    def test_variant_browser_entry_taps_the_bottom_menu(self):
        """真跑一次家族库的 menu 流程：底栏「菜单」被点到，进了设置页才算成功。"""
        clock = Clock(click_cost=0.05)
        clocked(self, fast, clock)
        p = fake_phone(clock=clock, size=(1080, 2400),
                       stages=[(0.0, BOTTOM_WITH_MENU), (0.3, MENU_POPUP), (1.2, SETTINGS_PAGE)],
                       focus=((0.0, BROWSER), (1.2, BROWSER_SETTINGS)))
        clicked = []
        stub(p, "click", lambda x, y: (clicked.append((x, y)), clock.click())[1])
        scope, _out = load_recipe(p, VARIANT)
        scope["rt"].clock = clock
        with contextlib.redirect_stdout(io.StringIO()):
            scope["browser_settings"]()
        self.assertIn(MENU_CENTER, clicked)


if __name__ == "__main__":
    unittest.main()
