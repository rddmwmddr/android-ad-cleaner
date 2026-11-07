"""#671：荣耀 CLE-AN00 机型脚本。不代为同意协议、底部标签带角标、必需入口缺失要报失败。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from fixtures import load_recipe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

RECIPE = ROOT / "recipes" / "honor-CLE-AN00" / "recipe.py"


def phone(**over):
    p = Mock()
    p.locked.return_value = False
    p.focus.return_value = ""
    p.entry.return_value = True
    p.tab.return_value = True
    p.tap.return_value = True
    p.find.return_value = None
    p.setting.return_value = True
    p.expect_page.return_value = True
    p.switches.return_value = []
    p.texts.return_value = []
    p.W, p.H = 1080, 2400
    for k, v in over.items():
        setattr(p, k, v)
    return p


def run(p, name):
    scope, out = load_recipe(p, RECIPE, only=name)
    return scope, out.getvalue()


def agreement(text, exact=False, **kw):
    return object() if text == "同意" else None


class AgreementTest(unittest.TestCase):
    def test_theme_with_agreement_is_skipped_not_failed(self):
        p = phone()
        p.find.side_effect = agreement
        scope, out = run(p, "主题")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("不代为同意", out)
        p.off.assert_not_called()
        p.tap.assert_not_called()
        p.entry.assert_not_called()

    def test_theme_is_launched_raw_so_the_engine_does_not_cancel_the_dialog(self):
        # p.start 的弹窗处理会点「取消」，App 一退就分不清是没同意还是没打开
        p = phone()
        p.find.side_effect = agreement
        run(p, "主题")
        p.start.assert_not_called()
        self.assertIn("com.hihonor.android.thememanager/.PageActivity", p.d.shell.call_args.args[0])

    def test_market_with_agreement_is_skipped(self):
        p = phone()
        p.find.side_effect = agreement
        scope, _ = run(p, "市场")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.off.assert_not_called()


class MarketTest(unittest.TestCase):
    def test_uses_the_bottom_tab_and_closes_each_switch_alone(self):
        p = phone()
        scope, _ = run(p, "市场")
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tab.assert_called_once_with("我的")
        only = [c.kwargs["only"] for c in p.off.call_args_list]
        self.assertEqual(only[:3], [["营销服务推荐"], ["个性化服务推荐"], ["热门推荐管理"]])

    def test_keeps_update_and_system_notices(self):
        p = phone()
        run(p, "市场")
        kept = [c.kwargs.get("keep", []) for c in p.off.call_args_list]
        self.assertIn(["应用更新通知"], kept)
        self.assertIn(["系统通知", "互动"], kept)

    def test_never_switches_to_basic_service(self):
        # 切回完整服务要重新同意协议
        p = phone()
        run(p, "市场")
        self.assertNotIn("基本服务", [c.args[0] for c in p.tap.call_args_list])
        self.assertNotIn("服务模式", [c.args[0] for c in p.entry.call_args_list])

    def test_missing_entry_is_a_failure_not_silent_success(self):
        p = phone()
        p.entry.side_effect = lambda text, scrolls=4: text != "内容推荐服务"
        scope, out = run(p, "市场")
        self.assertEqual(scope["FAILED_STEPS"], ["市场"])
        self.assertIn("内容推荐服务", out)


class AdTrackingTest(unittest.TestCase):
    def test_reports_switches_still_on_after_close_all(self):
        p = phone()
        p.switches.return_value = [("某应用", True), ("别的应用", False)]
        scope, out = run(p, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], ["广告跟踪"])
        self.assertIn("还有 1 个开着", out)

    def test_does_not_print_app_names(self):
        # 列表是装机应用，属于个人信息
        p = phone()
        p.switches.return_value = [("某个私人应用", False)]
        _, out = run(p, "广告跟踪")
        self.assertNotIn("某个私人应用", out)


class MinusOneTest(unittest.TestCase):
    def test_waits_for_the_page_before_scrolling(self):
        # 页面切换时前台还是上一页，这时翻页引擎会判成「离开了设置页」
        p = phone()
        p.find.side_effect = lambda text, exact=False, **kw: object() if text == "头像" else None
        calls = []
        p.expect_page.side_effect = lambda *a, **k: calls.append("等") or True
        p.off.side_effect = lambda **k: calls.append("关")
        run(p, "负一屏")
        self.assertEqual(calls, ["等", "关", "等", "关"])

    def test_page_that_never_draws_is_a_failure(self):
        p = phone()
        p.find.side_effect = lambda text, exact=False, **kw: object() if text == "头像" else None
        p.expect_page.return_value = False
        scope, _ = run(p, "负一屏")
        self.assertEqual(scope["FAILED_STEPS"], ["负一屏"])
        p.off.assert_not_called()


class NamedOnlyTest(unittest.TestCase):
    def test_every_close_names_its_switches(self):
        # 按型号 + 版本匹配时不是安全模式，不点名就是整页全关
        src = RECIPE.read_text(encoding="utf-8")
        for line in src.splitlines():
            if "p.off(" in line and "only=" not in line:
                self.fail(f"没有点名的 p.off：{line.strip()}")


if __name__ == "__main__":
    unittest.main()
