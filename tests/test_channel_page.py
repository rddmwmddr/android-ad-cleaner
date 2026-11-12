"""渠道页：从哪条路走进去、认出的是不是渠道页、从哪一行拿开关。不用手机。

认页与找行都收在这一份。起点是 #399 的四类目标分支（直达 / 应用通知页 / 内联 / 同名放弃）
与两条路线跳过（截断 ID、vivo）；并入的还有 vivo 无 resource-id 顶栏（#336）、ColorOS 11/12
的通知宿主（#415）、「应用通知页没有打开」的点名（#422）、重复节点算同一行（#510）、
认不出时上报的脱敏骨架（#428）与繁体界面的认页（#498）。
拨完之后怎么记、怎么报不在这一份，见 test_channel_outcomes.py。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import chan_fast as chan
import events
import row
from fixtures import job_stub, phone_stub
from gui import app

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


# ---- vivo_336_chan_page ----
# #336 vivo V1986A（Funtouch 13 / Android 12）chan-off 全部跳过。
#
# 这台机器的通知页宿主是 com.android.systemui，渠道页顶栏是一个没有 resource-id 的 TextView，
# 渠道行在应用通知页的「类别」分组下面、首屏看不到。样本按报告者 2026-10-30 的真机 dump 造：
# 渠道页顶栏 [0,111][1080,360]、向上导航 [24,168][156,300]、「允许通知」[0,397][342,473] 与开关 [876,381][1020,489]。


VIVO_FOCUS = ("com.android.systemui/com.vivo.systemui.statusbar.notification"
              ".settings.channels.NotificationSettingsActivity")
VIVO_APP = "快手极速版"
VIVO_CHANNEL = "运营消息"        # 报告里被跳过的那一个
VIVO_NAME = "优质内容推送"       # 渠道页 dump 里的那一个


def vivo_phone(pages, w=1080, h=2340):
    """pages：依次返回的页面，最后一页一直重复。每次读屏的文字签名都不同，相当于页面真的翻动了。"""
    p = phone_stub("test", d=Mock())
    p.W, p.H = w, h
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=VIVO_FOCUS)
    p.confirm, p.click = Mock(), Mock()
    pages_seen = iter(range(10 ** 6))
    p.screen.sig = Mock(side_effect=lambda: str(next(pages_seen)))
    p.screen.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    queue = [ET.fromstring(x) for x in pages]
    p.screen.tree = Mock(side_effect=lambda: queue.pop(0) if len(queue) > 1 else queue[0])
    return p


def vivo_page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.systemui" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


# 渠道页：顶栏没有 resource-id（dump 里就是一段横跨整屏的普通 TextView）
VIVO_CHANNEL_PAGE = vivo_page(
    '<node class="android.widget.TextView" text="优质内容推送" bounds="[0,111][1080,360]"/>',
    '<node class="android.widget.Button" content-desc="向上导航" bounds="[24,168][156,300]"/>',
    '<node clickable="true" bounds="[0,381][1080,489]">'
    '<node class="android.widget.TextView" text="允许通知" bounds="[0,397][342,473]"/>'
    '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
    ' clickable="true" bounds="[876,381][1020,489]"/></node>',
    '<node class="android.widget.TextView" text="接受智能通知控制" bounds="[0,547][582,623]"/>',
    '<node class="android.widget.TextView" text="重要程度" bounds="[0,644][342,720]"/>',
)

VIVO_APP_PAGE = vivo_page(
    '<node class="android.widget.TextView" text="快手极速版" bounds="[0,111][1080,360]"/>',
    '<node class="android.widget.Button" content-desc="向上导航" bounds="[24,168][156,300]"/>',
    '<node clickable="true" bounds="[0,381][1080,489]">'
    '<node class="android.widget.TextView" text="允许通知" bounds="[0,397][342,473]"/>'
    '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
    ' clickable="true" bounds="[876,381][1020,489]"/></node>',
    '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,520][1080,2280]">'
    '<node class="android.widget.TextView" text="类别" bounds="[0,540][400,616]"/>'
    '<node class="android.widget.TextView" text="其他" bounds="[0,660][400,736]"/></node>',
)

VIVO_ROW = ('<node clickable="true" bounds="[0,{t}][1080,{b}]">'
       '<node class="android.widget.TextView" text="%s" bounds="[60,{t2}][600,{b2}]"/>'
       '<node class="android.widget.CheckBox" checkable="true" checked="true" bounds="[876,{t}][1020,{b}]"/></node>')


def vivo_app_page_with_row(y=700, scrollable=True, title='<node class="android.widget.TextView" text="快手极速版"'
                                                   ' bounds="[0,111][1080,360]"/>'):
    """应用通知页，「类别」下面多一行渠道行。y 传 2500 把它放到屏外；
    scrollable=False 造「列表没标可滚动」的页面；title 传空串造滚动后顶栏已收起的页面。"""
    row = (VIVO_ROW % VIVO_NAME).format(t=y, b=y + 156, t2=y + 30, b2=y + 106)
    return vivo_page(
        title,
        '<node class="android.widget.Button" content-desc="向上导航" bounds="[24,168][156,300]"/>',
        '<node clickable="true" bounds="[0,381][1080,489]">'
        '<node class="android.widget.TextView" text="允许通知" bounds="[0,397][342,473]"/>'
        '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
        ' clickable="true" bounds="[876,381][1020,489]"/></node>',
        '<node class="androidx.recyclerview.widget.RecyclerView"%s bounds="[0,520][1080,2280]">'
        % (' scrollable="true"' if scrollable else '')
        + '<node class="android.widget.TextView" text="类别" bounds="[0,540][400,616]"/>'
        + row + "</node>",
    )


class VivoTopTitleTests(unittest.TestCase):
    def test_toolbar_id_wins_when_it_is_there(self):
        xml = VIVO_CHANNEL_PAGE.replace(
            'class="android.widget.TextView" text="优质内容推送" bounds="[0,111][1080,360]"',
            'class="android.widget.TextView" resource-id="com.vivo.systemuiplugin:id/originui_vtoolbar_normal_title"'
            ' text="优质内容推送" bounds="[0,111][1080,360]"')
        p = vivo_phone([xml])
        self.assertEqual(chan.top_title(p, p.tree()), "优质内容推送")

    def test_title_without_resource_id_is_read_by_geometry(self):
        p = vivo_phone([VIVO_CHANNEL_PAGE])
        self.assertEqual(chan.top_title(p, p.tree()), "优质内容推送")

    def test_narrow_top_text_is_not_a_title(self):
        # 顶栏只有「向上导航」这种窄控件时不能当标题：认错就会拿它去比渠道名
        xml = vivo_page('<node class="android.widget.Button" content-desc="向上导航" bounds="[24,168][156,300]"/>')
        p = vivo_phone([xml])
        self.assertIsNone(chan.top_title(p, p.tree()))

    def test_text_below_the_header_band_is_not_a_title(self):
        xml = vivo_page('<node class="android.widget.TextView" text="允许通知" bounds="[0,397][1080,473]"/>')
        p = vivo_phone([xml])
        self.assertIsNone(chan.top_title(p, p.tree()))


class VivoChannelPageTests(unittest.TestCase):
    def test_channel_page_without_toolbar_id_is_operated(self):
        p = vivo_phone([VIVO_CHANNEL_PAGE])
        at = chan.Attempt(vivo_app=VIVO_APP)
        self.assertEqual(chan.channel_switch(p, "优质内容推送", at), ("允许通知", True, (948, 435)))

    def test_wait_page_recognises_the_same_page(self):
        p = vivo_phone([VIVO_CHANNEL_PAGE])
        p.vivo_seen = True                  # 已经走过应用通知页
        with patch.object(chan.time, "sleep"):
            sw = chan.wait_page(p, VIVO_NAME, chan.Attempt(vivo_app=VIVO_APP))
        self.assertEqual(sw[2], (948, 435))

    def test_half_width_row_label_is_not_a_title(self):
        # 「允许通知」那一行横跨半屏；把它当顶栏标题，就会拿应用总开关当渠道开关
        xml = vivo_page(
            '<node class="android.widget.TextView" text="营销通知" bounds="[100,120][600,200]"/>',
            '<node clickable="true" bounds="[0,300][1080,410]">'
            '<node class="android.widget.TextView" text="允许通知" bounds="[60,320][600,390]"/>'
            '<node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/></node>')
        p = vivo_phone([xml])
        self.assertIsNone(chan.channel_switch(p, "允许通知", chan.Attempt(vivo_app="示例应用")))

    def test_other_channel_name_is_still_refused(self):
        # 顶栏是别的渠道名：认页仍要说不，心态是「宁可跳过」
        p = vivo_phone([VIVO_CHANNEL_PAGE])
        self.assertIsNone(chan.channel_switch(p, VIVO_CHANNEL, chan.Attempt(vivo_app=VIVO_APP)))

    def test_app_page_is_still_refused_when_title_matches_the_app(self):
        # 应用总页顶栏是 App 名；哪怕渠道名恰好相同也不认（否则关的是整个 App 的通知）
        p = vivo_phone([VIVO_APP_PAGE])
        self.assertIsNone(chan.channel_switch(p, VIVO_APP, chan.Attempt(vivo_app=VIVO_APP)))

    def test_unrecognised_page_is_reported_not_clicked(self):
        p = vivo_phone([VIVO_CHANNEL_PAGE])
        with patch.object(chan, "parse", return_value=({("com.kuaishou.nebula", "kwai_level_p11_v1"): (VIVO_CHANNEL, 3, False)}, {})), \
             patch.object(chan.ChannelPage, "_enter_app_page", return_value=None), patch.object(chan.time, "sleep"):
            outcome = chan.toggle(p, "com.kuaishou.nebula", "kwai_level_p11_v1", False, VIVO_CHANNEL)
        self.assertEqual(outcome.kind, chan.NOT_CONFIRMED)
        self.assertIn("未确认", outcome.detail)
        p.click.assert_not_called()


class VivoAppPageTests(unittest.TestCase):
    def test_row_below_categories_is_found_after_one_scroll(self):
        p = vivo_phone([VIVO_APP_PAGE, vivo_app_page_with_row(), VIVO_CHANNEL_PAGE])
        p.scroll_more = Mock(return_value=True)
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            sw = chan.via_app_page(p, "com.kuaishou.nebula", VIVO_NAME, at)
        p.click.assert_called_once_with(330, 768)
        self.assertEqual(at.vivo_app, VIVO_APP)
        self.assertEqual(sw[0], "允许通知")

    def test_row_above_categories_is_not_clicked(self):
        # 「类别」以上的同名文字不是渠道行（那是总开关区域）
        xml = vivo_app_page_with_row().replace(
            '<node class="android.widget.TextView" text="类别" bounds="[0,540][400,616]"/>',
            '<node class="android.widget.TextView" text="%s" bounds="[60,560][600,636]"/>'
            '<node class="android.widget.TextView" text="类别" bounds="[0,1200][400,1276]"/>' % VIVO_NAME)
        p = vivo_phone([xml])
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", VIVO_NAME, chan.Attempt()))
        p.click.assert_not_called()

    def test_row_read_but_off_screen_is_scrolled_to(self):
        # 列表没标 scrollable 时 scroll_more 直接返回 False；行已经在 dump 里、坐标在屏下，仍要翻一页
        p = vivo_phone([vivo_app_page_with_row(y=2500, scrollable=False), vivo_app_page_with_row(), VIVO_CHANNEL_PAGE])
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            sw = chan.via_app_page(p, "com.kuaishou.nebula", VIVO_NAME, at)
        p.scroll.assert_called_once()
        p.click.assert_called_once_with(330, 768)
        self.assertEqual(sw[0], "允许通知")

    def test_hidden_node_below_the_screen_does_not_justify_a_swipe(self):
        # 折叠屏合上时 dump 里留着的另一块屏幕的节点是 invisible 的：翻页看不到它，不该滑
        xml = vivo_app_page_with_row(y=2500, scrollable=False).replace(
            '<node clickable="true" bounds="[0,2500][1080,2656]">',
            '<node clickable="true" visible-to-user="false" bounds="[0,2500][1080,2656]">')
        p = vivo_phone([xml])
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", VIVO_NAME, chan.Attempt()))
        p.scroll.assert_not_called()
        p.click.assert_not_called()

    def test_scroll_that_moves_nothing_stops_instead_of_swiping_nine_times(self):
        # 滑了页面没动（到底了）：不再连滑，也不把「没找到这一行」说成别的
        p = vivo_phone([vivo_app_page_with_row(y=2500, scrollable=False)])
        p.screen.sig = Mock(return_value="same")
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", VIVO_NAME, at))
        p.scroll.assert_called_once()
        p.click.assert_not_called()
        self.assertEqual(at.stage, "应用通知页里没找到这一行")

    def test_swipe_that_leaves_the_page_stops_instead_of_clicking(self):
        # 自己翻页这条路要照 scroll_more 的规矩查焦点：页面被滑走了就停，不当成「没找到这一行」
        p = vivo_phone([vivo_app_page_with_row(y=2500, scrollable=False)])
        page_now = {"focus": VIVO_FOCUS}
        p.screen.focus = Mock(side_effect=lambda: page_now["focus"])
        p.scroll = Mock(side_effect=lambda: page_now.update(focus="com.android.settings/.SubSettings"))
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", VIVO_NAME, at))
        p.scroll.assert_called_once()
        p.click.assert_not_called()
        self.assertEqual(at.stage, "应用通知页翻页时离开了")

    def test_app_name_recorded_before_the_title_bar_collapses(self):
        # 应用通知页的顶栏在往下翻页后可能收起；「类别」那一屏先记下的 App 名照样能用来认渠道页
        p = vivo_phone([vivo_app_page_with_row(y=2500, scrollable=False),
                   vivo_app_page_with_row(title=""),
                   VIVO_CHANNEL_PAGE])
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            sw = chan.via_app_page(p, "com.kuaishou.nebula", VIVO_NAME, at)
        self.assertEqual(at.vivo_app, VIVO_APP)
        self.assertEqual(sw[0], "允许通知")


# ---- coloros_notify_host_415 ----
# #415 ColorOS 11/12（Android 10–12）的通知页宿主是 com.coloros.notificationmanager，
# 与 ColorOS 14+ 的 com.oplus.notificationmanager 是两个包。样本按报告者 OPPO PBDM00
# （ColorOS 11 / Android 10）的真机 dump 结构造：渠道页顶栏是渠道名，唯一开关在它的行里；
# 应用通知页另有「允许通知」总开关，那颗开关不得被当成渠道开关。


HOST = "com.coloros.notificationmanager"
CHANNEL_FOCUS = f"{HOST}/.ChannelNotificationSettingsActivity"
COLOROS_APP_FOCUS = f"{HOST}/.AppNotificationSettingsActivity"
COLOROS_NAME = "营销通知"

COLOROS_CHANNEL_PAGE = '''<hierarchy><node>
  <node text="营销通知" bounds="[100,120][600,200]"/>
  <node bounds="[0,300][1080,410]">
    <node text="允许通知" bounds="[60,320][600,390]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/>
  </node>
</node></hierarchy>'''

# 应用通知页：故意把渠道名也放在顶部、只留「允许通知」一个开关——这样的页面除了页面身份之外
# 和渠道页一模一样。放在 0.22H 以下是常态，但那样「标题在不在」那条判定先返回 None，
# 删掉 `_recognise()` 的 `"AppNotification" in focus` 守卫也照样绿，这条用例就守不住它。
COLOROS_APP_PAGE = '''<hierarchy><node>
  <node text="营销通知" bounds="[100,120][600,200]"/>
  <node bounds="[0,300][1080,410]">
    <node text="允许通知" bounds="[60,320][600,390]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/>
  </node>
</node></hierarchy>'''


def coloros_phone(xml, focus):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm, p.click = Mock(), Mock()
    p.screen.tree = Mock(return_value=ET.fromstring(xml))
    return p


class ColorosPageIdentityTests(unittest.TestCase):
    def test_channel_and_app_pages_are_recognised(self):
        # 两种 Activity 都要被 _focus() 认出来，否则整条渠道直接跳过
        for focus in (CHANNEL_FOCUS, COLOROS_APP_FOCUS,
                      f"{HOST}/{HOST}.ChannelNotificationSettingsActivity"):
            self.assertTrue(chan.notification_focus(coloros_phone(COLOROS_CHANNEL_PAGE, focus)), focus)

    def test_channel_page_switch_is_recognised(self):
        p = coloros_phone(COLOROS_CHANNEL_PAGE, CHANNEL_FOCUS)
        self.assertEqual(chan.channel_switch(p, COLOROS_NAME, chan.Attempt())[0], "允许通知")

    def test_app_page_is_refused_even_when_it_looks_like_a_channel_page(self):
        # 加了新宿主之后，App 通知页的「允许通知」总开关仍不得被当成渠道开关。
        # 去掉 _recognise() 的 `"AppNotification" in focus` 后这条必红（已实测）
        p = coloros_phone(COLOROS_APP_PAGE, COLOROS_APP_FOCUS)
        self.assertIsNone(chan.channel_switch(p, COLOROS_NAME, chan.Attempt()))

    def test_unknown_activity_and_lookalike_package_are_refused(self):
        for focus in (f"{HOST}/.NotificationSettingsActivity",
                      f"com.example.notificationmanager/{HOST}.ChannelNotificationSettingsActivity"):
            self.assertEqual(chan.notification_focus(coloros_phone(COLOROS_CHANNEL_PAGE, focus)), "", focus)


# ---- chan_focus_hint_422 ----
# #422 「应用通知页没有打开」把三种情况混成了一句：页面真没开、宿主不认识（#415 那种）、
# 前台被别的应用占着（0.2.9 的报告里 174 次，红米一台机器 112 次停在 MaaFramework）。
# 判空时点名真实前台，报告者据此自己判断该先关哪个自动化工具。


HINT_PK, HINT_CID, HINT_NAME = "com.example.app", "promo", "营销通知"
EMPTY_TREE = "<hierarchy><node/></hierarchy>"


def hint_phone(focus):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm, p.click = Mock(), Mock()
    p.screen.tree = Mock(return_value=ET.fromstring(EMPTY_TREE))
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.reader = Mock()
    p.reader.shell.return_value = Mock(output="")
    return p


def hint_stage(focus):
    p = hint_phone(focus)
    with patch.object(chan.time, "sleep"):
        reached = chan.ChannelPage(p, HINT_NAME, HINT_PK, HINT_CID).open()
    return reached.stage


class FocusStageTests(unittest.TestCase):
    def test_empty_focus_keeps_the_old_wording(self):
        self.assertEqual(hint_stage(""), "应用通知页没有打开")

    def test_target_app_in_front_is_named(self):
        got = hint_stage(f"{HINT_PK}/{HINT_PK}.MainActivity")
        self.assertIn(f"前台是 {HINT_PK}，是这个应用自己", got)

    def test_settings_host_without_a_notification_page_is_named(self):
        got = hint_stage("com.android.settings/.Settings")
        self.assertIn("前台是 com.android.settings，是系统设置但不是通知页", got)

    def test_third_party_app_in_front_is_named_with_its_package(self):
        # 红米 OS2.0.10 实测：112 次停在 MaaFramework。不猜它是谁，只点名包名
        got = hint_stage("com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity")
        self.assertIn("前台是 com.aliothmoon.maafw.man，不是通知设置页", got)
        self.assertNotIn("暂停", got)          # 桌面和启动器也会落到这一类，不能一律叫用户去暂停

    def test_known_notify_host_with_an_unknown_activity_is_not_blamed_on_the_user(self):
        # 包名在通知宿主名单里、Activity 不在：多半是没见过的新系统。说成「不是通知设置页」
        # 会让用户去退出一个系统包；说成「就是通知设置页」又把白名单的判据反过来。只陈述事实
        got = hint_stage("com.coloros.notificationmanager/.NotificationSettingsActivity")
        self.assertIn("前台是 com.coloros.notificationmanager，这个 Activity 没在已知列表里", got)

    def test_a_window_name_is_not_mistaken_for_a_package(self):
        # 通知栏拉下时 dumpsys 给的是窗口名，不是「包名/Activity」
        self.assertEqual(hint_stage("NotificationShade"), "应用通知页没有打开")

    def test_stage_does_not_repeat_the_stopped_activity(self):
        # toggle() 的「停在 …」另读一次前台；hint_stage 只解释为什么没到，不再写「停在」
        for focus in ("", f"{HINT_PK}/{HINT_PK}.MainActivity", "com.android.settings/.Settings",
                      "com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity"):
            self.assertNotIn("停在", hint_stage(focus), focus)


class FocusReadTests(unittest.TestCase):
    def test_focus_read_is_kept_for_the_stage(self):
        # 判定与文案用同一次读数：不为文案再发一次 dumpsys
        focus = "com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity"
        page = chan.ChannelPage(hint_phone(focus), HINT_NAME)
        self.assertEqual(page._focus(), "")
        self.assertEqual(page.raw_focus, focus)

    def test_stage_does_not_read_the_foreground_again(self):
        # 「不为文案再发一次 dumpsys」：文案只消费 _focus() 存下的那次读数
        p = hint_phone("")
        page = chan.ChannelPage(p, HINT_NAME, HINT_PK, HINT_CID)
        page.raw_focus = "com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity"
        self.assertIn("前台是 com.aliothmoon.maafw.man", page._unopened_stage())
        p.screen.focus.assert_not_called()


# ---- duplicate_nodes_510 ----
# #510 华为 HarmonyOS 4 的 dump 会把同一个节点吐出两次（resource-id、文字、坐标全同）。
# 读屏层按节点身份计数时把它当成两行，应用通知页的渠道行于是报「同名 2 行」认不出。


DUPLICATE_FOCUS = "com.android.settings/.Settings$AppNotificationSettingsActivity"
DUPLICATE_NAME = "营销通知"


def dup_row(y):
    """应用通知页里的一条内联渠道行：标题 + 自带开关，整行可点。"""
    return (f'<node class="android.widget.LinearLayout" bounds="[40,{y}][1040,{y + 200}]">'
            f'<node resource-id="android:id/title" text="{DUPLICATE_NAME}" bounds="[80,{y + 40}][500,{y + 100}]"/>'
            f'<node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true"'
            f' bounds="[900,{y + 60}][1000,{y + 140}]"/></node>')


def dup_page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            '<node text="示例应用" bounds="[60,100][600,200]"/>'
            '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"'
            ' bounds="[0,300][1080,2200]">' + "".join(nodes) + "</node></node></hierarchy>")


def dup_phone(xml):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.screen.focus = Mock(return_value=DUPLICATE_FOCUS)
    p.screen.tree = Mock(return_value=ET.fromstring(xml))
    return p


class DuplicateRowTests(unittest.TestCase):
    def test_the_same_row_twice_is_one_row(self):
        # 整行子树重复一次，坐标完全相同：这是同一个开关，不是两个同名行
        at = chan.Attempt()
        self.assertEqual(chan.inline_switch(dup_phone(dup_page(dup_row(880), dup_row(880))), DUPLICATE_NAME, at),
                         (DUPLICATE_NAME, True, (950, 980)))
        self.assertEqual(at.why, "")

    def test_two_rows_at_different_places_stay_ambiguous(self):
        # 真的两行同名、各带开关：仍然放弃，不能因为去重把这类歧义也吞掉（#287 的判据）
        at = chan.Attempt()
        self.assertIsNone(chan.inline_switch(dup_phone(dup_page(dup_row(880), dup_row(1000))), DUPLICATE_NAME, at))
        self.assertIn("同名 2 行", at.why)

    def test_a_switch_dumped_twice_is_one_switch(self):
        # 整行只出现一次，重复的是开关本身：同一个坐标上的同一个控件，不能读成「行内开关 2 个」
        twice = (f'<node class="android.widget.LinearLayout" bounds="[40,880][1040,1080]">'
                 f'<node resource-id="android:id/title" text="{DUPLICATE_NAME}" bounds="[80,920][500,980]"/>'
                 f'<node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true"'
                 f' bounds="[900,940][1000,1020]"/>'
                 f'<node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true"'
                 f' bounds="[900,940][1000,1020]"/></node>')
        at = chan.Attempt()
        self.assertEqual(chan.inline_switch(dup_phone(dup_page(twice)), DUPLICATE_NAME, at), (DUPLICATE_NAME, True, (950, 980)))
        self.assertEqual(at.why, "")


class SummaryTests(unittest.TestCase):
    def test_the_structure_summary_counts_a_duplicated_control_once(self):
        # 上报里的「标题 N 个，开关 M 个」也不能被重复节点翻倍
        got = row.summary(ET.fromstring(dup_page(dup_row(880), dup_row(880))), 1080, 2340)
        self.assertIn("标题 1 个，开关 1 个", got)


class TextsDedupeTests(unittest.TestCase):
    def test_a_duplicate_is_counted_once(self):
        p = dup_phone(dup_page(dup_row(880), dup_row(880)))
        self.assertEqual([t for t, _, _ in p.texts()], ["示例应用", DUPLICATE_NAME])

    def test_a_different_resource_id_is_a_different_node(self):
        xml = dup_page(
            f'<node resource-id="android:id/title" text="{DUPLICATE_NAME}" bounds="[80,920][500,980]"/>',
            f'<node resource-id="android:id/summary" text="{DUPLICATE_NAME}" bounds="[80,920][500,980]"/>')
        self.assertEqual(len(dup_phone(xml).texts()), 3)      # 示例应用 + 两个各不相同的节点

    def test_a_different_place_is_a_different_node(self):
        xml = dup_page(
            f'<node resource-id="android:id/title" text="{DUPLICATE_NAME}" bounds="[80,920][500,980]"/>',
            f'<node resource-id="android:id/title" text="{DUPLICATE_NAME}" bounds="[80,1220][500,1280]"/>')
        self.assertEqual(len(dup_phone(xml).texts()), 3)

    def test_a_duplicate_must_still_be_on_screen(self):
        # 折叠屏合上时内屏那份节点在同一坐标、同样重复：去重不能让它绕过在屏判定
        xml = dup_page(
            f'<node resource-id="android:id/title" text="{DUPLICATE_NAME}" bounds="[80,920][500,980]"/>',
            f'<node resource-id="android:id/title" text="{DUPLICATE_NAME}" visible-to-user="false"'
            ' bounds="[80,920][500,980]"/>')
        self.assertEqual([t for t, _, _ in dup_phone(xml).texts()], ["示例应用", DUPLICATE_NAME])


# ---- skeleton_428 ----
# #428 渠道页认不出时上报脱敏页面骨架：只含结构字段，不含页面文字。
#
# 样本按 #427 报告者的华为形态造：渠道名只写在 CheckBox 上，行容器可点。


SKELETON_FOCUS = "com.huawei.android.settings/.SubSettings"

# 渠道名只在 CheckBox 的 content-desc 上；列表里另有一行无关文字
HUAWEI_CARD = '''<hierarchy rotation="0">
<node package="com.huawei.android.settings" class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="通知管理" bounds="[40,100][400,160]"/>
  <node class="android.widget.ScrollView" scrollable="true" bounds="[0,200][1080,2340]">
    <node class="android.widget.LinearLayout" clickable="true" bounds="[0,300][1080,420]">
      <node class="android.widget.TextView" text="活动与优惠" bounds="[40,320][400,360]"/>
      <node class="android.widget.CheckBox" content-desc="营销通知" checkable="true" checked="true"
            clickable="true" bounds="[880,320][1000,400]"/>
    </node>
  </node>
</node>
</hierarchy>'''


def skeleton(xml, name="营销通知", w=1080, h=2340, focus=SKELETON_FOCUS):
    return row.skeleton(ET.fromstring(xml), name, w, h, focus)


FLAGS_PAGE = '''<hierarchy rotation="0">
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="android.widget.LinearLayout" clickable="true" bounds="[0,300][1080,420]">
    <node class="android.widget.TextView" text="营销通知" bounds="[40,300][400,340]"/>
    <node class="android.widget.TextView" content-desc="营销通知" bounds="[40,340][400,380]"/>
    <node class="android.widget.TextView" text="营销通知，已关闭" bounds="[40,380][600,420]"/>
  </node>
</node>
</hierarchy>'''


def rows(page_name="营销通知", count=1):
    """count 行可点的渠道行，每行一段文字（或只有开关）。"""
    body = "".join(
        f'<node clickable="true" bounds="[0,{300 + i * 20}][1080,{310 + i * 20}]">'
        + (f'<node class="android.widget.TextView" text="{page_name}" '
           f'bounds="[40,{300 + i * 20}][400,{305 + i * 20}]"/>' if page_name else "")
        + f'<node class="android.widget.CheckBox" checkable="true" checked="true" '
          f'bounds="[880,{300 + i * 20}][1000,{310 + i * 20}]"/></node>'
        for i in range(count))
    return ('<hierarchy rotation="0"><node class="android.widget.ScrollView" scrollable="true" '
            'bounds="[0,200][1080,2340]">' + body + "</node></hierarchy>")


class SkeletonTests(unittest.TestCase):
    def test_the_name_on_a_checkbox_is_marked_in_the_skeleton(self):
        text = skeleton(HUAWEI_CARD)
        head, body = text.split("\n", 1)
        self.assertTrue(head.startswith("骨架 v1"), head)
        self.assertIn("锚=名1", head)
        self.assertIn("CheckBox", body)
        self.assertIn("M", body)                 # content-desc 等于渠道名
        self.assertNotIn("活动与优惠", body)      # 页面文字不进骨架
        self.assertNotIn("通知管理", body)

    def test_a_row_with_only_a_switch_is_the_fallback_anchor(self):
        text = skeleton(rows(page_name="", count=2))
        head, body = text.split("\n", 1)
        self.assertIn("锚=回退列表2", head)
        self.assertIn("CheckBox", body)

    def test_the_fallback_skips_radio_buttons_and_reports_the_rows_it_kept(self):
        # RadioButton 是互斥选项，不算开关；它排在最前，混进来就会占掉 3 行里的一行。
        # 6 个带开关的行：只带 3 行，头部也得写 3。
        radio = ('<node class="android.widget.RadioButton" checkable="true" checked="true" '
                 'bounds="[880,220][1000,270]"/>')
        page = rows(page_name="", count=6).replace(
            'class="android.widget.ScrollView" scrollable="true" bounds="[0,200][1080,2340]">',
            'class="android.widget.ScrollView" scrollable="true" bounds="[0,200][1080,2340]">' + radio, 1)
        head, body = skeleton(page).split("\n", 1)
        self.assertIn("锚=回退列表3", head)
        self.assertEqual(body.count("CheckBox"), 3)
        self.assertNotIn("RadioButton", body)

    def test_a_nonstandard_resource_id_is_dropped_instead_of_leaking_text(self):
        page = ('<hierarchy rotation="0"><node class="android.widget.TextView" '
                'resource-id="营销通知-不是标准 id" bounds="[40,300][400,360]"/></hierarchy>')
        body = skeleton(page, "别的名字").split("\n", 1)[1]
        self.assertNotIn("id=", body)
        self.assertNotIn("营销通知", body)

    def test_the_character_cap_trims_from_the_end(self):
        nodes = "".join(
            f'<node class="android.widget.{"X" * 50}" resource-id="com.x:id/{"y" * 40}" '
            f'bounds="[0,{100 + i * 10}][1080,{105 + i * 10}]"/>' for i in range(60))
        page = f'<hierarchy rotation="0"><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">{nodes}</node></hierarchy>'
        text = skeleton(page, "营销通知")
        head, body = text.split("\n", 1)
        self.assertLessEqual(len(text), row.SKELETON_BYTES)
        self.assertNotIn("剪枝=0", head)
        self.assertLess(len(body.splitlines()), 40)

    def test_a_page_without_name_or_switch_falls_back_to_the_first_nodes(self):
        page = ('<hierarchy rotation="0"><node class="android.widget.TextView" text="甲" '
                'bounds="[0,100][400,160]"/><node class="android.widget.TextView" text="乙" '
                'bounds="[0,200][400,260]"/></hierarchy>')
        text = skeleton(page, "营销通知")
        head, body = text.split("\n", 1)
        self.assertIn("锚=回退前2", head)
        self.assertEqual(len(body.splitlines()), 2)
        self.assertNotIn("甲", body)
        self.assertNotIn("乙", body)

    def test_exact_text_exact_desc_and_containment_are_told_apart(self):
        flags = [ln.split()[3] for ln in skeleton(FLAGS_PAGE).split("\n")[1:] if len(ln.split()) > 3]
        self.assertIn("TN", flags)       # text 等于渠道名
        self.assertIn("DM", flags)       # content-desc 等于渠道名
        self.assertIn("TP", flags)       # 只是包含：名字被拼进更长的文案，没有 N / M

    def test_off_screen_invisible_and_status_bar_nodes_stay_out(self):
        page = '''<hierarchy rotation="0">
<node class="android.widget.StatusBar" package="com.android.systemui" bounds="[0,0][1080,60]"/>
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="android.widget.InvisibleBox" visible-to-user="false" bounds="[0,100][1080,200]"/>
  <node class="android.widget.OffScreenBox" bounds="[0,3000][1080,3100]"/>
  <node class="android.widget.TextView" text="营销通知" bounds="[40,300][400,360]"/>
</node>
</hierarchy>'''
        body = skeleton(page).split("\n", 1)[1]
        self.assertNotIn("StatusBar", body)
        self.assertNotIn("InvisibleBox", body)
        self.assertNotIn("OffScreenBox", body)
        self.assertIn("TextView", body)

    def test_the_skeleton_stops_at_eighty_nodes(self):
        # 8 个同名锚点各带一整行（行内 12 个子节点），选中远超 80
        rows_xml = "".join(
            f'<node clickable="true" bounds="[0,{300 + i * 20}][1080,{310 + i * 20}]">'
            f'<node class="android.widget.TextView" text="营销通知" bounds="[40,{300 + i * 20}][400,{305 + i * 20}]"/>'
            + "".join(f'<node class="android.widget.TextView" text="细节{j}" '
                      f'bounds="[40,{300 + i * 20}][400,{305 + i * 20}]"/>' for j in range(12))
            + "</node>"
            for i in range(20))
        page = ('<hierarchy rotation="0"><node class="android.widget.ScrollView" scrollable="true" '
                'bounds="[0,200][1080,2340]">' + rows_xml + "</node></hierarchy>")
        text = skeleton(page)
        head, body = text.split("\n", 1)
        self.assertIn("节点=80", head)
        self.assertNotIn("剪枝=0", head)
        self.assertEqual(len(body.splitlines()), 80)

    def test_resource_id_keeps_the_short_name_and_is_cut_at_forty(self):
        long_id = "com.huawei.android.settings:id/" + "x" * 60
        page = ('<hierarchy rotation="0"><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">'
                '<node class="android.widget.Switch" resource-id="com.huawei.android.settings:id/switch_widget" '
                'checkable="true" bounds="[880,300][1000,400]"/>'
                f'<node class="android.widget.Switch" resource-id="{long_id}" checkable="true" '
                'bounds="[880,500][1000,600]"/></node></hierarchy>')
        body = skeleton(page, "营销通知").split("\n", 1)[1]
        self.assertIn("id=switch_widget", body)
        self.assertIn("id=" + "x" * 40 + "…", body)
        self.assertNotIn("com.huawei.android.settings", body)


def skeleton_phone(pages):
    """每次读屏返回下一页，最后一页重复。"""
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=SKELETON_FOCUS)
    queue = [ET.fromstring(x) for x in pages]
    p.screen.tree = Mock(side_effect=lambda: queue.pop(0) if len(queue) > 1 else queue[0])
    return p


class ChannelPageSkeletonTests(unittest.TestCase):
    def test_only_the_row_not_found_stage_carries_a_skeleton(self):
        p = skeleton_phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = "点进去后没认出渠道页"
        page._hint()
        self.assertEqual(page.skeleton, "")

        p = skeleton_phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        page._hint()
        self.assertTrue(page.skeleton.startswith("骨架 v1"))

    def test_the_same_layout_is_reported_once_and_two_layouts_at_most(self):
        p = skeleton_phone([HUAWEI_CARD, HUAWEI_CARD, FLAGS_PAGE, rows(page_name="", count=1)])

        def attempt():
            page = chan.ChannelPage(p, "营销通知")
            page.stage = chan.ROW_NOT_FOUND
            page._hint()
            return page.skeleton

        self.assertTrue(attempt().startswith("骨架 v1"))
        self.assertEqual(attempt(), "")           # 同布局失败很多个渠道：只留第一份
        self.assertEqual(p.skeleton_count, 1)

        self.assertTrue(attempt().startswith("骨架 v1"))          # 第二种布局
        self.assertEqual(p.skeleton_count, 2)
        self.assertEqual(attempt(), "")                           # 第三份不再带
        self.assertEqual(p.skeleton_count, 2)

    def test_hint_does_not_read_the_focus_window_again(self):
        # ADR-0007：p.focus() 的调用次数只减不增；骨架用 _focus() 留下的 raw_focus
        p = skeleton_phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        page.raw_focus = SKELETON_FOCUS
        page._hint()
        self.assertTrue(page.skeleton.startswith("骨架 v1"))
        p.screen.focus.assert_not_called()

    def test_a_second_channel_name_on_the_same_layout_is_not_a_new_skeleton(self):
        # 同一页、换了目标渠道名：布局没变，不该再带一份
        p = skeleton_phone([HUAWEI_CARD, HUAWEI_CARD])
        for name in ("营销通知", "活动推送"):
            page = chan.ChannelPage(p, name)
            page.stage = chan.ROW_NOT_FOUND
            page._hint()
            if name == "营销通知":
                self.assertTrue(page.skeleton.startswith("骨架 v1"))
            else:
                self.assertEqual(page.skeleton, "")
        self.assertEqual(p.skeleton_count, 1)

    def test_an_app_level_denial_carries_no_skeleton(self):
        # 应用通知整体关着：页面上只有总开关，行不在页面上，不是没认出来（#426）
        p = skeleton_phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        page.no_row = True
        page._hint()
        self.assertEqual(page.skeleton, "")
        self.assertEqual(p.skeleton_count, 0)

    def test_a_page_that_cannot_be_read_keeps_the_step_alive(self):
        p = skeleton_phone([HUAWEI_CARD])
        p.screen.tree = Mock(side_effect=RuntimeError("dump 失败"))
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        self.assertEqual(page._hint(), "")
        self.assertEqual(page.skeleton, "")


class ToggleWiringTests(unittest.TestCase):
    def test_the_failure_outcome_carries_the_skeleton_to_the_report(self):
        p = Mock()
        p.locked.return_value = False
        reached = chan.Unreached(chan.ROW_NOT_FOUND, "", "", False, "骨架 v1\n0 X 0,0,100,100")
        with patch.object(chan, "parse", return_value=({("com.x", "promo"): ("营销通知", 3, False)}, {})), \
             patch.object(chan.ChannelPage, "open", return_value=reached):
            out = chan.toggle(p, "com.x", "promo", False, "营销通知")
        self.assertEqual(out.kind, chan.NOT_CONFIRMED)
        self.assertEqual(out.payload, "骨架 v1\n0 X 0,0,100,100")


class PayloadLineTests(unittest.TestCase):
    def test_silent_unless_the_client_asked_for_it(self):
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(out):
            os.environ.pop("AAC_EVENTS", None)
            events.payload("骨架 v1\n0 FrameLayout 0,0,100,100")
        self.assertEqual(out.getvalue(), "")

    def test_every_skeleton_line_gets_the_prefix(self):
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(out):
            os.environ["AAC_EVENTS"] = "1"
            events.payload("骨架 v1\n0 FrameLayout 0,0,100,100")
        self.assertEqual(out.getvalue().splitlines(), [
            "#aac:payload 骨架 v1",
            "#aac:payload 0 FrameLayout 0,0,100,100",
        ])

    def test_payload_lines_are_not_events(self):
        line = "#aac:payload 骨架 v1"
        self.assertTrue(events.is_payload(line))
        self.assertFalse(events.is_event(line))
        self.assertEqual(events.strip_payload(line), "骨架 v1")


class ShowTests(unittest.TestCase):
    def test_the_skeleton_is_printed_after_the_failure_line(self):
        outcome = chan.Outcome(chan.NOT_CONFIRMED, "未确认「营销通知」渠道页及通知开关", "骨架 v1\n0 X 0,0,100,100")
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(out):
            os.environ["AAC_EVENTS"] = "1"
            chan.show(outcome, "营销通知", False)
        lines = out.getvalue().splitlines()
        self.assertIn("✗", lines[0])
        self.assertEqual(lines[1:], ["#aac:payload 骨架 v1", "#aac:payload 0 X 0,0,100,100"])


class ClientLogTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.api = app.Api(self._dir.name)
        self.api.job = job_stub()

    def tearDown(self):
        self._dir.cleanup()

    def test_payload_reaches_the_report_but_not_the_step_summary(self):
        shown = self.api._log("#aac:payload 骨架 v1 页=com.huawei.android.settings/.SubSettings")
        self.assertIsNone(shown)                 # 进不了 tail（步骤摘要）
        self.assertEqual(self.api.job.lines, [])          # 也不进界面日志
        report = self.api.report_payload()
        self.assertEqual(report["log"].count("骨架 v1"), 1)  # 只出现一次
        self.assertIn("[诊断载荷]", report["log"])
        self.assertNotIn("aac:payload", json.dumps(report, ensure_ascii=False))

    def test_events_still_stay_out_of_the_log(self):
        self.api._log('#aac:event {"kind": "paused"}')
        self.assertEqual(self.api.job.lines, [])


# ---- traditional_chinese_498（认页部分） ----
# #498 繁体中文界面：渠道页认页与营销/服务词表只认简体、英文。
#
# 报告者 vivo V2436A（PD2436E_A_17.2.13.5.W10 / Android 17 / 繁体台湾）的 chan-off 日志：
# 「标题顶部，允许通知开关 0 个，开关 6 个」——页面已认出来，只差「允許通知」不在 ALLOW。
# 渠道页样本沿用 #336 的真机结构（顶栏无 resource-id、向上导航、允许通知行），按界面语言换掉全部文字。


TRAD_FOCUS = ("com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification"
              ".settings.channels.NotificationSettingsActivity")
TRAD_APP = "應用名"

# 同一份页面的三种界面语言：认页只看标签，标题 / 导航 / 分组也要跟着换，才对得上真机
HANT = {"name": "熱門推薦", "back": "向上導覽", "allow": "允許通知",
        "show": "顯示通知", "group": "類別"}
HANS = {"name": "热门推荐", "back": "向上导航", "allow": "允许通知",
        "show": "显示通知", "group": "类别"}
EN = {"name": "Popular recommendations", "back": "Navigate up", "allow": "Allow notifications",
      "show": "Show notifications", "group": "Categories"}


def trad_page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.vivo.systemuiplugin" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def trad_header(title, back):
    return (f'<node class="android.widget.TextView" text="{title}" bounds="[0,111][1080,360]"/>'
            f'<node class="android.widget.Button" content-desc="{back}" bounds="[24,168][156,300]"/>')


def trad_allow_row(label):
    return ('<node clickable="true" bounds="[0,381][1080,489]">'
            f'<node class="android.widget.TextView" text="{label}" bounds="[0,397][342,473]"/>'
            '<node class="android.widget.Switch" text="開啟" content-desc="開啟" checkable="true" checked="true"'
            ' clickable="true" bounds="[876,381][1020,489]"/></node>')


def trad_channel_page(ui, label):
    return trad_page(trad_header(ui["name"], ui["back"]), trad_allow_row(label))


def trad_app_page(ui):
    return trad_page(trad_header(TRAD_APP, ui["back"]), trad_allow_row(ui["allow"]),
                '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,520][1080,2280]">'
                f'<node class="android.widget.TextView" text="{ui["group"]}" bounds="[0,540][400,616]"/></node>')


def trad_phone(xml):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.screen.focus = Mock(return_value=TRAD_FOCUS)
    p.screen.tree = Mock(return_value=ET.fromstring(xml))
    return p


class TraditionalPageTests(unittest.TestCase):
    def _recognise(self, ui, label):
        p = trad_phone(trad_channel_page(ui, label))
        return chan.ChannelPage(p, ui["name"], vivo_app=TRAD_APP)._recognise()

    def test_every_interface_language_is_recognised(self):
        for ui in (HANT, HANS, EN):
            for key in ("allow", "show"):
                with self.subTest(ui=ui["name"], label=ui[key]):
                    self.assertIsNotNone(self._recognise(ui, ui[key]))

    def test_unknown_label_is_still_rejected(self):
        # 放宽语言不等于放宽判据：标着别的字样的开关不能当通知总开关
        self.assertIsNone(self._recognise(HANT, "通知"))

    def test_every_interface_language_channel_group_is_located(self):
        for ui in (HANT, HANS, EN):
            with self.subTest(ui=ui["name"]):
                p = trad_phone(trad_app_page(ui))
                self.assertIsNotNone(chan.group_floor(p.texts(p.tree())))


if __name__ == "__main__":
    unittest.main()
