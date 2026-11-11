"""#336 vivo V1986A（Funtouch 13 / Android 12）chan-off 全部跳过。

这台机器的通知页宿主是 com.android.systemui，渠道页顶栏是一个没有 resource-id 的 TextView，
渠道行在应用通知页的「类别」分组下面、首屏看不到。样本按报告者 2026-10-30 的真机 dump 造：
渠道页顶栏 [0,111][1080,360]、向上导航 [24,168][156,300]、「允许通知」[0,397][342,473] 与开关 [876,381][1020,489]。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
from fixtures import phone_stub

FOCUS = ("com.android.systemui/com.vivo.systemui.statusbar.notification"
         ".settings.channels.NotificationSettingsActivity")
APP = "快手极速版"
CHANNEL = "运营消息"        # 报告里被跳过的那一个
NAME = "优质内容推送"       # 渠道页 dump 里的那一个


def phone(pages, w=1080, h=2340):
    """pages：依次返回的页面，最后一页一直重复。每次读屏的文字签名都不同，相当于页面真的翻动了。"""
    p = phone_stub("test", d=Mock())
    p.W, p.H = w, h
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=FOCUS)
    p.confirm, p.click = Mock(), Mock()
    pages_seen = iter(range(10 ** 6))
    p.screen.sig = Mock(side_effect=lambda: str(next(pages_seen)))
    p.screen.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    queue = [ET.fromstring(x) for x in pages]
    p.screen.tree = Mock(side_effect=lambda: queue.pop(0) if len(queue) > 1 else queue[0])
    return p


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.systemui" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


# 渠道页：顶栏没有 resource-id（dump 里就是一段横跨整屏的普通 TextView）
CHANNEL_PAGE = page(
    '<node class="android.widget.TextView" text="优质内容推送" bounds="[0,111][1080,360]"/>',
    '<node class="android.widget.Button" content-desc="向上导航" bounds="[24,168][156,300]"/>',
    '<node clickable="true" bounds="[0,381][1080,489]">'
    '<node class="android.widget.TextView" text="允许通知" bounds="[0,397][342,473]"/>'
    '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
    ' clickable="true" bounds="[876,381][1020,489]"/></node>',
    '<node class="android.widget.TextView" text="接受智能通知控制" bounds="[0,547][582,623]"/>',
    '<node class="android.widget.TextView" text="重要程度" bounds="[0,644][342,720]"/>',
)

APP_PAGE = page(
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

ROW = ('<node clickable="true" bounds="[0,{t}][1080,{b}]">'
       '<node class="android.widget.TextView" text="%s" bounds="[60,{t2}][600,{b2}]"/>'
       '<node class="android.widget.CheckBox" checkable="true" checked="true" bounds="[876,{t}][1020,{b}]"/></node>')


def app_page_with_row(y=700, scrollable=True, title='<node class="android.widget.TextView" text="快手极速版"'
                                                   ' bounds="[0,111][1080,360]"/>'):
    """应用通知页，「类别」下面多一行渠道行。y 传 2500 把它放到屏外；
    scrollable=False 造「列表没标可滚动」的页面；title 传空串造滚动后顶栏已收起的页面。"""
    row = (ROW % NAME).format(t=y, b=y + 156, t2=y + 30, b2=y + 106)
    return page(
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


class TopTitleTests(unittest.TestCase):
    def test_toolbar_id_wins_when_it_is_there(self):
        xml = CHANNEL_PAGE.replace(
            'class="android.widget.TextView" text="优质内容推送" bounds="[0,111][1080,360]"',
            'class="android.widget.TextView" resource-id="com.vivo.systemuiplugin:id/originui_vtoolbar_normal_title"'
            ' text="优质内容推送" bounds="[0,111][1080,360]"')
        p = phone([xml])
        self.assertEqual(chan.top_title(p, p.tree()), "优质内容推送")

    def test_title_without_resource_id_is_read_by_geometry(self):
        p = phone([CHANNEL_PAGE])
        self.assertEqual(chan.top_title(p, p.tree()), "优质内容推送")

    def test_narrow_top_text_is_not_a_title(self):
        # 顶栏只有「向上导航」这种窄控件时不能当标题：认错就会拿它去比渠道名
        xml = page('<node class="android.widget.Button" content-desc="向上导航" bounds="[24,168][156,300]"/>')
        p = phone([xml])
        self.assertIsNone(chan.top_title(p, p.tree()))

    def test_text_below_the_header_band_is_not_a_title(self):
        xml = page('<node class="android.widget.TextView" text="允许通知" bounds="[0,397][1080,473]"/>')
        p = phone([xml])
        self.assertIsNone(chan.top_title(p, p.tree()))


class ChannelPageTests(unittest.TestCase):
    def test_channel_page_without_toolbar_id_is_operated(self):
        p = phone([CHANNEL_PAGE])
        at = chan.Attempt(vivo_app=APP)
        self.assertEqual(chan.channel_switch(p, "优质内容推送", at), ("允许通知", True, (948, 435)))

    def test_wait_page_recognises_the_same_page(self):
        p = phone([CHANNEL_PAGE])
        p.vivo_seen = True                  # 已经走过应用通知页
        with patch.object(chan.time, "sleep"):
            sw = chan.wait_page(p, NAME, chan.Attempt(vivo_app=APP))
        self.assertEqual(sw[2], (948, 435))

    def test_half_width_row_label_is_not_a_title(self):
        # 「允许通知」那一行横跨半屏；把它当顶栏标题，就会拿应用总开关当渠道开关
        xml = page(
            '<node class="android.widget.TextView" text="营销通知" bounds="[100,120][600,200]"/>',
            '<node clickable="true" bounds="[0,300][1080,410]">'
            '<node class="android.widget.TextView" text="允许通知" bounds="[60,320][600,390]"/>'
            '<node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/></node>')
        p = phone([xml])
        self.assertIsNone(chan.channel_switch(p, "允许通知", chan.Attempt(vivo_app="示例应用")))

    def test_other_channel_name_is_still_refused(self):
        # 顶栏是别的渠道名：认页仍要说不，心态是「宁可跳过」
        p = phone([CHANNEL_PAGE])
        self.assertIsNone(chan.channel_switch(p, CHANNEL, chan.Attempt(vivo_app=APP)))

    def test_app_page_is_still_refused_when_title_matches_the_app(self):
        # 应用总页顶栏是 App 名；哪怕渠道名恰好相同也不认（否则关的是整个 App 的通知）
        p = phone([APP_PAGE])
        self.assertIsNone(chan.channel_switch(p, APP, chan.Attempt(vivo_app=APP)))

    def test_unrecognised_page_is_reported_not_clicked(self):
        p = phone([CHANNEL_PAGE])
        with patch.object(chan, "parse", return_value=({("com.kuaishou.nebula", "kwai_level_p11_v1"): (CHANNEL, 3, False)}, {})), \
             patch.object(chan.ChannelPage, "_enter_app_page", return_value=None), patch.object(chan.time, "sleep"):
            outcome = chan.toggle(p, "com.kuaishou.nebula", "kwai_level_p11_v1", False, CHANNEL)
        self.assertEqual(outcome.kind, chan.NOT_CONFIRMED)
        self.assertIn("未确认", outcome.detail)
        p.click.assert_not_called()


class AppPageTests(unittest.TestCase):
    def test_row_below_categories_is_found_after_one_scroll(self):
        p = phone([APP_PAGE, app_page_with_row(), CHANNEL_PAGE])
        p.scroll_more = Mock(return_value=True)
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            sw = chan.via_app_page(p, "com.kuaishou.nebula", NAME, at)
        p.click.assert_called_once_with(330, 768)
        self.assertEqual(at.vivo_app, APP)
        self.assertEqual(sw[0], "允许通知")

    def test_row_above_categories_is_not_clicked(self):
        # 「类别」以上的同名文字不是渠道行（那是总开关区域）
        xml = app_page_with_row().replace(
            '<node class="android.widget.TextView" text="类别" bounds="[0,540][400,616]"/>',
            '<node class="android.widget.TextView" text="%s" bounds="[60,560][600,636]"/>'
            '<node class="android.widget.TextView" text="类别" bounds="[0,1200][400,1276]"/>' % NAME)
        p = phone([xml])
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", NAME, chan.Attempt()))
        p.click.assert_not_called()

    def test_row_read_but_off_screen_is_scrolled_to(self):
        # 列表没标 scrollable 时 scroll_more 直接返回 False；行已经在 dump 里、坐标在屏下，仍要翻一页
        p = phone([app_page_with_row(y=2500, scrollable=False), app_page_with_row(), CHANNEL_PAGE])
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            sw = chan.via_app_page(p, "com.kuaishou.nebula", NAME, at)
        p.scroll.assert_called_once()
        p.click.assert_called_once_with(330, 768)
        self.assertEqual(sw[0], "允许通知")

    def test_hidden_node_below_the_screen_does_not_justify_a_swipe(self):
        # 折叠屏合上时 dump 里留着的另一块屏幕的节点是 invisible 的：翻页看不到它，不该滑
        xml = app_page_with_row(y=2500, scrollable=False).replace(
            '<node clickable="true" bounds="[0,2500][1080,2656]">',
            '<node clickable="true" visible-to-user="false" bounds="[0,2500][1080,2656]">')
        p = phone([xml])
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", NAME, chan.Attempt()))
        p.scroll.assert_not_called()
        p.click.assert_not_called()

    def test_scroll_that_moves_nothing_stops_instead_of_swiping_nine_times(self):
        # 滑了页面没动（到底了）：不再连滑，也不把「没找到这一行」说成别的
        p = phone([app_page_with_row(y=2500, scrollable=False)])
        p.screen.sig = Mock(return_value="same")
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", NAME, at))
        p.scroll.assert_called_once()
        p.click.assert_not_called()
        self.assertEqual(at.stage, "应用通知页里没找到这一行")

    def test_swipe_that_leaves_the_page_stops_instead_of_clicking(self):
        # 自己翻页这条路要照 scroll_more 的规矩查焦点：页面被滑走了就停，不当成「没找到这一行」
        p = phone([app_page_with_row(y=2500, scrollable=False)])
        page_now = {"focus": FOCUS}
        p.screen.focus = Mock(side_effect=lambda: page_now["focus"])
        p.scroll = Mock(side_effect=lambda: page_now.update(focus="com.android.settings/.SubSettings"))
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.via_app_page(p, "com.kuaishou.nebula", NAME, at))
        p.scroll.assert_called_once()
        p.click.assert_not_called()
        self.assertEqual(at.stage, "应用通知页翻页时离开了")

    def test_app_name_recorded_before_the_title_bar_collapses(self):
        # 应用通知页的顶栏在往下翻页后可能收起；「类别」那一屏先记下的 App 名照样能用来认渠道页
        p = phone([app_page_with_row(y=2500, scrollable=False),
                   app_page_with_row(title=""),
                   CHANNEL_PAGE])
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            sw = chan.via_app_page(p, "com.kuaishou.nebula", NAME, at)
        self.assertEqual(at.vivo_app, APP)
        self.assertEqual(sw[0], "允许通知")


if __name__ == "__main__":
    unittest.main()
