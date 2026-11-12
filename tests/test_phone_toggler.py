"""拨动阶段的锚点：这一页该关的开关真的被关掉这条链路（ADR-0033、ADR-0024）。

钉的是拨动本身——`off()` 从页顶开始、两轮补点与回读、`confirm()` 的等待与按钮判定、灰态过滤、
安全模式下的跳过出口，以及残留确认框在后续导航失败里的说明。策略面的纯函数另有锚点：
`test_switch_plan.py`（该拨哪些）、`test_off_readback.py`（回读结局）、
`test_off_title_fallback.py`（点标题回退）、`test_main_switch_bar.py`（真开关藏在容器里）。

门面把调用转给了谁由 `test_phone_facade.py` 钉，脚本前导的跳过出口由 `test_recipe_kit.py` 钉。
迁入的用例把原票号留在类或方法的 docstring 里，仍可 grep 回原票。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import adb_link  # noqa: E402
import chan_fast  # noqa: E402
import fast  # noqa: E402
import row  # noqa: E402
from fixtures import (SIZES, Clock, clocked, drive, fake_phone,  # noqa: E402
                      install_clock, phone_stub)

SIZE = (1260, 2800)
CONFIRM_ONLY = ('<node class="android.widget.Button" content-desc="确认关闭" clickable="true" '
                'bounds="[308,2524][951,2665]"/>')
NOTE = "屏上还挂着没点掉的确认框「确认关闭」"


def page(body="", dialog=False):
    return ('<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]">'
            + body + (CONFIRM_ONLY if dialog else "") + "</node></hierarchy>")


class _NoToggler:
    """碰一下就炸的拨动会话：导航侧的失败说明不该走到它。"""

    def __getattr__(self, name):
        raise AssertionError(f"导航侧访问了拨动会话的 {name}")


class FacadeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_the_toggling_state_lives_on_the_session(self):
        """`p.safe_mode` 与 `p.changed` 转发到拨动会话本体：脚本照旧可写，集合仍是活对象。"""
        self.assertIs(self.p.changed, self.p.toggler.changed)
        self.assertIs(self.p.safe_mode, self.p.toggler.safe_mode)
        self.p.safe_mode = True
        self.assertIs(self.p.toggler.safe_mode, True)
        self.p.changed.append(("页", "开关"))
        self.assertEqual(self.p.toggler.changed, [("页", "开关")])

    def test_off_and_confirm_go_through_the_session(self):
        """门面没有实现残留：把会话换成替身，返回值必须由替身给出。"""
        self.p.toggler = Mock()
        self.p.toggler.off.return_value = 7
        self.p.toggler.confirm.return_value = "确定"
        self.assertEqual(self.p.off(page="页", only=["广告"]), 7)
        self.assertEqual(self.p.confirm(), "确定")
        self.p.toggler.off.assert_called_once_with((), ["广告"], "页", 40)

    def test_no_reflective_forwarding_on_the_toggler_side_either(self):
        """`__getattr__` 会把搬漏静默吃掉：门面与会话都不许有。"""
        self.assertNotIn("__getattr__", vars(type(self.p.toggler)))


class ResidualNoteTests(unittest.TestCase):
    def test_the_sentence_is_a_pure_function(self):
        self.assertEqual(row.residual_note("确认关闭", "；"), "；屏上还挂着没点掉的确认框「确认关闭」")
        self.assertEqual(row.residual_note(""), "")
        self.assertEqual(row.residual_note(None), "")

    def test_the_facade_reads_it_from_the_screen(self):
        """门面那句仍是读屏后拼出来的：有确认框时点名按钮，没有时是空串（#557）。"""
        p = fake_phone(clock=install_clock(fast, Clock()), size=SIZE,
                       stages=[(0.0, page(dialog=True))])
        self.assertEqual(p.residual_note(), "——屏上还挂着没点掉的确认框「确认关闭」")
        self.assertEqual(p.residual_note("；"), "；屏上还挂着没点掉的确认框「确认关闭」")


class NavigationDoesNotDependOnTogglingTests(unittest.TestCase):
    def test_tap_failure_names_the_dialog_without_the_toggler(self):
        """导航与拨动之间的那条环边：`tap()` 的失败说明只问观测基座，不问拨动会话。"""
        lines = []
        clock = install_clock(fast, Clock())
        p = fake_phone(clock=clock, size=SIZE, stages=[(0.0, page(dialog=True))],
                       say=lambda *a: lines.append(" ".join(str(x) for x in a)))
        p.toggler = _NoToggler()
        self.assertFalse(p.tap("服务管理", scrolls=0))
        self.assertEqual(lines[-1], "  ✗ 没找到「服务管理」——屏上还挂着没点掉的确认框「确认关闭」")


def bare_phone(size=(1080, 2400)):
    """只给读屏替身的门面：确认框判定不碰手机，也不装假时钟（`time.sleep` 由用例 patch）。"""
    p = phone_stub("test", d=Mock())
    p.W, p.H = size
    return p


class ConfirmButtonTests(unittest.TestCase):
    """Issue #246：确认框按钮的文字位置——vivo 阅图锁屏把它放在 content-desc 上。

    设备无关：用 dump 到的真实层级树片段构造 XML，不连接手机。
    """

    @patch.object(fast.time, "sleep")
    def test_button_label_from_content_desc(self, _sleep):
        """vivo V2452A / 阅图锁屏：Button 的 text 为空，文字在 content-desc。

        页面同时有一个 text="关闭" 的 TextView（说明行里的一部分），
        点和读都必须落在 Button 上。
        """
        p = bare_phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="false" bounds="[502,2175][578,2222]"/>
          <node class="android.widget.Button" content-desc="保持开启" clickable="true" bounds="[270,1944][810,2082]"/>
          <node class="android.widget.Button" content-desc="关闭" clickable="true" bounds="[270,2130][810,2268]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "关闭")
        p.screen.click.assert_called_once_with(540, 2199)

    @patch.object(fast.time, "sleep")
    def test_state_text_without_button_class_is_ignored(self, _sleep):
        """ColorOS 开关旁边的「关闭」是状态文字，不是按钮：点了会把开关拨回去。"""
        p = bare_phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="false" bounds="[900,400][1000,450]"/>
          <node class="android.view.View" text="关闭" clickable="true" bounds="[900,500][1000,550]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertIsNone(p.confirm())
        p.screen.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_sentence_in_content_desc_is_not_a_confirm_label(self, _sleep):
        """content-desc 是整段说明时不算确认词，不能点。"""
        p = bare_phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.Button" content-desc="关闭后将无法自动切换锁屏壁纸及滑动浏览图集，建议保持开启。"
                clickable="true" bounds="[60,2200][1020,2320]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertIsNone(p.confirm())
        p.screen.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_traditional_confirm_button(self, _sleep):
        """繁体界面上的确认键是「確定」（#604）：词表只收简体时这一下点不到。"""
        p = bare_phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.Button" text="取消" clickable="true" bounds="[120,2200][480,2320]"/>
          <node class="android.widget.Button" text="確定" clickable="true" bounds="[600,2200][960,2320]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "確定")
        p.screen.click.assert_called_once_with(780, 2260)

    @patch.object(fast.time, "sleep")
    def test_clickable_text_view_is_a_confirm_button(self, _sleep):
        """HyperOS 4（小米 17）热榜页：确认键是可点击的 TextView，不是 Button（#500 / PR #408）。

        弹窗里同时有说明文字与「取消」，点必须落在「关闭」上。
        """
        p = bare_phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭热榜后将不再显示榜单内容" clickable="false" bounds="[60,1900][1020,2100]"/>
          <node class="android.widget.TextView" text="取消" clickable="true" bounds="[120,2200][480,2320]"/>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[600,2200][960,2320]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "关闭")
        p.screen.click.assert_called_once_with(780, 2260)

    @patch.object(fast.time, "sleep")
    def test_button_class_wins_over_clickable_text_view(self, _sleep):
        """严格档优先：同一页既有 Button 又有可点击 TextView 时点 Button。"""
        p = bare_phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="确定" clickable="true" bounds="[600,2200][960,2320]"/>
          <node class="android.widget.Button" text="确定" clickable="true" bounds="[120,2200][480,2320]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "确定")
        p.screen.click.assert_called_once_with(300, 2260)

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_skips_wide_or_tall_nodes(self, _sleep):
        """兜底档只认按钮级尺寸：整行宽度和整段高度各守一个阈值。"""
        for bounds in ("[60,2000][1020,2320]", "[300,1600][600,2100]"):
            with self.subTest(bounds=bounds):
                p = bare_phone()
                root = ET.fromstring(
                    f'<hierarchy><node class="android.widget.TextView" text="关闭" '
                    f'clickable="true" bounds="{bounds}"/></hierarchy>')
                p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
                self.assertIsNone(p.confirm())
                p.screen.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_skips_bounds_at_the_threshold(self, _sleep):
        """阈值是严格小于：宽 540（0.5W）、高 288（0.12H）恰好卡线时都不点。"""
        for bounds in ("[270,2000][810,2100]", "[300,2000][600,2288]"):
            with self.subTest(bounds=bounds):
                p = bare_phone()
                root = ET.fromstring(
                    f'<hierarchy><node class="android.widget.TextView" text="关闭" '
                    f'clickable="true" bounds="{bounds}"/></hierarchy>')
                p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
                self.assertIsNone(p.confirm())
                p.screen.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_skips_offscreen_nodes(self, _sleep):
        """屏外残留的 TextView 不点。"""
        p = bare_phone()
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[600,2500][960,2700]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertIsNone(p.confirm())
        p.screen.click.assert_not_called()

    @patch.object(fast.time, "sleep")
    def test_text_view_fallback_scales_with_the_screen(self, _sleep):
        """阈值按当前屏尺寸算：窄屏上整行文字仍被排除，按钮级文字仍能命中。"""
        p = bare_phone((720, 1600))
        root = ET.fromstring('''<hierarchy>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[40,1320][680,1420]"/>
          <node class="android.widget.TextView" text="关闭" clickable="true" bounds="[380,1200][700,1300]"/>
        </hierarchy>''')
        p.screen.tree, p.screen.click = Mock(return_value=root), Mock()
        self.assertEqual(p.confirm(), "关闭")
        p.screen.click.assert_called_once_with(540, 1250)


PAGE = page()
DIALOG = ('<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]">'
          '<node class="android.widget.Button" content-desc="取消" clickable="true" bounds="[308,2333][951,2474]"/>'
          '<node class="android.widget.Button" content-desc="确认关闭" clickable="true" bounds="[308,2524][951,2665]"/>'
          '</node></hierarchy>')


class LateDialogTests(unittest.TestCase):
    """#555: vivo 商店「个性化推荐」页的确认框进树要 0.6 秒左右，而 `confirm()` 只在 0.2 秒时
    拍一次快照，从点击那一刻起就必然错过。等待必须是有界的轮询：晚到的弹窗照样认得出，
    没有弹窗的页面也不能无限等。
    """

    def setUp(self):
        self.addCleanup(setattr, fast, "time", fast.time)      # 假时钟装进模块后要还原，别影响后面的用例

    def test_dialog_that_arrives_late_is_still_confirmed(self):
        """0.6 秒才进树的弹窗仍要被认出来，且只点一次「确认关闭」。"""
        out, _, _, clicks = drive(lambda p: p.confirm(), modules=(fast,),
                                  size=(1260, 2800), stages=[(0.0, PAGE), (0.6, DIALOG)], read_cost=0.1)
        self.assertEqual(out, "确认关闭")
        self.assertEqual(clicks, 1)

    def test_page_without_dialog_does_not_wait_forever(self):
        """整屏没有确认框：返回 None、一次也不点，花费有上界。"""
        out, elapsed, _, clicks = drive(lambda p: p.confirm(), modules=(fast,), size=(1260, 2800), read_cost=0.1)
        self.assertIsNone(out)
        self.assertEqual(clicks, 0)
        self.assertLessEqual(elapsed, 1.5)


TITLES = ("个性化推荐", "个性化广告推荐", "推荐内容", "热点推荐", "应用推荐",
          "内容推荐", "搜索推荐", "榜单推荐", "视频推荐", "商品推荐")
TOPS = tuple(250 + 250 * i for i in range(len(TITLES)))
SWITCH_X = 1054
CONFIRM_XY = (629, 2594)


def store_page(states, dialog):
    rows = "".join(
        f'<node bounds="[40,{top}][1100,{top + 142}]">'
        f'<node text="{title}" bounds="[40,{top}][700,{top + 142}]"/>'
        f'<node class="android.widget.Switch" checkable="true"'
        f' checked="{"true" if on else "false"}" bounds="[984,{top}][1125,{top + 142}]"/></node>'
        for title, top, on in zip(TITLES, TOPS, states, strict=True))    # TOPS 按 len(TITLES) 生成，states 同长
    overlay = ('<node class="android.widget.Button" content-desc="取消" clickable="true" bounds="[308,2333][951,2474]"/>'
               '<node class="android.widget.Button" content-desc="确认关闭" clickable="true" bounds="[308,2524][951,2665]"/>'
               ) if dialog else ""
    return (f'<hierarchy rotation="0"><node package="com.vivo.appstore" bounds="[0,0][1260,2800]">'
            f'{rows}{overlay}</node></hierarchy>')


class StoreDevice:
    """vivo 商店的这一页：第一次往「关」拨之后 delay 秒弹确认框，弹窗挂着时页面上的点击被遮罩吞掉，
    只有点「确认关闭」能让它消失。"""

    def __init__(self, clock, delay):
        self.clock, self.delay = clock, delay
        self.states = [True] * len(TITLES)
        self.dialog_at, self.dialog, self.swallowed = None, False, 0
        self.lost_streak = self.max_lost_streak = 0        # 连续被吞的次数：一次竞态可以，一路吞不行

    def dump_hierarchy(self):
        self.clock.read()
        if self.dialog_at is not None and not self.dialog and self.clock.t >= self.dialog_at:
            self.dialog = True
        return store_page(self.states, self.dialog)

    def window_size(self):
        return (1260, 2800)

    def shell(self, command, timeout=60):
        return SimpleNamespace(output="", exit_code=0)

    def screenshot(self):
        return None

    def click(self, x, y):
        self.clock.click()
        if self.dialog:
            if (x, y) == CONFIRM_XY:
                self.dialog, self.dialog_at = False, None      # 关掉之后下一次拨动才会再弹
            else:
                self.swallowed += 1
                self.lost_streak += 1
                self.max_lost_streak = max(self.max_lost_streak, self.lost_streak)
            return
        self.lost_streak = 0
        for i, top in enumerate(TOPS):
            if (x, y) == (SWITCH_X, top + 71) and self.states[i]:
                self.states[i] = False
                if self.dialog_at is None:
                    self.dialog_at = self.clock.t + self.delay
                return


class MaskClickTests(unittest.TestCase):
    """#555 的另一半：弹窗挂着时页面上的点击会被遮罩吞掉，连点前必须先看清屏上有没有确认框。"""

    def setUp(self):
        self.addCleanup(setattr, fast, "time", fast.time)

    def run_off(self, delay):
        clock = Clock(read_cost=0.1)
        install_clock(fast, clock)
        device = StoreDevice(clock, delay)
        phone = fake_phone(clock=clock, size=(1260, 2800), click=device.click, d=device)
        return phone.off(), device

    def test_late_dialog_never_swallows_the_remaining_clicks(self):
        """报告者的场景：首击 0.6 秒后才弹的确认框。剩下的目标不能在弹窗挂着时去点。"""
        done, device = self.run_off(delay=0.6)
        self.assertEqual(device.swallowed, 0, "有目标被点在弹窗遮罩上了")
        self.assertEqual(done, len(TITLES))

    def test_dialog_slower_than_the_wait_budget_does_not_eat_later_clicks(self):
        """弹窗晚于 confirm() 的等待预算（慢机型）：连点前也要先看清屏上有没有确认框。

        读屏与点击之间仍有空隙，单次竞态漏掉一下是允许的；但不能一路吞下去。"""
        done, device = self.run_off(delay=1.2)
        self.assertLessEqual(device.max_lost_streak, 1, "连点被弹窗连续吞掉")
        self.assertEqual(done, len(TITLES))


def switch_row(title, checked, top):
    return (f'<node bounds="[40,{top}][1100,{top + 142}]">'
            f'<node text="{title}" bounds="[40,{top}][700,{top + 142}]"/>'
            f'<node class="android.widget.Switch" checkable="true" checked="{checked}"'
            f' bounds="[984,{top}][1125,{top + 142}]"/></node>')


NOTIFY_BODY = switch_row("允许通知", "true", 200) + switch_row("横幅", "false", 352)
ENTERED_BODY = '<node text="服务管理" bounds="[40,200][700,342]"/>'


class ResidualConfirmTests(unittest.TestCase):
    """#557: 一段跑完后确认框还挂在屏上时，后面的查找失败要说清是这个原因，
    而不是只报「没找到」——读者会把它当成这一版没适配。

    弹窗里只放确认键：没有 `DISMISS` 里的「取消」，`dismiss()` 也关不掉它，
    这样「残留」才是这份夹具真的在演的场景。
    """

    def setUp(self):
        self.addCleanup(setattr, fast, "time", fast.time)
        self.clock = install_clock(fast, Clock())

    def phone(self, xml):
        self.lines = []
        return fake_phone(clock=self.clock, size=SIZE, stages=[(0.0, xml)],
                          say=lambda *a: self.lines.append(" ".join(str(x) for x in a)))

    def test_tap_failure_names_the_dialog(self):
        """tap() 的两句「没找到」：整页翻找与走丢后的快速放弃。"""
        for kwargs, miss, expected in (
            ({"scrolls": 0}, 0, "  ✗ 没找到「服务管理」——" + NOTE),
            ({"scrolls": 2}, 0, "  ✗ 没找到「服务管理」——" + NOTE),
            ({"scrolls": 6}, 1, "  ✗ 没找到「服务管理」（快速放弃）——" + NOTE),
        ):
            with self.subTest(**kwargs, miss=miss):
                p = self.phone(page(dialog=True))
                p.miss = miss
                self.assertFalse(p.tap("服务管理", **kwargs))
                self.assertEqual(self.lines[-1], expected)

    def test_enter_failure_names_the_dialog(self):
        """enter() 的两条 raise：入口没找到、点了页面没换。"""
        with self.subTest("没找到入口"):
            p = self.phone(page(dialog=True))
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertTrue(str(caught.exception).startswith(f"未找到入口「服务管理」；{NOTE}；当前页："))
            self.assertIn("  ✗ 没找到「服务管理」——" + NOTE, self.lines)
        with self.subTest("页面没有变化"):
            p = self.phone(page(ENTERED_BODY, dialog=True))
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertTrue(str(caught.exception).startswith(f"点「服务管理」后页面没有变化；{NOTE}；当前页："))

    def test_go_failure_names_the_dialog(self):
        p = self.phone(page(ENTERED_BODY, dialog=True))
        self.assertFalse(p.go("服务管理", "关于"))
        self.assertEqual(self.lines[-1], "  ✗ 点「服务管理」后没出现「关于」——" + NOTE)

    def test_channel_hint_names_the_dialog(self):
        """渠道页没认出时的结构摘要也要点名确认框：那一行「开关 2 个」正是被遮罩挡住的读法。"""
        p = self.phone(page(NOTIFY_BODY, dialog=True))
        self.assertEqual(chan_fast.page_hint(p, "小视频"),
                         "标题无，允许通知开关 1 个，开关 2 个；" + NOTE)

    def test_lost_link_still_raises(self):
        """断线不是「没有确认框」：诊断只吞读页失败，不吞断线（#293 的形态）。"""
        p = self.phone(page(dialog=True))
        p.screen.tree = Mock(side_effect=adb_link.DeviceLost("设备已断开"))
        with self.assertRaises(adb_link.DeviceLost):
            p.residual_confirm()

    def test_without_dialog_output_is_unchanged(self):
        """六处的输出与改动前逐字一致：这条守的是不回退，改动前的树上也是绿的。"""
        for kwargs, miss, expected in (
            ({"scrolls": 0}, 0, "  ✗ 没找到「服务管理」"),
            ({"scrolls": 2}, 0, "  ✗ 没找到「服务管理」"),
            ({"scrolls": 6}, 1, "  ✗ 没找到「服务管理」（快速放弃）"),
        ):
            with self.subTest(**kwargs, miss=miss):
                p = self.phone(page())
                p.miss = miss
                self.assertFalse(p.tap("服务管理", **kwargs))
                self.assertEqual(self.lines[-1], expected)

        with self.subTest("没找到入口"):
            p = self.phone(page())
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertEqual(str(caught.exception), "未找到入口「服务管理」；当前页：")
            self.assertNotIn("确认框", "".join(self.lines))

        with self.subTest("页面没有变化"):
            p = self.phone(page(ENTERED_BODY))
            with self.assertRaises(RuntimeError) as caught:
                p.enter("服务管理")
            self.assertEqual(str(caught.exception), "点「服务管理」后页面没有变化；当前页：服务管理")
            self.assertNotIn("确认框", "".join(self.lines))

        with self.subTest("go"):
            p = self.phone(page(ENTERED_BODY))
            self.assertFalse(p.go("服务管理", "关于"))
            self.assertEqual(self.lines[-1], "  ✗ 点「服务管理」后没出现「关于」")

        with self.subTest("渠道页"):
            p = self.phone(page(NOTIFY_BODY))
            self.assertEqual(chan_fast.page_hint(p, "小视频"), "标题无，允许通知开关 1 个，开关 2 个")


FOCUS = "com.example.app/.AdActivity"
OTHER = "com.example.app/.OtherActivity"


class LongList:
    """一页能滚的假长列表：读屏读到的是窗口里那几行，滚动只挪窗口。

    与真机同形的地方是「一次只看得见几行」：在页底读屏看不到上面的行，
    不先复位就永远点不到它们。滚动一次挪一屏（真机是 0.58H，有重叠）。
    `ticker=True` 给页面顶部挂一条每读一次就变的内容（倒计时、轮播推广位那种）：
    「没有新文字」在那样的页面上永远不成立。
    """

    def __init__(self, count=40, visible=6, size=SIZES[0], scrollable=True, ticker=False):
        self.size, self.visible, self.scrollable = size, visible, scrollable
        self.rows = [[f"广告开关 {i}", True] for i in range(count)]
        self.top_row = 0
        self.scrolls = 0
        self.ticker, self.reads = ticker, 0

    @property
    def last_top(self):
        return max(0, len(self.rows) - self.visible)

    @property
    def row_h(self):
        return (self.size[1] - 400) // self.visible

    def window(self):
        return self.rows[self.top_row:self.top_row + self.visible]

    def tree(self):
        w, h = self.size
        self.reads += 1
        out = ['<hierarchy rotation="0">',
               f'<node package="com.example.app" class="android.widget.FrameLayout" bounds="[0,0][{w},{h}]">']
        if self.ticker:
            out.append(f'<node class="android.widget.TextView" text="还剩 {self.reads} 秒"'
                       ' bounds="[40,120][700,190]"/>')
        if self.scrollable:
            out.append(f'<node class="android.widget.ListView" scrollable="true" bounds="[0,200][{w},{h}]">')
        for i, (title, on) in enumerate(self.window()):
            y = 250 + i * self.row_h
            out.append(f'<node class="android.widget.LinearLayout" bounds="[0,{y}][{w},{y + self.row_h}]">'
                       f'<node class="android.widget.TextView" text="{title}" bounds="[40,{y + 30}][700,{y + 110}]"/>'
                       f'<node class="android.widget.Switch" checkable="true" clickable="true"'
                       f' checked="{"true" if on else "false"}" bounds="[900,{y + 30}][1050,{y + 110}]"/>'
                       '</node>')
        if self.scrollable:
            out.append("</node>")
        out.append("</node></hierarchy>")
        return ET.fromstring("".join(out))

    def scroll(self, up=False):
        self.scrolls += 1
        self.top_row = (max(0, self.top_row - self.visible) if up
                        else min(self.last_top, self.top_row + self.visible))

    def click(self, x, y):
        for i, item in enumerate(self.window()):
            top = 250 + i * self.row_h
            if top <= y < top + self.row_h and 40 <= x <= 1050:
                item[1] = False
                return
        raise AssertionError(f"点到了没有开关的位置 {(x, y)}")


def focus_axis(answers):
    """前台窗口的一条轴：按顺序给答案，用完之后重复最后一个。"""
    seq = list(answers)

    def read():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return read


def long_phone(model, focus=(FOCUS,), lines=None):
    """把假长列表接上一台不连手机的门面：读屏、滚动、点击都落在模型上，其余走真实现。"""
    lines = lines if lines is not None else []
    p = phone_stub("S")
    p.screen.W, p.screen.H = model.size
    p.screen.tree = model.tree
    p.screen.focus = focus_axis(focus)
    p.screen.scroll = lambda frac=0.45, up=False: model.scroll(up)
    p.screen.click = model.click
    p.screen.confirm_target = lambda root=None: None
    p.screen.back = lambda n=1: None
    p.conn.say = lines.append
    p.lines = lines
    return p


class TopReachesTheRealTopTests(unittest.TestCase):
    """#1094：`top()` 的终止条件是「这一屏没有新文字」，与 `scroll_more()` 对称，不写死次数。"""

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_top_scrolls_a_long_list_all_the_way_up(self):
        """页底进入：固定 4 次只到半路（34 → 10），按「没有新文字」才回得到 0。"""
        model = LongList(count=40, visible=6)
        model.top_row = model.last_top
        p = long_phone(model)
        p.top()
        self.assertEqual(model.top_row, 0)

    def test_top_stops_when_one_more_scroll_shows_nothing_new(self):
        """到底就该停：回顶后不再空滑，也不来回打转。"""
        model = LongList(count=40, visible=6)
        model.top_row = model.last_top
        p = long_phone(model)
        p.top()
        self.assertEqual(model.scrolls, 7)          # 6 次回到 0，第 7 次没新文字后收手

    def test_top_does_not_scroll_a_page_without_a_scrollable_container(self):
        """单屏面板上滑可能直接关掉页面：不滚动就零动作。（旧树也绿，守的是不回退）"""
        model = LongList(count=6, visible=6, scrollable=False)
        p = long_phone(model)
        p.top()
        self.assertEqual(model.scrolls, 0)

    def test_an_explicit_cap_still_limits_the_scrolls(self):
        """`n` 仍是「翻着找入口」那种有余量的兜底：给了就按它收手。（旧树也绿，守的是不回退）"""
        model = LongList(count=40, visible=6)
        model.top_row = model.last_top
        p = long_phone(model)
        p.top(2)
        self.assertEqual((model.scrolls, model.top_row), (2, 22))

    def test_a_page_whose_text_keeps_changing_still_stops(self):
        """顶部有会自己变的内容时「没有新文字」永不成立：得有一道兜底，不能一路滑下去。
        旧实现固定 4 次，换判据后若没有上限，这条会挂到跑不完。"""
        model = LongList(count=40, visible=6, ticker=True)
        model.top_row = model.last_top
        p = long_phone(model)
        p.top()
        self.assertLess(model.scrolls, 100)
        self.assertEqual(model.top_row, 0)          # 兜底之前已经翻到页顶


class OffStartsFromThePageTopTests(unittest.TestCase):
    """#1094：`off()` 的语义是「这一页该关的都关掉」，页顶是它自己的前提。

    `fast.py scan` 循环翻到列表底部、结束时不复位；紧接着 `off()` 从当前屏开始、只向下翻，
    219 个开关的页面只关掉底部那一段，没被看见的行既不在 targets 里也不进 missed，
    于是打一行「关了 N 个」、退出码 0。
    """

    def setUp(self):
        self.clock = clocked(self, fast, Clock())

    def test_off_from_the_bottom_closes_the_whole_page(self):
        """scan 之后那种进入方式：页底进去，关的必须是整页，不只是最后那一段。"""
        model = LongList(count=40, visible=6)
        model.top_row = model.last_top
        p = long_phone(model)
        self.assertEqual(p.off(page="广告"), 40)
        self.assertEqual([on for _, on in model.rows], [False] * 40)
        self.assertEqual(len(p.changed), 40)

    def test_leaving_the_page_while_resetting_raises(self):
        """复位中途换了页面：按既有 RuntimeError 口径抛，不静默接着拨。"""
        model = LongList(count=40, visible=6)
        model.top_row = model.last_top
        p = long_phone(model, focus=[FOCUS, OTHER])
        with self.assertRaisesRegex(RuntimeError, "回到页顶时离开了当前设置页"):
            p.off(page="广告")
        self.assertEqual([on for _, on in model.rows], [True] * 40)      # 一行都没点

    def test_a_single_screen_page_is_not_scrolled(self):
        """本来就是整页可见、也不滚动：复位不该凭空多出上滑手势。（旧树也绿，守的是不回退）"""
        model = LongList(count=6, visible=6, scrollable=False)
        p = long_phone(model)
        self.assertEqual(p.off(page="广告"), 6)
        self.assertEqual(model.scrolls, 0)


if __name__ == "__main__":
    unittest.main()
