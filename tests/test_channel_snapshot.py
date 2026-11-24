"""屏幕快照 / 通知清单 / 意图 / 进度四个值类型：构造、JSON 往返，以及每个意图种类只经基座唯一执行点落地（#1432）。

#1432 只建接缝；#1434 起认页判定消费快照（见 `tests/test_channel_decide.py`），
这里只守值类型本身。
"""
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import chan_fast as chan
import screen_snapshot as snap
from fixtures import phone_stub, screen_stub

PAGE = """<hierarchy rotation="0">
 <node package="com.android.systemui" class="android.widget.TextView" text="12:00" bounds="[0,0][1080,80]"/>
 <node package="com.android.settings" class="android.widget.TextView" text="通知" bounds="[0,120][1080,240]"/>
 <node package="com.android.settings" clickable="true" bounds="[0,300][1080,420]">
  <node class="android.widget.TextView" text="营销通知" bounds="[60,320][600,400]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" clickable="true" bounds="[900,300][1060,420]"/>
 </node>
 <node package="com.android.settings" clickable="true" enabled="false" bounds="[0,440][1080,560]">
  <node class="android.widget.TextView" text="系统锁定" bounds="[60,460][600,540]"/>
  <node class="android.widget.Switch" checkable="true" checked="false" clickable="true" bounds="[900,440][1060,560]"/>
 </node>
</hierarchy>"""

SCROLLABLE_PAGE = """<hierarchy rotation="0">
 <node package="com.android.settings" class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,0][1080,2340]"/>
</hierarchy>"""

FOCUS = "com.android.settings/.SubSettings"

DUMP = """Notification Settings:
  PackagePreferences:
    AppSettings: com.example.app (10123) importance=NONE fixedImportance=true
      NotificationChannel{mId='promo', mName=营销通知, mDescription=x mImportance=3 mDeleted=false}
      NotificationChannel{mId='locked', mName=特权, mDescription=x mImportance=3 mDeleted=false} mBlockableSystem=false
      NotificationChannel{mId='fg', mName=常驻, mDescription=x mImportance=2 mDeleted=false} mFgServiceShown=true
    AppSettings: com.other (10124) importance=IMPORTANCE_DEFAULT
      NotificationChannel{mId='gone', mName=已删, mDescription=x mImportance=0 mDeleted=true}
"""


def make_snapshot(page=PAGE, **kwargs):
    return snap.snapshot_from_tree(ET.fromstring(page), 1080, 2340, FOCUS, **kwargs)


def tree(xml):
    return ET.fromstring(xml)


def self_drawn_page(area="[10,20][90,60]", *extra):
    """一页只有自绘开关（resource-id 带 switch、没有 checkable），可选追加别的节点。"""
    return tree('<hierarchy>'
                f'<node clickable="true" resource-id="app:id/switch_view" bounds="{area}"/>'
                + "".join(extra) + "</hierarchy>")


def solid(width, height, colour):
    return Image.new("RGB", (width, height), colour)


class OnScreenTests(unittest.TestCase):
    """折叠屏另一块屏的副本、退化盒子与中心落点的取舍（Issue #2）。"""

    def on(self, area, width=1080, height=2340, **attrs):
        extra = "".join(f' {key.replace("_", "-")}="{value}"' for key, value in attrs.items())
        return snap.on_screen(tree(f'<node bounds="{area}"{extra}/>'), width, height)

    def test_a_node_marked_invisible_is_off_screen_even_inside_the_window(self):
        self.assertFalse(self.on("[10,10][100,100]", visible_to_user="false"))
        self.assertTrue(self.on("[10,10][100,100]"))

    def test_a_box_without_area_is_off_screen(self):
        self.assertFalse(self.on("[10,10][10,100]"))
        self.assertFalse(self.on("[10,10][100,10]"))

    def test_a_centre_on_the_near_edge_still_counts(self):
        self.assertTrue(self.on("[0,0][1,1]"))

    def test_a_centre_exactly_on_the_far_edge_does_not(self):
        # 中心 (999+1001)//2 = 1000 正好等于屏幕宽 / 高
        self.assertFalse(self.on("[999,0][1001,2]", width=1000, height=10))
        self.assertFalse(self.on("[0,999][2,1001]", width=10, height=1000))


class TextHitTests(unittest.TestCase):
    def test_the_status_bar_text_is_excluded_unless_asked_for(self):
        root = tree('<hierarchy><node package="com.android.systemui" text="12:00"'
                    ' bounds="[0,0][100,50]"/></hierarchy>')
        self.assertEqual(snap.text_hits(root, 1080, 2340), [])
        self.assertEqual([hit[0] for hit in snap.text_hits(root, 1080, 2340, systemui_text=True)],
                         ["12:00"])

    def test_only_node_elements_are_read(self):
        root = tree('<hierarchy text="根上的字" bounds="[0,0][10,10]">'
                    '<node text="营销通知" bounds="[0,0][100,50]"/></hierarchy>')
        self.assertEqual([hit[0] for hit in snap.text_hits(root, 1080, 2340)], ["营销通知"])


class CanScrollTests(unittest.TestCase):
    def test_the_flag_alone_marks_the_page_scrollable(self):
        self.assertTrue(snap.can_scroll(tree('<hierarchy><node scrollable="true"'
                                             ' bounds="[0,0][10,10]"/></hierarchy>')))

    def test_a_list_container_class_alone_marks_the_page_scrollable(self):
        self.assertTrue(snap.can_scroll(tree('<hierarchy><node class="android.widget.ListView"'
                                             ' bounds="[0,0][10,10]"/></hierarchy>')))
        self.assertFalse(snap.can_scroll(tree('<hierarchy><node class="android.widget.TextView"'
                                              ' bounds="[0,0][10,10]"/></hierarchy>')))

    def test_a_scrollable_flag_on_a_non_node_element_does_not_count(self):
        self.assertFalse(snap.can_scroll(tree('<hierarchy scrollable="true" bounds="[0,0][10,10]"/>')))


class PixelOnTests(unittest.TestCase):
    """开关轨道取样：盒子边界、RGB 通道、取样位置与阈值。"""

    def image(self, colour, mode="RGB"):
        return Image.new(mode, (100, 100), colour)

    def test_a_box_on_the_screen_edges_is_still_sampled(self):
        self.assertIsNotNone(snap.pixel_on(self.image("blue"), 0, 0, 100, 100))

    def test_a_degenerate_or_out_of_bounds_box_is_unknown(self):
        shot = self.image("blue")
        for box in ((50, 0, 50, 100), (0, 50, 100, 50), (0, 0, 101, 100), (0, 0, 100, 101)):
            with self.subTest(box=box):
                self.assertIsNone(snap.pixel_on(shot, *box))

    def test_the_threshold_is_strictly_above_sixty(self):
        self.assertFalse(snap.pixel_on(self.image((60, 60, 0)), 0, 0, 100, 100))
        self.assertTrue(snap.pixel_on(self.image((61, 61, 0)), 0, 0, 100, 100))

    def test_the_saturation_reads_every_channel(self):
        for colour in ((0, 200, 0), (200, 0, 200), (0, 200, 200), (20, 70, 0)):
            with self.subTest(colour=colour):
                self.assertTrue(snap.pixel_on(self.image(colour), 0, 0, 100, 100))

    def test_a_grey_track_with_a_large_sum_is_still_off(self):
        self.assertFalse(snap.pixel_on(self.image((100, 100, 100)), 0, 0, 100, 100))

    def test_an_rgba_screenshot_is_read_by_its_rgb_channels(self):
        self.assertTrue(snap.pixel_on(self.image((200, 0, 0, 255), mode="RGBA"), 0, 0, 100, 100))
        self.assertFalse(snap.pixel_on(self.image((128, 128, 128, 255), mode="RGBA"), 0, 0, 100, 100))

    def test_the_samples_follow_the_box_and_its_middle_row(self):
        # 盒子 [10,20][90,80] 的三个取样点是 x=30/50/70、y=50；别的位置彩色都不该被读到
        shot = self.image((120, 120, 120))
        shot.putpixel((90, 50), (200, 0, 0))
        self.assertFalse(snap.pixel_on(shot, 10, 20, 90, 80))
        shot.putpixel((30, 50), (200, 0, 0))
        self.assertTrue(snap.pixel_on(shot, 10, 20, 90, 80))


class FocusSplitTests(unittest.TestCase):
    def test_the_first_slash_splits_the_package_from_the_activity(self):
        got = snap.snapshot_from_tree(tree(PAGE), 1080, 2340, "com.a/.B/C")
        self.assertEqual((got.package, got.activity), ("com.a", ".B/C"))

    def test_a_focus_without_an_activity_leaves_it_empty(self):
        got = snap.snapshot_from_tree(tree(PAGE), 1080, 2340, "com.a")
        self.assertEqual((got.package, got.activity), ("com.a", ""))


class JsonDefaultTests(unittest.TestCase):
    def load(self, **data):
        bare = {"package": "p", "activity": "a", "width": 1, "height": 2,
                "signature": "", "can_scroll": False}
        bare.update(data)
        return snap.ScreenSnapshot.from_json(bare)

    def test_a_row_without_the_optional_flags_is_neither_clickable_nor_grey(self):
        got = self.load(rows=[{"title": "营销通知", "bounds": [0, 0, 10, 10]}])
        self.assertEqual(got.rows, (snap.Row(title="营销通知", bounds=(0, 0, 10, 10),
                                             checked=None, clickable=False, disabled=False),))

    def test_a_snapshot_without_the_row_or_text_lists_restores_them_empty(self):
        got = self.load()
        self.assertEqual((got.rows, got.texts), ((), ()))


class ValueTypeTests(unittest.TestCase):
    def test_progress_starts_empty_and_instances_do_not_share_state(self):
        a, b = snap.Progress(), snap.Progress()
        a.tapped.add("营销通知")
        a.failed_ways.add("not_confirmed")
        self.assertEqual((b.tapped, b.failed_ways, b.pages, b.last_signature), (set(), set(), 0, ""))
        self.assertEqual(a.tapped, {"营销通知"})

    def test_snapshot_carries_no_progress(self):
        names = {f.name for f in fields(snap.ScreenSnapshot)}
        self.assertNotIn("progress", names)
        self.assertNotIn("tapped", names)
        self.assertTrue({"package", "activity", "width", "height", "rows", "texts",
                         "signature", "can_scroll"} <= names)

    def test_intent_kinds_are_the_closed_seven(self):
        self.assertEqual([kind.value for kind in snap.IntentKind],
                         ["tap", "scroll", "back", "open", "home", "type", "settings"])

    def test_channel_list_keeps_channels_and_sets_apart(self):
        entry = snap.ChannelEntry("营销通知", 3, False)
        value = snap.ChannelList(channels={("pk", "cid"): entry}, app_off={"pk": False},
                                 locked=frozenset({("pk", "cid")}), foreground=frozenset())
        self.assertEqual(value.channels[("pk", "cid")], entry)
        self.assertEqual(value.locked, frozenset({("pk", "cid")}))
        self.assertEqual(value.foreground, frozenset())


class SnapshotTests(unittest.TestCase):
    def test_texts_signature_and_focus_come_from_one_tree(self):
        snapshot = make_snapshot()
        self.assertEqual((snapshot.package, snapshot.activity),
                         ("com.android.settings", ".SubSettings"))
        self.assertEqual([hit.text for hit in snapshot.texts], ["通知", "营销通知", "系统锁定"])
        self.assertEqual(snapshot.signature, "通知|营销通知|系统锁定")
        self.assertEqual((snapshot.width, snapshot.height), (1080, 2340))

    def test_systemui_text_is_opt_in_like_texts(self):
        self.assertNotIn("12:00", [hit.text for hit in make_snapshot().texts])
        self.assertIn("12:00", [hit.text for hit in make_snapshot(systemui_text=True).texts])

    def test_rows_carry_title_bounds_checked_clickable_and_grey(self):
        rows = make_snapshot().rows
        self.assertEqual([row.title for row in rows], ["营销通知", "系统锁定"])
        self.assertEqual(rows[0].bounds, (900, 300, 1060, 420))
        self.assertTrue(rows[0].checked)
        self.assertTrue(rows[0].clickable)
        self.assertEqual((rows[1].checked, rows[1].disabled), (False, True))

    def test_can_scroll_reads_scrollable_and_list_classes(self):
        self.assertFalse(make_snapshot().can_scroll)
        self.assertTrue(make_snapshot(SCROLLABLE_PAGE).can_scroll)

    def test_rows_match_switch_rows(self):
        base = screen_stub(PAGE, size=(1080, 2340))
        base.systemui_text = False
        base.focus = Mock(return_value=FOCUS)
        snapshot = base.snapshot()
        self.assertEqual([(row.title, row.checked) for row in snapshot.rows],
                         [(title, on) for title, on, _, _ in base.switch_rows()])

    def test_snapshot_reads_the_tree_and_the_focus_once(self):
        base = screen_stub(PAGE, size=(1080, 2340))
        base.systemui_text = False
        base.tree = Mock(return_value=ET.fromstring(PAGE))
        base.focus = Mock(return_value=FOCUS)
        snapshot = base.snapshot()
        self.assertEqual((base.tree.call_count, base.focus.call_count), (1, 1))
        self.assertEqual(snapshot, make_snapshot())


class SnapshotJsonTests(unittest.TestCase):
    def test_a_snapshot_round_trips_through_json_without_the_tree(self):
        snapshot = make_snapshot()
        data = snapshot.to_json()
        self.assertNotIn("tree", data)
        json.dumps(data)                                # json.dumps 能直接吃
        restored = snap.ScreenSnapshot.from_json(json.loads(json.dumps(data)))
        self.assertEqual(restored, snapshot)
        self.assertIsNone(restored.tree)

    def test_with_tree_puts_the_parsed_tree_back(self):
        root = ET.fromstring(PAGE)
        snapshot = make_snapshot().with_tree(root)
        self.assertIs(snapshot.tree, root)
        self.assertEqual(snapshot, make_snapshot())     # tree 不参与相等

    def test_intents_round_trip_by_kind(self):
        cases = [snap.Intent(snap.IntentKind.TAP, at=(10, 20)),
                 snap.Intent(snap.IntentKind.SCROLL),
                 snap.Intent(snap.IntentKind.BACK),
                 snap.Intent(snap.IntentKind.OPEN, target="https://example.com/渠道"),
                 snap.Intent(snap.IntentKind.HOME),
                 snap.Intent(snap.IntentKind.TYPE, text="营销通知"),
                 snap.Intent(snap.IntentKind.SETTINGS, target="android.settings.CHANNEL_NOTIFICATION_SETTINGS",
                             extras=(("android.provider.extra.APP_PACKAGE", "com.example.app"),
                                     ("android.provider.extra.CHANNEL_ID", "promo")))]
        for intent in cases:
            with self.subTest(kind=intent.kind):
                restored = snap.Intent.from_json(json.loads(json.dumps(intent.to_json())))
                self.assertEqual(restored, intent)

    def test_an_intent_can_be_built_from_a_bare_dict(self):
        self.assertEqual(snap.Intent.from_json({"kind": "tap", "at": [1, 2]}),
                         snap.Intent(snap.IntentKind.TAP, at=(1, 2)))
        self.assertEqual(snap.Intent.from_json({"kind": "home"}),
                         snap.Intent(snap.IntentKind.HOME))


class SwitchRowReadTests(unittest.TestCase):
    """`switch_row_data()` 的边界：自绘开关的惰性取图、类名词表、退化盒子与可点判据。"""

    W, H = 1080, 2340

    def rows(self, xml, screenshot=None):
        return snap.switch_row_data(tree(xml), self.W, self.H, screenshot)

    def shot(self, colour):
        return lambda: solid(self.W, self.H, colour)

    def test_a_switch_class_node_without_the_clickable_flag_is_still_a_row(self):
        rows = self.rows('<hierarchy><node class="android.widget.Switch" checkable="true" checked="true"'
                         ' bounds="[10,10][90,50]"/></hierarchy>')
        self.assertEqual([(title, on) for title, on, *_ in rows], [("", True)])

    def test_every_class_keyword_in_the_list_is_recognised(self):
        classes = ("android.widget.Switch", "android.widget.CheckBox",
                   "android.widget.ToggleButton", "android.widget.CompoundButton")
        body = "".join(f'<node class="{name}" checkable="true" checked="true"'
                       f' bounds="[10,{10 + 40 * index}][90,{40 + 40 * index}]"/>'
                       for index, name in enumerate(classes))
        self.assertEqual(len(self.rows(f"<hierarchy>{body}</hierarchy>")), len(classes))

    def test_a_class_that_is_not_a_switch_is_skipped_without_stopping_the_scan(self):
        rows = self.rows('<hierarchy>'
                         '<node class="android.view.View" checkable="true" bounds="[10,10][90,50]"/>'
                         '<node class="android.widget.Switch" checkable="true" bounds="[10,60][90,100]"/>'
                         '</hierarchy>')
        self.assertEqual(len(rows), 1)

    def test_a_box_without_area_is_skipped_without_stopping_the_scan(self):
        for area in ("[10,20][10,60]", "[10,20][90,20]"):
            with self.subTest(area=area):
                rows = self.rows('<hierarchy>'
                                 f'<node class="android.widget.Switch" checkable="true" bounds="{area}"/>'
                                 '<node class="android.widget.Switch" checkable="true" bounds="[10,120][90,160]"/>'
                                 '</hierarchy>')
                self.assertEqual(len(rows), 1)

    def test_a_self_drawn_candidate_without_a_screenshot_is_skipped_without_stopping(self):
        page = ('<hierarchy><node clickable="true" resource-id="app:id/switch_view"'
                ' bounds="[10,20][90,60]"/>'
                '<node class="android.widget.Switch" checkable="true" bounds="[10,120][90,160]"/>'
                '</hierarchy>')
        self.assertEqual(len(self.rows(page)), 1)

    def test_a_screenshot_of_another_size_leaves_the_candidate_unknown_without_stopping(self):
        page = ('<hierarchy><node clickable="true" resource-id="app:id/switch_view"'
                ' bounds="[10,20][90,60]"/>'
                '<node class="android.widget.Switch" checkable="true" bounds="[10,120][90,160]"/>'
                '</hierarchy>')
        self.assertEqual(len(self.rows(page, lambda: solid(1, 1, (200, 0, 0)))), 1)

    def test_a_degenerate_self_drawn_candidate_does_not_take_a_screenshot(self):
        shot = Mock()
        rows = self.rows('<hierarchy><node clickable="true" resource-id="app:id/switch_view"'
                         ' bounds="[10,20][10,60]"/></hierarchy>', shot)
        self.assertEqual(rows, [])
        shot.assert_not_called()

    def test_a_one_pixel_thin_self_drawn_switch_is_still_read(self):
        for area in ("[10,20][11,60]", "[10,20][90,21]"):
            with self.subTest(area=area):
                rows = self.rows(f'<hierarchy><node clickable="true" resource-id="app:id/switch_view"'
                                 f' bounds="{area}"/></hierarchy>', self.shot((200, 0, 0)))
                self.assertEqual(len(rows), 1)

    def test_the_self_drawn_track_colour_decides_on_and_off(self):
        on = snap.switch_row_data(self_drawn_page(), self.W, self.H, self.shot((200, 0, 0)))
        off = snap.switch_row_data(self_drawn_page(), self.W, self.H, self.shot((128, 128, 128)))
        self.assertEqual([on[0][1], off[0][1]], [True, False])

    def test_a_self_drawn_container_holding_a_real_switch_is_not_guessed_by_colour(self):
        # AOSP 渠道页的 main_switch_bar：外层按颜色猜会盖过里面那个真开关
        page = ('<hierarchy><node clickable="true" resource-id="app:id/main_switch_bar"'
                ' bounds="[0,300][100,400]">'
                '<node class="android.widget.Switch" checkable="true" checked="false" clickable="true"'
                ' bounds="[10,310][90,390]"/></node></hierarchy>')
        shot = Mock()
        shot.return_value = solid(self.W, self.H, (200, 0, 0))
        rows = snap.switch_row_data(tree(page), self.W, self.H, shot)
        self.assertEqual([on for _, on, *_ in rows], [False])
        shot.assert_not_called()

    def test_only_node_elements_become_rows(self):
        rows = self.rows('<hierarchy class="android.widget.Switch" checkable="true"'
                         ' bounds="[10,10][90,50]">'
                         '<node class="android.widget.TextView" text="标题" bounds="[10,60][90,100]"/>'
                         '</hierarchy>')
        self.assertEqual(rows, [])

    def test_a_real_switch_with_a_self_drawn_id_is_not_sent_to_the_colour_path(self):
        # 真开关（checkable）哪怕资源 id 长得像自绘开关，也不该走截图那一支：没给截图时它仍是行
        rows = self.rows('<hierarchy><node class="android.widget.Switch" checkable="true" checked="true"'
                         ' clickable="true" resource-id="app:id/switch_view"'
                         ' bounds="[10,20][90,60]"/></hierarchy>')
        self.assertEqual([on for _, on, *_ in rows], [True])

    def test_a_non_node_child_does_not_suppress_the_colour_path(self):
        page = ('<hierarchy><node clickable="true" resource-id="app:id/switch_view"'
                ' bounds="[10,20][90,60]"><extra checkable="true"/></node></hierarchy>')
        rows = snap.switch_row_data(tree(page), self.W, self.H, self.shot((200, 0, 0)))
        self.assertEqual([on for _, on, *_ in rows], [True])

    def test_a_self_drawn_candidate_with_children_is_still_read(self):
        page = ('<hierarchy><node clickable="true" resource-id="app:id/switch_view"'
                ' bounds="[10,20][90,60]"><node class="android.widget.TextView" text="开"'
                ' bounds="[20,30][40,50]"/></node></hierarchy>')
        rows = snap.switch_row_data(tree(page), self.W, self.H, self.shot((200, 0, 0)))
        self.assertEqual([on for _, on, *_ in rows], [True])


class RowClickabilityTests(unittest.TestCase):
    W, H = 1080, 2340

    def rows(self, xml):
        return snap.rows_from_tree(tree(xml), self.W, self.H)

    def test_a_clickable_control_is_clickable(self):
        rows = self.rows('<hierarchy><node clickable="true" checkable="true" bounds="[10,10][90,50]">'
                         '<node class="android.widget.Switch" clickable="true" bounds="[10,10][40,50]"/>'
                         '</node></hierarchy>')
        self.assertEqual([row.clickable for row in rows], [True])

    def test_a_checkable_control_without_the_clickable_flag_is_clickable(self):
        rows = self.rows('<hierarchy><node clickable="true" checkable="true" bounds="[10,10][90,50]">'
                         '<node class="android.widget.Switch" checkable="true" bounds="[10,10][40,50]"/>'
                         '</node></hierarchy>')
        self.assertEqual([row.clickable for row in rows], [True])

    def test_a_control_with_neither_flag_is_not_clickable(self):
        rows = self.rows('<hierarchy><node clickable="true" checkable="true" bounds="[10,10][90,50]">'
                         '<node class="android.widget.Switch" bounds="[10,10][40,50]"/>'
                         '</node></hierarchy>')
        self.assertEqual([row.clickable for row in rows], [False])

    def test_the_grey_check_uses_the_rounded_centre_of_the_control(self):
        # 开关的取整中心是 (950, 350)：右边缘正好落在这一格的灰态节点仍算命中
        rows = self.rows('<hierarchy>'
                         '<node class="android.widget.Switch" checkable="true" checked="true"'
                         ' clickable="true" bounds="[900,300][1001,401]"/>'
                         '<node checkable="true" enabled="false" bounds="[940,300][950,350]"/>'
                         '</hierarchy>')
        self.assertEqual([row.disabled for row in rows], [True])


class NotificationDumpTests(unittest.TestCase):
    def test_the_pure_parser_returns_channels_apps_and_both_evidence_sets(self):
        channels, app_off, locked, foreground = snap.parse_notification_dump(DUMP)
        self.assertEqual(channels[("com.example.app", "promo")], ("营销通知", 3, False))
        self.assertEqual(channels[("com.other", "gone")], ("已删", 0, True))
        self.assertEqual(app_off, {"com.example.app": True, "com.other": False})
        self.assertEqual(locked, {("com.example.app", "locked")})
        self.assertEqual(foreground, {("com.example.app", "fg")})

    def test_a_dump_without_the_preferences_section_is_refused(self):
        with self.assertRaises(RuntimeError) as caught:
            snap.parse_notification_dump("no notification preferences here")
        self.assertEqual(str(caught.exception),
                         "读不到通知渠道状态，停止操作；请检查 USB 调试连接和系统权限")

    def test_the_first_preferences_section_is_the_one_read(self):
        first = DUMP.splitlines()[:4]
        doubled = "\n".join(first + ["  PackagePreferences:",
                                     "    AppSettings: com.other (10124) importance=NONE",
                                     "      NotificationChannel{mId='later', mName=后来的, mDescription=x"
                                     " mImportance=3 mDeleted=false}"]) + "\n"
        channels = snap.parse_notification_dump(doubled)[0]
        self.assertEqual(list(channels), [("com.example.app", "promo"), ("com.other", "later")])

    def test_an_app_settings_line_with_a_uid_of_work_profile_size_is_not_user_zero(self):
        work = ("PackagePreferences:\n"
                "    AppSettings: com.work (100000) importance=NONE\n"
                "      NotificationChannel{mId='promo', mName=营销通知, mDescription=x"
                " mImportance=3 mDeleted=false}\n")
        self.assertEqual(snap.parse_notification_dump(work), ({}, {}, set(), set()))

    def test_a_later_reading_does_not_override_a_valid_record_with_a_deleted_one(self):
        dump = ("PackagePreferences:\n"
                "    AppSettings: com.example.app importance=DEFAULT\n"
                "      NotificationChannel{mId='promo', mName=旧名, mDescription=x mImportance=3"
                " mDeleted=true}\n"
                "      NotificationChannel{mId='promo', mName=新名, mDescription=x mImportance=5"
                " mDeleted=true}\n")
        self.assertEqual(snap.parse_notification_dump(dump)[0][("com.example.app", "promo")],
                         ("旧名", 3, True))

    def test_a_deleted_reading_is_replaced_by_a_live_one(self):
        dump = ("PackagePreferences:\n"
                "    AppSettings: com.example.app importance=DEFAULT\n"
                "      NotificationChannel{mId='promo', mName=旧名, mDescription=x mImportance=0"
                " mDeleted=true}\n"
                "      NotificationChannel{mId='promo', mName=新名, mDescription=x mImportance=3"
                " mDeleted=false}\n")
        self.assertEqual(snap.parse_notification_dump(dump)[0][("com.example.app", "promo")],
                         ("新名", 3, False))

    def test_two_live_readings_keep_the_first_one(self):
        dump = ("PackagePreferences:\n"
                "    AppSettings: com.example.app importance=DEFAULT\n"
                "      NotificationChannel{mId='promo', mName=旧名, mDescription=x mImportance=5"
                " mDeleted=false}\n"
                "      NotificationChannel{mId='promo', mName=新名, mDescription=x mImportance=3"
                " mDeleted=false}\n")
        self.assertEqual(snap.parse_notification_dump(dump)[0][("com.example.app", "promo")],
                         ("旧名", 5, False))

    def test_the_first_old_section_name_is_the_one_read(self):
        dump = ("per-package config:\n"
                "    AppSettings: com.old.app importance=NONE\n"
                "      NotificationChannel{mId='promo', mName=旧段, mDescription=x mImportance=3"
                " mDeleted=false}\n"
                "per-package config:\n"
                "    AppSettings: com.new.app importance=NONE\n"
                "      NotificationChannel{mId='promo', mName=新段, mDescription=x mImportance=3"
                " mDeleted=false}\n")
        self.assertEqual(list(snap.parse_notification_dump(dump)[0]),
                         [("com.old.app", "promo"), ("com.new.app", "promo")])

    def test_a_muted_reading_is_replaced_by_a_non_zero_importance_one(self):
        dump = ("PackagePreferences:\n"
                "    AppSettings: com.example.app importance=DEFAULT\n"
                "      NotificationChannel{mId='promo', mName=旧名, mDescription=x mImportance=0"
                " mDeleted=false}\n"
                "      NotificationChannel{mId='promo', mName=新名, mDescription=x mImportance=1"
                " mDeleted=false}\n")
        self.assertEqual(snap.parse_notification_dump(dump)[0][("com.example.app", "promo")],
                         ("新名", 1, False))

    def test_chan_fast_parse_still_fills_the_same_out_parameters(self):
        p = phone_stub("test")
        p.conn.reader = SimpleNamespace(shell=Mock(return_value=SimpleNamespace(output=DUMP)))
        locked, foreground = set(), set()
        channels, app_off = chan.parse(p.conn.reader, locked, foreground)
        self.assertEqual((channels, app_off), snap.parse_notification_dump(DUMP)[:2])
        self.assertEqual(locked, {("com.example.app", "locked")})
        self.assertEqual(foreground, {("com.example.app", "fg")})

    def test_read_channel_list_is_one_round_trip(self):
        reader = Mock()
        reader.shell.return_value = SimpleNamespace(output=DUMP)
        value = snap.read_channel_list(reader)
        reader.shell.assert_called_once_with("dumpsys notification --noredact", timeout=60)
        self.assertIsInstance(value, snap.ChannelList)
        self.assertEqual(value.channels[("com.example.app", "promo")],
                         snap.ChannelEntry("营销通知", 3, False))
        self.assertEqual(value.locked, frozenset({("com.example.app", "locked")}))
        self.assertEqual(value.foreground, frozenset({("com.example.app", "fg")}))


class IntentApplyTests(unittest.TestCase):
    def base(self):
        base = screen_stub()
        base.conn = SimpleNamespace(reader=Mock())
        for name in ("click", "scroll", "back", "open_uri", "home", "type_text", "start_settings"):
            setattr(base, name, Mock())
        return base

    def test_every_kind_lands_on_exactly_one_base_action(self):
        cases = [(snap.Intent(snap.IntentKind.TAP, at=(7, 9)), "click", (7, 9)),
                 (snap.Intent(snap.IntentKind.SCROLL), "scroll", ()),
                 (snap.Intent(snap.IntentKind.BACK), "back", ()),
                 (snap.Intent(snap.IntentKind.OPEN, target="https://example.com"), "open_uri",
                  ("https://example.com",)),
                 (snap.Intent(snap.IntentKind.HOME), "home", ()),
                 (snap.Intent(snap.IntentKind.TYPE, text="营销通知"), "type_text", ("营销通知",)),
                 (snap.Intent(snap.IntentKind.SETTINGS, target="android.settings.APP_NOTIFICATION_SETTINGS",
                              extras=(("android.provider.extra.APP_PACKAGE", "com.example.app"),)),
                  "start_settings",
                  ("android.settings.APP_NOTIFICATION_SETTINGS",
                   (("android.provider.extra.APP_PACKAGE", "com.example.app"),)))]
        for intent, action, args in cases:
            with self.subTest(kind=intent.kind):
                base = self.base()
                base.apply(intent)
                getattr(base, action).assert_called_once_with(*args)
                for other in ("click", "scroll", "back", "open_uri", "home", "type_text", "start_settings"):
                    if other != action:
                        getattr(base, other).assert_not_called()

    def test_the_settings_intent_sends_the_same_am_start_line(self):
        """深链表与重构前逐字相同：参数按给定顺序、值按 shell 规则引用。"""
        base = screen_stub()
        base.conn = SimpleNamespace(reader=Mock())
        base.apply(snap.Intent(snap.IntentKind.SETTINGS,
                               target="android.settings.CHANNEL_NOTIFICATION_SETTINGS",
                               extras=(("android.provider.extra.APP_PACKAGE", "com.example.app"),
                                       ("android.provider.extra.CHANNEL_ID", "a b"))))
        self.assertEqual(base.conn.reader.shell.call_args.args[0],
                         "am start -f 0x10008000 -a android.settings.CHANNEL_NOTIFICATION_SETTINGS"
                         " --es android.provider.extra.APP_PACKAGE com.example.app"
                         " --es android.provider.extra.CHANNEL_ID 'a b'")

    def test_tap_without_coordinates_is_refused(self):
        with self.assertRaises(ValueError):
            self.base().apply(snap.Intent(snap.IntentKind.TAP))

    def test_open_uri_quotes_the_uri(self):
        base = screen_stub()
        base.conn = SimpleNamespace(reader=Mock())
        base.open_uri("https://example.com/a b")
        self.assertEqual(base.conn.reader.shell.call_args.args[0],
                         "am start -a android.intent.action.VIEW -d 'https://example.com/a b'")

    def test_home_sends_the_home_key(self):
        base = screen_stub()
        base.conn = SimpleNamespace(reader=Mock())
        base.home()
        base.conn.reader.shell.assert_called_once_with("input keyevent HOME")

    def test_type_text_targets_the_focused_edit_box_with_a_timeout(self):
        base = screen_stub()
        reader = Mock()
        reader.return_value = SimpleNamespace(selector="SEL")
        reader.jsonrpc = Mock()
        base.conn = SimpleNamespace(reader=reader)
        base.type_text("营销通知", timeout=2.5)
        reader.assert_called_once_with(classNameMatches=r".*(EditText|AutoCompleteTextView)$",
                                       focused=True)
        reader.jsonrpc.setText.assert_called_once_with("SEL", "营销通知", http_timeout=2.5)


class FacadeForwardingTests(unittest.TestCase):
    def test_phone_forwards_snapshot_and_apply(self):
        p = phone_stub("test")
        p.screen.snapshot = Mock(return_value="SNAP")
        p.screen.apply = Mock()
        intent = snap.Intent(snap.IntentKind.HOME)
        self.assertEqual(p.snapshot(), "SNAP")
        p.apply(intent)
        p.screen.apply.assert_called_once_with(intent)

    def test_phone_produces_a_channel_list_from_its_reader(self):
        p = phone_stub("test")
        p.conn.reader = SimpleNamespace(shell=Mock(return_value=SimpleNamespace(output=DUMP)))
        self.assertEqual(p.channel_list().app_off, {"com.example.app": True, "com.other": False})


if __name__ == "__main__":
    unittest.main()
