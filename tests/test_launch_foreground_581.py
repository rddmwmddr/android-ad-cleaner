"""#581：冷启动时读不出前台（`mCurrentFocus=null`）不是「被别的 App 抢了前台」。

主题商店这类启动慢的 App 会在过渡期给出空焦点，甚至先跳到同厂商的另一个包再回到目标包。
两条判据因此分开：读不出 = 不知道，继续等；确知是别的 App、且连着读到几次，才停段。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import EMPTY_PAGE, Clock, fake_phone, install_clock

PKG = "com.miui.themestore"
APP = PKG + "/.MainActivity"
OTHER = "com.example.other/.Account"
THEME = "com.android.thememanager/.ThemeResourceProxyTabActivity"

HOME = f'''<hierarchy rotation="0"><node package="{PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="主题" bounds="[60,100][400,180]"/>
  <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
</node></hierarchy>'''


class LaunchForegroundTests(unittest.TestCase):
    def phone(self, stages, focus, **fields):
        clock = Clock()
        original = fast.time
        install_clock(fast, clock)
        self.addCleanup(setattr, fast, "time", original)
        p = fake_phone(clock=clock, stages=stages, focus=focus, **fields)
        return p, clock

    def test_empty_focus_while_the_window_paints_is_not_leaving(self):
        """空格→目标包：过渡期读不出焦点照常等，不报「没有进入前台」。
        旧实现也能过（0.6 秒落在 5 秒预算内），守着的是这条基本路径不回退。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (0.6, HOME)], focus=((0.0, ""), (0.6, APP)))
        p.start(PKG, settle=0)

    def test_empty_focus_after_entering_is_not_leaving(self):
        """目标→空→目标：进过目标 App 之后短暂读不出，不是「启动后离开前台」。"""
        p, _ = self.phone([(0.0, HOME)],
                          focus=((0.0, APP), (0.25, ""), (0.7, APP)))
        p.start(PKG, settle=1.2)

    def test_one_frame_in_another_app_is_not_leaving(self):
        """目标→别的包 1 次→回到目标：跳包过渡帧不算被占住。"""
        p, _ = self.phone([(0.0, HOME)],
                          focus=((0.0, APP), (0.25, OTHER), (0.7, APP)))
        p.start(PKG, settle=1.2)

    def test_jump_package_transition_is_not_leaving(self):
        """主题商店 → 主题管理器的跳包过渡帧（报告者实测的形态）。"""
        p, _ = self.phone([(0.0, HOME)],
                          focus=((0.0, APP), (0.3, THEME), (0.8, APP)))
        p.start(PKG, settle=1.2)

    def test_sustained_other_app_stops_the_step_with_the_landing_page(self):
        """持续被别的 App 占住照样停段，报错带上落点（#547）。"""
        p, _ = self.phone([(0.0, HOME)], focus=((0.0, APP), (0.2, OTHER)))
        reads = []
        focus = p.focus
        p.focus = lambda: (lambda v: (reads.append(v), v)[1])(focus())
        with self.assertRaisesRegex(RuntimeError, r"离开前台.*停在 com\.example\.other/\.Account"):
            p.start(PKG, settle=1.2)
        self.assertGreaterEqual(reads.count(OTHER), 3)      # 连续读到才算，不是一帧就停

    def test_six_seconds_of_unreadable_focus_still_reaches_the_app(self):
        """空焦点持续 6 秒后出现目标包：不算超时（5 秒启动预算不计空焦点）。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (6.0, HOME)], focus=((0.0, ""), (6.0, APP)))
        p.start(PKG, settle=0)

    def test_unreadable_focus_forever_fails_within_the_upper_bound(self):
        """空焦点一直不出现目标包：有界失败，文案与原来一致，且是顺延到上限才放弃。
        旧实现在 5 秒就报错，这里要求等过 7 秒——空焦点不能提前花掉启动预算。"""
        p, clock = self.phone([(0.0, EMPTY_PAGE)], focus=((0.0, ""),))
        with self.assertRaisesRegex(RuntimeError, "没有进入前台"):
            p.start(PKG, settle=0)
        self.assertLessEqual(clock.t, 8.4)
        self.assertGreater(clock.t, 7.0)

    def test_other_app_taking_over_right_at_the_end_is_caught(self):
        """settle 最后一拍之后才被别的 App 抢前台：收尾那次复核仍要读到并停段（d4ee2d2e 的保证）。"""
        p, _ = self.phone([(0.0, HOME)], focus=((0.0, APP), (1.0, OTHER)))
        with self.assertRaisesRegex(RuntimeError, "离开前台"):
            p.start(PKG, settle=1.2)


if __name__ == "__main__":
    unittest.main()
