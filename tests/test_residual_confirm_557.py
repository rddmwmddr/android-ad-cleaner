"""#557: 一段跑完后确认框还挂在屏上时，后面的查找失败要说清是这个原因，
而不是只报「没找到」——读者会把它当成这一版没适配。

设备无关：页面与时钟都由 `fixtures.fake_phone()` 给，`say` 换成收集列表。
弹窗里只放确认键：没有 `DISMISS` 里的「取消」，`dismiss()` 也关不掉它，
这样「残留」才是这份夹具真的在演的场景。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import adb_link
import chan_fast
import fast
from fixtures import Clock, fake_phone, install_clock

SIZE = (1260, 2800)
CONFIRM_ONLY = ('<node class="android.widget.Button" content-desc="确认关闭" clickable="true" '
                'bounds="[308,2524][951,2665]"/>')
NOTE = "屏上还挂着没点掉的确认框「确认关闭」"


def page(body="", dialog=False):
    return ('<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]">'
            + body + (CONFIRM_ONLY if dialog else "") + "</node></hierarchy>")


def row(title, checked, top):
    return (f'<node bounds="[40,{top}][1100,{top + 142}]">'
            f'<node text="{title}" bounds="[40,{top}][700,{top + 142}]"/>'
            f'<node class="android.widget.Switch" checkable="true" checked="{checked}"'
            f' bounds="[984,{top}][1125,{top + 142}]"/></node>')


NOTIFY_BODY = row("允许通知", "true", 200) + row("横幅", "false", 352)
ENTERED_BODY = '<node text="服务管理" bounds="[40,200][700,342]"/>'


class ResidualConfirmTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, fast, "time", fast.time)
        self.clock = install_clock(fast, Clock())

    def phone(self, xml):
        self.lines = []
        return fake_phone(clock=self.clock, size=SIZE, stages=[(0.0, xml)],
                          say=lambda *a: self.lines.append(" ".join(str(x) for x in a)))

    def test_tap_failure_names_the_dialog(self):
        """tap() 的两句「没找到」：整页翻找与走丢后的快速放弃。"""
        for kwargs, miss, expected in (
            ({"scrolls": 0}, 0, "  ✗ 没找到「服务管理」——" + NOTE),
            ({"scrolls": 2}, 0, "  ✗ 没找到「服务管理」——" + NOTE),
            ({"scrolls": 6}, 1, "  ✗ 没找到「服务管理」（快速放弃）——" + NOTE),
        ):
            with self.subTest(**kwargs, miss=miss):
                p = self.phone(page(dialog=True))
                p.miss = miss
                self.assertFalse(p.tap("服务管理", **kwargs))
                self.assertEqual(self.lines[-1], expected)

    def test_enter_failure_names_the_dialog(self):
        """enter() 的两条 raise：入口没找到、点了页面没换。"""
        with self.subTest("没找到入口"):
            p = self.phone(page(dialog=True))
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertTrue(str(caught.exception).startswith(f"未找到入口「服务管理」；{NOTE}；当前页："))
            self.assertIn("  ✗ 没找到「服务管理」——" + NOTE, self.lines)
        with self.subTest("页面没有变化"):
            p = self.phone(page(ENTERED_BODY, dialog=True))
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertTrue(str(caught.exception).startswith(f"点「服务管理」后页面没有变化；{NOTE}；当前页："))

    def test_go_failure_names_the_dialog(self):
        p = self.phone(page(ENTERED_BODY, dialog=True))
        self.assertFalse(p.go("服务管理", "关于"))
        self.assertEqual(self.lines[-1], "  ✗ 点「服务管理」后没出现「关于」——" + NOTE)

    def test_channel_hint_names_the_dialog(self):
        """渠道页没认出时的结构摘要也要点名确认框：那一行「开关 2 个」正是被遮罩挡住的读法。"""
        p = self.phone(page(NOTIFY_BODY, dialog=True))
        self.assertEqual(chan_fast.page_hint(p, "小视频"),
                         "标题无，允许通知开关 1 个，开关 2 个；" + NOTE)

    def test_lost_link_still_raises(self):
        """断线不是「没有确认框」：诊断只吞读页失败，不吞断线（#293 的形态）。"""
        p = self.phone(page(dialog=True))
        p.tree = Mock(side_effect=adb_link.DeviceLost("设备已断开"))
        with self.assertRaises(adb_link.DeviceLost):
            p.residual_confirm()

    def test_without_dialog_output_is_unchanged(self):
        """六处的输出与改动前逐字一致：这条守的是不回退，改动前的树上也是绿的。"""
        for kwargs, miss, expected in (
            ({"scrolls": 0}, 0, "  ✗ 没找到「服务管理」"),
            ({"scrolls": 2}, 0, "  ✗ 没找到「服务管理」"),
            ({"scrolls": 6}, 1, "  ✗ 没找到「服务管理」（快速放弃）"),
        ):
            with self.subTest(**kwargs, miss=miss):
                p = self.phone(page())
                p.miss = miss
                self.assertFalse(p.tap("服务管理", **kwargs))
                self.assertEqual(self.lines[-1], expected)

        with self.subTest("没找到入口"):
            p = self.phone(page())
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertEqual(str(caught.exception), "未找到入口「服务管理」；当前页：")
            self.assertNotIn("确认框", "".join(self.lines))

        with self.subTest("页面没有变化"):
            p = self.phone(page(ENTERED_BODY))
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertEqual(str(caught.exception), "点「服务管理」后页面没有变化；当前页：服务管理")
            self.assertNotIn("确认框", "".join(self.lines))

        with self.subTest("go"):
            p = self.phone(page(ENTERED_BODY))
            self.assertFalse(p.go("服务管理", "关于"))
            self.assertEqual(self.lines[-1], "  ✗ 点「服务管理」后没出现「关于」")

        with self.subTest("渠道页"):
            p = self.phone(page(NOTIFY_BODY))
            self.assertEqual(chan_fast.page_hint(p, "小视频"), "标题无，允许通知开关 1 个，开关 2 个")


if __name__ == "__main__":
    unittest.main()
