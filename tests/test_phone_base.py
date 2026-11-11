"""两个基座可以各自独立构造（ADR-0033、#1038）。

拆分之前，验一处读屏行为必须造整台 `Phone`；这两条用例守的是「不必」：`Connection` 注入一个
读屏 adapter 就能建起来，`Screen` 只认它，观测与四个动作原语（`click` / `back` / `settle` / `find`）
全都能在不认识门面的前提下驱动。

读屏替身走既有的 `reader=` 构造参数，不新发明装配。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
import fixtures  # noqa: E402

PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
    <node text="个性化广告推荐" bounds="[60,600][700,660]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,600][1040,660]"/>
    <node text="隐私" bounds="[60,900][400,960]"/>
  </node>
</hierarchy>"""

NEXT_PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
    <node text="下一个页面" bounds="[60,600][700,660]"/>
  </node>
</hierarchy>"""


class RecordingDevice(fixtures.Device):
    """假设备 + 命令流水：看 `back()` 到底发了什么。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands = []

    def shell(self, command, timeout=60):
        self.commands.append(command)
        return super().shell(command, timeout)


def base(stages=((0.0, PAGE),), size=(1080, 2340), clock=None):
    """(连接, 观测, 假设备, 假时钟)：只用构造参数注入读屏替身，不经过门面。"""
    clock = clock or fixtures.Clock()
    device = RecordingDevice(fixtures.Timeline(list(stages)), size, clock)
    conn = fast.Connection("test", log=False, reader=device)
    return conn, fast.Screen(conn), device, clock


class ScreenAloneTests(unittest.TestCase):
    """观测基座不认识门面：一个 `Connection` 就够了（用户故事 6）。"""

    def setUp(self):
        self.clock = fixtures.Clock()
        fixtures.install_clock(fast, self.clock)

    def test_page_can_be_read_without_a_phone(self):
        conn, screen, _, _ = base(clock=self.clock)
        self.assertEqual((screen.W, screen.H), (1080, 2340))          # 几何来自注入的连接
        self.assertEqual([t for t, _, _ in screen.texts()], ["个性化广告推荐", "隐私"])
        self.assertEqual([(t, on) for t, on, _ in screen.switches()], [("个性化广告推荐", True)])
        self.assertEqual(screen.sig(), "个性化广告推荐|隐私")

    def test_focus_and_diagnosis_come_from_the_connection(self):
        conn, screen, _, _ = base(clock=self.clock)
        self.assertEqual(screen.focus(), "")                           # 假设备没有前台：空串，不是异常
        where, detail = screen._page_diagnosis()
        self.assertEqual(where, "未知页面")
        self.assertIn("标题", detail)


class ActionPrimitiveTests(unittest.TestCase):
    """四个动作原语落在观测基座上，后续阶段一律经它们动作（#1038 的验收面）。"""

    def setUp(self):
        self.clock = fixtures.Clock()
        fixtures.install_clock(fast, self.clock)

    def test_the_four_primitives_live_on_the_screen(self):
        self.assertEqual({"click", "back", "settle", "find"} - set(vars(fast.Screen)), set())

    def test_find_gives_the_center_of_the_named_node(self):
        _, screen, _, _ = base(clock=self.clock)
        self.assertEqual(screen.find("隐私"), (230, 930))
        self.assertIsNone(screen.find("不存在的文字"))

    def test_click_rejects_coordinates_outside_the_screen(self):
        _, screen, device, _ = base(clock=self.clock)
        with self.assertRaisesRegex(RuntimeError, "屏幕外"):
            screen.click(5000, 100)
        self.assertEqual([c for c in device.commands if "input swipe" in c], [])

    def test_back_sends_the_key_event_and_waits(self):
        _, screen, device, _ = base(stages=[(0.0, PAGE), (0.2, NEXT_PAGE)], clock=self.clock)
        screen.back()
        self.assertIn("input keyevent BACK", device.commands)

    def test_settle_sees_the_next_page(self):
        _, screen, _, clock = base(stages=[(0.0, PAGE), (0.2, NEXT_PAGE)], clock=self.clock)
        self.assertTrue(screen.settle(screen.sig(), 1.0))
        self.assertLess(clock.time(), 1.0)


class ConnectionAloneTests(unittest.TestCase):
    """连接与生命周期可以单独持有：串号、断线、日志开关、关闭。"""

    def test_serial_and_lost_belong_to_the_connection(self):
        conn, _, _, _ = base()
        self.assertEqual(conn.serial, "test")
        self.assertFalse(conn.lost)
        conn.serial = "other"
        self.assertEqual(conn.link.serial, "other")
        conn.lost = True
        self.assertTrue(conn.lost)

    def test_say_follows_the_log_switch(self):
        conn, _, _, _ = base()
        with contextlib.redirect_stdout(io.StringIO()) as quiet:
            conn.say("安静")
        self.assertEqual(quiet.getvalue(), "")
        conn.log = True
        with contextlib.redirect_stdout(io.StringIO()) as loud:
            conn.say("说一句")
        self.assertEqual(loud.getvalue().strip(), "说一句")

    def test_close_closes_the_reader(self):
        conn, _, device, _ = base()
        conn.close()
        self.assertTrue(device.closed)


if __name__ == "__main__":
    unittest.main()
