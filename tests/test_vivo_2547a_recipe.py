"""V2547A 的商店 / 浏览器 / 阅图锁屏 / 天气四段转成数据（#1337）：段内走法逐条对齐旧脚本。

库调用换成桩：这里只验数据段的顺序与实参，不重测库实现（它们各自的用例在别处）。
调用序列快照只记到库内部的前缀，走不到这四个段的后半，所以另有这一层。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/vivo/V2547A/V2547A.toml"
LIBRARY_NAMES = ("tap_text", "goto", "off", "browser_settings", "search_setting", "confirm2")


def run_segment(segment, answers=None, focus=""):
    """跑一段：六个库调用记进 calls，`answers` 给它们的返回值（缺省一律算成）。"""
    import catalog.interpreter as interpreter
    phone = phone_mock(W=1080, H=2400)
    phone.locked.return_value = False
    phone.focus.return_value = focus
    calls = []
    answers = {"tap_text": True, "goto": True, "browser_settings": True,
               "search_setting": True, **(answers or {})}

    def recorder(name):
        def call(p, rt, *args, **kwargs):
            calls.append((name, args, kwargs))
            return answers.get(name)
        return call

    with patch.dict(interpreter.LIBRARY, {name: recorder(name) for name in LIBRARY_NAMES}):
        _scope, out = load_recipe(phone, RECIPE, [segment])
    return phone, calls, out


class StoreSegmentTests(unittest.TestCase):
    """应用商店：我的 → 设置 → 关于里的两个子页，两个入口失败都打印并停这一段。"""

    def test_the_two_settings_pages_are_closed_after_their_own_confirmation(self):
        phone, calls, _out = run_segment("应用商店")
        self.assertEqual([call[0] for call in calls],
                         ["tap_text", "tap_text", "goto", "goto", "off", "goto", "off"])
        self.assertEqual(calls[0][1], ("我的",))
        self.assertEqual(calls[1][1], ("设置",))
        self.assertEqual(calls[2][1], ("关于",))
        self.assertEqual(calls[3][1], ("个性化推荐",))
        self.assertEqual(calls[4][2], {"only": ["个性化推荐"], "page": "商店·个性化推荐"})
        self.assertEqual(calls[5][1], ("服务管理",))
        self.assertEqual(calls[5][2], {"scrolls": 2})
        self.assertEqual(calls[6][2]["page"], "商店·服务管理")
        self.assertEqual(calls[6][2]["keep"], ["我的服务", "空间清理"])
        # 两个子页各退一次、离开「关于」退一次、收尾退三次
        self.assertEqual([call.args for call in phone.back.call_args_list],
                         [(1,), (1,), (1,), (3,)])

    def test_a_missing_my_tab_prints_and_stops_before_any_switch(self):
        phone, calls, out = run_segment("应用商店", {"tap_text": False})
        self.assertEqual([call[0] for call in calls], ["tap_text"])
        self.assertIn("没找到「我的」", out.getvalue())
        phone.back.assert_not_called()


class BrowserSegmentTests(unittest.TestCase):
    """浏览器：首页切成极简，再逐个进三个设置页关点名的行。"""

    def test_the_minimal_home_is_picked_from_the_card_and_three_pages_are_visited(self):
        phone, calls, _out = run_segment("浏览器")
        self.assertEqual([(call[0], call[1][:1]) for call in calls],
                         [("browser_settings", ()), ("goto", ("首页设置",)),
                          ("confirm2", ()), ("goto", ("网页浏览设置",)), ("off", ()),
                          ("goto", ("更多设置",)), ("off", ()),
                          ("goto", ("隐私权限设置",)), ("off", ())])
        self.assertEqual([call[2].get("scrolls") for call in calls[3:]],
                         [10, None, 10, None, 10, None])
        self.assertEqual(phone.tap.call_args_list[0].args, ("极简首页",))
        self.assertEqual(phone.tap.call_args_list[0].kwargs, {"exact": True, "scrolls": 0})
        # 「首页设置」里退一次后回顶，三个入口各回顶一次
        self.assertEqual(len(phone.top.call_args_list), 4)
        self.assertEqual(phone.back.call_args_list[-1].args, (3,))

    def test_a_browser_without_its_settings_page_stops_at_once(self):
        _phone, calls, out = run_segment("浏览器", {"browser_settings": False})
        self.assertEqual([call[0] for call in calls], ["browser_settings"])
        self.assertIn("没进到浏览器设置", out.getvalue())


class LockScreenSegmentTests(unittest.TestCase):
    """阅图锁屏：设置搜索直达；停在结果页时再点一次结果，然后点名关。"""

    def test_landing_on_the_settings_page_needs_no_second_tap(self):
        phone, calls, _out = run_segment("阅图锁屏", focus="com.vivo.settings/.MagazineSettings")
        self.assertEqual([call[0] for call in calls], ["search_setting", "off"])
        self.assertEqual(calls[0][1], ("阅图锁屏",))
        self.assertEqual(calls[1][2]["page"], "系统·阅图锁屏")
        self.assertEqual(calls[1][2]["keep"], ["锁屏底部壁纸", "移动网络自动更新"])
        phone.tap.assert_not_called()
        self.assertEqual([call.args for call in phone.back.call_args_list], [(2,)])

    def test_a_search_result_page_gets_tapped_once_more(self):
        phone, _calls, _out = run_segment("阅图锁屏", focus="com.android.settings/.SearchResult")
        self.assertEqual(phone.tap.call_args_list[0].args, ("阅图锁屏",))
        self.assertEqual(phone.tap.call_args_list[0].kwargs, {"exact": True, "scrolls": 4})


class WeatherSegmentTests(unittest.TestCase):
    """天气：右上角菜单按资源 id 点（页面上另有一个同名的「更多」展开按钮）。"""

    def test_the_menu_is_tapped_by_resource_id_then_settings_is_closed(self):
        phone, calls, _out = run_segment("天气")
        selectors = [call.kwargs for call in phone.d.call_args_list]
        self.assertEqual(selectors, [{"resourceId": "com.vivo.weather:id/more_btn"}])
        self.assertEqual([call[0] for call in calls], ["tap_text", "off"])
        self.assertEqual(calls[1][2], {"only": ["天气服务"], "keep": ["气象预警", "异常天气", "地震预警"],
                                       "page": "天气·设置"})

    def test_a_missing_menu_button_prints_and_stops_the_segment(self):
        from fast import u2
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1080, H=2400)
        phone.locked.return_value = False
        # 选择器本身不会失败：读屏库是在点的时候才去找控件
        phone.d.return_value.click.side_effect = u2.exceptions.UiObjectNotFoundError({"code": -32002})
        asked = []
        with patch.dict(interpreter.LIBRARY, {"tap_text": lambda p, rt, *a, **k: asked.append(a)}):
            _scope, out = load_recipe(phone, RECIPE, ["天气"])
        self.assertEqual(asked, [], "菜单按钮点不到之后不该再去找设置")
        self.assertIn("没找到天气右上角的更多按钮", out.getvalue())


if __name__ == "__main__":
    unittest.main()
