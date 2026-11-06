"""vivo V2417A 浏览器段：31.3.0.0 起底部标签栏没有「菜单」，设置改挂在「我的」页右上角。

录制脚本用的浏览器是 31.1.3.1，入口是底部「菜单」→「设置」。31.3.0.0 上底部标签栏改成
首页/视频/AI/影视小说/我的，「菜单」这个文字不再存在，整段只能报「没找到入口」。
两条入口都要试：有「菜单」点「菜单」，没有它走「我的」页右上角那个图标。
图标文字的 content-desc 是「设置」，所以按文字找得到，不该退化成 `tap_icon()`——
`icon_candidates()` 只收文字与 desc 都为空的节点，这份图标会被它排除。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_stub

SETTING_FOCUS = "com.vivo.browser/com.vivo.browser.ui.module.setting.common.activity.SettingActivity"
# 31.3.0.0 实测：「我的」页右上角的设置图标没有 text，文字只在 content-desc 上。
MINE_PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.vivo.browser" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="我的" bounds="[908,2343][998,2380]" />
    <node class="android.widget.ImageView" content-desc="设置" clickable="true"
          bounds="[927,120][1080,255]" />
  </node>
</hierarchy>"""


class Vivo2417BrowserEntryTests(unittest.TestCase):
    def phone(self, has_menu):
        """一段浏览器路径需要的最小假手机：入口点得到，页面细节交给被替换的 helper。"""
        p = phone_stub("test", d=Mock())
        p.W, p.H = 1080, 2400
        p.locked = Mock(return_value=False)
        p.start = Mock(return_value=True)
        p.entry = Mock(return_value=has_menu)
        p.go = Mock(return_value=True)
        p.find = Mock(return_value=(540, 1200))
        p.back = Mock()
        p.focus = Mock(return_value=SETTING_FOCUS)
        return p

    def browser_step(self, p):
        scope, _ = load_recipe(p, ROOT / "recipes/vivo-V2417A/recipe.py")
        scope["tap"] = Mock(return_value=True)          # 首页设置/极简首页等子页入口
        scope["close_named"] = Mock(return_value=True)  # 本用例只验入口，不验开关
        return scope

    def test_old_browser_still_uses_the_menu_entry(self):
        """31.1.3.1：「菜单」在，就照老路径点，不该多此一举去翻「我的」。"""
        p = self.phone(has_menu=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.browser_step(p)["browser"]()
        self.assertEqual(p.entry.call_args_list, [call("菜单", scrolls=0)])
        self.assertEqual(p.go.call_args_list, [call("设置", "首页设置")])

    def test_new_browser_falls_back_to_the_mine_tab(self):
        """31.3.0.0：底部没有「菜单」，改点「我的」直到「设置」出现，再进设置主页。"""
        p = self.phone(has_menu=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.browser_step(p)["browser"]()
        self.assertEqual(p.entry.call_args_list, [call("菜单", scrolls=0)])
        self.assertEqual(p.go.call_args_list, [call("我的", "设置"), call("设置", "首页设置")])

    def test_both_entries_missing_reports_the_section_as_unfinished(self):
        """两条入口都落空时报「未打开浏览器设置入口」，不留在首页上乱点后面的子页。"""
        p = self.phone(has_menu=False)
        p.go = Mock(return_value=False)
        scope = self.browser_step(p)
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "未打开浏览器设置入口"):
                scope["browser"]()
        scope["tap"].assert_not_called()
        scope["close_named"].assert_not_called()

    def test_the_mine_page_settings_icon_is_found_by_its_content_desc(self):
        """「设置」只写在 content-desc 上：`find` 要能按文字命中它，`tap_icon` 反而不该命中。"""
        p = phone_stub("test", d=Mock(), W=1080, H=2400)
        p.tree = Mock(return_value=ET.fromstring(MINE_PAGE))
        self.assertEqual(p.find("设置", exact=True, edge_ok="tab", nav=True), (1003, 187))
        self.assertEqual(p.icon_candidates(), [])


if __name__ == "__main__":
    unittest.main()
