"""#576：页面打得开、页面上确实没有这一行的渠道，记进本机名单，下一轮扫描不再列出。

provenance: #576 @Sheldor-C

三个条件同时成立才记：应用通知页打开了、这一页翻到底都没有这个渠道名、App 通知没有被整体关闭。
页面没打开 / 认不出（名字还在页面上，只是没挂上容器）不进名单 —— 那是没适配好；
App 通知整体关闭也不进名单 —— 渠道本来就不该出现，仍按 APP_DENIED 处理。
"""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import chan_fast as chan
from fixtures import phone_stub

APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
PK, CID, NAME = "com.vivo.desktop", "VPushChannel_0", "运营消息"
MODEL = "V2217A"


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def switch_row(label, top):
    return (f'<node clickable="true" bounds="[0,{top}][1080,{top + 160}]">'
            f'<node class="android.widget.TextView" text="{label}" bounds="[60,{top + 20}][500,{top + 100}]"/>'
            f'<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
            f' clickable="true" bounds="[900,{top + 20}][1040,{top + 100}]"/></node>')


HEADER = '<node class="android.widget.TextView" text="系统桌面" bounds="[0,111][1080,360]"/>'

# 报告者的「系统桌面」：应用通知页上只有「允许通知」
MASTER_ONLY = page(HEADER, switch_row("允许通知", 700))

# 「信息」那一类：页面上另有几个开关，但同样没有这个渠道的行
OTHER_SWITCHES = page(HEADER, switch_row("允许通知", 700), switch_row("静默通知", 900),
                      switch_row("智能静默", 1100))

# 名字还在页面上，只是没挂上能认的行（#427 那一批）：这是「没认出」，不是「没有」
NAME_ON_PAGE = page(HEADER, f'<node class="android.widget.TextView" text="{NAME}"'
                            ' bounds="[60,700][700,800]"/>')


def phone(pages, focus=APP_FOCUS):
    """当前页可以读很多次；点击后换下一页，最后一页一直重复。"""
    index = [0]

    def tree():
        return ET.fromstring(pages[min(index[0], len(pages) - 1)])

    def click(*_args):
        index[0] = min(index[0] + 1, len(pages) - 1)

    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.focus = Mock(return_value=focus)
    p.confirm = Mock()
    p.click = Mock(side_effect=click)
    seen = iter(range(10 ** 6))
    p.sig = Mock(side_effect=lambda: str(next(seen)))
    p.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.tree = tree
    p.reader = Mock()
    p.reader.shell.return_value = Mock(output="")
    return p


def shell(appops_mode="allow", permission=None):
    def run(command, *a, **k):
        if "appops" in command:
            return Mock(output=f"POST_NOTIFICATION: {appops_mode}\n")
        if "granted=" in command:
            return Mock(output=permission or "")
        return Mock(output="")
    return run


def close(p, want_on=False):
    with patch.object(chan, "parse", return_value=({(PK, CID): (NAME, 3, False)}, {})), \
         patch.object(chan.time, "sleep"):
        return chan.toggle(p, PK, CID, want_on, NAME)


class Store:
    """把名单落到临时目录：扫描与关闭两条路共用同一份。"""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.patch = patch.multiple(chan, BACKUPS=self.dir.name)
        self.patch.start()
        self.model = patch.object(chan, "phone_model", return_value=MODEL)
        self.model.start()
        return self

    def __exit__(self, *exc):
        self.model.stop()
        self.patch.stop()
        self.dir.cleanup()


class ToggleDecisionTests(unittest.TestCase):
    """toggle() 的出口：这三种「页面上没有」必须分开，因为记账与进不进名单都不同。"""

    def test_page_opened_without_the_row_is_ui_hidden(self):
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("allow")
        self.assertEqual(close(p).kind, chan.UI_HIDDEN)

    def test_page_with_other_switches_but_no_row_is_ui_hidden(self):
        # 「信息」那种页面：另有开关，渠道行同样不存在
        p = phone([OTHER_SWITCHES])
        p.reader.shell.side_effect = shell("allow")
        self.assertEqual(close(p).kind, chan.UI_HIDDEN)

    def test_app_notifications_off_stays_app_denied(self):
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("deny")
        self.assertEqual(close(p).kind, chan.APP_DENIED)

    def test_name_on_the_page_but_no_row_is_still_a_failure(self):
        # 名字还在页面上：#427 那批是没认出，不能记成「页面没有这一行」
        p = phone([NAME_ON_PAGE])
        p.reader.shell.side_effect = shell("allow")
        got = close(p)
        self.assertEqual(got.kind, chan.NOT_CONFIRMED)
        self.assertIn("没找到这一行", got.detail)

    def test_page_that_did_not_open_is_still_a_failure(self):
        p = phone([MASTER_ONLY], focus="com.vendor.notify/.UnknownPage")
        p.reader.shell.side_effect = shell("allow")
        self.assertEqual(close(p).kind, chan.NOT_CONFIRMED)

    def test_unreadable_app_notification_state_is_not_recorded(self):
        # 名单是持久的：总开关读不出来时宁可继续报失败，也不能把一个也许关得掉的渠道记掉
        def broken(command, *a, **k):
            if "appops" in command:
                raise RuntimeError("shell output invalid")
            return Mock(output="")
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = broken
        got = close(p)
        self.assertEqual(got.kind, chan.NOT_CONFIRMED)
        self.assertIn("总开关读不出来", got.detail)

    def test_restore_direction_keeps_the_old_answer(self):
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("allow")
        self.assertEqual(close(p, want_on=True).kind, chan.NOT_CONFIRMED)

    def test_ui_hidden_is_not_a_failure_and_leaves_the_recheck_alone(self):
        got = chan.Outcome(chan.UI_HIDDEN)
        self.assertFalse(chan.failed(got, False))
        self.assertFalse(chan.retryable(got))
        self.assertFalse(chan.toggled(got))
        self.assertTrue(chan.exempt_from_recheck(got))
        self.assertIn("不算失败", chan.render(got, NAME, False))


ITEMS = [(PK, CID, NAME)]


def read(on=True):
    return ({(PK, CID): (NAME, 3 if on else 0, False)}, {})


def run_chan(cmd, reads, outcomes):
    phone_mock = Mock(wait_unlocked=Mock(return_value=True))
    with patch.object(chan, "load", return_value=ITEMS), \
         patch.object(chan, "parse", side_effect=reads), \
         patch.object(chan, "Phone", return_value=phone_mock), \
         patch.object(chan, "keep_awake", return_value=None), \
         patch.object(chan, "toggle", side_effect=outcomes), \
         patch.object(chan, "pause_point"), \
         patch.object(sys, "argv", ["chan_fast.py", "-s", "t", cmd, "x.tsv"]), \
         contextlib.redirect_stdout(io.StringIO()) as out:
        try:
            chan.main()
            code = 0
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


class BatchTests(unittest.TestCase):
    """chan-off 把 UI_HIDDEN 记进名单，且整批不因此算失败。"""

    def test_hidden_channel_is_remembered_and_does_not_fail_the_batch(self):
        with Store():
            code, out = run_chan("off", [read(True), read(True)], [chan.Outcome(chan.UI_HIDDEN)])
            self.assertEqual(code, 0)
            self.assertIn("不算失败", out)
            self.assertNotIn("仍开着：", out)
            self.assertEqual(chan.UiHidden(chan.BACKUPS, MODEL).load(), {(PK, CID)})

    def test_saved_channel_is_not_remembered_again(self):
        with Store():
            store = chan.UiHidden(chan.BACKUPS, MODEL)
            store.remember([(PK, CID)])
            self.assertEqual(store.remember([(PK, CID)]), 0)
            self.assertEqual(store.load(), {(PK, CID)})

    def test_failures_are_not_remembered(self):
        with Store():
            code, _ = run_chan("off", [read(True)] * 3,
                               [chan.Outcome(chan.NOT_CONFIRMED, "未确认")] * 2)
            self.assertEqual(code, 1)
            self.assertEqual(chan.UiHidden(chan.BACKUPS, MODEL).load(), set())

    def test_app_notifications_off_is_not_remembered(self):
        # 渠道本来就不该出现，按现有的 APP_DENIED 处理，不进「UI 未暴露」名单
        with Store():
            code, _ = run_chan("off", [read(True), read(True)], [chan.Outcome(chan.APP_DENIED)])
            self.assertEqual(code, 0)
            self.assertEqual(chan.UiHidden(chan.BACKUPS, MODEL).load(), set())


def dump(*lines):
    return ("PackagePreferences:\n"
            f"      AppSettings: {PK} importance=DEFAULT\n"
            + "".join(f"        {line}\n" for line in lines))


def channel_line(importance=3):
    return (f"NotificationChannel{{mId='{CID}', mName={NAME}, mDescription=null,"
            f" mImportance={importance}, mBypassDnd=false, mDeleted=false}}")


def scan_once(*extra):
    result = SimpleNamespace(returncode=0, stdout=dump(channel_line()), stderr="")
    with patch.object(subprocess, "run", return_value=result), \
         patch.object(chan, "app_labels", return_value={}), \
         patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "scan", *extra]), \
         contextlib.redirect_stdout(io.StringIO()) as out, \
         contextlib.redirect_stderr(io.StringIO()) as err:
        chan.main()
    return out.getvalue(), err.getvalue()


class ScanTests(unittest.TestCase):
    """chan-scan 读名单：这些渠道不进清单，只报一句计数。"""

    def test_remembered_channel_is_left_out_and_counted(self):
        with Store():
            chan.UiHidden(chan.BACKUPS, MODEL).remember([(PK, CID)])
            out, err = scan_once()
        self.assertEqual(out, "")
        self.assertIn("另有 1 个渠道本机 UI 未暴露，未列入清单", err)

    def test_unknown_channel_is_listed_as_before(self):
        with Store():
            out, err = scan_once()
        self.assertEqual(out, f"{PK}\t{CID}\t{NAME}\n")
        self.assertEqual(err, "")

    def test_another_model_keeps_its_own_list(self):
        with Store():
            chan.UiHidden(chan.BACKUPS, "OTHER").remember([(PK, CID)])
            out, err = scan_once()
        self.assertEqual(out, f"{PK}\t{CID}\t{NAME}\n")
        self.assertEqual(err, "")

    def test_one_close_run_is_enough_to_drop_the_channel_from_the_next_scan(self):
        # 验收原话：同一渠道第一次 chan-off 未确认后，下一次 chan-scan 不再把它列进清单
        with Store():
            code, _ = run_chan("off", [read(True), read(True)], [chan.Outcome(chan.UI_HIDDEN)])
            self.assertEqual(code, 0)
            out, err = scan_once()
        self.assertEqual(out, "")
        self.assertIn("另有 1 个渠道本机 UI 未暴露，未列入清单", err)

    def test_reset_empties_the_list_and_the_channel_comes_back(self):
        # 换系统或 App 升级后渠道可能重新暴露：整份名单可清空重建
        with Store():
            chan.UiHidden(chan.BACKUPS, MODEL).remember([(PK, CID)])
            out, err = scan_once("--reset")
            self.assertEqual(chan.UiHidden(chan.BACKUPS, MODEL).load(), set())
        self.assertEqual(out, f"{PK}\t{CID}\t{NAME}\n")
        self.assertEqual(err, "")


class ModelTests(unittest.TestCase):
    def test_unreadable_model_does_not_pick_a_file(self):
        # 读不到型号（断线、报错）时整条名单停用：宁可有噪音，也不跨机型误伤
        reader = Mock()
        reader.shell.side_effect = RuntimeError("adb 读取失败")
        self.assertEqual(chan.phone_model(reader), "")

    def test_multiline_output_is_not_a_model(self):
        reader = Mock()
        reader.shell.return_value = Mock(output="PackagePreferences:\n AppSettings: x\n")
        self.assertEqual(chan.phone_model(reader), "")


if __name__ == "__main__":
    unittest.main()
