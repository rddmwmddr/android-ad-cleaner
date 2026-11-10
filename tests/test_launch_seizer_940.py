"""#940：启动报错要留下「被谁抢了前台」。

抛错那一刻前台可能已经被抢回目标包（瞬时抢占：开屏、系统弹窗、桌面过渡帧），
重新读一次只看到目标包自己的页面。抢夺者只能在轮询里记下来。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
import recipe_kit
from fixtures import Clock, fake_phone, install_clock

PKG = "com.heytap.market"
APP = PKG + "/com.heytap.market.activity.MainActivity"
OTHER = "com.oplus.securitypermission/.XActivity"
LAUNCHER = "com.miui.home/.Launcher"

HOME = f'''<hierarchy rotation="0"><node package="{PKG}" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="应用商店" bounds="[60,100][400,180]"/>
</node></hierarchy>'''


def frames(*seq, tail=""):
    """焦点按帧给：seq 读完以后一直给 tail。轮询读几次就是几帧，不看挂钟。"""
    it = iter(seq)

    def focus():
        return next(it, tail)
    return focus


class LaunchSeizerTests(unittest.TestCase):
    def phone(self, focus=((0.0, ""),)):
        clock = Clock()
        original = fast.time
        install_clock(fast, clock)
        self.addCleanup(setattr, fast, "time", original)
        return fake_phone(clock=clock, stages=((0.0, HOME),), focus=focus)

    def test_transient_takeover_names_the_seizer_and_the_landing(self):
        """目标 → 别的包连续 3 帧 → 回到目标包：抢夺者与当前落点分开写。"""
        p = self.phone()
        p.focus = frames(APP, OTHER, OTHER, OTHER, APP)
        with self.assertRaises(RuntimeError) as caught:
            p.start(PKG, settle=0)
        msg = str(caught.exception)
        self.assertRegex(
            msg,
            r"离开前台.*被 com\.oplus\.securitypermission/\.XActivity 抢了前台，连续 3 帧"
            r".*当前停在 " + PKG.replace(".", r"\.") + r"/com\.heytap\.market\.activity\.MainActivity")
        # 机型脚本从报错里取落点判 dead_ends：多出「被谁抢了」那一句后仍要取到当前落点（#902 / #906）
        self.assertEqual(recipe_kit.LANDING.search(msg).group(1), PKG)

    def test_sustained_takeover_keeps_the_existing_wording(self):
        """目标 → 一直停在别的 App：落点已经写着抢夺者，不重复那一句。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        p.focus = frames(APP, tail=OTHER)
        with self.assertRaises(RuntimeError) as caught:
            p.start(PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn(f"（停在 {OTHER}；", msg)
        self.assertNotIn("抢了前台", msg)

    def test_unreadable_focus_never_names_a_seizer(self):
        """只读到空焦点：确知不了是谁，落点仍是「未知页面」，不写伪造的抢夺者。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        with self.assertRaises(RuntimeError) as caught:
            p.start(PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn("没有进入前台", msg)
        self.assertIn("停在 未知页面", msg)
        self.assertNotIn("抢了前台", msg)

    def test_single_foreign_frame_is_not_named_as_a_seizer(self):
        """启动时桌面闪一帧、之后一直读空：一两帧是过渡，不算确知（#581），不写抢夺者。
        旧树也绿，守的是不回退。"""
        p = self.phone(focus=((0.0, ""), (0.2, LAUNCHER), (0.4, "")))
        with self.assertRaises(RuntimeError) as caught:
            p.start(PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn("没有进入前台", msg)
        self.assertNotIn("抢了前台", msg)

    def test_alternating_foreign_apps_do_not_invent_a_run(self):
        """A → B → A：外来前台连读 3 帧才停段，但没有哪个包连占 3 帧，不把帧数记到某个包头上。
        旧树也绿，守的是不回退。"""
        p = self.phone()
        p.focus = frames(APP, OTHER, LAUNCHER, OTHER, APP)
        with self.assertRaises(RuntimeError) as caught:
            p.start(PKG, settle=0)
        msg = str(caught.exception)
        self.assertIn(f"停在 {APP}", msg)
        self.assertNotIn("抢了前台", msg)

    def test_never_entered_foreground_still_names_a_seizer_it_saw(self):
        """一直没进目标包、最后一帧又读空：之前记下的抢夺者仍要报出来（#940 的另一条短路）。"""
        p = self.phone(focus=((0.0, OTHER), (4.9, "")))
        with self.assertRaisesRegex(
                RuntimeError,
                r"没有进入前台.*被 com\.oplus\.securitypermission/\.XActivity 抢了前台，连续 \d+ 帧；"
                r"当前停在 未知页面"):
            p.start(PKG, settle=0)


if __name__ == "__main__":
    unittest.main()
