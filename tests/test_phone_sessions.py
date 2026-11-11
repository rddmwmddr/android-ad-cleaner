"""三个跨阶段会话对象（ADR-0033、#1039）：门面用显式属性 + 赋值器转发过去。

钉的是脚本侧真在用的三种写法——置零（`p.miss = 0`）、赋值（`p.app = pkg`）、
清空集合（`p.promoted.clear()`）。转发成拷贝会让最后一种静默失效，所以集合必须读回同一个对象。
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

    def test_promoted_is_the_live_set(self):
        """`honor-CLE-AN00` 直接写 `p.promoted.clear()`：清空了才是真的清空。"""
        self.assertIs(self.p.promoted, self.p.launch_session.promoted)
        self.p.promoted.add(("com.vivo.browser", "close"))
        self.p.promoted.clear()
        self.assertEqual(self.p.launch_session.promoted, set())

    def test_missed_is_the_live_list(self):
        self.assertIs(self.p.missed, self.p.lost_note.missed)
        self.p.missed.append(("系统·广告服务", "个性化推荐"))
        self.assertEqual(self.p.lost_note.missed, [("系统·广告服务", "个性化推荐")])

    def test_channel_fields_live_in_the_channel_session(self):
        self.p.vivo_seen = True
        self.p.skeleton_count = 1
        self.p.skeleton_sigs.add("sig")
        self.p.mismatch_probes = 2
        session = self.p.channel_session
        self.assertEqual((session.vivo_seen, session.skeleton_count, session.mismatch_probes),
                         (True, 1, 2))
        self.assertEqual(session.skeleton_sigs, {"sig"})

    def test_each_facade_gets_its_own_sessions(self):
        """两个 Phone 的丢失记录与推广位互不影响：会话对象是门面自己造的。"""
        other = phone_stub(W=1080, H=2340)
        self.p.miss = 1
        self.p.promoted.add(("com.android.settings", "close"))
        self.assertEqual(other.miss, 0)
        self.assertEqual(other.promoted, set())
        self.assertIsNot(self.p.lost_note, other.lost_note)


if __name__ == "__main__":
    unittest.main()
