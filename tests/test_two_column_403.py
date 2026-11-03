"""双列热榜（#403）：同一水平带上的左右两列是两个开关，不是同一行。

页面按屏尺寸现造，两种 SIZES 各跑一遍；断言值取自生成页面时写死的坐标，不重算实现。
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import fast
import fixtures
from fixtures import fake_phone
from row import bounds, title_of


def two_column_page(w, h):
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
                xml, expected = two_column_page(*size)
                self.assertEqual(fake_phone(size=size).switches(ET.fromstring(xml)), expected)

    def test_checked_state_comes_from_the_inner_switch_not_the_untagged_card(self):
        # 卡片只有 checkable、没有 checked；读卡片会一律当成「关」，方向反了
        for size in fixtures.SIZES:
            with self.subTest(size=size):
                xml, _ = two_column_page(*size)
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
        xml, cards = two_column_page(*size)
        clicks, said = [], []
        p = fake_phone(size=size, stages=[(0.0, xml)], click=lambda x, y: clicks.append((x, y)),
                       say=lambda *a: said.append(" ".join(str(x) for x in a)))
        with patch.object(fast.time, "sleep"):
            done = p.off(only=["微博热搜榜"])
        self.assertEqual(done, 0)
        self.assertEqual(clicks[0], cards[0][2])
        self.assertIn("✗ 关不掉 微博热搜榜", "\n".join(said))
        self.assertEqual(p.changed, [])


def old_switches(p, root):
    """改动前（bfff436）`Phone.switches()` 的逐字副本，只用于对拍，不要按新行为改它。
    它仍调用现行的 `title_of()`：对拍守的是分带合并与落点，标题规则的改前改后要另备基线。"""
    parent = {c: q for q in root.iter() for c in q}
    out = []
    shot = None
    for n in root.iter("node"):
        if not p.on_screen(n) or "RadioButton" in n.get("class", ""):
            continue
        if n.get("checkable") != "true":
            rid = (n.get("resource-id") or "").lower()
            if "switch" in rid and "switcher" not in rid and n.get("clickable") == "true":
                l, t, r, b = bounds(n)
                if r - l > 0 and b - t > 0:
                    if shot is None:
                        shot = p.reader.screenshot()
                    if shot.size != (p.W, p.H):
                        continue
                    on = p._pixel_on(shot, l, t, r, b)
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
        l, t, r, b = bounds(n)
        if r - l <= 0 or b - t <= 0 or not p.on_screen(n):
            continue
        cy = (t + b) // 2
        out.append((title_of(n, parent, p.on_screen, p.H),
                    n.get("checked") == "true", ((l + r) // 2, cy)))
    rows = []
    for sw in sorted(out, key=lambda s: s[2][1]):
        if rows and abs(rows[-1][2][1] - sw[2][1]) < 30:
            if sw[2][0] > rows[-1][2][0]:
                rows[-1] = sw if sw[0] else (rows[-1][0], sw[1], sw[2])
        else:
            rows.append(sw)
    return rows


def switch_centres(root, size):
    """屏幕上类名像 Switch 的控件中心。"""
    p = fixtures.phone_stub("test")
    p.W, p.H = size
    out = set()
    for n in root.iter("node"):
        cls = n.get("class") or ""
        if "Switch" in cls and "Switcher" not in cls and p.on_screen(n):
            l, t, r, b = bounds(n)
            out.add(((l + r) // 2, (t + b) // 2))
    return out


def shell_around_switch(root, size):
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


def wraps_switch(root, size):
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
                    old = result(lambda: old_switches(p, root))
                    new = result(lambda: p.switches(ET.fromstring(xml)))
                    if shell_around_switch(root, size):
                        # 有意的差异：旧实现去截图猜外层颜色（假手机不能截图，这里会报错），新实现只报真开关
                        shells += 1
                        self.assertNotIn("ERROR", new)
                        self.assertTrue(all(xy in switch_centres(root, size) for _, _, xy in new))
                        continue
                    if wraps_switch(root, size):
                        cards += 1
                        centres = switch_centres(root, size)
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
