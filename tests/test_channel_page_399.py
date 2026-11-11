"""#399 一次渠道到达收进 ChannelPage。四类目标分支（直达 / 应用通知页 / 内联 / 同名放弃）
与两条路线跳过（截断 ID、vivo）各一条守卫，断言它确实走到了那里。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
from fixtures import phone_stub

DEEP_FOCUS = "com.android.settings/com.android.settings.Settings$ChannelNotificationSettingsActivity"
APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
PK, CID, NAME = "com.example.app", "promo", "营销通知"


def phone(pages, focus=DEEP_FOCUS, w=1080, h=2340):
    """当前页在点击之后才换成下一页：同一页可以读很多次，最后一页一直重复。"""
    index = [0]

    def tree():
        return ET.fromstring(pages[min(index[0], len(pages) - 1)])

    def click(*_args):
        index[0] = min(index[0] + 1, len(pages) - 1)

    p = phone_stub("test", d=Mock())
    p.W, p.H = w, h
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm = Mock()
    p.click = Mock(side_effect=click)
    seen = iter(range(10 ** 6))
    p.screen.sig = Mock(side_effect=lambda: str(next(seen)))
    p.screen.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.screen.tree = tree
    p.reader = Mock()
    p.reader.shell.return_value = Mock(output="")
    return p


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

# 应用通知页：渠道行可点，点进去才是渠道页
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

# 华为 HarmonyOS 4 那种：列表里两处同名，都带开关，无法判断哪一行是渠道
SAME_NAME_PAGE = page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[60,720][700,800]"/>'
    '<node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,720][1040,800]"/></node>',
    '<node clickable="true" bounds="[0,900][1080,1060]">'
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[60,920][700,1000]"/>'
    '<node class="android.widget.Switch" checkable="true" checked="false" bounds="[900,920][1040,1000]"/></node>',
)


def shells(p):
    return [str(c) for c in p.reader.shell.call_args_list]


class ReachedTests(unittest.TestCase):
    def test_direct_link_reaches_the_channel_page(self):
        p = phone([DEEP_PAGE])
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID).open()
        self.assertIsInstance(got, chan.Reached)
        self.assertEqual(got.switch, ("允许通知", True, (948, 435)))
        self.assertTrue(any("CHANNEL_NOTIFICATION_SETTINGS" in c for c in shells(p)))
        p.click.assert_not_called()

    def test_blocked_direct_link_falls_back_to_the_app_page(self):
        # 深链没换成渠道页（第一屏还是应用通知页）：点这一行进去
        p = phone([APP_PAGE, DEEP_PAGE])
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID).open()
        self.assertIsInstance(got, chan.Reached)
        self.assertEqual(got.switch[0], "允许通知")
        p.click.assert_called_once_with(380, 760)

    def test_inline_row_on_the_app_page_is_used_without_clicking(self):
        p = phone([INLINE_PAGE], focus=APP_FOCUS)
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID).open()
        self.assertIsInstance(got, chan.Reached)
        self.assertEqual(got.switch, (NAME, True, (970, 760)))
        p.click.assert_not_called()

    def test_two_same_name_rows_are_refused_with_the_reason(self):
        p = phone([SAME_NAME_PAGE], focus=APP_FOCUS)
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID).open()
        self.assertIsInstance(got, chan.Unreached)
        self.assertIn("同名 2 行", got.why)          # 守卫：真的走到了「同名放弃」这一支
        p.click.assert_not_called()

    def test_refresh_does_not_navigate_again(self):
        # 点击循环每轮重取开关，不能重发深链
        p = phone([DEEP_PAGE])
        page_ = chan.ChannelPage(p, NAME, PK, CID)
        with patch.object(chan.time, "sleep"):
            page_.open()
            before = len(shells(p))
            page_.refresh(rounds=2)
        self.assertEqual(len(shells(p)), before)
        self.assertFalse(any("APP_NOTIFICATION_SETTINGS" in c for c in shells(p)))


class RouteTests(unittest.TestCase):
    def test_truncated_id_skips_the_direct_link(self):
        # 三星把长渠道 ID 缩略成 com.se...，不能拿去深链
        p = phone([INLINE_PAGE], focus=APP_FOCUS)
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, "com.se...").open()
        self.assertIsInstance(got, chan.Reached)
        self.assertFalse(any("CHANNEL_NOTIFICATION_SETTINGS" in c for c in shells(p)))

    def test_vivo_only_enters_from_the_app_page(self):
        p = phone([INLINE_PAGE], focus=APP_FOCUS)
        p.vivo_seen = True
        with patch.object(chan.time, "sleep"):
            got = chan.ChannelPage(p, NAME, PK, CID).open()
        self.assertIsInstance(got, chan.Reached)
        self.assertFalse(any("CHANNEL_NOTIFICATION_SETTINGS" in c for c in shells(p)))


class ToggleTests(unittest.TestCase):
    def test_unreached_page_is_reported_with_the_same_wording(self):
        # 给用户看的那一段逐字不变：未确认「名」渠道页及通知开关，跳过（停在 …；卡在哪一环）
        p = phone([SAME_NAME_PAGE], focus="com.vendor.notify/.UnknownPage")
        with patch.object(chan, "parse", return_value=({(PK, CID): (NAME, 3, False)}, {})), \
             patch.object(chan.time, "sleep"):
            outcome = chan.toggle(p, PK, CID, False, NAME)
        self.assertEqual(outcome.kind, chan.NOT_CONFIRMED)
        self.assertIn("停在 com.vendor.notify/.UnknownPage", outcome.detail)
        self.assertIn("未确认「营销通知」渠道页及通知开关，跳过", outcome.detail)
        p.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
