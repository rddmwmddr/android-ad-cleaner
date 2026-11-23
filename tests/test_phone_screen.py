"""观测基座 `tool/phone/screen.py`：读屏、认行、页面诊断、视口几何与动作原语（ADR-0033）。

`Screen` 只认注入的 `Connection`，所以这里不必造整台 `Phone`：读屏替身、假设备与假钟都取
`tests/fixtures.py` 已有的装配，逐条断言它对外可观察的行为——读到的文字、算出的落点、
下发的命令、抛出的文案。装配仍只落 `fixtures`，不另造一套。
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fixtures  # noqa: E402
import geometry  # noqa: E402
import screen_snapshot  # noqa: E402

fixtures.load_tool()
import fast  # noqa: E402

EMPTY_PAGE = "<hierarchy/>"

PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
    <node text="个性化广告推荐" bounds="[60,600][700,660]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,600][1040,660]"/>
    <node text="隐私" bounds="[60,900][400,960]"/>
  </node>
</hierarchy>"""

SCROLLABLE = """<hierarchy><node bounds="[0,0][1080,2340]">
  <node scrollable="true" bounds="[0,300][1080,2000]">
    <node text="设置项" bounds="[60,400][600,460]"/>
  </node>
</node></hierarchy>"""

SWITCH_ROW = """<hierarchy><node bounds="[0,0][1080,2340]">
  <node clickable="true" bounds="[0,300][1080,500]">
    <node text="边下边玩" bounds="[60,320][600,380]"/>
    <node text="不涉及隐私数据" bounds="[60,420][900,480]"/>
    <node class="android.widget.Switch" checkable="true" checked="false" bounds="[900,320][1040,380]"/>
  </node>
</node></hierarchy>"""

SELF_DRAWN = """<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node package="com.android.systemui" text="通知" bounds="[0,0][100,40]"/>
  <node bounds="[0,500][1080,660]">
    <node text="个性化推荐" bounds="[60,510][600,590]"/>
    <node resource-id="com.x:id/toggle_switch" clickable="true" bounds="[900,500][1040,600]"/>
  </node>
</node></hierarchy>"""


class Shot:
    """假截图：尺寸对得上；轨道三个取样点都取彩色像素（`pixel_on` 判开）。"""

    def __init__(self, size=(1080, 2340)):
        self.size = size

    def convert(self, mode):
        return self

    def getpixel(self, xy):
        return (0, 200, 0)


class ScriptedDevice(fixtures.Device):
    """假设备 + 命令流水：`shell` 按命令子串应答，没命中的回一个固定结果。"""

    def __init__(self, *, size=(1080, 2340), stages=((0.0, EMPTY_PAGE),), clock=None,
                 answers=(), response=None, shot=None):
        super().__init__(fixtures.Timeline(list(stages)), size, clock or fixtures.Clock())
        self.commands = []
        self.answers = list(answers)
        self.response = response if response is not None else SimpleNamespace(output="", exit_code=0)
        self.shots = 0
        self.shot = shot if shot is not None else Shot(size)

    def shell(self, cmd, timeout=60):
        self.commands.append(cmd)
        for key, value in self.answers:
            if key in cmd:
                return SimpleNamespace(output=value, exit_code=0)
        return self.response

    def screenshot(self):
        self.shots += 1
        return self.shot


class Selection:
    """uiautomator2 选择器的替身：`click` / `click_exists` / 下标都记在 reader 上。"""

    def __init__(self, reader, selector):
        self.reader, self.selector = reader, selector

    def __getitem__(self, index):
        self.reader.indexes.append(index)
        return self

    def click(self):
        self.reader.clicks.append(self.selector)

    def click_exists(self, timeout=0):
        self.reader.existence.append((self.selector, timeout))
        return True


class SelectionReader:
    """选择器与输入框的读屏替身：`reader(**选择器)` 与 `reader.jsonrpc.setText` 都记账。"""

    def __init__(self, size=(1080, 2340)):
        self.size = size
        self.settings = {}
        self.shells = []
        self.selectors = []
        self.indexes = []
        self.clicks = []
        self.existence = []
        self.typed = []
        self.jsonrpc = SimpleNamespace(setText=self.set_text)

    def window_size(self):
        return self.size

    def dump_hierarchy(self):
        return ""

    def shell(self, cmd, timeout=60):
        self.shells.append(cmd)
        return SimpleNamespace(output="", exit_code=0)

    def close(self):
        pass

    def __call__(self, **selector):
        self.selectors.append(selector)
        return Selection(self, selector)

    def set_text(self, selector, text, http_timeout=None):
        self.typed.append((selector, text, http_timeout))


class ScreenTestCase(unittest.TestCase):
    """共用装配：假钟装进 `fast`（连到观测基座），每条用例自己给读屏替身。"""

    def setUp(self):
        self.clock = fixtures.clocked(self, fast, fixtures.Clock())

    def screen(self, reader):
        return fast.Screen(fast.Connection("test", log=False, reader=reader))

    def device(self, **kwargs):
        return ScriptedDevice(clock=self.clock, **kwargs)


class ConstructionTests(ScreenTestCase):
    """构造出的默认状态：没有 systemui 文字、没有失败现场、捕获目录为空。"""

    def test_construction_defaults(self):
        screen = self.screen(self.device())
        self.assertIs(screen.systemui_text, False)
        self.assertEqual(screen.dump, "")
        self.assertEqual(screen.pending_capture, "")
        self.assertEqual(screen.captures.dir, "")

    def test_a_given_capture_store_is_kept(self):
        import captures
        store = captures.Captures("/tmp/does-not-matter")
        conn = fast.Connection("test", log=False, reader=self.device())
        self.assertIs(fast.Screen(conn, captures=store).captures, store)


class FocusTests(ScreenTestCase):
    """前台窗口：mCurrentFocus 优先，缺了看 mFocusedApp，再退到 dumpsys activity。"""

    def focus(self, **answers):
        device = self.device(answers=tuple(answers.items()))
        self.device_used = device
        return self.screen(device)

    def test_the_current_focus_command_is_sent_verbatim(self):
        screen = self.focus(**{"dumpsys window": "  mCurrentFocus=Window{4c2 u0 com.a/.A}\n"})
        self.assertEqual(screen.focus(), "com.a/.A")
        self.assertEqual(self.device_used.commands,
                         ["dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | sed -n '1,4p'"])

    def test_a_null_focus_falls_back_to_the_focused_app(self):
        screen = self.focus(**{"dumpsys window":
                               "  mCurrentFocus=null\n"
                               "  mFocusedApp=ActivityRecord{5e1 u0 com.android.settings/.Settings$X t88}\n"})
        self.assertEqual(screen.focus(), "com.android.settings/.Settings$X")

    def test_the_activity_dump_is_the_last_resort(self):
        screen = self.focus(**{"dumpsys activity activities": "  mResumedActivity: com.b/.B\n"})
        self.assertEqual(screen.focus(), "com.b/.B")
        self.assertEqual(self.device_used.commands, [
            "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | sed -n '1,4p'",
            "dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity|ResumedActivity:'"
            " | sed -n '1p'",
        ])


def words_page(count):
    nodes = "".join(
        '<node text="词%d" bounds="[0,%d][500,%d]"/>' % (i, i * 40, i * 40 + 30)
        for i in range(count))
    return '<hierarchy><node bounds="[0,0][1080,2340]">' + nodes + "</node></hierarchy>"


class PageTextTests(ScreenTestCase):
    """`page_text()` 是失败诊断用的前 20 条：第 21 条不该被带出来。"""

    def test_only_the_first_twenty_texts_are_joined(self):
        screen = fixtures.screen_stub(words_page(21))
        self.assertEqual(screen.page_text(), " / ".join(f"词{i}" for i in range(20)))


class SnapshotTests(ScreenTestCase):
    """一次读屏的快照：systemui 开关透传、自绘开关取一次图、`with_rows=False` 不取图。"""

    def test_systemui_text_and_one_screenshot_reach_the_snapshot(self):
        device = self.device(stages=((0.0, SELF_DRAWN),))
        screen = self.screen(device)
        screen.systemui_text = True
        snap = screen.snapshot(focus="")
        self.assertIn("通知", snap.signature)
        self.assertEqual([(row.title, row.checked) for row in snap.rows], [("个性化推荐", True)])
        self.assertEqual(device.shots, 1)

    def test_without_rows_no_screenshot_is_taken(self):
        device = self.device(stages=((0.0, SELF_DRAWN),))
        screen = self.screen(device)
        snap = screen.snapshot(with_rows=False, focus="")
        self.assertEqual(snap.rows, ())
        self.assertEqual(device.shots, 0)


LIST_PAGE = """<hierarchy>
  <node bounds="[0,0][1080,2340]">
    <node bounds="[0,600][1080,660]">
      <node text="个性化广告推荐" bounds="[60,600][700,660]"/>
      <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,600][1040,660]"/>
    </node>
    <node bounds="[0,900][1080,960]">
      <node text="广告跟踪" bounds="[60,900][700,960]"/>
      <node class="android.widget.Switch" checkable="true" checked="false" bounds="[900,900][1040,960]"/>
    </node>
  </node>
</hierarchy>"""


class ListingTests(ScreenTestCase):
    """`ls` 是一条诊断打印：一次读屏、逐行原文，开关按开/关标注。"""

    def test_the_listing_prints_the_page_once(self):
        device = self.device(stages=((0.0, LIST_PAGE),))
        screen = self.screen(device)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            screen.ls()
        self.assertEqual(out.getvalue().splitlines(),
                         ["· ", "个性化广告推荐 / 广告跟踪",
                          "  [开] 个性化广告推荐  @(970, 630)",
                          "  [关] 广告跟踪  @(970, 930)"])
        self.assertEqual(self.clock.page_reads, 1)


class DiagnosisTests(ScreenTestCase):
    """页面结构读不到时只吞解析失败，换一句人话；断线照旧冒泡由连接层负责。"""

    def test_a_broken_tree_is_reported_in_words(self):
        screen = fixtures.screen_stub(PAGE)
        screen.focus = lambda: ""
        screen.tree = lambda: (_ for _ in ()).throw(ET.ParseError())
        self.assertEqual(screen._page_diagnosis(), ("未知页面", "页面结构读不到"))


class Store:
    """捕获目录的替身：只记落盘参数。"""

    def __init__(self):
        self.saved = []

    def save(self, page, size=None):
        self.saved.append((page, size))
        return "folder"


class CaptureStateTests(ScreenTestCase):
    """失败现场的记账：段结束时取走且只写一次；页面证据按当次读到的标题拼句。"""

    def test_save_capture_takes_the_page_once_and_clears_it(self):
        screen = fixtures.screen_stub(PAGE)
        store = Store()
        screen.captures = store
        screen.pending_capture = "<node/>"
        screen.save_capture()
        screen.save_capture()
        self.assertEqual(store.saved, [("<node/>", (1080, 2340))])
        self.assertEqual(screen.pending_capture, "")

    def test_page_evidence_lists_the_titles_in_order(self):
        screen = fixtures.screen_stub(PAGE)
        screen.focus = lambda: "com.a/.A"
        self.assertTrue(screen.page_evidence(["甲", "乙"]).endswith("当次读到 2 个开关：甲、乙"))

    def test_page_evidence_says_so_when_no_switch_was_read(self):
        screen = fixtures.screen_stub(PAGE)
        screen.focus = lambda: "com.a/.A"
        self.assertTrue(screen.page_evidence().endswith("当次读到 0 个开关：无"))


class ConfirmTargetTests(ScreenTestCase):
    """确认框的落点：退化（零宽 / 零高）的按钮不算，正常的取中心。"""

    def page(self, bounds, cls="android.widget.Button"):
        return (f'<hierarchy><node class="{cls}" text="确定" '
                f'bounds="{bounds}"/></hierarchy>')

    def test_a_normal_button_is_found_at_its_center(self):
        screen = fixtures.screen_stub(self.page("[100,200][300,400]"))
        self.assertEqual(screen.confirm_target(), ("确定", (200, 300)))

    def test_a_zero_width_button_is_skipped(self):
        screen = fixtures.screen_stub(self.page("[100,200][100,400]"))
        self.assertIsNone(screen.confirm_target())

    def test_a_zero_height_button_is_skipped(self):
        screen = fixtures.screen_stub(self.page("[100,200][300,200]"))
        self.assertIsNone(screen.confirm_target())


def icon_page(*nodes):
    body = "".join(nodes)
    return f'<hierarchy><node bounds="[0,0][1080,2340]">{body}</node></hierarchy>'


def icon(bounds, **attrs):
    extra = "".join(f' {key}="{value}"' for key, value in attrs.items())
    return f'<node bounds="{bounds}"{extra}/>'


class IconCandidateTests(ScreenTestCase):
    """图标候选：只要无文字、在取样区、尺寸像图标、点得动的那些，按 x 从右往左。"""

    def candidates(self, page, size=(1080, 2340), area=None):
        screen = fixtures.screen_stub(page, size)
        return screen.icon_candidates() if area is None else screen.icon_candidates(area)

    def test_invalid_nodes_are_skipped_and_the_valid_one_survives(self):
        page = icon_page(
            icon("[900,80][1020,180]", clickable="false"),
            icon("[900,90][1020,190]", clickable="true", text="齿轮"),
            icon("[900,100][1020,200]", clickable="true", **{"content-desc": "更多"}),
            icon("[400,100][600,200]", clickable="true"),
            icon("[700,500][1100,600]", clickable="true"),
            icon("[700,100][1140,200]", clickable="true"),
            icon("[800,140][980,440]", clickable="true"),
            icon("[900,140][1020,240]", clickable="true"),
        )
        self.assertEqual(self.candidates(page), [(960, 190)])

    def test_boundaries_are_inclusive(self):
        page = icon_page(
            icon("[700,100][740,140]", clickable="true"),        # 中心正好在 x0
            icon("[980,100][1020,140]", clickable="true"),       # 中心正好在 x1
        )
        size = (1000, 1000)
        self.assertEqual(self.candidates(page, size),
                         [(1000, 120), (720, 120)])

    def test_vertical_boundaries_are_inclusive(self):
        page = icon_page(
            icon("[800,0][840,0]", clickable="true"),            # 中心正好在 y0
            icon("[800,120][840,200]", clickable="true"),        # 中心正好在 y1
        )
        self.assertEqual(self.candidates(page, (1000, 1000)), [(820, 0), (820, 160)])
        # 自定义取样区的上沿也要按高度算：中心 y=50 落在 0.1H 之下
        low = icon_page(icon("[800,20][840,80]", clickable="true"))
        self.assertEqual(self.candidates(low, (1000, 1000), area=(0.72, 0.1, 1.0, 0.16)), [])

    def test_exact_max_size_is_kept(self):
        page = icon_page(icon("[700,20][970,254]", clickable="true"))   # 宽 270、高 234
        self.assertEqual(self.candidates(page), [(835, 137)])

    def test_centers_are_integer_halves(self):
        page = icon_page(icon("[801,101][820,140]", clickable="true"))
        self.assertEqual(self.candidates(page, (1000, 1000)), [(810, 120)])

    def test_candidates_are_sorted_right_to_left(self):
        page = icon_page(
            icon("[800,40][900,140]", clickable="true"),
            icon("[950,240][1050,340]", clickable="true"),
        )
        self.assertEqual(self.candidates(page), [(1000, 290), (850, 90)])


class ClickTests(ScreenTestCase):
    """点击的越界守卫与尺寸守卫：边界坐标可用，越界一个像素就停。"""

    def test_the_screen_corners_are_inside(self):
        device = self.device()
        screen = self.screen(device)
        screen.click(0, 0)
        screen.click(1079, 2339)
        self.assertEqual([c for c in device.commands if "input swipe" in c],
                         ["input swipe 0 0 0 0 80", "input swipe 1079 2339 1079 2339 80"])

    def test_a_changed_screen_size_stops_before_acting(self):
        screen = self.screen(self.device())
        screen.W, screen.H = 1079, 2340
        with self.assertRaisesRegex(RuntimeError, "^屏幕方向或尺寸已变化，停止使用旧坐标；请重新读取页面$"):
            screen.click(10, 10)

    def test_out_of_screen_coordinates_are_rejected(self):
        device = self.device()
        screen = self.screen(device)
        for x, y in ((1080, 10), (10, 2340)):
            with self.subTest(x=x, y=y):
                with self.assertRaisesRegex(RuntimeError, "^点击坐标在屏幕外，未操作$"):
                    screen.click(x, y)
        self.assertEqual([c for c in device.commands if "input swipe" in c], [])


class RichText(str):
    """自带比较语义的字符串子类（对拍驱动那种读数。）；普通子类带 `__dict__`。"""


class OpaqueText(str):
    """没有 `__dict__` 的字符串子类：只能被收进 ShellResult。"""

    __slots__ = ()


class ShellResultTests(ScreenTestCase):
    """`shell()` 的返回形状：普通 str 收成 ShellResult，带语义的子类原样返回并挂退出码。"""

    def result(self, response):
        screen = self.screen(self.device(response=response))
        return screen.shell("echo hi")

    def test_a_plain_string_becomes_a_shell_result_with_the_exit_code(self):
        result = self.result(SimpleNamespace(output="probe", exit_code=3))
        self.assertIs(type(result), fast.ShellResult)
        self.assertEqual(result, "probe")
        self.assertEqual(result.exit_code, 3)

    def test_a_missing_exit_code_defaults_to_zero(self):
        result = self.result(SimpleNamespace(output="probe"))
        self.assertEqual(result.exit_code, 0)

    def test_a_semantic_string_subclass_is_returned_as_itself(self):
        rich = RichText("probe")
        result = self.result(SimpleNamespace(output=rich, exit_code=5))
        self.assertIs(result, rich)
        self.assertEqual(result.exit_code, 5)

    def test_a_subclass_without_a_dict_is_wrapped(self):
        opaque = OpaqueText("probe")
        result = self.result(SimpleNamespace(output=opaque, exit_code=6))
        self.assertIs(type(result), fast.ShellResult)
        self.assertEqual(result, "probe")
        self.assertEqual(result.exit_code, 6)


class SelectorVerbTests(ScreenTestCase):
    """选择器动词与打字的默认值：下标 0 不加 instance、等待 0 秒、只给文字就不塞 resourceId。"""

    def setUp(self):
        super().setUp()
        self.reader = SelectionReader()
        self.screen_ = self.screen(self.reader)

    def test_tap_id_clicks_the_first_match_by_default(self):
        self.screen_.tap_id(text="确定")
        self.assertEqual(self.reader.selectors, [{"text": "确定"}])
        self.assertEqual(self.reader.clicks, [{"text": "确定"}])
        self.assertEqual(self.reader.indexes, [])

    def test_tap_id_index_selects_the_nth_match(self):
        self.screen_.tap_id(resource_id="com.x:id/a", index=2)
        self.assertEqual(self.reader.indexes, [2])

    def test_tap_id_if_present_defaults_to_no_wait_and_keeps_the_text_selector(self):
        self.assertTrue(self.screen_.tap_id_if_present(text="确定"))
        self.assertEqual(self.reader.existence, [({"text": "确定"}, 0)])

    def test_type_text_sends_one_set_text_with_the_default_timeout(self):
        self.screen_.type_text("广告")
        selector, text, timeout = self.reader.typed[0]
        self.assertEqual(text, "广告")
        self.assertEqual(timeout, 4.0)
        self.assertEqual(selector, {"classNameMatches": r".*(EditText|AutoCompleteTextView)$",
                                    "focused": True})


class BackAndSettleTests(ScreenTestCase):
    """`back()` 的默认序列与 `settle()` 的默认预算：一条 keyevent、一次读屏前后各一次签名。"""

    def test_back_reads_waits_and_sends_one_keyevent(self):
        device = self.device(stages=((0.0, PAGE), (0.2, PAGE)))
        screen = self.screen(device)
        calls = []
        screen.sig = lambda: calls.append("sig") or "sig"
        screen.settle = lambda before, maxwait=0.8: calls.append(("settle", before, maxwait)) or True
        screen.back()
        self.assertEqual(calls, ["sig", ("settle", "sig", 0.6)])
        self.assertEqual(device.commands, ["input keyevent BACK"])

    def test_settle_defaults_wait_eight_hundred_milliseconds(self):
        screen = self.screen(self.device())
        self.assertFalse(screen.settle(""))
        self.assertEqual(self.clock.page_reads, 8)      # 0.8 / poll 0.1


def swipe_command(width, height=2340, frac=geometry.SCROLL_FRAC, up=False):
    x = width * 7 // 10 if width > 2000 else width // 2
    y1, y2 = int(height * geometry.SCROLL_BOTTOM), int(height * (geometry.SCROLL_BOTTOM - frac))
    if up:
        y1, y2 = y2, y1
    moves = [f"input motionevent MOVE {x} {int(y1 + (y2 - y1) * i / 6)}" for i in range(1, 7)]
    return ";".join([f"input motionevent DOWN {x} {y1}", *moves, "sleep 0.12",
                     f"input motionevent UP {x} {y2}"])


class ScrollTests(ScreenTestCase):
    """`scroll()` 下发的手势逐字节固定：两侧宽度各一条，上行一条，外加那 0.15 秒停顿。"""

    def test_the_gesture_uses_half_the_width_on_a_phone(self):
        device = self.device(size=(1080, 2340))
        screen = self.screen(device)
        screen.scroll()
        self.assertEqual(device.commands, [swipe_command(1080)])
        self.assertEqual(self.clock.t, 0.15)

    def test_the_tablet_branch_starts_above_twenty_hundred(self):
        for width in (2000, 2001):
            with self.subTest(width=width):
                device = self.device(size=(width, 2340))
                self.screen(device).scroll()
                self.assertEqual(device.commands, [swipe_command(width)])

    def test_the_gesture_uses_seven_tenths_on_a_tablet_width(self):
        device = self.device(size=(2400, 2340))
        screen = self.screen(device)
        screen.scroll()
        self.assertEqual(device.commands, [swipe_command(2400)])

    def test_an_upward_scroll_starts_at_the_lower_point(self):
        device = self.device(size=(1080, 2340))
        screen = self.screen(device)
        screen.scroll(up=True)
        self.assertEqual(device.commands, [swipe_command(1080, up=True)])


class ScrollMoreTests(ScreenTestCase):
    """翻一页：没有新文字返回 False；离开当前页抛一句固定的错。"""

    def test_no_new_text_means_false(self):
        screen = fixtures.screen_stub(SCROLLABLE)
        screen.focus = lambda: "com.a/.A"
        screen.scroll = lambda *a, **k: None
        self.assertFalse(screen.scroll_more())

    def test_leaving_the_page_is_reported(self):
        screen = fixtures.screen_stub(SCROLLABLE)
        focuses = iter(["com.a/.A", "com.b/.B"])
        screen.focus = lambda: next(focuses)
        screen.scroll = lambda *a, **k: None
        with self.assertRaisesRegex(RuntimeError,
                                    "^翻页离开了当前设置页，停止本段以免操作其他 App$"):
            screen.scroll_more()


class ScrollTopTests(ScreenTestCase):
    """回顶：每次上滑用最大比例、方向向上；中途离开当前页与翻页同款报错。"""

    def test_it_scrolls_by_the_max_fraction_upwards(self):
        screen = fixtures.screen_stub(SCROLLABLE)
        screen.focus = lambda: "com.a/.A"
        screen.texts = lambda root=None: [("甲", 0, 0)] if screen.scroll.called else [("甲", 0, 0), ("乙", 0, 0)]
        screen.scroll = Mock()
        screen.scroll_top(1)
        screen.scroll.assert_called_once_with(geometry.SCROLL_MAX_FRAC, up=True)

    def test_leaving_the_page_is_reported(self):
        screen = fixtures.screen_stub(SCROLLABLE)
        focuses = iter(["com.a/.A", "com.b/.B"])
        screen.focus = lambda: next(focuses)
        screen.scroll = Mock()
        with self.assertRaisesRegex(RuntimeError, "^回到页顶时离开了当前设置页，停止本段$"):
            screen.scroll_top(1)


class ApplyTests(ScreenTestCase):
    """意图的唯一执行点：缺坐标与未知种类各报一句固定的错。"""

    def test_a_tap_without_coordinates_is_rejected(self):
        screen = fixtures.screen_stub(PAGE)
        with self.assertRaisesRegex(ValueError, "^点击意图缺少坐标$"):
            screen.apply(SimpleNamespace(kind=screen_snapshot.IntentKind.TAP, at=None))

    def test_an_unknown_intent_kind_is_rejected(self):
        screen = fixtures.screen_stub(PAGE)
        with self.assertRaisesRegex(ValueError, "^未知意图种类：bogus$"):
            screen.apply(SimpleNamespace(kind="bogus"))


def find_page(*nodes):
    body = "".join(nodes)
    return f'<hierarchy><node bounds="[0,0][1080,2340]">{body}</node></hierarchy>'


class FindTests(ScreenTestCase):
    """`find()` 的匹配顺序、退化节点、可视阈值与页底折衷。"""

    def find(self, page, text, size=(1080, 2340), **kwargs):
        return fixtures.screen_stub(page, size).find(text, **kwargs)

    def test_substring_matching_is_the_default(self):
        page = find_page('<node text="个性化广告推荐" bounds="[60,600][700,660]"/>')
        self.assertEqual(self.find(page, "个性"), (380, 630))

    def test_exact_matching_is_opt_in(self):
        page = find_page('<node text="个性化广告推荐" bounds="[60,600][700,660]"/>')
        self.assertIsNone(self.find(page, "个性", exact=True))

    def test_a_given_root_is_used_instead_of_reading_the_screen(self):
        screen = fixtures.screen_stub(find_page('<node text="别的" bounds="[0,0][100,100]"/>'))
        given = ET.fromstring(find_page('<node text="目标" bounds="[60,600][700,660]"/>'))
        self.assertEqual(screen.find("目标", root=given), (380, 630))

    def test_navigation_skips_text_inside_a_switch_row(self):
        screen = fixtures.screen_stub(SWITCH_ROW)
        self.assertEqual(screen.find("隐私"), (480, 450))
        self.assertIsNone(screen.find("隐私", nav=True))

    def test_degenerate_nodes_are_skipped(self):
        page = find_page('<node text="目标" bounds="[100,200][300,200]"/>',
                         '<node text="目标" bounds="[400,300][400,400]"/>')
        self.assertIsNone(self.find(page, "目标"))

    def test_a_degenerate_node_does_not_stop_the_search(self):
        page = find_page('<node text="目标" bounds="[100,200][300,200]"/>',
                         '<node text="目标" bounds="[100,500][300,600]"/>')
        self.assertEqual(self.find(page, "目标"), (200, 550))

    def test_the_visible_bottom_edge_is_exclusive(self):
        page = find_page('<node text="目标" bounds="[0,900][100,940]"/>')
        self.assertIsNone(self.find(page, "目标", size=(1080, 1000)))

    def test_the_visible_bottom_threshold_is_not_divided(self):
        page = find_page('<node text="目标" bounds="[0,910][100,990]"/>')
        self.assertIsNone(self.find(page, "目标", size=(1080, 1000)))

    def test_the_returned_center_is_integer(self):
        page = find_page('<node text="目标" bounds="[61,601][100,700]"/>')
        self.assertEqual(self.find(page, "目标"), (80, 650))

    def test_edge_fallback_is_opt_in(self):
        page = find_page('<node text="目标" bounds="[101,950][900,960]"/>')
        self.assertIsNone(self.find(page, "目标", size=(1080, 1000)))
        self.assertEqual(self.find(page, "目标", size=(1080, 1000), edge_ok=True), (500, 965))
        self.assertEqual(self.find(page, "目标", size=(1080, 1000), edge_ok="tab"), (500, 955))

    def test_the_edge_threshold_is_exclusive(self):
        page = find_page('<node text="目标" bounds="[100,975][900,1000]"/>')
        self.assertIsNone(self.find(page, "目标", size=(1080, 1000), edge_ok=True))

    def test_the_edge_threshold_is_not_divided(self):
        page = find_page('<node text="目标" bounds="[100,990][900,1000]"/>')
        self.assertIsNone(self.find(page, "目标", size=(1080, 1000), edge_ok=True))


if __name__ == "__main__":
    unittest.main()
