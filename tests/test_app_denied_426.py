"""#426 华为 / 荣耀：应用通知被整体关掉时，应用通知页只列「允许通知」总开关、不列渠道。
引擎以前把这种页面记成「没找到这一行」→ 失败；判据也不认安卓 12 上唯一的表达 —— appops。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
from fixtures import phone_stub

APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
PK, CID, NAME = "com.example.app", "promo", "营销通知"


def page(*nodes):
    return ('<hierarchy rotation="0"><node package="com.android.settings" bounds="[0,0][1080,2340]">'
            + "".join(nodes) + "</node></hierarchy>")


def phone(pages, focus=APP_FOCUS):
    """当前页在点击之后才换成下一页：同一页可以读很多次，最后一页一直重复。"""
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


# 应用通知页：这个应用的通知被系统整体关了 —— 渠道列表不出现，只剩「允许通知」总开关
MASTER_ONLY = page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    '<node class="android.widget.TextView" text="允许通知" bounds="[60,720][500,800]"/>'
    '<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true" checked="true"'
    ' clickable="true" bounds="[900,720][1040,800]"/></node>',
)

# 应用通知页：渠道行在，只是行内开关没认出（这时不许套用「应用通知整体关闭」）
ROW_UNREADABLE = page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    '<node clickable="true" bounds="[0,700][1080,860]">'
    f'<node class="android.widget.TextView" text="{NAME}" bounds="[60,720][700,800]"/></node>',
)


def shell(appops_mode="allow", permission=None):
    """读屏层的假传输：dumpsys package 与 appops 各回各的。"""
    def run(command, *a, **k):
        if "appops" in command:
            return Mock(output=f"POST_NOTIFICATION: {appops_mode}\n")
        if "granted=" in command:
            return Mock(output=permission or "")
        return Mock(output="")
    return run


# 应用通知页：列出了渠道，但渠道名写在 CheckBox 自己身上（#427 那 194 次），这轮一行都没认出来
CHECKBOX_ROWS = page(
    '<node class="android.widget.TextView" text="示例应用" bounds="[0,111][1080,360]"/>',
    *[f'<node class="android.widget.CheckBox" text="渠道{i}" checkable="true" checked="true"'
      f' clickable="true" bounds="[60,{700 + i * 160}][1020,{860 + i * 160}]"/>' for i in range(3)],
)


def outcome(p, want_on=False):
    with patch.object(chan, "parse", return_value=({(PK, CID): (NAME, 3, False)}, {})), \
         patch.object(chan.time, "sleep"):
        return chan.toggle(p, PK, CID, want_on, NAME)


class AppLevelOffTests(unittest.TestCase):
    def test_appops_ignore_on_the_master_only_page_is_not_a_failure(self):
        # 华为 HarmonyOS 4.2（安卓 12）没有 POST_NOTIFICATIONS 权限，只能看 appops
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("ignore")
        self.assertEqual(outcome(p).kind, chan.APP_DENIED)

    def test_appops_deny_is_the_same_answer(self):
        # 新一点的系统上同一个开关写作 deny
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("deny")
        self.assertEqual(outcome(p).kind, chan.APP_DENIED)

    def test_appops_allow_is_ui_hidden(self):
        # 应用通知开着、页面上却没有这个渠道：不是「应用通知整体关闭」，也不该每轮重复报同一条失败
        # —— 记成「本机 UI 未暴露」，下一轮扫描不再列出（#576）
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("allow")
        self.assertEqual(outcome(p).kind, chan.UI_HIDDEN)

    def test_unreadable_appops_is_still_a_failure(self):
        # 命令报错 / 输出不认识时既不算「关着」，也不算「明确没关」：
        # 名单是持久的，读不出来就继续报失败，不把渠道记成「本机 UI 未暴露」（#576）
        def broken(command, *a, **k):
            if "appops" in command:
                raise RuntimeError("shell output invalid")
            return Mock(output="")
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = broken
        got = outcome(p)
        self.assertEqual(got.kind, chan.NOT_CONFIRMED)
        self.assertIn("总开关读不出来", got.detail)

    def test_no_operations_means_not_denied(self):
        # 这个应用没有 POST_NOTIFICATION 这条 appops 记录：读不出=没关
        def unknown_op(command, *a, **k):
            if "appops" in command:
                return Mock(output="No operations.\n")
            return Mock(output="")
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = unknown_op
        self.assertEqual(outcome(p).kind, chan.UI_HIDDEN)

    def test_a_listed_row_without_a_readable_switch_is_not_degraded(self):
        # 渠道行在页面上（#427 那批），只是行内开关没认出：此时不许套用总开关判据
        p = phone([ROW_UNREADABLE])
        p.reader.shell.side_effect = shell("ignore")
        self.assertEqual(outcome(p).kind, chan.NOT_CONFIRMED)

    def test_a_page_full_of_channels_is_not_degraded(self):
        # 页面明明列着渠道（渠道名写在 CheckBox 上、这轮没认出来）就说明应用通知没关：
        # 不能因为「这轮没找到行」就把 #427 那批算成 #426
        p = phone([CHECKBOX_ROWS])
        p.reader.shell.side_effect = shell("ignore")
        self.assertEqual(outcome(p).kind, chan.NOT_CONFIRMED)

    def test_restore_direction_keeps_the_old_wording(self):
        # 还原（chan-on）方向不套这条判据：文案与记账维持原样
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("ignore")
        got = outcome(p, want_on=True)
        self.assertEqual(got.kind, chan.NOT_CONFIRMED)
        self.assertIn("未确认「营销通知」渠道页及通知开关，跳过", got.detail)

    def test_granted_permission_short_circuits_appops(self):
        # 权限读数说 granted=true 就是没关，不再去问 appops（#330 记过两者可能不同步）
        p = phone([MASTER_ONLY])
        p.reader.shell.side_effect = shell("ignore", permission="  POST_NOTIFICATIONS: granted=true, flags=[ ]\n")
        self.assertEqual(outcome(p).kind, chan.UI_HIDDEN)
        self.assertFalse([c for c in p.reader.shell.call_args_list if "appops" in str(c)])

    def test_unconfirmed_page_is_not_degraded(self):
        # 压根没确认停在应用通知页（前台是别的页面）时，就算 appops 说 ignore 也不能降级
        p = phone([MASTER_ONLY], focus="com.vendor.notify/.UnknownPage")
        p.reader.shell.side_effect = shell("ignore")
        self.assertEqual(outcome(p).kind, chan.NOT_CONFIRMED)


if __name__ == "__main__":
    unittest.main()
