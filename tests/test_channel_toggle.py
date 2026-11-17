"""渠道拨动的决定：能不能点、重试还是放弃、点后消失与灰态各自算什么。（#1436）

每个决定只吃一份快照（内联 XML 经 `snapshot_from_tree()` 装配）或快照里的一行，断言下一步与结局；
退避与重试次数的节奏留在执行侧，这里只证明决定函数数次数、不表达时间。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import channel_toggle as toggling
import screen_snapshot as snap

FOCUS = "com.android.settings/com.android.settings.Settings$ChannelNotificationSettingsActivity"
NAME = "营销通知"
XY = (948, 435)


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def text(value, area):
    return f'<node class="android.widget.TextView" text="{value}" bounds="{area}"/>'


def switch(area, checked=True, **attrs):
    extra = "".join(f' {key.replace("_", "-")}="{str(value).lower()}"'
                    for key, value in attrs.items())
    return ('<node class="android.widget.Switch" checkable="true"'
            f' checked="{str(checked).lower()}" bounds="{area}"{extra}/>')


def row(area, *children):
    return f'<node clickable="true" bounds="{area}">' + "".join(children) + "</node>"


def make(page_xml):
    return snap.snapshot_from_tree(ET.fromstring(page_xml), 1080, 2340, FOCUS)


# 渠道页：「允许通知」那一行带唯一开关，checked 是这一行现在开着
ON_PAGE = page(text(NAME, "[0,111][1080,360]"),
               row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"),
                   switch("[876,381][1020,489]", checked=True)))
OFF_PAGE = page(text(NAME, "[0,111][1080,360]"),
                row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"),
                    switch("[876,381][1020,489]", checked=False)))
# 系统锁定：开关灰了，点了也不会变（#333）
GREY_PAGE = page(text(NAME, "[0,111][1080,360]"),
                 row("[0,381][1080,489]", text("允许通知", "[0,397][342,473]"),
                     switch("[876,381][1020,489]", checked=True, enabled=False)))
# 点完之后这一行从列表里消失了：只剩页眉
VANISHED_PAGE = page(text(NAME, "[0,111][1080,360]"))


class ClickTests(unittest.TestCase):
    def test_a_row_already_at_the_target_is_not_clicked(self):
        self.assertTrue(toggling.can_click(make(OFF_PAGE).rows[0], True))
        self.assertFalse(toggling.can_click(make(ON_PAGE).rows[0], True))
        self.assertTrue(toggling.can_click(make(ON_PAGE).rows[0], False))
        self.assertFalse(toggling.can_click(make(OFF_PAGE).rows[0], False))


class RecheckTests(unittest.TestCase):
    def test_three_rechecks_retry_twice_then_give_up(self):
        row = make(ON_PAGE).rows[0]       # 点了三次，页面上的开关一次都没动
        got = [toggling.verdict(row, "ON", False, attempt, tries=3) for attempt in range(3)]
        self.assertEqual(got, [toggling.ToggleVerdict.RETRY, toggling.ToggleVerdict.RETRY,
                               toggling.ToggleVerdict.UNCHANGED])

    def test_the_retry_rhythm_is_the_callers_and_the_decision_never_watches_a_clock(self):
        row = make(ON_PAGE).rows[0]
        self.assertEqual([toggling.verdict(row, "ON", False, attempt, tries=2) for attempt in range(2)],
                         [toggling.ToggleVerdict.RETRY, toggling.ToggleVerdict.UNCHANGED])
        self.assertFalse(hasattr(toggling, "time"))

    def test_the_channel_record_winning_over_the_page_is_done(self):
        self.assertEqual(toggling.verdict(make(ON_PAGE).rows[0], "off", False, 0, tries=3),
                         toggling.ToggleVerdict.DONE)

    def test_a_page_that_matches_the_target_but_the_record_does_not_splits_on_the_app_switch(self):
        row = make(OFF_PAGE).rows[0]      # 页面上已经关着，渠道记录却还开着
        self.assertEqual(toggling.verdict(row, "ON", False, 0, tries=3),
                         toggling.ToggleVerdict.MISMATCH)
        self.assertEqual(toggling.verdict(row, "ON", False, 0, tries=3, denied=True),
                         toggling.ToggleVerdict.APP_DENIED)


class VanishedTests(unittest.TestCase):
    def test_a_row_gone_from_the_list_is_not_counted_as_closed(self):
        after = make(VANISHED_PAGE)
        self.assertEqual(after.rows, ())
        self.assertTrue(toggling.vanished(reached=False))
        self.assertFalse(toggling.vanished(reached=True))


class GreyedTests(unittest.TestCase):
    def test_a_disabled_row_is_greyed_and_a_healthy_one_is_not(self):
        grey = make(GREY_PAGE)
        self.assertTrue(toggling.greyed(grey, XY))
        self.assertTrue(grey.rows[0].disabled)      # 同一份判据：行上的灰态与 greyed() 一致
        self.assertFalse(toggling.greyed(make(ON_PAGE), XY))


class SideEffectTests(unittest.TestCase):
    def test_a_side_effect_stops_the_batch_and_only_undoes_when_the_row_was_clicked(self):
        self.assertFalse(toggling.side_effect_verdict([], clicked=True).stop)
        clicked = toggling.side_effect_verdict(["应用通知总开关"], clicked=True)
        self.assertTrue(clicked.stop)
        self.assertTrue(clicked.undo)
        untouched = toggling.side_effect_verdict(["应用通知总开关"], clicked=False)
        self.assertTrue(untouched.stop)
        self.assertFalse(untouched.undo)


if __name__ == "__main__":
    unittest.main()
