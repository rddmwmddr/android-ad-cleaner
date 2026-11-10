"""主题商店缺失、主题页被系统转走时按跳过收尾（#902）。

没有主题商店的小米 / 红米机型上，主题管理包的代理页会被系统导去应用商店详情页或桌面。
`Phone.start` 等不到前台时抛 RuntimeError，段体要把这一档记成跳过（入口不可达），而不是
未完成；落点在别的 App 时仍是未完成，保留 #547 的落点诊断。
"""
import ast
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adb_link  # noqa: E402
import entries  # noqa: E402
from fixtures import load_recipe, phone_mock  # noqa: E402

THEME = "com.android.thememanager"
STORE = "com.miui.themestore"
MARKET = "com.xiaomi.market/com.xiaomi.market.ui.detail.AppDetailActivityInner"
LAUNCHER = "com.miui.home/.launcher.Launcher"
OTHER = "com.miui.securitycenter/com.miui.securityscan.activity.MainActivity"


def theme_recipes():
    """带 `@step("主题")` 的机型脚本：一份都不能漏，否则「所有共用这段入口的脚本一起改」就没守住。"""
    found = []
    for path in sorted((ROOT / "recipes").glob("*/recipe*.py")):
        if entries.family(path.parent.name.split("-", 1)[0]) != "xiaomi":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "step"
                        and dec.args and getattr(dec.args[0], "value", None) == "主题"):
                    found.append(path)
    return found


class ThemeUnreachableTests(unittest.TestCase):
    def run_theme(self, path, landing, store=""):
        p = phone_mock()
        p.locked = lambda: False
        installed = {STORE: store, THEME: "package:/system/app/ThemeManager/ThemeManager.apk"}

        def shell(command, timeout=None):
            for package, output in installed.items():
                if command == "pm path " + package:
                    return SimpleNamespace(output=output, exit_code=0)
            return SimpleNamespace(output="", exit_code=0)

        p.d.shell.side_effect = shell
        # 落点只认 `Phone.start` 报错里带着的那份；抛错之后再读前台有窗口期，故意让它读成别的。
        p.focus = lambda: "com.example.stale/.Main"
        p.start.side_effect = RuntimeError(
            f"{THEME} 没有进入前台，跳过本段（停在 {landing}；标题 5 个、开关 0 个）")
        out = io.StringIO()
        scope, _ = load_recipe(p, path, only="主题", out=out)
        return scope, out.getvalue(), p

    @staticmethod
    def manager_only():
        """只装了主题管理包、没有主题商店：脚本会走代理页兜底。"""
        def shell(command, timeout=None):
            installed = command == "pm path " + THEME
            return SimpleNamespace(output="package:/system/app/ThemeManager/ThemeManager.apk"
                                   if installed else "", exit_code=0)
        return shell

    def test_store_detail_page_landing_is_skipped(self):
        """主题商店缺失 + 落在应用商店详情页：跳过，理由里带落点。"""
        scope, out, _ = self.run_theme(ROOT / "recipes/xiaomi-24129PN74C/recipe.py", MARKET)
        self.assertEqual(scope["SKIPPED_STEPS"], ["主题"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("com.xiaomi.market", out)

    def test_every_theme_recipe_skips_when_the_store_page_takes_over(self):
        """所有共这段入口的小米 / 红米脚本一起改：商店详情页落点哪一份都不能记成未完成。"""
        recipes = theme_recipes()
        self.assertGreaterEqual(len(recipes), 15, "主题段的机型脚本少找了")
        for path in recipes:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, out, _ = self.run_theme(path, MARKET)
                self.assertEqual(scope["SKIPPED_STEPS"], ["主题"])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("com.xiaomi.market", out)

    def test_launcher_landing_is_skipped_too(self):
        """桌面落点与被导去应用商店是同一档：主题页根本打不开。"""
        for path in theme_recipes():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, out, _ = self.run_theme(path, LAUNCHER)
                self.assertEqual(scope["SKIPPED_STEPS"], ["主题"])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("com.miui.home", out)

    def test_another_app_taking_over_stays_unfinished(self):
        """落点是别的 App（例如开屏广告顶掉）不是「入口不可达」：仍按未完成上报，落点留在理由里。"""
        for path in theme_recipes():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                scope, out, _ = self.run_theme(path, OTHER)
                self.assertEqual(scope["FAILED_STEPS"], ["主题"])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                self.assertIn("未完成", out)
                self.assertIn("com.miui.securitycenter", out)

    def test_launch_error_that_is_not_a_landing_mismatch_stays_unfinished(self):
        """「无法打开 / 没装」不是落点不对：那时前台可能只是桌面，不能当成入口不可达的证据。"""
        p = phone_mock()
        p.locked = lambda: False
        p.focus = lambda: LAUNCHER
        p.d.shell.side_effect = self.manager_only()
        p.start.side_effect = RuntimeError(f"无法打开 {THEME}：** No activities found to run")
        out = io.StringIO()
        scope, _ = load_recipe(p, ROOT / "recipes/xiaomi-24129PN74C/recipe.py", only="主题", out=out)
        self.assertEqual(scope["FAILED_STEPS"], ["主题"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertIn("No activities found", out.getvalue())

    def test_disconnect_is_not_reported_as_an_unreachable_entry(self):
        """断线交还引擎整轮停下，不能被当成「入口不可达」收成跳过。"""
        p = phone_mock()
        p.locked = lambda: False
        p.focus = lambda: LAUNCHER
        p.d.shell.side_effect = self.manager_only()
        p.start.side_effect = adb_link.DeviceLost("device offline")
        with self.assertRaises(adb_link.DeviceLost):
            load_recipe(p, ROOT / "recipes/xiaomi-24129PN74C/recipe.py", only="主题", out=io.StringIO())

    def test_installed_store_does_not_change_the_launch(self):
        """主题商店在不在都直达代理页（#906），不再经商店冷启动过一次重定向过渡窗。

        商店路径只在 #730 的兜底里出现过；现在统一成一条，落点被转走仍按跳过收尾。"""
        for path in theme_recipes():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                _, _, p = self.run_theme(path, MARKET,
                                         store="package:/system/app/ThemeStore/ThemeStore.apk")
                self.assertEqual(p.start.call_args_list[0].args[0], THEME)
                self.assertNotIn(STORE, [call.args[0] for call in p.start.call_args_list])


if __name__ == "__main__":
    unittest.main()
