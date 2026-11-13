"""#911：一加 Ace 2 Pro（PJA110）ColorOS 16 变体——设置页直达、推广位缺席项只报告、回读不写成功。"""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe, phone_mock

VARIANT = ROOT / "recipes/oppo/PJA110/PJA110-android16.toml"
OLD = ROOT / "recipes/oppo/PJA110/PJA110.toml"
MARKET = "com.heytap.market/com.heytap.market.mine.cn.setting.ui.SettingActivity"
MARKET_MAIN = "com.heytap.market/com.heytap.market.activity.MainActivity"
BROWSER = "com.heytap.browser/com.heytap.browser.settings.component.BrowserPreferencesPage"
SEARCH_SETTINGS = "com.heytap.quicksearchbox/.ui.activity.SearchSettingActivity"
SEARCH_HOME = "com.heytap.quicksearchbox/.ui.activity.SearchHomeActivity"
EVIDENCE = "停在 com.heytap.market/.MainActivity；结构摘要；当次读到 0 个开关：无"


def phone(focus=MARKET, **fields):
    p = phone_mock(locked=lambda: False, **fields)
    p.d.shell.return_value = SimpleNamespace(exit_code=0, output="")
    p.focus.return_value = focus
    p.page_evidence.return_value = EVIDENCE
    p.expect_page.return_value = True
    p.scroll_more.return_value = False
    return p


def loaded(p):
    scope, _ = load_recipe(p, VARIANT)
    return scope


class VersionTests(unittest.TestCase):
    def test_android16_build_selects_variant_and_14_keeps_original(self):
        new = {"build": "PJA110_16.0.5.1201(CN01)", "os": ""}
        old = {"build": "PJA110_14.0.0.812", "os": ""}
        self.assertEqual(Path(run.recipe_for("PJA110", "OnePlus", new)[0]).name, "PJA110-android16.toml")
        self.assertEqual(Path(run.recipe_for("PJA110", "OnePlus", old)[0]).name, "PJA110.toml")
        self.assertEqual(run.recipe_meta(VARIANT)["build"], "PJA110_16.0.5.1201")
        self.assertEqual(run.recipe_meta(OLD)["build"], "PJA110_14.0.0.812")


class SettingsEntryTests(unittest.TestCase):
    def test_system_refusal_stops_without_looking_for_the_page(self):
        p = phone()
        p.d.shell.return_value = SimpleNamespace(exit_code=0, output="Error: Permission Denial: not exported")
        scope = loaded(p)
        with self.assertRaisesRegex(RuntimeError, "com.heytap.market：系统不允许直达设置"):
            scope["open_settings"]("com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity",
                                   "应用与服务")
        p.expect_page.assert_not_called()

    def test_wrong_page_reports_where_it_stopped_and_never_touches_switches(self):
        p = phone()
        p.expect_page.return_value = False
        scope = loaded(p)
        with self.assertRaisesRegex(RuntimeError, "设置页未打开；" + EVIDENCE):
            scope["open_settings"]("com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity",
                                   "应用与服务")
        p.off.assert_not_called()

    def test_page_title_without_the_settings_activity_is_not_taken_as_landed(self):
        """标题对得上、落点却停在 App 首页：Intent 没生效时不能当已经进了设置页。"""
        p = phone(focus=MARKET_MAIN)
        scope = loaded(p)
        with self.assertRaisesRegex(RuntimeError, f"没落在设置页（停在 {MARKET_MAIN}）"):
            scope["open_settings"]("com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity",
                                   "应用与服务")


class SearchTests(unittest.TestCase):
    def ready_phone(self):
        p = phone(focus=SEARCH_SETTINGS)
        p.texts.return_value = [("账号与隐私", (0, 0, 10, 10), None)]
        return p

    def test_scheme_landing_skips_the_search_home_page(self):
        p = self.ready_phone()
        p.switches.side_effect = [[("个性化推荐", True, (1, 2))], [("个性化推荐", False, (1, 2))]]
        scope, _ = load_recipe(p, VARIANT, only="下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.start.assert_not_called()
        self.assertEqual([c.args[0] for c in p.enter.call_args_list], ["账号与隐私", "隐私"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_falls_back_to_the_bottom_most_settings_on_the_search_home_page(self):
        """scheme 不通时才退回搜索首页，并且只点 0.8 屏高以下最靠下的那个「设置」。"""
        p = phone(focus=SEARCH_HOME, W=1080, H=2400)
        state = {"ready": False}
        p.focus.side_effect = lambda: SEARCH_SETTINGS if state["ready"] else SEARCH_HOME
        p.texts.side_effect = lambda: (
            [("账号与隐私", (0, 0, 10, 10), None)] if state["ready"] else
            [("设置", (40, 400, 600, 500), None),          # 搜索范围列表里的同名项：不能点
             ("设置", (40, 1950, 600, 2000), None),
             ("设置", (40, 2200, 600, 2250), None)])
        p.click.side_effect = lambda x, y: state.update(ready=True)
        p.switches.side_effect = [[("个性化推荐", True, (1, 2))], [("个性化推荐", False, (1, 2))]]
        scope, _ = load_recipe(p, VARIANT, only="下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.click.assert_called_once_with(320, 2225)
        p.start.assert_called_once_with("com.heytap.quicksearchbox", ".ui.activity.SearchHomeActivity")

    def test_no_settings_at_the_bottom_reports_the_page(self):
        p = phone(focus=SEARCH_HOME, W=1080, H=2400)
        p.texts.return_value = [("设置", (40, 400, 600, 500), None)]
        scope, out = load_recipe(p, VARIANT, only="下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], ["下拉搜索"])
        self.assertIn("搜索首页底部没有「设置」", out.getvalue())
        p.click.assert_not_called()


class StoreTests(unittest.TestCase):
    def test_personalised_switch_is_closed_on_the_second_level_page(self):
        p = phone()
        p.switches.side_effect = [[("个性化推荐", True, (1, 2))], [("个性化推荐", False, (1, 2))]]
        scope, _ = load_recipe(p, VARIANT, only="软件商店")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.off.assert_called_once_with(only=["个性化推荐"], page="商店·个性化推荐", max_screens=1)
        self.assertEqual([c.args[0] for c in p.enter.call_args_list], ["隐私", "个性化推荐"])

    def test_privacy_entry_called_something_else_is_tried_next(self):
        p = phone()
        p.enter.side_effect = [RuntimeError("未找到入口「隐私」；当前页：…"), None]
        scope = loaded(p)
        scope["enter_privacy"]()
        self.assertEqual([c.args[0] for c in p.enter.call_args_list], ["隐私", "隐私授权管理"])

    def test_connection_error_during_privacy_entry_is_not_swallowed(self):
        """换名重试只认「没找到 / 页面没换」；断线这类错误要原样冒上去，不能当成叫法不同。"""
        p = phone()
        p.enter.side_effect = RuntimeError("与手机的连接断开了")
        scope = loaded(p)
        with self.assertRaisesRegex(RuntimeError, "与手机的连接断开了"):
            scope["enter_privacy"]()
        self.assertEqual([c.args[0] for c in p.enter.call_args_list], ["隐私"])

    def test_recorded_promotion_missing_is_a_report_not_a_failed_step(self):
        p = phone()
        p.switches.side_effect = [
            [("首页：活动弹窗", True, (1, 2)), ("软件专区：福利", True, (1, 3))],
            [("首页：活动弹窗", False, (1, 2)), ("软件专区：福利", False, (1, 3))],
        ]
        scope, out = load_recipe(p, VARIANT, only="商店推广位")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("本次未显示", out.getvalue())
        self.assertEqual(p.off.call_args.kwargs["only"], ["首页：活动弹窗", "软件专区：福利"])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 2)

    def test_unrecognised_page_is_failure_with_evidence(self):
        p = phone()
        p.switches.return_value = [("WLAN 自动更新应用", True, (1, 2))]
        scope, out = load_recipe(p, VARIANT, only="商店推广位")
        self.assertEqual(scope["FAILED_STEPS"], ["商店推广位"])
        self.assertIn("未识别全部目标开关", out.getvalue())
        self.assertIn(EVIDENCE, out.getvalue())
        p.off.assert_not_called()


class ReadbackTests(unittest.TestCase):
    def test_missing_target_aborts_without_clicking_anything(self):
        p = phone()
        p.switches.return_value = [("WLAN 自动更新应用", True, (1, 2))]
        scope = loaded(p)
        with self.assertRaisesRegex(RuntimeError, "未识别全部目标开关"):
            scope["close_named"](["个性化推荐"], "商店")
        p.off.assert_not_called()

    def test_reverted_switch_is_not_counted_as_verified(self):
        p = phone()
        p.switches.return_value = [("个性化推荐", True, (1, 2))]
        scope = loaded(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭"):
            scope["close_named"](["个性化推荐"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)

    def test_row_that_disappears_after_turning_off_counts_as_closed(self):
        """关掉一项这一行就从列表消失的页面：同页还有别的行、没换页时按已关记账。"""
        p = phone()
        p.switches.side_effect = [
            [("活动弹窗", True, (1, 2)), ("应用安全", True, (1, 3))],
            [("应用安全", True, (1, 3))],
        ]
        scope = loaded(p)
        scope["close_named"](["活动弹窗"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 1)

    def test_emptied_page_is_not_read_as_a_successful_close(self):
        p = phone()
        p.switches.side_effect = [[("活动弹窗", True, (1, 2))], []]
        scope = loaded(p)
        with self.assertRaisesRegex(RuntimeError, "回读未确认关闭「活动弹窗」"):
            scope["close_named"](["活动弹窗"], "商店")
        self.assertEqual(scope["VERIFIED_SWITCHES"], 0)


class BrowserTests(unittest.TestCase):
    def test_both_personalised_switches_are_named_on_this_versions_wording(self):
        p = phone(focus=BROWSER)
        p.switches.side_effect = [
            [("个性化优惠推荐", True, (1, 2)), ("个性化广告推荐", True, (1, 3))],
            [("个性化优惠推荐", False, (1, 2)), ("个性化广告推荐", False, (1, 3))],
        ]
        scope, _ = load_recipe(p, VARIANT, only="浏览器")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.off.assert_called_once_with(only=["个性化优惠推荐", "个性化广告推荐"],
                                      page="浏览器·个性化管理", max_screens=1)


if __name__ == "__main__":
    unittest.main()
