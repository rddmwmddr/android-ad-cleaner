"""#939：机型脚本「未确认页面」这类失败要先留下页面骨架，再抛原来的错。

OPPO 家族参考脚本与一加 15T 的 `page()` 是三段落点判据（包名、Activity、页面标题）的
复制品，三段失败都只抛一句错、不留现场：#910 的「未确认页面「游戏中心」」分不清是标题
改名了、还是页面根本没加载完。现在失败时先打一行与入口失败同形的
「· 「X」没找到；停在 …；结构摘要」，再抛原来的错 —— 报错文案是上报与用例认的那句，
逐字不变，现场走那条独立输出行。实现只留在 `recipe_kit.page` 一处。
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

import fast
from fixtures import fake_phone, load_recipe

# 两份复制品的宿主脚本（#939 的改动面）：注入面里叫 `page`，脚本不再自带。
RECIPES = ("oppo-PMX110/recipe.py", "oneplus-PLZ110/recipe.py")
GAME = "com.nearme.gamecenter"
SETTING_PAGE = "com.nearme.gamecenter/com.nearme.gamecenter.setting.SettingActivity"
LAUNCHER = "com.coloros.launcher/.Launcher"
GAME_MAIN = "com.nearme.gamecenter/.MainActivity"

PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.nearme.gamecenter" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="设置" bounds="[48,96][360,180]" />
  </node>
</hierarchy>"""

OTHER_PAGE = """<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.nearme.gamecenter" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="游戏中心" bounds="[48,96][360,180]" />
  </node>
</hierarchy>"""


def phone(focus=SETTING_PAGE, screen=PAGE, **fields):
    """假设备 + 真的 `say`：`fake_phone` 默认把 `say` 关掉，这里要看现场那一行。"""
    p = fake_phone(size=(1080, 2340), stages=((0.0, screen),), focus=((0.0, focus),), **fields)
    p.log = True
    p.say = fast.Phone.say.__get__(p)
    p.conn.say = fast.Connection.say.__get__(p.conn)      # 现场行走连接基座（ADR-0033）
    return p


class PageEvidenceTests(unittest.TestCase):
    """报错第一句逐字比对：现场必须走独立输出行，不能拼进消息（上报与用例都认那句）。"""

    def run_page(self, recipe, *args, focus=SETTING_PAGE, screen=PAGE):
        p = phone(focus, screen)
        scope, _ = load_recipe(p, ROOT / "recipes" / recipe)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(RuntimeError) as caught:
                scope["page"](*args)
        return str(caught.exception), out.getvalue()

    def test_a_wrong_title_keeps_the_old_message_and_leaves_the_page(self):
        message, printed = self.run_page(RECIPES[0], "游戏中心", GAME, "SettingActivity")
        self.assertEqual(message, "未确认页面「游戏中心」，未操作开关")
        self.assertIn(f"· 「游戏中心」没找到；停在 {SETTING_PAGE}；标题 1 个", printed)

    def test_a_wrong_package_names_the_package_not_the_title(self):
        """落点跑偏时标题往往就在屏上：现场行写缺的那个包名，别把人引去查改名。"""
        message, printed = self.run_page(RECIPES[0], "游戏中心", GAME, "SettingActivity",
                                         focus=LAUNCHER)
        self.assertEqual(message, "未进入目标应用，未操作开关")
        self.assertIn(f"· 「{GAME}」没找到；停在 {LAUNCHER}；", printed)

    def test_a_wrong_activity_names_the_activity(self):
        message, printed = self.run_page(RECIPES[0], "游戏中心", GAME, "SettingActivity",
                                         focus=GAME_MAIN)
        self.assertEqual(message, "未进入目标设置页，未操作开关")
        self.assertIn(f"· 「SettingActivity」没找到；停在 {GAME_MAIN}；", printed)

    def test_a_confirmed_page_prints_no_evidence(self):
        p = phone(SETTING_PAGE, OTHER_PAGE)
        scope, _ = load_recipe(p, ROOT / "recipes" / RECIPES[0])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scope["page"]("游戏中心", GAME, "SettingActivity")
        self.assertNotIn("没找到", out.getvalue())

    def test_a_group_of_titles_is_joined_in_the_evidence(self):
        """一段可以给几种等价标题：现场行把这一组都列出来，别只报第一个。"""
        message, printed = self.run_page(RECIPES[0], ("游戏中心", "游戏空间"), GAME, "SettingActivity")
        self.assertEqual(message, "未确认页面「游戏中心、游戏空间」，未操作开关")
        self.assertIn("· 「游戏中心 / 游戏空间」没找到；", printed)

    def test_both_copies_report_identically(self):
        for recipe in RECIPES:
            with self.subTest(recipe=recipe):
                message, printed = self.run_page(recipe, "游戏中心", GAME, "SettingActivity")
                self.assertEqual(message, "未确认页面「游戏中心」，未操作开关")
                self.assertIn(f"· 「游戏中心」没找到；停在 {SETTING_PAGE}；", printed)


class SingleSourceTests(unittest.TestCase):
    def test_the_wording_lives_only_in_recipe_kit(self):
        """三句判据各自复制一份就会再分叉成两种输出形状（#939）。"""
        sources = sorted((ROOT / "recipes").glob("*/recipe*.py"))
        sources += [path for name in ("tool", "gui") for path in sorted((ROOT / name).rglob("*.py"))]
        offenders = [path.relative_to(ROOT).as_posix() for path in sources
                     if path != ROOT / "tool" / "recipe_kit.py"
                     and "未操作开关" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
