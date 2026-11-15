"""小米各机型的「应用商店」段转成数据（#1364）：入口形态与收尾次序逐条对齐旧脚本。

调用序列快照跑在空页面上，`entry` / `tab` 一律落空，所以只有靠 `code=` 之外的那几层才会真正
走到「隐私设置 / 通知设置」。这里把库调用换成桩、让门面入口都算成，把入口成功的那条路补齐：
各机型的入口形态各不相同（回到首页 / 直达偏好页 / 底栏标签 / 顶栏齿轮），
收尾的两种次序（隐私在前、通知在前）与「模式切换」两档也各有一台以上。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import load_recipe, phone_mock

LIBRARY_NAMES = ("store_privacy_nested", "store_privacy_sub", "store_mode_step",
                 "direct_page", "tap_any", "gear", "bottom_tab", "tap_bottom_tab", "tap_low")


def run(machine, answers=None, found=(), segment="应用商店"):
    """跑一台机的商店段：库调用记进 calls，`answers` 给它们的返回值，`found` 是读得到的文字。"""
    import catalog.interpreter as interpreter
    phone = phone_mock(W=1080, H=2400)
    phone.locked.return_value = False
    phone.focus.return_value = "com.xiaomi.market/.ui.Main"
    phone.switches.return_value = []
    phone.entry.return_value = True
    phone.tab.return_value = True
    phone.tap.return_value = True
    phone.settle.return_value = True
    phone.find.side_effect = lambda text, **_: text in found
    calls = []
    events = []
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
        scope, out = load_recipe(phone, ROOT / f"recipes/xiaomi/{machine}/{machine}.toml", [segment])
    return calls, events, phone, scope, out


def backs(phone):
    return [item.args for item in phone.back.call_args_list]


class StoreSegmentTests(unittest.TestCase):
    """各机型自己的入口形态与收尾次序：`events` 把库调用与 `off` 按真实顺序记在一起。"""

    def test_the_home_page_detour_then_the_top_bar_setting_icon(self):
        # 2505APX7BC / 24129PN74C：冷启动可能落福利页，先点「回到首页」；「我的」走 p.tab。
        for machine, wait in (("2505APX7BC", 1.5), ("24129PN74C", 2)):
            with self.subTest(machine=machine):
                calls, events, phone, scope, _out = run(machine, found=("回到首页",))
                self.assertEqual(events, ["store_privacy_nested", "store_privacy_sub",
                                          ("off", ["个性化服务", "个性化推荐"]),
                                          ("off", ["新手帮助"])])
                self.assertEqual(phone.off.call_args_list[0].kwargs,
                                 {"only": ["个性化服务", "个性化推荐"],
                                  "page": "商店·个性化服务"})
                # 两台只在「我的」页等多久上不同：2.5 + 2 + wait + 1
                self.assertEqual(scope["time"].slept, 5.5 + wait)
                self.assertEqual(phone.tap.call_args_list[0],
                                 call("回到首页", exact=True, scrolls=0))
                self.assertEqual(phone.tab.call_args_list, [call("我的")])
                self.assertEqual(phone.off.call_args_list,
                                 [call(only=["个性化服务", "个性化推荐"],
                                       page="商店·个性化服务"),
                                  call(only=["新手帮助"], keep=["推送消息", "应用更新"],
                                       page="商店·通知设置")])
                self.assertEqual(backs(phone), [(), (), (), (2,)])

    def test_a_toolbar_only_gear_first_and_a_wrapped_privacy_page(self):
        # 25060RK16C：齿轮三档（工具栏 → 通用 → 点文字），「隐私设置」多包一层「其他功能」，
        # 收尾次序是 通知 → 其他功能 → 隐私，另关「秒装」。
        calls, events, phone, _scope, _out = run("25060RK16C")
        self.assertEqual(events, ["gear", ("off", ["秒装"]), ("off", ["新手帮助"]),
                                  "store_privacy_nested", "store_privacy_sub",
                                  ("off", ["个性化服务"])])
        self.assertEqual(calls[0][2], {"toolbar_only": True})   # 三档里第一档就点中了
        self.assertEqual(phone.off.call_args_list[1].kwargs["keep"],
                         ["推送消息", "应用更新", "删除安装包", "秒装"])
        # 通知一层退一次、其他功能退一次、收尾退两次
        self.assertEqual(backs(phone), [(), (), (), (), (2,)])

    def test_the_bottom_tab_falls_back_to_the_menu_path(self):
        # 2512BPNDAC：底栏标签点得到就点，点不到走「我的 → 设置」；「隐私设置」在页底，点不中试「隐私」。
        calls, events, phone, _scope, _out = run("2512BPNDAC", answers={"bottom_tab": False})
        self.assertEqual(events, ["bottom_tab", "gear", "tap_low", "store_privacy_nested",
                                  "store_privacy_sub", ("off", ["个性化服务"]),
                                  ("off", ["新手帮助"])])
        self.assertEqual(phone.go.call_args_list, [call("我的", "设置")])
        calls, events, _phone, _scope, _out = run("2512BPNDAC",
                                                  answers={"bottom_tab": False, "tap_low": False})
        self.assertEqual([item[1] for item in calls[2:4]], [("隐私设置",), ("隐私",)])

    def test_a_bottom_tab_that_is_only_reachable_by_its_own_helper(self):
        # 24094RAD4C：底栏按内容描述模板找（`p.tab` 够不着），齿轮点不到即这一段失败。
        calls, events, phone, _scope, _out = run("24094RAD4C")
        self.assertEqual(events, ["tap_bottom_tab", "gear", "tap_any", "store_privacy_nested",
                                  "store_privacy_sub", ("off", ["个性化服务"]),
                                  ("off", ["新手帮助"])])
        self.assertEqual(calls[0][1], ("我的",))
        self.assertEqual(calls[2][1], ("隐私设置", "隐私"))
        self.assertEqual(backs(phone), [(), (), (), (2,)])

    def test_the_notice_page_comes_before_the_privacy_page(self):
        # 2410CRP4CC / 2304FPN6DC：这两台的收尾是 通知 → 隐私。
        for machine, scrolls in (("2410CRP4CC", 8), ("2304FPN6DC", 10)):
            with self.subTest(machine=machine):
                _calls, events, phone, _scope, _out = run(machine)
                self.assertEqual(events, [("off", ["新手帮助"]), "tap_any",
                                          "store_privacy_nested", "store_privacy_sub",
                                          ("off", ["个性化服务"])])
                self.assertEqual(phone.entry.call_args_list[0], call("设置", scrolls=scrolls))

    def test_the_preferences_activity_is_tried_before_the_menu_path(self):
        # M154FF / 23049RAD8C：直达偏好页，通了就不走「我的 → 设置」。
        for machine in ("M154FF", "23049RAD8C"):
            with self.subTest(machine=machine):
                _calls, events, phone, _scope, _out = run(machine)
                self.assertEqual(events, ["direct_page", "tap_any", "store_privacy_nested",
                                          "store_privacy_sub", ("off", ["个性化服务"]),
                                          "store_mode_step", ("off", ["新手帮助"])])
                self.assertEqual(phone.go.call_args_list, [])
                self.assertEqual(backs(phone), [(), (), (), (2,)])

    def test_a_slow_machine_settles_on_the_signature_after_the_store_tab(self):
        # M332BF：底栏点完按点之前读到的签名再等 2 秒（这台机换页慢），其余与上面两台同形。
        calls, events, phone, _scope, _out = run("M332BF", answers={"direct_page": False})
        self.assertEqual(calls[0], ("direct_page", ("com.xiaomi.market", ".ui.MarketPreferenceActivity"),
                                    {"expect": "通知设置"}))
        self.assertEqual(phone.tab.call_args_list, [call("我的")])
        self.assertEqual(phone.settle.call_args_list, [call(phone.sig.return_value, 2)])
        self.assertEqual(events, ["direct_page", "gear", "tap_any", "store_privacy_nested",
                                  "store_privacy_sub", ("off", ["个性化服务"]),
                                  ("off", ["新手帮助"])])
        self.assertEqual(backs(phone), [(), (), (), (2,)])

    def test_a_slow_machine_that_reaches_the_preferences_page_skips_the_tab_entirely(self):
        _calls, events, phone, _scope, _out = run("M332BF")
        self.assertEqual(events, ["direct_page", "tap_any", "store_privacy_nested",
                                  "store_privacy_sub", ("off", ["个性化服务"]),
                                  ("off", ["新手帮助"])])
        self.assertEqual(phone.tab.call_args_list, [])
        self.assertEqual(phone.sig.call_count, 0)

    def test_a_missing_preferences_activity_falls_back_to_the_menu_path(self):
        # 直达不通时走 我的 → 设置 → 齿轮；两台的回退一模一样，只有直达的实参不同。
        for machine, activity, kwargs in (
                ("M154FF", ".ui.MarketPreferenceActivity", {"expect": "通知设置"}),
                ("23049RAD8C", "com.xiaomi.market.ui.MarketPreferenceActivity", {})):
            with self.subTest(machine=machine):
                calls, events, phone, _scope, _out = run(machine,
                                                         answers={"direct_page": False})
                self.assertEqual(calls[0], ("direct_page", ("com.xiaomi.market", activity), kwargs))
                self.assertEqual(phone.start.call_args_list, [call("com.xiaomi.market")])
                self.assertEqual(phone.go.call_args_list, [call("我的", "设置")])
                self.assertEqual(events, ["direct_page", "gear", "tap_any",
                                          "store_privacy_nested", "store_privacy_sub",
                                          ("off", ["个性化服务"]), "store_mode_step",
                                          ("off", ["新手帮助"])])

    def test_a_store_with_the_switch_on_the_privacy_page_does_not_descend(self):
        # 老版本商店：「个性化服务」开关就在隐私页，关完只退一层（那一步的判据在 StoreTailTests）。
        _calls, events, phone, _scope, _out = run(
            "24094RAD4C", answers={"store_privacy_nested": False})
        self.assertEqual(events, ["tap_bottom_tab", "gear", "tap_any", "store_privacy_nested",
                                  ("off", ["个性化服务"]), ("off", ["新手帮助"])])
        self.assertEqual(backs(phone), [(), (), (2,)])

    def test_an_unreachable_sub_page_leaves_that_page_alone(self):
        # 判成子页但入口点不动：什么都不关，只退回设置页。
        _calls, events, phone, _scope, _out = run(
            "24094RAD4C", answers={"store_privacy_sub": False})
        self.assertEqual(events, ["tap_bottom_tab", "gear", "tap_any", "store_privacy_nested",
                                  "store_privacy_sub", ("off", ["新手帮助"])])
        self.assertEqual(backs(phone), [(), (), (2,)])

    def test_a_blocked_gear_ends_the_segment_as_unfinished(self):
        # 齿轮点不到是「这一段没做成」，不是继续往下空跑。
        _calls, _events, _phone, scope, out = run("24094RAD4C", answers={"gear": False})
        self.assertEqual(scope["FAILED_STEPS"], ["应用商店"])
        self.assertIn("未完成：商店设置入口没有找到", out.getvalue())


class Os4StoreTests(unittest.TestCase):
    """HyperOS 4 变体的商店段（#1364）：底栏标签交给 `p.tab`，不再自己等那一行画出来。

    这台机的底栏读作「我的，有新消息」，`p.tab` 按「逗号末段等于」认，省掉旧脚本里 24 次探测 +
    精确/包含两档重试。快照停在空页面的 `tab` 那一步，所以入口成功的那条路只能靠这里守。
    """

    def run_os4(self, **answers):
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1080, H=2400)
        phone.locked.return_value = False
        phone.tab.return_value = True
        phone.entry.return_value = True
        phone.off.return_value = 0
        values = {"gear_top": True, "store_privacy_nested": True, "store_privacy_sub": True}
        values.update(answers)

        with patch.dict(interpreter.LIBRARY,
                        {name: (lambda p, rt, *a, _v=value, **k: _v) for name, value in values.items()}):
            _scope, out = load_recipe(phone, ROOT / "recipes/xiaomi/24129PN74C/24129PN74C-os4.toml", ["应用商店"])
        return phone, out

    def test_the_bottom_tab_is_tapped_by_p_tab_and_both_pages_closed(self):
        phone, _out = self.run_os4()
        phone.tab.assert_called_once_with("我的")
        phone.find.assert_not_called()          # 不再自己探测「我的，有新消息」
        self.assertEqual([item.kwargs["page"] for item in phone.off.call_args_list],
                         ["商店·个性化服务", "商店·通知设置"])
        self.assertEqual(phone.off.call_args_list[1].kwargs["keep"],
                         ["应用更新通知", "点赞消息", "评论消息"])
        # 子页退一次、隐私页退一次、通知设置退一次，收尾退两次
        self.assertEqual(backs(phone), [(), (), (), (2,)])

    def test_a_store_with_the_switch_on_the_privacy_page_does_not_descend(self):
        phone, _out = self.run_os4(store_privacy_nested=False)
        self.assertEqual([item.kwargs["page"] for item in phone.off.call_args_list],
                         ["商店·个性化服务", "商店·通知设置"])
        self.assertEqual(backs(phone), [(), (), (2,)])

    def test_a_missing_bottom_tab_ends_the_segment_before_the_gear(self):
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1080, H=2400)
        phone.locked.return_value = False
        phone.tab.return_value = False
        with patch.dict(interpreter.LIBRARY, {"gear_top": lambda p, rt: True}):
            scope, out = load_recipe(phone, ROOT / "recipes/xiaomi/24129PN74C/24129PN74C-os4.toml", ["应用商店"])
        self.assertEqual(scope["FAILED_STEPS"], ["应用商店"])
        self.assertIn("商店底部「我的」标签没找到", out.getvalue())
        phone.off.assert_not_called()

    def test_a_blocked_gear_ends_the_segment_as_unfinished(self):
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1080, H=2400)
        phone.locked.return_value = False
        phone.tab.return_value = True
        with patch.dict(interpreter.LIBRARY, {"gear_top": lambda p, rt: False}):
            scope, out = load_recipe(phone, ROOT / "recipes/xiaomi/24129PN74C/24129PN74C-os4.toml", ["应用商店"])
        self.assertEqual(scope["FAILED_STEPS"], ["应用商店"])
        self.assertIn("商店「我的」页右上角齿轮未找到", out.getvalue())


class StoreTailTests(unittest.TestCase):
    """收尾两块共用的走法：「个性化服务」在不在子页，以及「模式切换」的门槛。"""

    def test_the_switch_is_one_page_down_on_newer_stores(self):
        import recipe_lib.xiaomi as xiaomi
        phone = phone_mock()
        phone.switches.return_value = [("通知设置", True, (0, 0, 10, 10))]   # 本页没有「个性化服务」
        self.assertTrue(xiaomi.store_privacy_nested(phone, Mock()))
        phone.entry.return_value = True
        self.assertTrue(xiaomi.store_privacy_sub(phone, Mock()))
        self.assertEqual(phone.entry.call_args_list, [call("个性化服务", scrolls=6)])

    def test_an_older_store_keeps_the_switch_on_the_privacy_page(self):
        import recipe_lib.xiaomi as xiaomi
        phone = phone_mock()
        phone.switches.return_value = [("个性化服务", True, (0, 0, 10, 10))]
        self.assertFalse(xiaomi.store_privacy_nested(phone, Mock()))
        self.assertEqual(phone.entry.call_args_list, [])   # 不必再进子页

    def test_an_unreachable_sub_page_is_reported_as_not_entered(self):
        import recipe_lib.xiaomi as xiaomi
        phone = phone_mock()
        phone.entry.return_value = False
        self.assertFalse(xiaomi.store_privacy_sub(phone, Mock()))

    def test_the_mode_switch_is_switched_or_left_alone(self):
        import recipe_lib.xiaomi as xiaomi
        phone = phone_mock()
        phone.entry.return_value = True
        phone.tap.return_value = True
        xiaomi.store_mode_step(phone, Mock())
        self.assertEqual(phone.tap.call_args_list,
                         [call("极简模式", exact=True, scrolls=0)])
        self.assertEqual(phone.confirm.call_count, 1)
        self.assertEqual(backs(phone), [()])

        phone = phone_mock()
        phone.entry.return_value = False       # 新版商店没有这一项
        xiaomi.store_mode_step(phone, Mock())
        self.assertEqual(phone.tap.call_args_list, [])
        self.assertEqual(backs(phone), [])


if __name__ == "__main__":
    unittest.main()
