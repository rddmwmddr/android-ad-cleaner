"""OPPO Find X8s（PKT110）：换页的入口要确认页面真的换了，没换就重点；失败时报出停在哪一页（#286）。

0.3.0 日志里主题商店「我的」→「设置」、视频「我的」→「设置」各只点一次；点击被关弹窗的淡出
动画吞掉后仍当成已经换页，下一步在旧页上找入口，整段以「未找到入口」结束。只补终点页面的
文字不够——「我的」点开后页面上本来就有「设置」，真正没发生的是换页。
"""
from pathlib import Path
import contextlib
import io
import sys
import unittest
from unittest.mock import Mock, call

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import phone_mock, phone_stub


def phone(taps=1):
    """真 `Phone`，只把读屏、点击、等页面换成可编排的替身。`taps` 次点击后 tap 返回 False。"""
    p = phone_stub("test", W=1080, H=2400)
    p.say = Mock()
    p.sig = Mock(return_value="点击前的页面")
    p.page_text = Mock(return_value="主题 / 壁纸 / 字体")
    p.find = Mock(return_value=(540, 2300))
    rounds = {"left": taps}

    def tap(text, **kw):
        if rounds["left"] <= 0:
            return False
        rounds["left"] -= 1
        if kw.get("seen") is not None:
            kw["seen"].append("点击前的页面")
        return True

    p.tap = Mock(side_effect=tap)
    return p


def load_step(p, only):
    """按段名加载并执行：返回 (scope, 标准输出)。"""
    path = ROOT / "recipes/oppo-PKT110/recipe.py"
    scope = {"p": p, "ONLY": only}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
    return scope, out.getvalue()


class EnterRetriesSwallowedTapTests(unittest.TestCase):
    def test_swallowed_first_tap_is_tapped_again(self):
        """第一次点完页面没换：enter 要再点一次，第二次换页后返回。"""
        p = phone(taps=2)
        p.settle = Mock(side_effect=[False, True])
        p.enter("我的")
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["我的", "我的"])

    def test_a_tap_that_lands_is_not_repeated(self):
        p = phone()
        p.settle = Mock(return_value=True)
        p.enter("我的")
        p.tap.assert_called_once()
        self.assertEqual(p.tap.call_args.kwargs["scrolls"], 0)

    def test_page_that_never_changes_reports_the_page_it_stayed_on(self):
        p = phone(taps=3)
        p.settle = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, "页面没有变化.*主题 / 壁纸 / 字体"):
            p.enter("我的")
        self.assertEqual(p.tap.call_count, 3)

    def test_missing_entry_is_reported_with_the_page_text(self):
        p = phone(taps=0)
        with self.assertRaisesRegex(RuntimeError, "未找到入口「我的」.*主题 / 壁纸 / 字体"):
            p.enter("我的")
        p.tap.assert_called_once()

    def test_change_is_measured_from_the_click_not_from_before_the_scroll(self):
        """入口要翻页才找得到：翻页也会改页面，基准要取点击那一刻，否则点被吞也判成功。"""
        p = phone()
        p.sig = Mock(return_value="翻页前")
        rounds = {"left": 1}

        def tap(text, **kw):
            p.sig.return_value = "翻到入口那一屏"
            kw["seen"].append(p.sig())
            rounds["left"] -= 1
            return True

        p.tap = Mock(side_effect=tap)
        p.settle = Mock(return_value=True)
        p.enter("个性化管理", scrolls=6)
        p.settle.assert_called_once_with("翻到入口那一屏", 2.0)

    def test_suffixed_bottom_tab_is_tapped_by_contains_match(self):
        """底栏常读作「我的，有新消息」：精确找不到时退回包含匹配，换页仍由页面变化判定。"""
        p = phone()
        p.settle = Mock(return_value=True)
        p.find = Mock(side_effect=lambda text, **kw: (540, 2300) if not kw.get("exact") else None)
        p.enter("我的")
        self.assertIs(p.tap.call_args.kwargs["exact"], False)


class ThemeStoreStepTests(unittest.TestCase):
    pages = [
        [("消息通知", True, (1, 2)), ("开屏广告", True, (1, 3))],
        [("消息通知", False, (1, 2)), ("开屏广告", False, (1, 3))],
        [("个性化推荐设置", True, (1, 2))],
        [("个性化推荐设置", False, (1, 2))],
    ]

    def make(self):
        p = phone_mock()
        p.locked.return_value = False
        p.switches.side_effect = [list(page) for page in self.pages]
        return p

    def test_every_screen_change_in_the_theme_store_is_confirmed(self):
        p = self.make()
        scope, _ = load_step(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual([c.args[0] for c in p.enter.call_args_list],
                         ["我的", "服务管理", "消息与广告",              # 主路径
                          "我的", "隐私",                             # to_privacy
                          "我的", "隐私"])                            # 确认后退回，回读前重进
        self.assertEqual(scope["VERIFIED_SWITCHES"], 3)

    def test_theme_store_falls_back_to_the_settings_gear_icon(self):
        """17.22 的「设置」是右上角没有文字的齿轮：文字找不到就用图标，并用设置页的内容确认（#286）。"""
        p = self.make()
        p.tap.side_effect = lambda text, **kw: text != "设置"
        p.tap_icon.return_value = True
        scope, _ = load_step(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tap_icon.assert_called_with(["服务管理", "隐私"])

    def test_theme_store_reports_when_neither_text_nor_icon_opens_settings(self):
        p = self.make()
        p.tap.side_effect = lambda text, **kw: text != "设置"
        p.tap_icon.return_value = False
        scope, out = load_step(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], ["主题商店"])
        self.assertIn("没找到「设置」入口", out)

    def test_theme_store_fails_when_a_hop_does_not_land(self):
        p = self.make()
        p.enter.side_effect = RuntimeError("点「设置」后页面没有变化；当前页：主题 / 壁纸")
        scope, out = load_step(p, ["主题商店"])
        self.assertEqual(scope["FAILED_STEPS"], ["主题商店"])
        self.assertIn("页面没有变化", out)


class VideoStepTests(unittest.TestCase):
    def make(self):
        p = phone_mock()
        p.locked.return_value = False
        p.switches.side_effect = [
            [("个性化广告推荐", True, (1, 2)), ("个性化内容推荐", True, (1, 3))],
            [("个性化广告推荐", False, (1, 2)), ("个性化内容推荐", False, (1, 3))],
        ]
        return p

    def test_video_confirms_the_tab_and_the_settings_page_before_the_row(self):
        p = self.make()
        scope, _ = load_step(p, ["视频"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual(p.enter.call_args_list,
                         [call("我的"), call("设置"), call("个性化管理", scrolls=6)])
        self.assertEqual(scope["VERIFIED_SWITCHES"], 2)


class PageTextTests(unittest.TestCase):
    def test_page_text_joins_the_visible_texts(self):
        p = phone_stub("test", W=1080, H=2400)
        p.texts = Mock(return_value=[("我的", (0, 0, 1, 1), None), ("设置", (0, 2, 1, 3), None)])
        self.assertEqual(p.page_text(), "我的 / 设置")

    def test_page_text_is_empty_on_an_empty_page(self):
        p = phone_stub("test", W=1080, H=2400)
        p.texts = Mock(return_value=[])
        self.assertEqual(p.page_text(), "")


if __name__ == "__main__":
    unittest.main()
