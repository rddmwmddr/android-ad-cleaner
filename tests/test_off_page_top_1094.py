"""长列表页上 `off()` 必须自己从页顶开始（#1094）。

`fast.py scan` 循环翻到列表底部、结束时不复位；紧接着 `off()` 从当前屏开始、只向下翻，
219 个开关的页面只关掉底部那一段，没被看见的行既不在 targets 里也不进 missed，
于是打一行「关了 N 个」、退出码 0。现成的 `top()` 也不能直接用：固定上滑 4 次翻不回页顶。

两个接缝都在门面上：`p.off()` 的语义是「这一页该关的都关掉」，页顶是它自己的前提；
`p.top()` 的终止条件是「这一屏没有新文字」，与 `scroll_more()` 对称，不写死次数。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from fixtures import SIZES, Clock, clocked, phone_stub  # noqa: E402

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
        for i, row in enumerate(self.window()):
            top = 250 + i * self.row_h
            if top <= y < top + self.row_h and 40 <= x <= 1050:
                row[1] = False
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
