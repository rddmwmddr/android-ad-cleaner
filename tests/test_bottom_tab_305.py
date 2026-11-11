"""p.go() 精确匹配不到时退回包含匹配，但落点仍由 expect 确认（#305 的第二层原因）。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import phone_stub, stub


def phone(*, exact_tab, loose_tab, lands):
    """exact_tab / loose_tab：精确 / 包含匹配「我的」返回的坐标；lands：点完后 expect 是否出现。"""
    p = phone_stub("test", W=1080, H=2400)
    p.say = Mock()
    p.dismiss = Mock(return_value=None)
    # `go()` 内部调的是导航阶段的 `tap()`、观测基座的 `find()`（ADR-0033）：桩要落到那里
    stub(p, "tap", Mock(return_value=True))

    def find(text, exact=False, root=None, edge_ok=False, nav=False):
        if text == "我的":
            return exact_tab if exact else loose_tab
        return (300, 300) if lands else None

    stub(p, "find", find)
    return p


class GoBottomTabTests(unittest.TestCase):
    def test_exact_tab_is_used_when_it_reads_exactly_my(self):
        p = phone(exact_tab=(540, 2300), loose_tab=None, lands=True)
        self.assertTrue(p.go("我的", "设置"))
        p.navigator.tap.assert_called_once_with("我的", exact=True, scrolls=0)

    def test_suffixed_tab_falls_back_to_contains(self):
        p = phone(exact_tab=None, loose_tab=(540, 2300), lands=True)
        self.assertTrue(p.go("我的", "设置"))
        p.navigator.tap.assert_called_once_with("我的", exact=False, scrolls=0)

    def test_loose_click_that_lands_nowhere_still_fails(self):
        p = phone(exact_tab=None, loose_tab=(540, 2300), lands=False)
        with patch.object(fast.time, "sleep"):
            self.assertFalse(p.go("我的", "设置"))

    def test_caller_requesting_loose_match_skips_the_probe(self):
        p = phone(exact_tab=(540, 2300), loose_tab=(540, 2300), lands=True)
        self.assertTrue(p.go("我的", "设置", exact=False))
        p.navigator.tap.assert_called_with("我的", exact=False, scrolls=0)


if __name__ == "__main__":
    unittest.main()
