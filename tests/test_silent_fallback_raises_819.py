"""三处机型脚本：设置搜索失败、兜底也不通时停段记败，不再静默成功（#819）。

步骤在 load_recipe 装载时由 @step 装饰器执行并吞异常记 FAILED_STEPS——
用例只断言 FAILED_STEPS 与假 Phone 的调用清单。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import load_recipe, phone_mock

RECIPES = ROOT / "recipes"


def base_phone():
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.dismiss.return_value = None
    p.sig.return_value = "page"
    return p


class HonorAdTrackingFallbackTests(unittest.TestCase):
    """honor-PNM-AN10「广告跟踪」：直达抛错才进搜索/菜单兜底，兜底死路必须记败。"""

    RECIPE = RECIPES / "honor-PNM-AN10/recipe.py"

    def test_menu_fallback_dead_end_is_a_failed_step(self):
        """直达抛错 + 搜索失败 + 菜单三步打不通：进 FAILED_STEPS，不再裸 return。"""
        p = base_phone()
        p.start.side_effect = RuntimeError("直达失败")
        p.setting.return_value = False
        p.tap.return_value = False
        scope, _ = load_recipe(p, self.RECIPE, only=("广告跟踪",))
        self.assertIn("广告跟踪", scope["FAILED_STEPS"])
        p.tap.assert_any_call("隐私和安全", exact=True)      # 菜单兜底确实走起（and 短路：首击败即停）

    def test_menu_fallback_reaching_the_page_still_passes(self):
        """直达抛错 + 搜索失败 + 菜单走通：仍拨同一批开关，段不算失败。"""
        p = base_phone()
        p.start.side_effect = [RuntimeError("直达失败"), None]   # 只让第一次（直达）抛，回开 App 不抛
        p.setting.return_value = False
        p.tap.return_value = True
        p.find.return_value = None
        scope, _ = load_recipe(p, self.RECIPE, only=("广告跟踪",))
        self.assertNotIn("广告跟踪", scope["FAILED_STEPS"])
        p.off.assert_called_once()

    def test_direct_hit_path_is_untouched(self):
        """直达成功：不碰搜索与菜单，拨动集合不变。"""
        p = base_phone()
        p.find.return_value = None
        scope, _ = load_recipe(p, self.RECIPE, only=("广告跟踪",))
        self.assertNotIn("广告跟踪", scope["FAILED_STEPS"])
        p.setting.assert_not_called()
        self.assertEqual(p.start.call_count, 2)             # 直达 + 回开 App，各一次


class VivoGlobalSearchFallbackTests(unittest.TestCase):
    """vivo-V2303A「全局搜索」：搜索失败 raise（在 try 外，单子页的 except 吞不掉）。"""

    RECIPE = RECIPES / "vivo-V2303A/recipe.py"

    def test_search_failure_is_a_failed_step(self):
        p = base_phone()
        p.setting.return_value = False
        scope, _ = load_recipe(p, self.RECIPE, only=("全局搜索",))
        self.assertIn("全局搜索", scope["FAILED_STEPS"])
        p.off.assert_not_called()

    def test_search_success_keeps_the_per_subpage_skip_guard(self):
        """搜索走通、单个子页出异常：仍按子页跳过，整段不算失败。"""
        p = base_phone()
        p.setting.return_value = True
        p.entry.side_effect = RuntimeError("页面变了")
        scope, _ = load_recipe(p, self.RECIPE, only=("全局搜索",))
        self.assertNotIn("全局搜索", scope["FAILED_STEPS"])


class RedmiSystemAdsFallbackTests(unittest.TestCase):
    """redmi-25060RK16C「系统广告」：菜单兜底没到「广告服务」时必须记败。"""

    RECIPE = RECIPES / "redmi-25060RK16C/recipe.py"

    def test_menu_fallback_dead_end_is_a_failed_step(self):
        """搜索失败 + 菜单各层都打不通：进 FAILED_STEPS。"""
        p = base_phone()
        p.setting.return_value = False
        p.entry.return_value = False
        scope, _ = load_recipe(p, self.RECIPE, only=("系统广告",))
        self.assertIn("系统广告", scope["FAILED_STEPS"])
        p.off.assert_not_called()

    def test_menu_fallback_reaching_ads_service_still_passes(self):
        """搜索失败 + 菜单走通：拨同一批开关后正常返回，段不算失败。"""
        p = base_phone()
        p.setting.return_value = False
        p.entry.return_value = True
        scope, _ = load_recipe(p, self.RECIPE, only=("系统广告",))
        self.assertNotIn("系统广告", scope["FAILED_STEPS"])
        p.off.assert_called_once_with(only=["个性化广告推荐", "广告跟踪"], page="系统·广告服务")

    def test_search_hit_path_is_untouched(self):
        """搜索直达：不走菜单。"""
        p = base_phone()
        p.setting.return_value = True
        scope, _ = load_recipe(p, self.RECIPE, only=("系统广告",))
        self.assertNotIn("系统广告", scope["FAILED_STEPS"])
        p.entry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
