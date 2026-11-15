"""V2545A（X Fold6）系统广告段转成数据（#1365）：先走「安全 → 更多安全设置 → 广告与隐私」，
走不通再按关键词搜「广告」。

两条路都在同一段里，快照的空页面上 `entry` 一律落空，只有兜底那一支走得到；安全页那条路
要 `entry` 全部算成才走得进去，所以这里按 `entry` / `setting` 两档返回值把四支补齐。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/vivo/V2545A/V2545A.toml"
NAMES = ["个性化广告", "个性化推荐", "智能推荐服务"]


def run(entry=True, setting=True):
    """跑系统广告段：`entry` 决定设置首页那几层入口认不认得出，`setting` 是搜索直达的成败。"""
    phone = phone_mock(W=1080, H=2400)
    phone.locked.return_value = False
    phone.focus.return_value = "com.vivo.settings/.Settings"
    phone.entry.return_value = entry
    phone.setting.return_value = setting
    pages = []
    phone.off.side_effect = lambda **kwargs: pages.append(kwargs["page"]) or 0
    scope, _out = load_recipe(phone, RECIPE, ["系统广告"])
    return phone, pages, scope


class VivoV2545ARecipeTests(unittest.TestCase):
    def test_the_safety_branch_closes_the_page_and_the_search_is_not_tried(self):
        """守卫用例：旧树也绿，守的是「走到了安全页就不再搜一次」。"""
        phone, pages, scope = run()
        self.assertEqual(pages, ["系统·广告与隐私"])
        phone.setting.assert_not_called()
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_missing_safety_entry_falls_back_to_the_settings_search(self):
        phone, pages, scope = run(entry=False)
        self.assertEqual(phone.setting.call_args.args, ("广告", "广告与隐私"))
        self.assertEqual(pages, ["系统·广告与隐私（搜索）"])
        self.assertEqual(scope["FAILED_STEPS"], [])

    def test_a_dead_search_ends_the_segment_without_touching_any_switch(self):
        _phone, pages, scope = run(entry=False, setting=False)
        self.assertEqual(pages, [])
        self.assertEqual(scope["FAILED_STEPS"], [])


if __name__ == "__main__":
    unittest.main()
