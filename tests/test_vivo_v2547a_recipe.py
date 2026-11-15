"""V2547A（X300 Ultra）应用商店段转成数据（#1365）：「我的」页的入口与「关于」里的两层子页。

这台没有直达（「我的」页的齿轮点左侧文字不转发点击），入口是 `start` 起商店 → `tap_text`
点「我的」→ 点「设置」，之后 `goto` 逐页进「关于」里的两页。空页面快照上 `tap_text` / `goto`
一律落空，只有「没找到」那两支走得到，所以入口成功的那条路在这里补。
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


if __name__ == "__main__":
    unittest.main()
