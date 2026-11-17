"""渠道页的到达决策：六条路线与三条失败路径各自该发哪个意图、结局是什么。（#1435）

每条用例都是「喂页面 → 断言意图与结局」：路线与逐帧的下一步由 `channel_arrive` 的纯函数给，
这里用一台假手机看它落到哪个动作、这一趟怎么收场。意图取 `p.apply()` 收到的那一串
（`Screen.apply()` 是唯一执行点），结局取 `Reached` / `Unreached` / 抛出的异常，
读屏报错与断线另外经 `toggle()` 看记成了哪个结局。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import adb_link
import chan_fast as chan
import channel_arrive as arrive
import screen_snapshot as snap
from fixtures import phone_stub

DEEP_FOCUS = "com.android.settings/com.android.settings.Settings$ChannelNotificationSettingsActivity"
APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
VIVO_FOCUS = ("com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification"
              ".settings.channels.NotificationSettingsActivity")
PK, CID, NAME = "com.example.app", "promo", "营销通知"


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


# 渠道页：顶栏是渠道名，「允许通知」那一行带唯一开关
DEEP_PAGE = page(
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,381][1080,489]">'
    '<node class="android.widget.TextView" text="允许通知" bounds="[0,397][342,473]"/>'
    '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
    ' clickable="true" bounds="[876,381][1020,489]"/></node>',
)

# 应用通知页：渠道行是导航行，点进去才是渠道页
APP_PAGE = page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[60,720][700,800]"/></node>',
)

# 应用通知页：渠道行自带开关（内联布局）
INLINE_PAGE = page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[60,720][700,800]"/>'
    '<node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,720][1040,800]"/></node>',
)

# 两处同名、都带开关：无法判断哪一行是渠道
SAME_NAME_PAGE = page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[60,720][700,800]"/>'
    '<node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,720][1040,800]"/></node>',
    '<node clickable="true" bounds="[0,900][1080,1060]">'
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[60,920][700,1000]"/>'
    '<node class="android.widget.Switch" checkable="true" checked="false" bounds="[900,920][1040,1000]"/></node>',
)

CHANNELS = snap.ChannelList(channels={(PK, CID): snap.ChannelEntry(NAME, 3, False)},
                            app_off={PK: False}, locked=frozenset(), foreground=frozenset())


def phone(pages, focus=APP_FOCUS, **fields):
    """当前页在点击之后才换成下一页：同一页可以读很多次，最后一页一直重复。"""
    index = [0]

    def tree():
        return ET.fromstring(pages[min(index[0], len(pages) - 1)])

    def click(*_args):
        index[0] = min(index[0] + 1, len(pages) - 1)

    p = phone_stub("test", reader=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm = Mock()
    p.click = p.screen.click = Mock(side_effect=click)
    seen = iter(range(10 ** 6))
    p.screen.sig = Mock(side_effect=lambda: str(next(seen)))
    p.screen.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.screen.scroll = p.scroll
    p.screen.tree = tree
    p.conn.reader = Mock()
    p.conn.reader.shell.return_value = Mock(output="")
    p.apply = Mock(wraps=p.apply)
    for name, value in fields.items():
        setattr(p, name, value)
    return p


def intents(p):
    return [call.args[0] for call in p.apply.call_args_list]


def make_snapshot(page_xml, focus):
    return snap.snapshot_from_tree(ET.fromstring(page_xml), 1080, 2340, focus)


class RouteTests(unittest.TestCase):
    """六条路线：先走哪条、发哪些意图、最后停在哪。"""

    def test_a_real_id_goes_straight_to_the_channel_page(self):
        self.assertEqual(arrive.route(CHANNELS, None, pk=PK, cid=CID),
                         arrive.Route(arrive.DIRECT, (arrive.channel_intent(PK, CID),)))
        p = phone([DEEP_PAGE], focus=DEEP_FOCUS)
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID, channels=CHANNELS).open()
        self.assertEqual(intents(p), [arrive.channel_intent(PK, CID)])
        self.assertIsInstance(got, chan.Reached)
        self.assertEqual(got.switch[0], "允许通知")

    def test_a_blocked_deep_link_taps_the_row_on_the_app_page(self):
        p = phone([APP_PAGE, DEEP_PAGE], focus=DEEP_FOCUS)
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID, channels=CHANNELS).open()
        self.assertEqual(intents(p), [arrive.channel_intent(PK, CID), arrive.app_page_intent(PK),
                                      snap.Intent(snap.IntentKind.TAP, at=(380, 760))])
        self.assertEqual(p.click.call_args_list, [call(380, 760)])
        self.assertIsInstance(got, chan.Reached)
        self.assertEqual(got.switch[0], "允许通知")

    def test_an_inline_row_is_recognised_without_tapping(self):
        p = phone([INLINE_PAGE])
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID, channels=CHANNELS).open()
        self.assertEqual(intents(p), [arrive.channel_intent(PK, CID)])
        p.click.assert_not_called()
        self.assertIsInstance(got, chan.Reached)
        self.assertEqual(got.switch, (NAME, True, (970, 760)))

    def test_two_same_name_rows_are_abandoned_with_the_reason(self):
        p = phone([SAME_NAME_PAGE])
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID, channels=CHANNELS).open()
        p.click.assert_not_called()
        self.assertIsInstance(got, chan.Unreached)
        self.assertIn("同名 2 行", got.why)

    def test_a_truncated_id_sends_only_the_app_page_link(self):
        self.assertEqual(arrive.route(CHANNELS, None, pk=PK, cid="com.se..."),
                         arrive.Route(arrive.APP_PAGE, (arrive.app_page_intent(PK),)))
        p = phone([INLINE_PAGE])
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, "com.se...", channels=CHANNELS).open()
        self.assertEqual(intents(p), [arrive.app_page_intent(PK)])
        self.assertIsInstance(got, chan.Reached)
        self.assertEqual(got.switch[0], NAME)

    def test_the_same_activity_is_read_off_the_snapshot(self):
        # 渠道页与应用通知页是同一个 Activity（vivo）：深链到不了不一样的页面，只走应用通知页
        vivo = make_snapshot(INLINE_PAGE, VIVO_FOCUS)
        self.assertEqual(arrive.route(CHANNELS, vivo, pk=PK, cid=CID),
                         arrive.Route(arrive.APP_PAGE, (arrive.app_page_intent(PK),)))
        self.assertEqual(arrive.route(CHANNELS, None, pk=PK, cid=CID, vivo_seen=True),
                         arrive.Route(arrive.APP_PAGE, (arrive.app_page_intent(PK),)))
        p = phone([INLINE_PAGE])
        p.channel_session.vivo_seen = True
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID, channels=CHANNELS).open()
        self.assertEqual(intents(p), [arrive.app_page_intent(PK)])
        self.assertIsInstance(got, chan.Reached)


class FailureTests(unittest.TestCase):
    """三条失败路径：意图发到哪一步、结局是什么。"""

    def test_a_lock_screen_stops_the_arrival(self):
        p = phone([INLINE_PAGE])
        p.locked = Mock(return_value=True)
        with patch.object(chan.time, "sleep"), self.assertRaises(chan.ScreenLocked):
            chan.ChannelPage(p, NAME, PK, "com.se...", channels=CHANNELS).open()
        self.assertEqual(intents(p), [arrive.app_page_intent(PK)])
        p.click.assert_not_called()

    def toggled(self, p, error):
        """经 `toggle()` 看这一趟记成了哪个结局：读屏报错与断线在那里各有一档收容。"""
        p.screen.tree = Mock(side_effect=error)
        with patch.object(chan, "parse", return_value=({(PK, CID): (NAME, 3, False)}, {})), \
             patch.object(chan.time, "sleep"):
            return chan.toggle(p, PK, CID, False, NAME)

    def test_a_read_error_is_recorded_as_an_error(self):
        p = phone([DEEP_PAGE], focus=DEEP_FOCUS)
        got = self.toggled(p, RuntimeError("读屏请求超时"))
        self.assertEqual(got.kind, chan.ERROR)
        self.assertEqual(got.detail, "这一步没有完成：读屏请求超时")
        self.assertEqual(intents(p), [arrive.channel_intent(PK, CID)])

    def test_a_lost_link_is_raised_not_swallowed(self):
        p = phone([DEEP_PAGE], focus=DEEP_FOCUS)
        with self.assertRaises(adb_link.DeviceLost):
            self.toggled(p, adb_link.DeviceLost("probe 已断开"))
        self.assertEqual(intents(p), [arrive.channel_intent(PK, CID)])


if __name__ == "__main__":
    unittest.main()
