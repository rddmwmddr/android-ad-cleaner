"""Phone 的接口面：读屏策略、探路的包名过滤、安全模式、读屏 adapter 的名字。

守的是「这些状态从哪来」：一次渠道尝试的诊断归 chan_fast（Attempt），
读屏策略与设备记忆归 Phone 构造处声明的字段。装配统一走 fixtures。
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import explore
import fast
from fixtures import Clock, Device, Timeline, fake_phone, install_clock, load_recipe, phone_stub
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
        p.systemui_text = True
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

    def test_a_stub_reader_is_the_same_object_as_d(self):
        p = phone_stub("S", d=reader())
        self.assertIs(p.d, p.reader)                                  # `d` 只是历史名字
        p.d = reader()                                                # 写 `d` 也写穿到 reader
        self.assertIsNotNone(p.reader)

    def test_phone_can_be_built_from_a_named_reader(self):
        r = reader()
        p = fast.Phone("S", log=False, reader=r)
        self.assertIs(p.reader, r)
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
        p.tree = Mock(return_value=ET.fromstring("<hierarchy/>"))
        p.switches = Mock(side_effect=reads)
        # off() 的回退还会问 switch_rows()：一起桩掉，否则它跑真实现、对着空树空转，
        # 这批用例就测不到「回退拿到的行」与实际读到的是同一份（标题回退的行为在 test_off_title_fallback）
        p.switch_rows = Mock(return_value=[])
        p.focus = Mock(return_value="app/settings")
        p.click = Mock()
        p.confirm = Mock(return_value=None)
        p.scroll_more = Mock(return_value=False)
        p.say = Mock()
        p.back = Mock()
        return p

    def run_off(self, p, clock=None, **kwargs):
        with patch.object(fast, "time", clock or Clock()):
            done = p.off(**kwargs)
        p.tree.assert_called()
        p.switches.assert_any_call(p.tree.return_value)   # 主循环真的带着这一棵树读屏
        return done

    def test_first_target_is_clicked_alone_then_the_rest_follow(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000))]
        mid = [("广告甲", True, (500, 800)), ("广告乙", False, (500, 1000))]
        after = [("广告甲", False, (500, 800)), ("广告乙", False, (500, 1000))]
        p = self.phone([rows, rows, mid, after, after, after])
        done = self.run_off(p, clock=Clock(click_cost=0.0), page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000), (500, 800)])
        self.assertEqual(p.confirm.call_count, 2)   # 首击单独确认一次 + 收尾统一确认
        self.assertEqual(p.focus.call_count, 2)     # start + 首击后的离页检查，第二下不再检查
        self.assertEqual((done, p.switches.call_count), (2, 5))  # 多读的一次是首击后的坐标核对；没有要补的目标就不再读

    def test_a_confirmation_makes_every_following_click_slow(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000))]
        mid = [("广告甲", True, (500, 800)), ("广告乙", False, (500, 1000))]
        after = [("广告甲", False, (500, 800)), ("广告乙", False, (500, 1000))]
        p = self.phone([rows, rows, mid, after, after, after])
        p.confirm = Mock(return_value="确定")       # 第一个目标弹出确认框
        self.run_off(p, clock=Clock(click_cost=0.0), page="页")
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 1000), (500, 800)])
        self.assertEqual(p.confirm.call_count, 3)   # 首击 + 第二个目标各确认一次，收尾再一次
        self.assertEqual(p.focus.call_count, 1)     # 确认分支不再走离页检查

    def test_non_slow_targets_are_clicked_with_a_short_pause_after_each(self):
        rows = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000)), ("广告丙", True, (500, 1200))]
        mid = [("广告甲", True, (500, 800)), ("广告乙", True, (500, 1000)), ("广告丙", False, (500, 1200))]
        after = [(t, False, xy) for t, _, xy in rows]
        p = self.phone([rows, rows, mid, after, after, after, after])
        clock = Clock(click_cost=0.0)
        moments = []
        p.click = Mock(side_effect=lambda *a: moments.append(clock.t))
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
        p.tree.assert_called()
        p.switches.assert_any_call(p.tree.return_value)
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
        p.focus = Mock(side_effect=["app/settings", "app/settings"] + ["other/app"] * 10)
        done = self.run_off(p, page="页")
        self.assertEqual((done, p.changed), (0, []))
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 800)])   # 不在新页上补点
        # 守卫：回读确实查过是否跳走（start / 首击 / 三次回读 / 两次重试）；
        # 挑不到标题落点时回退不多读前台，所以这里不增一次
        self.assertEqual(p.focus.call_count, 7)
        p.say.assert_any_call("  ✗ 关不掉 广告推荐")

    def test_a_retry_does_not_click_a_same_named_row_on_another_page(self):
        """跳走之后新页上恰好也有同名开关：补点不能落到新页上。"""
        rows = [("广告推荐", True, (500, 800))]
        elsewhere = [("广告推荐", True, (500, 700))]
        p = self.phone([rows, rows] + [elsewhere] * 10)
        p.focus = Mock(side_effect=["app/settings", "app/settings"] + ["other/app"] * 10)
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
        p.tree = Mock(side_effect=[plain, plain] + [grey] * 10)
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
        p.tree = Mock(return_value=grey)
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
        p.tree = Mock(side_effect=[plain] + [grey] * 10)   # 首屏计划后（首击起）就只剩灰树
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
        p.tree = Mock(side_effect=[plain, plain] + [grey] * 10)
        with patch.object(fast.time, "sleep"):
            done = p.off(page="页")
        self.assertEqual(done, 0)
        self.assertEqual([c.args for c in p.click.call_args_list], [(500, 800)])  # 灰行一次也不补点
        p.say.assert_any_call("  · 被上级开关禁用（开关是灰的），未改动 营销通知")
        self.assertNotIn("  ✗ 关不掉 营销通知", [c.args[0] for c in p.say.call_args_list])

    def test_the_same_grey_row_is_reported_once_across_screens(self):
        rows = [("摇一摇广告", True, (500, 800))]
        p = self.phone([rows] * 5)
        p.scroll_more = Mock(side_effect=[True, False])
        p.tree = Mock(return_value=ET.fromstring(
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
        p.focus = Mock(side_effect=["app/settings", "other/app", "other/app"])
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
        p.scroll_more = Mock(side_effect=[True, False])
        done = self.run_off(p, page="页")
        self.assertEqual((done, p.switches.call_count), (0, 3))
        p.click.assert_not_called()
        p.say.assert_any_call("  · 页：核对 2 项，调整 0 项")

    def test_kept_accumulates_across_screens_in_safe_mode(self):
        first = [("个性化推荐", True, (500, 800))]
        second = [("猜你喜欢", True, (500, 1000))]
        p = self.phone([first, first, second])
        p.safe_mode = True
        p.scroll_more = Mock(side_effect=[True, False])
        self.run_off(p, page="页")
        p.click.assert_not_called()
        p.say.assert_any_call("  · 页：安全模式不做整页全关，本页 2 个开关未改动，需要时请按清单手动关")


class MissedLedgerTests(unittest.TestCase):
    """#788：拨不动的开关除了那行 ✗，还要记进引擎台账（形状与 `Phone.changed` 对齐）。"""

    def phone(self, reads, size=(1080, 2340)):
        p = phone_stub("S")
        p.W, p.H = size
        p.tree = Mock(return_value=ET.fromstring("<hierarchy/>"))
        p.switches = Mock(side_effect=reads)
        p.switch_rows = Mock(return_value=[])
        p.focus = Mock(return_value="app/settings")
        p.click = Mock()
        p.confirm = Mock(return_value=None)
        p.scroll_more = Mock(return_value=False)
        p.say = Mock()
        p.back = Mock()
        return p

    def run_off(self, p, **kwargs):
        with patch.object(fast, "time", Clock()):        # 假钟的 sleep 只推进读数，不真等
            done = p.off(**kwargs)
        p.tree.assert_called()
        p.switches.assert_any_call(p.tree.return_value)   # 主循环真的带着这一棵树读屏
        return done

    def test_a_switch_that_will_not_budge_lands_in_the_ledger(self):
        rows = [("广告推荐", True, (500, 800))]
        p = self.phone([])
        p.switches = Mock(return_value=rows)       # 一直拨不动：读几次都是开着
        done = self.run_off(p, page="页")
        self.assertEqual({c.args for c in p.click.call_args_list}, {(500, 800)})   # 首击 + 两轮补点都点它
        self.assertEqual((done, p.changed), (0, []))
        self.assertEqual(p.missed, [("页", "广告推荐")])

    def test_the_same_switch_across_screens_is_counted_once(self):
        """滚动后同一行还留在屏带里：每屏都会重新成为目标，但不能记成两个（#788 复核）。"""
        rows = [("广告推荐", True, (500, 800))]
        p = self.phone([])
        p.switches = Mock(return_value=rows)
        p.scroll_more = Mock(side_effect=[True, False])
        self.run_off(p, page="页")
        self.assertEqual(p.missed, [("页", "广告推荐")])

    def test_a_later_pass_that_gets_it_clears_the_ledger_entry(self):
        """上一次没拨动、这一次拨到了：旧条目要撤销，否则结果页会报一次假失败。"""
        rows = [("广告推荐", True, (500, 800))]
        after = [("广告推荐", False, (500, 800))]
        clicked = []
        p = self.phone([])
        p.click = Mock(side_effect=lambda *a: clicked.append(a))
        p.switches = Mock(side_effect=lambda *a: after if clicked else rows)
        p.missed = [("页", "广告推荐")]            # 上一次 off() 留下的
        done = self.run_off(p, page="页")
        self.assertEqual((done, p.changed), (1, [("页", "广告推荐")]))
        self.assertEqual(p.missed, [])

    def test_a_second_pass_that_finds_it_closed_clears_the_ledger_entry(self):
        """同页再调一次 off()：这次它已关着、不是目标，靠拨动计划的 checked 撤销旧条目。"""
        rows = [("广告推荐", True, (500, 800))]
        after = [("广告推荐", False, (500, 800))]
        p = self.phone([])
        p.switches = Mock(return_value=rows)
        self.run_off(p, page="页")
        self.assertEqual(p.missed, [("页", "广告推荐")])
        p.switches = Mock(return_value=after)
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
        p.click = Mock(side_effect=lambda *a: clicked.append(a))
        p.switches = Mock(side_effect=lambda *a: after if clicked else rows)
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
            path = Path(tmp, "recipe.py")
            path.write_text('p.off(page="设置·广告服务")\n', encoding="utf-8")
            scope, _ = load_recipe(p, path)
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
            path = Path(tmp, "recipe.py")
            path.write_text('p.off(page="设置·广告服务")\n', encoding="utf-8")
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
        with patch.object(fast, "connect", side_effect=gone):
            with self.assertRaises(RuntimeError) as caught:
                fast.Phone("S", log=False)
        self.assertIn("那块屏已经关了", str(caught.exception))
        self.assertNotIn("读屏服务（UiAutomation）启动失败", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
