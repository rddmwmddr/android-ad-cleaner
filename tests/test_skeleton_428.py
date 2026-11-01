"""#428 渠道页认不出时上报脱敏页面骨架：只含结构字段，不含页面文字。

样本按 #427 报告者的华为形态造：渠道名只写在 CheckBox 上，行容器可点。
"""
import io
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast as chan
import events
import row
from fixtures import phone_stub

FOCUS = "com.huawei.android.settings/.SubSettings"

# 渠道名只在 CheckBox 的 content-desc 上；列表里另有一行无关文字
HUAWEI_CARD = '''<hierarchy rotation="0">
<node package="com.huawei.android.settings" class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="通知管理" bounds="[40,100][400,160]"/>
  <node class="android.widget.ScrollView" scrollable="true" bounds="[0,200][1080,2340]">
    <node class="android.widget.LinearLayout" clickable="true" bounds="[0,300][1080,420]">
      <node class="android.widget.TextView" text="活动与优惠" bounds="[40,320][400,360]"/>
      <node class="android.widget.CheckBox" content-desc="营销通知" checkable="true" checked="true"
            clickable="true" bounds="[880,320][1000,400]"/>
    </node>
  </node>
</node>
</hierarchy>'''


def skeleton(xml, name="营销通知", w=1080, h=2340, focus=FOCUS):
    return row.skeleton(ET.fromstring(xml), name, w, h, focus)


FLAGS_PAGE = '''<hierarchy rotation="0">
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="android.widget.LinearLayout" clickable="true" bounds="[0,300][1080,420]">
    <node class="android.widget.TextView" text="营销通知" bounds="[40,300][400,340]"/>
    <node class="android.widget.TextView" content-desc="营销通知" bounds="[40,340][400,380]"/>
    <node class="android.widget.TextView" text="营销通知，已关闭" bounds="[40,380][600,420]"/>
  </node>
</node>
</hierarchy>'''


def rows(page_name="营销通知", count=1):
    """count 行可点的渠道行，每行一段文字（或只有开关）。"""
    body = "".join(
        f'<node clickable="true" bounds="[0,{300 + i * 20}][1080,{310 + i * 20}]">'
        + (f'<node class="android.widget.TextView" text="{page_name}" '
           f'bounds="[40,{300 + i * 20}][400,{305 + i * 20}]"/>' if page_name else "")
        + f'<node class="android.widget.CheckBox" checkable="true" checked="true" '
          f'bounds="[880,{300 + i * 20}][1000,{310 + i * 20}]"/></node>'
        for i in range(count))
    return ('<hierarchy rotation="0"><node class="android.widget.ScrollView" scrollable="true" '
            'bounds="[0,200][1080,2340]">' + body + "</node></hierarchy>")


class SkeletonTests(unittest.TestCase):
    def test_the_name_on_a_checkbox_is_marked_in_the_skeleton(self):
        text = skeleton(HUAWEI_CARD)
        head, body = text.split("\n", 1)
        self.assertTrue(head.startswith("骨架 v1"), head)
        self.assertIn("锚=名1", head)
        self.assertIn("CheckBox", body)
        self.assertIn("M", body)                 # content-desc 等于渠道名
        self.assertNotIn("活动与优惠", body)      # 页面文字不进骨架
        self.assertNotIn("通知管理", body)

    def test_a_row_with_only_a_switch_is_the_fallback_anchor(self):
        text = skeleton(rows(page_name="", count=2))
        head, body = text.split("\n", 1)
        self.assertIn("锚=回退列表2", head)
        self.assertIn("CheckBox", body)

    def test_the_fallback_skips_radio_buttons_and_reports_the_rows_it_kept(self):
        # RadioButton 是互斥选项，不算开关；它排在最前，混进来就会占掉 3 行里的一行。
        # 6 个带开关的行：只带 3 行，头部也得写 3。
        radio = ('<node class="android.widget.RadioButton" checkable="true" checked="true" '
                 'bounds="[880,220][1000,270]"/>')
        page = rows(page_name="", count=6).replace(
            'class="android.widget.ScrollView" scrollable="true" bounds="[0,200][1080,2340]">',
            'class="android.widget.ScrollView" scrollable="true" bounds="[0,200][1080,2340]">' + radio, 1)
        head, body = skeleton(page).split("\n", 1)
        self.assertIn("锚=回退列表3", head)
        self.assertEqual(body.count("CheckBox"), 3)
        self.assertNotIn("RadioButton", body)

    def test_a_nonstandard_resource_id_is_dropped_instead_of_leaking_text(self):
        page = ('<hierarchy rotation="0"><node class="android.widget.TextView" '
                'resource-id="营销通知-不是标准 id" bounds="[40,300][400,360]"/></hierarchy>')
        body = skeleton(page, "别的名字").split("\n", 1)[1]
        self.assertNotIn("id=", body)
        self.assertNotIn("营销通知", body)

    def test_the_character_cap_trims_from_the_end(self):
        nodes = "".join(
            f'<node class="android.widget.{"X" * 50}" resource-id="com.x:id/{"y" * 40}" '
            f'bounds="[0,{100 + i * 10}][1080,{105 + i * 10}]"/>' for i in range(60))
        page = f'<hierarchy rotation="0"><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">{nodes}</node></hierarchy>'
        text = skeleton(page, "营销通知")
        head, body = text.split("\n", 1)
        self.assertLessEqual(len(text), row.SKELETON_BYTES)
        self.assertNotIn("剪枝=0", head)
        self.assertLess(len(body.splitlines()), 40)

    def test_a_page_without_name_or_switch_falls_back_to_the_first_nodes(self):
        page = ('<hierarchy rotation="0"><node class="android.widget.TextView" text="甲" '
                'bounds="[0,100][400,160]"/><node class="android.widget.TextView" text="乙" '
                'bounds="[0,200][400,260]"/></hierarchy>')
        text = skeleton(page, "营销通知")
        head, body = text.split("\n", 1)
        self.assertIn("锚=回退前2", head)
        self.assertEqual(len(body.splitlines()), 2)
        self.assertNotIn("甲", body)
        self.assertNotIn("乙", body)

    def test_exact_text_exact_desc_and_containment_are_told_apart(self):
        flags = [ln.split()[3] for ln in skeleton(FLAGS_PAGE).split("\n")[1:] if len(ln.split()) > 3]
        self.assertIn("TN", flags)       # text 等于渠道名
        self.assertIn("DM", flags)       # content-desc 等于渠道名
        self.assertIn("TP", flags)       # 只是包含：名字被拼进更长的文案，没有 N / M

    def test_off_screen_invisible_and_status_bar_nodes_stay_out(self):
        page = '''<hierarchy rotation="0">
<node class="android.widget.StatusBar" package="com.android.systemui" bounds="[0,0][1080,60]"/>
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="android.widget.InvisibleBox" visible-to-user="false" bounds="[0,100][1080,200]"/>
  <node class="android.widget.OffScreenBox" bounds="[0,3000][1080,3100]"/>
  <node class="android.widget.TextView" text="营销通知" bounds="[40,300][400,360]"/>
</node>
</hierarchy>'''
        body = skeleton(page).split("\n", 1)[1]
        self.assertNotIn("StatusBar", body)
        self.assertNotIn("InvisibleBox", body)
        self.assertNotIn("OffScreenBox", body)
        self.assertIn("TextView", body)

    def test_the_skeleton_stops_at_eighty_nodes(self):
        # 8 个同名锚点各带一整行（行内 12 个子节点），选中远超 80
        rows_xml = "".join(
            f'<node clickable="true" bounds="[0,{300 + i * 20}][1080,{310 + i * 20}]">'
            f'<node class="android.widget.TextView" text="营销通知" bounds="[40,{300 + i * 20}][400,{305 + i * 20}]"/>'
            + "".join(f'<node class="android.widget.TextView" text="细节{j}" '
                      f'bounds="[40,{300 + i * 20}][400,{305 + i * 20}]"/>' for j in range(12))
            + "</node>"
            for i in range(20))
        page = ('<hierarchy rotation="0"><node class="android.widget.ScrollView" scrollable="true" '
                'bounds="[0,200][1080,2340]">' + rows_xml + "</node></hierarchy>")
        text = skeleton(page)
        head, body = text.split("\n", 1)
        self.assertIn("节点=80", head)
        self.assertNotIn("剪枝=0", head)
        self.assertEqual(len(body.splitlines()), 80)

    def test_resource_id_keeps_the_short_name_and_is_cut_at_forty(self):
        long_id = "com.huawei.android.settings:id/" + "x" * 60
        page = ('<hierarchy rotation="0"><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">'
                '<node class="android.widget.Switch" resource-id="com.huawei.android.settings:id/switch_widget" '
                'checkable="true" bounds="[880,300][1000,400]"/>'
                f'<node class="android.widget.Switch" resource-id="{long_id}" checkable="true" '
                'bounds="[880,500][1000,600]"/></node></hierarchy>')
        body = skeleton(page, "营销通知").split("\n", 1)[1]
        self.assertIn("id=switch_widget", body)
        self.assertIn("id=" + "x" * 40 + "…", body)
        self.assertNotIn("com.huawei.android.settings", body)


def phone(pages):
    """每次读屏返回下一页，最后一页重复。"""
    p = phone_stub("test", d=Mock())
    p.W, p.H = 1080, 2340
    p.locked = Mock(return_value=False)
    p.focus = Mock(return_value=FOCUS)
    queue = [ET.fromstring(x) for x in pages]
    p.tree = Mock(side_effect=lambda: queue.pop(0) if len(queue) > 1 else queue[0])
    return p


class ChannelPageSkeletonTests(unittest.TestCase):
    def test_only_the_row_not_found_stage_carries_a_skeleton(self):
        p = phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = "点进去后没认出渠道页"
        page._hint()
        self.assertEqual(page.skeleton, "")

        p = phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        page._hint()
        self.assertTrue(page.skeleton.startswith("骨架 v1"))

    def test_the_same_layout_is_reported_once_and_two_layouts_at_most(self):
        p = phone([HUAWEI_CARD, HUAWEI_CARD, FLAGS_PAGE, rows(page_name="", count=1)])

        def attempt():
            page = chan.ChannelPage(p, "营销通知")
            page.stage = chan.ROW_NOT_FOUND
            page._hint()
            return page.skeleton

        self.assertTrue(attempt().startswith("骨架 v1"))
        self.assertEqual(attempt(), "")           # 同布局失败很多个渠道：只留第一份
        self.assertEqual(p.skeleton_count, 1)

        self.assertTrue(attempt().startswith("骨架 v1"))          # 第二种布局
        self.assertEqual(p.skeleton_count, 2)
        self.assertEqual(attempt(), "")                           # 第三份不再带
        self.assertEqual(p.skeleton_count, 2)

    def test_hint_does_not_read_the_focus_window_again(self):
        # ADR-0007：p.focus() 的调用次数只减不增；骨架用 _focus() 留下的 raw_focus
        p = phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        page.raw_focus = FOCUS
        page._hint()
        self.assertTrue(page.skeleton.startswith("骨架 v1"))
        p.focus.assert_not_called()

    def test_a_second_channel_name_on_the_same_layout_is_not_a_new_skeleton(self):
        # 同一页、换了目标渠道名：布局没变，不该再带一份
        p = phone([HUAWEI_CARD, HUAWEI_CARD])
        for name in ("营销通知", "活动推送"):
            page = chan.ChannelPage(p, name)
            page.stage = chan.ROW_NOT_FOUND
            page._hint()
            if name == "营销通知":
                self.assertTrue(page.skeleton.startswith("骨架 v1"))
            else:
                self.assertEqual(page.skeleton, "")
        self.assertEqual(p.skeleton_count, 1)

    def test_an_app_level_denial_carries_no_skeleton(self):
        # 应用通知整体关着：页面上只有总开关，行不在页面上，不是没认出来（#426）
        p = phone([HUAWEI_CARD])
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        page.no_row = True
        page._hint()
        self.assertEqual(page.skeleton, "")
        self.assertEqual(p.skeleton_count, 0)

    def test_a_page_that_cannot_be_read_keeps_the_step_alive(self):
        p = phone([HUAWEI_CARD])
        p.tree = Mock(side_effect=RuntimeError("dump 失败"))
        page = chan.ChannelPage(p, "营销通知")
        page.stage = chan.ROW_NOT_FOUND
        self.assertEqual(page._hint(), "")
        self.assertEqual(page.skeleton, "")


class ToggleWiringTests(unittest.TestCase):
    def test_the_failure_outcome_carries_the_skeleton_to_the_report(self):
        p = Mock()
        p.locked.return_value = False
        reached = chan.Unreached(chan.ROW_NOT_FOUND, "", "", False, "骨架 v1\n0 X 0,0,100,100")
        with patch.object(chan, "parse", return_value=({("com.x", "promo"): ("营销通知", 3, False)}, {})), \
             patch.object(chan.ChannelPage, "open", return_value=reached):
            out = chan.toggle(p, "com.x", "promo", False, "营销通知")
        self.assertEqual(out.kind, chan.NOT_CONFIRMED)
        self.assertEqual(out.payload, "骨架 v1\n0 X 0,0,100,100")


class PayloadLineTests(unittest.TestCase):
    def test_silent_unless_the_client_asked_for_it(self):
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(out):
            os.environ.pop("AAC_EVENTS", None)
            events.payload("骨架 v1\n0 FrameLayout 0,0,100,100")
        self.assertEqual(out.getvalue(), "")

    def test_every_skeleton_line_gets_the_prefix(self):
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(out):
            os.environ["AAC_EVENTS"] = "1"
            events.payload("骨架 v1\n0 FrameLayout 0,0,100,100")
        self.assertEqual(out.getvalue().splitlines(), [
            "#aac:payload 骨架 v1",
            "#aac:payload 0 FrameLayout 0,0,100,100",
        ])

    def test_payload_lines_are_not_events(self):
        line = "#aac:payload 骨架 v1"
        self.assertTrue(events.is_payload(line))
        self.assertFalse(events.is_event(line))
        self.assertEqual(events.strip_payload(line), "骨架 v1")


class ShowTests(unittest.TestCase):
    def test_the_skeleton_is_printed_after_the_failure_line(self):
        outcome = chan.Outcome(chan.NOT_CONFIRMED, "未确认「营销通知」渠道页及通知开关", "骨架 v1\n0 X 0,0,100,100")
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), redirect_stdout(out):
            os.environ["AAC_EVENTS"] = "1"
            chan.show(outcome, "营销通知", False)
        lines = out.getvalue().splitlines()
        self.assertIn("✗", lines[0])
        self.assertEqual(lines[1:], ["#aac:payload 骨架 v1", "#aac:payload 0 X 0,0,100,100"])


os.environ.setdefault("AAC_NO_SOUND", "1")
from gui import app


class ClientLogTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.api = app.Api(self._dir.name)
        self.api.job = {"running": True, "cancel": False, "lines": [], "results": [],
                        "step_events": set(), "serial": "test", "t0": 0, "idx": 0,
                        "total": 0, "title": "", "model": "m"}

    def tearDown(self):
        self._dir.cleanup()

    def test_payload_reaches_the_report_but_not_the_step_summary(self):
        shown = self.api._log("#aac:payload 骨架 v1 页=com.huawei.android.settings/.SubSettings")
        self.assertIsNone(shown)                 # 进不了 tail（步骤摘要）
        self.assertEqual(self.api.job["lines"], [])          # 也不进界面日志
        report = self.api.report_payload()
        self.assertEqual(report["log"].count("骨架 v1"), 1)  # 只出现一次
        self.assertIn("[页面骨架]", report["log"])
        self.assertNotIn("aac:payload", json.dumps(report, ensure_ascii=False))

    def test_events_still_stay_out_of_the_log(self):
        self.api._log('#aac:event {"kind": "paused"}')
        self.assertEqual(self.api.job["lines"], [])
