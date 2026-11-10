"""#901：OPPO / 一加 / realme 负一屏入口的手势加固与失败现场。

两份脚本（PMX110 / PLZ110）的同一段实现在这里一起守：滑动起点让开 ColorOS 的左缘返回手势区、
已经在负一屏时不再滑走、认不到头像入口时留下停在哪个 Activity 与页面结构摘要。真机落点仍要另验。
"""
import ast
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import fake_phone, load_recipe, phone_mock

RECIPES = {
    "PMX110": ROOT / "recipes" / "oppo-PMX110" / "recipe.py",
    "PLZ110": ROOT / "recipes" / "oneplus-PLZ110" / "recipe.py",
}
LAUNCHER = "com.android.launcher/com.android.launcher3.Launcher"
ASSISTANT_SETTING = "com.coloros.assistantscreen/setting.RecommendServiceSettingActivity"
MARKET_SETTING = "com.heytap.market/com.heytap.market.settings.SettingActivity"
HOME = "input keyevent HOME"

ICON_PAGE = '''<hierarchy>
  <node resource-id="com.coloros.assistantscreen:id/head_icon" clickable="true"
        bounds="[40,80][160,200]"/>
</hierarchy>'''
MARKET_PAGE = '''<hierarchy>
  <node resource-id="com.heytap.market:id/head_icon" clickable="true"
        bounds="[900,80][1020,200]"/>
</hierarchy>'''
HOME_PAGE = '''<hierarchy>
  <node text="桌面" bounds="[0,0][1080,120]"/>
  <node class="android.widget.Switch" checkable="true" checked="true" bounds="[900,300][1000,380]"/>
</hierarchy>'''


def page(xml):
    return ET.fromstring(xml)


def phone(**over):
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.focus.return_value = LAUNCHER
    p.texts.return_value = []
    p.on_screen.return_value = True
    for key, value in over.items():
        setattr(p, key, value)
    return p


def shell_recorder(p, swipes, before=HOME_PAGE, after=ICON_PAGE, focus_before=LAUNCHER,
                   after_home=HOME_PAGE):
    """记下发过的 swipe；按 HOME / 滑动推进页面与前台，让第一次滑动就到达负一屏。"""
    state = {"front": focus_before, "home": False}

    def shell(cmd):
        if cmd.startswith("input keyevent HOME"):
            state["front"], state["home"] = LAUNCHER, True
        elif cmd.startswith("input swipe"):
            swipes.append(cmd)
        return SimpleNamespace(output="", exit_code=0)

    p.d.shell.side_effect = shell
    p.focus.side_effect = lambda: state["front"]
    p.tree.side_effect = lambda: page(after if swipes else after_home if state["home"] else before)


def commands(p):
    return [call.args[0] for call in p.d.shell.call_args_list]


def load(p, recipe):
    scope, _ = load_recipe(p, recipe)
    return scope


def action(scope, recipe, name):
    """取真实分段的函数体，以便给它的协作者注入替身；不复制分段实现。"""
    node = next(n for n in ast.parse(recipe.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.decorator_list
                and n.decorator_list[0].args[0].value == name)
    node.decorator_list, node.name = [], "selected_action"
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(recipe), "exec"), scope)
    return scope["selected_action"]


class AssistantEntryTests(unittest.TestCase):
    def test_swipe_starts_inside_the_left_edge_gesture_zone(self):
        """起点从 W//7 起：ColorOS 最左一条是返回 / 侧边栏手势区，8 落在里面。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                swipes = []
                shell_recorder(p, swipes)
                icon = load(p, recipe)["assistant_icon"]()
                self.assertEqual(icon.get("resource-id"),
                                 "com.coloros.assistantscreen:id/head_icon")
                self.assertEqual(swipes, [f"input swipe {1080 // 7} 1200 {1080 * 6 // 7} 1200 250"])
                self.assertGreater(1080 // 7, 8)

    def test_already_on_the_screen_skips_home_and_swipes(self):
        """已经在负一屏：不再按 HOME、不再右滑，否则把自己划走。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                p.tree.return_value = page(ICON_PAGE)
                load(p, recipe)["assistant_icon"]()
                self.assertEqual(commands(p), [])

    def test_assistant_settings_page_is_not_treated_as_arrived(self):
        """停在负一屏设置页：包名是它自己的，但不在首页，必须回桌面重进。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                swipes = []
                shell_recorder(p, swipes, focus_before=ASSISTANT_SETTING)
                load(p, recipe)["assistant_icon"]()
                self.assertEqual(commands(p)[:2], [HOME, HOME])
                self.assertEqual(swipes, [f"input swipe {1080 // 7} 1200 {1080 * 6 // 7} 1200 250"])

    def test_a_foreign_app_avatar_is_not_the_assistant_screen(self):
        """别的 App 上的同资源名头像不算到达：不按 HOME 就会在错的应用里点下去。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                swipes = []
                shell_recorder(p, swipes, before=MARKET_PAGE, focus_before=MARKET_SETTING)
                icon = load(p, recipe)["assistant_icon"]()
                self.assertEqual(commands(p)[:2], [HOME, HOME])
                self.assertEqual(icon.get("resource-id"), "com.coloros.assistantscreen:id/head_icon")

    def test_known_home_texts_are_enough_to_stop_swiping(self):
        """头像入口认不出但首页两条文案都在：停在原地报现场，不再一轮轮滑走。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                p.tree.return_value = page(HOME_PAGE)
                p.texts.return_value = [("我的服务", (0, 100, 300, 160), {}),
                                        ("添加卡片", (0, 200, 300, 260), {})]
                with self.assertRaisesRegex(RuntimeError, "未确认负一屏头像入口"):
                    load(p, recipe)["assistant_icon"]()
                self.assertEqual(commands(p), [])
                self.assertIn("唯一的负一屏头像入口", p.note_miss.call_args.args[0])

    def test_one_of_the_two_home_texts_is_not_enough(self):
        """只有一条文案的页面（如商店「我的」页）不当成负一屏：同族实测要求两条都在。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                p.texts.return_value = [("我的服务", (0, 100, 300, 160), {})]
                swipes = []
                shell_recorder(p, swipes)
                load(p, recipe)["assistant_icon"]()
                self.assertEqual(commands(p)[:2], [HOME, HOME])
                self.assertEqual(len(swipes), 1)

    def test_home_is_pressed_twice_when_another_app_is_in_front(self):
        """不在桌面：先两次 HOME 回默认桌面并等页面站稳，再滑；顺序不能反。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                swipes = []
                shell_recorder(p, swipes, focus_before="com.tencent.mm/.ui.LauncherUI")
                load(p, recipe)["assistant_icon"]()
                self.assertEqual(commands(p)[:2], [HOME, HOME])
                self.assertIn("input swipe", commands(p)[2])
                p.await_page.assert_any_call()

    def test_home_landing_on_the_screen_stops_before_swiping(self):
        """HOME 也可能正好落在负一屏（PLR110 实测）：到了就不再滑，否则把自己划走。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                swipes = []
                shell_recorder(p, swipes, after_home=ICON_PAGE)
                load(p, recipe)["assistant_icon"]()
                self.assertEqual(commands(p), [HOME])
                self.assertEqual(swipes, [])

    def test_swiping_stops_when_home_does_not_bring_the_desktop_back(self):
        """HOME 被吞掉时不能在别的 App 里连做右滑。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                p.focus.return_value = "com.tencent.mm/.ui.LauncherUI"
                p.tree.return_value = page(HOME_PAGE)
                with self.assertRaisesRegex(RuntimeError, "未停在系统桌面"):
                    load(p, recipe)["assistant_icon"]()
                self.assertFalse(any("input swipe" in c.args[0]
                                     for c in p.d.shell.call_args_list))

    def test_missing_entry_reports_where_the_swipe_stopped(self):
        """认不到头像入口：输出带上停在哪个 Activity 与页面结构摘要，文案保持不变。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                out = io.StringIO()
                p = fake_phone(size=(1080, 2340), stages=((0.0, HOME_PAGE),),
                               focus=((0.0, LAUNCHER),), await_page=lambda *a, **k: None,
                               say=lambda *a, **k: print(*a, file=out, flush=True))  # noqa: B023 - 当轮创建当轮消费，load() 同步执行
                with self.assertRaisesRegex(RuntimeError, "未确认负一屏头像入口"):
                    load(p, recipe)["assistant_icon"]()
                text = out.getvalue()
                self.assertIn("停在 com.android.launcher", text)
                self.assertIn("标题", text)
                self.assertIn("开关", text)
                self.assertIn("结构", text)
                self.assertIn("读到 0 个", text)

    def test_switches_after_the_entrance_are_unchanged(self):
        """头像入口在：点它进设置页，随后仍是「推荐服务」→「热点资讯」两步。"""
        for name, recipe in RECIPES.items():
            with self.subTest(name):
                p = phone()
                p.tree.return_value = page(ICON_PAGE)
                scope = load(p, recipe)
                for helper in ("row", "close_named", "open_page", "hide_carousel"):
                    scope[helper] = Mock()
                action(scope, recipe, "负一屏")()
                self.assertEqual([c.args[0] for c in scope["row"].call_args_list],
                                 ["设置", "推荐服务"])
                self.assertIn("InfoFlowSettingActivity", scope["open_page"].call_args.args[0])
                scope["close_named"].assert_called_once_with(["热点资讯"], "热点资讯")
                scope["hide_carousel"].assert_called_once_with()
                p.click.assert_called_once()
                self.assertEqual(commands(p), [])


if __name__ == "__main__":
    unittest.main()
