"""启动与落点阶段（`tool/phone/launcher.py`，ADR-0033）：`start()` 之后算不算到了目标 App。

三件事分开守：
  · 启动时的前台归属——读不出焦点不是「离开」，确知被别的 App 占了才停段（#581）；
  · 停段时的现场——被谁抢了前台、当前落在哪个页面，两者分开写（#940）；
  · 落点校验——给了期望文字就先确认落在那一页，落在开屏 / 推广页时退一次重来（#420）。

票号留在各用例的 docstring 首行；按票号 grep 仍能找到它。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adb_link  # noqa: E402
import fast  # noqa: E402
import recipe_kit  # noqa: E402
from fixtures import EMPTY_PAGE, Clock, clocked, fake_phone, phone_stub, stub  # noqa: E402

# ---------- #581：主题商店的前台归属 ----------
THEME_PKG = "com.miui.themestore"
THEME_APP = THEME_PKG + "/.MainActivity"
THEME_OTHER = "com.example.other/.Account"
THEME_MANAGER = "com.android.thememanager/.ThemeResourceProxyTabActivity"

THEME_HOME = f'''<hierarchy rotation="0"><node package="{THEME_PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="主题" bounds="[60,100][400,180]"/>
  <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
</node></hierarchy>'''

# ---------- #940：应用商店启动时报出抢夺者 ----------
MARKET_PKG = "com.heytap.market"
MARKET_APP = MARKET_PKG + "/com.heytap.market.activity.MainActivity"
MARKET_OTHER = "com.oplus.securitypermission/.XActivity"
MARKET_LAUNCHER = "com.miui.home/.Launcher"

MARKET_HOME = f'''<hierarchy rotation="0"><node package="{MARKET_PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="应用商店" bounds="[60,100][400,180]"/>
</node></hierarchy>'''


def frames(*seq, tail=""):
    """焦点按帧给：seq 读完以后一直给 tail。轮询读几次就是几帧，不看挂钟。"""
    it = iter(seq)

    def focus():
        return next(it, tail)
    return focus


# ---------- #420：应用商店的落点校验 ----------
def promo_page(n=17):
    """开屏推荐页：有文字、没有底栏（所以「我的」找不到）。"""
    rows = "".join(
        f'<node class="android.widget.TextView" text="推荐{i}款应用" '
        f'bounds="[60,{300 + i * 110}][900,{380 + i * 110}]"/>' for i in range(n))
    return ('<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">'
            f'{rows}</node></hierarchy>')


STORE_HOME = '''<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="应用商店" bounds="[60,100][600,180]"/>
  <node class="android.widget.TextView" text="首页" bounds="[60,2180][200,2260]"/>
  <node class="android.widget.TextView" text="应用" bounds="[260,2180][400,2260]"/>
  <node class="android.widget.TextView" text="游戏" bounds="[460,2180][600,2260]"/>
  <node class="android.widget.TextView" text="分类" bounds="[660,2180][800,2260]"/>
  <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
</node></hierarchy>'''

# 不是底栏、只是标题里含「我的」：不能当成落在主页
TITLE_PAGE = '''<hierarchy rotation="0"><node package="com.bbk.appstore" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="我的应用" bounds="[60,300][900,380]"/>
  <node class="android.widget.TextView" text="管理我的应用" bounds="[60,420][900,500]"/>
</node></hierarchy>'''

STORE_APP = "com.bbk.appstore/.Main"


class LaunchForegroundTests(unittest.TestCase):
    def phone(self, stages, focus, **fields):
        clock = Clock()
        clocked(self, fast, clock)
        p = fake_phone(clock=clock, stages=stages, focus=focus, **fields)
        return p, clock

    def test_empty_focus_while_the_window_paints_is_not_leaving(self):
        """#581 空格→目标包：过渡期读不出焦点照常等，不报「没有进入前台」。
        旧实现也能过（0.6 秒落在 5 秒预算内），守着的是这条基本路径不回退。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (0.6, THEME_HOME)],
                          focus=((0.0, ""), (0.6, THEME_APP)))
        p.start(THEME_PKG, settle=0)

    def test_empty_focus_after_entering_is_not_leaving(self):
        """#581 目标→空→目标：进过目标 App 之后短暂读不出，不是「启动后离开前台」。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (0.25, ""), (0.7, THEME_APP)))
        p.start(THEME_PKG, settle=1.2)

    def test_one_frame_in_another_app_is_not_leaving(self):
        """#581 目标→别的包 1 次→回到目标：跳包过渡帧不算被占住。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (0.25, THEME_OTHER), (0.7, THEME_APP)))
        p.start(THEME_PKG, settle=1.2)

    def test_jump_package_transition_is_not_leaving(self):
        """#581 主题商店 → 主题管理器的跳包过渡帧（报告者实测的形态）。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (0.3, THEME_MANAGER), (0.8, THEME_APP)))
        p.start(THEME_PKG, settle=1.2)

    def test_sustained_other_app_stops_the_step_with_the_landing_page(self):
        """#581 持续被别的 App 占住照样停段，报错带上落点（#547）。"""
        p, _ = self.phone([(0.0, THEME_HOME)], focus=((0.0, THEME_APP), (0.2, THEME_OTHER)))
        reads = []
        focus = p.screen.focus      # 取基座原来那个：门面的 focus 已经转到基座上，取门面会绕回自己
        p.screen.focus = lambda: (lambda v: (reads.append(v), v)[1])(focus())
        with self.assertRaisesRegex(RuntimeError,
                                    r"离开前台.*停在 com\.example\.other/\.Account"):
            p.start(THEME_PKG, settle=1.2)
        self.assertGreaterEqual(reads.count(THEME_OTHER), 3)      # 连续读到才算，不是一帧就停

    def test_six_seconds_of_unreadable_focus_still_reaches_the_app(self):
        """#581 空焦点持续 6 秒后出现目标包：不算超时（5 秒启动预算不计空焦点）。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (6.0, THEME_HOME)],
                          focus=((0.0, ""), (6.0, THEME_APP)))
        p.start(THEME_PKG, settle=0)

    def test_unreadable_focus_forever_fails_within_the_upper_bound(self):
        """#581 空焦点一直不出现目标包：有界失败，文案与原来一致，且是顺延到上限才放弃。
        旧实现在 5 秒就报错，这里要求等过 7 秒——空焦点不能提前花掉启动预算。"""
        p, clock = self.phone([(0.0, EMPTY_PAGE)], focus=((0.0, ""),))
        with self.assertRaisesRegex(RuntimeError, "没有进入前台"):
            p.start(THEME_PKG, settle=0)
        self.assertLessEqual(clock.t, 8.4)
        self.assertGreater(clock.t, 7.0)

    def test_other_app_taking_over_right_at_the_end_is_caught(self):
        """#581 settle 最后一拍之后才被别的 App 抢前台：收尾那次复核仍要读到并停段
        （d4ee2d2e 的保证）。"""
        p, _ = self.phone([(0.0, THEME_HOME)],
                          focus=((0.0, THEME_APP), (1.0, THEME_OTHER)))
        with self.assertRaisesRegex(RuntimeError, "离开前台"):
            p.start(THEME_PKG, settle=1.2)


class LaunchSeizerTests(unittest.TestCase):
    def phone(self, focus=((0.0, ""),)):
        clock = Clock()
        clocked(self, fast, clock)
        return fake_phone(clock=clock, stages=((0.0, MARKET_HOME),), focus=focus)

    def test_transient_takeover_names_the_seizer_and_the_landing(self):
        """#940 目标 → 别的包连续 3 帧 → 回到目标包：抢夺者与当前落点分开写。"""
        p = self.phone()
        p.screen.focus = frames(MARKET_APP, MARKET_OTHER, MARKET_OTHER, MARKET_OTHER, MARKET_APP)
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertRegex(
            msg,
            r"离开前台.*被 com\.oplus\.securitypermission/\.XActivity 抢了前台，连续 3 帧"
            r".*当前停在 " + MARKET_PKG.replace(".", r"\.")
            + r"/com\.heytap\.market\.activity\.MainActivity")
        # 机型脚本从报错里取落点判 dead_ends：多出「被谁抢了」那一句后仍要取到当前落点（#902 / #906）
        self.assertEqual(recipe_kit.LANDING.search(msg).group(1), MARKET_PKG)

    def test_sustained_takeover_keeps_the_existing_wording(self):
        """#940 目标 → 一直停在别的 App：落点已经写着抢夺者，不重复那一句。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        p.screen.focus = frames(MARKET_APP, tail=MARKET_OTHER)
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn(f"（停在 {MARKET_OTHER}；", msg)
        self.assertNotIn("抢了前台", msg)

    def test_unreadable_focus_never_names_a_seizer(self):
        """#940 只读到空焦点：确知不了是谁，落点仍是「未知页面」，不写伪造的抢夺者。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn("没有进入前台", msg)
        self.assertIn("停在 未知页面", msg)
        self.assertNotIn("抢了前台", msg)

    def test_single_foreign_frame_is_not_named_as_a_seizer(self):
        """#940 启动时桌面闪一帧、之后一直读空：一两帧是过渡，不算确知（#581），不写抢夺者。
        旧树也绿，守的是不回退。"""
        p = self.phone(focus=((0.0, ""), (0.2, MARKET_LAUNCHER), (0.4, "")))
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn("没有进入前台", msg)
        self.assertNotIn("抢了前台", msg)

    def test_alternating_foreign_apps_do_not_invent_a_run(self):
        """#940 A → B → A：外来前台连读 3 帧才停段，但没有哪个包连占 3 帧，不把帧数记到某个包头上。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        p.screen.focus = frames(MARKET_APP, MARKET_OTHER, MARKET_LAUNCHER, MARKET_OTHER, MARKET_APP)
        with self.assertRaises(RuntimeError) as caught:
            p.start(MARKET_PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn(f"停在 {MARKET_APP}", msg)
        self.assertNotIn("抢了前台", msg)

    def test_never_entered_foreground_still_names_a_seizer_it_saw(self):
        """#940 一直没进目标包、最后一帧又读空：之前记下的抢夺者仍要报出来（#940 的另一条短路）。"""
        p = self.phone(focus=((0.0, MARKET_OTHER), (4.9, "")))
        with self.assertRaisesRegex(
                RuntimeError,
                r"没有进入前台.*被 com\.oplus\.securitypermission/\.XActivity 抢了前台，连续 \d+ 帧；"
                r"当前停在 未知页面"):
            p.start(MARKET_PKG, settle=0)


class LandingTests(unittest.TestCase):
    """启动后的落点校验（判据由调用方给）。"""

    def phone(self, stages, focus=((0.0, STORE_APP),), **fields):
        clock = Clock()
        clocked(self, fast, clock)
        return fake_phone(clock=clock, stages=stages, focus=focus, **fields), clock

    def test_promo_page_is_left_before_looking_for_entries(self):
        """#420 落在开屏推广页：退一次回到主页后才去点「我的」。"""
        p, clock = self.phone([(0.0, promo_page()), (30.0, STORE_HOME)])
        stub(p, "back", lambda *a, **k: setattr(clock, "t", 30.0))   # 推广页不会自己消失，返回一次才回主页
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertTrue(p.tap("我的", exact=True, scrolls=0))

    def test_without_expect_the_promo_page_is_searched_until_timeout(self):
        """#420 对照（改前行为）：不给判据就不知道落在推广页，入口探测在推广页里翻满 6 秒才放弃。"""
        p, clock = self.phone([(0.0, promo_page()), (30.0, STORE_HOME)])
        p.start("com.bbk.appstore", settle=0)
        self.assertFalse(p.tap("我的", exact=True, scrolls=0))
        self.assertGreaterEqual(clock.t, 6.0)

    def test_promo_page_that_never_goes_away_fails_with_diagnostics(self):
        """#420 推广页始终不消失：有界失败，日志写清停在哪、期望什么、实际结构，不打印页面文字。"""
        p, clock = self.phone([(0.0, promo_page())])
        lines = []
        stub(p, "say", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))
        with self.assertRaisesRegex(RuntimeError, "非预期页面"):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        out = "\n".join(lines)
        self.assertEqual(out.count("启动后没落在预期页面"), 2)   # 恢复前一次、结束前一次
        self.assertIn(STORE_APP, out)                 # 停在哪个前台
        self.assertIn("我的", out)                    # 期望看到什么
        self.assertIn("标题", out)                    # 实际页面结构摘要
        self.assertNotIn("推荐0款应用", out)          # 不打印页面文字
        self.assertLess(clock.t, 20)                  # 不再把时间走满
        self.assertIn("推荐0款应用", [t for t, _, _ in p.texts()])   # 守卫：页面里真有这些文字

    def test_recovery_relaunches_when_back_leaves_the_app(self):
        """#420 返回把 App 退到后台：重新拉起一次，仍按判据确认落点。"""
        p, clock = self.phone(
            [(0.0, promo_page()), (30.0, STORE_HOME)],
            focus=((0.0, STORE_APP), (30.0, "com.android.launcher/.Launcher"), (31.0, STORE_APP)))
        p.d.app_stop = Mock()
        stub(p, "back", lambda *a, **k: setattr(clock, "t", 30.0))
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertEqual(p.d.app_stop.call_count, 2)  # 首次拉起 + 返回后重拉
        self.assertTrue(p.tap("我的", exact=True, scrolls=0))

    def test_expected_page_needs_no_recovery(self):
        """#420 已经在期望的页面上：不返回、不点击。"""
        p, clock = self.phone([(0.0, STORE_HOME)])
        p.start("com.bbk.appstore", settle=0, expect=("首页", "应用", "游戏", "分类", "我的"))
        self.assertEqual(clock.clicks, 0)             # 没有返回、没有点击

    def test_landing_failure_only_presses_back_and_never_taps(self):
        """#420 恢复只发一次返回，不在陌生页面上猜着点。"""
        p, _ = self.phone([(0.0, promo_page())])
        click, back = Mock(), Mock()
        stub(p, "click", click)
        stub(p, "back", back)
        with self.assertRaises(RuntimeError):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        back.assert_called_once()
        click.assert_not_called()

    def test_blank_page_is_not_treated_as_a_promo_page(self):
        """#420 页面重绘成空白（还没画完）时不按返回：空白不等于推广页。"""
        p, _ = self.phone([(0.0, promo_page()), (2.0, EMPTY_PAGE)])
        back = Mock()
        stub(p, "back", back)
        with self.assertRaises(RuntimeError):
            p.start("com.bbk.appstore", settle=0, expect=("我的",))
        back.assert_not_called()

    def test_a_string_criterion_is_not_split_into_characters(self):
        """#420 单个字符串判据按整词算，不拆成一个个字。"""
        p, _ = self.phone([(0.0, STORE_HOME)])
        self.assertEqual(p.expect_hits("我的"), ["我的"])

    def test_a_title_that_starts_with_the_word_is_not_the_tab(self):
        """#420「我的应用」不是底栏「我的」：判据要停在文字开头或分隔符上。"""
        p, _ = self.phone([(0.0, TITLE_PAGE)])
        self.assertIn("我的应用", [t for t, _, _ in p.texts()])   # 守卫：页面里确实有这个词
        self.assertFalse(p.expect_page("我的", timeout=0.4))

    def test_promoted_keys_are_reset_on_start(self):
        """#420 每次启动清空「点过的推广位」：同一个 App 的新一轮不再沿用上一轮的豁免。"""
        p, _ = self.phone([(0.0, STORE_HOME)])
        p.promoted = {("com.bbk.appstore", "关闭")}
        p.start("com.bbk.appstore", settle=0, expect=("我的",))
        self.assertEqual(p.promoted, set())

    def test_device_lost_while_waiting_for_the_landing_page_is_raised(self):
        """#420 等落点时设备掉线：抛 DeviceLost，不当作「没落在预期页面」。"""
        p = phone_stub("test", d=Mock())
        p.W, p.H = 1080, 2340
        p.lost = True
        with self.assertRaises(adb_link.DeviceLost):
            p.expect_page("我的", timeout=1)


if __name__ == "__main__":
    unittest.main()
