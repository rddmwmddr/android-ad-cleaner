"""#510 华为 HarmonyOS 4 的 dump 会把同一个节点吐出两次（resource-id、文字、坐标全同）。
读屏层按节点身份计数时把它当成两行，应用通知页的渠道行于是报「同名 2 行」认不出。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
import row
from fixtures import phone_stub

APP_FOCUS = "com.android.settings/.Settings$AppNotificationSettingsActivity"
NAME = "营销通知"


def channel_row(y):
    """应用通知页里的一条内联渠道行：标题 + 自带开关，整行可点。"""
    return (f'<node class="android.widget.LinearLayout" bounds="[40,{y}][1040,{y + 200}]">'
            f'<node resource-id="android:id/title" text="{NAME}" bounds="[80,{y + 40}][500,{y + 100}]"/>'
            f'<node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true"'
            f' bounds="[900,{y + 60}][1000,{y + 140}]"/></node>')


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            '<node text="示例应用" bounds="[60,100][600,200]"/>'
            '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"'
            ' bounds="[0,300][1080,2200]">' + "".join(nodes) + "</node></node></hierarchy>")


def phone(xml):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.focus = Mock(return_value=APP_FOCUS)
    p.tree = Mock(return_value=ET.fromstring(xml))
    return p


class DuplicateRowTests(unittest.TestCase):
    def test_the_same_row_twice_is_one_row(self):
        # 整行子树重复一次，坐标完全相同：这是同一个开关，不是两个同名行
        at = chan.Attempt()
        self.assertEqual(chan.inline_switch(phone(page(channel_row(880), channel_row(880))), NAME, at),
                         (NAME, True, (950, 980)))
        self.assertEqual(at.why, "")

    def test_two_rows_at_different_places_stay_ambiguous(self):
        # 真的两行同名、各带开关：仍然放弃，不能因为去重把这类歧义也吞掉（#287 的判据）
        at = chan.Attempt()
        self.assertIsNone(chan.inline_switch(phone(page(channel_row(880), channel_row(1000))), NAME, at))
        self.assertIn("同名 2 行", at.why)

    def test_a_switch_dumped_twice_is_one_switch(self):
        # 整行只出现一次，重复的是开关本身：同一个坐标上的同一个控件，不能读成「行内开关 2 个」
        twice = (f'<node class="android.widget.LinearLayout" bounds="[40,880][1040,1080]">'
                 f'<node resource-id="android:id/title" text="{NAME}" bounds="[80,920][500,980]"/>'
                 f'<node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true"'
                 f' bounds="[900,940][1000,1020]"/>'
                 f'<node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true"'
                 f' bounds="[900,940][1000,1020]"/></node>')
        at = chan.Attempt()
        self.assertEqual(chan.inline_switch(phone(page(twice)), NAME, at), (NAME, True, (950, 980)))
        self.assertEqual(at.why, "")


class SummaryTests(unittest.TestCase):
    def test_the_structure_summary_counts_a_duplicated_control_once(self):
        # 上报里的「标题 N 个，开关 M 个」也不能被重复节点翻倍
        got = row.summary(ET.fromstring(page(channel_row(880), channel_row(880))), 1080, 2340)
        self.assertIn("标题 1 个，开关 1 个", got)


class TextsDedupeTests(unittest.TestCase):
    def test_a_duplicate_is_counted_once(self):
        p = phone(page(channel_row(880), channel_row(880)))
        self.assertEqual([t for t, _, _ in p.texts()], ["示例应用", NAME])

    def test_a_different_resource_id_is_a_different_node(self):
        xml = page(
            f'<node resource-id="android:id/title" text="{NAME}" bounds="[80,920][500,980]"/>',
            f'<node resource-id="android:id/summary" text="{NAME}" bounds="[80,920][500,980]"/>')
        self.assertEqual(len(phone(xml).texts()), 3)      # 示例应用 + 两个各不相同的节点

    def test_a_different_place_is_a_different_node(self):
        xml = page(
            f'<node resource-id="android:id/title" text="{NAME}" bounds="[80,920][500,980]"/>',
            f'<node resource-id="android:id/title" text="{NAME}" bounds="[80,1220][500,1280]"/>')
        self.assertEqual(len(phone(xml).texts()), 3)

    def test_a_duplicate_must_still_be_on_screen(self):
        # 折叠屏合上时内屏那份节点在同一坐标、同样重复：去重不能让它绕过在屏判定
        xml = page(
            f'<node resource-id="android:id/title" text="{NAME}" bounds="[80,920][500,980]"/>',
            f'<node resource-id="android:id/title" text="{NAME}" visible-to-user="false"'
            ' bounds="[80,920][500,980]"/>')
        self.assertEqual([t for t, _, _ in phone(xml).texts()], ["示例应用", NAME])


if __name__ == "__main__":
    unittest.main()
