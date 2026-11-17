"""三个跨阶段会话对象（ADR-0033、沿用 #1039 的做法）：状态归对象，门面只留设备概念那几个。

钉的是脚本侧真在用的写法——置零（`p.miss = 0`）、换 App（`p.app = pkg`）、
读集合本体（`p.missed`）。其余字段直接读持有它的会话对象（`p.channel_session.*`），
门面上没有第二条访问路径（ADR-0045、#1479）；转发成拷贝会让集合类字段静默失效，所以
留下的那几个必须读回同一个对象。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import phone_stub  # noqa: E402


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_miss_writes_through_to_the_note(self):
        """`p.miss = 0` 在 6 份机型脚本（10 处）与 `recipe_kit`（1 处）里是赋值，不是只读属性。"""
        self.p.miss = 3
        self.assertEqual(self.p.lost_note.miss, 3)
        self.p.miss = 0
        self.assertEqual(self.p.lost_note.miss, 0)

    def test_app_writes_through_to_the_launch_session(self):
        self.p.app = "com.android.settings"
        self.assertEqual(self.p.launch_session.app, "com.android.settings")

    def test_changing_the_app_forgets_the_promoted_marks(self):
        """`honor` 的 `launch()` 只写 `p.app`：换 App 就该作废上一个 App 的推广位记忆（沿用 #420 的裁决、#1479）。"""
        self.p.app = "com.vivo.browser"
        self.p.launch_session.promoted.add(("com.vivo.browser", "close"))
        self.p.app = "com.heytap.themestore"
        self.assertEqual(self.p.launch_session.promoted, set())
        self.assertEqual(self.p.launch_session.app, "com.heytap.themestore")

    def test_the_launch_session_keeps_a_single_setter_for_that_invariant(self):
        """「换 App 就清空 promoted」只有 `LaunchSession.set_app()` 一份，别处不再各清一次。"""
        session = self.p.launch_session
        session.promoted.add(("com.android.settings", "close"))
        session.set_app("com.android.vending")
        self.assertEqual(session.promoted, set())

    def test_missed_is_the_live_list(self):
        self.assertIs(self.p.missed, self.p.lost_note.missed)
        self.p.missed.append(("系统·广告服务", "个性化推荐"))
        self.assertEqual(self.p.lost_note.missed, [("系统·广告服务", "个性化推荐")])

    def test_channel_fields_live_in_the_channel_session(self):
        session = self.p.channel_session
        session.vivo_seen = True
        session.skeleton_count = 1
        session.skeleton_sigs.add("sig")
        session.mismatch_probes = 2
        self.assertEqual((session.vivo_seen, session.skeleton_count, session.mismatch_probes),
                         (True, 1, 2))
        self.assertEqual(session.skeleton_sigs, {"sig"})

    def test_the_channel_fields_are_not_on_the_facade(self):
        for gone in ("vivo_seen", "skeleton_sigs", "skeleton_count", "mismatch_probes", "promoted"):
            with self.assertRaises(AttributeError):
                getattr(self.p, gone)

    def test_each_facade_gets_its_own_sessions(self):
        """两个 Phone 的丢失记录与推广位互不影响：会话对象是门面自己造的。"""
        other = phone_stub(W=1080, H=2340)
        self.p.miss = 1
        self.p.launch_session.promoted.add(("com.android.settings", "close"))
        self.assertEqual(other.miss, 0)
        self.assertEqual(other.launch_session.promoted, set())
        self.assertIsNot(self.p.lost_note, other.lost_note)


if __name__ == "__main__":
    unittest.main()
