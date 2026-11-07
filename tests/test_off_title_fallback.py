"""#608：只认行标题的页面（Google 广告设置页）点开关本体不动，`off()` 回退到点这一行的标题。

设备无关：读屏与点击都走假时钟。`TitleOnlyDevice` 按报道的页面记账——点开关圆点不弹框也不改状态，
点标题才拨；保护类开关点标题后先弹确认框，点「确定」才生效。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))
import fast
from fixtures import Clock, fake_phone, install_clock, load_tool, phone_stub

SIZE = (1080, 2340)
ROWS = (("猜你喜欢", False), ("限制广告跟踪", True), ("应用推荐", False))
TOP0, ROW_PITCH, ROW_DY = 300, 240, 80  # 行顶边 300 / 540 / 780，中心都在可点带内
TITLE_X, SWITCH_X = 390, 950
CONFIRM_XY = (590, 1950)                # 「确定」按钮 [420,1850][760,2050] 的中心
FOCUS = "com.google.android.gms/.adid.settings.AdsSettingsActivity"
DETAIL = "com.google.android.gms/.adid.settings.AdsDetailActivity"


def tops_of(count):
    return [TOP0 + ROW_PITCH * i for i in range(count)]


def page(titles, states, tops, dialog=False):
    rows = "".join(
        f'<node bounds="[40,{top}][1040,{top + 160}]">'
        f'<node text="{title}" bounds="[80,{top + 40}][700,{top + 120}]"/>'
        f'<node class="android.widget.Switch" checkable="true" checked="{str(on).lower()}"'
        f' bounds="[900,{top + 40}][1000,{top + 120}]"/></node>'
        for title, on, top in zip(titles, states, tops))
    overlay = ('<node class="android.widget.Button" content-desc="取消" clickable="true" bounds="[80,1850][420,2050]"/>'
               '<node class="android.widget.Button" content-desc="确定" clickable="true" bounds="[420,1850][760,2050]"/>'
               ) if dialog else ""
    return (f'<hierarchy rotation="0"><node package="com.google.android.gms" bounds="[0,0][1080,2340]">'
            f'{rows}{overlay}</node></hierarchy>')


class TitleOnlyDevice:
    """只认行标题的页面：点开关本体没反应，点标题才拨。needs_confirm 里的行先弹确认框。"""

    def __init__(self, clock, states, needs_confirm=(), navigate=None):
        self.clock, self.states = clock, list(states)
        self.titles = [title for title, _ in ROWS]
        self.needs_confirm, self.navigate = set(needs_confirm), navigate
        self.dialog = None                     # 待确认的行号
        self.focus = FOCUS
        self.body_clicks = self.title_clicks = self.confirmed = 0

    @property
    def tops(self):
        return tops_of(len(self.titles))

    def dump_hierarchy(self):
        self.clock.read()
        return page(self.titles, self.states, self.tops, dialog=self.dialog is not None)

    def window_size(self):
        return SIZE

    def shell(self, command, timeout=60):
        from types import SimpleNamespace
        return SimpleNamespace(output="", exit_code=0)

    def screenshot(self):
        return None

    def click(self, x, y):
        self.clock.click()
        if self.dialog is not None:
            if (x, y) == CONFIRM_XY:
                self.states[self.dialog] = not self.states[self.dialog]
                self.dialog, self.confirmed = None, self.confirmed + 1
            return
        for i, top in enumerate(self.tops):
            if (x, y) == (SWITCH_X, top + ROW_DY):
                self.body_clicks += 1          # 点了没反应：这一页只认标题
                return
            if (x, y) == (TITLE_X, top + ROW_DY):
                self.title_clicks += 1
                if self.navigate:
                    self.focus = self.navigate
                elif self.titles[i] in self.needs_confirm:
                    self.dialog = i
                else:
                    self.states[i] = not self.states[i]
                return


class ShrinkingDevice(TitleOnlyDevice):
    """标题一拨这一行就从列表消失、下面的行整体上移（#480 的排版，只是落点成了标题）。"""

    def __init__(self, clock, states, removes=()):
        super().__init__(clock, states)
        self.removes = set(removes)

    def click(self, x, y):
        before = self.title_clicks
        super().click(x, y)
        if self.title_clicks == before:        # 这一下没点到标题
            return
        for i, top in enumerate(self.tops):
            if (x, y) == (TITLE_X, top + ROW_DY) and self.titles[i] in self.removes:
                self.titles.pop(i)
                self.states.pop(i)
                return


class TitleFallbackTests(unittest.TestCase):
    def setUp(self):
        load_tool()
        self.addCleanup(setattr, fast, "time", fast.time)      # 假时钟装进模块后要还原
        self.clock = Clock(read_cost=0.0)
        install_clock(fast, self.clock)
        self.clicks, self.backs = [], []

    def phone(self, device):
        def click(x, y):
            self.clicks.append((x, y))
            device.click(x, y)

        def back(*a, **k):
            self.backs.append("back")
            self.clock.click()
        p = fake_phone(clock=self.clock, size=SIZE, click=click, d=device, back=back, say=Mock())
        p.focus = lambda: device.focus        # focus 这条时间轴由设备自己管：标题可能点进详情页
        return p

    def test_a_body_that_does_nothing_falls_back_to_the_row_title(self):
        """点开关圆点状态不变、点标题才拨：off() 最终关掉它，并照旧回读确认。"""
        device = TitleOnlyDevice(self.clock, [True, True, False])
        p = self.phone(device)
        done = p.off(page="页", only=["猜你喜欢"])
        self.assertEqual((done, p.changed), (1, [("页", "猜你喜欢")]))
        self.assertEqual(device.title_clicks, 1)
        self.assertEqual(device.body_clicks, 3)      # 首击 + 两轮补点之后才回退，不是首击就点标题
        self.assertIn((TITLE_X, tops_of(3)[0] + ROW_DY), self.clicks)
        self.assertNotIn((TITLE_X, tops_of(3)[1] + ROW_DY), self.clicks)   # 另一行不动

    def test_the_fallback_also_opens_a_protection_switch_and_confirms_it(self):
        """保护类开关（want=True）走同一条回退：点标题 → 弹确认框 → 点「确定」→ 回读为开。"""
        device = TitleOnlyDevice(self.clock, [False, False, False], needs_confirm=("限制广告跟踪",))
        p = self.phone(device)
        done = p.off(page="页", only=["猜你喜欢"])
        self.assertEqual((done, p.changed), (1, [("页", "限制广告跟踪")]))
        self.assertEqual((device.title_clicks, device.confirmed), (1, 1))
        self.assertTrue(device.states[1])

    def test_a_page_whose_body_click_works_never_clicks_the_title(self):
        """现有行为不变：点本体就生效的页面，一次标题都不点（否则会点进详情页）。"""
        class BodyDevice(TitleOnlyDevice):
            def click(self, x, y):
                self.clock.click()
                for i, top in enumerate(self.tops):
                    if (x, y) == (SWITCH_X, top + ROW_DY):
                        self.body_clicks += 1
                        self.states[i] = not self.states[i]
                        return
                self.title_clicks += 1

        device = BodyDevice(self.clock, [True, True, False])
        p = self.phone(device)
        done = p.off(page="页", only=["猜你喜欢"])
        self.assertEqual(done, 1)
        self.assertEqual(device.title_clicks, 0)

    def test_a_row_that_disappears_does_not_hand_its_coordinates_to_the_row_below(self):
        """点标题拨掉一行、下面的行整体上移（#480 的排版）：第二下要按新树重取，
        不能复用上移前的坐标——那会落到上移过来的邻行标题上，把不在名单里的开关打开。"""
        device = ShrinkingDevice(self.clock, [True, True, True], removes=("猜你喜欢",))
        p = self.phone(device)
        done = p.off(page="页", only=["猜你喜欢", "应用推荐"])
        self.assertEqual(done, 2)
        self.assertEqual(device.states, [True, False])           # 只剩两行：应用推荐关了、保护开关没动
        self.assertIn((TITLE_X, tops_of(3)[1] + ROW_DY), self.clicks)      # 第二下点在移上来的新位置
        self.assertNotIn((TITLE_X, tops_of(3)[2] + ROW_DY), self.clicks)   # 不是上移前的旧坐标

    def test_a_title_that_takes_the_page_away_is_backed_out_and_reported(self):
        """标题不是开关：有的页面点它进详情页。退回来、不把这一行记成关掉了。"""
        device = TitleOnlyDevice(self.clock, [True, True, False], navigate=DETAIL)
        p = self.phone(device)
        done = p.off(page="页", only=["猜你喜欢"])
        self.assertEqual((done, p.changed), (0, []))
        self.assertEqual(len(self.backs), 1)
        self.assertTrue(any("  ✗ 关不掉 猜你喜欢" in c.args[0] for c in p.say.call_args_list))


class PickTitleRowsTests(unittest.TestCase):
    TARGETS = (("甲", (500, 800), False),)

    def test_a_row_without_an_independent_title_is_skipped(self):
        """标题取自开关自己的标签时没有可点的标题：点它等于再点一次本体。"""
        rows = [("甲", True, (500, 800), None)]
        self.assertEqual(fast.pick_title_rows(self.TARGETS, rows, {"甲"}, lambda xy: False), [])

    def test_the_twin_still_in_the_wrong_state_lends_its_title(self):
        """同名两行（双列）：按状态挑还开着的那行，落点用它自己的标题（#403 的同一套挑选）。"""
        rows = [("甲", False, (500, 800), (100, 800)), ("甲", True, (500, 1000), (100, 1000))]
        self.assertEqual(fast.pick_title_rows(self.TARGETS, rows, {"甲"}, lambda xy: False),
                         [("甲", (100, 1000))])

    def test_a_grey_row_is_not_clicked(self):
        rows = [("甲", True, (500, 800), (100, 800))]
        self.assertEqual(fast.pick_title_rows(self.TARGETS, rows, {"甲"}, lambda xy: True), [])


class SwitchRowsTests(unittest.TestCase):
    PAGE = ('<hierarchy rotation="0">'
            '<node bounds="[40,300][1040,460]">'
            '<node text="营销通知" bounds="[80,340][700,420]"/>'
            '<node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,340][1000,420]"/>'
            '</node>'
            '<node bounds="[40,540][1040,700]">'
            '<node class="android.widget.Switch" checkable="true" checked="false" content-desc="显示通知"'
            ' bounds="[900,580][1000,660]"/>'
            '</node></hierarchy>')

    def rows(self):
        load_tool()
        p = phone_stub("S")
        p.W, p.H = SIZE
        return p, p.switch_rows(ET.fromstring(self.PAGE)), ET.fromstring(self.PAGE)

    def test_the_title_hit_is_the_title_text_and_is_empty_without_one(self):
        p, rows, root = self.rows()
        self.assertEqual(rows[0][0], "营销通知")
        self.assertEqual(rows[0][3], (TITLE_X, 380))
        self.assertIsNone(rows[1][3])                 # 标题取自开关自己的标签：没有独立标题
        self.assertEqual(p.switches(root), [(t, on, xy) for t, on, xy, _ in rows])


if __name__ == "__main__":
    unittest.main()
