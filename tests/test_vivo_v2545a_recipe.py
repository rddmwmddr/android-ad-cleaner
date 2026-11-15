"""V2545A 的系统广告段转成数据（#1337）：先走设置菜单，走不通再按关键词搜「广告」。

两条路各关到哪一页由 `page` 区分（`系统·广告与隐私` / `系统·广告与隐私（搜索）`），
快照停在合成空页的「直达不通」那一步，所以分支只能靠这里守。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/vivo/V2545A/V2545A.toml"
ONLY = ["个性化广告", "个性化推荐", "智能推荐服务"]


def run_segment(**answers):
    """跑系统广告段：三个库调用换成桩，`answers` 给它们各自的返回值。"""
    import catalog.interpreter as interpreter
    phone = phone_mock(W=1080, H=2400)
    phone.locked.return_value = False
    phone.off.return_value = 0
    calls = []
    defaults = {"system_ads_branch": True, "setting_search": True}

    def recorder(name):
        def call(p, rt, *args, **kwargs):
            calls.append((name, args, kwargs))
            return answers.get(name, defaults.get(name))
        return call

    with patch.dict(interpreter.LIBRARY, {name: recorder(name) for name in defaults}):
        _scope, out = load_recipe(phone, RECIPE, ["系统广告"])
    return phone, calls, out


class SystemAdsSegmentTests(unittest.TestCase):
    def test_the_menu_path_closes_the_switches_and_never_searches(self):
        phone, calls, _out = run_segment()
        self.assertEqual([call[0] for call in calls], ["system_ads_branch"])
        phone.off.assert_not_called()          # 菜单那条路的 off 在库里，这一段不再补一次

    def test_a_menu_path_that_ends_nowhere_falls_back_to_the_settings_search(self):
        phone, calls, _out = run_segment(system_ads_branch=False)
        self.assertEqual([call[0] for call in calls], ["system_ads_branch", "setting_search"])
        self.assertEqual(calls[1][1], ("广告", "广告与隐私"))
        self.assertEqual(phone.off.call_args_list[0].kwargs["page"], "系统·广告与隐私（搜索）")
        self.assertEqual(phone.off.call_count, 1)

    def test_neither_path_reaching_a_switch_touches_nothing(self):
        phone, _calls, _out = run_segment(system_ads_branch=False, setting_search=False)
        phone.off.assert_not_called()


class SystemAdsBranchTests(unittest.TestCase):
    """`system_ads_branch` 的返回值：走到了广告与隐私页就是真，与关掉几项无关。"""

    def run_branch(self, entries, closed=0):
        import recipe_lib.vivo as vivo
        p = phone_mock(W=1080, H=2400)
        p.entry.side_effect = lambda text, scrolls=6: text in entries
        p.off.return_value = closed
        return vivo.system_ads_branch(p, Mock()), p

    def test_a_reached_page_reports_true_even_when_nothing_was_closed(self):
        # 出厂就全关是常态：走通了这条路就不该再搜一次设置
        ok, p = self.run_branch({"安全与隐私", "更多安全设置", "广告与隐私"}, closed=0)
        self.assertTrue(ok)
        self.assertEqual(p.off.call_args_list[0].kwargs["only"], ONLY)

    def test_a_chain_that_breaks_before_the_page_reports_false(self):
        ok, p = self.run_branch({"安全", "更多安全设置"})
        self.assertFalse(ok)
        p.off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
