"""渠道页的认页决策是屏幕快照上的纯函数：认出哪一行、卡在哪一阶段、哪些行可拨。（#1434）

输入只有一份 `ScreenSnapshot`（内联 XML 字面量经 `snapshot_from_tree()` 装配），输出是
认出 / 没认出与原因；最后一组用点击桩断言 `ChannelPage` 那侧「不该点时一次都没点」。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import chan_fast as chan
import channel_decide as decide
import screen_snapshot as snap
from fixtures import phone_stub

DEEP_FOCUS = "com.android.settings/com.android.settings.Settings$ChannelNotificationSettingsActivity"
APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
VIVO_FOCUS = ("com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification"
              ".settings.channels.NotificationSettingsActivity")
NAME, APP = "营销通知", "示例应用"


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def text(value, area):
    return f'<node class="android.widget.TextView" text="{value}" bounds="{area}"/>'


def switch(area, checked=True, **attrs):
    extra = "".join(f' {key.replace("_", "-")}="{value}"' for key, value in attrs.items())
    return ('<node class="android.widget.Switch" checkable="true"'
            f' checked="{str(checked).lower()}" bounds="{area}"{extra}/>')


def row(area, *children):
    return f'<node clickable="true" bounds="{area}">' + "".join(children) + "</node>"


def make(page_xml, focus=DEEP_FOCUS, width=1080, height=2340, **kwargs):
    return snap.snapshot_from_tree(ET.fromstring(page_xml), width, height, focus, **kwargs)


# 渠道页：顶栏是渠道名，「允许通知」那一行带唯一开关
DEEP_PAGE = page(
    text(NAME, "[0,111][1080,360]"),
    row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"),
        switch("[876,381][1020,489]")),
)

# 应用通知页：渠道行可点，点进去才是渠道页
APP_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,700][1080,860]", text(NAME, "[60,720][700,800]")),
)

# 应用通知页：渠道行自带开关（内联布局）
INLINE_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,700][1080,860]", text(NAME, "[60,720][700,800]"), switch("[900,720][1040,800]")),
)

# 两处同名、都带开关：无法判断哪一行是渠道
SAME_NAME_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,700][1080,860]", text(NAME, "[60,720][700,800]"), switch("[900,720][1040,800]")),
    row("[0,900][1080,1060]", text(NAME, "[60,920][700,1000]"),
        switch("[900,920][1040,1000]", checked=False)),
)

# 三星 One UI：渠道名在页眉控件里，位置低于顶部带
HEADER_PAGE = page(
    '<node class="android.widget.TextView" resource-id="android:id/entity_header_title"'
    f' text="{NAME}" bounds="[0,600][1080,700]"/>',
    row("[0,800][1080,920]", text("允许通知", "[0,820][342,900]"), switch("[876,820][1020,920]")),
)

# 「允许通知」标题不在行里，只在开关自己的 content-desc 上（三星）
SAMSUNG_ALLOW_PAGE = page(
    text(NAME, "[0,111][1080,360]"),
    switch("[876,381][1020,489]", content_desc="允许通知"),
)

# 两个「允许通知」：分不清哪个是渠道页的总开关
TWO_ALLOW_PAGE = page(
    text(NAME, "[0,111][1080,360]"),
    row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"), switch("[876,381][1020,489]")),
    row("[0,540][1080,648]", text("允许通知", "[0,556][342,632]"), switch("[876,540][1020,648]")),
)

# 应用通知整体关闭时只剩总开关：页面上确实没有这个渠道
MASTER_ONLY_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"), switch("[876,381][1020,489]")),
)

# 名字读进 dump 了，坐标在屏幕下沿之外；列表没标可滚动（vivo 的返回形状）
OFF_SCREEN_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,2400][1080,2520]", text(NAME, "[60,2420][700,2500]")),
)

# 折叠屏合上时留下的另一块屏：坐标在屏外且不可见，翻页看不到它
HIDDEN_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    '<node visible-to-user="false" bounds="[0,0][1080,2340]">'
    + row("[0,2400][1080,2520]", text(NAME, "[60,2420][700,2500]")) + "</node>",
)

# 行内有应用总开关：不能当渠道行
INLINE_MASTER_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,700][1080,860]", text(NAME, "[60,720][700,800]"), text("允许通知", "[60,800][600,860]"),
        switch("[900,720][1040,800]")),
)

# 行高超过屏高的 20%：不是一行
TALL_ROW_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,700][1080,1300]", text(NAME, "[60,720][700,800]"), switch("[900,720][1040,800]")),
)

# 两处同名：第一行的开关错开一整个行高（分组名借来的），第二行的开关同一水平带
GAP_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,700][1080,1160]", text(NAME, "[60,710][700,780]"), switch("[876,1080][1020,1150]")),
    row("[0,1300][1080,1460]", text(NAME, "[60,1320][700,1400]"), switch("[876,1320][1020,1400]")),
)

# 应用通知页：「类别」分组以下才是渠道行
CATEGORY_PAGE = page(
    text(APP, "[0,111][1080,360]"),
    row("[0,600][1080,690]", text(NAME, "[60,610][700,680]")),
    text("类别", "[0,700][400,776]"),
    row("[0,800][1080,960]", text(NAME, "[60,820][700,900]")),
)

# 自绘开关：没有 checkable，靠 resource-id 与截图颜色判态
SELF_DRAWN_PAGE = page(
    text(NAME, "[0,111][1080,360]"),
    row("[0,700][1080,860]", text("允许通知", "[60,720][600,800]"),
        '<node clickable="true" resource-id="com.example:id/switch_view" bounds="[900,720][1040,800]"/>'),
)


class RecogniseTests(unittest.TestCase):
    def test_a_channel_page_gives_its_single_allow_switch(self):
        got = decide.recognise(make(DEEP_PAGE), NAME, DEEP_FOCUS)
        self.assertEqual(got.switch, ("允许通知", True, (948, 435)))
        self.assertEqual(got.why, "")

    def test_another_channel_name_on_the_same_page_is_not_recognised(self):
        self.assertIsNone(decide.recognise(make(DEEP_PAGE), "别的渠道", DEEP_FOCUS).switch)

    def test_the_app_page_is_never_mistaken_for_a_channel_page(self):
        """焦点就是应用通知页的 Activity：哪怕标题在顶部也不认。"""
        snap_with = make(APP_PAGE, focus=APP_FOCUS)
        self.assertFalse(decide.recognised_page(snap_with, APP, APP_FOCUS))
        self.assertIsNone(decide.recognise(snap_with, APP, APP_FOCUS).switch)

    def test_a_name_in_the_header_band_needs_the_samsung_header_id(self):
        self.assertEqual(decide.recognise(make(HEADER_PAGE), NAME, DEEP_FOCUS).switch[0], "允许通知")
        plain = page(
            text(NAME, "[0,600][1080,700]"),
            row("[0,800][1080,920]", text("允许通知", "[0,820][342,900]"),
                switch("[876,820][1020,920]")),
        )
        self.assertIsNone(decide.recognise(make(plain), NAME, DEEP_FOCUS).switch)

    def test_two_allow_switches_are_ambiguous_and_refused(self):
        self.assertIsNone(decide.recognise(make(TWO_ALLOW_PAGE), NAME, DEEP_FOCUS).switch)

    def test_vivo_needs_the_app_name_from_the_app_page(self):
        for app in (None, NAME):
            self.assertIsNone(decide.recognise(make(DEEP_PAGE, focus=VIVO_FOCUS), NAME, VIVO_FOCUS,
                                               vivo_app=app).switch)
        got = decide.recognise(make(DEEP_PAGE, focus=VIVO_FOCUS), NAME, VIVO_FOCUS, vivo_app=APP)
        self.assertEqual(got.switch[0], "允许通知")

    def test_a_snapshot_without_its_tree_says_so(self):
        bare = snap.ScreenSnapshot.from_json(make(DEEP_PAGE).to_json())
        with self.assertRaisesRegex(ValueError, "with_tree"):
            decide.recognise(bare, NAME, DEEP_FOCUS)


class TitleTests(unittest.TestCase):
    def test_titled_reads_the_top_band_only(self):
        self.assertTrue(decide.titled(make(DEEP_PAGE), NAME))
        self.assertFalse(decide.titled(make(APP_PAGE), NAME))

    def test_the_toolbar_id_wins_over_geometry(self):
        xml = page(
            '<node class="android.widget.TextView" resource-id="com.vivo:id/originui_vtoolbar_normal_title"'
            ' text="优质内容推送" bounds="[0,111][1080,360]"/>')
        self.assertEqual(decide.top_title(make(xml, focus=VIVO_FOCUS)), "优质内容推送")

    def test_a_wide_top_text_without_an_id_is_the_title(self):
        xml = page('<node class="android.widget.TextView" text="优质内容推送" bounds="[0,111][1080,360]"/>')
        self.assertEqual(decide.top_title(make(xml, focus=VIVO_FOCUS)), "优质内容推送")

    def test_a_narrow_or_low_top_text_is_not_a_title(self):
        narrow = page('<node class="android.widget.Button" content-desc="向上导航" bounds="[24,168][156,300]"/>')
        low = page(text("允许通知", "[0,397][1080,473]"))
        self.assertIsNone(decide.top_title(make(narrow, focus=VIVO_FOCUS)))
        self.assertIsNone(decide.top_title(make(low, focus=VIVO_FOCUS)))


class GroupFloorTests(unittest.TestCase):
    def test_the_category_header_gives_its_top_edge(self):
        self.assertEqual(decide.group_floor(make(CATEGORY_PAGE)), 700)
        self.assertIsNone(decide.group_floor(make(DEEP_PAGE)))

    def test_the_legacy_text_shape_is_the_same_judgement(self):
        texts = [(hit.text, hit.bounds, None) for hit in make(CATEGORY_PAGE).texts]
        self.assertEqual(decide.group_floor_of(texts), decide.group_floor(make(CATEGORY_PAGE)))
        self.assertEqual(chan.group_floor(texts), 700)


class OffScreenTests(unittest.TestCase):
    def test_a_name_below_the_screen_justifies_one_more_page(self):
        self.assertTrue(decide.off_screen_name(make(OFF_SCREEN_PAGE), NAME))

    def test_a_node_marked_invisible_is_not_off_screen(self):
        """折叠屏留下的另一块屏，翻页也看不到，不能拿它当「还有下一页」。"""
        self.assertFalse(decide.off_screen_name(make(HIDDEN_PAGE), NAME))
        self.assertFalse(decide.off_screen_name(make(APP_PAGE), NAME))


class AllowSwitchTests(unittest.TestCase):
    def test_the_title_comes_from_the_row(self):
        found = decide.allow_switches(make(DEEP_PAGE))
        self.assertEqual(found, [("允许通知", True, (948, 435))])

    def test_the_samsung_content_desc_fallback_is_a_second_source(self):
        found = decide.allow_switches(make(SAMSUNG_ALLOW_PAGE))
        self.assertEqual(found, [("允许通知", True, (948, 435))])


class InlineTests(unittest.TestCase):
    def test_the_unique_inline_row_is_recognised(self):
        got = decide.recognise_inline(make(INLINE_PAGE), NAME, APP_FOCUS)
        self.assertEqual(got.switch, (NAME, True, (970, 760)))
        self.assertEqual(got.why, "")

    def test_two_same_name_rows_are_refused_and_the_reason_is_kept(self):
        got = decide.recognise_inline(make(SAME_NAME_PAGE), NAME, APP_FOCUS)
        self.assertIsNone(got.switch)
        self.assertIn("同名 2 行", got.why)

    def test_a_row_with_the_app_master_switch_is_not_a_channel_row(self):
        got = decide.recognise_inline(make(INLINE_MASTER_PAGE), NAME, APP_FOCUS)
        self.assertIsNone(got.switch)
        self.assertIn("行内有应用总开关", got.why)

    def test_a_row_taller_than_the_limit_is_not_a_row(self):
        self.assertIsNone(decide.recognise_inline(make(TALL_ROW_PAGE), NAME, APP_FOCUS).switch)

    def test_the_switch_on_the_same_line_breaks_the_tie(self):
        """分组名借来的开关错开一整个行高：同一水平带上的那一行才是渠道行。"""
        got = decide.recognise_inline(make(GAP_PAGE), NAME, APP_FOCUS)
        self.assertEqual(got.switch, (NAME, True, (948, 1360)))

    def test_a_vivo_page_is_never_an_inline_page(self):
        self.assertIsNone(decide.recognise_inline(make(INLINE_PAGE, focus=VIVO_FOCUS),
                                                  NAME, VIVO_FOCUS).switch)


class CandidateTests(unittest.TestCase):
    def test_a_navigation_row_is_a_candidate(self):
        got = decide.candidates(make(APP_PAGE), NAME)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].bounds, (60, 720, 700, 800))
        self.assertEqual(got[0].boxes, ())

    def test_an_inline_row_carries_its_switch(self):
        got = decide.candidates(make(INLINE_PAGE), NAME)
        self.assertEqual(len(got[0].boxes), 1)

    def test_the_category_floor_hides_the_master_switch(self):
        snapshot = make(CATEGORY_PAGE)
        self.assertEqual([cand.bounds[1] for cand in decide.candidates(snapshot, NAME)], [610, 820])
        self.assertEqual([cand.bounds[1] for cand in decide.candidates(snapshot, NAME, floor=700)], [820])

    def test_a_page_without_the_name_has_no_candidates(self):
        self.assertEqual(decide.candidates(make(DEEP_PAGE), "别的渠道"), ())


class PageSwitchAndHintTests(unittest.TestCase):
    def test_page_switch_falls_back_to_the_inline_row(self):
        got = decide.page_switch(make(INLINE_PAGE), NAME, APP_FOCUS)
        self.assertEqual(got.switch[0], NAME)

    def test_page_switch_prefers_the_channel_page(self):
        got = decide.page_switch(make(DEEP_PAGE), NAME, DEEP_FOCUS)
        self.assertEqual(got.switch[0], "允许通知")

    def test_the_hint_counts_titles_and_switches(self):
        self.assertEqual(decide.page_hint(make(DEEP_PAGE), NAME), "标题顶部，允许通知开关 1 个，开关 1 个")
        self.assertEqual(decide.page_hint(make(APP_PAGE), NAME), "标题列表，允许通知开关 0 个，开关 0 个")


class NoRowsTests(unittest.TestCase):
    def test_without_rows_no_screenshot_is_taken_and_no_row_is_read(self):
        """自绘开关要在算行时截图：只认标题的路径传 with_rows=False，一次都不该取图。"""
        shot = Mock()
        bare = make(SELF_DRAWN_PAGE, with_rows=False, screenshot=shot)
        self.assertEqual(bare.rows, ())
        shot.assert_not_called()
        inline = make(INLINE_PAGE, with_rows=False, screenshot=shot)
        self.assertEqual(decide.recognise_inline(inline, NAME, APP_FOCUS).switch[0], NAME)
        shot.assert_not_called()

    def test_with_rows_the_self_drawn_switch_is_read_once(self):
        shot = Mock()
        shot.return_value.size = (1080, 2340)
        shot.return_value.convert.return_value.getpixel.return_value = (200, 0, 0)
        got = make(SELF_DRAWN_PAGE, with_rows=True, screenshot=shot)
        self.assertEqual(len(got.rows), 1)
        self.assertTrue(got.rows[0].checked)
        shot.assert_called_once()


def phone(pages, focus=APP_FOCUS):
    index = [0]

    def tree():
        return ET.fromstring(pages[min(index[0], len(pages) - 1)])

    def click(*_args):
        index[0] = min(index[0] + 1, len(pages) - 1)

    p = phone_stub("test", reader=Mock())
    p.W, p.H = 1080, 2340
    p.conn.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.screen.tree = tree
    p.screen.sig = Mock(return_value="")
    p.screen.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.click = Mock(side_effect=click)
    p.confirm = Mock()
    p.conn.reader = Mock()
    p.conn.reader.shell.return_value = Mock(output="")
    return p


class NoActionTests(unittest.TestCase):
    """认页/认行结论不对时一次都不点：点击桩的计数就是判据。"""

    def test_a_page_that_is_not_the_channel_page_is_not_clicked(self):
        p = phone([APP_PAGE])
        self.assertIsNone(chan.channel_switch(p, NAME, chan.Attempt()))
        p.click.assert_not_called()

    def test_the_channel_switch_is_returned_without_clicking(self):
        p = phone([DEEP_PAGE], focus=DEEP_FOCUS)
        self.assertEqual(chan.channel_switch(p, NAME, chan.Attempt())[0], "允许通知")
        p.click.assert_not_called()

    def test_the_master_only_page_is_reported_as_no_row_without_clicking(self):
        p = phone([MASTER_ONLY_PAGE])
        with patch.object(chan.time, "sleep"):
            got = chan.via_app_page(p, "com.example.app", NAME, chan.Attempt())
        self.assertIsNone(got)
        p.click.assert_not_called()

    def test_an_ambiguous_inline_page_is_not_clicked(self):
        p = phone([SAME_NAME_PAGE])
        self.assertIsNone(chan.inline_switch(p, NAME, chan.Attempt()))
        p.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
