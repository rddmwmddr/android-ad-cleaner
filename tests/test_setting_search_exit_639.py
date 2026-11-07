"""#639：设置搜索失败后必须离开搜索页，不然调用方会在弹出的输入法上继续滚屏。

报告者的机器（HONOR DVD-AN00，MagicOS 10）搜不到「新闻资讯」时页面停在设置搜索页，
半屏手写输入法还开着；`off()` 接着滚了 40 屏找开关，滑动全落在输入法上，一直画出「丨」。
"""
import itertools
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import fast
from fixtures import fake_phone, load_recipe, phone_stub

SEARCH_PAGE = ('<hierarchy><node text="新闻资讯" class="android.widget.EditText"'
               ' focused="true" bounds="[50,100][1000,200]"/></hierarchy>')
SETTINGS_HOME = '<hierarchy><node text="搜索设置项" bounds="[50,100][1100,200]"/></hierarchy>'


class SettingSearchExitTests(unittest.TestCase):
    def make_phone(self, *, page="search", results=(), focus="com.android.settings/.SearchActivity"):
        p = phone_stub("S")
        p.W, p.H = 1168, 1712
        p.focus = Mock(return_value=focus)
        p.say = Mock()
        p.click = Mock()
        p.type_text = Mock(return_value=True)
        p.reader = Mock()
        p.reader.shell.return_value = types.SimpleNamespace(exit_code=0, output="Starting: Intent")
        state = {"page": page}
        p.tree = Mock(side_effect=lambda: ET.fromstring(
            SEARCH_PAGE if state["page"] == "search" else SETTINGS_HOME))
        p.back = Mock(side_effect=lambda *a, **k: state.update(page="home"))
        row = ET.fromstring('<node class="android.widget.TextView"/>')
        p.texts = Mock(return_value=[(t, (50, y, 1000, y + 100), row)
                                     for t, y in results])
        p.state = state
        return p

    def run_setting(self, p, **kw):
        with patch.object(fast.time, "time", side_effect=itertools.count(0, 0.2)), \
                patch.object(fast.time, "sleep"):
            return p.setting("新闻资讯", **kw)

    def test_missing_result_returns_after_leaving_the_search_page(self):
        p = self.make_phone()
        self.assertFalse(self.run_setting(p))
        self.assertTrue(p.back.called)
        self.assertFalse(p.edit_ready())
        self.assertTrue(any("没搜到" in c.args[0] for c in p.say.call_args_list))

    def test_result_that_does_not_open_also_leaves_the_search_page(self):
        # 结果行在，点下去没换页（落点判据 timeout）：仍要退场
        p = self.make_phone(results=[("新闻资讯", 400)])
        self.assertFalse(self.run_setting(p))
        self.assertTrue(p.back.called)
        self.assertFalse(p.edit_ready())

    def test_input_failure_also_leaves_the_search_page(self):
        p = self.make_phone()
        p.type_text = Mock(return_value=False)
        self.assertFalse(self.run_setting(p))
        self.assertTrue(p.back.called)
        self.assertFalse(p.edit_ready())

    def test_search_box_not_opening_does_not_press_back(self):
        """旧树也绿，守的是失败路径不乱按返回：没进搜索页就没有输入法占屏。"""
        p = self.make_phone(page="home")
        p.reader.shell.return_value = types.SimpleNamespace(
            exit_code=1, output="Error: Activity not started, unable to resolve Intent")
        self.assertFalse(self.run_setting(p))
        p.back.assert_not_called()

    def test_failure_returns_to_the_settings_home(self):
        # 直达搜索页时它是新任务根：退场要主动拉起设置首页，不能只按返回（#639）
        p = self.make_phone()
        self.assertFalse(self.run_setting(p))
        commands = [c.args[0] for c in p.reader.shell.call_args_list]
        self.assertIn("am start -f 0x10008000 -a android.settings.SETTINGS", commands)

    def test_stuck_on_search_page_reports_where_it_landed(self):
        p = self.make_phone()
        p.back = Mock()                      # 按了也不离开：退场失败
        self.assertFalse(self.run_setting(p))
        self.assertTrue(any("com.android.settings/.SearchActivity" in c.args[0]
                            for c in p.say.call_args_list))


class HonorYoyoSearchFailureTests(unittest.TestCase):
    RECIPE = ROOT / "recipes/honor-PNM-AN10/recipe.py"

    def test_missing_search_result_skips_dismiss_and_off(self):
        p = fake_phone()
        p.setting = Mock(return_value=False)
        p.dismiss, p.off = Mock(), Mock()
        load_recipe(p, self.RECIPE, only="YOYO")
        p.dismiss.assert_not_called()
        p.off.assert_not_called()

    def test_working_search_still_closes_the_switch(self):
        """旧树也绿，守的是成功路径不回退：搜索到了仍要关那个开关。"""
        p = fake_phone()
        p.setting = Mock(return_value=True)
        p.off = Mock(return_value=1)
        load_recipe(p, self.RECIPE, only="YOYO")
        p.off.assert_called_once()


if __name__ == "__main__":
    unittest.main()
