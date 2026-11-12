"""「开关所属的那一行」的唯一定义：结构定界 + 几何分带 + 同一水平带的去重。不用真机。

大部分页面 XML 在本文件里直接构造，断言值取自 XML 写死的坐标而不是重算实现；
双列与自绘开关那两组借 `fixtures.SIZES` 的两种屏尺寸与 `all_pages()` 的已有页面样本。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import chan_fast
import fast
import fixtures
import row
from fixtures import fake_phone, phone_stub


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


# ---------- 按名字筛候选行 ----------
# 认行的前置筛选：名字完全相等、不在顶部标题带内、不是开关本体

NAME = "营销通知"
APP_PAGE = '''<hierarchy><node package="com.android.settings" bounds="[0,0][1080,2340]">
  <node text="示例应用" bounds="[60,80][600,140]"/>
  <node text="营销通知" bounds="[60,900][600,960]"/>
  <node class="android.widget.Switch" checkable="true" content-desc="营销通知" checked="true" bounds="[990,900][1080,960]"/>
</node></hierarchy>'''

# 应用名和渠道名相同：顶部那一个是标题，不是列表行
TITLE_ONLY = '''<hierarchy><node package="com.android.settings" bounds="[0,0][1080,2340]">
  <node class="android.widget.TextView" text="营销通知" bounds="[60,80][600,140]"/>
</node></hierarchy>'''

# 顶部带边界两侧各放一个：0.22 × 2340 = 514.8
BAND_EDGE = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node text="营销通知" bounds="[60,514][600,560]"/>
  <node text="营销通知" bounds="[60,515][600,561]"/>
</node></hierarchy>'''

# 分组名和渠道名相同，各带一个开关：两条都得算候选，交给调用方取舍
TWO_ROWS = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node text="营销通知" bounds="[60,900][600,960]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,900][1080,960]"/>
  <node text="营销通知" bounds="[60,1300][600,1360]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" bounds="[990,1300][1080,1360]"/>
</node></hierarchy>'''


# 同一个控件在 dump 里吐出两次（华为 HarmonyOS 4）：只算一个候选
DUPLICATE = '''<hierarchy><node bounds="[0,0][1080,2340]">
  <node text="营销通知" bounds="[60,900][600,960]"/>
  <node text="营销通知" bounds="[60,900][600,960]"/>
</node></hierarchy>'''

# 同名文字挂在 com.android.systemui 上：默认不算（vivo 的通知页由 systemui_text 放行）
SYSTEMUI_NAME = '''<hierarchy><node package="com.android.settings" bounds="[0,0][1080,2340]">
  <node package="com.android.systemui" text="营销通知" bounds="[60,900][600,960]"/>
  <node text="营销通知" bounds="[60,1300][600,1360]"/>
</node></hierarchy>'''


class NamedNodesTests(unittest.TestCase):
    """`row.named_nodes()`：按名字筛候选行，只出结构、不认识渠道。"""

    def test_a_name_only_in_the_top_band_is_the_page_title(self):
        root, parents = page(TITLE_ONLY)
        self.assertEqual(row.named_nodes(root, parents, on_screen(), NAME, 2340), [])

    def test_the_band_edge_is_the_top_22_percent_of_the_screen(self):
        root, parents = page(BAND_EDGE)
        found = row.named_nodes(root, parents, on_screen(), NAME, 2340)
        self.assertEqual([b for _, b, _ in found], [(60, 515, 600, 561)])

    def test_a_name_in_the_list_area_is_the_only_candidate_on_that_row(self):
        # 开关的 content-desc 常常也是渠道名：checkable 的那一个不算，只剩标题节点
        root, parents = page(APP_PAGE)
        found = row.named_nodes(root, parents, on_screen(), NAME, 2340)
        self.assertEqual(found, [(NAME, (60, 900, 600, 960), text_node(root, NAME))])

    def test_two_rows_with_the_same_name_stay_two_candidates(self):
        root, parents = page(TWO_ROWS)
        found = row.named_nodes(root, parents, on_screen(), NAME, 2340)
        self.assertEqual([b[1] for _, b, _ in found], [900, 1300])

    def test_the_same_control_twice_in_the_dump_is_one_candidate(self):
        root, parents = page(DUPLICATE)
        self.assertEqual(len(row.named_nodes(root, parents, on_screen(), NAME, 2340)), 1)

    def test_whitespace_around_the_page_text_still_matches(self):
        root, parents = page('''<hierarchy><node bounds="[0,0][1080,2340]">
          <node text="  营销通知  " bounds="[60,900][600,960]"/>
        </node></hierarchy>''')
        found = row.named_nodes(root, parents, on_screen(), NAME, 2340)
        self.assertEqual([t for t, _, _ in found], [NAME])

    def test_a_copy_on_the_other_screen_is_not_a_candidate(self):
        # 折叠屏合上时 dump 里留着内屏那份：标了不可见的、坐标落在屏外的都不算
        root, parents = page('''<hierarchy><node bounds="[0,0][1080,2340]">
          <node text="营销通知" visible-to-user="false" bounds="[60,900][600,960]"/>
          <node text="营销通知" bounds="[60,2500][600,2560]"/>
        </node></hierarchy>''')
        self.assertEqual(row.named_nodes(root, parents, on_screen(), NAME, 2340), [])

    def test_systemui_text_is_off_unless_the_page_asks_for_it(self):
        root, parents = page(SYSTEMUI_NAME)
        self.assertEqual([b[1] for _, b, _ in row.named_nodes(root, parents, on_screen(), NAME, 2340)],
                         [1300])
        both = row.named_nodes(root, parents, on_screen(), NAME, 2340, systemui_text=True)
        self.assertEqual([b[1] for _, b, _ in both], [900, 1300])


def real_candidates(method, xml, focus, **kwargs):
    """跑一次真实认行，录下它交给 `own()` 的候选节点，再与 `named_nodes()` 在同一样本上的结果并排返回。

    `own()` 换成录音桩：真实方法把每个过筛的节点交过来，认行本身（行高上限、行内开关数、
    同名取舍）这一段停止。两处调用点自身已改成调 `named_nodes()`，这里比的是调用点有没有把
    候选集与 `systemui_text` 原样转发下去；`named_nodes()` 自己的三条筛选由 `NamedNodesTests` 直接守。"""
    root = ET.fromstring(xml)
    parents = {c: n for n in root.iter() for c in n}
    p = phone_stub("test", d=Mock(), W=1080, H=2340)
    p.screen.focus = Mock(return_value=focus)
    p.screen.tree = Mock(return_value=root)
    p.screen.scroll_more = Mock(return_value=False)
    p.locked = Mock(return_value=False)
    seen = []

    def recording(node, *_args, **_kwargs):
        seen.append(node)
        return None, []

    with patch.object(chan_fast, "own", recording):
        method(chan_fast.ChannelPage(p, NAME, pk="com.example.app"))
    want = [n for _, _, n in row.named_nodes(root, parents, p.on_screen, NAME, p.H, **kwargs)]
    return seen, want


APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
VIVO_SYSTEMUI_FOCUS = ("com.android.systemui/com.vivo.systemui.statusbar.notification.settings."
                       "channels.NotificationSettingsActivity")


class FilterParityTests(unittest.TestCase):
    """两处认行把 `named_nodes()` 的候选集原样交给 `own()`：比的是转发（名字、屏高、`systemui_text`）与顺序。"""

    def test_inline_rows_feed_the_same_candidates(self):
        for label, xml in (("app", APP_PAGE), ("title", TITLE_ONLY), ("same", TWO_ROWS),
                           ("band", BAND_EDGE), ("dup", DUPLICATE), ("systemui", SYSTEMUI_NAME)):
            with self.subTest(page=label):
                seen, want = real_candidates(chan_fast.ChannelPage._recognise_inline, xml, APP_FOCUS)
                self.assertEqual(seen, want)

    def test_navigation_rows_feed_the_same_candidates(self):
        seen, want = real_candidates(chan_fast.ChannelPage._enter_app_page, APP_PAGE, APP_FOCUS)
        self.assertEqual(seen, want)
        self.assertEqual([row.bounds(n) for n in seen], [(60, 900, 600, 960)])

    def test_the_vivo_systemui_page_keeps_its_own_text_on_both_sides(self):
        # 宿主是 com.android.systemui 时 _focus() 把 systemui_text 置真：两边都把那段文字算进来
        seen, want = real_candidates(chan_fast.ChannelPage._enter_app_page, SYSTEMUI_NAME,
                                     VIVO_SYSTEMUI_FOCUS, systemui_text=True)
        self.assertEqual(seen, want)
        self.assertEqual([row.bounds(n)[1] for n in seen], [900, 1300])


# ---------- 来源 tests/test_switch_dedupe_531.py ----------
#   #531: vivo's self-drawn switch stacks an untitled wrapper and the real switch on the same
#   bounds. The wrapper has no resource-id and no text, so collapsing duplicate nodes by
#   (resource-id, text, bounds) throws the checkable Switch away and the page reads as empty.

PKG_531 = "com.vivo.appstore"


def vivo_switch_row_531(title, top, checked):
    """One row of the vivo "personalized recommendation" page: title on the left, and on the
    right a four-node stack sharing the same bounds, the checkable Switch last."""
    bottom = top + 142
    box = f"[984,{top}][1125,{bottom}]"
    desc = "开启，开关" if checked else "关闭，开关"
    return (f'<node bounds="[40,{top}][1100,{bottom}]">'
            f'<node text="{title}" bounds="[40,{top}][700,{bottom}]"/>'
            f'<node class="android.widget.FrameLayout" resource-id="{PKG_531}:id/user_recommend_setting_bool_btn"'
            f' content-desc="{desc}" clickable="true" bounds="{box}">'
            f'<node class="android.widget.RelativeLayout" bounds="{box}"/>'
            f'<node class="android.widget.RelativeLayout" resource-id="{PKG_531}:id/move_switch_btn"'
            f' bounds="{box}"/>'
            f'<node class="android.widget.Switch" checkable="true"'
            f' checked="{"true" if checked else "false"}" bounds="{box}"/>'
            f'</node></node>')


def page_531(*rows):
    return (f'<hierarchy rotation="0"><node package="{PKG_531}" bounds="[0,0][1260,2800]">'
            + "".join(rows) + "</node></hierarchy>")


def phone_531(xml):
    p = phone_stub("test")
    p.W, p.H = 1260, 2800
    p.screen.tree = lambda: ET.fromstring(xml)
    return p


class SelfDrawnSwitchTests(unittest.TestCase):
    def test_wrapper_without_identity_does_not_hide_the_real_switch(self):
        xml = page_531(vivo_switch_row_531("个性化推荐，关闭", 353, False),
                   vivo_switch_row_531("个性化广告推荐，关闭", 600, False))
        # #565 后引擎在标题产出处剥掉状态尾缀，去重判定（wrapper 身份）不受影响。
        self.assertEqual([(t, c) for t, c, _ in phone_531(xml).switches()],
                         [("个性化推荐", False), ("个性化广告推荐", False)])


# ---------- 来源 tests/test_two_column_403.py ----------
#   双列热榜（#403）：同一水平带上的左右两列是两个开关，不是同一行。
#   
#   页面按屏尺寸现造，两种 SIZES 各跑一遍；断言值取自生成页面时写死的坐标，不重算实现。


def two_column_page_403(w, h):
    """2×2 双列卡片：卡片整体 checkable、自己不带 checked；状态与落点都在内层 Switch 上。"""
    margin, gap = w // 20, w // 36
    cw, ch = (w - 2 * margin - gap) // 2, h // 8
    top = h // 10
    cards = []

    def card(title, x, y, on):
        sl, st, sr, sb = x + cw - 140, y + ch - 90, x + cw - 40, y + ch - 30
        cards.append((title, on, ((sl + sr) // 2, (st + sb) // 2)))
        return (f'<node class="android.widget.LinearLayout" checkable="true" clickable="true"'
                f' bounds="[{x},{y}][{x + cw},{y + ch}]">'
                f'<node text="{title}" bounds="[{x + 20},{y + 20}][{x + cw - 20},{y + 60}]"/>'
                f'<node class="android.widget.Switch" checked="{"true" if on else "false"}"'
                f' bounds="[{sl},{st}][{sr},{sb}]"/></node>')

    rows = []
    for i, (left, right) in enumerate((("微博热搜榜", "千问热议"), ("微博智搜榜", "全网热搜榜"))):
        y = top + i * (ch + gap)
        rows.append('<node class="android.widget.LinearLayout" bounds="[%d,%d][%d,%d]">%s%s</node>' % (
            margin, y, w - margin, y + ch,
            card(left, margin, y, True), card(right, margin + cw + gap, y, False)))
    xml = ('<hierarchy><node bounds="[0,0][%d,%d]">'
           '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"'
           ' bounds="[0,%d][%d,%d]">%s</node></node></hierarchy>'
           % (w, h, top // 2, w, h - top // 2, "".join(rows)))
    return xml, cards


class TwoColumnTests(unittest.TestCase):
    def test_both_columns_of_a_card_grid_are_switches_of_their_own(self):
        # 改动前：同一 30px 水平带只留最靠右的那个，左列整列消失，off() 静默少关
        for size in fixtures.SIZES:
            with self.subTest(size=size):
                xml, expected = two_column_page_403(*size)
                self.assertEqual(fake_phone(size=size).switches(ET.fromstring(xml)), expected)

    def test_checked_state_comes_from_the_inner_switch_not_the_untagged_card(self):
        # 卡片只有 checkable、没有 checked；读卡片会一律当成「关」，方向反了
        for size in fixtures.SIZES:
            with self.subTest(size=size):
                xml, _ = two_column_page_403(*size)
                got = fake_phone(size=size).switches(ET.fromstring(xml))
                self.assertEqual([(t, c) for t, c, _ in got],
                                 [("微博热搜榜", True), ("千问热议", False),
                                  ("微博智搜榜", True), ("全网热搜榜", False)])

    def test_a_card_that_reports_its_own_state_is_not_overridden_by_the_inner_switch(self):
        # 内层控件可能只是装饰、带着过期的 checked；卡片自己报了状态就以卡片为准
        for size in fixtures.SIZES:
            with self.subTest(size=size):
                w = size[0]
                xml = (f'<hierarchy><node class="android.widget.LinearLayout" checkable="true"'
                       f' clickable="true" checked="true" bounds="[0,300][{w},560]">'
                       f'<node text="营销通知" bounds="[60,320][700,380]"/>'
                       f'<node class="android.widget.Switch" checked="false"'
                       f' bounds="[{w - 180},420][{w - 80},500]"/></node></hierarchy>')
                self.assertEqual(fake_phone(size=size).switches(ET.fromstring(xml)),
                                 [("营销通知", True, (w - 130, 460))])


class OffReadbackTests(unittest.TestCase):
    def test_a_left_column_switch_that_will_not_turn_off_is_reported(self):
        # 页面不随点击变化：左列那个开关关不掉，不能计入「调整 N 项」
        for size in fixtures.SIZES:
            with self.subTest(size=size):
                self._check(size)

    def _check(self, size):
        xml, cards = two_column_page_403(*size)
        clicks, said = [], []
        p = fake_phone(size=size, stages=[(0.0, xml)], click=lambda x, y: clicks.append((x, y)),
                       say=lambda *a: said.append(" ".join(str(x) for x in a)))
        with patch.object(fast.time, "sleep"):
            done = p.off(only=["微博热搜榜"])
        self.assertEqual(done, 0)
        self.assertEqual(clicks[0], cards[0][2])
        self.assertIn("✗ 关不掉 微博热搜榜", "\n".join(said))
        self.assertEqual(p.changed, [])


def old_switches_403(p, root):
    """改动前（bfff436）`Phone.switches()` 的逐字副本，只用于对拍，不要按新行为改它。
    它仍调用现行的 `row.title_of()`：对拍守的是分带合并与落点，标题规则的改前改后要另备基线。"""
    parent = {c: q for q in root.iter() for c in q}
    out = []
    shot = None
    for n in root.iter("node"):
        if not p.on_screen(n) or "RadioButton" in n.get("class", ""):
            continue
        if n.get("checkable") != "true":
            rid = (n.get("resource-id") or "").lower()
            if "switch" in rid and "switcher" not in rid and n.get("clickable") == "true":
                l, t, r, b = row.bounds(n)
                if r - l > 0 and b - t > 0:
                    if shot is None:
                        shot = p.reader.screenshot()
                    if shot.size != (p.W, p.H):
                        continue
                    on = fast.Screen._pixel_on(shot, l, t, r, b)
                    if on is None:
                        continue
                    n.set("checked", "true" if on else "false")
                    n.set("checkable", "true")
                    n.set("class", "SelfDrawnSwitch")
            if n.get("checkable") != "true":
                continue
        cls = n.get("class", "")
        if not any(k in cls for k in ("Switch", "CheckBox", "ToggleButton", "Compound")) and n.get("clickable") != "true":
            continue
        l, t, r, b = row.bounds(n)
        if r - l <= 0 or b - t <= 0 or not p.on_screen(n):
            continue
        cy = (t + b) // 2
        out.append((row.title_of(n, parent, p.on_screen, p.H),
                    n.get("checked") == "true", ((l + r) // 2, cy)))
    rows = []
    for sw in sorted(out, key=lambda s: s[2][1]):
        if rows and abs(rows[-1][2][1] - sw[2][1]) < 30:
            if sw[2][0] > rows[-1][2][0]:
                rows[-1] = sw if sw[0] else (rows[-1][0], sw[1], sw[2])
        else:
            rows.append(sw)
    return rows


def switch_centres_403(root, size):
    """屏幕上类名像 Switch 的控件中心。"""
    p = fixtures.phone_stub("test")
    p.W, p.H = size
    out = set()
    for n in root.iter("node"):
        cls = n.get("class") or ""
        if "Switch" in cls and "Switcher" not in cls and p.on_screen(n):
            l, t, r, b = row.bounds(n)
            out.add(((l + r) // 2, (t + b) // 2))
    return out


def shell_around_switch_403(root, size):
    """这一页有没有「可点、resource-id 带 switch、自己不 checkable 的外层里包着真开关」：AOSP 渠道页的
    main_switch_bar。旧实现把外层当自绘开关、截图按颜色猜状态，猜出的状态盖过里面的真开关；
    修复后外层不再参与，只剩真开关（0.3.1 发版前模拟器发现，见 test_main_switch_bar）。"""
    p = fixtures.phone_stub("test")
    p.W, p.H = size
    for n in root.iter("node"):
        rid = (n.get("resource-id") or "").lower()
        if (n.get("checkable") != "true" and n.get("clickable") == "true" and "switch" in rid
                and "switcher" not in rid and p.on_screen(n)
                and any(x is not n and x.get("checkable") == "true" for x in n.iter("node"))):
            return True
    return False


def wraps_switch_403(root, size):
    """这一页有没有「checkable 容器里包着屏幕内的 Switch」：本票要改的卡片形态。
    旧实现把这一行记在卡片中心（点上去是标题与开关之间的空白），新实现落在内层开关上。"""
    p = fixtures.phone_stub("test")
    p.W, p.H = size
    for n in root.iter("node"):
        if n.get("checkable") != "true":
            continue
        for x in n.iter("node"):
            cls = x.get("class") or ""
            if x is not n and "Switch" in cls and "Switcher" not in cls and p.on_screen(x):
                return True
    return False


class SameLayoutTests(unittest.TestCase):
    def test_existing_pages_are_unchanged(self):
        """既有布局（整行可点 + 行内开关）逐条对拍：页面样本取 tests/ 全部，两种屏尺寸各一遍。
        唯一允许的差异是「checkable 卡片里包着屏幕内 Switch」的样本——本票要改的形态，落点从卡片中心
        移到内层开关；其余页面新旧逐条相同。"""
        def result(call):
            try:
                return call()
            except Exception as e:          # noqa: BLE001 - 对拍要看到异常本身
                return ["ERROR", type(e).__name__]

        seen, cards, moved, shells = 0, 0, 0, 0
        for label, xml in fixtures.all_pages():
            for size in fixtures.SIZES:
                with self.subTest(page=label, size=size):
                    p = fake_phone(size=size, stages=[(0.0, xml)])
                    root = ET.fromstring(xml)
                    old = result(lambda: old_switches_403(p, root))  # noqa: B023 - 当轮创建当轮消费，result 同步调用
                    new = result(lambda: p.switches(ET.fromstring(xml)))  # noqa: B023 - 同上
                    if shell_around_switch_403(root, size):
                        # 有意的差异：旧实现去截图猜外层颜色（假手机不能截图，这里会报错），新实现只报真开关
                        shells += 1
                        self.assertNotIn("ERROR", new)
                        self.assertTrue(all(xy in switch_centres_403(root, size) for _, _, xy in new))
                        continue
                    if wraps_switch_403(root, size):
                        cards += 1
                        centres = switch_centres_403(root, size)
                        if old and not any(r[2] in centres for r in old if isinstance(r, tuple)):
                            # 卡片自己 checkable、内层 Switch 不标 checkable（#333 的页面样本）：
                            # 旧实现只按卡片记一行，落点与状态都不是开关本体，只比标题与顺序。
                            self.assertEqual([t for t, _, _ in new], [t for t, _, _ in old])
                            self.assertTrue(all(xy in centres for _, _, xy in new))
                            moved += new != old
                            continue
                        # 唯一允许的差异：旧实现给卡片中心单独记一行（落点不是开关本体），
                        # 新实现落在内层开关上；标题与状态逐条照抄旧输出。
                        self.assertEqual(new, [r for r in old if isinstance(r, tuple) and r[2] in centres])
                        self.assertTrue(new and all(xy in centres for _, _, xy in new))
                        moved += new != old
                        continue
                    self.assertEqual(new, old)
                    seen += bool(old)
        self.assertGreater(seen, 10)        # 对拍不能是空跑
        self.assertGreater(cards, 0)        # 卡片形态的样本必须真的走到上面的分支
        self.assertGreater(moved, 0)        # 而且新旧确实不同，否则这个分支什么也没守住
        self.assertGreater(shells, 0)       # main_switch_bar 形态的样本也要真的走到它的分支


if __name__ == "__main__":
    unittest.main()
