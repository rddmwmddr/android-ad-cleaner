"""#422 「应用通知页没有打开」把三种情况混成了一句：页面真没开、宿主不认识（#415 那种）、
前台被别的应用占着（0.2.9 的报告里 174 次，红米一台机器 112 次停在 MaaFramework）。
判空时点名真实前台，报告者据此自己判断该先关哪个自动化工具。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
from fixtures import phone_stub

PK, CID, NAME = "com.example.app", "promo", "营销通知"
EMPTY = "<hierarchy><node/></hierarchy>"


def phone(focus):
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm, p.click = Mock(), Mock()
    p.screen.tree = Mock(return_value=ET.fromstring(EMPTY))
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.reader = Mock()
    p.reader.shell.return_value = Mock(output="")
    return p


def stage(focus):
    p = phone(focus)
    with patch.object(chan.time, "sleep"):
        reached = chan.ChannelPage(p, NAME, PK, CID).open()
    return reached.stage


class StageTests(unittest.TestCase):
    def test_empty_focus_keeps_the_old_wording(self):
        self.assertEqual(stage(""), "应用通知页没有打开")

    def test_target_app_in_front_is_named(self):
        got = stage(f"{PK}/{PK}.MainActivity")
        self.assertIn(f"前台是 {PK}，是这个应用自己", got)

    def test_settings_host_without_a_notification_page_is_named(self):
        got = stage("com.android.settings/.Settings")
        self.assertIn("前台是 com.android.settings，是系统设置但不是通知页", got)

    def test_third_party_app_in_front_is_named_with_its_package(self):
        # 红米 OS2.0.10 实测：112 次停在 MaaFramework。不猜它是谁，只点名包名
        got = stage("com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity")
        self.assertIn("前台是 com.aliothmoon.maafw.man，不是通知设置页", got)
        self.assertNotIn("暂停", got)          # 桌面和启动器也会落到这一类，不能一律叫用户去暂停

    def test_known_notify_host_with_an_unknown_activity_is_not_blamed_on_the_user(self):
        # 包名在通知宿主名单里、Activity 不在：多半是没见过的新系统。说成「不是通知设置页」
        # 会让用户去退出一个系统包；说成「就是通知设置页」又把白名单的判据反过来。只陈述事实
        got = stage("com.coloros.notificationmanager/.NotificationSettingsActivity")
        self.assertIn("前台是 com.coloros.notificationmanager，这个 Activity 没在已知列表里", got)

    def test_a_window_name_is_not_mistaken_for_a_package(self):
        # 通知栏拉下时 dumpsys 给的是窗口名，不是「包名/Activity」
        self.assertEqual(stage("NotificationShade"), "应用通知页没有打开")

    def test_stage_does_not_repeat_the_stopped_activity(self):
        # toggle() 的「停在 …」另读一次前台；stage 只解释为什么没到，不再写「停在」
        for focus in ("", f"{PK}/{PK}.MainActivity", "com.android.settings/.Settings",
                      "com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity"):
            self.assertNotIn("停在", stage(focus), focus)


class FocusReadTests(unittest.TestCase):
    def test_focus_read_is_kept_for_the_stage(self):
        # 判定与文案用同一次读数：不为文案再发一次 dumpsys
        focus = "com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity"
        page = chan.ChannelPage(phone(focus), NAME)
        self.assertEqual(page._focus(), "")
        self.assertEqual(page.raw_focus, focus)

    def test_stage_does_not_read_the_foreground_again(self):
        # 「不为文案再发一次 dumpsys」：文案只消费 _focus() 存下的那次读数
        p = phone("")
        page = chan.ChannelPage(p, NAME, PK, CID)
        page.raw_focus = "com.aliothmoon.maafw.man/com.aliothmoon.maafw.MainActivity"
        self.assertIn("前台是 com.aliothmoon.maafw.man", page._unopened_stage())
        p.screen.focus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
