"""0.2.6 发布当天（2026-10-28）33 份错误日志的回归：华为 / 旧版荣耀卡片布局、vivo 读到旧页、
个别渠道没认出就算失败、断线带堆栈、停止算失败、空报告，以及清单里显示应用名。不用手机。"""
import os
os.environ.setdefault("AAC_NO_SOUND", "1")     # 客户端提示音：测试里不出声
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from fixtures import job_stub
from gui import app
from gui.bundle_data import bundle_data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adb_link
import chan_fast as chan
import fast
from fixtures import phone_stub


APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
VIVO_FOCUS = "com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification.settings.channels.NotificationSettingsActivity"
OCEAN_FOCUS = "com.android.systemui/com.vivo.systemui.statusbar.notification.settings.channels.NotificationSettingsActivity"


def phone(pages, focus, w=1080, h=2340):
    """pages：依次返回的页面，最后一页一直重复。"""
    p = phone_stub("test", d=Mock())
    p.W, p.H = w, h
    p.locked = Mock(return_value=False)
    p.focus = Mock(return_value=focus)
    p.confirm = Mock()
    p.click = Mock()
    p.sig = Mock(return_value="")
    p.settle = Mock(return_value=True)
    p.scroll_more = Mock(return_value=False)
    queue = [ET.fromstring(x) for x in pages]
    p.tree = Mock(side_effect=lambda: queue.pop(0) if len(queue) > 1 else queue[0])
    return p


# 华为 / 旧版荣耀（推断的结构）：渠道排在同一张卡片里，卡片是列表的直接子项，行本身不可点；
# 开关的无障碍标签也是渠道名。
HUAWEI_CARD = '''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node text="淘宝" bounds="[60,100][600,200]"/>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,300][1080,2200]">
    <node class="android.widget.LinearLayout" bounds="[40,320][1040,480]">
      <node class="android.widget.LinearLayout" bounds="[40,320][1040,480]">
        <node text="允许通知" bounds="[80,360][500,440]"/>
        <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,360][1000,440]"/>
      </node>
    </node>
    <node class="android.widget.LinearLayout" bounds="[40,520][1040,1000]">
      <node class="android.widget.LinearLayout" bounds="[40,520][1040,760]">
        <node class="android.widget.LinearLayout" bounds="[80,540][800,740]">
          <node text="营销通知" bounds="[80,560][500,620]"/>
          <node text="横幅、声音" bounds="[80,630][500,690]"/>
        </node>
        <node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true" content-desc="营销通知" bounds="[900,600][1000,680]"/>
      </node>
      <node class="android.widget.LinearLayout" bounds="[40,760][1040,1000]">
        <node class="android.widget.LinearLayout" bounds="[80,780][800,980]">
          <node text="订单通知" bounds="[80,800][500,860]"/>
        </node>
        <node class="com.huawei.uikit.hwswitch.widget.HwSwitch" checkable="true" checked="true" bounds="[900,840][1000,920]"/>
      </node>
    </node>
  </node>
</node></hierarchy>'''

# 标题和开关直接并排放在卡片里：看不出哪个开关属于哪一行，只能放弃
FLAT_CARD = '''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2200]">
    <node class="android.widget.LinearLayout" bounds="[40,520][1040,1000]">
      <node text="营销通知" bounds="[80,560][500,620]"/>
      <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,560][1000,620]"/>
      <node text="订单通知" bounds="[80,800][500,860]"/>
      <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,800][1000,860]"/>
    </node>
  </node>
</node></hierarchy>'''


class HuaweiCardTests(unittest.TestCase):
    def test_row_inside_card_gets_its_own_switch(self):
        # 9 份报告：华为 HarmonyOS 4.0 / 4.2、EMUI 10.1、荣耀 YOK-AN10 / CDY-TN90 每个渠道都「这一行的开关没认出」
        p = phone([HUAWEI_CARD], APP_FOCUS)
        self.assertEqual(chan.inline_switch(p, "营销通知", chan.Attempt()), ("营销通知", True, (950, 640)))
        self.assertEqual(chan.inline_switch(p, "订单通知", chan.Attempt()), ("订单通知", True, (950, 880)))

    def test_app_page_uses_inline_switch_without_clicking_the_title(self):
        p = phone([HUAWEI_CARD], APP_FOCUS)
        with patch.object(chan.time, "sleep"):
            self.assertEqual(chan.via_app_page(p, "com.taobao.taobao", "营销通知", chan.Attempt())[2], (950, 640))
        p.click.assert_not_called()

    def test_flat_card_is_refused_with_text_free_structure(self):
        p = phone([FLAT_CARD], APP_FOCUS)
        at = chan.Attempt()
        self.assertIsNone(chan.inline_switch(p, "营销通知", at))
        self.assertIn("行内开关 2 个", at.why)
        self.assertIn("结构 node#0 < LinearLayout#2 < ListView:s#2", at.why)
        self.assertNotIn("营销通知", at.why)      # 只有控件类型，不带页面文字

    def test_skip_message_carries_the_reason(self):
        p = phone([FLAT_CARD], APP_FOCUS)
        with patch.object(chan, "parse", return_value=({("com.x", "promo"): ("营销通知", 3, False)}, {})), \
             patch.object(chan.time, "sleep"):
            message = chan.toggle(p, "com.x", "promo", False, "营销通知").detail
        self.assertIn("这一行的开关没认出", message)
        self.assertIn("行内开关 2 个", message)


VIVO_CHANNEL = '''<hierarchy><node package="com.vivo.systemuiplugin" bounds="[0,0][1080,2340]">
  <node resource-id="com.vivo.systemuiplugin:id/originui_vtoolbar_normal_title" text="营销通知" bounds="[100,120][600,200]"/>
  <node text="营销通知" bounds="[60,700][600,760]"/>
  <node clickable="true" bounds="[0,900][1080,1010]">
    <node text="允许通知" bounds="[60,920][600,990]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,920][1000,990]"/>
  </node>
</node></hierarchy>'''

VIVO_APP = '''<hierarchy><node package="com.vivo.systemuiplugin" bounds="[0,0][1080,2340]">
  <node resource-id="com.vivo.systemuiplugin:id/originui_vtoolbar_normal_title" text="淘宝" bounds="[100,120][600,200]"/>
  <node clickable="true" bounds="[0,500][1080,610]">
    <node text="允许通知" bounds="[60,520][600,590]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,520][1000,590]"/>
  </node>
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,700][1080,2200]">
    <node clickable="true" bounds="[0,1100][1080,1210]">
      <node text="营销通知" bounds="[60,1120][600,1190]"/>
      <node class="android.widget.CheckBox" checkable="true" checked="true" bounds="[900,1120][1000,1190]"/>
    </node>
  </node>
</node></hierarchy>'''


class VivoTests(unittest.TestCase):
    def test_app_page_is_read_only_after_the_old_channel_page_is_gone(self):
        # 5 份 vivo 报告「点这一行后页面没变；标题顶部」：切回应用通知页时读到的还是直达的渠道页
        p = phone([VIVO_CHANNEL, VIVO_CHANNEL, VIVO_APP, VIVO_CHANNEL], VIVO_FOCUS)
        at = chan.Attempt()
        with patch.object(chan.time, "sleep"):
            sw = chan.via_app_page(p, "com.taobao.taobao", "营销通知", at)
        p.click.assert_called_once_with(330, 1155)        # 应用通知页里的那一行，不是旧页上的标题
        self.assertEqual(at.vivo_app, "淘宝")
        self.assertEqual(sw[2], (950, 955))

    def test_deep_link_page_is_not_waited_on(self):
        # 每个渠道平均 29 秒：直达页按规则不能直接用，以前还要等满 12 轮
        p = phone([VIVO_CHANNEL], VIVO_FOCUS)
        with patch.object(chan.time, "sleep"):
            self.assertIsNone(chan.wait_page(p, "营销通知", chan.Attempt()))
        self.assertEqual(p.tree.call_count, 1)
        self.assertTrue(p.vivo_seen)

    def test_deep_link_page_gives_up_without_a_single_poll(self):
        # 认不出就当场放弃，不是「等满 12 轮再放弃」，也不该多睡一次
        p = phone([VIVO_CHANNEL], VIVO_FOCUS)
        with patch.object(chan.time, "sleep") as nap:
            self.assertIsNone(chan.wait_page(p, "营销通知", chan.Attempt()))
        nap.assert_not_called()

    def test_known_vivo_skips_the_deep_link(self):
        p = phone([VIVO_APP, VIVO_CHANNEL], VIVO_FOCUS)
        p.vivo_seen = True
        with patch.object(chan, "parse", return_value=({("com.taobao.taobao", "promo"): ("营销通知", 3, False)}, {})), \
             patch.object(chan.ChannelPage, "_enter_app_page", return_value=None) as via, patch.object(chan.time, "sleep"):
            chan.toggle(p, "com.taobao.taobao", "promo", False, "营销通知")
        via.assert_called_once()
        self.assertFalse(any("CHANNEL_NOTIFICATION_SETTINGS" in str(c) for c in p.d.shell.call_args_list))

    def test_origin_os_ocean_host_is_recognised(self):
        # OriginOS Ocean / 安卓 10：通知页挂在 com.android.systemui，以前「应用通知页没有打开」
        xml = VIVO_APP.replace("com.vivo.systemuiplugin", "com.android.systemui")
        p = phone([xml], OCEAN_FOCUS)
        self.assertEqual(chan.notification_focus(p), OCEAN_FOCUS)
        self.assertTrue(any(t == "营销通知" for t, _, _ in p.texts(p.tree())))

    def test_systemui_shade_is_still_not_a_notification_page(self):
        p = phone([VIVO_APP], "com.android.systemui/NotificationShade")
        self.assertEqual(chan.notification_focus(p), "")


ITEMS = [("com.a", "promo", "营销通知"), ("com.b", "news", "资讯推送"), ("com.c", "deal", "优惠活动")]
ON = {(pk, cid): (label, 3, False) for pk, cid, label in ITEMS}


def off(data):
    return {k: (v[0], 0, False) for k, v in data.items()}


def run_off(toggle, reads):
    phone = Mock(wait_unlocked=Mock(return_value=True), lost=False)
    with patch.object(chan, "load", return_value=ITEMS), patch.object(chan, "parse", side_effect=[(r, {}) for r in reads]), \
         patch.object(chan, "Phone", return_value=phone), patch.object(chan, "keep_awake", return_value=None), \
         patch.object(chan, "toggle", side_effect=toggle) as toggled, \
         patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", "x.tsv"]), \
         contextlib.redirect_stdout(io.StringIO()) as printed:
        try:
            chan.main()
            code = 0
        except SystemExit as e:
            code = e.code
    return code, printed.getvalue(), toggled


OK = chan.Outcome(chan.DONE)
SKIPPED = chan.Outcome(chan.NOT_CONFIRMED, "未确认「资讯推送」渠道页及通知开关，跳过（停在 x；点这一行后页面没变）")


class RetryTests(unittest.TestCase):
    def test_unconfirmed_channel_is_retried_once_at_the_end(self):
        # OPPO Find X9 关了 67 个剩 1 个、红米 Note 12 Turbo 93 个剩 1 个，整步算失败
        after = dict(off(ON))
        code, printed, toggled = run_off([OK, SKIPPED, OK, OK], [ON, {**after, ("com.b", "news"): ON[("com.b", "news")]}, after])
        self.assertEqual(code, 0)
        self.assertEqual([c.args[2] for c in toggled.call_args_list], ["promo", "news", "deal", "news"])
        self.assertIn("再试一次刚才没确认的 1 个渠道", printed)
        self.assertIn("营销渠道仍开着: 0 个", printed)

    def test_retry_that_fails_again_still_fails_the_step(self):
        still = {**off(ON), ("com.b", "news"): ON[("com.b", "news")]}
        code, printed, toggled = run_off([OK, SKIPPED, OK, SKIPPED], [ON, still, still])
        self.assertEqual(code, 1)
        self.assertIn("仍开着：资讯推送", printed)

    def test_nothing_recognised_means_no_retry(self):
        # 华为那种一个都认不出：重试只会多等，不重试
        code, printed, toggled = run_off([SKIPPED] * 3, [ON, ON])
        self.assertEqual(code, 1)
        self.assertEqual(toggled.call_count, 3)
        self.assertNotIn("再试一次", printed)

    def test_already_changed_channel_is_not_touched_again(self):
        code, printed, toggled = run_off([OK, SKIPPED, OK], [ON, off(ON), off(ON)])
        self.assertEqual(code, 0)
        self.assertEqual(toggled.call_count, 3)

    def test_progress_line_after_connecting(self):
        code, printed, _ = run_off([OK, OK, OK], [ON, off(ON)])
        self.assertIn("要处理 3 个渠道", printed)


class DisconnectTests(unittest.TestCase):
    def test_library_errors_that_mean_the_phone_is_gone(self):
        # OPPO K12：u2 HTTPError「device not found」；一加 Ace 6：AdbShellError「closed」。以前都带着堆栈
        http = fast.u2.exceptions.HTTPError("Unable to connect to uiautomator2 server: device 'x' not found")
        with patch.object(adb_link, "present", return_value=False):
            self.assertIsInstance(adb_link.lost_from(http, "x"), adb_link.DeviceLost)
            try:
                try:
                    raise fast.adbutils.AdbError("closed")
                except fast.adbutils.AdbError as e:
                    raise fast.u2.exceptions.AdbShellError(e)
            except Exception as chained:
                self.assertIsInstance(adb_link.lost_from(chained, "x"), adb_link.DeviceLost)
        with patch.object(adb_link, "present", return_value=True):
            self.assertIsNone(adb_link.lost_from(http, "x"))     # 手机还在：不冒充断开
        self.assertIsNone(adb_link.lost_from(ValueError("closed door"), "x"))

    def test_toggle_turns_library_disconnect_into_device_lost(self):
        p = phone([HUAWEI_CARD], APP_FOCUS)
        p.serial = "x"
        p.tree = Mock(side_effect=fast.u2.exceptions.HTTPError("device 'x' not found"))
        with patch.object(chan, "parse", return_value=({("com.x", "promo"): ("营销通知", 3, False)}, {})), \
             patch.object(adb_link, "present", return_value=False), patch.object(chan.time, "sleep"):
            with self.assertRaises(adb_link.DeviceLost):
                chan.toggle(p, "com.x", "promo", False, "营销通知")

    def test_engine_main_prints_hint_instead_of_traceback(self):
        err = fast.u2.exceptions.AdbShellError("closed")
        with patch.object(fast, "Phone", side_effect=err), patch.object(adb_link, "present", return_value=False), \
             patch.object(sys, "argv", ["fast.py", "-s", "x", "ls"]), contextlib.redirect_stdout(io.StringIO()) as printed:
            with self.assertRaises(SystemExit):
                fast.main()
        self.assertIn("adb 连接断开了", printed.getvalue())


class AppLabelTests(unittest.TestCase):
    def reader(self, reply):
        return types.SimpleNamespace(push=Mock(), shell=Mock(return_value=types.SimpleNamespace(output=reply)))

    def test_labels_are_read_once_and_the_helper_is_removed(self):
        r = self.reader("com.taobao.taobao\t淘宝\ncom.gone\t\n")
        self.assertEqual(chan.app_labels(r, ["com.taobao.taobao", "com.gone", "com.taobao.taobao"]), {"com.taobao.taobao": "淘宝"})
        r.push.assert_called_once_with(chan.LABELS_DEX, chan.LABELS_REMOTE)
        self.assertIn("app_process / aac.Labels com.gone com.taobao.taobao", r.shell.call_args_list[0].args[0])
        self.assertEqual(r.shell.call_args_list[-1].args[0], f"rm -f {chan.LABELS_REMOTE}")

    def test_failure_only_costs_the_names(self):
        r = self.reader("")
        r.push.side_effect = RuntimeError("adb 传文件失败")
        self.assertEqual(chan.app_labels(r, ["com.a"]), {})
        r.shell.assert_not_called()

    def test_long_lists_are_split(self):
        r = self.reader("")
        chan.app_labels(r, [f"com.app{i}" for i in range(90)])
        self.assertEqual(sum("aac.Labels" in c.args[0] for c in r.shell.call_args_list), 3)

    def test_odd_package_names_are_not_passed_to_the_shell(self):
        r = self.reader("")
        chan.app_labels(r, ["com.a;reboot"])
        r.push.assert_not_called()

    def test_scan_prints_app_name_column(self):
        dump = """PackagePreferences:
      AppSettings: com.taobao.taobao importance=DEFAULT
        NotificationChannel{mId='promo', mName=活动优惠, mDescription=null, mImportance=3, mDeleted=false}
      AppSettings: com.unknown importance=DEFAULT
        NotificationChannel{mId='news', mName=新闻推送, mDescription=null, mImportance=3, mDeleted=false}
    """
        with patch.object(chan.ShellPhone, "shell", return_value=types.SimpleNamespace(output=dump)), \
             patch.object(chan, "app_labels", return_value={"com.taobao.taobao": "淘宝"}), \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "x", "scan"]), contextlib.redirect_stdout(io.StringIO()) as printed:
            chan.main()
        self.assertEqual(printed.getvalue(), "com.taobao.taobao\tpromo\t活动优惠\t淘宝\ncom.unknown\tnews\t新闻推送\n")

    def test_list_file_app_column_never_reaches_the_log(self):
        # 上报的日志承诺不含应用列表：第四列只给人看
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "c.tsv")
            f.write_text("com.taobao.taobao\tpromo\t活动优惠\t淘宝\n", encoding="utf-8")
            self.assertEqual(chan.load(str(f)), [("com.taobao.taobao", "promo", "活动优惠")])

    def test_dex_is_shipped_with_the_tools(self):
        self.assertIn(str(ROOT / "tool/applabels.dex"), [src for src, _ in bundle_data(ROOT)])
        self.assertTrue((ROOT / "tool/applabels/Labels.java").exists())


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app

    def api(self, directory):
        api = self.app.Api(directory)
        api.job = job_stub(model="M")
        return api

    def test_stop_is_not_a_failure_and_finish_still_runs(self):
        # 4 份报告是用户点了停止后上报的；停止以前也让插电常亮一直开着
        with tempfile.TemporaryDirectory() as directory:
            api = self.api(directory)
            stopped = Mock(stdout=io.StringIO("正在连接手机读屏服务……\n"))
            stopped.wait.side_effect = lambda: (api.job.request_stop(), -15)[1]
            finish = Mock(stdout=io.StringIO("插电常亮已改回 0\n")); finish.wait.return_value = 0
            with patch.object(self.app.subprocess, "Popen", side_effect=[stopped, finish]) as popen:
                api._work([self.app.Task("关闭营销通知", "run.py", ["-s", "test", "x"]),
                           self.app.Task("关闭快应用", "run.py", ["-s", "test", "quickapp", "off"]),
                           self.app.Task("收尾", "run.py", ["-s", "test", "finish"])])
            self.assertEqual(popen.call_count, 2)
            self.assertEqual([(r["title"], r.get("stopped", False)) for r in api.job.results], [("关闭营销通知", True), ("收尾", False)])
            self.assertIsNone(api.last_error)
            self.assertEqual([s["result"] for s in api.report_payload()["steps"]], ["已停止", "成功"])

    def test_empty_report_is_not_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            api = self.app.Api(directory)
            with patch.object(self.app.urllib.request, "urlopen") as urlopen:
                self.assertEqual(api.send_report({"steps": [], "log": "  "}), {"error": self.app.EMPTY_REPORT})
            urlopen.assert_not_called()

    def test_channel_list_file_keeps_app_names_for_people(self):
        with tempfile.TemporaryDirectory() as directory:
            api = self.api(directory)
            done = Mock(stdout=io.StringIO("")); done.wait.return_value = 0
            with patch.object(self.app.subprocess, "Popen", return_value=done):
                api._work([self.app.Task("关闭营销通知", "chan_fast.py", uses_ui=True,
                                         channels=[{"pkg": "com.taobao.taobao", "id": "promo", "name": "活动优惠", "app": "淘\t宝"}])])
            text = Path(directory, "backups", "M-gui", "channels.tsv").read_text(encoding="utf-8")
            self.assertIn("com.taobao.taobao\tpromo\t活动优惠\t淘 宝\n", text)

    def test_new_version_notice(self):
        class Reply(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        api = self.app.Api(data.name)
        with patch.object(self.app.urllib.request, "urlopen", return_value=Reply(json.dumps({"version": "9.9.9"}).encode())):
            self.assertEqual(api.latest_version(), {"version": "9.9.9", "url": self.app.DOWNLOAD_PAGE})
        with patch.object(self.app.urllib.request, "urlopen", return_value=Reply(json.dumps({"version": self.app.VERSION}).encode())):
            self.assertEqual(api.latest_version(), {})
        # 官网的版本文件取不到：退到 GitHub 的 tag_name
        with patch.object(self.app.urllib.request, "urlopen",
                          side_effect=[OSError("timeout"), Reply(json.dumps({"tag_name": "v9.9.10"}).encode())]):
            self.assertEqual(api.latest_version()["version"], "9.9.10")
        with patch.object(self.app.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(api.latest_version(), {})
        self.assertGreater(self.app.version_key("0.2.10"), self.app.version_key("0.2.9"))



class PauseTests(unittest.TestCase):
    """用户要求：执行中需要操作手机时可以暂停。暂停只在安全的位置生效，继续后重新读页面。"""
    def wait_then_resume(self, path, delay=0.3):
        import threading
        threading.Timer(delay, lambda: Path(path).unlink()).start()

    def test_pause_point_waits_until_resumed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "pause")
            with patch.dict(fast.os.environ, {"AAC_PAUSE_FILE": str(path)}), contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertFalse(fast.pause_point())            # 没点暂停：不停
                path.write_text("")
                self.wait_then_resume(path)
                self.assertTrue(fast.pause_point())
            self.assertIn("⏸ 已暂停", printed.getvalue())
            self.assertIn("▶ 继续执行", printed.getvalue())

    def test_recipe_segments_pause_at_their_lock_check_and_wait_for_unlock(self):
        p = phone_stub("test", d=Mock(), pause_at_lock_check=True)
        p.wait_unlocked = Mock(return_value=True)
        with patch.object(fast, "pause_point", return_value=True):
            self.assertFalse(p.locked())
        p.wait_unlocked.assert_called_once()
        p.d.shell.assert_not_called()

    def test_channels_pause_only_between_channels(self):
        phone = Mock(wait_unlocked=Mock(return_value=True), lost=False)
        with patch.object(chan, "load", return_value=ITEMS), patch.object(chan, "parse", side_effect=[(ON, {}), (off(ON), {})]), \
             patch.object(chan, "Phone", return_value=phone), patch.object(chan, "keep_awake", return_value=None), \
             patch.object(chan, "toggle", return_value=OK), patch.object(chan, "pause_point") as paused, \
             patch.object(sys, "argv", ["chan_fast.py", "-s", "test", "off", "x.tsv"]), contextlib.redirect_stdout(io.StringIO()):
            chan.main()
        self.assertEqual(paused.call_count, 3)
        self.assertIs(phone.pause_at_lock_check, False)

    def test_gui_pause_resume_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            self.assertFalse(api.pause())                                # 没在执行
            api.job = job_stub(serial="t", idx=1, total=2, title="x")
            self.assertTrue(api.pause())
            self.assertTrue(Path(directory, "pause").exists())
            api._log('#aac:event {"kind": "paused"}')
            state = api.poll()
            self.assertEqual((state["pause"], state["paused"]), (True, True))
            api._log('#aac:event {"kind": "resumed"}')
            api.resume()
            self.assertFalse(Path(directory, "pause").exists())
            self.assertEqual((api.poll()["pause"], api.poll()["paused"]), (False, False))
            api.pause()
            api.stop()                                                   # 停止也要放开暂停，引擎才能退出
            self.assertFalse(Path(directory, "pause").exists())

    def test_gui_waits_between_steps_and_passes_the_flag_to_engines(self):
        with tempfile.TemporaryDirectory() as directory:
            api = app.Api(directory)
            api.job = job_stub(serial="t")
            envs = []

            def proc(cmd, **kw):
                envs.append(kw["env"].get("AAC_PAUSE_FILE"))
                if len(envs) == 1:
                    api.pause()                                          # 第一步执行中点了暂停
                    import threading
                    threading.Timer(0.3, api.resume).start()
                done = Mock(stdout=io.StringIO("")); done.wait.return_value = 0
                return done
            with patch.object(app.subprocess, "Popen", side_effect=proc):
                api._work([app.Task("存改动前的快照", "run.py", ["-s", "t", "backup"]),
                           app.Task("收尾", "run.py", ["-s", "t", "finish"])])
            self.assertEqual(envs, [str(Path(directory, "pause"))] * 2)
            log = "\n".join(api.job.lines)
            self.assertLess(log.index("⏸ 已暂停"), log.index("▶ 收尾"))
            self.assertIn("▶ 继续执行", log)
            self.assertFalse(Path(directory, "pause").exists())


if __name__ == "__main__":
    unittest.main()
