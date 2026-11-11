"""导航搬出 `Phone` 之后的对外契约（ADR-0033、#1044）。

钉四件事：
  · 门面继续逐个转发导航方法——返回值与异常都由阶段给，门面没有实现残留；
  · 这个阶段只造自己就能验：一个假 `Screen`、一个丢失记录与一个 `dismiss` 桩，
    不必造整台 `Phone`（搬迁声称的测试面下沉，不是实现细节）；
  · 失败语义逐处保持：`tap()` / `entry()` / `go()` / `tab()` 只返回假，`enter()` 抛；
  · 调用图单向无环：阶段只 import 基座，彼此之间只传注入的窄接口。
"""
import ast
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast  # noqa: E402
from phone import navigator  # noqa: E402
from fixtures import SIZES, Clock, EMPTY_PAGE, clocked, phone_stub, screen_stub  # noqa: E402

# ---------- 基线：bb2afb7 的旧实现，逐字冻结 ----------
BASE_SETTINGS_MARKS = ("Setting", "Preference")

SETTINGS = "com.example.app/.SettingsActivity"
HOME = "com.example.app/.MainActivity"

PAGE = '''<hierarchy rotation="0">
  <node package="com.example.app" bounds="[0,0][1080,2340]">
    <node class="android.widget.ListView" scrollable="true" bounds="[0,300][1080,2100]">
      <node class="android.widget.TextView" text="设置" clickable="true" bounds="[60,400][900,500]"/>
    </node>
    <node class="android.widget.TextView" text="我的" clickable="true" bounds="[860,2180][1020,2260]"/>
  </node>
</hierarchy>'''


def bare_navigator(page=PAGE, focus=SETTINGS, dismiss=None, size=SIZES[0]):
    """只造导航阶段：观测替身取 `fixtures.screen_stub()`，没有 `Phone`。点击与返回只记账。"""
    screen = screen_stub(page, size=size, conn=SimpleNamespace(say=lambda *a: None))
    screen.focus = focus if callable(focus) else (lambda: focus)
    screen.say = lambda *a: None
    screen.sig = lambda: "page"
    screen.settle = lambda *a, **k: True
    screen.scroll = lambda *a, **k: None
    clicks, backs = [], []
    screen.click = lambda x, y: clicks.append((x, y))
    screen.back = lambda n=1: backs.append(n)
    return fast.Navigator(screen, fast.LostNote(), dismiss or (lambda: None)), clicks, backs


class FacadeForwardingTests(unittest.TestCase):
    def setUp(self):
        self.p = phone_stub(W=1080, H=2340)

    def test_the_phase_methods_go_through_the_stage(self):
        """门面没有实现残留：把阶段换成替身，返回值与异常必须由替身给出。"""
        self.p.navigator = Mock()
        nav = self.p.navigator
        nav.tap.return_value = True
        nav.go.return_value = False
        nav.enter.side_effect = RuntimeError("页面没有变化")
        nav.entry.return_value = True
        nav.tab.return_value = False
        nav.tap_icon.return_value = True
        nav.await_page.return_value = "ok"
        nav.in_settings_page.return_value = True

        self.assertTrue(self.p.tap("设置", exact=True, scrolls=2))
        self.assertFalse(self.p.go("我的", "设置"))
        with self.assertRaisesRegex(RuntimeError, "页面没有变化"):
            self.p.enter("设置")
        self.assertTrue(self.p.entry("设置"))
        self.assertFalse(self.p.tab("我的"))
        self.assertTrue(self.p.tap_icon("设置"))
        self.assertEqual(self.p.await_page(), "ok")
        self.assertTrue(self.p.in_settings_page())
        self.p.top(2)

        nav.tap.assert_called_once_with("设置", True, 2, 0.6, False, None)
        nav.go.assert_called_once_with("我的", "设置", 3, True)
        nav.enter.assert_called_once_with("设置", 0, 3)
        nav.entry.assert_called_once_with("设置", 6, 2.4, 0.2, 2)
        nav.tab.assert_called_once_with("我的", 6.0)
        nav.tap_icon.assert_called_once_with("设置", (0.72, 0.0, 1.0, 0.16), 3)
        nav.await_page.assert_called_once()
        nav.in_settings_page.assert_called_once_with()
        nav.top.assert_called_once_with(2)


class StandalonePhaseTests(unittest.TestCase):
    def setUp(self):
        # 等页、找字与 6 秒底栏预算都读 `time`：假钟一装，这些等待不占真实时间。
        self.clock = clocked(self, fast, Clock())

    def test_the_bottom_band_label_is_clicked_without_a_phone(self):
        stage, clicks, _ = bare_navigator()
        self.assertTrue(stage.tab("我的"))
        self.assertEqual(clicks, [(940, 2220)])

    def test_a_missing_text_only_records_the_miss(self):
        stage, clicks, _ = bare_navigator()
        self.assertFalse(stage.tap("没有的字", scrolls=2))
        self.assertEqual(stage.lost_note.miss, 1)
        self.assertEqual(clicks, [])

    def test_entering_a_page_that_never_changes_raises(self):
        stage, clicks, _ = bare_navigator()
        stage.screen.settle = lambda *a, **k: False      # 入口找得到，点了页面没换
        with self.assertRaisesRegex(RuntimeError, "页面没有变化"):
            stage.enter("设置")
        self.assertEqual(len(clicks), 3)                  # tries 次重点

    def test_the_settings_page_signature_is_read_from_the_base(self):
        stage, _, _ = bare_navigator(focus=lambda: SETTINGS)
        self.assertTrue(stage.in_settings_page())
        stage.screen.focus = lambda: HOME
        self.assertFalse(stage.in_settings_page())

    def test_the_injected_dismiss_is_the_only_way_back_to_the_popups(self):
        """挡路的弹窗归 `Dismisser`：导航只调注入的窄接口，不 import 那个模块。"""
        called = []
        stage, _, _ = bare_navigator(page=EMPTY_PAGE, dismiss=lambda: called.append(1))
        self.assertFalse(stage.tap("我的", exact=True, scrolls=0))
        self.assertTrue(called)


class FailureSemanticsTests(unittest.TestCase):
    """按文字导航的失败语义逐个保持：一处也不许改成统一的「抛」或「返回假」。"""

    def setUp(self):
        clocked(self, fast, Clock())

    def assert_returns_false(self, call):
        stage, _, _ = bare_navigator(page=EMPTY_PAGE)
        self.assertIs(call(stage), False)

    def test_false_is_returned_by_the_optional_paths(self):
        self.assert_returns_false(lambda s: s.tap("我的"))
        self.assert_returns_false(lambda s: s.tap("我的", exact=True, scrolls=0))
        self.assert_returns_false(lambda s: s.entry("设置"))
        self.assert_returns_false(lambda s: s.go("我的", "设置"))
        self.assert_returns_false(lambda s: s.tab("我的", maxwait=0))
        self.assert_returns_false(lambda s: s.tap_icon("设置"))

    def test_enter_raises_because_the_caller_has_no_fallback(self):
        stage, _, _ = bare_navigator(page=EMPTY_PAGE)
        with self.assertRaisesRegex(RuntimeError, "未找到入口"):
            stage.enter("设置")


class SingleWordListTests(unittest.TestCase):
    def test_the_settings_signature_matches_the_frozen_baseline(self):
        self.assertEqual(navigator.SETTINGS_MARKS, BASE_SETTINGS_MARKS)

    def test_the_settings_signature_lives_only_in_this_module(self):
        self.assertIs(fast.SETTINGS_MARKS, navigator.SETTINGS_MARKS)
        for owner in (fast.Phone, fast.Screen, fast.Toggler, fast.Launcher,
                      fast.SettingsSearch, fast.Dismisser):
            self.assertFalse(hasattr(owner, "SETTINGS_MARKS"),
                             f"{owner.__name__} 上又出现了一份设置页签名")


class CallGraphTests(unittest.TestCase):
    """阶段之间不互相 import，整张图无环：环从方法之间挪到模块之间不算断掉（#1044）。"""

    STAGES = {"toggler", "launcher", "settings_search", "dismisser", "navigator"}
    BASES = {"connection", "screen", "session"}

    def package_imports(self):
        """{模块: 它 import 的同包模块}，来自 `tool/phone/` 的源码。"""
        out = {}
        for path in sorted((ROOT / "tool" / "phone").glob("*.py")):
            if path.name == "__init__.py":
                continue
            graph = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("phone."):
                    graph.add(node.module.split(".", 1)[1])
                elif isinstance(node, ast.Import):
                    graph.update(a.name.split(".", 1)[1] for a in node.names
                                 if a.name.startswith("phone."))
            out[path.stem] = graph
        return out

    def test_phases_only_import_the_bases(self):
        graph = self.package_imports()
        self.assertTrue(self.STAGES <= set(graph), f"阶段模块不全：{sorted(graph)}")
        for stage in self.STAGES:
            others = graph[stage] - self.BASES
            self.assertEqual(others, set(), f"{stage} 直接 import 了 {sorted(others)}：应走注入的窄接口")

    def test_the_import_graph_has_no_cycle(self):
        graph = self.package_imports()

        def walk(node, seen):
            if node in seen:
                return True
            return any(walk(nxt, seen | {node}) for nxt in graph.get(node, ()))

        cycles = [node for node in graph if walk(node, frozenset())]
        self.assertEqual(cycles, [], f"包内 import 成环：{cycles}")


if __name__ == "__main__":
    unittest.main()
