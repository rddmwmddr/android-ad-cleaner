"""确认框按钮的文字位置：vivo 阅图锁屏把按钮文字放在 content-desc 上（Issue #246）。

设备无关：用 dump 到的真实层级树片段构造 XML，不连接手机。
运行：python -m unittest discover -s tests -v
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import fast
from fixtures import phone_stub


def phone(size=(1080, 2400)):
    p = phone_stub("test", d=Mock())
    p.W, p.H = size
    return p


class ConfirmButtonTests(unittest.TestCase):
    @patch.object(fast.time, "sleep")
    def test_button_label_from_content_desc(self, _sleep):
        """vivo V2452A / 阅图锁屏：Button 的 text 为空，文字在 content-desc。

        页面同时有一个 text="关闭" 的 TextView（说明行里的一部分），
        点和读都必须落在 Button 上。
        """
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="false" bounds="[502,2175][578,2222]"/>
          <node class="android.widget.Button" content-desc="保持开启" clickable="true" bounds="[270,1944][810,2082]"/>
          <node class="android.widget.Button" content-desc="关闭" clickable="true" bounds="[270,2130][810,2268]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "关闭")
        p.click.assert_called_once_with(540, 2199)

    @patch.object(fast.time, "sleep")
    def test_state_text_without_button_class_is_ignored(self, _sleep):
        """ColorOS 开关旁边的「关闭」是状态文字，不是按钮：点了会把开关拨回去。"""
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="false" bounds="[900,400][1000,450]"/>
          <node class="android.view.View" text="关闭" clickable="true" bounds="[900,500][1000,550]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertIsNone(p.confirm())
        p.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_sentence_in_content_desc_is_not_a_confirm_label(self, _sleep):
        """content-desc 是整段说明时不算确认词，不能点。"""
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.Button" content-desc="关闭后将无法自动切换锁屏壁纸及滑动浏览图集，建议保持开启。"
                clickable="true" bounds="[60,2200][1020,2320]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertIsNone(p.confirm())
        p.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_traditional_confirm_button(self, _sleep):
        """繁体界面上的确认键是「確定」（#604）：词表只收简体时这一下点不到。"""
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.Button" text="取消" clickable="true" bounds="[120,2200][480,2320]"/>
          <node class="android.widget.Button" text="確定" clickable="true" bounds="[600,2200][960,2320]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "確定")
        p.click.assert_called_once_with(780, 2260)

    @patch.object(fast.time, "sleep")
    def test_clickable_text_view_is_a_confirm_button(self, _sleep):
        """HyperOS 4（小米 17）热榜页：确认键是可点击的 TextView，不是 Button（#500 / PR #408）。

        弹窗里同时有说明文字与「取消」，点必须落在「关闭」上。
        """
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭热榜后将不再显示榜单内容" clickable="false" bounds="[60,1900][1020,2100]"/>
          <node class="android.widget.TextView" text="取消" clickable="true" bounds="[120,2200][480,2320]"/>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[600,2200][960,2320]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "关闭")
        p.click.assert_called_once_with(780, 2260)

    @patch.object(fast.time, "sleep")
    def test_button_class_wins_over_clickable_text_view(self, _sleep):
        """严格档优先：同一页既有 Button 又有可点击 TextView 时点 Button。"""
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="确定" clickable="true" bounds="[600,2200][960,2320]"/>
          <node class="android.widget.Button" text="确定" clickable="true" bounds="[120,2200][480,2320]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "确定")
        p.click.assert_called_once_with(300, 2260)

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_skips_wide_or_tall_nodes(self, _sleep):
        """兜底档只认按钮级尺寸：整行宽度和整段高度各守一个阈值。"""
        for bounds in ("[60,2000][1020,2320]", "[300,1600][600,2100]"):
            with self.subTest(bounds=bounds):
                p = phone()
                root = ET.fromstring(
                    f'<hierarchy><node class="android.widget.TextView" text="关闭" '
                    f'clickable="true" bounds="{bounds}"/></hierarchy>')
                p.tree, p.click = Mock(return_value=root), Mock()
                self.assertIsNone(p.confirm())
                p.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_skips_bounds_at_the_threshold(self, _sleep):
        """阈值是严格小于：宽 540（0.5W）、高 288（0.12H）恰好卡线时都不点。"""
        for bounds in ("[270,2000][810,2100]", "[300,2000][600,2288]"):
            with self.subTest(bounds=bounds):
                p = phone()
                root = ET.fromstring(
                    f'<hierarchy><node class="android.widget.TextView" text="关闭" '
                    f'clickable="true" bounds="{bounds}"/></hierarchy>')
                p.tree, p.click = Mock(return_value=root), Mock()
                self.assertIsNone(p.confirm())
                p.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_skips_offscreen_nodes(self, _sleep):
        """屏外残留的 TextView 不点。"""
        p = phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[600,2500][960,2700]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertIsNone(p.confirm())
        p.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_scales_with_the_screen(self, _sleep):
        """阈值按当前屏尺寸算：窄屏上整行文字仍被排除，按钮级文字仍能命中。"""
        p = phone((720, 1600))
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[40,1320][680,1420]"/>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[380,1200][700,1300]"/>
        </hierarchy>''')
        p.tree, p.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "关闭")
        p.click.assert_called_once_with(540, 1250)


if __name__ == "__main__":
    unittest.main()
