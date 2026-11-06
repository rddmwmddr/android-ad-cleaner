"""#331：进入设置页后页面还没画完就探测入口，五个入口整段误报「没找到」。

Android 17 上设置页渲染更慢：点完齿轮 Activity 已经换了，读屏还是空白页。
入口探测要先等页面站稳再判定，找不到时留下能定位的结构，而不是只打一句「没找到」。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
import row
from fixtures import EMPTY_PAGE, Clock, fake_phone, install_clock, load_recipe

ENTRIES = ["隐私和安全", "主页设置", "搜索设置", "功能设置", "网页浏览设置"]


def page(entries=ENTRIES, top="设置"):
    rows = "".join(
        f'<node class="android.widget.TextView" text="{t}" clickable="true" '
        f'bounds="[48,{320 + i * 120}][600,{420 + i * 120}]" />'
        for i, t in enumerate(entries))
    return f"""<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="{top}" bounds="[48,96][360,180]" />
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2340]">
      {rows}
      <node class="android.widget.Switch" text="个性化内容推荐" checkable="true" checked="true" bounds="[900,320][1020,420]" />
    </node>
  </node>
</hierarchy>"""


SETTINGS_PAGE = page()
HALF_PAGE = page(ENTRIES[:2])
OTHER_PAGE = page(["别的页"])


class BrowserEntryTests(unittest.TestCase):
    def phone(self, stages, **fields):
        clock = Clock()
        original = fast.time
        install_clock(fast, clock)
        self.addCleanup(setattr, fast, "time", original)
        return fake_phone(clock=clock, stages=stages, **fields), clock

    def test_entry_waits_for_settings_page_to_render(self):
        """空白页先出现、1 秒后才换成完整设置页：等页之后五个入口都该找得到。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (1.0, SETTINGS_PAGE)])
        for name in ENTRIES:
            self.assertTrue(p.entry(name), name)

    def test_entry_keeps_waiting_while_the_page_is_still_repainting(self):
        """页面一屏一屏往上长（每屏都比上一屏多）：不能停在中间那屏就去找入口。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (0.2, OTHER_PAGE), (0.4, HALF_PAGE),
                           (0.6, SETTINGS_PAGE)])
        self.assertTrue(p.entry("网页浏览设置"))

    def test_entry_retries_after_the_page_finishes_rendering(self):
        """第一轮只等到半画完的页面就去找、没找到；第二轮页面又画完一版，得能找回来。"""
        p, _ = self.phone([(0.0, EMPTY_PAGE), (0.4, HALF_PAGE), (1.5, SETTINGS_PAGE)])
        self.assertTrue(p.entry("网页浏览设置", budget=2.4))

    def test_entry_gives_up_within_budget_when_page_never_renders(self):
        """页面始终空白时，等页预算耗尽就判失败，不会无限等。"""
        p, clock = self.phone([(0.0, EMPTY_PAGE)])
        self.assertFalse(p.entry("隐私和安全", budget=2.4))
        self.assertGreaterEqual(clock.t, 2.4)
        self.assertLess(clock.t, 3.0)

    def test_entry_keeps_the_section_from_going_off_path_after_a_miss(self):
        """可选入口 miss 不能把段级 miss 留在 1，否则后面的必需入口会被「快速放弃」。"""
        p, _ = self.phone([(0.0, SETTINGS_PAGE)])
        p.tap("不存在的必需入口", exact=True)
        self.assertGreater(p.miss, 0)
        self.assertFalse(p.entry("也不存在的入口"))
        self.assertEqual(p.miss, 0)

    def test_missing_entry_logs_activity_and_structure_without_page_text(self):
        """入口确实不存在时，日志要带 Activity 与结构摘要，且不打印页面文字。"""
        p, _ = self.phone([(0.0, SETTINGS_PAGE)])
        lines = []
        p.say = lambda *a, **k: lines.append(" ".join(str(x) for x in a))
        p.focus = lambda: "com.android.browser/.BrowserSettingsActivity"
        self.assertFalse(p.entry("不存在的入口"))
        log = "\n".join(lines)
        self.assertIn("BrowserSettingsActivity", log)
        self.assertIn("结构", log)
        self.assertIn("开关", log)
        for text in ENTRIES:
            self.assertNotIn(text, log)

    def test_note_miss_lets_a_dropped_connection_through(self):
        """诊断读不到页面时只该少一段摘要；断线是 RuntimeError，不能被当成「页面没认出来」吞掉。"""
        p, _ = self.phone([(0.0, SETTINGS_PAGE)])
        p.focus = lambda: "com.android.browser/.BrowserSettingsActivity"

        def gone():
            raise RuntimeError("设备已断开")

        p.tree = gone
        with self.assertRaisesRegex(RuntimeError, "设备已断开"):
            p.note_miss("不存在的入口")

    def test_note_miss_survives_an_unparsable_page(self):
        p, _ = self.phone([(0.0, SETTINGS_PAGE)])
        p.focus = lambda: "com.android.browser/.BrowserSettingsActivity"
        lines = []
        p.say = lambda *a, **k: lines.append(" ".join(str(x) for x in a))
        p.tree = lambda: (_ for _ in ()).throw(fast.ET.ParseError("bad"))
        p.note_miss("不存在的入口")
        self.assertIn("页面结构读不到", "\n".join(lines))

    def test_in_settings_page_recognizes_the_settings_activity(self):
        p, _ = self.phone([(0.0, SETTINGS_PAGE)],
                          focus=((0.0, "com.android.browser/.BrowserSettingsActivity"),))
        self.assertTrue(p.in_settings_page())
        p.focus = lambda: "com.android.browser/.MainActivity"
        self.assertFalse(p.in_settings_page())

    def test_browser_settings_rejects_a_gear_click_that_did_not_open_settings(self):
        """点完齿轮页面没换（点击被吞）：不能当成进了设置页，否则后面入口全打在旧页上。"""
        from unittest.mock import Mock
        p = Mock(W=1080, H=2340)
        p.tree.return_value = fast.ET.fromstring(
            '<hierarchy><node text="设置" class="android.widget.ImageView" clickable="false" '
            'bounds="[900,100][1020,220]"/></hierarchy>')
        p.on_screen.return_value = True
        p.focus.return_value = "com.android.browser/.MainActivity"
        p.in_settings_page.return_value = False
        p.texts.return_value = []
        scope, _ = load_recipe(p, ROOT / "recipes/xiaomi-M154FF/recipe.py")
        self.assertFalse(scope["browser_settings"]())
        p.back.assert_not_called()

    def test_row_summary_skips_offscreen_and_status_bar_nodes(self):
        """摘要只数屏内的节点：状态栏文字、折叠屏合上后的内屏残留都不算。"""
        xml = """<hierarchy rotation="0">
          <node class="android.widget.FrameLayout" package="com.android.browser" bounds="[0,0][1080,2340]">
            <node class="android.widget.TextView" package="com.android.systemui" text="12:00" bounds="[48,24][180,72]" />
            <node class="android.widget.TextView" text="设置" bounds="[48,96][360,180]" />
            <node class="android.widget.TextView" text="内屏残留" bounds="[48,2600][360,2700]" />
            <node class="android.widget.Switch" checkable="true" bounds="[900,320][1020,420]" />
          </node>
        </hierarchy>"""
        out = row.summary(fast.ET.fromstring(xml), 1080, 2340)
        self.assertIn("标题 1 个", out)
        self.assertIn("开关 1 个", out)

    def test_row_summary_reports_counts_and_chain(self):
        root = fast.ET.fromstring(SETTINGS_PAGE)
        out = row.summary(root, 1080, 2340)
        self.assertIn("标题 1 个", out)
        self.assertIn("开关 1 个", out)
        self.assertIn("结构 ", out)

    def test_row_link_matches_channel_chain_format(self):
        """入口诊断与渠道「未确认」共用一份控件链渲染。"""
        import chan_fast
        root = fast.ET.fromstring(SETTINGS_PAGE)
        parents = {c: n for n in root.iter("node") for c in n}
        node = next(n for n in root.iter("node") if n.get("checkable") == "true")
        self.assertEqual(chan_fast.chain(node, parents), row.link(node, parents))


if __name__ == "__main__":
    unittest.main()
