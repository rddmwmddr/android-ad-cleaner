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


# 系统界面（com.android.systemui）的文字与开关：`systemui_text` 为真时才算数
SYSTEM_SWITCH = ('<node package="com.android.systemui" class="android.widget.Switch"'
                 ' checkable="true" text="允许通知" checked="true" bounds="[876,381][1020,489]"/>')
SYSTEM_TITLE_PAGE = page(
    '<node package="com.android.systemui" class="android.widget.TextView"'
    f' text="{NAME}" bounds="[0,50][1080,120]"/>')
SYSTEM_ALLOW_PAGE = page(
    '<node package="com.android.systemui" class="android.widget.TextView"'
    f' text="{NAME}" bounds="[0,50][1080,120]"/>', SYSTEM_SWITCH)
SYSTEM_INLINE_PAGE = page(
    '<node package="com.android.systemui" clickable="true" bounds="[0,700][1080,860]">'
    '<node package="com.android.systemui" class="android.widget.TextView"'
    f' text="{NAME}" bounds="[60,720][700,800]"/>'
    '<node package="com.android.systemui" class="android.widget.Switch"'
    ' checkable="true" checked="true" bounds="[900,720][1040,800]"/></node>')


class VivoPageTests(unittest.TestCase):
    def test_only_the_vivo_hosts_with_the_channel_activity_are_vivo(self):
        self.assertTrue(decide.vivo_page("com.vivo.systemuiplugin/" + decide.VIVO_ACTIVITY))
        self.assertFalse(decide.vivo_page("com.example/" + decide.VIVO_ACTIVITY))
        self.assertFalse(decide.vivo_page(""))

    def test_an_extra_path_segment_keeps_the_vivo_host(self):
        """host 取第一个 `/` 之前那段：多出来的路径段不是包名。"""
        self.assertTrue(decide.vivo_page("com.vivo.systemuiplugin/extra/" + decide.VIVO_ACTIVITY))


class RootMessageTests(unittest.TestCase):
    def test_the_missing_tree_error_names_the_fix(self):
        bare = snap.ScreenSnapshot.from_json(make(DEEP_PAGE).to_json())
        with self.assertRaises(ValueError) as caught:
            decide.recognise(bare, NAME, DEEP_FOCUS)
        self.assertEqual(str(caught.exception),
                         "认页要页面树：先用 ScreenSnapshot.with_tree() 把 tree 装回")


class SystemuiTextTests(unittest.TestCase):
    """`systemui_text` 一路转发到读屏筛选：默认不算系统界面的文字，调用方显式要时才要。"""

    def test_top_title_reads_systemui_text_only_on_request(self):
        snapshot = make(SYSTEM_TITLE_PAGE)
        self.assertIsNone(decide.top_title(snapshot))
        self.assertEqual(decide.top_title(snapshot, True), NAME)

    def test_a_header_title_in_systemui_text_needs_the_flag(self):
        self.assertFalse(decide.recognised_page(make(SYSTEM_TITLE_PAGE), NAME, DEEP_FOCUS))
        self.assertTrue(decide.recognised_page(make(SYSTEM_TITLE_PAGE), NAME, DEEP_FOCUS,
                                               systemui_text=True))

    def test_the_systemui_switch_is_counted_without_a_flag(self):
        """`com.android.systemui` 的通知页就是渠道页本身：这里的开关不能按状态栏文字滤掉。"""
        self.assertEqual(decide.allow_switches(make(SYSTEM_ALLOW_PAGE)),
                         [("允许通知", True, (948, 435))])

    def test_recognise_forwards_the_flag_to_every_scan(self):
        snapshot = make(SYSTEM_ALLOW_PAGE)
        self.assertIsNone(decide.recognise(snapshot, NAME, DEEP_FOCUS).switch)
        self.assertEqual(decide.recognise(snapshot, NAME, DEEP_FOCUS, systemui_text=True).switch,
                         ("允许通知", True, (948, 435)))

    def test_candidates_read_systemui_text_only_on_request(self):
        snapshot = make(SYSTEM_INLINE_PAGE)
        self.assertEqual(decide.candidates(snapshot, NAME), ())
        self.assertEqual(len(decide.candidates(snapshot, NAME, True)), 1)

    def test_recognise_inline_reads_systemui_rows_only_on_request(self):
        snapshot = make(SYSTEM_INLINE_PAGE)
        self.assertIsNone(decide.recognise_inline(snapshot, NAME, APP_FOCUS).switch)
        self.assertEqual(decide.recognise_inline(snapshot, NAME, APP_FOCUS, True).switch[0], NAME)

    def test_page_switch_gives_the_vivo_check_the_app_name(self):
        snapshot = make(DEEP_PAGE, focus=VIVO_FOCUS)
        self.assertIsNone(decide.page_switch(snapshot, NAME, VIVO_FOCUS).switch)
        self.assertEqual(decide.page_switch(snapshot, NAME, VIVO_FOCUS, vivo_app=APP).switch[0],
                         "允许通知")

    def test_page_switch_forwards_the_flag_to_both_recognisers(self):
        channel = make(SYSTEM_ALLOW_PAGE)
        self.assertEqual(decide.page_switch(channel, NAME, DEEP_FOCUS, systemui_text=True).switch[0],
                         "允许通知")
        inline = make(SYSTEM_INLINE_PAGE)
        self.assertIsNone(decide.page_switch(inline, NAME, APP_FOCUS).switch)
        self.assertEqual(decide.page_switch(inline, NAME, APP_FOCUS, systemui_text=True).switch[0],
                         NAME)

    def test_page_hint_keeps_the_explicit_switch_total(self):
        self.assertIn("开关 5 个", decide.page_hint(make(DEEP_PAGE), NAME, total=5))


class TopTitleEdgeTests(unittest.TestCase):
    def test_a_title_id_without_the_toolbar_word_is_not_a_title(self):
        xml = page('<node class="android.widget.TextView" resource-id="com.example:id/title"'
                   ' text="优质内容推送" bounds="[0,50][300,120]"/>')
        self.assertIsNone(decide.top_title(make(xml, width=1000, height=1000)))

    def test_a_toolbar_title_exactly_on_the_band_edge_is_not_read(self):
        xml = page('<node class="android.widget.TextView"'
                   ' resource-id="com.vivo:id/originui_vtoolbar_normal_title"'
                   ' text="优质内容推送" bounds="[0,220][300,300]"/>')
        self.assertIsNone(decide.top_title(make(xml, width=1000, height=1000)))

    def test_a_toolbar_title_below_the_band_is_not_read(self):
        xml = page('<node class="android.widget.TextView"'
                   ' resource-id="com.vivo:id/originui_vtoolbar_normal_title"'
                   ' text="优质内容推送" bounds="[0,1000][300,1080]"/>')
        self.assertIsNone(decide.top_title(make(xml, width=1000, height=2000)))

    def test_the_highest_wide_text_wins(self):
        xml = page('<node class="android.widget.TextView" text="上面" bounds="[0,50][950,120]"/>',
                   '<node class="android.widget.TextView" text="下面" bounds="[100,60][900,140]"/>')
        self.assertEqual(decide.top_title(make(xml, width=1000, height=1000)), "上面")

    def test_the_widest_of_two_texts_on_one_line_wins(self):
        xml = page('<node class="android.widget.TextView" text="窄" bounds="[0,50][900,120]"/>',
                   '<node class="android.widget.TextView" text="宽" bounds="[50,50][1000,130]"/>')
        self.assertEqual(decide.top_title(make(xml, width=1000, height=1000)), "宽")

    def test_a_text_too_narrow_to_be_the_title_is_skipped(self):
        """左边界参与宽度判定：只按 left+right 会把一段窄字当成整屏宽。"""
        xml = page('<node class="android.widget.TextView" text="窄条" bounds="[1200,50][1900,120]"/>')
        self.assertIsNone(decide.top_title(make(xml, width=2000, height=1000)))

    def test_the_left_edge_breaks_a_width_tie(self):
        xml = page('<node class="android.widget.TextView" text="A" bounds="[0,50][950,120]"/>',
                   '<node class="android.widget.TextView" text="B" bounds="[100,50][1000,130]"/>')
        self.assertEqual(decide.top_title(make(xml, width=1000, height=1000)), "A")

    def test_the_top_edge_breaks_a_width_tie(self):
        xml = page('<node class="android.widget.TextView" text="A" bounds="[0,50][950,120]"/>',
                   '<node class="android.widget.TextView" text="B" bounds="[50,50][900,180]"/>')
        self.assertEqual(decide.top_title(make(xml, width=1000, height=1000)), "A")

    def test_a_tall_wide_text_is_still_the_title(self):
        xml = page('<node class="android.widget.TextView" text="标题" bounds="[0,100][850,140]"/>')
        self.assertEqual(decide.top_title(make(xml, width=1000, height=1000)), "标题")

    def test_a_text_exactly_at_the_width_edge_is_wide_enough(self):
        xml = page('<node class="android.widget.TextView" text="标题" bounds="[0,50][800,120]"/>')
        self.assertEqual(decide.top_title(make(xml, width=1000, height=1000)), "标题")

    def test_a_text_exactly_at_the_top_band_edge_is_not_a_title(self):
        xml = page('<node class="android.widget.TextView" text="标题" bounds="[0,150][1000,200]"/>')
        self.assertIsNone(decide.top_title(make(xml, width=1000, height=1000)))


class BandEdgeTests(unittest.TestCase):
    def test_titled_ignores_a_title_exactly_on_the_top_band_edge(self):
        xml = page(text(NAME, "[0,220][1080,300]"))
        self.assertFalse(decide.titled(make(xml, height=1000), NAME))

    def test_page_hint_calls_a_title_on_the_edge_missing(self):
        xml = page(text(NAME, "[0,220][1080,300]"))
        self.assertEqual(decide.page_hint(make(xml, height=1000), NAME),
                         "标题列表，允许通知开关 0 个，开关 0 个")

    def test_a_title_exactly_on_the_top_band_edge_is_not_recognised(self):
        xml = page(text(NAME, "[0,220][1080,300]"))
        self.assertFalse(decide.recognised_page(make(xml, height=1000), NAME, DEEP_FOCUS))

    def test_a_header_title_exactly_on_the_header_band_edge_is_rejected(self):
        xml = page('<node class="android.widget.TextView"'
                   ' resource-id="android:id/entity_header_title"'
                   f' text="{NAME}" bounds="[0,400][1080,500]"/>')
        self.assertFalse(decide.recognised_page(make(xml, height=1000), NAME, DEEP_FOCUS))

    def test_the_vivo_check_compares_the_systemui_toolbar_title(self):
        focus = "com.android.systemui/" + decide.VIVO_ACTIVITY
        xml = page('<node package="com.android.systemui" class="android.widget.TextView"'
                   ' resource-id="com.android.systemui:id/originui_vtoolbar_normal_title"'
                   f' text="{NAME}" bounds="[0,50][1080,120]"/>')
        snapshot = make(xml)
        self.assertFalse(decide.recognised_page(snapshot, NAME, focus, vivo_app=APP))
        self.assertTrue(decide.recognised_page(snapshot, NAME, focus, vivo_app=APP,
                                               systemui_text=True))


class CandidateEdgeTests(unittest.TestCase):
    def test_a_candidate_exactly_on_the_group_floor_is_kept(self):
        got = decide.candidates(make(CATEGORY_PAGE), NAME, floor=820)
        self.assertEqual([cand.bounds[1] for cand in got], [820])

    def test_a_candidate_carries_the_row_container(self):
        got = decide.candidates(make(APP_PAGE), NAME)
        self.assertEqual(got[0].row.get("clickable"), "true")


class OffScreenEdgeTests(unittest.TestCase):
    def test_only_node_elements_are_read(self):
        xml = ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
               f'<label text="{NAME}" bounds="[60,2420][700,2500]"/>'
               '<label checkable="true" text="允许通知" checked="true" bounds="[876,381][1020,489]"/>'
               "</node></hierarchy>")
        self.assertFalse(decide.off_screen_name(make(xml), NAME))
        self.assertEqual(decide.allow_switches(make(xml)), [])

    def test_a_name_exactly_on_the_screen_edge_is_off_screen(self):
        xml = page(text(APP, "[0,111][1080,360]"), text(NAME, "[60,2340][700,2420]"))
        self.assertTrue(decide.off_screen_name(make(xml), NAME))

    def test_an_off_screen_name_read_from_content_desc_still_counts(self):
        xml = page(text(APP, "[0,111][1080,360]"),
                   f'<node content-desc="{NAME}" bounds="[60,2420][700,2500]"/>')
        self.assertTrue(decide.off_screen_name(make(xml), NAME))


class AllowSwitchEdgeTests(unittest.TestCase):
    def test_a_checkable_content_desc_allow_switch_is_counted(self):
        xml = page('<node class="android.widget.Switch" checkable="true" content-desc="允许通知"'
                   ' checked="true" bounds="[876,381][1020,489]"/>')
        self.assertEqual(decide.allow_switches(make(xml)), [("允许通知", True, (948, 435))])

    def test_text_wins_over_content_desc_on_the_same_node(self):
        xml = page('<node class="android.widget.Switch" checkable="true" text="允许通知"'
                   ' content-desc="别的文字" checked="true" bounds="[876,381][1020,489]"/>')
        self.assertEqual(decide.allow_switches(make(xml)), [("允许通知", True, (948, 435))])

    def test_a_padded_label_is_still_the_allow_label(self):
        xml = page('<node checkable="true" text=" 允许通知 " checked="true"'
                   ' bounds="[876,381][1020,489]"/>')
        self.assertEqual(decide.allow_switches(make(xml))[0][0], "允许通知")

    def test_coordinates_are_integers(self):
        for snapshot in (make(DEEP_PAGE), make(SAMSUNG_ALLOW_PAGE)):
            found = decide.allow_switches(snapshot)
            self.assertIsInstance(found[0][2][0], int)
            self.assertIsInstance(found[0][2][1], int)

    def test_a_radio_button_is_not_a_switch(self):
        xml = page('<node class="android.widget.RadioButton" checkable="true" text="允许通知"'
                   ' bounds="[876,381][1020,489]"/>')
        self.assertEqual(decide.allow_switches(make(xml)), [])

    def test_a_switch_without_a_class_but_with_text_is_counted(self):
        xml = page('<node checkable="true" text="允许通知" checked="true"'
                   ' bounds="[876,381][1020,489]"/>')
        self.assertEqual(decide.allow_switches(make(xml)), [("允许通知", True, (948, 435))])

    def test_the_same_switch_read_twice_on_one_line_is_counted_once(self):
        xml = page(
            text(NAME, "[0,111][1080,360]"),
            row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"),
                switch("[876,381][1020,489]")),
            '<node class="android.widget.Switch" checkable="true" content-desc="允许通知"'
            ' checked="true" bounds="[876,381][1020,489]"/>')
        self.assertEqual(len(decide.allow_switches(make(xml))), 1)

    def test_a_switch_exactly_one_line_away_is_a_second_switch(self):
        """`ImageView` 这种形状不算开关行（`switch_row_data` 只收 Switch / CheckBox 一族），
        只在开关扫描里出现：与行内开关正好差 `SAME_LINE` 时仍算第二个。"""
        xml = page(
            text(NAME, "[0,111][1080,360]"),
            row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"),
                switch("[876,381][1020,489]")),
            '<node class="android.widget.ImageView" checkable="true" content-desc="允许通知"'
            ' checked="true" bounds="[876,411][1020,519]"/>')
        self.assertEqual(len(decide.allow_switches(make(xml))), 2)


class InlineReasonTests(unittest.TestCase):
    """`recognise_inline()` 失败时的人话：哪一行、为什么、数了几行。"""

    def test_a_name_without_a_row_says_where_it_was_read(self):
        got = decide.recognise_inline(make(page(text(NAME, "[0,700][700,800]"))), NAME, APP_FOCUS)
        self.assertTrue(got.why.startswith("没找到所在行；结构 "), got.why)
        self.assertIn("TextView", got.why)

    def test_a_page_without_the_name_has_no_reason_detail(self):
        got = decide.recognise_inline(make(DEEP_PAGE), "不存在的渠道", APP_FOCUS)
        self.assertEqual(got.why, "同名 0 行")

    def test_an_allow_label_or_an_empty_name_is_never_an_inline_row(self):
        page_xml = page(text(NAME, "[0,111][1080,360]"),
                        row("[0,700][1080,860]", text("允许通知", "[60,720][700,800]"),
                            switch("[900,720][1040,800]")))
        allowed = decide.recognise_inline(make(page_xml), "允许通知", APP_FOCUS)
        self.assertEqual((allowed.switch, allowed.why), (None, ""))
        blank = decide.recognise_inline(make(INLINE_PAGE), "", APP_FOCUS)
        self.assertEqual((blank.switch, blank.why), (None, ""))

    def test_without_a_focus_an_inline_row_is_not_read(self):
        self.assertIsNone(decide.recognise_inline(make(INLINE_PAGE), NAME).switch)
        self.assertIsNone(decide.page_switch(make(INLINE_PAGE), NAME).switch)

    def test_several_same_name_rows_join_their_reasons(self):
        got = decide.recognise_inline(make(SAME_NAME_PAGE), NAME, APP_FOCUS)
        self.assertIn(" | ", got.why)
        self.assertIn("行高 7%", got.why)
        self.assertIn("文字与开关错开 0px", got.why)
        self.assertNotIn("XX", got.why)

    def test_a_rejected_row_keeps_its_switch_count_and_loses_the_gap(self):
        got = decide.recognise_inline(make(TALL_ROW_PAGE), NAME, APP_FOCUS)
        self.assertIn("行内开关 1 个", got.why)
        self.assertNotIn("错开", got.why)
        self.assertNotIn("行内有应用总开关", got.why)
        self.assertNotIn("XXXX", got.why)

    def test_the_master_switch_text_is_named_in_the_reason(self):
        got = decide.recognise_inline(make(INLINE_MASTER_PAGE), NAME, APP_FOCUS)
        self.assertIn("行内有应用总开关", got.why)
        self.assertNotIn("XX", got.why)

    def test_at_most_three_reasons_are_listed(self):
        rows = "".join(
            row(f"[0,{700 + i * 200}][1080,{860 + i * 200}]",
                text(NAME, f"[60,{720 + i * 200}][700,{800 + i * 200}]"),
                switch(f"[900,{720 + i * 200}][1040,{800 + i * 200}]"))
            for i in range(4))
        got = decide.recognise_inline(make(page(text(APP, "[0,111][1080,360]"), rows)),
                                      NAME, APP_FOCUS)
        self.assertEqual(got.why.count(" | "), 2)

    def test_a_row_exactly_at_the_inline_height_limit_is_a_row(self):
        tall = row("[0,700][1080,1168]", text(NAME, "[60,720][700,800]"),
                   switch("[900,720][1040,800]"))
        got = decide.recognise_inline(make(page(text(APP, "[0,111][1080,360]"), tall)),
                                      NAME, APP_FOCUS)
        self.assertEqual(got.switch, (NAME, True, (970, 760)))

    def test_the_row_height_percentage_uses_the_screen_height(self):
        rows = "".join(
            row(f"[0,{800 + i * 200}][1080,{905 + i * 200}]",
                text(NAME, f"[60,{820 + i * 200}][700,{880 + i * 200}]"),
                switch(f"[900,{820 + i * 200}][1040,{880 + i * 200}]"))
            for i in range(2))
        got = decide.recognise_inline(make(page(text(APP, "[0,111][1080,360]"), rows)),
                                      NAME, APP_FOCUS)
        self.assertIn("行高 4%", got.why)

    def test_a_row_read_twice_is_a_single_candidate(self):
        twice = row("[0,700][1080,860]", text(NAME, "[60,720][700,800]"),
                    text(NAME, "[60,720][700,780]"), switch("[900,720][1040,800]"))
        got = decide.recognise_inline(make(page(text(APP, "[0,111][1080,360]"), twice)),
                                      NAME, APP_FOCUS)
        self.assertEqual(got.switch, (NAME, True, (970, 760)))
        self.assertIsInstance(got.switch[2][1], int)

    def test_a_duplicate_in_the_first_row_does_not_hide_the_second_row(self):
        first = row("[0,700][1080,860]", text(NAME, "[60,720][700,800]"),
                    text(NAME, "[60,740][700,820]"))
        second = row("[0,900][1080,1060]", text(NAME, "[60,920][700,1000]"),
                     switch("[900,920][1040,1000]"))
        got = decide.recognise_inline(
            make(page(text(APP, "[0,111][1080,360]"), first, second)), NAME, APP_FOCUS)
        self.assertEqual(got.switch, (NAME, True, (970, 960)))
        self.assertIsInstance(got.switch[2][0], int)

    def test_the_same_line_switch_wins_an_exact_gap(self):
        """两次同名的行里，只有隔离开关一行高的那一行 gap 超过容差。"""
        boundary = row("[0,700][1080,860]", text(NAME, "[0,700][700,780]"),
                       switch("[876,780][1020,860]"))
        far = row("[0,900][1080,1180]", text(NAME, "[0,900][700,980]"),
                  switch("[876,1100][1020,1180]"))
        got = decide.recognise_inline(
            make(page(text(APP, "[0,111][1080,360]"), far, boundary)), NAME, APP_FOCUS)
        self.assertEqual(got.switch, (NAME, True, (948, 820)))


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
