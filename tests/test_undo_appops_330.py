"""#330 华为 ALN-AL00：点回后要复核受影响渠道的最终状态；访问应用通知页把
POST_NOTIFICATION 从 default 改成 allow 时按窄条件写回。不用手机。"""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
from fixtures import phone_stub

FOCUS = "com.android.settings/.Settings$ChannelNotificationSettingsActivity"

CHANNEL_PAGE = '''<hierarchy><node>
  <node text="营销通知" bounds="[100,120][600,200]"/>
  <node bounds="[0,300][1080,410]">
    <node text="允许通知" bounds="[60,320][600,390]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/>
  </node>
</node></hierarchy>'''


def page():
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.focus = Mock(return_value=FOCUS)
    p.confirm = Mock()
    p.click = Mock()
    p.tree = Mock(return_value=ET.fromstring(CHANNEL_PAGE))
    return p


def flip_on_click(p):
    """点一下就翻页面上所有开关：模拟「点了这一行，别的渠道跟着变了」。"""
    def flip(*_):
        for node in p.tree().iter():
            if node.get("checkable") == "true":
                node.set("checked", "false" if node.get("checked") == "true" else "true")
    p.click.side_effect = flip


def snap(target_on=True, other_on=True, app_off=False, extra=None):
    d = {("com.example", "promo"): ("营销通知", 3 if target_on else 0, False),
         ("com.example", "order"): ("订单通知", 3 if other_on else 0, False)}
    d.update(extra or {})
    return d, {"com.example": app_off}


@patch.object(chan.time, "sleep")
class UndoRecheckTests(unittest.TestCase):
    def toggle(self, snapshots):
        p = page()
        flip_on_click(p)
        with patch.object(chan, "parse", side_effect=snapshots):
            with self.assertRaises(chan.StopBatch) as caught:
                chan.toggle(p, "com.example", "promo", False, "营销通知")
        return p, str(caught.exception)

    def test_recheck_passes_only_after_reading_the_channels_back(self, _sleep):
        p, message = self.toggle([snap(), snap(target_on=False, other_on=False),
                                  snap(target_on=True, other_on=True)])
        self.assertEqual(p.click.call_count, 2)
        self.assertIn("订单通知", message)
        self.assertIn("已点回并复核通过", message)

    def test_channels_that_did_not_come_back_are_named(self, _sleep):
        _, message = self.toggle([snap(), snap(target_on=False, other_on=False),
                                  snap(target_on=True, other_on=False)])
        self.assertIn("复核仍有差异：渠道「订单通知」", message)
        self.assertIn("没能完全恢复", message)
        self.assertNotIn("复核通过", message)

    def test_app_master_switch_difference_after_undo_is_named(self, _sleep):
        _, message = self.toggle([snap(), snap(target_on=False, other_on=False),
                                  snap(target_on=True, other_on=True, app_off=True)])
        self.assertIn("应用通知总开关", message)
        self.assertIn("没能完全恢复", message)

    def test_recheck_that_cannot_read_says_so_instead_of_claiming_restored(self, _sleep):
        _, message = self.toggle([snap(), snap(target_on=False, other_on=False),
                                  RuntimeError("读不到通知渠道状态")])
        self.assertIn("复核失败", message)
        self.assertIn("无法确认已恢复", message)

    def test_link_lost_during_recheck_says_it_could_not_verify(self, _sleep):
        _, message = self.toggle([snap(), snap(target_on=False, other_on=False),
                                  adb_link.DeviceLost("device offline")])
        self.assertIn("没能核对", message)

    def test_channel_that_appears_after_the_click_is_named(self, _sleep):
        _, message = self.toggle([snap(), snap(target_on=False, other_on=False),
                                  snap(target_on=True, other_on=True,
                                       extra={("com.example", "new"): ("新渠道", 3, False)})])
        self.assertIn("新增渠道「新渠道」", message)
        self.assertIn("没能完全恢复", message)

    def test_no_click_is_not_reported_as_a_failed_undo(self, _sleep):
        _, apps = snap()
        message, lost = chan.undo_message(page(), snap()[0], apps, {("com.example", "promo")},
                                          False, ["渠道「订单通知」"], clicked=False)
        self.assertIn("本次没有点击这一行", message)
        self.assertNotIn("没能自动点回", message)
        self.assertFalse(lost)

    def test_normal_toggle_keeps_its_two_full_reads(self, _sleep):
        p = page()
        with patch.object(chan, "parse", side_effect=[snap(), snap(target_on=False)]) as parse:
            self.assertEqual(chan.toggle(p, "com.example", "promo", False, "营销通知").kind, chan.DONE)
        self.assertEqual(parse.call_count, 2)


class FakeReader:
    """cmd appops 替身：get 返回模式，set 修改模式（可以装作写不进去）。"""

    def __init__(self, modes, write_fails=(), read_fails=(), lost=()):
        self.modes = dict(modes)
        self.write_fails, self.read_fails, self.lost = set(write_fails), set(read_fails), set(lost)
        self.writes = []
        self.d = self

    def shell(self, command, timeout=60):
        if not command.startswith("cmd appops "):
            return Mock(output="")
        parts = command.split()
        package = parts[3]
        if parts[:3] == ["cmd", "appops", "get"]:
            if package in self.lost:
                raise adb_link.DeviceLost("device offline")
            if package in self.read_fails:
                raise RuntimeError("adb 读取失败")
            mode = self.modes.get(package)
            return Mock(output="No operations." if mode is None else f"POST_NOTIFICATION: {mode}\n")
        self.writes.append(command)
        if package in self.write_fails:
            raise RuntimeError("adb 写入失败")
        self.modes[package] = "default"
        return Mock(output="")


class AppOpsTests(unittest.TestCase):
    def test_default_to_allow_is_written_back_and_verified(self):
        reader = FakeReader({"com.a": "allow"})
        changed, failed = chan.restore_appops(reader, {"com.a": "default"})
        self.assertEqual((changed, failed), (["com.a"], []))
        self.assertEqual(reader.modes["com.a"], "default")
        self.assertEqual(len(reader.writes), 1)

    def test_only_default_to_allow_is_written(self):
        modes = {"com.a": "allow", "com.b": "allow", "com.c": "allow", "com.d": "allow"}
        reader = FakeReader(modes)
        before = {"com.a": "allow", "com.b": "deny", "com.c": "ignore", "com.d": "unknown"}
        self.assertEqual(chan.restore_appops(reader, before), ([], []))
        self.assertEqual(reader.writes, [])

    def test_mode_that_is_still_default_is_left_alone(self):
        reader = FakeReader({"com.a": "default"})
        self.assertEqual(chan.restore_appops(reader, {"com.a": "default"}), ([], []))
        self.assertEqual(reader.writes, [])

    def test_unreadable_mode_is_not_written(self):
        reader = FakeReader({}, read_fails={"com.a"})
        self.assertEqual(chan.restore_appops(reader, {"com.a": "default"}), ([], []))
        self.assertEqual(reader.writes, [])

    def test_failed_write_is_reported(self):
        reader = FakeReader({"com.a": "allow"}, write_fails={"com.a"})
        changed, failed = chan.restore_appops(reader, {"com.a": "default"})
        self.assertEqual((changed, failed), (["com.a"], ["com.a"]))

    def test_write_that_does_not_stick_is_a_failure(self):
        class Stubborn(FakeReader):
            def shell(self, command, timeout=60):
                result = super().shell(command, timeout)
                if command.startswith("cmd appops set "):
                    self.modes[command.split()[3]] = "allow"
                return result

        reader = Stubborn({"com.a": "allow"})
        changed, failed = chan.restore_appops(reader, {"com.a": "default"})
        self.assertEqual((changed, failed), (["com.a"], ["com.a"]))

    def test_link_lost_is_not_swallowed(self):
        reader = FakeReader({"com.a": "allow"}, lost={"com.a"})
        with self.assertRaises(adb_link.DeviceLost):
            chan.restore_appops(reader, {"com.a": "default"})

    def test_mode_text_is_read_as_the_mode_itself(self):
        reader = Mock()
        reader.shell.return_value = Mock(output="POST_NOTIFICATION: allow\n")
        self.assertEqual(chan.appops_mode(reader, "com.a"), "allow")
        reader.shell.return_value = Mock(output="No operations.")
        self.assertEqual(chan.appops_mode(reader, "com.a"), "default")
        reader.shell.return_value = Mock(output="看不懂的输出")
        self.assertEqual(chan.appops_mode(reader, "com.a"), "unknown")


class RestoreReportTests(unittest.TestCase):
    def test_observed_change_goes_into_the_report_payload(self):
        reader = FakeReader({"com.a": "allow"})
        with patch.object(chan.events, "payload") as payload, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(chan.restore_report(reader, {"com.a": "default"}), 0)
        payload.assert_called_once_with("appops-changed\tcom.a")
        self.assertIn("已写回 default", out.getvalue())

    def test_failed_write_counts_as_a_failed_step(self):
        reader = FakeReader({"com.a": "allow"}, write_fails={"com.a"})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(chan.restore_report(reader, {"com.a": "default"}), 1)
        self.assertIn("没能恢复原值", out.getvalue())

    def test_link_lost_while_restoring_says_it_could_not_verify(self):
        reader = FakeReader({"com.a": "allow"}, lost={"com.a"})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(chan.restore_report(reader, {"com.a": "default"}), 1)
        self.assertIn("没能核对", out.getvalue())


DUMP_ON = """PackagePreferences:
  AppSettings: com.example (10200) importance=DEFAULT
    NotificationChannel{mId='promo', mName=营销通知, mDescription=, mImportance=3, mDeleted=false}
"""
DUMP_OFF = """PackagePreferences:
  AppSettings: com.example (10200) importance=DEFAULT
    NotificationChannel{mId='promo', mName=营销通知, mDescription=, mImportance=0, mDeleted=false}
"""


class BatchAppOpsTests(unittest.TestCase):
    """整批结束时恢复，而不是只测函数本身。"""

    class Reader(FakeReader):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.channel_on = True

        def shell(self, command, timeout=60):
            if command.startswith("dumpsys notification"):
                return Mock(output=DUMP_ON if self.channel_on else DUMP_OFF)
            return super().shell(command, timeout=timeout)

    def run_off(self, reader, write_fails=()):
        reader.write_fails = set(write_fails)
        items = [("com.example", "promo", "营销通知")]

        def toggle(*_args):
            reader.channel_on = False          # 页面把渠道关掉
            reader.modes["com.example"] = "allow"   # 副作用：权限模式被页面改成 allow
            return chan.Outcome(chan.DONE)

        phone = Mock()
        phone.d = reader
        phone.wait_unlocked = Mock(return_value=True)
        with patch.object(chan, "ShellPhone", return_value=reader), \
             patch.object(chan, "load", return_value=items), \
             patch.object(chan, "Phone", return_value=phone), \
             patch.object(chan, "keep_awake", return_value=None), \
             patch.object(chan.events, "payload") as payload, \
             patch.object(chan, "toggle", side_effect=toggle) as toggled, \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", "x.tsv"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                chan.main()
                code = 0
            except SystemExit as e:
                code = e.code
        toggled.assert_called_once()
        return code, out.getvalue(), payload

    def test_batch_writes_the_page_side_effect_back(self):
        reader = self.Reader({"com.example": "default"})
        code, out, payload = self.run_off(reader)
        self.assertEqual(code, 0)
        self.assertEqual(reader.modes["com.example"], "default")
        self.assertIn("通知权限模式", out)
        self.assertIn("已写回 default", out)
        payload.assert_called_once_with("appops-changed\tcom.example")

    def test_original_allow_is_never_written(self):
        reader = self.Reader({"com.example": "allow"})   # 批次开始时已是 allow：不该写
        code, out, _payload = self.run_off(reader)
        self.assertEqual(code, 0)
        self.assertEqual(reader.writes, [])
        self.assertNotIn("通知权限模式", out)

    def test_failed_restore_exits_non_zero(self):
        reader = self.Reader({"com.example": "default"})
        reader.write_fails = set()
        original = reader.shell

        def shell(command, timeout=60):
            if command.startswith("cmd appops set "):
                raise RuntimeError("adb 写入失败")
            return original(command, timeout=timeout)
        reader.shell = shell
        code, out, _payload = self.run_off(reader)
        self.assertEqual(code, 1)
        self.assertIn("没能恢复原值", out)


if __name__ == "__main__":
    unittest.main()
