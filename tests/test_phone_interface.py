"""Phone 的接口面：读屏策略、探路的包名过滤、安全模式、读屏 adapter 的归属。

守的是「这些状态从哪来」：一次渠道尝试的诊断归 chan_fast（Attempt），
读屏策略归观测基座（`p.screen.*`），读屏 adapter 归连接基座（`p.conn.reader`）——
门面上没有第二条访问路径（ADR-0045、#1479）。装配统一走 fixtures。
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import explore
import fast
from phone import connection as phone_connection
from fixtures import Clock, Device, Timeline, fake_phone, install_clock, load_recipe, patched_clock
from fixtures import phone_stub
from reader import Reader


# 同一屏里两个 App 的文字：Settings 自己的一行，和浮在它上面的另一个窗口
TWO_WINDOWS = '''<hierarchy rotation="0">
  <node class="android.widget.TextView" package="com.android.settings" text="隐私" bounds="[60,300][400,360]"/>
  <node class="android.widget.TextView" package="com.example.overlay" text="别的窗口" bounds="[60,420][400,480]"/>
  <node class="android.widget.TextView" package="com.android.settings" text="广告" bounds="[60,540][400,600]"/>
</hierarchy>'''


# vivo OriginOS Ocean（安卓 10）的通知设置页挂在 com.android.systemui 上
SYSTEMUI_PAGE = '''<hierarchy rotation="0">
  <node package="com.android.systemui" text="状态栏" bounds="[60,60][400,120]"/>
  <node package="com.android.systemui" text="允许通知" bounds="[60,300][400,360]"/>
  <node package="com.android.systemui" class="android.widget.Switch" checkable="true" checked="true" bounds="[950,300][1060,380]"/>
</hierarchy>'''


class TextsTests(unittest.TestCase):
    def test_systemui_text_is_dropped_unless_the_page_is_systemui(self):
        p = fake_phone(stages=[(0.0, SYSTEMUI_PAGE)])
        self.assertEqual(p.texts(), [])                              # 状态栏文字默认不算
        p.screen.systemui_text = True
        self.assertEqual([t for t, _, _ in p.texts()], ["状态栏", "允许通知"])


class EntriesTests(unittest.TestCase):
    def test_entries_drop_text_from_another_window(self):
        p = fake_phone(stages=[(0.0, TWO_WINDOWS)])
        self.assertIn("别的窗口", [t for t, _, _ in p.texts()])      # 守卫：这段文字真的读到了
        self.assertEqual(explore.entries(p, "com.android.settings"), ["隐私", "广告"])


def reader(page="<hierarchy/>", size=(1080, 2340)):
    """夹具里的假设备就是一个 Reader；这里只补上时间轴与假时钟。"""
    return Device(Timeline([(0.0, page)]), size, Clock())


class ReaderTests(unittest.TestCase):
    def test_fixtures_device_is_a_reader(self):
        self.assertIsInstance(reader(), Reader)

    def test_a_stub_reader_lives_on_the_connection(self):
        dev = reader()
        p = phone_stub("S")
        p.conn.reader = dev
        self.assertIs(p.conn.reader, dev)
        for gone in ("d", "reader"):                                  # 门面上不再有第二条访问路径
            with self.assertRaises(AttributeError):
                getattr(p, gone)

    def test_phone_can_be_built_from_a_named_reader(self):
        r = reader()
        with patch.object(phone_connection, "connect",
                          side_effect=AssertionError("给了 reader 就不该连真机")):
            p = fast.Phone("S", log=False, reader=r)
        self.assertIs(p.conn.reader, r)
        self.assertEqual((p.W, p.H), (1080, 2340))
        self.assertEqual(p.texts(), [])                               # 没连手机也能读屏（空树）
        p.close()
        self.assertTrue(r.closed)


# 两个都不该在安全模式下被碰的普通广告开关
LIST_PAGE = '''<hierarchy rotation="0">
  <node package="com.android.settings" clickable="true" bounds="[0,300][1080,380]">
    <node text="个性化推荐" bounds="[60,310][400,370]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[950,300][1060,380]"/>
  </node>
  <node package="com.android.settings" clickable="true" bounds="[0,500][1080,580]">
    <node text="猜你喜欢" bounds="[60,510][400,570]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[950,500][1060,580]"/>
  </node>
</hierarchy>'''

# 同一页，两个开关都已经关着：off() 只有 checked、没有 target，台账为空
CLOSED_PAGE = LIST_PAGE.replace('checked="true"', 'checked="false"')


CARD_PAGE = '''<hierarchy rotation="0">
  <node package="com.android.settings" clickable="true" bounds="[0,600][1080,860]">
    <node text="营销通知" bounds="[60,620][600,700]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,620][1000,700]"/>
    <node class="android.widget.Switch" checkable="true" checked="false" bounds="[900,750][1000,830]"/>
  </node>
  <node package="com.android.settings" bounds="[0,1000][1080,1260]">
    <node text="订单通知" bounds="[60,1020][600,1100]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,1020][1000,1100]"/>
  </node>
</hierarchy>'''


class AttemptTests(unittest.TestCase):
    """一次渠道尝试的诊断归 chan_fast；Phone 上不再有 why / stage / vivo_app。"""

    def test_the_reason_lands_in_the_attempt_not_on_the_phone(self):
        import chan_fast as chan
        p = fake_phone(stages=[(0.0, CARD_PAGE)],
                       focus=[(0.0, "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity")])
        at = chan.Attempt()
        self.assertIsNone(chan.inline_switch(p, "营销通知", at))     # 行内两个开关：认不出
        self.assertIn("行内开关 2 个", at.why)                        # 守卫：真的走到了「没认出」这一支
        for gone in ("why", "stage", "vivo_app"):
            self.assertFalse(hasattr(p, gone), gone)                  # 这些状态不再挂在 Phone 上


class SafeModeTests(unittest.TestCase):
    """安全模式（参考脚本 / 录制版本不符）只关点名的开关，不做整页全关。"""

    def phone(self):
        self.lines = []
        self.clock = Clock()
        install_clock(fast, self.clock)
        return fake_phone(clock=self.clock, stages=[(0.0, LIST_PAGE)], say=self.lines.append)

    def test_safe_mode_leaves_a_page_of_unnamed_switches_alone(self):
        p = self.phone()
        p.safe_mode = True
        self.assertEqual(p.off(page="系统·广告服务"), 0)
        self.assertEqual(self.clock.clicks, 0)                        # 守卫：真的一下都没点
        self.assertTrue(any("安全模式不做整页全关" in line for line in self.lines))
        self.assertEqual(p.changed, [])

    def test_without_safe_mode_the_same_page_is_clicked(self):
        p = self.phone()
        p.safe_mode = False
        p.off(page="系统·广告服务")
        self.assertGreater(self.clock.clicks, 0)                      # 同一页在非安全模式下会点
        self.assertFalse(any("安全模式不做整页全关" in line for line in self.lines))


# 一加 7T 浏览器（#333）：上级广告开关关掉后「摇一摇广告」这一行是灰的（enabled="false"）
GREY_LIST_PAGE = '''<hierarchy rotation="0">
  <node package="com.android.settings" clickable="true" bounds="[0,500][1080,580]">
    <node text="摇一摇广告" bounds="[60,510][400,570]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" enabled="false" bounds="[950,500][1060,580]"/>
  </node>
</hierarchy>'''


# 卡片整体 checkable，灰态只落在内层 Switch 上（#403 的双列布局）
GREY_CARD_PAGE = '''<hierarchy rotation="0">
  <node class="android.widget.LinearLayout" checkable="true" clickable="true" bounds="[0,500][1080,760]">
    <node text="摇一摇广告" bounds="[60,520][600,600]"/>
    <node class="android.widget.Switch" checked="true" enabled="false" bounds="[900,520][1000,600]"/>
  </node>
</hierarchy>'''


class DisabledSwitchTests(unittest.TestCase):
    """开关是灰的：不点、不报「关不掉」，单独说明被上级开关禁用（#333）。"""

    def test_a_greyed_inner_switch_is_not_clicked(self):
        lines = []
        clock = Clock()
        install_clock(fast, clock)
        p = fake_phone(clock=clock, stages=[(0.0, GREY_CARD_PAGE)], say=lines.append)
        self.assertEqual(p.off(page="页"), 0)
        self.assertEqual(clock.clicks, 0)
        self.assertTrue(any("被上级开关禁用（开关是灰的），未改动 摇一摇广告" in line for line in lines))

    def test_a_greyed_row_is_not_clicked_and_is_not_reported_as_unclosable(self):
        lines = []
        clock = Clock()
        install_clock(fast, clock)
        p = fake_phone(clock=clock, stages=[(0.0, GREY_LIST_PAGE)], say=lines.append)
        self.assertEqual(p.off(page="页"), 0)
        self.assertEqual(clock.clicks, 0)                              # 守卫：一下都没点
        self.assertTrue(any("被上级开关禁用（开关是灰的），未改动 摇一摇广告" in line for line in lines))
        self.assertFalse(any("关不掉 摇一摇广告" in line for line in lines))
        self.assertEqual(p.changed, [])
        self.assertIn("  · 页：核对 1 项，调整 0 项", lines)             # 不是「本页未找到目标开关」


class OffDriverTests(unittest.TestCase):
    """off() 的点击节奏、回读重试、离页与记账；策略面在 tests/test_switch_plan.py。"""

    def phone(self, reads, size=(1080, 2340)):
        p = phone_stub("S")
        p.W, p.H = size
        p.screen.tree = Mock(return_value=ET.fromstring("<hierarchy/>"))
        p.screen.switches = p.switches = Mock(side_effect=reads)
        # off() 的回退还会问 switch_rows()：一起桩掉，否则它跑真实现、对着空树空转，
        # 这批用例就测不到「回退拿到的行」与实际读到的是同一份（标题回退的行为在 test_off_title_fallback）
        p.screen.switch_rows = Mock(return_value=[])
        p.screen.focus = Mock(return_value="app/settings")
        p.screen.click = p.click = Mock()
        p.toggler.confirm = p.confirm = Mock(return_value=None)
        p.screen.scroll_more = p.scroll_more = Mock(return_value=False)
        p.screen.say = p.say = Mock()
        p.screen.back = p.back = Mock()
        return p

    def run_off(self, p, clock=None, **kwargs):
        clock = clock or Clock()
        with patched_clock(clock):
            done = p.off(**kwargs)
        p.screen.tree.assert_called()
        p.switches.assert_any_call(p.screen.tree.return_value)   # 主循环真的带着这一棵树读屏
        return done

    def test_first_target_is_clicked_alone_then_the_rest_follow(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000))]
        mid = [("广告甲", True, (500, 800)), ("广告乙", False, (500, 1000))]
        after = [("广告甲", False, (500, 800)), ("广告乙", False, (500, 1000))]
        p = self.phone([rows, rows, mid, after, after, after])
        done = self.run_off(p, clock=Clock(click_cost=0.0), page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000), (500, 800)])
        self.assertEqual(p.confirm.call_count, 2)   # 首击单独确认一次 + 收尾统一确认
        self.assertEqual(p.screen.focus.call_count, 2)     # start + 首击后的离页检查，第二下不再检查
        self.assertEqual((done, p.switches.call_count), (2, 5))  # 多读的一次是首击后的坐标核对；没有要补的目标就不再读

    def test_a_confirmation_makes_every_following_click_slow(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000))]
        mid = [("广告甲", True, (500, 800)), ("广告乙", False, (500, 1000))]
        after = [("广告甲", False, (500, 800)), ("广告乙", False, (500, 1000))]
        p = self.phone([rows, rows, mid, after, after, after])
        p.toggler.confirm = p.confirm = Mock(return_value="确定")       # 第一个目标弹出确认框
        self.run_off(p, clock=Clock(click_cost=0.0), page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000), (500, 800)])
        self.assertEqual(p.confirm.call_count, 3)   # 首击 + 第二个目标各确认一次，收尾再一次
        self.assertEqual(p.screen.focus.call_count, 1)     # 确认分支不再走离页检查

    def test_non_slow_targets_are_clicked_with_a_short_pause_after_each(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000)), ("广告丙", True, (500, 1200))]
        mid = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000)), ("广告丙", False, (500, 1200))]
        after = [(t, False, xy) for t, _, xy in rows]
        p = self.phone([rows, rows, mid, after, after, after, after])
        clock = Clock(click_cost=0.0)
        moments = []
        p.screen.click = p.click = Mock(side_effect=lambda *a: moments.append(clock.t))
        self.run_off(p, clock=clock, page="页")
        self.assertEqual(round(moments[1] - moments[0], 2), 0.3)   # 首击后只核对坐标，不等确认框
        self.assertEqual(round(moments[2] - moments[1], 2), 0.06)  # 非 slow 的点击后停 0.06

    def test_a_row_that_disappears_after_being_switched_off_does_not_take_its_neighbour(self):
        """关掉一项这一行就消失、下面的行整体上移（#480 realme RMX3700「首页卡片管理」）。

        先点下面的行，上移的只可能是已经点过的行；首击后剩下的「推荐位」仍在原坐标，继续连着点。
        改前是自上而下点：关掉「推荐位」后第二次点击落在上移后的「便捷服务」上，把它误关了。"""
        rows = [("推荐位", True, (500, 800)), ("热搜", True, (500, 1000)), ("便捷服务", True, (500, 1200))]
        after_热搜 = [("推荐位", True, (500, 800)), ("便捷服务", True, (500, 1000))]
        after_推荐位 = [("便捷服务", True, (500, 800))]
        p = self.phone([rows, rows, after_热搜] + [after_推荐位] * 5)
        self.run_off(p, page="页", only=["推荐位", "热搜"])
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000), (500, 800)])

    def test_a_reflow_that_moves_a_remaining_target_is_re_read_before_clicking_it(self):
        """关掉一项后剩下的行也挪了位置（顶部提示条收起等）：点前重读，不用计划坐标。"""
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000))]
        moved = [("广告甲", True, (500, 600)), ("广告乙", False, (500, 1100))]
        after = [("广告甲", False, (500, 600)), ("广告乙", False, (500, 1100))]
        p = self.phone([rows, rows, moved, moved] + [after] * 5)
        done = self.run_off(p, page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000), (500, 600)])
        # 两行都点了、回读里都还在且已是关：记两项。这一页不测「点后消失」（见 #486 的用例）
        self.assertEqual((done, sorted(p.changed)), (2, [("页", "广告乙"), ("页", "广告甲")]))

    def test_a_duplicated_title_is_clicked_by_state_not_by_name(self):
        """同一张卡片里的两个开关同名：重读时要找还开着的那个，不能按标题取到已关的那行。"""
        rows = [("营销通知", True, (500, 800)), ("营销通知", False, (500, 1000)), ("广告乙", True, (500, 1200))]
        moved = [("营销通知", True, (500, 600)), ("营销通知", False, (500, 1000))]
        after = [("营销通知", False, (500, 600)), ("营销通知", False, (500, 1000))]
        p = self.phone([rows, rows, moved, moved] + [after] * 5)
        self.run_off(p, page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1200), (500, 600)])

    def test_a_wrong_readback_retries_at_the_fresh_coordinates(self):
        rows = [("广告推荐", True, (500, 800))]
        still = [("广告推荐", True, (620, 900))]    # 页面重排：坐标变了，状态还没变
        fixed = [("广告推荐", False, (620, 900))]
        p = self.phone([rows, rows, still, still, fixed])
        done = self.run_off(p, page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 800), (620, 900)])
        self.assertEqual(done, 1)
        self.assertEqual(p.changed, [("页", "广告推荐")])

    def test_three_failed_readbacks_are_reported_as_not_closed(self):
        """点过之后整页读空：这一页已无法核对，不能当成功（#486 的边界）。"""
        rows = [("广告推荐", True, (500, 800))]
        p = self.phone([rows, rows, rows] + [[]] * 4)
        with patch.object(fast.time, "sleep") as sleep:
            done = p.off(page="页")
        p.screen.tree.assert_called()
        p.switches.assert_any_call(p.screen.tree.return_value)
        p.say.assert_any_call("  ✗ 关不掉 广告推荐")
        p.click.assert_called_once_with(500, 800)   # 节点消失后不沿用旧坐标重拨
        self.assertEqual((done, p.changed), (0, []))
        self.assertEqual(p.switches.call_count, 7)  # 三次回读与两次重试的次数
        for pause in (0.25, 0.8, 0.4):
            sleep.assert_any_call(pause)            # 收尾统一确认与二次重试的节奏

    def test_a_row_that_vanishes_after_being_switched_off_counts_as_closed(self):
        """关掉一项这一行就从列表消失的页面（#486，RMX3700「首页卡片管理」）。

        点击本身已经正确（#480），但收尾回读找不到这一行：以前读成「关不掉」，
        整页汇总成「调整 0 项」。点过、且页面仍读得到别的开关时按已关处理。"""
        rows = [("甲", True, (500, 800)), ("推荐位", True, (500, 1000))]
        after = [("甲", True, (500, 800))]
        p = self.phone([rows, rows] + [after] * 5)
        done = self.run_off(p, page="页", only=["推荐位"])
        self.assertEqual((done, p.changed), (1, [("页", "推荐位")]))
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000)])
        p.say.assert_any_call("  关 推荐位（点后从列表消失）")
        p.say.assert_any_call("  · 页：核对 1 项，调整 1 项")
        self.assertNotIn("  ✗ 关不掉 推荐位", [c.args[0] for c in p.say.call_args_list])

    def test_a_duplicated_title_is_judged_by_state_not_by_its_last_read_row(self):
        """同名两行（双列卡片，#403）：一行还开着、一行已关。判定与补点都按状态挑行，
        不取最后读到的那行——否则补点取决于读屏顺序，开着的那行一次也不点。"""
        rows = [("营销通知", True, (500, 800)), ("营销通知", False, (500, 1000))]
        p = self.phone([rows] * 20)
        done = self.run_off(p, page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 800)] * 3)  # 首击 + 两次补点
        self.assertEqual((done, p.changed), (0, []))
        p.say.assert_any_call("  ✗ 关不掉 营销通知")

    def test_a_vanished_target_that_was_never_clicked_is_still_reported_unclosable(self):
        """重排分支里因为读不到而跳过的目标：没点过就消失，不能当成点掉了。"""
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000)), ("常驻行", False, (500, 1200))]
        moved = [("常驻行", False, (500, 700))]      # 点掉 广告乙 后整页重排，广告甲 也不在回读里了
        p = self.phone([rows, rows, moved, moved] + [moved] * 10)
        done = self.run_off(p, page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000)])
        self.assertEqual((done, p.changed), (1, [("页", "广告乙")]))
        p.say.assert_any_call("  ✗ 关不掉 广告甲")

    def test_a_row_clicked_only_by_the_retry_counts_as_closed_when_it_vanishes(self):
        """计划后被跳过、只由补点点过的行，点后从列表消失同样算关（补点也是「点过」）。"""
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000)), ("常驻行", False, (500, 1200))]
        away = [("广告甲", True, (500, 2320)), ("常驻行", False, (500, 1200))]    # 重排时广告甲滚到带外
        back = [("广告甲", True, (500, 800)), ("常驻行", False, (500, 1200))]
        after = [("广告乙", False, (500, 1000)), ("常驻行", False, (500, 700))]   # 补点后广告甲消失
        p = self.phone([rows, rows, away, away, back, back] + [after] * 10)
        done = self.run_off(p, page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000), (500, 800)])
        self.assertEqual((done, p.changed), (2, [("页", "广告甲"), ("页", "广告乙")]))   # 广告乙 回读确认
        p.say.assert_any_call("  关 广告甲（点后从列表消失）")
        self.assertNotIn("  ✗ 关不掉 广告甲", [c.args[0] for c in p.say.call_args_list])

    def test_a_sub_page_with_fresh_titles_is_not_read_as_closed(self):
        """同一个 Activity 里换成子页（标题全新、前台名不变）：本屏计划时的行一个都不在了，
        不能把「找不到」当成关掉了。"""
        rows = [("广告推荐", True, (500, 800)), ("常驻行", False, (500, 1000))]
        sub_page = [("别的开关", False, (500, 700))]
        p = self.phone([rows, rows] + [sub_page] * 10)
        done = self.run_off(p, page="页", only=["广告推荐"])
        self.assertEqual((done, p.changed), (0, []))
        p.say.assert_any_call("  ✗ 关不掉 广告推荐")

    def test_a_click_that_takes_the_page_away_is_not_read_as_closed(self):
        """点过之后页面跳走：回读来自别的页，找不到这一行不等于关掉了。"""
        rows = [("广告推荐", True, (500, 800))]
        elsewhere = [("别的开关", True, (500, 700))]
        p = self.phone([rows, rows] + [elsewhere] * 10)
        p.screen.focus = Mock(side_effect=["app/settings", "app/settings"] + ["other/app"] * 10)
        done = self.run_off(p, page="页")
        self.assertEqual((done, p.changed), (0, []))
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 800)])   # 不在新页上补点
        # 守卫：回读确实查过是否跳走（start / 首击 / 三次回读 / 两次重试）；
        # 挑不到标题落点时回退不多读前台，所以这里不增一次
        self.assertEqual(p.screen.focus.call_count, 7)
        p.say.assert_any_call("  ✗ 关不掉 广告推荐")

    def test_a_retry_does_not_click_a_same_named_row_on_another_page(self):
        """跳走之后新页上恰好也有同名开关：补点不能落到新页上。"""
        rows = [("广告推荐", True, (500, 800))]
        elsewhere = [("广告推荐", True, (500, 700))]
        p = self.phone([rows, rows] + [elsewhere] * 10)
        p.screen.focus = Mock(side_effect=["app/settings", "app/settings"] + ["other/app"] * 10)
        done = self.run_off(p, page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 800)])
        self.assertEqual((done, p.changed), (0, []))

    def test_a_protection_switch_that_vanishes_is_not_reported_as_opened(self):
        """保护类开关是「主动打开」：行消失证明不了它开了，仍报打不开（#486 只定义了关闭方向）。"""
        rows = [("甲", True, (500, 800)), ("限制广告跟踪", False, (500, 1000))]
        after = [("甲", True, (500, 800))]
        p = self.phone([rows, rows] + [after] * 10)
        done = self.run_off(p, page="页", only=["限制广告跟踪"])
        self.assertEqual((done, p.changed), (0, []))
        p.say.assert_any_call("  ✗ 打不开 限制广告跟踪")

    def test_a_row_that_turns_grey_after_the_batch_is_not_retried_again(self):
        # 同一屏先关父级、后关子级：子级在回读时已经变灰，不能再连点、也不能报成「关不掉」
        rows = [("开屏广告", True, (500, 800)), ("摇一摇广告", True, (500, 1000))]
        after = [("开屏广告", False, (500, 800)), ("摇一摇广告", True, (500, 1000))]
        p = self.phone([rows, rows, rows] + [after] * 20)   # 第三次是首击后的重排探测
        plain, grey = ET.fromstring("<hierarchy/>"), ET.fromstring(
            '<hierarchy><node class="android.widget.Switch" checkable="true" checked="true"'
            ' enabled="false" bounds="[400,950][600,1050]"/></hierarchy>')
        p.screen.tree = Mock(side_effect=[plain, plain] + [grey] * 10)
        with patch.object(fast.time, "sleep"):
            done = p.off(page="页")
        clicks = [c.args for c in p.click.call_args_list]
        self.assertEqual(clicks[0], (500, 1000))                  # #480 起先点下面那行
        self.assertEqual(clicks[1:], [(500, 800)])                # 回读里的重试没有再点灰掉的那个
        p.say.assert_any_call("  · 被上级开关禁用（开关是灰的），未改动 摇一摇广告")
        p.say.assert_any_call("  关 开屏广告")
        self.assertNotIn("  ✗ 关不掉 摇一摇广告", [c.args[0] for c in p.say.call_args_list])
        self.assertEqual((done, p.changed), (1, [("页", "开屏广告")]))

    def test_a_grey_twin_does_not_swallow_the_other_twins_failure(self):
        # 同名两行（双列）：一个灰、一个点了没反应。只有全部同名行都灰才算灰态
        rows = [("个性化推荐", True, (500, 800)), ("个性化推荐", True, (800, 800))]
        p = self.phone([rows] * 20)
        grey = ET.fromstring('<hierarchy><node class="android.widget.Switch" checkable="true"'
                             ' checked="true" enabled="false" bounds="[400,750][600,850]"/></hierarchy>')
        p.screen.tree = Mock(return_value=grey)
        with patch.object(fast.time, "sleep"):
            done = p.off(page="页")
        self.assertEqual(done, 0)
        p.say.assert_any_call("  ✗ 关不掉 个性化推荐")
        self.assertNotIn("  · 被上级开关禁用（开关是灰的），未改动 个性化推荐",
                         [c.args[0] for c in p.say.call_args_list])

    def test_a_retry_skips_the_grey_twin_and_clicks_the_usable_one(self):
        """同名两行都开着、其中一行灰（#333 的双列形态）：补点落在可用那行，灰行一次也不点。
        两次重试各补一次，所以可用行共三次点击（首击 + 两次补点），都在同一坐标。"""
        rows = [("个性化推荐", True, (500, 800)), ("个性化推荐", True, (800, 800))]
        moved = [("个性化推荐", True, (500, 820)), ("个性化推荐", True, (800, 800))]   # 点完首屏微调了行位置
        p = self.phone([rows, rows, moved] + [moved] * 20)
        plain = ET.fromstring("<hierarchy/>")
        grey = ET.fromstring(
            '<hierarchy><node class="android.widget.Switch" checkable="true" checked="true"'
            ' enabled="false" bounds="[400,750][600,850]"/></hierarchy>')   # 只盖住左列 (500,800)
        p.screen.tree = Mock(side_effect=[plain] + [grey] * 10)   # 首屏计划后（首击起）就只剩灰树
        with patch.object(fast.time, "sleep"):
            done = p.off(page="页")
        # 首击 + 两次补点，都落在可用那行；灰行一次不碰（#480 按计划逆序先点后一个）
        self.assertEqual([c.args for c in p.click.call_args_list], [(800, 800)] * 3)
        self.assertEqual(done, 0)
        p.say.assert_any_call("  ✗ 关不掉 个性化推荐")

    def test_a_duplicate_title_whose_open_twin_turned_grey_is_reported_as_disabled(self):
        """同名两行：一行已关、另一行点击后变灰。灰态只看还没到目标态的行，判据仍是「一个灰不吞掉别的失败」。"""
        rows = [("营销通知", True, (500, 800)), ("营销通知", False, (500, 1000))]
        p = self.phone([rows] * 20)
        plain = ET.fromstring("<hierarchy/>")
        grey = ET.fromstring(
            '<hierarchy><node class="android.widget.Switch" checkable="true" checked="true"'
            ' enabled="false" bounds="[400,750][600,850]"/></hierarchy>')
        p.screen.tree = Mock(side_effect=[plain, plain] + [grey] * 10)
        with patch.object(fast.time, "sleep"):
            done = p.off(page="页")
        self.assertEqual(done, 0)
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 800)])  # 灰行一次也不补点
        p.say.assert_any_call("  · 被上级开关禁用（开关是灰的），未改动 营销通知")
        self.assertNotIn("  ✗ 关不掉 营销通知", [c.args[0] for c in p.say.call_args_list])

    def test_the_same_grey_row_is_reported_once_across_screens(self):
        rows = [("摇一摇广告", True, (500, 800))]
        p = self.phone([rows] * 5)
        p.screen.scroll_more = p.scroll_more = Mock(side_effect=[True, False])
        p.screen.tree = Mock(return_value=ET.fromstring(
            '<hierarchy><node class="android.widget.Switch" checkable="true" checked="true"'
            ' enabled="false" bounds="[400,750][600,850]"/></hierarchy>'))
        with patch.object(fast.time, "sleep"):
            done = p.off(page="页")
        self.assertEqual(done, 0)
        self.assertEqual([c.args[0] for c in p.say.call_args_list].count(
            "  · 被上级开关禁用（开关是灰的），未改动 摇一摇广告"), 1)

    def test_three_failed_readbacks_on_a_protection_switch_say_it_will_not_open(self):
        rows = [("限制广告跟踪", False, (500, 800))]
        p = self.phone([rows, rows, rows] + [[]] * 4)
        done = self.run_off(p, page="页")
        p.say.assert_any_call("  ✗ 打不开 限制广告跟踪")
        self.assertEqual((done, p.changed), (0, []))

    def test_leaving_the_page_after_the_first_click_stops_the_segment(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000))]
        p = self.phone([rows, rows])
        p.screen.focus = Mock(side_effect=["app/settings", "other/app", "other/app"])
        done = self.run_off(p, page="页")
        self.assertEqual(done, 0)
        p.click.assert_called_once_with(500, 1000)
        p.back.assert_called_once_with()
        p.scroll_more.assert_not_called()
        p.say.assert_any_call("  ! 页面变了（other/app），停")

    def test_the_summary_counts_checked_and_adjusted(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", False, (500, 1000))]
        after = [("广告甲", False, (500, 800)), ("广告乙", False, (500, 1000))]
        p = self.phone([rows, rows, after, after, after])
        self.run_off(p, page="系统·广告服务")
        p.say.assert_any_call("  · 系统·广告服务：核对 2 项，调整 1 项")

    def test_a_protection_switch_is_reported_as_opened(self):
        rows = [("限制广告跟踪", False, (500, 800))]
        after = [("限制广告跟踪", True, (500, 800))]
        p = self.phone([rows, rows, after, after, after])
        done = self.run_off(p, page="页")
        p.say.assert_any_call("  开（保护类开关） 限制广告跟踪")
        self.assertEqual((done, p.changed), (1, [("页", "限制广告跟踪")]))

    def test_a_page_of_already_closed_switches_is_checked_but_not_adjusted(self):
        rows = [("个性化推荐", False, (500, 800))]
        p = self.phone([rows, rows])
        self.run_off(p, page="页")
        p.click.assert_not_called()
        p.say.assert_any_call("  · 页：核对 1 项，调整 0 项")
        self.assertEqual(p.switches.call_count, 2)

    def test_a_page_without_a_named_target_says_not_found(self):
        rows = [("关闭推送", True, (500, 800))]
        p = self.phone([rows, rows])
        self.run_off(p, page="页")
        p.click.assert_not_called()
        p.say.assert_any_call("  · 页：核对 0 项，调整 0 项（本页未找到目标开关）")
        self.assertEqual(p.switches.call_count, 2)

    def test_checked_accumulates_across_screens(self):
        first = [("个性化推荐", False, (500, 800))]
        second = [("猜你喜欢", False, (500, 1000))]
        p = self.phone([first, first, second])
        p.screen.scroll_more = p.scroll_more = Mock(side_effect=[True, False])
        done = self.run_off(p, page="页")
        self.assertEqual((done, p.switches.call_count), (0, 3))
        p.click.assert_not_called()
        p.say.assert_any_call("  · 页：核对 2 项，调整 0 项")

    def test_kept_accumulates_across_screens_in_safe_mode(self):
        first = [("个性化推荐", True, (500, 800))]
        second = [("猜你喜欢", True, (500, 1000))]
        p = self.phone([first, first, second])
        p.safe_mode = True
        p.screen.scroll_more = p.scroll_more = Mock(side_effect=[True, False])
        self.run_off(p, page="页")
        p.click.assert_not_called()
        p.say.assert_any_call("  · 页：安全模式不做整页全关，本页 2 个开关未改动，需要时请按清单手动关")


class MissedLedgerTests(unittest.TestCase):
    """#788：拨不动的开关除了那行 ✗，还要记进引擎台账（形状与 `Phone.changed` 对齐）。"""

    def phone(self, reads, size=(1080, 2340)):
        p = phone_stub("S")
        p.W, p.H = size
        p.screen.tree = Mock(return_value=ET.fromstring("<hierarchy/>"))
        p.screen.switches = p.switches = Mock(side_effect=reads)
        p.screen.switch_rows = Mock(return_value=[])
        p.screen.focus = Mock(return_value="app/settings")
        p.screen.click = p.click = Mock()
        p.toggler.confirm = p.confirm = Mock(return_value=None)
        p.screen.scroll_more = p.scroll_more = Mock(return_value=False)
        p.screen.say = p.say = Mock()
        p.screen.back = p.back = Mock()
        return p

    def run_off(self, p, **kwargs):
        with patched_clock(Clock()):                     # 假钟的 sleep 只推进读数，不真等
            done = p.off(**kwargs)
        p.screen.tree.assert_called()
        p.switches.assert_any_call(p.screen.tree.return_value)   # 主循环真的带着这一棵树读屏
        return done

    def test_a_switch_that_will_not_budge_lands_in_the_ledger(self):
        rows = [("广告推荐", True, (500, 800))]
        p = self.phone([])
        p.screen.switches = p.switches = Mock(return_value=rows)       # 一直拨不动：读几次都是开着
        done = self.run_off(p, page="页")
        self.assertEqual({c.args for c in p.click.call_args_list}, {(500, 800)})   # 首击 + 两轮补点都点它
        self.assertEqual((done, p.changed), (0, []))
        self.assertEqual(p.missed, [("页", "广告推荐")])

    def test_the_same_switch_across_screens_is_counted_once(self):
        """滚动后同一行还留在屏带里：每屏都会重新成为目标，但不能记成两个（#788 复核）。"""
        rows = [("广告推荐", True, (500, 800))]
        p = self.phone([])
        p.screen.switches = p.switches = Mock(return_value=rows)
        p.screen.scroll_more = p.scroll_more = Mock(side_effect=[True, False])
        self.run_off(p, page="页")
        self.assertEqual(p.missed, [("页", "广告推荐")])

    def test_a_later_pass_that_gets_it_clears_the_ledger_entry(self):
        """上一次没拨动、这一次拨到了：旧条目要撤销，否则结果页会报一次假失败。"""
        rows = [("广告推荐", True, (500, 800))]
        after = [("广告推荐", False, (500, 800))]
        clicked = []
        p = self.phone([])
        p.screen.click = p.click = Mock(side_effect=lambda *a: clicked.append(a))
        p.screen.switches = p.switches = Mock(side_effect=lambda *a: after if clicked else rows)
        p.missed = [("页", "广告推荐")]            # 上一次 off() 留下的
        done = self.run_off(p, page="页")
        self.assertEqual((done, p.changed), (1, [("页", "广告推荐")]))
        self.assertEqual(p.missed, [])

    def test_a_second_pass_that_finds_it_closed_clears_the_ledger_entry(self):
        """同页再调一次 off()：这次它已关着、不是目标，靠拨动计划的 checked 撤销旧条目。"""
        rows = [("广告推荐", True, (500, 800))]
        after = [("广告推荐", False, (500, 800))]
        p = self.phone([])
        p.screen.switches = p.switches = Mock(return_value=rows)
        self.run_off(p, page="页")
        self.assertEqual(p.missed, [("页", "广告推荐")])
        p.screen.switches = p.switches = Mock(return_value=after)
        self.run_off(p, page="页")
        self.assertEqual(p.missed, [])

    def test_a_protection_switch_that_will_not_open_lands_in_the_ledger_too(self):
        rows = [("限制广告跟踪", False, (500, 800))]
        p = self.phone([rows] * 20)
        self.run_off(p, page="页")
        p.say.assert_any_call("  ✗ 打不开 限制广告跟踪")
        self.assertEqual(p.missed, [("页", "限制广告跟踪")])

    def test_a_page_that_all_closes_leaves_the_ledger_empty(self):
        rows = [("广告甲", True, (500, 800))]
        after = [("广告甲", False, (500, 800))]
        clicked = []
        p = self.phone([])
        p.screen.click = p.click = Mock(side_effect=lambda *a: clicked.append(a))
        p.screen.switches = p.switches = Mock(side_effect=lambda *a: after if clicked else rows)
        self.run_off(p, page="页")
        self.assertEqual(p.missed, [])

    def test_a_row_that_vanishes_after_being_switched_off_is_not_missed(self):
        """点后从列表消失按已关记账（#486）：它进了 `changed`，不进台账。"""
        rows = [("甲", True, (500, 800)), ("推荐位", True, (500, 1000))]
        after = [("甲", True, (500, 800))]
        p = self.phone([rows, rows] + [after] * 5)
        self.run_off(p, page="页", only=["推荐位"])
        self.assertEqual(p.changed, [("页", "推荐位")])
        self.assertEqual(p.missed, [])

    def test_a_grey_switch_is_not_missed(self):
        """灰态是「被上级开关禁用」，不是没拨动（#333）。"""
        lines = []
        clock = Clock()
        install_clock(fast, clock)
        p = fake_phone(clock=clock, stages=[(0.0, GREY_LIST_PAGE)], say=lines.append)
        p.off(page="页")
        self.assertEqual(clock.clicks, 0)                                # 守卫：真的当过目标、但一下都没点
        self.assertTrue(any("被上级开关禁用（开关是灰的），未改动 摇一摇广告" in line for line in lines))
        self.assertEqual((p.changed, p.missed), ([], []))


class MissedLineTests(unittest.TestCase):
    def test_lists_page_and_title(self):
        self.assertEqual(fast.missed_line([("设置·广告服务", "个性化广告推荐")]),
                         "没拨动的开关：1 个（设置·广告服务 · 个性化广告推荐）")

    def test_a_switch_without_a_page_name_is_listed_by_its_title(self):
        self.assertEqual(fast.missed_line([("", "广告推荐")]), "没拨动的开关：1 个（广告推荐）")

    def test_a_single_extra_entry_still_says_how_many(self):
        missed = [(f"页{i}", f"开关{i}") for i in range(9)]
        self.assertTrue(fast.missed_line(missed).endswith("等 1 个）"))

    def test_the_tail_beyond_the_limit_is_folded(self):
        missed = [(f"页{i}", f"开关{i}") for i in range(10)]
        line = fast.missed_line(missed, limit=8)
        self.assertTrue(line.startswith("没拨动的开关：10 个（"))
        self.assertIn("开关7", line)
        self.assertNotIn("开关8", line)
        self.assertTrue(line.endswith("等 2 个）"))


class ReportRunTests(unittest.TestCase):
    """#788：脚本跑完的收尾把「没拨动的开关」也算进退出码。"""

    def quiet(self):
        return patch.dict("os.environ", {"AAC_EVENTS": ""})

    def test_a_clean_run_prints_nothing_and_returns_zero(self):
        p = phone_stub("S")
        with self.quiet(), patch("builtins.print") as out:
            self.assertEqual(fast.report_run({}, p), 0)
        out.assert_not_called()

    def test_failed_steps_alone_still_exit_one(self):
        with self.quiet(), patch("builtins.print") as out:
            self.assertEqual(fast.report_run({"FAILED_STEPS": ["商店"]}, phone_stub("S")), 1)
        out.assert_called_once_with("未完成步骤：商店", flush=True)

    def test_missed_switches_alone_exit_one(self):
        p = phone_stub("S")
        p.missed = [("页", "个性化广告推荐")]
        with self.quiet(), patch("builtins.print") as out:
            self.assertEqual(fast.report_run({}, p), 1)
        out.assert_called_once_with("没拨动的开关：1 个（页 · 个性化广告推荐）", flush=True)

    def test_a_halted_step_gets_its_own_line_and_the_event(self):
        p = phone_stub("S")
        p.missed = []
        scope = {"FAILED_STEPS": ["商店", "主题"], "HALTED_STEPS": ["商店", "主题"]}
        with self.quiet(), patch("builtins.print") as out, \
             patch.object(fast.events, "emit") as emit:
            self.assertEqual(fast.report_run(scope, p), 1)
        emit.assert_called_once_with("failed_steps", steps=["商店", "主题"])
        self.assertEqual([(c.args, c.kwargs) for c in out.call_args_list],
                         [(("未完成步骤：商店、主题",), {"flush": True}),
                          (("因中止未执行：商店、主题",), {"flush": True})])

    def test_both_inputs_print_both_lines(self):
        p = phone_stub("S")
        p.missed = [("页", "广告推荐")]
        with self.quiet(), patch("builtins.print") as out:
            self.assertEqual(fast.report_run({"FAILED_STEPS": ["商店"]}, p), 1)
        self.assertEqual([(c.args, c.kwargs) for c in out.call_args_list],
                         [(("未完成步骤：商店",), {"flush": True}),
                          (("没拨动的开关：1 个（页 · 广告推荐）",), {"flush": True})])

    def test_a_recipe_whose_switches_will_not_budge_ends_with_a_failing_rc(self):
        """假设备上跑一份脚本：点不动的开关留在台账里，收尾退出码为 1。

        页面一直是那两行开着——`Device` 的点击只推进假时钟，回读永远没到位。"""
        p = fake_phone(stages=[(0.0, LIST_PAGE)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "recipe.toml")
            path.write_text('model = "x"\nmodels = ["x"]\n[[segment]]\nname = "a"\nops = [{kind = "off", page = "设置·广告服务", page_wide = true}]\n', encoding="utf-8")
            scope, _ = load_recipe(p, path, [])
        self.assertEqual(p.missed, [("设置·广告服务", "个性化推荐"), ("设置·广告服务", "猜你喜欢")])
        with patch("builtins.print"):
            self.assertEqual(fast.report_run(scope, p), 1)

    def run_script(self, page):
        """在假设备上让 `execute()` 走一遍 `run` 分支：临时脚本 + 临时备份目录。"""
        clock = Clock()
        install_clock(fast, clock)
        p = fake_phone(clock=clock, stages=[(0.0, page)])
        out, code = io.StringIO(), 0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "recipe.toml")
            path.write_text('model = "x"\nmodels = ["x"]\n[[segment]]\nname = "a"\nops = [{kind = "off", page = "设置·广告服务", page_wide = true}]\n', encoding="utf-8")
            with patch.dict(os.environ, {"AAC_BACKUPS": tmp}), contextlib.redirect_stdout(out):
                try:
                    fast.execute(p, "run", [str(path)])
                except SystemExit as e:
                    code = e.code
        return code, out.getvalue()

    def test_the_run_branch_turns_the_ledger_into_a_failing_rc(self):
        """收尾那一句 `if report_run(g, p): sys.exit(1)` 本身由这条守住（#788）。"""
        code, printed = self.run_script(LIST_PAGE)
        self.assertEqual(code, 1)
        self.assertIn("没拨动的开关：2 个（设置·广告服务 · 个性化推荐、设置·广告服务 · 猜你喜欢）", printed)

    def test_the_run_branch_stays_quiet_when_every_switch_is_closed(self):
        code, printed = self.run_script(CLOSED_PAGE)
        self.assertEqual(code, 0)
        self.assertNotIn("没拨动的开关", printed)


class ScreenGoneTests(unittest.TestCase):
    def test_a_gone_background_screen_is_not_reported_as_a_reader_failure(self):
        """#674：屏已经没了不是读屏服务坏了，别把用户指去关别的客户端。"""
        gone = fast.u2.exceptions.UiAutomationError("后台屏意外关闭（建屏进程已退出），这一步无法继续")
        with patch.object(phone_connection, "connect", side_effect=gone):
            with self.assertRaises(RuntimeError) as caught:
                fast.Phone("S", log=False)
        self.assertIn("那块屏已经关了", str(caught.exception))
        self.assertNotIn("读屏服务（UiAutomation）启动失败", str(caught.exception))

    def test_a_gone_screen_found_on_the_first_read_gets_the_same_sentence(self):
        """#928：connect() 成功、紧接着的第一次读屏才发现屏没了，结局与 #674 同形，并且要关掉 reader。"""
        for message in ("显示 7 不存在（这块屏已经没了）",
                        "后台屏意外关闭（建屏进程已退出），这一步无法继续"):
            reader = GoneOnFirstRead(message)
            with patch.object(phone_connection, "connect",
                              side_effect=AssertionError("给了 reader 就不该连真机")), \
                 self.assertRaises(RuntimeError) as caught:
                fast.Phone("S", log=False, reader=reader)
            self.assertIn("那块屏已经关了", str(caught.exception), message)
            self.assertIn("本次未点击开关", str(caught.exception), message)
            self.assertNotIn("读屏服务（UiAutomation）启动失败", str(caught.exception))
            self.assertTrue(reader.closed, f"首读失败也要关掉 reader：{message}")

    def test_a_broken_reader_on_the_first_read_still_points_at_the_reader_service(self):
        """不是屏没了的那种首读失败仍要说读屏服务起不来，别把用户指去重试后台屏。"""
        reader = GoneOnFirstRead("UiAutomation 被别的无障碍服务占用")
        with patch.object(phone_connection, "connect",
                          side_effect=AssertionError("给了 reader 就不该连真机")), \
             self.assertRaises(RuntimeError) as caught:
            fast.Phone("S", log=False, reader=reader)
        self.assertIn("读屏服务（UiAutomation）启动失败", str(caught.exception))
        self.assertTrue(reader.closed)

    def test_a_dead_command_service_on_the_first_read_is_still_a_disconnect(self):
        """#731：命令服务断开要以消息为证据判成断线，不能被首读那一层包成「读屏服务启动失败」。"""
        reader = GoneOnFirstRead("命令服务断开")
        with patch.object(phone_connection, "connect",
                          side_effect=AssertionError("给了 reader 就不该连真机")), \
             patch.object(fast.adb_link, "ON_PHONE", True):
            with self.assertRaises(fast.adb_link.DeviceLost) as caught:
                fast.Phone("S", log=False, reader=reader)
        self.assertIn("连接断开了", str(caught.exception))
        self.assertTrue(reader.closed)

    def test_a_slow_first_read_is_still_one_unfinished_step(self):
        """#731：读屏请求超时只是这一步没成，不是读屏服务起不来。"""
        reader = GoneOnFirstRead("读屏请求超时（30 秒）")
        with patch.object(phone_connection, "connect",
                          side_effect=AssertionError("给了 reader 就不该连真机")), \
             self.assertRaises(RuntimeError) as caught:
            fast.Phone("S", log=False, reader=reader)
        self.assertEqual(str(caught.exception), "这一步没有完成：读屏请求超时（30 秒）")
        self.assertTrue(reader.closed)


class GoneOnFirstRead:
    """假读屏：connect() 成功，第一次问尺寸时才失败（#928）。

    不进 fixtures：`phone_stub()` 绕开 `Phone.__init__` 造对象，而这两组用例要跑的正是构造处的翻译。
    """

    def __init__(self, message):
        self.message, self.closed, self.settings = message, False, {}
        self.shell = lambda *a, **k: None

    def window_size(self):
        raise fast.u2.exceptions.UiAutomationError(self.message)

    def close(self):
        self.closed = True


class Wired:
    """只记下自己怎么被用的协作者：门面的职责是把参数原样交出去（#1536）。"""

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs, self.calls = args, kwargs, []

    def dismiss(self):
        self.calls.append(("dismiss", (), {}))
        return ("returned", "dismiss")

    def __getattr__(self, name):
        def record(*a, **k):
            self.calls.append((name, a, k))
            return ("returned", name)
        return record


# 门面上不返回值的动作动词：只断言转发，不断言返回值。
VOID_FORWARDS = {
    "check_alive", "close", "say", "ls", "note_miss", "click", "back", "swipe", "home", "press",
    "app_stop", "tap_id", "set_text", "scroll", "top", "start", "_promoted_click", "_launch",
}


class FacadeForwardingTests(unittest.TestCase):
    """门面只做转发：每个动词把参数（含默认值）原样交给它的协作者，返回值原样交回。

    默认值是公开面的一部分——`settle=1.2` 改成别的数、`edge_ok=False` 改成 True，
    调用点的节奏与判据就变了，而门面本身没有第二种行为可测。
    """

    # (门面方法, 位置参数, 关键字, 协作者, 协作者收到的方法名, 期望位置参数, 期望关键字)
    FORWARDS = [
        ("_resilient_shell", ("ls",), {"timeout": 3}, "conn", "_resilient_shell", ("ls",), {"timeout": 3}),
        ("_u2", ("fn", "a", 2), {"x": 1}, "conn", "_u2", ("fn", "a", 2), {"x": 1}),
        ("check_alive", (), {}, "conn", "check_alive", (), {}),
        ("close", (), {}, "conn", "close", (), {}),
        ("say", ("提示",), {}, "conn", "say", ("提示",), {}),
        ("locked", (), {}, "conn", "locked", (), {}),
        ("wait_unlocked", (), {}, "conn", "wait_unlocked", (90,), {}),
        ("tree", (), {}, "screen", "tree", (), {}),
        ("focus", (), {}, "screen", "focus", (), {}),
        ("texts", (), {}, "screen", "texts", (None,), {}),
        ("page_text", (), {}, "screen", "page_text", (), {}),
        ("on_screen", ("节点",), {}, "screen", "on_screen", ("节点",), {}),
        ("switches", (), {}, "screen", "switches", (None,), {}),
        ("switches_raw", (), {}, "screen", "switches", (None,), {}),
        ("switch_rows", (), {}, "screen", "switch_rows", (None,), {}),
        ("sig", (), {}, "screen", "sig", (), {}),
        ("snapshot", (), {}, "screen", "snapshot", (), {"with_rows": True, "focus": None, "root": None}),
        ("scroll_more", (), {}, "screen", "scroll_more", (), {}),
        ("ls", (), {}, "screen", "ls", (), {}),
        ("_page_diagnosis", (), {}, "screen", "_page_diagnosis", (), {}),
        ("note_miss", ("文字",), {}, "screen", "note_miss", ("文字",), {}),
        ("page_evidence", (), {}, "screen", "page_evidence", ((),), {}),
        ("icon_candidates", (), {}, "screen", "icon_candidates", ((0.72, 0.0, 1.0, 0.16),), {}),
        ("click", (1, 2), {}, "screen", "click", (1, 2), {}),
        ("back", (), {}, "screen", "back", (1, True), {}),
        ("shell", ("getprop x",), {}, "screen", "shell", ("getprop x",), {"timeout": None}),
        ("swipe", (1, 2, 3, 4, 5), {}, "screen", "swipe", (1, 2, 3, 4, 5), {}),
        ("window_size", (), {}, "screen", "window_size", (), {}),
        ("home", (), {}, "screen", "home", (), {}),
        ("press", ("home",), {}, "screen", "press", ("home",), {}),
        ("app_stop", ("com.x",), {}, "screen", "app_stop", ("com.x",), {}),
        ("tap_id", (), {}, "screen", "tap_id", (None, None, 0), {}),
        ("tap_id_if_present", (), {}, "screen", "tap_id_if_present", (None, None, 0), {}),
        ("set_text", ("id", "值"), {}, "screen", "set_text", ("id", "值"), {}),
        ("apply", ("intent",), {}, "screen", "apply", ("intent",), {}),
        ("settle", ("before",), {}, "screen", "settle", ("before", 0.8), {}),
        ("find", ("文字",), {}, "screen", "find", ("文字",),
         {"exact": False, "root": None, "edge_ok": False, "nav": False}),
        ("scroll", (), {}, "screen", "scroll", (0.45, False), {}),
        ("residual_confirm", (), {}, "screen", "residual_confirm", (None,), {}),
        ("residual_note", (), {}, "screen", "residual_note", ("——", None), {}),
        ("dismiss", (), {}, "dismisser", "dismiss", (), {}),
        ("_promoted_click", (1, 2, "key"), {}, "dismisser", "promoted_click", (1, 2, "key"), {}),
        ("tap", ("文字",), {}, "navigator", "tap", ("文字", False, 6, 0.6, False, None), {}),
        ("in_settings_page", (), {}, "navigator", "in_settings_page", (), {}),
        ("await_page", (), {}, "navigator", "await_page", (2.4, 0.2, 0.15, fast.wait.UNSET), {}),
        ("entry", ("入口",), {}, "navigator", "entry", ("入口", 6, 2.4, 0.2, 2), {}),
        ("tap_icon", ("图标",), {}, "navigator", "tap_icon", ("图标", (0.72, 0.0, 1.0, 0.16), 3), {}),
        ("enter", ("入口",), {}, "navigator", "enter", ("入口", 0, 3), {}),
        ("go", ("入口", "期望"), {}, "navigator", "go", ("入口", "期望", 3, True), {}),
        ("tab", ("我的",), {}, "navigator", "tab", ("我的", 6.0), {}),
        ("top", (), {}, "navigator", "top", (None,), {}),
        ("confirm", (), {}, "toggler", "confirm", (), {}),
        ("off", (), {}, "toggler", "off", ((), None, "", 40), {}),
        ("focused_text", (), {}, "search", "focused_text", (), {}),
        ("type_text", ("关键词",), {}, "search", "type_text", ("关键词", 4.0), {}),
        ("edit_ready", (), {}, "search", "edit_ready", (), {}),
        ("setting", ("关键词",), {}, "search", "setting", ("关键词", None, None, None), {}),
        ("start", ("com.x",), {}, "launcher", "start", ("com.x", None, 1.2, None, None, 6.0), {}),
        ("has_text", (), {}, "launcher", "has_text", (), {}),
        ("expect_hits", ("约定",), {}, "launcher", "expect_hits", ("约定",), {}),
        ("expect_page", ("约定",), {}, "launcher", "expect_page", ("约定", 4.0, 0.2), {}),
        ("_landing_note", ("约定",), {}, "launcher", "_landing_note", ("约定",), {}),
        ("_launch_evidence", (), {}, "launcher", "_launch_evidence", ("", 0), {}),
        ("_launch", ("pkg", "act", 1.2, None), {}, "launcher", "_launch", ("pkg", "act", 1.2, None), {}),
    ]

    def test_each_verb_forwards_its_arguments_and_returns_the_value(self):
        for method, args, kwargs, collaborator, call, want_args, want_kwargs in self.FORWARDS:
            with self.subTest(method=method):
                p = phone_stub("test")
                stub = Wired()
                setattr(p, collaborator, stub)
                got = getattr(p, method)(*args, **kwargs)
                self.assertEqual(stub.calls, [(call, want_args, want_kwargs)])
                if call in VOID_FORWARDS:
                    self.assertIsNone(got)
                else:
                    self.assertEqual(got, ("returned", call))

    def test_optional_arguments_reach_the_collaborator_when_given(self):
        p = phone_stub("test")
        p.screen = Wired()
        p.navigator = Wired()
        p.launcher = Wired()
        p.switches_raw("根")
        p.tap_id_if_present("id", "文字", 3)
        p.find("文字", root="根")
        p.tap("文字", seen=["甲"])
        p.residual_confirm("根")
        p.start("com.x", activity=".A", settle=2.0, foreground="fg", expect="e", budget=7.0)
        p._launch("com.x", ".A", 2.0, "fg")
        self.assertEqual(p.screen.calls, [
            ("switches", ("根",), {}),
            ("tap_id_if_present", ("id", "文字", 3), {}),
            ("find", ("文字",), {"exact": False, "root": "根", "edge_ok": False, "nav": False}),
            ("residual_confirm", ("根",), {}),
        ])
        self.assertEqual(p.navigator.calls,
                         [("tap", ("文字", False, 6, 0.6, False, ["甲"]), {})])
        self.assertEqual(p.launcher.calls, [
            ("start", ("com.x", ".A", 2.0, "fg", "e", 7.0), {}),
            ("_launch", ("com.x", ".A", 2.0, "fg"), {}),
        ])

    def test_explicit_arguments_override_the_defaults(self):
        # 默认值之外再走一次显式传参：判据不只在默认值上成立
        p = phone_stub("test")
        screen = Wired()
        p.screen = screen
        p.find("文字", exact=True, edge_ok=True, nav=True)
        p.scroll(0.9, True)
        p.snapshot(with_rows=False)
        self.assertEqual(screen.calls, [
            ("find", ("文字",), {"exact": True, "root": None, "edge_ok": True, "nav": True}),
            ("scroll", (0.9, True), {}),
            ("snapshot", (), {"with_rows": False, "focus": None, "root": None}),
        ])


class PhoneWiringTests(unittest.TestCase):
    """`Phone.__init__` 只做装配：每个协作者拿到的是哪一份状态（#1536）。"""

    def build(self, *args, **kwargs):
        made = {}

        def factory(name):
            def make(*a, **k):
                made[name] = Wired(*a, **k)
                return made[name]
            return make

        names = ("Connection", "Screen", "Captures", "LostNote", "LaunchSession", "ChannelSession",
                 "Toggler", "SettingsSearch", "Dismisser", "Launcher", "Navigator")
        patches = [patch.object(fast, name, factory(name)) for name in names]
        patches.append(patch.object(fast, "_captures_root_from_env", lambda: "/tmp/caps"))
        for one in patches:
            self.enterContext(one)
        fast.Phone(*args, **kwargs)
        return made

    def test_each_collaborator_gets_the_state_it_owns(self):
        made = self.build("S")
        self.assertEqual(made["Connection"].args, ("S",))
        self.assertEqual(made["Connection"].kwargs, {"log": True, "reader": None})
        self.assertEqual(made["Captures"].args, ("/tmp/caps",))
        # 观测基座拿到连接与现场目录；两个都是构造处的对象，不是新的一份
        self.assertEqual(made["Screen"].args, (made["Connection"], made["Captures"]))
        self.assertEqual(made["Toggler"].args, (made["Screen"], made["LostNote"]))
        self.assertEqual(made["SettingsSearch"].args, (made["Screen"], made["LostNote"]))
        self.assertEqual(made["Dismisser"].args, (made["Screen"], made["LaunchSession"]))
        self.assertEqual(made["Launcher"].args,
                         (made["Screen"], made["LostNote"], made["LaunchSession"],
                          made["Dismisser"].dismiss))
        self.assertEqual(made["Navigator"].args,
                         (made["Screen"], made["LostNote"], made["Dismisser"].dismiss))

    def test_the_sessions_are_real_objects(self):
        made = self.build("S")
        for name in ("LostNote", "LaunchSession", "ChannelSession"):
            self.assertIn(name, made)          # 被换成 None 时这里就红：属性读到的是 None

    def test_the_log_flag_and_reader_go_to_the_connection(self):
        reader = Mock()
        made = self.build("S", log=False, reader=reader)
        self.assertEqual(made["Connection"].kwargs, {"log": False, "reader": reader})

    def test_the_connection_is_checked_once_at_the_end(self):
        made = self.build("S")
        self.assertEqual(made["Connection"].calls, [("check_input", (), {})])


class LedgerTests(unittest.TestCase):
    """失败段与「因中止未执行」段名的来源：`rt` 对象、作用域里的 `rt`、纯字典三种形状。"""

    def test_an_runtime_object_is_read_directly(self):
        rt = SimpleNamespace(failed_steps=["商店"], halted_steps=["主题"])
        self.assertEqual(fast._ledger(rt), (["商店"], ["主题"]))

    def test_a_scope_dict_with_a_runtime_uses_the_runtime(self):
        rt = SimpleNamespace(failed_steps=["商店"], halted_steps=[])
        self.assertEqual(fast._ledger({"rt": rt}), (["商店"], []))

    def test_a_scope_object_with_a_runtime_still_reads_the_step_lists(self):
        # 只有 dict 作用域才按 `rt` 读；别的对象走 FAILED_STEPS（`rt` 分支只在 isinstance(dict) 下开）
        rt = SimpleNamespace(failed_steps=["商店"], halted_steps=[])
        self.assertEqual(fast._ledger(SimpleNamespace(get=lambda key: rt if key == "rt" else None)),
                         ([], []))

    def test_a_plain_mapping_reads_the_step_lists(self):
        scope = {"FAILED_STEPS": ["商店", "主题"], "HALTED_STEPS": ["主题"]}
        self.assertEqual(fast._ledger(scope), (["商店", "主题"], ["主题"]))

    def test_a_plain_mapping_without_a_halted_list_reports_none_halted(self):
        self.assertEqual(fast._ledger({"FAILED_STEPS": ["商店"]}), (["商店"], []))


class MissedLineLimitTests(unittest.TestCase):
    def test_exactly_at_the_limit_is_not_folded(self):
        missed = [(f"页{i}", f"开关{i}") for i in range(8)]
        self.assertNotIn("等", fast.missed_line(missed, limit=8))


class ExecuteCliTests(unittest.TestCase):
    """`execute()` 的逐条命令：每条命令的任务名、落点与打印（#1536）。"""

    def phone(self, page="<hierarchy><node text='甲' bounds='[0,100][400,160]'/></hierarchy>", **fields):
        p = fake_phone(size=(1080, 2340), stages=[(0.0, page)], **fields)
        p.screen.captures = fast.Captures("")
        clock = Clock()
        clock.t = 5.0                    # 起跑时刻不是 0：`time.time() + t` 这类变体会露出 10.0 秒
        install_clock(fast, clock)
        return p

    def run_execute(self, phone, cmd, rest=()):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fast.execute(phone, cmd, list(rest))
        return out.getvalue()

    def test_the_capture_task_is_the_command_name_except_for_run(self):
        for cmd, want in (("ls", "ls"), ("tap", "tap"), ("scan", "scan"), ("check", "check")):
            with self.subTest(cmd=cmd):
                p = self.phone()
                p.ls = lambda: None
                p.tap = lambda text: None
                p.switches = lambda: []
                self.run_execute(p, cmd, ["甲"])
                self.assertEqual(p.screen.captures.task, want)

    def test_check_reports_the_screen_size_and_touches_nothing(self):
        p = self.phone()
        self.assertIn("读屏检查通过：1080 × 2340；未点击或修改任何开关", self.run_execute(p, "check"))

    def test_check_on_a_locked_phone_asks_the_owner_to_unlock(self):
        p = self.phone(locked=lambda: True)
        with self.assertRaises(SystemExit) as caught:
            self.run_execute(p, "check")
        self.assertEqual(caught.exception.code, "手机锁屏了，请机主解锁后重试")

    def test_check_with_no_nodes_asks_for_the_settings_home(self):
        p = self.phone(page="<hierarchy/>")
        with self.assertRaises(SystemExit) as caught:
            self.run_execute(p, "check")
        self.assertEqual(caught.exception.code,
                         "读屏服务已连接，但没有读到页面节点，请解锁并停在设置首页后重试")

    def test_ls_is_one_read_and_one_print(self):
        p = self.phone()
        calls = []
        p.screen.ls = lambda: calls.append("ls")
        self.run_execute(p, "ls")
        self.assertEqual(calls, ["ls"])

    def test_tap_taps_each_argument_then_lists(self):
        p = self.phone()
        tapped, listed = [], []
        p.navigator.tap = lambda text, *a: tapped.append(text)
        p.screen.ls = lambda: listed.append("ls")
        self.run_execute(p, "tap", ["甲", "乙"])
        self.assertEqual(tapped, ["甲", "乙"])
        self.assertEqual(listed, ["ls"])

    def test_off_passes_the_keep_list_and_reports_the_count(self):
        p = self.phone()
        seen = []
        p.toggler.off = lambda *a: (seen.append(a), 2)[1]
        out = self.run_execute(p, "off", ["甲,乙"])
        self.assertEqual(seen, [(["甲", "乙"], None, "", 40)])
        self.assertIn("关了 2 个，0.0 秒", out)

    def test_off_without_a_keep_list_keeps_nothing(self):
        p = self.phone()
        seen = []
        p.toggler.off = lambda *a: (seen.append(a), 0)[1]
        self.run_execute(p, "off", [])
        self.assertEqual(seen, [((), None, "", 40)])

    def test_only_passes_the_only_list(self):
        p = self.phone()
        seen = []
        p.toggler.off = lambda *a: (seen.append(a), 1)[1]
        out = self.run_execute(p, "only", ["甲,乙"])
        self.assertEqual(seen, [((), ["甲", "乙"], "", 40)])
        self.assertIn("关了 1 个，0.0 秒", out)

    def test_scan_lists_every_switch_once_and_stops_at_the_bottom(self):
        p = self.phone()
        pages = [[("甲", True, (1, 2)), ("乙", False, (3, 4))], [("甲", True, (1, 2))]]
        p.screen.switches = lambda root=None: pages.pop(0) if pages else []
        p.screen.scroll_more = lambda: len(pages) > 0
        out = self.run_execute(p, "scan")
        self.assertIn("  [开] 甲", out)
        self.assertIn("  [关] 乙", out)
        self.assertIn("2 个开关，开着 1 个，0.0 秒", out)

    def test_an_unknown_command_prints_the_doc(self):
        p = self.phone()
        out = self.run_execute(p, "wat")
        self.assertIn("去广告快速引擎", out)

    def test_scan_scrolls_at_most_sixty_times(self):
        p = self.phone()
        p.screen.switches = lambda root=None: [("甲", True, (1, 2))]
        scrolled = []
        p.screen.scroll_more = lambda: (scrolled.append(1), True)[1]
        self.run_execute(p, "scan")
        self.assertEqual(len(scrolled), 60)

    def test_scan_of_an_empty_page_returns_to_the_top(self):
        p = self.phone()
        p.screen.switches = lambda root=None: []
        p.screen.scroll_more = lambda: False
        top, listed = [], []
        p.navigator.top = lambda n=None: top.append(n)
        p.screen.ls = lambda: listed.append("ls")
        out = self.run_execute(p, "scan")
        self.assertEqual((top, listed), ([None], ["ls"]))
        self.assertIn("0 个开关，开着 0 个，0.0 秒", out)


RECIPE_TOML = ('model = "x"\nmodels = ["x"]\n[[segment]]\nname = "a"\n'
               'ops = [{kind = "off", page = "设置·广告服务", page_wide = true}]\n')


class ExecuteRunTests(unittest.TestCase):
    """`execute()` 的 run 分支：参考脚本、锁屏、版本不符、日志与退出码（#1536）。"""

    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.recipe = self.dir / "recipe.toml"
        self.recipe.write_text(RECIPE_TOML, encoding="utf-8")

    def phone(self, build="", osv=""):
        p = fake_phone(size=(1080, 2340), stages=[(0.0, "<hierarchy/>")])
        p.screen.captures = fast.Captures("")
        answers = {"getprop ro.build.display.id": build,
                   "getprop ro.mi.os.version.incremental": osv}
        p.screen.shell = lambda command, timeout=None: answers.get(command, "")
        clock = Clock(click_cost=0.0)
        clock.t = 5.0                    # 起跑时刻不是 0：`time.time() + t` 这类变体会露出 10 秒
        install_clock(fast, clock)
        return p

    def run_execute(self, phone, rest):
        out = io.StringIO()
        code = 0
        frozen = SimpleNamespace(time=lambda: 5.0, sleep=lambda seconds: None)
        with contextlib.redirect_stdout(out), patch.object(fast, "time", frozen), \
             patch.dict(os.environ, {"AAC_BACKUPS": str(self.dir)}):
            try:
                fast.execute(phone, "run", rest)
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue()

    def test_the_capture_task_of_a_run_is_recipe(self):
        p = self.phone()
        self.run_execute(p, [str(self.recipe)])
        self.assertEqual(p.screen.captures.task, "recipe")

    def test_a_reference_script_turns_on_safe_mode_and_is_stripped(self):
        p = self.phone()
        seen = []
        with patch.object(fast.recipe_loader, "run", side_effect=lambda path, phone, only=(): seen.append(only) or Mock(rt={})):
            self.run_execute(p, [str(self.recipe), "--ref"])
        self.assertTrue(p.toggler.safe_mode)
        self.assertEqual(seen, [[]])          # `--ref` 已经从段参数里摘掉

    def test_the_segment_arguments_after_the_recipe_are_the_only_list(self):
        p = self.phone()
        seen = []
        with patch.object(fast.recipe_loader, "run", side_effect=lambda path, phone, only=(): seen.append((path, only)) or Mock(rt={})):
            self.run_execute(p, [str(self.recipe), "段一", "段二"])
        self.assertEqual(seen, [(str(self.recipe), ["段一", "段二"])])

    def test_a_locked_phone_stops_the_run_with_exit_two(self):
        p = self.phone()
        p.conn.wait_unlocked = lambda *a, **k: False
        code, out = self.run_execute(p, [str(self.recipe)])
        self.assertEqual(code, 2)
        self.assertEqual(out, "✗ 手机一直锁屏，本步骤没有执行。请解锁手机、保持亮屏后重试\n")

    def test_a_build_mismatch_falls_back_to_safe_mode(self):
        recipe = self.dir / "old.toml"
        recipe.write_text('build = "16.0.0.1"\n' + RECIPE_TOML.split("\n", 1)[1], encoding="utf-8")
        p = self.phone(build="17.0.0.157")
        _, out = self.run_execute(p, [str(recipe)])
        self.assertTrue(p.toggler.safe_mode)
        self.assertIn("⚠ 机型脚本是按 16.0.0.1 录的，这台是 17.0.0.157：用安全模式跑"
                      "（只关点名的开关），没找到的段会快速跳过", out)

    def test_a_matching_build_keeps_the_full_run(self):
        recipe = self.dir / "same.toml"
        recipe.write_text('build = "17.0.0"\n' + RECIPE_TOML.split("\n", 1)[1], encoding="utf-8")
        p = self.phone(build="17.0.0.157")
        _, out = self.run_execute(p, [str(recipe)])
        self.assertFalse(p.toggler.safe_mode)
        self.assertNotIn("用安全模式跑", out)

    def test_a_recipe_without_a_recorded_build_never_warns(self):
        p = self.phone(build="17.0.0.157")
        _, out = self.run_execute(p, [str(self.recipe)])
        self.assertFalse(p.toggler.safe_mode)
        self.assertNotIn("用安全模式跑", out)

    def test_a_matching_mi_os_version_is_enough_even_when_the_build_is_older(self):
        recipe = self.dir / "mi.toml"
        recipe.write_text('build = "2.0.5"\n' + RECIPE_TOML.split("\n", 1)[1], encoding="utf-8")
        p = self.phone(build="1.0.1", osv="2.0.5.0")
        _, out = self.run_execute(p, [str(recipe)])
        self.assertFalse(p.toggler.safe_mode)
        self.assertNotIn("用安全模式跑", out)

    def test_the_run_log_records_the_segment_outcome(self):
        p = self.phone()
        p.toggler.changed = [("设置·广告服务", "个性化推荐")]
        self.run_execute(p, [str(self.recipe)])
        self.assertIn("run-log.txt", [path.name for path in self.dir.iterdir()])
        lines = (self.dir / "run-log.txt").read_text(encoding="utf-8").splitlines()
        self.assertRegex(lines[1], r"^# \d{4}-\d\d-\d\d \d\d:\d\d 全跑  0s$")
        self.assertEqual(lines[2], "设置·广告服务\t个性化推荐")

    def test_the_finish_line_reports_what_was_closed(self):
        p = self.phone()
        p.toggler.changed = [("页", "甲"), ("页", "乙")]
        _, out = self.run_execute(p, [str(self.recipe)])
        self.assertIn("\n机型脚本跑完：关了 2 个，0 秒", out)

    def test_the_log_header_names_the_segments_that_ran(self):
        p = self.phone()
        with patch.object(fast.recipe_loader, "run", return_value=Mock(rt={})):
            self.run_execute(p, [str(self.recipe), "段一", "段二"])
        # 时间戳部分随机器而变，只看后半句
        header = (self.dir / "run-log.txt").read_text(encoding="utf-8").splitlines()[1]
        self.assertTrue(header.endswith(" 段一 段二  0s"), header)

    def test_the_log_follows_the_backup_root_not_the_recipe_folder(self):
        other = Path(self.dir, "backups")
        other.mkdir()
        p = self.phone()
        with patch.dict(os.environ, {"AAC_BACKUPS": str(other)}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                fast.execute(p, "run", [str(self.recipe)])
        self.assertTrue((other / "run-log.txt").is_file())
        self.assertFalse((self.dir / "run-log.txt").exists())

    def test_without_a_backup_root_the_log_sits_next_to_the_recipe(self):
        p = self.phone()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AAC_BACKUPS", None)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                fast.execute(p, "run", [str(self.recipe)])
        self.assertTrue((self.dir / "run-log.txt").is_file())

    def test_a_device_lost_mid_recipe_reports_what_was_done(self):
        p = self.phone()
        with patch.object(fast.recipe_loader, "run", side_effect=fast.adb_link.DeviceLost("断线了")), \
             patch("builtins.print") as out:
            code, _ = self.run_execute(p, [str(self.recipe)])
        self.assertEqual(code, 1)
        out.assert_called_once_with("\n✗ 断线了\n已停止：关了 0 个，0 秒", flush=True)


class MainTests(unittest.TestCase):
    """命令行入口：用法、串给 Phone 的参数、与两类异常的收尾（#1536）。"""

    def invoke(self, argv, execute=None):
        p = phone_stub("test")
        calls = {}

        class FacadeStub:
            def __init__(self, serial, **kwargs):
                calls["serial"], calls["kwargs"] = serial, kwargs

            def __enter__(self):
                return p

            def __exit__(self, *exc):
                calls["closed"] = True

        def fake_execute(phone, cmd, rest):
            calls["execute"] = (phone, cmd, rest)

        with patch.object(fast.sys, "argv", ["fast.py"] + argv), \
             patch.object(fast, "Phone", FacadeStub), \
             patch.object(fast, "execute", execute or fake_execute):
            result = fast.main()
        return result, calls

    def test_no_arguments_prints_the_doc_without_dispatching(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(self.invoke([])[0])
        self.assertIn("去广告快速引擎", out.getvalue())

    def test_help_flags_print_the_doc(self):
        for flag in (["--help"], ["-h"]):
            with self.subTest(flag=flag):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertIsNone(self.invoke(flag)[0])
                self.assertIn("去广告快速引擎", out.getvalue())

    def test_too_few_arguments_exit_one_with_the_doc(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            self.invoke(["-s", "SER"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("去广告快速引擎", out.getvalue())

    def test_a_missing_serial_flag_exit_one_with_the_doc(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            self.invoke(["-x", "SER", "ls"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("去广告快速引擎", out.getvalue())

    def test_the_serial_and_the_command_go_to_phone_and_execute(self):
        _, calls = self.invoke(["-s", "SER", "ls", "甲"])
        self.assertEqual(calls["serial"], "SER")
        self.assertEqual(calls["execute"][1:], ("ls", ["甲"]))
        self.assertTrue(calls["closed"])

    def test_a_runtime_error_is_reported_with_flush_and_exit_one(self):
        def boom(*a):
            raise RuntimeError("断线了")
        with patch("builtins.print") as out, self.assertRaises(SystemExit) as caught:
            self.invoke(["-s", "SER", "ls"], execute=boom)
        self.assertEqual(caught.exception.code, 1)
        out.assert_called_once_with("✗ 断线了", flush=True)

    def test_other_errors_are_translated_by_adb_link(self):
        error = ValueError("坏")

        def boom(*a):
            raise error
        with patch.object(fast.adb_link, "failure_message", return_value="人话") as message, \
             patch("builtins.print") as out, self.assertRaises(SystemExit) as caught:
            self.invoke(["-s", "SER", "ls"], execute=boom)
        message.assert_called_once_with(error, "SER")
        self.assertEqual(caught.exception.code, 1)
        out.assert_called_once_with("✗ 人话", flush=True)

    def test_an_untranslatable_error_propagates(self):
        def boom(*a):
            raise ValueError("坏")
        with patch.object(fast.adb_link, "failure_message", return_value=None), \
             self.assertRaises(ValueError):
            self.invoke(["-s", "SER", "ls"], execute=boom)


if __name__ == "__main__":
    unittest.main()
