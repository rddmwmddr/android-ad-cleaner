"""小米主题两段转成数据（#1367）：24090RA29C 的「我的」在 65% 屏高以下，M332BF 点完要再等 2 秒。

两段原先整段是 `code=`。快照跑在空页面上，24090RA29C 到「我的」就断了、M332BF 的换页等待
只是一条 `settle`；所以入口成功那条路、齿轮点不到的出口、以及「我的」在下半屏的判据都在这里补。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from fixtures import load_recipe, phone_mock, shell_result

LIBRARY_NAMES = ("mine_tab_low", "gear")


def run(machine, answers=None, segment="主题"):
    """跑一台机的主题段：库调用记进 calls，`answers` 给它们的返回值。"""
    import catalog.interpreter as interpreter
    phone = phone_mock(W=1080, H=2400)
    phone.locked.return_value = False
    phone.shell.return_value = shell_result("package:/system/app/ThemeManager/ThemeManager.apk")
    phone.page_evidence.return_value = "停在 主题首页"
    phone.switches.return_value = [("每次联网时通知", True, (0, 0, 10, 10))]
    phone.entry.return_value = True
    phone.tab.return_value = True
    phone.settle.return_value = True
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
        scope, out = load_recipe(phone, ROOT / f"recipes/xiaomi/{machine}/{machine}.toml", [segment])
    return calls, events, phone, scope, out


class ThemeSegmentTests(unittest.TestCase):
    def test_the_low_tab_leads_to_the_gear_and_the_privacy_page(self):
        # 24090RA29C：「我的」在下半屏（家族库 mine_tab_low），进设置页、点名关、再进隐私页。
        calls, events, phone, scope, _out = run("24090RA29C")
        self.assertEqual(events, ["mine_tab_low", "gear", ("off", ["每次联网时通知"]),
                                  ("off", ["个性化推荐"])])
        self.assertEqual([item[0] for item in calls], ["mine_tab_low", "gear"])
        self.assertEqual(scope["time"].slept, 3)          # 首页要几秒才画完
        self.assertEqual([item.args for item in phone.dismiss.call_args_list], [(), ()])
        self.assertEqual([item.args for item in phone.back.call_args_list], [(), (2,)])

    def test_a_missing_low_tab_ends_the_segment_as_unfinished(self):
        _calls, events, _phone, scope, out = run("24090RA29C", answers={"mine_tab_low": False})
        self.assertEqual(events, ["mine_tab_low"])
        self.assertEqual(scope["FAILED_STEPS"], ["主题"])
        self.assertIn("主题「我的」标签没找到", out.getvalue())

    def test_a_blocked_gear_ends_the_segment_as_unfinished(self):
        _calls, events, phone, scope, out = run("24090RA29C", answers={"gear": False})
        self.assertEqual(events, ["mine_tab_low", "gear"])
        self.assertEqual(scope["FAILED_STEPS"], ["主题"])
        self.assertIn("主题设置入口没找到", out.getvalue())
        phone.off.assert_not_called()        # 没进设置页就不许动开关

    def test_a_slow_machine_settles_on_the_page_signature_after_the_tab(self):
        # M332BF：底栏走门面 p.tab，点完按点之前读到的签名再等 2 秒。
        _calls, events, phone, scope, _out = run("M332BF")
        self.assertEqual(events, ["gear", ("off", ["每次联网时通知"]), ("off", ["个性化推荐"])])
        self.assertEqual(phone.tab.call_args_list, [call("我的")])
        self.assertEqual(phone.sig.call_count, 1)
        self.assertEqual(phone.settle.call_args_list, [call(phone.sig.return_value, 2)])
        self.assertEqual(scope["FAILED_STEPS"], [])


class LowTabTests(unittest.TestCase):
    """`mine_tab_low`：只认 65% 屏高以下那一带的「我的」，点中心、等换页。"""

    def test_a_mine_tab_in_the_lower_half_is_tapped_at_its_center(self):
        import recipe_lib.xiaomi as xiaomi
        phone = phone_mock(W=1080, H=2400)
        phone.texts.return_value = [("我的奇妙小镇", (0, 100, 1080, 200), None),
                                    ("我的", (400, 1800, 680, 1900), None)]
        self.assertTrue(xiaomi.mine_tab_low(phone, Mock()))
        self.assertEqual(phone.click.call_args_list, [call(540, 1850)])
        self.assertEqual(phone.settle.call_args_list, [call(phone.sig.return_value, 1.5)])

    def test_a_mine_written_above_the_band_is_not_a_tab(self):
        import recipe_lib.xiaomi as xiaomi
        phone = phone_mock(W=1080, H=2400)
        phone.texts.return_value = [("我的", (400, 900, 680, 1000), None)]
        self.assertFalse(xiaomi.mine_tab_low(phone, Mock()))
        self.assertEqual(phone.click.call_args_list, [])


if __name__ == "__main__":
    unittest.main()
