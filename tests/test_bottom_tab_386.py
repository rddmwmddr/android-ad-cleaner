"""Phone.tab()：只在屏幕底部带里找标签，带内三层匹配，找不到不回退（#386）。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import phone_stub

W, H = 1080, 2400
CONTENT = "[0,300][1080,360]"
BAND = "[0,2200][216,2300]"
RIGHT = "[864,2200][1080,2300]"
JUST_BELOW = "[0,2039][216,2099]"     # 屏高 85% = 2040
JUST_INSIDE = "[0,2041][216,2101]"


def page(*nodes):
    return fast.ET.fromstring('<hierarchy rotation="0">' + "".join(nodes) + "</hierarchy>")


def node(text=None, desc=None, area=BAND):
    attrs = f'class="android.widget.TextView" bounds="{area}"'
    if text is not None:
        attrs += f' text="{text}"'
    if desc is not None:
        attrs += f' content-desc="{desc}"'
    return f"<node {attrs}/>"


def phone(*nodes):
    p = phone_stub("test", W=W, H=H)
    p.tree = Mock(return_value=page(*nodes))
    p.click = Mock()
    p.say = Mock()
    p.dismiss = Mock(return_value=None)
    p.sig = Mock(return_value="page")
    p.settle = Mock(return_value=True)
    return p


class TabTests(unittest.TestCase):
    def test_plain_label_in_the_bottom_band_is_clicked(self):
        p = phone(node(text="我的"))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(108, 2250)
        p.settle.assert_called_once()

    def test_selected_state_prefix_in_content_desc_is_ignored(self):
        p = phone(node(desc="未选中,我的"))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(108, 2250)

    def test_unread_suffix_label_is_clicked(self):
        p = phone(node(text="我的，有新消息"))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(108, 2250)

    def test_same_name_outside_the_band_is_not_clicked(self):
        p = phone(node(text="我的", area=CONTENT))
        self.assertFalse(p.tab("我的", maxwait=0))
        p.click.assert_not_called()

    # vivo 应用商店底栏把角标和序号一起塞进无障碍名（#530）：末段是「共5个」，
    # 既不等于「我的」也不以逗号收在「我的」，只剩包含匹配能命中。
    def test_badge_and_index_suffix_is_clicked(self):
        p = phone(node(text="我的, 2个应用待更新,第5个, 共5个"))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(108, 2250)

    def test_badge_suffix_tab_wins_over_a_content_label_with_the_same_name(self):
        p = phone(node(text="我的", area=CONTENT),
                  node(text="我的, 2个应用待更新,第5个, 共5个"))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(108, 2250)

    def test_exact_label_wins_over_a_longer_label_in_the_band(self):
        p = phone(node(text="我的奇妙小镇"), node(text="我的", area=RIGHT))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(972, 2250)

    def test_comma_tail_wins_over_a_longer_label_in_the_band(self):
        p = phone(node(text="我的奇妙小镇"), node(desc="未选中,我的", area=RIGHT))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(972, 2250)

    def test_a_label_above_the_band_is_left_alone(self):
        p = phone(node(text="我的", area=JUST_BELOW))
        self.assertFalse(p.tab("我的", maxwait=0))
        p.click.assert_not_called()

    def test_a_label_just_inside_the_band_is_clicked(self):
        p = phone(node(text="我的", area=JUST_INSIDE))
        self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(108, 2071)

    def test_band_without_a_match_returns_false_and_clicks_nothing(self):
        p = phone(node(text="首页"))
        self.assertFalse(p.tab("我的", maxwait=0))
        p.click.assert_not_called()

    def test_tab_that_shows_up_late_is_still_clicked(self):
        pages = [page(), page(), page(node(text="我的"))]
        p = phone()
        p.tree = Mock(side_effect=lambda: pages.pop(0) if len(pages) > 1 else pages[0])
        clock = [0.0]
        with patch.object(fast.time, "time", side_effect=lambda: clock[0]), \
                patch.object(fast.time, "sleep", side_effect=lambda s: clock.__setitem__(0, clock[0] + s)):
            self.assertTrue(p.tab("我的"))
        p.click.assert_called_once_with(108, 2250)


if __name__ == "__main__":
    unittest.main()
