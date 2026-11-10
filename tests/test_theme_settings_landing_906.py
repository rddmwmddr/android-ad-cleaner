"""主题段进设置页要校验落点（#906）。

0.4.x 上报库里「停在 thememanager 首页、整页 0 个标题 0 个开关」与「设置页本来就少一项」
同形：`go()` / `gear()` 的返回值被丢掉，`off()` 又把空页当成功收尾。用例护住三层：

- 所有小米 / 红米脚本的主题段都不再有未被消费的 `go()` / `gear()` 返回值，点名开关走
  `require_switches()` / `close_named()`，也不再经主题商店冷启动（AST 守卫，一份都不能漏）；
- 导航没到设置页 / 设置页上一个点名开关都没读到时整段失败，报错带页面现场；
- 导航正常时输出与改动前逐字一致（不多打一行提示）。

真机缺口：这里只验到「失败会响亮地失败」，验不到 OS3.0.3xx 上「我的 → 齿轮」之后到底能不能
进设置页——那要等一次真实运行（票面「验证缺口」）。
"""
import ast
import io
import sys
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import entries  # noqa: E402
import fast  # noqa: E402
from fixtures import load_recipe, phone_mock  # noqa: E402

THEME = "com.android.thememanager"
STORE = "com.miui.themestore"
INSTALLED = "package:/system/app/ThemeManager/ThemeManager.apk"
FOCUS = f"{THEME}/.ThemeResourceProxyTabActivity"
SWITCH = "每次联网时通知"
PRIVACY = "个性化推荐"

# 主题首页：底部一个「我的」标签（y > 85% 屏高），「我的」页右上角是 desc=设置 的齿轮。
PAGE = """<hierarchy rotation="0">
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
<node class="android.widget.ImageView" content-desc="设置" bounds="[950,180][1040,260]" clickable="true"/>
<node class="android.widget.TextView" text="我的" bounds="[0,2180][270,2380]" clickable="true"/>
</node>
</hierarchy>"""

EMPTY = """<hierarchy rotation="0">
<node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]"/>
</hierarchy>"""


def theme_steps():
    """[(路径, 段函数)]：所有带 `@step("主题")` 的小米 / 红米脚本段。"""
    found = []
    for path in sorted((ROOT / "recipes").glob("*/recipe*.py")):
        if entries.family(path.parent.name.split("-", 1)[0]) != "xiaomi":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "step"
                        and dec.args and getattr(dec.args[0], "value", None) == "主题"):
                    found.append((path, node))
    return found


def unconsumed(fn):
    """段里返回值被丢掉的 `go()` / `gear()` 所在行号（#906）。

    算「消费」的只有三种落点：if/while 的判据、赋值/返回、交给 require() 系断言。
    """
    parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
    bad = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in {"go", "gear"}:
            continue
        cur, parent = node, parents.get(node)
        while isinstance(parent, (ast.BoolOp, ast.UnaryOp, ast.Compare, ast.IfExp)):
            cur, parent = parent, parents.get(parent)
        consumed = ((isinstance(parent, (ast.If, ast.While)) and cur is parent.test)
                    or isinstance(parent, (ast.Assign, ast.Return))
                    or (isinstance(parent, ast.Call)
                        and getattr(parent.func, "id", "") in {"require", "close_named",
                                                               "require_switches"}))
        if not consumed:
            bad.append(node.lineno)
    return bad


def called_names(fn):
    return {getattr(n.func, "id", "") for n in ast.walk(fn) if isinstance(n, ast.Call)}


class ThemeLandingGuardTests(unittest.TestCase):
    def test_every_theme_step_consumes_go_and_gear(self):
        steps = theme_steps()
        self.assertGreaterEqual(len(steps), 15, "主题段的机型脚本少找了")
        for path, fn in steps:
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                self.assertEqual(unconsumed(fn), [], f"{path.name}: 丢了导航的返回值")

    def test_every_theme_step_verifies_the_named_switch(self):
        for path, fn in theme_steps():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                self.assertTrue(called_names(fn) & {"require_switches", "close_named"},
                                f"{path.name}: 点名开关没有校验")

    def test_theme_steps_launch_the_manager_directly(self):
        """#906：不再经主题商店冷启动。落点被系统转走时由 start_or_skip 收成跳过（#902）。"""
        for path, fn in theme_steps():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                literals = {n.value for n in ast.walk(fn)
                            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                self.assertNotIn(STORE, literals, f"{path.name}: 还在冷启动主题商店")


class ThemeSettingsLandingTests(unittest.TestCase):
    def phone(self, page=PAGE, state=None, nav=True):
        """主题首页 + 「我的」标签可点；state 是设置页上读到的开关（{标题: 是否开着}）。"""
        p = phone_mock()
        p.W, p.H = 1080, 2400
        p.locked = lambda: False
        p.focus = lambda: FOCUS
        p.tree.return_value = ET.fromstring(page)
        texts = [("我的", (0, 2180, 270, 2380), ET.fromstring(page))] if page is PAGE else []
        p.texts.return_value = texts
        rows = dict(state or {})

        def shell(command, timeout=None):
            return SimpleShell(INSTALLED if command == f"pm path {THEME}" else "")
        p.d.shell.side_effect = shell
        p.switches.side_effect = lambda *a, **k: [(name, on, (900, 500)) for name, on in rows.items()]

        def fake_off(*a, only=None, **k):
            for name in only or ():
                if name in rows:
                    rows[name] = False
        p.off.side_effect = fake_off
        p.go.return_value = nav
        p.tab.return_value = nav
        p.tap.return_value = nav
        p.find.return_value = (900, 150) if nav else None
        p.entry.return_value = True
        # 页面现场用真实实现：报错文案正是这条用例要护住的东西；包一层 Mock 好数调用次数。
        p._page_diagnosis = lambda: fast.Phone._page_diagnosis(p)
        p.page_evidence = Mock(side_effect=lambda titles=(): fast.Phone.page_evidence(p, list(titles)))
        return p

    def test_zero_named_switches_fails_the_step_with_page_evidence(self):
        for path, _ in theme_steps():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = self.phone(state={})
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["FAILED_STEPS"], ["主题"])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                p.off.assert_not_called()
                text = out.getvalue()
                self.assertIn("未识别全部目标开关", text)
                self.assertIn(FOCUS, text)
                self.assertIn("当次读到 0 个开关", text)

    def test_navigation_that_never_reaches_the_settings_page_fails_the_step(self):
        for path, _ in theme_steps():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = self.phone(page=EMPTY, state={SWITCH: True}, nav=False)
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["FAILED_STEPS"], ["主题"])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                p.off.assert_not_called()
                text = out.getvalue()
                self.assertIn(FOCUS, text)
                self.assertIn("当次读到 0 个开关", text)

    def test_navigation_to_the_settings_page_keeps_the_output_unchanged(self):
        for path, _ in theme_steps():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = self.phone(state={SWITCH: True, PRIVACY: True})
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                # 与改动前逐字一致：不多打行，失败才用的页面现场也不去读（时长行与脚本末尾的台账行不算）
                section = out.getvalue().split("== 主题", 1)[1]
                self.assertNotIn("✗", section)
                self.assertNotIn("  · ", section)
                p.page_evidence.assert_not_called()
                self.assertEqual(p.off.call_args_list[0].kwargs["page"], "主题·设置")


class ThemeUnreachableStillSkippedTests(unittest.TestCase):
    def test_missing_thememanager_is_skipped_not_failed(self):
        """没有主题管理包的机器仍按跳过收尾，不算失败（#902 的口径不变）。"""
        for path, _ in theme_steps():
            with self.subTest(recipe=str(path.relative_to(ROOT))):
                p = phone_mock()
                p.locked = lambda: False
                p.d.shell.side_effect = lambda command, timeout=None: SimpleShell("")
                out = io.StringIO()
                scope, _ = load_recipe(p, path, only="主题", out=out)
                self.assertEqual(scope["SKIPPED_STEPS"], [])
                self.assertEqual(scope["FAILED_STEPS"], [])
                self.assertIn("本机没有主题管理包，跳过", out.getvalue())
                p.start.assert_not_called()


class SimpleShell:
    """`p.d.shell` 的返回形状：只要 output / exit_code。"""

    def __init__(self, output=""):
        self.output, self.exit_code = output, 0


if __name__ == "__main__":
    unittest.main()
