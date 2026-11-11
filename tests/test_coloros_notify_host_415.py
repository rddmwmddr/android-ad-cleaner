"""#415 ColorOS 11/12（Android 10–12）的通知页宿主是 com.coloros.notificationmanager，
与 ColorOS 14+ 的 com.oplus.notificationmanager 是两个包。样本按报告者 OPPO PBDM00
（ColorOS 11 / Android 10）的真机 dump 结构造：渠道页顶栏是渠道名，唯一开关在它的行里；
应用通知页另有「允许通知」总开关，那颗开关不得被当成渠道开关。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
from fixtures import phone_stub

HOST = "com.coloros.notificationmanager"
CHANNEL_FOCUS = f"{HOST}/.ChannelNotificationSettingsActivity"
APP_FOCUS = f"{HOST}/.AppNotificationSettingsActivity"
NAME = "营销通知"

CHANNEL_PAGE = '''<hierarchy><node>
  <node text="营销通知" bounds="[100,120][600,200]"/>
  <node bounds="[0,300][1080,410]">
    <node text="允许通知" bounds="[60,320][600,390]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/>
  </node>
</node></hierarchy>'''

# 应用通知页：故意把渠道名也放在顶部、只留「允许通知」一个开关——这样的页面除了页面身份之外
# 和渠道页一模一样。放在 0.22H 以下是常态，但那样「标题在不在」那条判定先返回 None，
# 删掉 `_recognise()` 的 `"AppNotification" in focus` 守卫也照样绿，这条用例就守不住它。
APP_PAGE = '''<hierarchy><node>
  <node text="营销通知" bounds="[100,120][600,200]"/>
  <node bounds="[0,300][1080,410]">
    <node text="允许通知" bounds="[60,320][600,390]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/>
  </node>
</node></hierarchy>'''


def phone(xml, focus):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm, p.click = Mock(), Mock()
    p.screen.tree = Mock(return_value=ET.fromstring(xml))
    return p


class PageIdentityTests(unittest.TestCase):
    def test_channel_and_app_pages_are_recognised(self):
        # 两种 Activity 都要被 _focus() 认出来，否则整条渠道直接跳过
        for focus in (CHANNEL_FOCUS, APP_FOCUS,
                      f"{HOST}/{HOST}.ChannelNotificationSettingsActivity"):
            self.assertTrue(chan.notification_focus(phone(CHANNEL_PAGE, focus)), focus)

    def test_channel_page_switch_is_recognised(self):
        p = phone(CHANNEL_PAGE, CHANNEL_FOCUS)
        self.assertEqual(chan.channel_switch(p, NAME, chan.Attempt())[0], "允许通知")

    def test_app_page_is_refused_even_when_it_looks_like_a_channel_page(self):
        # 加了新宿主之后，App 通知页的「允许通知」总开关仍不得被当成渠道开关。
        # 去掉 _recognise() 的 `"AppNotification" in focus` 后这条必红（已实测）
        p = phone(APP_PAGE, APP_FOCUS)
        self.assertIsNone(chan.channel_switch(p, NAME, chan.Attempt()))

    def test_unknown_activity_and_lookalike_package_are_refused(self):
        for focus in (f"{HOST}/.NotificationSettingsActivity",
                      f"com.example.notificationmanager/{HOST}.ChannelNotificationSettingsActivity"):
            self.assertEqual(chan.notification_focus(phone(CHANNEL_PAGE, focus)), "", focus)


if __name__ == "__main__":
    unittest.main()
