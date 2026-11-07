"""「开关所属的那一行」的唯一定义：结构定界 + 几何分带。不用手机。

页面 XML 直接构造，不借别的测试文件的常量；断言值取自 XML 里写死的坐标，
不是把实现的算法重算一遍。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import fast
import row


def page(xml):
    root = ET.fromstring(xml)
    nodes = list(root.iter())
    return root, {c: p for p in nodes for c in p}


def on_screen(w=1080, h=2340):
    def check(n):
        if n.get("visible-to-user") == "false":
            return False
        l, t, r, b = row.bounds(n)
        return r > l and b > t and 0 <= (l + r) // 2 < w and 0 <= (t + b) // 2 < h
    return check


def text_node(root, text):
    for n in root.iter("node"):
        if (n.get("text") or "") == text:
            return n
    raise AssertionError(f"页面里没有 {text!r}")


def switch_at(root, top):
    for n in root.iter("node"):
        if n.get("checkable") == "true" and row.bounds(n)[1] == top:
            return n
    raise AssertionError(f"页面里没有上沿 {top} 的开关")


# 平铺列表：行是 ListView 的直接子项，本身不可点（点击由列表处理）
LIST_ROWS = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,900]">
    <node bounds="[0,320][1080,430]">
      <node text="每次联网时通知" bounds="[60,350][600,400]"/>
      <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,350][1080,400]"/>
    </node>
  </node>
</node></hierarchy>'''


NESTED = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node clickable="true" bounds="[0,400][1080,560]">
    <node bounds="[0,410][1080,550]">
      <node bounds="[0,420][1080,540]">
        <node text="边下边玩" bounds="[60,430][700,490]"/>
      </node>
    </node>
  </node>
</node></hierarchy>'''


class StructureTests(unittest.TestCase):
    def test_list_row_stops_at_the_item_even_when_it_is_not_clickable(self):
        # 以前只认可点 / 可勾选的祖先，这种行会被一路穿过，行内开关就看不见了
        root, parents = page(LIST_ROWS)
        line = row.line(text_node(root, "每次联网时通知"), parents)
        self.assertEqual(row.bounds(line), (0, 320, 1080, 430))

    def test_depth_cap_stops_before_a_far_away_clickable_ancestor(self):
        root, parents = page(NESTED)
        t = text_node(root, "边下边玩")
        self.assertIsNone(row.line(t, parents, max_depth=3))
        self.assertEqual(row.bounds(row.line(t, parents)), (0, 400, 1080, 560))


MIXED_BOXES = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node clickable="true" checkable="true" bounds="[0,300][1080,900]">
    <node class="android.widget.RadioButton" checkable="true" bounds="[60,320][600,380]"/>
    <node class="android.widget.Switch" checkable="true" bounds="[900,320][1000,380]"/>
    <node class="android.widget.Switch" checkable="true" bounds="[2160,500][2240,546]"/>
  </node>
</node></hierarchy>'''


class BoxesTests(unittest.TestCase):
    def test_only_real_switches_on_screen_and_never_the_container_itself(self):
        root, _ = page(MIXED_BOXES)
        container = root[0][0]
        found = row.switches_in(container, on_screen())
        self.assertEqual([row.bounds(n) for n in found], [(900, 320, 1000, 380)])

    def test_control_is_the_innermost_switch_not_the_container_holding_it(self):
        # 卡片中心落在标题与开关之间的空白里，点它不生效（#403）
        root, _ = page(CARD)
        row_line = root[0][0][0][0]
        self.assertEqual(row.bounds(row.control(row_line, on_screen())), (900, 600, 1000, 680))

    def test_a_card_with_several_switches_stays_the_control(self):
        # 同一层两个开关：认不出点哪个，退回卡片，由调用方按行归属决定
        root, _ = page(FLAT_CARD)
        card = root[0][0][0]
        self.assertIs(row.control(card, on_screen()), card)


class DisabledAtTests(unittest.TestCase):
    """灰态判定（#333）：整卡禁用、内层开关禁用、不可见副本都要分清。"""

    def test_a_greyed_switch_is_disabled(self):
        root, _ = page('''<hierarchy>
          <node class="android.widget.Switch" checkable="true" checked="true" enabled="false" bounds="[900,700][1000,800]"/>
        </hierarchy>''')
        self.assertTrue(row.disabled_at(root, (950, 750)))

    def test_a_disabled_card_makes_its_inner_switch_grey(self):
        # 卡片整体 checkable 且 enabled=false，内层 Switch 不带 enabled
        root, _ = page('''<hierarchy>
          <node class="android.widget.LinearLayout" checkable="true" clickable="true" enabled="false" bounds="[0,600][1080,860]">
            <node text="摇一摇广告" bounds="[60,620][600,700]"/>
            <node class="android.widget.Switch" checked="true" bounds="[900,620][1000,700]"/>
          </node>
        </hierarchy>''')
        self.assertTrue(row.disabled_at(root, (950, 660)))

    def test_a_disabled_inner_switch_under_an_enabled_card_is_grey(self):
        # 卡片可勾选但不带 enabled，灰态落在内层 Switch 上
        root, _ = page('''<hierarchy>
          <node class="android.widget.LinearLayout" checkable="true" clickable="true" bounds="[0,600][1080,860]">
            <node text="摇一摇广告" bounds="[60,620][600,700]"/>
            <node class="android.widget.Switch" checked="true" enabled="false" bounds="[900,620][1000,700]"/>
          </node>
        </hierarchy>''')
        self.assertTrue(row.disabled_at(root, (950, 660)))

    def test_a_hidden_copy_does_not_make_a_normal_switch_grey(self):
        # 折叠屏合上时 dump 里留着内屏那份（Issue #2）：它盖住落点也不算
        root, _ = page('''<hierarchy>
          <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,700][1000,800]"/>
          <node class="android.widget.Switch" checkable="true" enabled="false" visible-to-user="false" bounds="[880,680][1020,820]"/>
        </hierarchy>''')
        self.assertFalse(row.disabled_at(root, (950, 750)))

    def test_a_point_off_the_switch_is_not_grey(self):
        root, _ = page('''<hierarchy>
          <node class="android.widget.Switch" checkable="true" enabled="false" bounds="[900,700][1000,800]"/>
        </hierarchy>''')
        self.assertFalse(row.disabled_at(root, (100, 100)))


class DedupeTests(unittest.TestCase):
    """dedupe 直接吃 bounds：同一水平带里的两个候选什么时候算一行、什么时候算两列。"""

    def test_a_whole_row_and_its_inline_switch_collapse_to_the_rightmost(self):
        rows = row.dedupe([("营销通知", True, (40, 500, 1040, 540)),
                           ("营销通知", True, (940, 500, 1040, 540))])
        self.assertEqual(rows, [("营销通知", True, (940, 500, 1040, 540))])

    def test_the_band_is_thirty_pixels(self):
        # 旧实现里写死的 30px 搬进常量：边界两侧各放一组，改成别的数就要红
        same = row.dedupe([("甲", True, (900, 300, 1000, 340)), ("甲", True, (900, 329, 1000, 369))])
        apart = row.dedupe([("甲", True, (900, 300, 1000, 340)), ("甲", True, (900, 331, 1000, 371))])
        self.assertEqual(len(same), 1)
        self.assertEqual(len(apart), 2)

    def test_two_columns_keep_both_when_each_has_its_own_title(self):
        rows = row.dedupe([("微博热搜榜", True, (54, 234, 525, 526)),
                           ("千问热议", False, (555, 234, 1026, 526))])
        self.assertEqual([t for t, _, _ in rows], ["微博热搜榜", "千问热议"])

    def test_a_column_without_a_title_is_still_merged_away(self):
        rows = row.dedupe([("", True, (54, 234, 525, 526)),
                           ("千问热议", False, (555, 234, 1026, 526))])
        self.assertEqual(rows, [("千问热议", False, (555, 234, 1026, 526))])


# 华为 / 旧版荣耀：几个渠道排在同一张卡片里，卡片是列表的直接子项，行本身不可点
CARD = '''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
  <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,300][1080,2200]">
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

# 标题和开关直接并排放在卡片里：看不出哪个开关属于哪一行
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


class OwnTests(unittest.TestCase):
    def test_each_channel_inside_a_card_gets_its_own_row_and_switch(self):
        root, parents = page(CARD)
        on = on_screen()
        for title, row_bounds, switch_bounds in (
                ("营销通知", (40, 520, 1040, 760), (900, 600, 1000, 680)),
                ("订单通知", (40, 760, 1040, 1000), (900, 840, 1000, 920))):
            with self.subTest(title=title):
                line, boxes = row.own(text_node(root, title), parents, on)
                self.assertEqual(row.bounds(line), row_bounds)
                self.assertEqual([row.bounds(b) for b in boxes], [switch_bounds])

    def test_flat_card_reports_the_whole_card_so_the_caller_can_refuse(self):
        root, parents = page(FLAT_CARD)
        line, boxes = row.own(text_node(root, "营销通知"), parents, on_screen())
        self.assertEqual(row.bounds(line), (40, 520, 1040, 1000))
        self.assertEqual(len(boxes), 2)


# 平铺列表：开关和上一行的文字在同一个高容器里，第一段文字不是本行的标题
TALL_LIST = '''<hierarchy><node bounds="[0,300][1168,900]">
  <node bounds="[0,320][1168,430]">
    <node text="每次联网时通知" bounds="[60,350][600,400]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,350][1080,400]"/>
  </node>
  <node text="自动更新" bounds="[60,570][600,620]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,570][1080,620]"/>
</node></hierarchy>'''


# 一行里「标题 + 长说明」：说明离得更近，但标题才是最上面那段
ONE_ROW = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node bounds="[0,680][1080,880]">
    <node text="个性化广告推荐" bounds="[60,700][700,750]"/>
    <node text="个性化广告服务会根据您的喜好进行精准匹配" bounds="[60,755][900,860]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,760][1080,810]"/>
  </node>
</node></hierarchy>'''


# 平铺列表（开关是列表的直接子项）里本行的标题在开关上方，下一行的文字在下方：
# 「竖直最近」要按上 / 下边界算，不能让下一行借走标题（#608 拆 title_label 时踩过）
TALL_NEIGHBOUR = '''<hierarchy><node bounds="[0,300][1080,2340]">
  <node text="本行标题" bounds="[60,960][600,1000]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" content-desc="本行开关" bounds="[990,1000][1080,1080]"/>
  <node text="下一行的说明" bounds="[60,1340][600,1380]"/>
</node></hierarchy>'''

# 同上，但唯一的文字在下方远处：够不着就不是本行标题，退回开关自己的标签
TALL_ONLY_BELOW = '''<hierarchy><node bounds="[0,300][1080,2340]">
  <node class="android.widget.Switch" checkable="true" checked="true" content-desc="本行开关" bounds="[990,1000][1080,1080]"/>
  <node text="下一行的说明" bounds="[60,1400][600,1440]"/>
</node></hierarchy>'''


# 开关状态词写在标题上面：它不是标题
STATE_ABOVE = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node bounds="[0,400][1080,560]">
    <node text="已开启" bounds="[60,410][400,460]"/>
    <node text="内容推广" bounds="[60,480][600,530]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,440][1080,520]"/>
  </node>
</node></hierarchy>'''

# 行里只有开关自己：标题只能取它的无障碍标签
LABEL_ONLY = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node class="android.widget.Switch" checkable="true" checked="true" content-desc="内容推广&#10;推荐相关内容" bounds="[900,400][1050,500]"/>
</node></hierarchy>'''


class TitleTests(unittest.TestCase):
    def test_tall_container_takes_the_nearest_text_not_the_top_one(self):
        # Issue #2：取最上面那段会把上一行的「每次联网时通知」认成本行标题
        root, parents = page(TALL_LIST)
        self.assertEqual(row.title_of(switch_at(root, 570), parents, on_screen(1168, 1712), 1712),
                         "自动更新")

    def test_tall_container_does_not_borrow_the_title_of_the_row_below(self):
        root, parents = page(TALL_NEIGHBOUR)
        self.assertEqual(row.title_of(switch_at(root, 1000), parents, on_screen(), 2340),
                         "本行标题")

    def test_a_text_too_far_below_is_not_the_title(self):
        root, parents = page(TALL_ONLY_BELOW)
        self.assertEqual(row.title_of(switch_at(root, 1000), parents, on_screen(), 2340),
                         "本行开关")

    def test_short_container_takes_the_top_text_even_when_the_description_is_closer(self):
        root, parents = page(ONE_ROW)
        self.assertEqual(row.title_of(switch_at(root, 760), parents, on_screen(), 2340),
                         "个性化广告推荐")

    def test_state_word_is_never_the_title(self):
        root, parents = page(STATE_ABOVE)
        self.assertEqual(row.title_of(switch_at(root, 440), parents, on_screen(), 2340),
                         "内容推广")

    def test_switch_own_accessibility_label_is_the_title_when_the_row_has_no_text(self):
        root, parents = page(LABEL_ONLY)
        self.assertEqual(row.title_of(switch_at(root, 400), parents, on_screen(), 2340),
                         "内容推广")


# 两个开关并排躺在同一个高容器里，各自带无障碍标签：不能互借对方的标签当标题
SIBLINGS = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node bounds="[0,300][1080,900]">
    <node text="设置" bounds="[60,310][400,360]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" content-desc="内容推广" bounds="[900,440][1000,520]"/>
    <node class="android.widget.Switch" checkable="true" checked="true" content-desc="天气预警提醒" bounds="[900,560][1000,640]"/>
  </node>
</node></hierarchy>'''


class SiblingTests(unittest.TestCase):
    def test_switch_with_its_own_label_does_not_borrow_the_neighbour_title(self):
        root, parents = page(SIBLINGS)
        on = on_screen()
        self.assertEqual(row.title_of(switch_at(root, 440), parents, on, 2340), "内容推广")
        self.assertEqual(row.title_of(switch_at(root, 560), parents, on, 2340), "天气预警提醒")


class SwitchRowTests(unittest.TestCase):
    def test_switch_inside_a_non_clickable_list_item_is_a_switch_row(self):
        # 这次唯一的行为变化：以前只认可点 / 可勾选的祖先，这种行判不出来，
        # tap 会去点开关的说明文字，等于拨了开关（#247）
        root, parents = page(LIST_ROWS)
        self.assertTrue(fast.switch_row(text_node(root, "每次联网时通知"), parents))

    def test_plain_navigation_row_is_not_a_switch_row(self):
        root, parents = page(NESTED)
        self.assertFalse(fast.switch_row(text_node(root, "边下边玩"), parents))


class PathTests(unittest.TestCase):
    def test_path_carries_class_flags_and_switch_count_up_to_the_scroll_container(self):
        # 上报里那一行「结构 node#0 < LinearLayout#2 < ListView:s#2」的数据来源
        root, parents = page(FLAT_CARD)
        self.assertEqual(row.path(text_node(root, "营销通知"), parents),
                         [("node", "", 0),
                          ("android.widget.LinearLayout", "", 2),
                          ("android.widget.ListView", "s", 2)])


if __name__ == "__main__":
    unittest.main()
