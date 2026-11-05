"""V2303A：系统广告 / 全局搜索 / 阅图锁屏三段改走 p.setting() 设置内搜索直达（#579）。

Android 17 上从设置首页逐层翻页会滑出设置页、触发保护性中止；这台改成搜关键词直达。
全局搜索的三个子页各自重新搜一次回主页，单页失败只跳过该页。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import phone_mock

RECIPE = ROOT / "recipes/vivo-V2303A/recipe.py"


def make_phone(**fields):
    p = phone_mock(W=1260, H=2800, **fields)
    p.tree.return_value = ET.fromstring("<hierarchy></hierarchy>")
    p.on_screen.return_value = True
    p.locked.return_value = False
    p.back.return_value = None
    p.off.return_value = 0
    return p


def load(phone, only):
    scope = {"p": phone, "ONLY": only}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(RECIPE.read_text(encoding="utf-8"), str(RECIPE), "exec"), scope)
    return scope


class VivoV2303ARecipeTests(unittest.TestCase):
    def test_model_is_matched_without_reference_and_records_build(self):
        path, reference = run.recipe_for("V2303A", "vivo")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "vivo-V2303A")
        meta = run.recipe_meta(path)
        self.assertEqual(meta["build"], "CP2A.260605.016")
        self.assertEqual(meta["models"], ["V2303A"])
        self.assertEqual(meta["steps"],
                         ["系统广告", "全局搜索", "阅图锁屏", "应用商店", "浏览器", "i管家", "天气"])

    def test_settings_segments_search_inside_settings_instead_of_walking_pages(self):
        """三段都先搜关键词直达；不再从设置首页逐层 maybe() 翻。"""
        p = make_phone()
        p.setting.return_value = True
        p.entry.return_value = True
        load(p, only=["系统广告", "阅图锁屏"])
        self.assertEqual([c.args[0] for c in p.setting.call_args_list], ["广告与隐私", "锁屏设置"])
        self.assertEqual({c.kwargs["page"] for c in p.off.call_args_list},
                         {"系统·广告与隐私", "阅图锁屏"})

    def test_global_search_reenters_the_home_page_for_every_subpage(self):
        p = make_phone()
        p.setting.return_value = True
        p.entry.return_value = True
        load(p, only=["全局搜索"])
        self.assertEqual(p.setting.call_count, 3)
        self.assertEqual([c.args[0] for c in p.setting.call_args_list], ["全局搜索"] * 3)

    def test_a_failing_subpage_does_not_stop_the_following_ones(self):
        """任一子页触发「离开设置页」保护只跳过该页，后面的子页照常钻。"""
        p = make_phone()
        p.setting.return_value = True
        p.entry.return_value = True
        pages = []

        def off(**kw):
            pages.append(kw["page"])
            if len(pages) == 2:
                raise RuntimeError("离开设置页，停止本段")
            return 0

        p.off.side_effect = off
        load(p, only=["全局搜索"])
        self.assertEqual(pages, ["全局搜索·首页展示内容", "全局搜索·推荐热搜榜单", "全局搜索·个性化内容"])

    def test_global_search_does_nothing_when_the_search_box_never_opens(self):
        p = make_phone()
        p.setting.return_value = False
        load(p, only=["全局搜索"])
        p.off.assert_not_called()
        self.assertEqual(p.setting.call_count, 1)


if __name__ == "__main__":
    unittest.main()
