"""V2547A（X300 Ultra）的段内走法（#1366）：六个过程段转成数据；应用商店段沿用 #1365 的用例。

应用商店没有直达（「我的」页的齿轮点左侧文字不转发点击），入口是 `start` 起商店 → `tap_text`
点「我的」→ 点「设置」，之后 `goto` 逐页进「关于」里的两页。其余六段逐条对齐旧脚本：
库调用顺序与实参照抄，`code=` 只剩 i管家一段。

空页面快照上 `tap_text` / `goto` 一律落空，入口成功的那条路走不到，所以两批都在这里补。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/vivo/V2547A/V2547A.toml"
LIBRARY_NAMES = ("tap_text", "goto", "off")
SERVICE_SWITCHES = ["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"]


def run(answers=None):
    """跑应用商店段：`tap_text` / `goto` / `off` 换成桩，`answers` 给它们返回值（或按实参现算）。"""
    import catalog.interpreter as interpreter
    phone = phone_mock(W=1260, H=2800)
    phone.locked.return_value = False
    phone.focus.return_value = "com.bbk.appstore/.ui.menu.AppstoreSettingsActivity"
    phone.back.return_value = None
    calls = []
    values = {name: True for name in LIBRARY_NAMES}
    values.update(answers or {})

    def recorder(name):
        def record(p, rt, *args, **kwargs):
            calls.append((name, args, kwargs))
            answer = values[name]
            return answer(*args, **kwargs) if callable(answer) else answer
        return record

    with patch.dict(interpreter.LIBRARY, {name: recorder(name) for name in LIBRARY_NAMES}):
        scope, out = load_recipe(phone, RECIPE, ["应用商店"])
    return calls, phone, scope, out


class StoreSegmentTests(unittest.TestCase):
    def test_the_settings_page_is_reached_through_my_tab_and_both_subpages_are_closed(self):
        calls, phone, scope, _out = run()
        self.assertEqual(calls, [
            ("tap_text", ("我的",), {}),
            ("tap_text", ("设置",), {}),
            ("goto", ("关于",), {}),
            ("goto", ("个性化推荐",), {}),
            ("off", (), {"only": ["个性化推荐"], "page": "商店·个性化推荐"}),
            ("goto", ("服务管理",), {"scrolls": 2}),
            ("off", (), {"only": SERVICE_SWITCHES, "keep": ["我的服务", "空间清理"],
                         "page": "商店·服务管理"}),
        ])
        # 两个子页各回一次、「关于」回一次、收段再回三次
        self.assertEqual(phone.back.call_args_list, [call(1), call(1), call(1), call(3)])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_missing_my_tab_ends_the_segment_but_is_not_a_failure(self):
        calls, phone, scope, out = run(answers={"tap_text": lambda text, **_: text != "我的"})
        self.assertEqual(calls, [("tap_text", ("我的",), {})])
        phone.back.assert_not_called()          # 早退连收段的两次返回也一起跳过
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("没找到「我的」", out.getvalue())

    def test_a_missing_settings_entry_ends_the_segment_after_the_my_tab(self):
        calls, _phone, _scope, out = run(answers={"tap_text": lambda text, **_: text != "设置"})
        self.assertEqual([name for name, _args, _kwargs in calls], ["tap_text", "tap_text"])
        self.assertIn("「我的」页没找到设置", out.getvalue())


SEGMENT_LIBRARIES = ("tap_text", "goto", "off", "browser_settings", "search_setting",
                     "confirm2", "hiboard_panel_v2547a")


def run_segment(segment, answers=None, focus=""):
    """跑一段：七个库助手换成桩，`answers` 给它们的返回值（缺省一律算成）。"""
    import catalog.interpreter as interpreter
    phone = phone_mock(W=1260, H=2800)
    phone.locked.return_value = False
    phone.focus.return_value = focus
    phone.back.return_value = None
    calls = []
    values = {name: True for name in SEGMENT_LIBRARIES}
    values.update(answers or {})

    def recorder(name):
        def record(p, rt, *args, **kwargs):
            calls.append((name, args, kwargs))
            answer = values[name]
            return answer(*args, **kwargs) if callable(answer) else answer
        return record

    with patch.dict(interpreter.LIBRARY, {name: recorder(name) for name in SEGMENT_LIBRARIES}):
        scope, out = load_recipe(phone, RECIPE, [segment])
    return phone, calls, scope, out


class AdPrivacySegmentTests(unittest.TestCase):
    """广告与隐私（#1366）：设置搜索直达后点名关三项；搜不到只打印并停这一段。"""

    def test_the_three_named_switches_are_closed_after_the_search(self):
        phone, calls, scope, _out = run_segment("广告与隐私")
        self.assertEqual([call_[0] for call_ in calls], ["search_setting", "off"])
        self.assertEqual(calls[0][1], ("广告与隐私",))
        self.assertEqual(calls[1][2], {"only": ["个性化广告", "个性化推荐", "智能推荐服务"],
                                       "page": "系统·广告与隐私"})
        self.assertEqual(phone.back.call_args_list, [call(1)])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_missing_setting_page_prints_and_leaves_before_any_switch(self):
        phone, calls, _scope, out = run_segment("广告与隐私", {"search_setting": False})
        self.assertEqual([call_[0] for call_ in calls], ["search_setting"])
        self.assertIn("没进到广告与隐私", out.getvalue())
        phone.back.assert_not_called()          # 早退连收段的返回也一起跳过


class NegativeScreenSegmentTests(unittest.TestCase):
    """负一屏（#1366）：两个子页各自先回一次设置面板，回不去就不再试后面的名字。"""

    def test_both_sub_pages_are_closed_after_the_panel_comes_back(self):
        phone, calls, _scope, _out = run_segment("负一屏")
        self.assertEqual([call_[0] for call_ in calls],
                         ["hiboard_panel_v2547a", "goto", "goto", "off",
                          "hiboard_panel_v2547a", "goto", "off",
                          "hiboard_panel_v2547a", "goto", "off"])
        self.assertEqual(calls[1][1], ("更多设置",))
        self.assertEqual(calls[2][1], ("个性化推荐",))
        self.assertEqual(calls[3][2], {"only": ["服务推荐", "资讯推荐"], "page": "负一屏·个性化推荐"})
        self.assertEqual((calls[5][1], calls[5][2]), (("内容精选",), {"scrolls": 6}))
        self.assertEqual(calls[6][2], {"only": ["内容精选"], "page": "负一屏·内容精选"})
        self.assertEqual((calls[8][1], calls[8][2]), (("热点资讯",), {"scrolls": 6}))
        self.assertEqual(calls[9][2], {"only": ["热点资讯"], "page": "负一屏·热点资讯"})
        self.assertEqual(len(phone.top.call_args_list), 2)
        self.assertEqual(phone.back.call_args_list, [call(3)])

    def test_a_panel_that_never_shows_up_stops_the_whole_segment(self):
        phone, calls, _scope, out = run_segment("负一屏", {"hiboard_panel_v2547a": False})
        self.assertEqual([call_[0] for call_ in calls], ["hiboard_panel_v2547a"])
        self.assertIn("没滑到负一屏", out.getvalue())
        phone.back.assert_not_called()

    def test_a_lost_panel_after_the_first_sub_page_skips_the_second_one(self):
        """回不到面板时旧写法是 break：后面的名字不再试，收尾那三次 back 照常走。"""
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1260, H=2800)
        phone.locked.return_value = False
        seen = []

        def panel(p, rt):
            seen.append(1)
            return len(seen) == 1        # 第一次在面板上，之后回不去

        with patch.dict(interpreter.LIBRARY, {"hiboard_panel_v2547a": panel,
                                              "goto": lambda p, rt, *a, **k: True,
                                              "off": lambda p, rt, *a, **k: 0}):
            _scope, out = load_recipe(phone, RECIPE, ["负一屏"])
        self.assertEqual(len(seen), 2)
        self.assertIn("回不到负一屏设置面板", out.getvalue())
        self.assertNotIn("热点资讯", out.getvalue())
        self.assertEqual(phone.back.call_args_list, [call(3)])


class GlobalSearchSegmentTests(unittest.TestCase):
    """全局搜索（#1366）：直达设置页后按三个入口钻，入口缺失不挡后面的。"""

    def test_the_three_pages_are_visited_after_the_activity_comes_up(self):
        phone, calls, scope, _out = run_segment(
            "全局搜索", focus="com.vivo.globalsearch/.view.SearchSettingsActivity")
        self.assertEqual([(call_[0], call_[1]) for call_ in calls],
                         [("goto", ("首页展示内容",)), ("off", ()), ("goto", ("推荐热搜榜单",)),
                          ("off", ()), ("goto", ("个性化内容",)), ("off", ())])
        self.assertEqual(calls[2][2], {"scrolls": 4})
        self.assertEqual([call_[2]["page"] for call_ in calls if call_[0] == "off"],
                         ["搜索·首页展示内容", "搜索·推荐热搜榜单", "搜索·个性化内容"])
        self.assertEqual(phone.start.call_args_list[0].args,
                         ("com.vivo.globalsearch", ".view.SearchSettingsActivity"))
        # 热搜子页、首页展示内容、个性化内容各退一次，收尾再退一次
        self.assertEqual(phone.back.call_args_list, [call(1), call(1), call(1), call(1)])
        self.assertEqual(len(phone.top.call_args_list), 1)
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_foreground_that_is_not_the_search_app_stops_the_segment(self):
        phone, calls, _scope, out = run_segment("全局搜索", focus="com.android.settings/.Settings")
        self.assertEqual(calls, [])
        self.assertIn("没拉起全局搜索设置", out.getvalue())
        phone.back.assert_not_called()


class BrowserSegmentTests(unittest.TestCase):
    """浏览器（#1366）：首页切成极简，再逐个进三个设置页关点名的行。"""

    def test_the_minimal_home_is_picked_from_the_card_and_three_pages_are_visited(self):
        phone, calls, scope, _out = run_segment("浏览器")
        self.assertEqual([(call_[0], call_[1][:1]) for call_ in calls],
                         [("browser_settings", ()), ("goto", ("首页设置",)),
                          ("confirm2", ()), ("goto", ("网页浏览设置",)), ("off", ()),
                          ("goto", ("更多设置",)), ("off", ()),
                          ("goto", ("隐私权限设置",)), ("off", ())])
        self.assertEqual([call_[2].get("scrolls") for call_ in calls[3:]],
                         [10, None, 10, None, 10, None])
        self.assertEqual(phone.tap.call_args_list[0].args, ("极简首页",))
        self.assertEqual(phone.tap.call_args_list[0].kwargs, {"exact": True, "scrolls": 0})
        # 「首页设置」里退一次后回顶，三个入口各回顶一次
        self.assertEqual(len(phone.top.call_args_list), 4)
        self.assertEqual(phone.back.call_args_list[-1], call(3))
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_browser_without_its_settings_page_stops_at_once(self):
        phone, calls, _scope, out = run_segment("浏览器", {"browser_settings": False})
        self.assertEqual([call_[0] for call_ in calls], ["browser_settings"])
        self.assertIn("没进到浏览器设置", out.getvalue())
        phone.back.assert_not_called()          # 早退连收段的三次返回也一起跳过


class LockScreenSegmentTests(unittest.TestCase):
    """阅图锁屏（#1366）：设置搜索直达；停在结果页时再点一次结果，然后点名关。"""

    def test_landing_on_the_settings_page_needs_no_second_tap(self):
        phone, calls, _scope, _out = run_segment("阅图锁屏", focus="com.vivo.settings/.MagazineSettings")
        self.assertEqual([call_[0] for call_ in calls], ["search_setting", "off"])
        self.assertEqual(calls[0][1], ("阅图锁屏",))
        self.assertEqual(calls[1][2]["page"], "系统·阅图锁屏")
        self.assertEqual(calls[1][2]["keep"], ["锁屏底部壁纸", "移动网络自动更新"])
        phone.tap.assert_not_called()
        self.assertEqual(phone.back.call_args_list, [call(2)])

    def test_a_search_result_page_gets_tapped_once_more(self):
        phone, _calls, _scope, _out = run_segment("阅图锁屏", focus="com.android.settings/.SearchResult")
        self.assertEqual(phone.tap.call_args_list[0].args, ("阅图锁屏",))
        self.assertEqual(phone.tap.call_args_list[0].kwargs, {"exact": True, "scrolls": 4})


class WeatherSegmentTests(unittest.TestCase):
    """天气（#1366）：右上角菜单按资源 id 点（页面上另有一个同名的「更多」展开按钮）。"""

    def test_the_menu_is_tapped_by_resource_id_then_settings_is_closed(self):
        phone, calls, scope, _out = run_segment("天气")
        selectors = [call_.kwargs for call_ in phone.tap_id.call_args_list]
        self.assertEqual(selectors, [{"resource_id": "com.vivo.weather:id/more_btn"}])
        self.assertEqual([call_[0] for call_ in calls], ["tap_text", "off"])
        self.assertEqual(calls[1][2], {"only": ["天气服务"], "keep": ["气象预警", "异常天气", "地震预警"],
                                       "page": "天气·设置"})
        self.assertEqual(phone.back.call_args_list, [call(2)])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_missing_menu_button_prints_and_stops_the_segment(self):
        from fast import u2
        import catalog.interpreter as interpreter
        phone = phone_mock(W=1260, H=2800)
        phone.locked.return_value = False
        # 选择器本身不会失败：读屏库是在点的时候才去找控件
        phone.tap_id.side_effect = u2.exceptions.UiObjectNotFoundError({"code": -32002})
        asked = []
        with patch.dict(interpreter.LIBRARY, {"tap_text": lambda p, rt, *a, **k: asked.append(a)}):
            _scope, out = load_recipe(phone, RECIPE, ["天气"])
        self.assertEqual(asked, [], "菜单按钮点不到之后不该再去找设置")
        self.assertIn("没找到天气右上角的更多按钮", out.getvalue())


if __name__ == "__main__":
    unittest.main()
