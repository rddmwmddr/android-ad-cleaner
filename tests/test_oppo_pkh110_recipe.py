"""PHK110 的广告跟踪段转成数据（#1337）：三台 ColorOS 共用的收尾「等列表加载 → 回页顶 → 整页关」。

列表没加载出来时不能闭着眼睛整页关——那只会空跑一遍；这一段按未完成收场。
"""
from pathlib import Path
import contextlib
import io
import sys
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import recipe_lib.oppo as oppo
from fixtures import RecipeClock, phone_mock


def phone(*switch_pages):
    p = phone_mock(W=1080, H=2400)
    p.switches.side_effect = [list(page) for page in switch_pages]
    return p


class AdTrackingClosePagedTests(unittest.TestCase):
    def test_the_list_is_closed_once_it_loads(self):
        loaded = [("应用一", True, (1, 2))]
        p = phone([], [], loaded, loaded)
        self.assertTrue(oppo.ad_tracking_close_paged(p, SimpleNamespace(clock=RecipeClock())))
        # 页顶留足 16 屏的余量：219 个应用的列表要翻很多屏才回得去
        self.assertEqual(p.top.call_args.kwargs, {"n": 16})
        p.off.assert_called_once_with(page="广告跟踪", max_screens=40)

    def test_a_list_that_never_loads_is_not_blindly_closed(self):
        p = phone(*([[]] * 31))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(oppo.ad_tracking_close_paged(p, SimpleNamespace(clock=RecipeClock())))
        p.off.assert_not_called()
        self.assertIn("广告跟踪列表未加载", out.getvalue())


if __name__ == "__main__":
    unittest.main()
