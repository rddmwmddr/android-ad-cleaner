"""#582 渠道失败行带上包名，MISMATCH 另附一条判据读数：同名渠道分属不同 App 时能区分。

结局、退出码、点击行为一个字不动 —— 这里只测「事后取证」那部分。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
from fixtures import EMPTY_PAGE, SIZES, Clock, fake_phone, install_clock

SETTINGS_FOCUS = "com.android.settings/.Settings"     # 认不出通知页，走「未确认」出口


def phone():
    """一页读不出渠道的假设备：读取按假时钟走，卡在「应用通知页没有打开」。"""
    clock = Clock()
    p = fake_phone(clock=clock, size=SIZES[0], stages=((0.0, EMPTY_PAGE),),
                   focus=((0.0, SETTINGS_FOCUS),))
    original = chan.time
    install_clock(chan, clock)
    return p, original


class PackageOnFailureLineTests(unittest.TestCase):
    def setUp(self):
        self.p, original = phone()
        self.addCleanup(setattr, chan, "time", original)

    def toggle(self, pk, cid="promo", name="运营消息"):
        parsed = ({(pk, cid): (name, 3, False)}, {})
        with patch.object(chan, "parse", return_value=parsed):
            return chan.toggle(self.p, pk, cid, False, name)

    def line(self, outcome, pk, name="运营消息"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            chan.show(outcome, name, False, pk)
        return buf.getvalue().strip()

    def test_the_same_channel_name_in_two_packages_prints_two_different_packages(self):
        browser = self.toggle("com.vivo.browser")
        store = self.toggle("com.vivo.themestore")
        self.assertEqual(browser.kind, chan.NOT_CONFIRMED)
        self.assertEqual(store.kind, chan.NOT_CONFIRMED)
        first, second = self.line(browser, "com.vivo.browser"), self.line(store, "com.vivo.themestore")
        self.assertTrue(first.startswith("✗"), first)
        self.assertIn("运营消息（com.vivo.browser）", first)
        self.assertIn("运营消息（com.vivo.themestore）", second)
        self.assertNotEqual(first, second)


class MismatchProbeTests(unittest.TestCase):
    def setUp(self):
        self.p, original = phone()
        self.addCleanup(setattr, chan, "time", original)

    def mismatch(self, cid, pk="com.vivo.browser", importance=3):
        parsed = ({(pk, cid): ("运营消息", importance, False)}, {})
        switch = ("运营消息", False, (500, 800))      # 页面上已经是关的
        with patch.object(chan, "parse", return_value=parsed), \
             patch.object(chan.ChannelPage, "open", return_value=chan.Reached(switch)), \
             patch.object(chan.ChannelPage, "refresh", return_value=chan.Reached(switch)):
            return chan.toggle(self.p, pk, cid, False, "运营消息")

    def test_the_mismatch_line_names_the_package(self):
        outcome = self.mismatch("VPushChannel_0")
        self.assertEqual(outcome.kind, chan.MISMATCH)
        self.assertIn("运营消息（com.vivo.browser）",
                      chan.render(outcome, "运营消息", False, "com.vivo.browser"))

    def test_the_probe_line_carries_channel_id_importance_and_the_app_level_answer(self):
        outcome = self.mismatch("VPushChannel_0", importance=3)
        self.assertEqual(outcome.payload,
                         "mismatch\tcom.vivo.browser\tVPushChannel_0"
                         "\timportance=3\tapp_notifications=allowed")
        # 「页面关着、记录开着」差的就是这一项
        self.assertEqual(self.mismatch("VPushChannel_4", importance=4).payload.split("\t")[3],
                         "importance=4")

    def test_the_probe_stops_after_the_per_run_cap(self):
        payloads = [self.mismatch(f"ch{i}").payload for i in range(chan.MISMATCH_PER_RUN + 1)]
        self.assertEqual(len([x for x in payloads if x]), chan.MISMATCH_PER_RUN)
        self.assertEqual(payloads[-1], "")


class ShowTests(unittest.TestCase):
    def test_the_probe_goes_out_as_a_payload_line_not_part_of_the_failure_line(self):
        outcome = chan.Outcome(chan.MISMATCH, "界面状态与渠道实际状态不一致，未继续点击",
                               "mismatch\tcom.x\tpromo\timportance=3\tapp_notifications=allowed")
        buf = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(buf):
            os.environ["AAC_EVENTS"] = "1"
            chan.show(outcome, "运营消息", False, "com.x")
        lines = buf.getvalue().splitlines()
        self.assertEqual(lines[0], "  ✗ 界面状态与渠道实际状态不一致，未继续点击  运营消息（com.x）")
        self.assertEqual(lines[1],
                         "#aac:payload mismatch\tcom.x\tpromo\timportance=3\tapp_notifications=allowed")


if __name__ == "__main__":
    unittest.main()
