"""设置搜索搬出 `Phone` 之后的两条对外契约（ADR-0033、#1042）。

钉两件事：
  · 门面继续转发 `setting()` / `type_text()` / `edit_ready()` / `focused_text()`——返回值由阶段给；
  · 这个阶段只造自己就能验：给一个假 `Screen` 就能判「在不在搜索页」「框里是什么」，
    不必造整台 `Phone`。这是搬迁声称的测试面下沉，不是实现细节。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from fixtures import phone_stub, screen_stub  # noqa: E402

# 荣耀 MagicOS 10 的设置搜索框：AutoCompleteTextView，类名里没有 EditText（沿用 #597 的判例）
SEARCH_BOX = ('<hierarchy><node class="android.widget.AutoCompleteTextView" focused="true" '
              'text="广告" bounds="[138,509][930,629]"/></hierarchy>')


def bare_search(page=SEARCH_BOX):
    """只造设置搜索阶段：观测替身取 `fixtures.screen_stub()`，没有 `Phone`。"""
    return fast.SettingsSearch(screen_stub(page), fast.LostNote())


class FacadeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_the_phase_methods_go_through_the_session(self):
        """门面没有实现残留：把阶段换成替身，返回值必须由替身给出。"""
        self.p.search = Mock()
        self.p.search.setting.return_value = False
        self.p.search.type_text.return_value = True
        self.p.search.edit_ready.return_value = True
        self.p.search.focused_text.return_value = "广告"
        self.assertFalse(self.p.setting("广告", "广告服务", "搜索设置", "隐私 > 广告"))
        self.assertTrue(self.p.type_text("广告", timeout=0.5))
        self.assertTrue(self.p.edit_ready())
        self.assertEqual(self.p.focused_text(), "广告")
        self.p.search.setting.assert_called_once_with("广告", "广告服务", "搜索设置", "隐私 > 广告")
        self.p.search.type_text.assert_called_once_with("广告", 0.5)
        self.p.search.edit_ready.assert_called_once_with()
        self.p.search.focused_text.assert_called_once_with()


class StandalonePhaseTests(unittest.TestCase):
    def test_the_search_page_is_recognised_without_a_phone(self):
        search = bare_search()
        self.assertTrue(search.edit_ready())
        self.assertEqual(search.focused_text(), "广告")

    def test_a_page_without_a_focused_box_is_not_the_search_page(self):
        search = bare_search('<hierarchy><node text="搜索设置项" bounds="[50,100][1030,200]"/></hierarchy>')
        self.assertFalse(search.edit_ready())
        self.assertIsNone(search.focused_text())


if __name__ == "__main__":
    unittest.main()
