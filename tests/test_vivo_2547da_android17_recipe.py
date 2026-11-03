"""vivo V2547DA 的 Android 17 变体（#220）：商店直达设置页，「个性化推荐」页按位置关无标题开关。

页面按报告者的读屏描述现造：开关的 content-desc 只有「开启，开关」，行里没有标题文字，
所以 p.off() 按名字匹配不到（plan_switches 直接跳过空标题的行）。
本仓库没有这台机器，这些用例只护住「认得出来、点得到、回读写实」三件事。
"""
import contextlib
import io
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import fixtures
from fast import plan_switches
from fixtures import fake_phone, phone_mock

RECIPE = ROOT / "recipes/vivo-V2547DA/recipe_android17.py"


def personal_recommend_page(w, h):
    """商店「个性化推荐」页：两行开关，状态只写在 content-desc 里，行内没有标题。"""
    rows, expected = [], []
    top, rh = h // 6, h // 7
    for i in range(2):
        y = top + i * rh
        sl, st, sr, sb = w - 260, y + rh // 3, w - 80, y + rh // 3 + 100
        expected.append(("", True, ((sl + sr) // 2, (st + sb) // 2)))
        rows.append(
            '<node class="android.widget.LinearLayout" bounds="[40,%d][%d,%d]">'
            '<node class="android.widget.Switch" checkable="true" clickable="true" checked="true"'
            ' content-desc="开启，开关" bounds="[%d,%d][%d,%d]"/></node>'
            % (y, w - 40, y + rh, sl, st, sr, sb))
    xml = ('<hierarchy><node bounds="[0,0][%d,%d]">'
           '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true"'
           ' bounds="[0,%d][%d,%d]">%s</node></node></hierarchy>'
           % (w, h, top // 2, w, h - top // 2, "".join(rows)))
    return xml, expected


class FakePage:
    """按点击翻状态的假页面。
    flips=False 时怎么点都不变；blank=True 时点过之后读屏读空（模拟确认框挡着）；
    grey 里的坐标对应的开关是灰的（enabled="false"）。"""

    def __init__(self, rows, flips=True, blank=False, grey=()):
        self.rows = [list(r) for r in rows]
        self.flips = flips
        self.blank = blank
        self.grey = set(grey)
        self.clicks = []
        self.confirms = 0
        self.changed = []

    def switches(self, root=None):
        if self.blank and self.clicks:
            return []
        return [tuple(r) for r in self.rows]

    def tree(self):
        nodes = "".join(
            '<node class="android.widget.Switch" checkable="true" clickable="true" enabled="%s"'
            ' bounds="[%d,%d][%d,%d]"/>'
            % ("false" if row[2] in self.grey else "true",
               row[2][0] - 20, row[2][1] - 20, row[2][0] + 20, row[2][1] + 20)
            for row in self.rows)
        return ET.fromstring(f"<hierarchy>{nodes}</hierarchy>")

    def click(self, x, y):
        self.clicks.append((x, y))
        if not self.flips:
            return
        for row in self.rows:
            if row[2] == (x, y):
                row[1] = False

    def confirm(self):
        self.confirms += 1
        return "确认关闭"


class Android17RecipeTests(unittest.TestCase):
    def load(self, phone, only=None):
        scope = {"p": phone, "ONLY": only or ["__none__"]}
        with patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            exec(compile(RECIPE.read_text(encoding="utf-8"), str(RECIPE), "exec"), scope)
        return scope

    def call(self, scope, page):
        buf = io.StringIO()
        with patch("time.sleep"), contextlib.redirect_stdout(buf):
            result = scope["off_unnamed"](page)
        return result, buf.getvalue()

    def phone(self):
        p = phone_mock()
        p.locked.return_value = False
        p.tree.return_value = ET.Element("hierarchy")
        p.entry.return_value = False
        p.tap.return_value = False
        p.focus.return_value = "com.bbk.appstore/com.bbk.appstore.ui.AppStore"
        return p

    def test_engine_reads_the_two_switches_without_a_title(self):
        for size in fixtures.SIZES:
            with self.subTest(size=size):
                xml, expected = personal_recommend_page(*size)
                self.assertEqual(fake_phone(size=size).switches(ET.fromstring(xml)), expected)

    def test_p_off_cannot_target_untitled_switches(self):
        # #220 里 p.off() 关不掉的原因：空标题的行连目标都进不了，既不关也不报「关不掉」
        size = fixtures.SIZES[0]
        xml, _ = personal_recommend_page(*size)
        rows = fake_phone(size=size).switches(ET.fromstring(xml))
        plan = plan_switches(rows, only=["个性化推荐"], screen_h=size[1])
        self.assertEqual(plan.targets, ())
        self.assertEqual(plan.checked, frozenset())

    def test_closes_every_switch_that_has_no_title_and_leaves_named_ones_alone(self):
        p = FakePage([("", True, (900, 500)), ("", True, (900, 800)),
                      ("个性化推荐", True, (300, 500))])
        scope = self.load(p)
        done, said = self.call(scope, "商店·个性化推荐")
        self.assertEqual(done, 2)
        self.assertEqual(p.clicks, [(900, 500), (900, 800)])
        self.assertEqual(p.confirms, 2)
        self.assertEqual(p.changed, [("商店·个性化推荐", "无标题开关 1"),
                                     ("商店·个性化推荐", "无标题开关 2")])
        self.assertNotIn("关不掉", said)

    def test_already_off_switches_are_not_touched(self):
        p = FakePage([("", False, (900, 500)), ("", False, (900, 800))])
        scope = self.load(p)
        done, _ = self.call(scope, "商店·个性化推荐")
        self.assertEqual(done, 0)
        self.assertEqual(p.clicks, [])

    def test_a_switch_that_stays_on_is_reported_not_counted(self):
        p = FakePage([("", True, (900, 500)), ("", True, (900, 800))], flips=False)
        scope = self.load(p)
        done, said = self.call(scope, "商店·个性化推荐")
        self.assertEqual(done, 0)
        self.assertEqual(said.count("关不掉"), 2)
        self.assertEqual(p.changed, [])

    def test_a_readback_that_sees_nothing_is_not_a_success(self):
        # 确认框没被点掉时读屏读不到开关；读空不等于关掉（#486）
        p = FakePage([("", True, (900, 500))], blank=True)
        scope = self.load(p)
        done, said = self.call(scope, "商店·个性化推荐")
        self.assertEqual(done, 0)
        self.assertIn("关不掉", said)
        self.assertEqual(p.changed, [])

    def test_a_greyed_switch_is_left_alone(self):
        p = FakePage([("", True, (900, 500))], grey={(900, 500)})
        scope = self.load(p)
        done, said = self.call(scope, "商店·个性化推荐")
        self.assertEqual(done, 0)
        self.assertEqual(p.clicks, [])
        self.assertIn("被上级开关禁用", said)

    def test_store_opens_the_settings_activity_directly(self):
        # Android 17 的「我的」页没有能读到的齿轮入口（#220）
        p = self.phone()
        p.focus.return_value = "com.bbk.appstore/.ui.menu.AppstoreSettingsActivity"
        self.load(p, ["应用商店"])
        self.assertEqual(p.start.call_args_list[0].args, ("com.bbk.appstore", ".ui.menu.AppstoreSettingsActivity"))
        self.assertEqual(p.start.call_count, 1)

    def test_store_falls_back_to_my_page_when_the_activity_does_not_open(self):
        p = self.phone()
        p.start = Mock(side_effect=[RuntimeError("Error type 3: Activity class does not exist"), None])
        self.load(p, ["应用商店"])
        self.assertEqual(p.start.call_args_list[1].args, ("com.bbk.appstore",))
        self.assertEqual(p.start.call_args_list[1].kwargs, {"expect": ("我的",)})
        p.tab.assert_any_call("我的")


if __name__ == "__main__":
    unittest.main()
