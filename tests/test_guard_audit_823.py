"""守护复查的审计模式（#823/ADR-0027）：off() 只读走计划、四档结局、默认路径不变。

Phone 是 Mock，off() 走未绑定真方法；switches/tree 用「当前页」闭包（真
switch_rows 过夹具 XML），点击用闭包翻状态。
"""
import sys
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import events
import fast
from fixtures import phone_mock


def page(*switches, enabled="true"):
    """一屏开关页：行容器（TextView 标题 + 内层可勾选 Switch）。ElementTree 节点构造。"""
    root = ET.Element("hierarchy")
    for (t, on, y) in switches:
        row = ET.SubElement(root, "node", {
            "class": "android.widget.LinearLayout", "bounds": f"[0,{y}][1080,{y + 120}]"})
        ET.SubElement(row, "node", {
            "class": "android.widget.TextView", "text": t,
            "bounds": f"[80,{y + 20}][700,{y + 80}]"})
        ET.SubElement(row, "node", {
            "class": "android.widget.Switch", "checkable": "true",
            "checked": str(on).lower(), "clickable": "true", "enabled": enabled,
            "bounds": f"[900,{y + 20}][1040,{y + 80}]"})
    return root


def base_phone():
    p = phone_mock(W=1080, H=2400)
    p.safe_mode = False
    p.miss = []
    return p


class AuditModeTests(unittest.TestCase):
    def setUp(self):
        fast.AUDIT_MODE = True
        fast.AUDIT_SEEN.clear()
        self.emitted = []
        self._orig_emit = events.emit
        events.emit = lambda kind, **data: self.emitted.append((kind, data))

    def tearDown(self):
        fast.AUDIT_MODE = False
        fast.AUDIT_SEEN.clear()
        events.emit = self._orig_emit

    def phone(self, *pages):
        """switches/tree 返回「当前页」（scroll_more 翻页），行按真实 switches() 契约裁 3 元组。"""
        p = base_phone()
        current = {"i": 0}

        def current_page():
            return pages[min(current["i"], len(pages) - 1)]

        def switches_now(root=None):
            return [r[:3] for r in fast.Phone.switch_rows(p, current_page())]

        def scroll():
            if current["i"] < len(pages) - 1:
                current["i"] += 1
                return True
            return False

        p.tree = current_page
        p.switches = switches_now
        p.scroll_more = scroll
        p.entry.return_value = False
        return p

    def reports(self, page_name):
        return [d for k, d in self.emitted if k == "guard_audit" and d.get("page") == page_name]

    def test_reverted_rows_are_reported(self):
        """开着的「个性化广告推荐」（目标关）→ 被改回；关着的达标行不进档。"""
        p = self.phone(page(("个性化广告推荐", True, 300), ("搜索框推荐词", False, 500)))
        n = fast.Phone.off(p, only=["个性化广告推荐", "搜索框推荐词"], page="设置·推荐")
        report = self.reports("设置·推荐")[-1]
        self.assertEqual(report["reverted"], ["个性化广告推荐"])
        self.assertEqual(report["greyed"], [])
        self.assertEqual(report["unconfirmed"], [])
        self.assertEqual(n, 1)
        self.assertIn("搜索框推荐词", fast.AUDIT_SEEN)

    def test_greyed_rows_are_their_own_bucket(self):
        """灰的行不进 targets（plan_switches 滤掉）也不算被改回——按 plan.disabled 交档。"""
        p = self.phone(page(("推荐卡片", True, 300), enabled="false"))
        n = fast.Phone.off(p, only=["推荐卡片"], page="设置·推荐")
        report = self.reports("设置·推荐")[-1]
        self.assertEqual(report["reverted"], [])
        self.assertEqual(report["greyed"], ["推荐卡片"])
        self.assertEqual(n, 0)

    def test_unconfirmed_on_a_dead_screen_reader(self):
        p = self.phone(page(("个性化广告推荐", True, 300)))
        p.switches = lambda root=None: (_ for _ in ()).throw(RuntimeError("读屏炸了"))
        n = fast.Phone.off(p, page="设置·推荐")
        report = [d for k, d in self.emitted if k == "guard_audit"][-1]
        self.assertEqual(report["unconfirmed"], ["读屏炸了"])
        self.assertEqual(report["reverted"], [])
        self.assertEqual(n, 0)

    def test_missing_titles_computed_by_the_caller_from_audit_seen(self):
        """--expect 的对账材料 = AUDIT_SEEN（全程读到的标题）：调用方拿它减出「找不到」。"""
        p = self.phone(page(("搜索框推荐词", False, 300)))
        fast.Phone.off(p, page="设置·推荐")
        self.assertIn("搜索框推荐词", fast.AUDIT_SEEN)
        missing = {"搜索框推荐词", "上一版还有的入口"} - fast.AUDIT_SEEN
        self.assertEqual(missing, {"上一版还有的入口"})

    def test_default_off_path_is_untouched_when_not_auditing(self):
        """默认（非审计）：执行路径真的点击（点击翻状态）、记 changed、不发守护事件。"""
        fast.AUDIT_MODE = False
        p = base_phone()
        state = {"on": True}

        def tree_of(*a, **k):
            return page(("个性化广告推荐", state["on"], 300))

        def switches_now(root=None):
            return [r[:3] for r in fast.Phone.switch_rows(p, tree_of())]

        def flip(x, y, *a, **k):
            state["on"] = False

        p.tree = tree_of
        p.switches = switches_now
        p.switch_rows = lambda root=None: fast.Phone.switch_rows(p, tree_of())
        p.click.side_effect = flip
        p.confirm.return_value = None
        p.scroll_more.return_value = False
        p.changed = []                                    # Mock 属性：换成真清单好断言
        n = fast.Phone.off(p, only=["个性化广告推荐"], page="设置·推荐")
        self.assertEqual(n, 1)
        self.assertEqual(len(p.changed), 1)
        self.assertFalse([1 for k, _ in self.emitted if k == "guard_audit"])


if __name__ == "__main__":
    unittest.main()
