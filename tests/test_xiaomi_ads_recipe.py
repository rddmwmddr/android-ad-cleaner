"""小米系统广告转成数据（#1367）：一台要先切「安全」标签，一台先试直达再退回菜单，
两台按菜单路径进「隐私与安全」页，一台直接用设置搜索。

快照跑在空页面上，几段都在「隐私与安全」那一步就断了；入口成功那条路、标签的重试轮、
「直达不通 → 菜单」与「两条都不通」两个出口，以及设置搜索搜不到那条失败都在这里补。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from fixtures import load_recipe, phone_mock

LIBRARY_NAMES = ("direct_page", "system_ads_menu")


def run(machine, answers=None):
    """跑一台机的系统广告段：库调用记进 calls，`answers` 给它们的返回值。"""
    import catalog.interpreter as interpreter
    phone = phone_mock(W=1080, H=2400)
    phone.locked.return_value = False
    calls, events = [], []
    values = {name: True for name in LIBRARY_NAMES}
    values.update(answers or {})

    def recorder(name):
        def record(p, rt, *args, **kwargs):
            calls.append((name, args, kwargs))
            events.append(name)
            return values[name]
        return record

    def off(*, only, **kwargs):
        events.append(("off", list(only)))

    phone.off.side_effect = off
    with patch.dict(interpreter.LIBRARY, {name: recorder(name) for name in LIBRARY_NAMES}):
        scope, out = load_recipe(phone, ROOT / f"recipes/xiaomi/{machine}/{machine}.toml", ["系统广告"])
    return calls, events, phone, scope, out


class AdsSegmentTests(unittest.TestCase):
    def test_the_old_layout_machine_switches_the_security_tab_before_looking(self):
        # 2304FPN6DC：隐私页首屏没有「更多安全设置」，整段交给库里的切标签走法。
        calls, events, _phone, scope, _out = run("2304FPN6DC")
        self.assertEqual(calls[0], ("system_ads_menu", (), {"security_tab_first": True}))
        self.assertEqual(events, ["system_ads_menu", ("off", ["个性化广告推荐"])])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_menu_that_stops_short_leaves_the_switch_alone(self):
        # 软失败：进不去广告服务页不算这一段失败，也不许动开关。
        _calls, events, phone, scope, _out = run("2304FPN6DC", answers={"system_ads_menu": False})
        self.assertEqual(events, ["system_ads_menu"])
        phone.off.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_the_direct_page_wins_and_the_menu_is_never_walked(self):
        # M154FF：广告服务页是独立 Activity，直达到了就直接点开关并结束这一段。
        calls, events, _phone, scope, _out = run("M154FF")
        self.assertEqual(calls[0], ("direct_page", ("com.android.settings", ".ad.AdServiceSettings"),
                                    {"expect": "个性化广告推荐"}))
        self.assertEqual(events, ["direct_page", ("off", ["个性化广告推荐"])])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_missing_direct_page_falls_back_to_the_settings_menu(self):
        _calls, events, _phone, scope, _out = run("M154FF", answers={"direct_page": False})
        self.assertEqual(events, ["direct_page", "system_ads_menu", ("off", ["个性化广告推荐"])])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_both_ways_failing_leaves_the_switch_alone(self):
        _calls, events, phone, scope, _out = run("M154FF", answers={"direct_page": False,
                                                                   "system_ads_menu": False})
        self.assertEqual(events, ["direct_page", "system_ads_menu"])
        phone.off.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])


class SettingsPathTests(unittest.TestCase):
    """23049RAD8C 与 25102RKBEC：一段先直达广告服务页，一段按菜单路径切「安全」分栏。"""

    def walk(self, machine, *, direct=True, entries=(), finds=(), setting=True):
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1080, H=2400)
        phone.locked.return_value = False
        phone.entry.side_effect = list(entries)
        phone.find.side_effect = lambda text, **kwargs: text in finds
        phone.setting.return_value = setting
        events = []

        def off(*, only, **kwargs):
            events.append(("off", list(only)))

        def direct_page(p, rt, pkg, activity, **kwargs):
            events.append(("direct_page", pkg, activity))
            return direct

        def tab(p, rt, name):
            events.append(("tab", name))
            return True

        phone.off.side_effect = off
        with patch.dict(interpreter.LIBRARY, {"tab": tab, "direct_page": direct_page}):
            scope, out = load_recipe(phone, ROOT / f"recipes/xiaomi/{machine}/{machine}.toml", ["系统广告"])
        return phone, events, scope, out

    def test_the_direct_page_closes_both_switches(self):
        # 23049RAD8C：「广告服务」直达页与「系统广告」搜索各自管一个总闸。
        _phone, events, scope, _out = self.walk("23049RAD8C")
        self.assertEqual(events, [("direct_page", "com.android.settings", "com.android.settings.ad.AdServiceSettings"),
                                  ("off", ["个性化广告推荐"]),
                                  ("off", ["系统工具广告"])])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_missing_direct_page_still_runs_the_settings_search(self):
        _phone, events, scope, _out = self.walk("23049RAD8C", direct=False)
        self.assertEqual(events, [("direct_page", "com.android.settings", "com.android.settings.ad.AdServiceSettings"),
                                  ("off", ["系统工具广告"])])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_settings_search_that_misses_fails_the_segment(self):
        _phone, events, scope, out = self.walk("23049RAD8C", setting=False)
        self.assertEqual(events, [("direct_page", "com.android.settings", "com.android.settings.ad.AdServiceSettings"),
                                  ("off", ["个性化广告推荐"])])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])
        self.assertIn("没搜到「系统广告」", out.getvalue())

    def test_the_second_column_is_only_entered_when_the_page_lacks_the_entry(self):
        # 25102RKBEC：隐私与安全页默认停在「隐私」分栏，页上没有「更多安全设置」才去切「安全」。
        _phone, events, scope, _out = self.walk("25102RKBEC", entries=[True, True, True],
                                                finds={"隐私与安全"})
        self.assertEqual(events, [("tab", "安全"), ("off", ["个性化广告推荐"])])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_page_that_already_shows_the_entry_keeps_its_column(self):
        _phone, events, scope, _out = self.walk("25102RKBEC", entries=[True, True, True],
                                                finds={"隐私与安全", "更多安全设置"})
        self.assertEqual(events, [("off", ["个性化广告推荐"])])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_missing_first_entry_ends_the_segment_without_touching_switches(self):
        phone, events, scope, out = self.walk("25102RKBEC", entries=[False])
        self.assertEqual(events, [])
        phone.off.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("隐私与安全", out.getvalue())

    def test_the_long_column_is_scrolled_further_than_the_first_screen(self):
        phone, _events, _scope, _out = self.walk("25102RKBEC", entries=[True, True, True])
        self.assertEqual([item.args for item in phone.entry.call_args_list],
                         [("隐私与安全",), ("更多安全设置",), ("广告服务",)])
        self.assertEqual([item.kwargs["scrolls"] for item in phone.entry.call_args_list], [8, 10, 4])


class SearchFirstTests(unittest.TestCase):
    """25060RK16C：设置搜索直达优先，搜不到才退回菜单路径（三级可选探测）。"""

    def walk(self, *, setting=True, entries=()):
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1080, H=2400)
        phone.locked.return_value = False
        phone.setting.return_value = setting
        phone.entry.side_effect = list(entries)
        events = []

        def off(*, only, **kwargs):
            events.append(("off", list(only)))

        phone.off.side_effect = off
        with patch.dict(interpreter.LIBRARY, {"tab": lambda p, rt, name: True}):
            scope, out = load_recipe(phone, ROOT / "recipes/xiaomi/25060RK16C/25060RK16C.toml", ["系统广告"])
        return phone, events, scope, out

    def test_the_settings_search_skips_the_whole_menu_path(self):
        phone, events, scope, _out = self.walk()
        self.assertEqual(events, [("off", ["个性化广告推荐", "广告跟踪"])])
        phone.entry.assert_not_called()
        phone.shell.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_search_that_misses_walks_the_menu_path_column_by_column(self):
        phone, events, scope, _out = self.walk(setting=False, entries=[True, False, True, True, True])
        self.assertEqual(events, [("off", ["个性化广告推荐", "广告跟踪"])])
        self.assertEqual([item.args[0] for item in phone.entry.call_args_list],
                         ["隐私与安全", "更多安全设置", "安全", "更多安全设置", "广告服务"])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_both_ways_missing_fails_the_segment(self):
        _phone, events, scope, out = self.walk(setting=False, entries=[False, False])
        self.assertEqual(events, [])
        self.assertEqual(scope["FAILED_STEPS"], ["系统广告"])
        self.assertIn("没找到「广告服务」入口", out.getvalue())


class SystemAdsMenuTests(unittest.TestCase):
    """`system_ads_menu`：两种入口形态下的点击顺序与返回值。"""

    def walk(self, entries, security_tab_first=False, painted=()):
        import recipe_lib.xiaomi as xiaomi
        phone = phone_mock(W=1080, H=2400)
        rt = Mock()
        phone.entry.side_effect = list(entries)
        phone.find.side_effect = lambda text, **kwargs: text in painted
        reached = xiaomi.system_ads_menu(phone, rt, security_tab_first=security_tab_first)
        return reached, phone, rt

    def test_a_painted_security_page_needs_no_tab_tap(self):
        reached, phone, rt = self.walk([True, True, True], security_tab_first=True,
                                       painted={"人身安全"})
        self.assertTrue(reached)
        self.assertEqual(phone.shell.call_args_list,
                         [call("am start -f 0x10008000 -a android.settings.SETTINGS")])
        phone.tap.assert_not_called()                 # 页面已经在「安全」这一页，不再切
        self.assertEqual(rt.clock.sleep.call_args_list, [call(1.2)])
        self.assertEqual([item.args[0] for item in phone.entry.call_args_list],
                         ["隐私与安全", "更多安全设置", "广告服务"])

    def test_an_unpainted_page_is_retried_three_times_then_given_up(self):
        reached, phone, rt = self.walk([True, False], security_tab_first=True)
        self.assertFalse(reached)                     # 没翻到「更多安全设置」就不问「广告服务」
        self.assertEqual(phone.tap.call_args_list,
                         [call("安全", exact=True, scrolls=0)] * 3)
        self.assertEqual(rt.clock.sleep.call_args_list, [call(1.2), call(0.5), call(0.5), call(0.5)])
        self.assertEqual([item.args[0] for item in phone.entry.call_args_list],
                         ["隐私与安全", "更多安全设置"])

    def test_the_menu_first_machine_finds_the_page_without_the_tab(self):
        reached, phone, rt = self.walk([True, True, True])
        self.assertTrue(reached)
        phone.tap.assert_not_called()
        self.assertEqual(rt.clock.sleep.call_args_list, [call(1.2)])

    def test_the_menu_first_machine_switches_the_tab_only_after_a_miss(self):
        # 18 Fold 那一档：隐私与安全 → 安全 → 更多安全设置。
        reached, phone, _rt = self.walk([True, False, True, True, True])
        self.assertTrue(reached)
        self.assertEqual(phone.entry.call_args_list, [
            call("隐私与安全", scrolls=6),
            call("更多安全设置", scrolls=6),
            call("安全", scrolls=3),
            call("更多安全设置", scrolls=6),
            call("广告服务", scrolls=6),
        ])

    def test_a_settings_page_that_never_opens_costs_one_try(self):
        reached, phone, _rt = self.walk([False])
        self.assertFalse(reached)
        phone.entry.assert_called_once_with("隐私与安全", scrolls=6)


if __name__ == "__main__":
    unittest.main()
