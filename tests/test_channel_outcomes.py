"""渠道批处理：一项的结局是值，怎么记、怎么报由几张表决定。不用手机。

结局集覆盖 toggle() 的每个出口与 run() 的预筛；记账（失败、重试、拨动、复查豁免）、
渲染与退出码都在这一份。并入的还有应用通知整体关闭与本机 UI 未暴露（#426、#576）、
失败行与探针带上包名（#582、#751）、扫描附注的上报（#521）、扫描失败归因、点回复核与
appops 写回（#330）、关渠道清单的落盘与还原（#628、#651）。
认页与找行不在这一份，见 test_channel_page.py。
"""
import contextlib
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

os.environ.setdefault("AAC_NO_SOUND", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import adb_link
import chan_fast as chan
from backups import Backups
from fixtures import (EMPTY_PAGE, SIZES, Clock, FakeProc, FakeRunner, fake_adb, fake_phone,
                      install_clock, job_stub, phone_stub)
from gui import app


def outcome(kind, detail=""):
    return chan.Outcome(kind, detail)


class OutcomeTableTests(unittest.TestCase):
    def test_channel_missing_counts_as_a_failure_in_both_directions(self):
        for want_on in (False, True):
            self.assertTrue(chan.failed(outcome(chan.NO_CHANNEL), want_on))

    def test_deleted_or_app_off_only_counts_when_restoring(self):
        for kind in (chan.DELETED, chan.APP_OFF):
            self.assertFalse(chan.failed(outcome(kind), False))
            self.assertTrue(chan.failed(outcome(kind), True))

    def test_reached_states_are_not_failures(self):
        for kind in (chan.DONE, chan.ALREADY, chan.GREYED, chan.APP_DENIED, chan.PROTECTED,
                     chan.CONFIRMED_LATER):
            self.assertFalse(chan.failed(outcome(kind), False))

    def test_outcomes_that_need_a_human_are_failures(self):
        for kind in (chan.NOT_CONFIRMED, chan.APP_STATE_UNKNOWN, chan.MISMATCH, chan.UNCHANGED,
                     chan.ERROR):
            self.assertTrue(chan.failed(outcome(kind), False))

    def test_only_not_confirmed_app_state_unknown_and_unchanged_are_retried(self):
        self.assertEqual({k for k in chan.KINDS if chan.retryable(outcome(k))},
                         {chan.NOT_CONFIRMED, chan.APP_STATE_UNKNOWN, chan.UNCHANGED})

    def test_only_done_and_confirmed_later_count_as_toggled(self):
        self.assertEqual({k for k in chan.KINDS if chan.toggled(outcome(k))},
                         {chan.DONE, chan.CONFIRMED_LATER})

    def test_channels_that_cannot_be_closed_are_exempt_from_the_recheck(self):
        self.assertEqual({k for k in chan.KINDS if chan.exempt_from_recheck(outcome(k))},
                         {chan.GREYED, chan.APP_DENIED, chan.UI_HIDDEN})


class RenderTests(unittest.TestCase):
    def test_done_prints_the_verb_then_the_label(self):
        self.assertEqual(chan.render(outcome(chan.DONE), "营销通知", False), "  关  营销通知")
        self.assertEqual(chan.render(outcome(chan.DONE), "营销通知", True), "  开  营销通知")

    def test_only_already_and_confirmed_later_are_silent(self):
        silent = {k for k in chan.KINDS if chan.render(outcome(k), "营销通知", False) is None}
        self.assertEqual(silent, {chan.ALREADY, chan.CONFIRMED_LATER})

    def test_every_kind_renders_a_line(self):
        for kind in chan.KINDS:
            with self.subTest(kind=kind):
                line = chan.render(outcome(kind, "说明"), "营销通知", False)
                self.assertTrue(line is None or line.startswith("  "))

    def test_locked_and_app_denied_say_they_are_not_failures(self):
        self.assertIn("不算失败", chan.render(outcome(chan.GREYED), "营销通知", False))
        self.assertIn("不算失败", chan.render(outcome(chan.APP_DENIED), "营销通知", False))

    def test_protected_shows_the_current_state(self):
        self.assertEqual(chan.render(outcome(chan.PROTECTED, "当前状态 off"), "找机位通知", False),
                         "  · 受保护，未改动 找机位通知（找机位功能通知，当前状态 off）")

    def test_unoperated_kinds_share_one_line(self):
        for kind in (chan.NO_CHANNEL, chan.DELETED, chan.APP_OFF):
            self.assertEqual(chan.render(outcome(kind), "营销通知", False),
                             "  · 未操作 营销通知（渠道不存在、已删除或应用通知已关闭）")

    def test_unreadable_master_switch_says_what_could_not_be_judged(self):
        # #1064：这一页的结构已经认出来了，只差总开关状态 —— 不能再套「未确认…跳过」那句
        line = chan.render(outcome(chan.APP_STATE_UNKNOWN, "停在 x；标题无，允许通知开关 1 个"),
                           "营销通知", False, "com.x")
        self.assertIn("总开关状态读不到，无法判断是否整体关闭", line)
        self.assertNotIn("未确认", line)
        self.assertIn("营销通知（com.x）", line)

    def test_failures_print_the_detail_after_a_cross(self):
        line = chan.render(outcome(chan.MISMATCH, "界面状态与渠道实际状态不一致，未继续点击"), "营销通知", False)
        self.assertEqual(line, "  ✗ 界面状态与渠道实际状态不一致，未继续点击  营销通知")


class ToggleTests(unittest.TestCase):
    """toggle() 的出口：设备侧那三种「没得可关」必须分开，因为记账口径不同。"""

    def outcome_for(self, parsed):
        p = Mock()
        p.locked.return_value = False
        with patch.object(chan, "parse", return_value=parsed):
            return chan.toggle(p, "com.x", "promo", False, "营销通知")

    def test_missing_deleted_and_app_off_are_distinct_outcomes(self):
        cases = {
            chan.NO_CHANNEL: ({}, {}),
            chan.DELETED: ({("com.x", "promo"): ("营销通知", 3, True)}, {}),
            chan.APP_OFF: ({("com.x", "promo"): ("营销通知", 3, False)}, {"com.x": True}),
        }
        for kind, parsed in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.outcome_for(parsed).kind, kind)


ITEMS = [("com.a", "promo", "营销通知")]


def read(on=True, deleted=False):
    return ({("com.a", "promo"): ("营销通知", 3 if on else 0, deleted)}, {})


class BatchTests(unittest.TestCase):
    def run_chan(self, cmd, reads, outcomes):
        phone = Mock(wait_unlocked=Mock(return_value=True))
        with patch.object(chan, "load", return_value=ITEMS), \
             patch.object(chan, "parse", side_effect=reads), \
             patch.object(chan, "Phone", return_value=phone), \
             patch.object(chan, "keep_awake", return_value=None), \
             patch.object(chan, "toggle", side_effect=outcomes) as toggled, \
             patch.object(chan, "pause_point"), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "t", cmd, "x.tsv"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                chan.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), toggled

    def test_channel_confirmed_on_the_retry_counts_as_changed_and_is_not_retried_again(self):
        code, out, toggled = self.run_chan("off", [read(True), read(False), read(False)],
                                           [outcome(chan.UNCHANGED, "点击后渠道状态未改变")])
        self.assertEqual(code, 0)
        self.assertEqual(toggled.call_count, 1)     # 第二遍只重试还没改好的那个
        self.assertIn("拨了 1 个", out)
        self.assertIn("营销渠道仍开着: 0 个", out)

    def test_channel_still_unchanged_after_the_retry_fails_the_step(self):
        code, out, _ = self.run_chan("off", [read(True), read(True), read(True)],
                                     [outcome(chan.UNCHANGED, "点击后渠道状态未改变")] * 2)
        self.assertEqual(code, 1)
        self.assertIn("拨了 0 个", out)              # 失败项不算「拨了」
        self.assertIn("仍开着：营销通知（com.a）", out)

    def test_mismatch_is_not_retried(self):
        code, out, toggled = self.run_chan("off", [read(True), read(True)],
                                           [outcome(chan.MISMATCH, "界面状态与渠道实际状态不一致，未继续点击")])
        self.assertEqual(code, 1)
        self.assertEqual(toggled.call_count, 1)
        self.assertNotIn("再试一次", out)

    def test_locked_channel_is_printed_but_not_counted(self):
        code, out, _ = self.run_chan("off", [read(True), read(True)], [outcome(chan.GREYED)])
        self.assertEqual(code, 0)
        self.assertIn("系统锁定（开关是灰的），不能关闭，不算失败  营销通知", out)

    def test_deleted_channel_does_not_fail_a_close_run(self):
        code, out, toggled = self.run_chan("off", [read(True, True), read(True, True)], [])
        self.assertEqual(code, 0)
        self.assertIn("未操作 营销通知（渠道不存在、已删除或应用通知已关闭）", out)
        toggled.assert_not_called()

    def test_deleted_channel_fails_a_restore_run(self):
        code, out, _ = self.run_chan("on", [read(True, True), read(True, True)], [])
        self.assertEqual(code, 1)
        self.assertIn("未恢复的渠道: 1 个", out)

    def test_channel_already_closed_is_silent_and_untouched(self):
        code, out, toggled = self.run_chan("off", [read(False), read(False)], [])
        self.assertEqual(code, 0)
        self.assertNotIn("  关  ", out)
        toggled.assert_not_called()


# ---- app_denied_426 ----
# #426 华为 / 荣耀：应用通知被整体关掉时，应用通知页只列「允许通知」总开关、不列渠道。
# 引擎以前把这种页面记成「没找到这一行」→ 失败；判据也不认安卓 12 上唯一的表达 —— appops。


DENIED_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
DENIED_PK, DENIED_CID, DENIED_NAME = "com.example.app", "promo", "营销通知"


def denied_page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def denied_phone(pages, focus=DENIED_FOCUS):
    """当前页在点击之后才换成下一页：同一页可以读很多次，最后一页一直重复。"""
    index = [0]

    def tree():
        return ET.fromstring(pages[min(index[0], len(pages) - 1)])

    def click(*_args):
        index[0] = min(index[0] + 1, len(pages) - 1)

    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm = Mock()
    p.click = Mock(side_effect=click)
    seen = iter(range(10 ** 6))
    p.screen.sig = Mock(side_effect=lambda: str(next(seen)))
    p.screen.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.screen.tree = tree
    p.reader = Mock()
    p.reader.shell.return_value = Mock(output="")
    return p


# 应用通知页：这个应用的通知被系统整体关了 —— 渠道列表不出现，只剩「允许通知」总开关
MASTER_ONLY = denied_page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    '<node class="android.widget.TextView" text="允许通知" bounds="[60,720][500,800]"/>'
    '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
    ' clickable="true" bounds="[900,720][1040,800]"/></node>',
)

# 应用通知页：只有一个总开关，渠道名也还在页面上（这轮没认出它的行）：不能断言「页面上没有这一行」
MASTER_WITH_NAME = denied_page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    f'<node class="android.widget.TextView" text="{DENIED_NAME}" bounds="[60,700][700,800]"/>',
    '<node clickable="true" bounds="[0,1100][1080,1260]">'
    '<node class="android.widget.TextView" text="允许通知" bounds="[60,1120][500,1200]"/>'
    '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
    ' clickable="true" bounds="[900,1120][1040,1200]"/></node>',
)

# 应用通知页：渠道行在，只是行内开关没认出（这时不许套用「应用通知整体关闭」）
ROW_UNREADABLE = denied_page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    f'<node class="android.widget.TextView" text="{DENIED_NAME}" bounds="[60,720][700,800]"/></node>',
)


def denied_shell(appops_mode="allow", permission=None):
    """读屏层的假传输：dumpsys package 与 appops 各回各的。"""
    def run(command, *a, **k):
        if "appops" in command:
            return Mock(output=f"POST_NOTIFICATION: {appops_mode}\n")
        if "granted=" in command:
            return Mock(output=permission or "")
        return Mock(output="")
    return run


# 应用通知页：列出了渠道，但渠道名写在 CheckBox 自己身上（#427 那 194 次），这轮一行都没认出来
CHECKBOX_ROWS = denied_page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    *[f'<node class="android.widget.CheckBox" text="渠道{i}" checkable="true" checked="true"'
      f' clickable="true" bounds="[60,{700 + i * 160}][1020,{860 + i * 160}]"/>' for i in range(3)],
)


def denied_outcome(p, want_on=False):
    with patch.object(chan, "parse", return_value=({(DENIED_PK, DENIED_CID): (DENIED_NAME, 3, False)}, {})), \
         patch.object(chan.time, "sleep"):
        return chan.toggle(p, DENIED_PK, DENIED_CID, want_on, DENIED_NAME)


class AppLevelOffTests(unittest.TestCase):
    def test_appops_ignore_on_the_master_only_page_is_not_a_failure(self):
        # 华为 HarmonyOS 4.2（安卓 12）没有 POST_NOTIFICATIONS 权限，只能看 appops
        p = denied_phone([MASTER_ONLY])
        p.reader.shell.side_effect = denied_shell("ignore")
        self.assertEqual(denied_outcome(p).kind, chan.APP_DENIED)

    def test_appops_deny_is_the_same_answer(self):
        # 新一点的系统上同一个开关写作 deny
        p = denied_phone([MASTER_ONLY])
        p.reader.shell.side_effect = denied_shell("deny")
        self.assertEqual(denied_outcome(p).kind, chan.APP_DENIED)

    def test_appops_allow_is_ui_hidden(self):
        # 应用通知开着、页面上却没有这个渠道：不是「应用通知整体关闭」，也不该每轮重复报同一条失败
        # —— 记成「本机 UI 未暴露」，下一轮扫描不再列出（#576）
        p = denied_phone([MASTER_ONLY])
        p.reader.shell.side_effect = denied_shell("allow")
        self.assertEqual(denied_outcome(p).kind, chan.UI_HIDDEN)

    def test_unreadable_appops_is_its_own_failure(self):
        # 命令报错 / 输出不认识时既不算「关着」，也不算「明确没关」：
        # 名单是持久的，读不出来就继续报失败，不把渠道记成「本机 UI 未暴露」，沿用 #576 的取舍；
        # 但它与「页面没打开 / 认不出」不是同一件事，单独一个结局、单独一句（#1064）
        def broken(command, *a, **k):
            if "appops" in command:
                raise RuntimeError("shell output invalid")
            return Mock(output="")
        p = denied_phone([MASTER_ONLY])
        p.reader.shell.side_effect = broken
        got = denied_outcome(p)
        self.assertEqual(got.kind, chan.APP_STATE_UNKNOWN)
        self.assertTrue(chan.failed(got, False))
        self.assertIn("总开关状态读不到，无法判断是否整体关闭", chan.render(got, DENIED_NAME, False))

    def test_master_only_page_with_the_name_on_screen_is_the_same_unknown(self):
        # 同一个出口的另一条来源（reached.no_row）：页面上只有总开关，但渠道名还在 ——
        # 两条来源必须同一条判据，只改「确实没有这一行」那一边会漏掉这里（#1064）
        def broken(command, *a, **k):
            if "appops" in command:
                raise RuntimeError("shell output invalid")
            return Mock(output="")
        p = denied_phone([MASTER_WITH_NAME])
        p.reader.shell.side_effect = broken
        self.assertEqual(denied_outcome(p).kind, chan.APP_STATE_UNKNOWN)

    def test_no_operations_means_not_denied(self):
        # 这个应用没有 POST_NOTIFICATION 这条 appops 记录：读不出=没关
        def unknown_op(command, *a, **k):
            if "appops" in command:
                return Mock(output="No operations.\n")
            return Mock(output="")
        p = denied_phone([MASTER_ONLY])
        p.reader.shell.side_effect = unknown_op
        self.assertEqual(denied_outcome(p).kind, chan.UI_HIDDEN)

    def test_a_listed_row_without_a_readable_switch_is_not_degraded(self):
        # 渠道行在页面上（#427 那批），只是行内开关没认出：此时不许套用总开关判据
        p = denied_phone([ROW_UNREADABLE])
        p.reader.shell.side_effect = denied_shell("ignore")
        self.assertEqual(denied_outcome(p).kind, chan.NOT_CONFIRMED)

    def test_a_page_full_of_channels_is_not_degraded(self):
        # 页面明明列着渠道（渠道名写在 CheckBox 上、这轮没认出来）就说明应用通知没关：
        # 不能因为「这轮没找到行」就把 #427 那批算成 #426
        p = denied_phone([CHECKBOX_ROWS])
        p.reader.shell.side_effect = denied_shell("ignore")
        self.assertEqual(denied_outcome(p).kind, chan.NOT_CONFIRMED)

    def test_restore_direction_keeps_the_old_wording(self):
        # 还原（chan-on）方向不套这条判据：文案与记账维持原样
        p = denied_phone([MASTER_ONLY])
        p.reader.shell.side_effect = denied_shell("ignore")
        got = denied_outcome(p, want_on=True)
        self.assertEqual(got.kind, chan.NOT_CONFIRMED)
        self.assertIn("未确认「营销通知」渠道页及通知开关，跳过", got.detail)

    def test_granted_permission_short_circuits_appops(self):
        # 权限读数说 granted=true 就是没关，不再去问 appops（#330 记过两者可能不同步）
        p = denied_phone([MASTER_ONLY])
        p.reader.shell.side_effect = denied_shell("ignore", permission="  POST_NOTIFICATIONS: granted=true, flags=[ ]\n")
        self.assertEqual(denied_outcome(p).kind, chan.UI_HIDDEN)
        self.assertFalse([c for c in p.reader.shell.call_args_list if "appops" in str(c)])

    def test_unconfirmed_page_is_not_degraded(self):
        # 压根没确认停在应用通知页（前台是别的页面）时，就算 appops 说 ignore 也不能降级
        p = denied_phone([MASTER_ONLY], focus="com.vendor.notify/.UnknownPage")
        p.reader.shell.side_effect = denied_shell("ignore")
        self.assertEqual(denied_outcome(p).kind, chan.NOT_CONFIRMED)


# ---- ui_hidden_576 ----
# #576：页面打得开、页面上确实没有这一行的渠道，记进本机名单，下一轮扫描不再列出。
#
# provenance: #576 @Sheldor-C
#
# 三个条件同时成立才记：应用通知页打开了、这一页翻到底都没有这个渠道名、App 通知没有被整体关闭。
# 页面没打开 / 认不出（名字还在页面上，只是没挂上容器）不进名单 —— 那是没适配好；
# App 通知整体关闭也不进名单 —— 渠道本来就不该出现，仍按 APP_DENIED 处理。


HIDDEN_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
HIDDEN_PK, HIDDEN_CID, HIDDEN_NAME = "com.vivo.desktop", "VPushChannel_0", "运营消息"
HIDDEN_MODEL = "V2217A"


def hidden_page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def hidden_switch_row(label, top):
    return (f'<node clickable="true" bounds="[0,{top}][1080,{top + 160}]">'
            f'<node class="android.widget.TextView" text="{label}" bounds="[60,{top + 20}][500,{top + 100}]"/>'
            f'<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
            f' clickable="true" bounds="[900,{top + 20}][1040,{top + 100}]"/></node>')


HIDDEN_HEADER = '<node class="android.widget.TextView" text="系统桌面" bounds="[0,111][1080,360]"/>'

# 「信息」那一类：页面上另有几个开关，但同样没有这个渠道的行
HIDDEN_OTHER_SWITCHES = hidden_page(
    HIDDEN_HEADER, hidden_switch_row("允许通知", 700), hidden_switch_row("静默通知", 900),
    hidden_switch_row("智能静默", 1100))

# 名字还在页面上，只是没挂上能认的行（#427 那一批）：这是「没认出」，不是「没有」
HIDDEN_NAME_ON_PAGE = hidden_page(
    HIDDEN_HEADER, f'<node class="android.widget.TextView" text="{HIDDEN_NAME}" bounds="[60,700][700,800]"/>')


def hidden_phone(pages, focus=HIDDEN_FOCUS):
    """当前页可以读很多次；点击后换下一页，最后一页一直重复。"""
    index = [0]

    def tree():
        return ET.fromstring(pages[min(index[0], len(pages) - 1)])

    def click(*_args):
        index[0] = min(index[0] + 1, len(pages) - 1)

    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=focus)
    p.confirm = Mock()
    p.click = Mock(side_effect=click)
    seen = iter(range(10 ** 6))
    p.screen.sig = Mock(side_effect=lambda: str(next(seen)))
    p.screen.settle = Mock(return_value=True)
    p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
    p.screen.tree = tree
    p.reader = Mock()
    p.reader.shell.return_value = Mock(output="")
    return p


def hidden_shell(appops_mode="allow", permission=None):
    def run(command, *a, **k):
        if "appops" in command:
            return Mock(output=f"POST_NOTIFICATION: {appops_mode}\n")
        if "granted=" in command:
            return Mock(output=permission or "")
        return Mock(output="")
    return run


def hidden_close(p, want_on=False):
    with patch.object(chan, "parse", return_value=({(HIDDEN_PK, HIDDEN_CID): (HIDDEN_NAME, 3, False)}, {})), \
         patch.object(chan.time, "sleep"):
        return chan.toggle(p, HIDDEN_PK, HIDDEN_CID, want_on, HIDDEN_NAME)


class HiddenStore:
    """把名单落到临时目录：扫描与关闭两条路共用同一份。"""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.patch = patch.multiple(chan, BACKUPS=self.dir.name)
        self.patch.start()
        self.model = patch.object(chan, "phone_model", return_value=HIDDEN_MODEL)
        self.model.start()
        return self

    def __exit__(self, *exc):
        self.model.stop()
        self.patch.stop()
        self.dir.cleanup()


class HiddenToggleTests(unittest.TestCase):
    """toggle() 的出口：这三种「页面上没有」必须分开，因为记账与进不进名单都不同。

    只列总开关的页面那五条与 AppLevelOffTests 重复（同一份夹具、同一条断言）：allow 与 deny
    各一条读数、「页面没打开」一条（那边用 ignore 读数，更严）、总开关读不出来一条、还原
    方向一条。这里只留那边没有的两条来源与「UI 未暴露不算失败」。
    """

    def test_page_with_other_switches_but_no_row_is_ui_hidden(self):
        # 「信息」那种页面：另有开关，渠道行同样不存在
        p = hidden_phone([HIDDEN_OTHER_SWITCHES])
        p.reader.shell.side_effect = hidden_shell("allow")
        self.assertEqual(hidden_close(p).kind, chan.UI_HIDDEN)

    def test_name_on_the_page_but_no_row_is_still_a_failure(self):
        # 名字还在页面上：#427 那批是没认出，不能记成「页面没有这一行」
        p = hidden_phone([HIDDEN_NAME_ON_PAGE])
        p.reader.shell.side_effect = hidden_shell("allow")
        got = hidden_close(p)
        self.assertEqual(got.kind, chan.NOT_CONFIRMED)
        self.assertIn("没找到这一行", got.detail)

    def test_page_with_other_switches_and_unreadable_master_state_is_the_same_unknown(self):
        # 另一条来源：翻到底都没读到这个渠道名（hidden），页面却另有开关（不是「只列总开关」，no_row 为假）。
        # 两条来源同一条判据，只改 no_row 那一边时这里会静默退回「未确认…跳过」（#1064）
        def broken(command, *a, **k):
            if "appops" in command:
                raise RuntimeError("shell output invalid")
            return Mock(output="")
        p = hidden_phone([HIDDEN_OTHER_SWITCHES])
        p.reader.shell.side_effect = broken
        self.assertEqual(hidden_close(p).kind, chan.APP_STATE_UNKNOWN)

    def test_ui_hidden_is_not_a_failure_and_leaves_the_recheck_alone(self):
        got = chan.Outcome(chan.UI_HIDDEN)
        self.assertFalse(chan.failed(got, False))
        self.assertFalse(chan.retryable(got))
        self.assertFalse(chan.toggled(got))
        self.assertTrue(chan.exempt_from_recheck(got))
        self.assertIn("不算失败", chan.render(got, HIDDEN_NAME, False))


HIDDEN_ITEMS = [(HIDDEN_PK, HIDDEN_CID, HIDDEN_NAME)]


def hidden_read(on=True):
    return ({(HIDDEN_PK, HIDDEN_CID): (HIDDEN_NAME, 3 if on else 0, False)}, {})


def hidden_run_chan(cmd, reads, outcomes):
    phone_mock = Mock(wait_unlocked=Mock(return_value=True))
    with patch.object(chan, "load", return_value=HIDDEN_ITEMS), \
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


class HiddenBatchTests(unittest.TestCase):
    """chan-off 把 UI_HIDDEN 记进名单，且整批不因此算失败。"""

    def test_hidden_channel_is_remembered_and_does_not_fail_the_batch(self):
        with HiddenStore():
            code, out = hidden_run_chan("off", [hidden_read(True), hidden_read(True)], [chan.Outcome(chan.UI_HIDDEN)])
            self.assertEqual(code, 0)
            self.assertIn("不算失败", out)
            self.assertNotIn("仍开着：", out)
            self.assertEqual(chan.UiHidden(chan.BACKUPS, HIDDEN_MODEL).load(), {(HIDDEN_PK, HIDDEN_CID)})

    def test_saved_channel_is_not_remembered_again(self):
        with HiddenStore():
            store = chan.UiHidden(chan.BACKUPS, HIDDEN_MODEL)
            store.remember([(HIDDEN_PK, HIDDEN_CID)])
            self.assertEqual(store.remember([(HIDDEN_PK, HIDDEN_CID)]), 0)
            self.assertEqual(store.load(), {(HIDDEN_PK, HIDDEN_CID)})

    def test_failures_are_not_remembered(self):
        # 总开关读不出来也照这条走：报失败、不进名单（#1064）
        for kind in (chan.NOT_CONFIRMED, chan.APP_STATE_UNKNOWN):
            with self.subTest(kind=kind), HiddenStore():
                code, _ = hidden_run_chan("off", [hidden_read(True)] * 3, [chan.Outcome(kind, "未确认")] * 2)
                self.assertEqual(code, 1)
                self.assertEqual(chan.UiHidden(chan.BACKUPS, HIDDEN_MODEL).load(), set())

    def test_app_notifications_off_is_not_remembered(self):
        # 渠道本来就不该出现，按现有的 APP_DENIED 处理，不进「UI 未暴露」名单
        with HiddenStore():
            code, _ = hidden_run_chan("off", [hidden_read(True), hidden_read(True)], [chan.Outcome(chan.APP_DENIED)])
            self.assertEqual(code, 0)
            self.assertEqual(chan.UiHidden(chan.BACKUPS, HIDDEN_MODEL).load(), set())


def hidden_dump(*lines):
    return ("PackagePreferences:\n"
            f"      AppSettings: {HIDDEN_PK} importance=DEFAULT\n"
            + "".join(f"        {line}\n" for line in lines))


def hidden_channel_line(importance=3):
    return (f"NotificationChannel{{mId='{HIDDEN_CID}', mName={HIDDEN_NAME}, mDescription=null,"
            f" mImportance={importance}, mBypassDnd=false, mDeleted=false}}")


def hidden_scan_once(*extra):
    result = SimpleNamespace(returncode=0, stdout=hidden_dump(hidden_channel_line()), stderr="")
    with patch.object(subprocess, "run", return_value=result), \
         patch.object(chan, "app_labels", return_value={}), \
         patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "scan", *extra]), \
         contextlib.redirect_stdout(io.StringIO()) as out, \
         contextlib.redirect_stderr(io.StringIO()) as err:
        chan.main()
    return out.getvalue(), err.getvalue()


class HiddenScanTests(unittest.TestCase):
    """chan-scan 读名单：这些渠道不进清单，只报一句计数。"""

    def test_remembered_channel_is_left_out_and_counted(self):
        with HiddenStore():
            chan.UiHidden(chan.BACKUPS, HIDDEN_MODEL).remember([(HIDDEN_PK, HIDDEN_CID)])
            out, err = hidden_scan_once()
        self.assertEqual(out, "")
        self.assertIn("另有 1 个渠道本机 UI 未暴露，未列入清单", err)

    def test_unknown_channel_is_listed_as_before(self):
        with HiddenStore():
            out, err = hidden_scan_once()
        self.assertEqual(out, f"{HIDDEN_PK}\t{HIDDEN_CID}\t{HIDDEN_NAME}\n")
        self.assertEqual(err, "")

    def test_another_model_keeps_its_own_list(self):
        with HiddenStore():
            chan.UiHidden(chan.BACKUPS, "OTHER").remember([(HIDDEN_PK, HIDDEN_CID)])
            out, err = hidden_scan_once()
        self.assertEqual(out, f"{HIDDEN_PK}\t{HIDDEN_CID}\t{HIDDEN_NAME}\n")
        self.assertEqual(err, "")

    def test_one_close_run_is_enough_to_drop_the_channel_from_the_next_scan(self):
        # 验收原话：同一渠道第一次 chan-off 未确认后，下一次 chan-scan 不再把它列进清单
        with HiddenStore():
            code, _ = hidden_run_chan("off", [hidden_read(True), hidden_read(True)], [chan.Outcome(chan.UI_HIDDEN)])
            self.assertEqual(code, 0)
            out, err = hidden_scan_once()
        self.assertEqual(out, "")
        self.assertIn("另有 1 个渠道本机 UI 未暴露，未列入清单", err)

    def test_reset_empties_the_list_and_the_channel_comes_back(self):
        # 换系统或 App 升级后渠道可能重新暴露：整份名单可清空重建
        with HiddenStore():
            chan.UiHidden(chan.BACKUPS, HIDDEN_MODEL).remember([(HIDDEN_PK, HIDDEN_CID)])
            out, err = hidden_scan_once("--reset")
            self.assertEqual(chan.UiHidden(chan.BACKUPS, HIDDEN_MODEL).load(), set())
        self.assertEqual(out, f"{HIDDEN_PK}\t{HIDDEN_CID}\t{HIDDEN_NAME}\n")
        self.assertEqual(err, "")


class HiddenModelTests(unittest.TestCase):
    def test_unreadable_model_does_not_pick_a_file(self):
        # 读不到型号（断线、报错）时整条名单停用：宁可有噪音，也不跨机型误伤
        reader = Mock()
        reader.shell.side_effect = RuntimeError("adb 读取失败")
        self.assertEqual(chan.phone_model(reader), "")

    def test_multiline_output_is_not_a_model(self):
        reader = Mock()
        reader.shell.return_value = Mock(output="PackagePreferences:\n AppSettings: x\n")
        self.assertEqual(chan.phone_model(reader), "")


# ---- failure_context_582 ----
# #582 渠道失败行带上包名，MISMATCH 另附一条判据读数：同名渠道分属不同 App 时能区分。
#
# 结局、退出码、点击行为一个字不动 —— 这里只测「事后取证」那部分。


CTX_FOCUS = "com.android.settings/.Settings"     # 认不出通知页，走「未确认」出口


def ctx_phone():
    """一页读不出渠道的假设备：读取按假时钟走，卡在「应用通知页没有打开」。"""
    clock = Clock()
    p = fake_phone(clock=clock, size=SIZES[0], stages=((0.0, EMPTY_PAGE),),
                   focus=((0.0, CTX_FOCUS),))
    original = chan.time
    install_clock(chan, clock)
    return p, original


class PackageOnFailureLineTests(unittest.TestCase):
    def setUp(self):
        self.p, original = ctx_phone()
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
        self.p, original = ctx_phone()
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


# ---- recheck_package_751 ----
# #751 收尾复查的「仍开着」与 verify 逐项行带上包名：同名渠道分属不同 App 时读日志能分清。
#
# 结局、计数、退出码与两份汇总行一个字不动 —— 这里只测这两行的取证部分。


RECHECK_ITEMS = [("com.a", "promo", "运营消息"), ("com.b", "promo", "运营消息")]
ON = {(pk, cid): (label, 3, False) for pk, cid, label in RECHECK_ITEMS}


def recheck_dump():
    return """PackagePreferences:
      AppSettings: com.a importance=DEFAULT
        NotificationChannel{mId='promo', mName=运营消息, mDescription=null, mImportance=3, mDeleted=false}
      AppSettings: com.b importance=DEFAULT
        NotificationChannel{mId='promo', mName=运营消息, mDescription=null, mImportance=3, mDeleted=false}
    """


class RecheckPackageTests(unittest.TestCase):
    def test_still_on_line_names_the_package(self):
        # 0.4.0 上报 e3334810：27 项里 24 行是同一个「运营消息」，事后看不出是哪些 App
        phone = Mock(wait_unlocked=Mock(return_value=True))
        with patch.object(chan, "load", return_value=RECHECK_ITEMS), \
             patch.object(chan, "parse", return_value=(ON, {})), \
             patch.object(chan, "Phone", return_value=phone), \
             patch.object(chan, "keep_awake", return_value=None), \
             patch.object(chan, "appops_mode", return_value="default"), \
             patch.object(chan, "toggle", return_value=chan.Outcome(chan.UNCHANGED, "点击后渠道状态未改变")), \
             patch.object(chan, "pause_point"), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "t", "off", "x.tsv"]), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as stop:
                chan.main()
        self.assertEqual(stop.exception.code, 1)
        self.assertIn("仍开着：运营消息（com.a）", out.getvalue())
        self.assertIn("仍开着：运营消息（com.b）", out.getvalue())
        self.assertIn("营销渠道仍开着: 2 个", out.getvalue())

    def test_verify_line_names_the_package(self):
        fake_adb(self)
        result = types.SimpleNamespace(returncode=0, stdout=recheck_dump(), stderr="")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.a\tpromo\t运营消息\ncom.b\tpromo\t运营消息\n", encoding="utf-8")
            with patch.object(subprocess, "run", return_value=result), \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "t", "verify", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                chan.main()
        self.assertIn("ON   运营消息（com.a）", out.getvalue())
        self.assertIn("ON   运营消息（com.b）", out.getvalue())
        self.assertIn("营销渠道仍开着: 2 个", out.getvalue())

    def test_verify_line_keeps_the_protected_note_with_the_package(self):
        # 受保护备注并进包名括号，改的就是这一句；受保护的仍不计入「仍开着」
        fake_adb(self)
        body = """PackagePreferences:
      AppSettings: com.a importance=DEFAULT
        NotificationChannel{mId='spot', mName=找机位通知, mDescription=null, mImportance=3, mDeleted=false}
    """
        result = types.SimpleNamespace(returncode=0, stdout=body, stderr="")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "channels.tsv")
            path.write_text("com.a\tspot\t找机位通知\n", encoding="utf-8")
            with patch.object(subprocess, "run", return_value=result), \
                 patch.object(sys, "argv", ["chan_fast.py", "-s", "t", "verify", str(path)]), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                chan.main()
        self.assertIn("ON   找机位通知（com.a，受保护，不参与营销关闭）", out.getvalue())
        self.assertIn("营销渠道仍开着: 0 个", out.getvalue())


# ---- scan_notes_521 ----
# #521：扫描的排除计数要经正式入口到达用户。
#
# 引擎把三条排除计数写在 scan 成功路径的 stderr；客户端过去只在失败时读它。这里守的是
# 「成功时也读、原样带出、失败不残留」——不按中文文案挑行，流里给什么就带什么。

NOTE = "另有 3 个前台服务渠道未列入清单"


class ScanNotesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)

    def make_api(self, out="", err="", rc=0):
        api = app.Api(self.directory.name, runner=FakeRunner(runs=(out, err, rc)))
        api._adb = Mock(return_value="Android Debug Bridge version 1.0.41")
        return api

    def test_scan_returns_the_engine_notes_alongside_the_candidates(self):
        api = self.make_api(out="com.shop\tpromo\t活动优惠\n", err=NOTE + "\n\n")
        result = api.chan_scan("test")
        self.assertEqual([r["pkg"] for r in result["chans"]], ["com.shop"])
        self.assertEqual(result["notes"], [NOTE])

    def test_notes_are_carried_whatever_their_wording(self):
        api = self.make_api(err="扫描用时 12 秒\n")
        self.assertEqual(api.chan_scan("test")["notes"], ["扫描用时 12 秒"])

    def test_scan_without_notes_returns_an_empty_list(self):
        api = self.make_api(out="com.shop\tpromo\t活动优惠\n")
        self.assertEqual(api.chan_scan("test")["notes"], [])

    def test_failed_scan_does_not_keep_the_previous_notes(self):
        replies = iter([("com.shop\tpromo\t活动优惠\n", NOTE + "\n", 0),
                        ("", "读取失败\n", 1)])
        api = app.Api(self.directory.name, runner=FakeRunner(runs=lambda *a: next(replies)))
        api._adb = Mock(return_value="Android Debug Bridge version 1.0.41")
        api.chan_scan("test")
        self.assertIn("读取失败", api.chan_scan("test")["error"])
        self.assertEqual(api.last_scan_notes, [])
        self.assertNotIn("通知扫描附注", api.diagnostics())

    def test_an_unexpected_failure_does_not_keep_the_previous_notes(self):
        replies = iter([("com.shop\tpromo\t活动优惠\n", NOTE + "\n", 0), ValueError("boom")])
        api = app.Api(self.directory.name, runner=FakeRunner(runs=lambda *a: next(replies)))
        api.chan_scan("test")
        with self.assertRaises(ValueError):
            api.chan_scan("test")
        self.assertEqual(api.last_scan_notes, [])

    def test_diagnostics_carry_the_scan_notes_on_one_line(self):
        locked = "另有 2 个渠道属于系统锁定、不允许关闭的系统应用，未列入清单"
        api = self.make_api(err=NOTE + "\n" + locked + "\n")
        api.chan_scan("test")
        self.assertIn(f"- 通知扫描附注：{NOTE}；{locked}", api.diagnostics())


# ---- scan_startup ----
# 0.2.2：只读扫描不依赖 UiAutomation，初始化失败保留完整原因。

class ScanErrorTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def make_api(self, runs=None, **runner):
        api = self.app.Api(self.directory.name, runner=FakeRunner(runs=runs, **runner))
        api._adb = Mock(return_value="Android Debug Bridge version 1.0.41")
        return api

    def test_scan_failure_keeps_root_cause_and_redacts_before_saving(self):
        home = str(Path.home())
        detail = f"java.lang.IllegalStateException: root cause; device-123; {home}/private\n" + "at QueryController.java:95\n" * 100
        self.api = self.make_api(runs=("", detail, 1))
        result = self.api.chan_scan("device-123")
        self.assertIn("root cause", result["error"])
        self.assertGreater(len(result["detail"]), 600)
        self.assertNotIn("device-123", result["detail"])
        self.assertNotIn(home, result["detail"])
        saved = Path(self.directory.name, "logs/last-error.txt").read_text(encoding="utf-8")
        self.assertIn(result["detail"], saved)
        self.assertIn("root cause", self.api.diagnostics())  # 扫描失败时还没有执行 job

    def test_scan_timeout_is_reported_and_saved(self):
        self.api = self.make_api(runs=subprocess.TimeoutExpired(["scan", "device-123"], 120))
        result = self.api.chan_scan("device-123")
        self.assertIn("timed out", result["detail"])
        self.assertNotIn("device-123", result["detail"])

    def test_read_screen_check_preserves_full_failure_and_os_version(self):
        self.api = self.make_api(runs=("", "UiAutomation failed at QueryController", 1))
        self.api.last_status = {"info": {"brand": "Xiaomi", "model": "M154FF", "name": "Xiaomi 18 Pro Max",
                                        "build": "CP2A.260605.016", "os": "OS4.0.27", "android": "17"}}
        result = self.api.ui_check("test")
        self.assertIn("UiAutomation", result["detail"])
        self.assertIn("OS4.0.27", self.api.diagnostics())
        self.assertEqual(self.api.runner.run_calls, [("fast.py", ("-s", "test", "check"), 75)])

    def test_read_screen_check_does_not_run_during_job(self):
        self.api = self.make_api()
        self.api.job = job_stub()
        self.assertIn("正在执行", self.api.ui_check("test")["error"])
        self.assertEqual(self.api.runner.run_calls, [])

    def test_failed_task_keeps_first_exception_not_only_tail(self):
        detail = "java.lang.IllegalStateException: first cause\n" + f"at {Path.home()}/frame\n" * 100
        self.api = self.make_api(spawns=[FakeProc(detail, rc=1)])
        self.api.job = job_stub()
        self.api._work([self.app.Task("关闭广告", "run.py", [])])
        self.assertFalse(self.api.job.running)
        self.assertEqual(self.api.job.results[0]["rc"], 1)
        self.assertIn("first cause", self.api.last_error["detail"])
        self.assertNotIn(str(Path.home()), self.api.diagnostics())

    def test_packaged_cli_handles_exception_with_nonzero_exit(self):
        with patch.object(self.app, "_fix_stdio"), \
             patch.object(self.app.runpy, "run_path", side_effect=RuntimeError("java.lang.IllegalStateException: full cause")), \
             patch.object(sys, "argv", ["aac-cli.exe", "--cli", "fast.py", "-s", "test", "check"]), \
             contextlib.redirect_stderr(io.StringIO()) as log:
            with self.assertRaises(SystemExit) as raised:
                self.app.cli_main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("full cause", log.getvalue())
        self.assertNotIn("[PYI-", log.getvalue())


# ---- undo_appops_330 ----
# #330 华为 ALN-AL00：点回后要复核受影响渠道的最终状态；访问应用通知页把
# POST_NOTIFICATION 从 default 改成 allow 时按窄条件写回。不用手机。


UNDO_FOCUS = "com.android.settings/.Settings$ChannelNotificationSettingsActivity"

UNDO_CHANNEL_PAGE = '''<hierarchy><node>
  <node text="营销通知" bounds="[100,120][600,200]"/>
  <node bounds="[0,300][1080,410]">
    <node text="允许通知" bounds="[60,320][600,390]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,320][1040,390]"/>
  </node>
</node></hierarchy>'''


def undo_page():
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.screen.focus = Mock(return_value=UNDO_FOCUS)
    p.confirm = Mock()
    p.click = Mock()
    p.screen.tree = Mock(return_value=ET.fromstring(UNDO_CHANNEL_PAGE))
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
        p = undo_page()
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
        message, lost = chan.undo_message(undo_page(), snap()[0], apps, {("com.example", "promo")},
                                          False, ["渠道「订单通知」"], clicked=False)
        self.assertIn("本次没有点击这一行", message)
        self.assertNotIn("没能自动点回", message)
        self.assertFalse(lost)

    def test_normal_toggle_keeps_its_two_full_reads(self, _sleep):
        p = undo_page()
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


# ---- restore_channels_628 ----
# 还原营销通知合并历次备份里的清单（#628）：最近一次没关渠道时，之前关的也能打开。


def restore_write(root, name, rows):
    d = Path(root, "backups", name)
    d.mkdir(parents=True, exist_ok=True)
    if rows is not None:
        (d / "channels.tsv").write_text("# 包名\t渠道id\t渠道名\t应用名\n" + "".join(r + "\n" for r in rows), encoding="utf-8")


def restore_write_file(root, name, data):
    d = Path(root, "backups", name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "channels.tsv").write_bytes(data)


class RestoreChannelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent, self.paths = [], []

        def runs(script, *args):
            if script == "run.py" and "status-json" in args:
                return json.dumps({"info": {"model": "M1"}}) + "\n", "", 0
            if script == "chan_fast.py" and args[2] == "on":
                self.sent.append(Path(args[3]).read_text(encoding="utf-8"))
                self.paths.append(args[3])
                return "拨了 1 个\n", "", 0
            return None
        self.api = app.Api(self.tmp.name, runner=FakeRunner(runs=runs))

    def tearDown(self):
        self.tmp.cleanup()

    def loaded(self):
        """交给 `chan_fast.py on` 的那份清单按引擎自己的读法解析：写出去的必须真的读得回来。"""
        return chan.load(self.paths[0])

    def test_older_list_is_used_when_latest_run_closed_nothing(self):
        restore_write(self.tmp.name, "M1-20261106-1040", ["com.a\tpromo\t推广\tA"])
        restore_write(self.tmp.name, "M1-20261106-1053", None)
        self.api.restore("s", "channels")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("com.a\tpromo\t推广\tA", self.sent[0])

    def test_lists_are_merged_newest_first_without_duplicates(self):
        restore_write(self.tmp.name, "M1-20261106-1040", ["com.a\tpromo\t旧名\tA", "com.b\tnews\t资讯\tB"])
        restore_write(self.tmp.name, "M1-20261106-1053", ["com.a\tpromo\t推广\tA"])
        self.api.restore("s", "channels")
        rows = [r for r in self.sent[0].splitlines() if not r.startswith("#")]
        self.assertEqual(rows, ["com.a\tpromo\t推广\tA", "com.b\tnews\t资讯\tB"])

    def test_no_list_anywhere(self):
        restore_write(self.tmp.name, "M1-20261106-1053", None)
        self.assertEqual(self.api.restore("s", "channels"), "没有找到上次关掉的营销通知清单")
        self.assertEqual(self.sent, [])

    def test_other_models_are_ignored(self):
        restore_write(self.tmp.name, "M10-20261106-1040", ["com.z\tpromo\t推广\tZ"])
        self.assertEqual(self.api.restore("s", "channels"), "没有找到上次关掉的营销通知清单")

    def test_legacy_list_in_the_gui_dir_is_still_merged(self):
        """旧树也绿，守的是不回退：0.4.0 及更早的客户端把关渠道清单写进 `<型号>-gui/channels.tsv`
        （#651 起客户端与 `run.py chan-scan` 都改写快照目录）。老机器上那份不做迁移，
        字典序上排在最前，照旧当「最新那份」合并进来。"""
        restore_write(self.tmp.name, "M1-20261106-1040", ["com.a\tpromo\t推广\tA", "com.b\tnews\t资讯\tB"])
        restore_write(self.tmp.name, "M1-gui", ["com.b\tnews\t资讯\tB", "com.c\tspam\t推广\tC"])
        self.api.restore("s", "channels")
        self.assertEqual(self.loaded(), [("com.b", "news", "资讯"), ("com.c", "spam", "推广"), ("com.a", "promo", "推广")])

    def test_list_saved_with_bom_is_readable(self):
        # AGENTS.md 让人手工删这份清单里的行，编辑器会按系统习惯另存（Windows 上带 BOM + CRLF）。
        # 首行故意是数据行：带 BOM 的表头本来就会被坏行过滤跳过，那样测不出 `utf-8-sig`。
        restore_write_file(self.tmp.name, "M1-20261106-1040",
                    "com.a\tpromo\t推广\tA\r\ncom.b\tnews\t资讯\tB\r\n".encode("utf-8-sig"))
        self.api.restore("s", "channels")
        self.assertEqual(self.loaded(), [("com.a", "promo", "推广"), ("com.b", "news", "资讯")])

    def test_bad_row_in_an_old_list_is_skipped(self):
        # 坏行所在的备份从界面删不掉：不跳过就永远卡死这个型号的还原。第二条带 cid、包名里有空格，
        # 只按「有没有 cid」过滤拦不住它 —— 它进清单后 `load()` 会抛错。
        restore_write(self.tmp.name, "M1-20261106-1040", ["残留坏行", "com.a promo\tpromo\t促销\tA", "com.b\tnews\t资讯\tB"])
        self.api.restore("s", "channels")
        self.assertEqual(self.loaded(), [("com.b", "news", "资讯")])

    def test_rows_differing_only_in_spaces_are_one_channel(self):
        restore_write(self.tmp.name, "M1-20261106-1040", ["com.a \tpromo\t旧名\tA"])
        restore_write(self.tmp.name, "M1-20261106-1053", ["com.a\tpromo\t推广\tA"])
        self.api.restore("s", "channels")
        rows = [r for r in self.sent[0].splitlines() if not r.startswith("#")]
        self.assertEqual(rows, ["com.a\tpromo\t推广\tA"])     # 真的合成一行，且用最近那条的名字


# ---- restore_channels_651 ----
# 关渠道清单写进本次运行的快照目录，不再写历次共用的 `<型号>-gui`（#651）。
#
# 客户端每次运行开始时有一步 `run.py backup`，它会新建一个 `<型号>-<时间>` 目录；关营销通知的清单
# 跟着写进这一份，历次清单才各自留得住。都写进 `<型号>-gui` 时后一次会覆盖前一次，还原只能找回最后一批。


LANDING_MODEL = "M1"


def landing_batch(*rows):
    return [{"pkg": pkg, "id": cid, "name": name, "app": app_} for pkg, cid, name, app_ in rows]


class ChannelsListLandingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name, "backups")
        self.paths = []

        def runs(script, *args):
            if script == "run.py" and "status-json" in args:
                return json.dumps({"info": {"model": LANDING_MODEL}}) + "\n", "", 0
            if script == "chan_fast.py" and args[2] == "on":
                self.paths.append(args[3])
                return "拨了 1 个\n", "", 0
            return None

        self.api = app.Api(self.tmp.name, runner=FakeRunner(runs=runs))
        self.api.job = job_stub(model=LANDING_MODEL)

    def run_once(self, channels):
        self.api._work([app.Task("关闭营销通知", "chan_fast.py", uses_ui=True, channels=channels)])

    def snapshot_dirs(self):
        return sorted(p for p in self.root.iterdir() if p.name != f"{LANDING_MODEL}-gui")

    def test_two_runs_keeping_different_batches_are_both_restorable(self):
        # 跑过一次还原的机器上有 `<型号>-gui`（放合并后的 channels-restore.tsv）；
        # 每次运行开头的 `run.py backup` 又会新建一份快照目录。两次运行各在自己的目录里留一份清单。
        Path(self.root, f"{LANDING_MODEL}-gui").mkdir(parents=True)
        Backups(self.root).create(LANDING_MODEL, when=datetime.datetime(2026, 11, 6, 10, 40))
        self.run_once(landing_batch(("com.a", "promo", "推广", "A")))
        Backups(self.root).create(LANDING_MODEL, when=datetime.datetime(2026, 11, 6, 10, 53))
        self.run_once(landing_batch(("com.b", "news", "资讯", "B")))

        self.api.restore("s", "channels")

        self.assertEqual(len(self.paths), 1)
        self.assertEqual(chan.load(self.paths[0]),
                         [("com.b", "news", "资讯"), ("com.a", "promo", "推广")])

    def test_list_goes_to_a_new_snapshot_when_there_is_none(self):
        self.run_once(landing_batch(("com.a", "promo", "推广", "A")))

        dirs = self.snapshot_dirs()
        self.assertEqual(len(dirs), 1, f"应新建一份快照目录，实际 {[p.name for p in self.root.iterdir()]}")
        self.assertRegex(dirs[0].name, rf"^{LANDING_MODEL}-\d{{8}}-\d{{4}}$")
        self.assertEqual(chan.load(str(dirs[0] / "channels.tsv")), [("com.a", "promo", "推广")])

    def test_restore_scratch_dir_never_receives_the_list(self):
        # 跑过一次还原的机器都有 `<型号>-gui`（放合并后的 channels-restore.tsv）。
        # 它不能接关渠道的清单：那是历次共用的目录，后一次会覆盖前一次。
        gui = Path(self.root, f"{LANDING_MODEL}-gui")
        gui.mkdir(parents=True)
        (gui / "channels-restore.tsv").write_text("# 上一次还原的合并清单\n", encoding="utf-8")

        self.run_once(landing_batch(("com.a", "promo", "推广", "A")))

        self.assertFalse((gui / "channels.tsv").exists())
        self.assertEqual(chan.load(str(self.snapshot_dirs()[0] / "channels.tsv")),
                         [("com.a", "promo", "推广")])


if __name__ == "__main__":
    unittest.main()
