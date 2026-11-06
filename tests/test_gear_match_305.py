"""HyperOS 机型脚本的 gear()：只认设置图标，不把正文/描述里含「设置」的干扰行当成入口（#305）。"""
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock

# 干扰样本来自 #305 与 #374 的真机读数。
STORE_ROW = ('<node class="android.widget.TextView" text="去功能设置里重新开启"'
             ' clickable="true" bounds="[0,600][1080,680]"/>')
THEME_TILE = ('<node class="android.widget.ImageView" content-desc="设置壁纸"'
              ' clickable="true" bounds="[0,900][540,1200]"/>')
GEAR_ICON = ('<node class="android.widget.ImageView" content-desc="设置"'
             ' clickable="true" bounds="[950,120][1040,210]"/>')
MORE_MENU = ('<node class="android.widget.ImageView" content-desc="更多"'
             ' clickable="true" bounds="[980,120][1040,180]"/>')
TEXT_ENTRY = ('<node class="android.widget.TextView" text="设置"'
              ' clickable="true" bounds="[100,900][300,980]"/>')
LOW_GEAR = ('<node class="android.widget.ImageView" content-desc="设置"'
            ' clickable="true" bounds="[950,1500][1040,1590]"/>')
# 工具栏图标本身不可点、文字正好是「设置」：靠尺寸启发式命中（test_release_regressions 守同一类页面）。
TOOLBAR_TEXT_ICON = ('<node class="android.widget.ImageView" text="设置"'
                     ' clickable="false" bounds="[900,100][1020,220]"/>')
# 齿轮的 id 形态：iv_setting 要认，securitySettingSwitchLayout 不认（后者是「应用安全检测」入口）。
ID_GEAR = ('<node class="android.widget.ImageView" resource-id="com.android.market:id/iv_setting"'
           ' clickable="true" bounds="[950,120][1040,210]"/>')
ID_SECURITY = ('<node class="android.widget.TextView"'
               ' resource-id="com.xiaomi.market:id/securitySettingSwitchLayout"'
               ' clickable="true" bounds="[0,1400][1080,1500]"/>')

GEAR_CENTER = (995, 165)


def hyperos_recipes():
    """定义了 gear() 的小米 / 红米机型脚本。"""
    for path in sorted(ROOT.glob("recipes/*/recipe*.py")):
        if not path.parent.name.startswith(("xiaomi-", "redmi-")):
            continue
        if "def gear(" in path.read_text(encoding="utf-8"):
            yield path


def make_phone(nodes):
    p = phone_mock(W=1080, H=2400)
    p.tree.return_value = ET.fromstring(f"<hierarchy>{nodes}</hierarchy>")
    p.on_screen.return_value = True
    p.find.return_value = None
    p.tap.return_value = True
    return p


def call_gear(path, phone, **kwargs):
    scope, _ = load_recipe(phone, path)
    return scope["gear"](**kwargs)


class GearMatcherTests(unittest.TestCase):
    def each(self, nodes):
        return [(path, make_phone(nodes)) for path in hyperos_recipes()]

    def label(self, path):
        return f"{path.parent.name}/{path.stem}"

    def test_store_row_is_not_mistaken_for_settings(self):
        for path, phone in self.each(STORE_ROW + GEAR_ICON):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER)

    def test_theme_tile_is_not_mistaken_for_settings(self):
        for path, phone in self.each(THEME_TILE + GEAR_ICON):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "没找到真齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER)

    def test_interference_row_alone_is_not_a_settings_entry(self):
        for path, phone in self.each(STORE_ROW):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear(path, phone), "把干扰行当成了设置入口")
                phone.click.assert_not_called()

    def test_security_switch_layout_id_is_not_a_settings_entry(self):
        for path, phone in self.each(ID_SECURITY):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear(path, phone), "把 securitySettingSwitchLayout 当成设置入口")
                phone.click.assert_not_called()

    def test_gear_identified_by_setting_word_in_its_id(self):
        for path, phone in self.each(ID_GEAR):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "没认出 iv_setting 形态的齿轮")
                self.assertEqual(phone.click.call_args_list[0].args, GEAR_CENTER)

    def test_more_menu_still_reaches_the_gear(self):
        for path, phone in self.each(MORE_MENU):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "没走通「更多」菜单")
                phone.tap.assert_called_with("设置", exact=True, scrolls=0)

    def test_text_settings_entry_still_reachable(self):
        for path, phone in self.each(TEXT_ENTRY):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone), "点不到文字「设置」")
                self.assertEqual(phone.click.call_args_list[0].args, (200, 940))

    def test_toolbar_text_icon_without_clickable_flag_still_opens_settings(self):
        for path, phone in self.each(TOOLBAR_TEXT_ICON):
            with self.subTest(recipe=self.label(path)):
                self.assertTrue(call_gear(path, phone, toolbar_only=True), "没点到不可点的工具栏图标")
                self.assertEqual(phone.click.call_args_list[0].args, (960, 160))

    def test_toolbar_only_ignores_gear_below_the_toolbar(self):
        for path, phone in self.each(LOW_GEAR):
            with self.subTest(recipe=self.label(path)):
                self.assertFalse(call_gear(path, phone, toolbar_only=True),
                                 "在工具栏模式点了页面中部的齿轮")


if __name__ == "__main__":
    unittest.main()
