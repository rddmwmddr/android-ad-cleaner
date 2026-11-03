"""设置入口判据收进引擎（#530）：描述或正文恰好是「设置」，或 id 末段是 setting 词。

原先 13 份小米 / 红米脚本各复制一份 `icon_hit`（#305 引入），vivo 参考脚本的 `gear()` 又是
另一套子串匹配。本文件分三层守：引擎谓词本身、13 份脚本不再各留副本、vivo `gear()` 在说明行
两种先后下都只点齿轮。
"""
import ast
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from row import icon_hit
from fixtures import phone_mock


class IconHitTests(unittest.TestCase):
    def test_exact_desc_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"content-desc": "设置"}))

    def test_exact_english_text_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"text": "settings"}))

    def test_matching_is_case_insensitive(self):
        self.assertTrue(icon_hit({"text": "SETTINGS"}))

    def test_desc_with_extra_words_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit({"content-desc": "设置壁纸"}))

    def test_body_text_containing_settings_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit({"text": "去功能设置里重新开启"}))

    def test_id_starting_with_setting_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"resource-id": "com.android.market:id/iv_setting"}))

    def test_setting_embedded_in_a_longer_id_segment_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit(
            {"resource-id": "com.xiaomi.market:id/securitySettingSwitchLayout"}))

    def test_setting_suffix_segment_in_id_is_a_settings_entry(self):
        self.assertTrue(icon_hit({"resource-id": "com.vivo.appstore:id/gear_setting"}))

    def test_empty_node_is_not_a_settings_entry(self):
        self.assertFalse(icon_hit({}))

    def test_whitespace_around_the_label_is_ignored(self):
        self.assertTrue(icon_hit({"content-desc": "  设置  "}))


class ScriptsShareOnePredicateTests(unittest.TestCase):
    """13 份小米 / 红米脚本不再各留一份 icon_hit，改用引擎这一份（#530）。"""

    def test_no_recipe_defines_its_own_icon_hit(self):
        offenders = []
        for path in sorted(ROOT.glob("recipes/*/recipe*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "icon_hit":
                    offenders.append(f"{path.parent.name}/{path.name}:{node.lineno}")
        self.assertEqual(offenders, [], "脚本里还留着 icon_hit 的本地副本")


VIVO_RECIPES = (ROOT / "recipes/vivo-V2547DA/recipe.py",
                ROOT / "recipes/vivo-V2547DA/recipe_android17.py")


def calls_on_p(tree, method):
    """`p.<method>(...)` 调用点。"""
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == method
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "p"]


class VivoStoreEntryTests(unittest.TestCase):
    """vivo 参考脚本的商店段改用引擎入口，不再按精确文字点底栏（#530）。"""

    def test_store_section_uses_the_bottom_tab_helper(self):
        for path in VIVO_RECIPES:
            with self.subTest(recipe=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = [a.value for call in calls_on_p(tree, "tab")
                         for a in call.args if isinstance(a, ast.Constant)]
                self.assertIn("我的", names, "商店段没改用 p.tab(\"我的\")")


# 齿轮与两种说明行：正文版来自 #305 的小米样本，description 版才是 vivo 旧子串匹配真正会误点的形状。
GEAR = ('<node class="android.widget.ImageView" content-desc="设置" clickable="true"'
        ' bounds="[950,120][1040,210]"/>')
GEAR_CENTER = (995, 165)
TEXT_DECOY = ('<node class="android.widget.TextView" text="去功能设置里重新开启" clickable="true"'
              ' bounds="[0,600][1080,680]"/>')
DESC_DECOY = ('<node class="android.widget.TextView" content-desc="去功能设置里重新开启"'
              ' clickable="true" bounds="[0,900][1080,980]"/>')
# 看起来像图标但没勾 clickable：旧实现漏掉，新实现按尺寸启发式认。
UNCLICKABLE_GEAR = ('<node class="android.widget.ImageView" content-desc="设置" clickable="false"'
                    ' bounds="[900,100][1020,220]"/>')


def make_phone(nodes):
    p = phone_mock(W=1080, H=2400)
    p.tree.return_value = ET.fromstring(f"<hierarchy>{nodes}</hierarchy>")
    p.on_screen.return_value = True
    p.tap.return_value = False
    return p


def call_gear(path, phone):
    scope = {"p": phone, "ONLY": ["__no_steps__"]}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
        with patch.object(scope["time"], "sleep"):
            return scope["gear"]()


class VivoGearTests(unittest.TestCase):
    """vivo 参考脚本的 gear() 用引擎判据：说明行与齿轮并存时，两种先后都只点齿轮（#530）。

    vivo 旧实现按 content-desc / resource-id 子串匹配，把说明行排在前就会点它；收窄成精确判据
    后必须两种顺序都只点齿轮，这是这次唯一的行为变化，没有真机，只能靠合成页面守。
    """

    def each(self, nodes):
        return [(path, make_phone(nodes)) for path in VIVO_RECIPES]

    def label(self, path):
        return path.name

    def test_text_decoy_before_the_gear_is_not_clicked(self):
        for path, phone in self.each(TEXT_DECOY + GEAR):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER)

    def test_text_decoy_after_the_gear_is_not_clicked(self):
        for path, phone in self.each(GEAR + TEXT_DECOY):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER)

    def test_desc_decoy_alone_is_not_a_settings_entry(self):
        for path, phone in self.each(DESC_DECOY):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear(path, phone), "把说明行当成了设置入口")
                phone.click.assert_not_called()

    def test_unclickable_icon_sized_gear_is_clicked(self):
        for path, phone in self.each(UNCLICKABLE_GEAR):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "没点到不可点的齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, (960, 160))


if __name__ == "__main__":
    unittest.main()
