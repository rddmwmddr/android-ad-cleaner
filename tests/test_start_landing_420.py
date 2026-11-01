"""#420：应用商店的开屏推荐页挡路。

两件事分开守：
  启动后要校验落点 —— 落在开屏 / 推广页时不在里面翻找入口，退一次重来，仍有界失败；
  关弹窗点到推广位 —— 点完跳到了别的 App 就退回来，这一次不算关掉了弹窗。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import Clock, fake_phone, install_clock, phone_stub


def promo_page(n=17):
    """开屏推荐页：有文字、没有底栏（所以「我的」找不到）。"""
    rows = "".join(
        f'<node class="android.widget.TextView" text="推荐{i}款应用" '
        f'bounds="[60,{300 + i * 110}][900,{380 + i * 110}]"/>' for i in range(n))
    return ('<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">'
            f'{rows}</node></hierarchy>')


HOME = '''<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="应用商店" bounds="[60,100][600,180]"/>
  <node class="android.widget.TextView" text="首页" bounds="[60,2180][200,2260]"/>
  <node class="android.widget.TextView" text="应用" bounds="[260,2180][400,2260]"/>
  <node class="android.widget.TextView" text="游戏" bounds="[460,2180][600,2260]"/>
  <node class="android.widget.TextView" text="分类" bounds="[660,2180][800,2260]"/>
  <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
</node></hierarchy>'''

# 浮层里的 ✕（不在滚动列表里，dismiss 会点它），列表里是正常内容
POPUP = '''<hierarchy><node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,0][1272,2772]">
  <node text="首页" bounds="[100,300][600,400]"/></node>
  <node class="android.widget.FrameLayout" bounds="[100,600][1172,2000]">
    <node content-desc="关闭" clickable="true" bounds="[1050,620][1150,720]"/></node></hierarchy>'''

APP = "com.bbk.appstore/.Main"


class LandingTests(unittest.TestCase):
    """启动后的落点校验（判据由调用方给）。"""

    def phone(self, stages, focus=((0.0, APP),), **fields):
        clock = Clock()
        original = fast.time
        install_clock(fast, clock)
        self.addCleanup(setattr, fast, "time", original)
        return fake_phone(clock=clock, stages=stages, focus=focus, **fields), clock

    def test_promo_page_is_left_before_looking_for_entries(self):
        """落在开屏推广页：退一次回到主页后才去点「我的」（#420）。"""
        p, clock = self.phone([(0.0, promo_page()), (30.0, HOME)])
        p.back = lambda *a, **k: setattr(clock, "t", 30.0)   # 推广页不会自己消失，返回一次才回主页
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertTrue(p.tap("我的", exact=True, scrolls=0))

    def test_without_expect_the_promo_page_is_searched_until_timeout(self):
        """对照（改前行为）：不给判据就不知道落在推广页，入口探测在推广页里翻满 6 秒才放弃。"""
        p, clock = self.phone([(0.0, promo_page()), (30.0, HOME)])
        p.start("com.bbk.appstore", settle=0)
        self.assertFalse(p.tap("我的", exact=True, scrolls=0))
        self.assertGreaterEqual(clock.t, 6.0)

    def test_promo_page_that_never_goes_away_fails_with_diagnostics(self):
        """推广页始终不消失：有界失败，日志写清停在哪、期望什么、实际页面结构，不打印页面文字。"""
        p, clock = self.phone([(0.0, promo_page())])
        lines = []
        p.say = lambda *a, **k: lines.append(" ".join(str(x) for x in a))
        with self.assertRaisesRegex(RuntimeError, "非预期页面"):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        out = "\n".join(lines)
        self.assertIn(APP, out)                       # 停在哪个前台
        self.assertIn("我的", out)                    # 期望看到什么
        self.assertIn("标题", out)                    # 实际页面结构摘要
        self.assertNotIn("推荐0款应用", out)          # 不打印页面文字
        self.assertLess(clock.t, 20)                  # 不再把时间走满
        self.assertIn("推荐0款应用", [t for t, _, _ in p.texts()])   # 守卫：页面里真有这些文字

    def test_recovery_relaunches_when_back_leaves_the_app(self):
        """返回把 App 退到后台：重新拉起一次，仍按判据确认落点。"""
        p, clock = self.phone(
            [(0.0, promo_page()), (30.0, HOME)],
            focus=((0.0, APP), (30.0, "com.android.launcher/.Launcher"), (31.0, APP)))
        p.back = lambda *a, **k: setattr(clock, "t", 30.0)
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertTrue(p.tap("我的", exact=True, scrolls=0))

    def test_expected_page_needs_no_recovery(self):
        p, clock = self.phone([(0.0, HOME)])
        p.start("com.bbk.appstore", settle=0, expect=("首页", "应用", "游戏", "分类", "我的"))
        self.assertEqual(clock.clicks, 0)             # 没有返回、没有点击

    def test_landing_failure_only_presses_back_and_never_taps(self):
        """恢复只发返回，不在陌生页面上猜着点（安全模式下的同一约束）。"""
        p, _ = self.phone([(0.0, promo_page())])
        p.safe_mode = True
        p.click = Mock()
        with self.assertRaises(RuntimeError):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        p.click.assert_not_called()


class PromotedClickTests(unittest.TestCase):
    """dismiss 的 ✕ 分支：点完跳到了别的 App 就退回来。"""

    def phone(self, focus):
        p = phone_stub("test", d=Mock())
        p.W, p.H = 1272, 2772
        p.tree = Mock(return_value=ET.fromstring(POPUP))
        p.focus = Mock(side_effect=list(focus))
        p.click = Mock()
        p.back = Mock()
        p.say = Mock()
        return p

    def test_close_icon_that_leads_to_another_app_is_undone(self):
        p = self.phone(["com.heytap.market/.Main", "com.kuaishou.nebula/.Splash",
                        "com.heytap.market/.Main"])
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())            # 不算关掉了弹窗
        p.back.assert_called_once()
        p.click.assert_called_once_with(1100, 670)
        said = " ".join(" ".join(map(str, c.args)) for c in p.say.call_args_list)
        self.assertIn("疑似推广位", said)
        self.assertIn("com.kuaishou.nebula", said)

    def test_promoted_close_icon_is_not_clicked_again(self):
        """同一个推广位只点一次：退回来以后不再接着点它。"""
        p = self.phone(["com.heytap.market/.Main", "com.kuaishou.nebula/.Splash",
                        "com.heytap.market/.Main"] * 2)
        with patch.object(fast.time, "sleep"):
            self.assertIsNone(p.dismiss())
            self.assertIsNone(p.dismiss())
        self.assertEqual(p.click.call_count, 1)

    def test_close_icon_without_leaving_the_app_keeps_the_output(self):
        """前台没变：返回值、点击坐标与日志逐字不变。"""
        p = self.phone(["com.heytap.market/.Main"] * 2)
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        p.click.assert_called_once_with(1100, 670)
        p.back.assert_not_called()
        self.assertEqual([c.args[0] for c in p.say.call_args_list], ["  · 弹窗点了 ✕（关闭）"])

    def test_unreadable_foreground_after_click_is_not_a_promotion(self):
        """点击后读不到前台：不知道去了哪，不当作推广位，也不回退。"""
        p = self.phone(["com.heytap.market/.Main", ""])
        with patch.object(fast.time, "sleep"):
            self.assertEqual(p.dismiss(), "✕")
        p.back.assert_not_called()


if __name__ == "__main__":
    unittest.main()
