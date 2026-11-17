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


class NotificationDumpTests(unittest.TestCase):
    def test_the_pure_parser_returns_channels_apps_and_both_evidence_sets(self):
        channels, app_off, locked, foreground = snap.parse_notification_dump(DUMP)
        self.assertEqual(channels[("com.example.app", "promo")], ("营销通知", 3, False))
        self.assertEqual(channels[("com.other", "gone")], ("已删", 0, True))
        self.assertEqual(app_off, {"com.example.app": True, "com.other": False})
        self.assertEqual(locked, {("com.example.app", "locked")})
        self.assertEqual(foreground, {("com.example.app", "fg")})

    def test_a_dump_without_the_preferences_section_is_refused(self):
        with self.assertRaises(RuntimeError):
            snap.parse_notification_dump("no notification preferences here")

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
