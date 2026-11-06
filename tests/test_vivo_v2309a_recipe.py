"""V2309A：底栏用引擎 p.tab()、齿轮只认上半屏、行内点击落在行中间（#530）。

三处入口差异都来自 V2309A 真机读数；参考脚本按 V2547DA 的写法在这台上空转 216 秒。
"""
from pathlib import Path
import sys
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import run
from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/vivo-V2309A/recipe.py"

# 「我的」页真机读数：右上角是无文字齿轮；下面还有一条含「设置」的可点行当诱饵（#305）。
DECOY_ROW = ('<node class="android.widget.TextView" text="去功能设置里重新开启"'
             ' clickable="true" bounds="[0,1900][1260,1990]"/>')
# 主题商店那类「设置壁纸」图块：描述里含「设置」但不是入口（#374）。
DECOY_TILE = ('<node class="android.widget.ImageView" content-desc="设置壁纸"'
              ' clickable="true" bounds="[0,900][540,1200]"/>')
GEAR_ICON = ('<node class="android.widget.Button" content-desc="设置"'
             ' clickable="true" bounds="[1079,199][1221,340]"/>')
ABOUT_ROW = ('<node class="android.widget.LinearLayout" clickable="true" bounds="[0,1600][1260,1740]">'
             '<node class="android.widget.TextView" text="关于" clickable="false"'
             ' bounds="[104,1632][182,1684]"/></node>')
NOTIFY_ROW = ('<node class="android.widget.LinearLayout" clickable="true" bounds="[0,1200][1260,1360]">'
              '<node class="android.widget.TextView" text="消息提醒" clickable="false"'
              ' bounds="[104,1248][260,1300]"/></node>')

GEAR_CENTER = (1150, 269)
ABOUT_ROW_CENTER_X = 504          # 行宽 1260 的 40%，不是标题文字中心 143
ABOUT_ROW_CENTER_Y = 1670


def make_phone(nodes, **fields):
    p = phone_mock(W=1260, H=2800, **fields)
    p.tree.return_value = ET.fromstring(f"<hierarchy>{nodes}</hierarchy>")
    p.on_screen.return_value = True
    p.click.return_value = None
    p.scroll_more.return_value = False
    return p


def load(phone, only=None):
    scope, _ = load_recipe(phone, RECIPE, only)
    return scope


def call(scope, name, *args, **kwargs):
    return scope[name](*args, **kwargs)


class VivoV2309ARecipeTests(unittest.TestCase):
    def test_model_is_matched_without_reference_and_records_build(self):
        path, reference = run.recipe_for("V2309A", "vivo")
        self.assertFalse(reference)
        self.assertEqual(Path(path).parent.name, "vivo-V2309A")
        meta = run.recipe_meta(path)
        self.assertEqual(meta["build"], "PD2309E_A_16")
        self.assertEqual(meta["models"], ["V2309A"])
        self.assertEqual(meta["steps"],
                         ["系统广告", "全局搜索", "阅图锁屏", "应用商店", "浏览器", "i管家", "天气"])

    def test_store_uses_engine_bottom_tab_instead_of_exact_tap(self):
        """底栏读作「我的, 2个应用待更新,第5个, 共5个」：精确匹配落空，必须走 p.tab()。"""
        p = make_phone(GEAR_ICON + ABOUT_ROW + NOTIFY_ROW + DECOY_ROW)
        p.locked.return_value = False
        p.tab.return_value = True
        p.entry.return_value = False
        p.start.return_value = None
        p.back.return_value = None
        scope = load(p, only=["应用商店"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        p.tab.assert_called_once_with("我的")
        self.assertNotIn("我的", [c.args[0] for c in p.tap.call_args_list if c.args])

    def test_missing_bottom_tab_fails_the_step_loudly(self):
        """停在开屏或推荐页时 p.tab() 返回假：整段算失败，不接着点齿轮。"""
        p = make_phone(GEAR_ICON + ABOUT_ROW + DECOY_ROW)
        p.locked.return_value = False
        p.tab.return_value = False
        p.start.return_value = None
        p.back.return_value = None
        scope = load(p, only=["应用商店"])
        self.assertEqual(scope["FAILED_STEPS"], ["应用商店"])
        p.click.assert_not_called()

    def test_gear_is_picked_even_when_decoy_row_comes_first(self):
        p = make_phone(DECOY_ROW + GEAR_ICON)
        scope = load(p)
        self.assertTrue(call(scope, "gear_top"))
        p.click.assert_called_once_with(*GEAR_CENTER)

    def test_gear_does_not_click_decoy_when_gear_is_absent(self):
        p = make_phone(DECOY_ROW)
        scope = load(p)
        self.assertFalse(call(scope, "gear_top"))
        p.click.assert_not_called()

    def test_gear_skips_tiles_whose_label_merely_contains_settings(self):
        """「设置壁纸」这种含「设置」的描述不算入口：判据走引擎的精确匹配（#374）。"""
        p = make_phone(DECOY_TILE + DECOY_ROW + GEAR_ICON)
        scope = load(p)
        self.assertTrue(call(scope, "gear_top"))
        p.click.assert_called_once_with(*GEAR_CENTER)

    def test_about_row_clicks_row_middle_not_title_text(self):
        """点左侧标题文字不跳转（V1986A 同此），落点要落在行宽 40% 处。"""
        p = make_phone(ABOUT_ROW)
        scope = load(p)
        self.assertTrue(call(scope, "tap_row", "关于"))
        p.click.assert_called_once_with(ABOUT_ROW_CENTER_X, ABOUT_ROW_CENTER_Y)
        self.assertNotEqual(ABOUT_ROW_CENTER_X, 143)

    def test_notification_page_only_targets_marketing_channel(self):
        """商店「消息提醒」9 个开关里只有「资讯活动提醒」是营销，其余是服务提醒。"""
        p = make_phone(GEAR_ICON + ABOUT_ROW + NOTIFY_ROW + DECOY_ROW)
        p.locked.return_value = False
        p.tab.return_value = True
        p.entry.return_value = True          # 关于页的各个子页都当作存在
        p.start.return_value = None
        p.back.return_value = None
        scope = load(p, only=["应用商店"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        pages = {c.kwargs.get("page"): c.kwargs.get("only") for c in p.off.call_args_list}
        self.assertEqual(pages.get("商店·消息提醒"), ["资讯活动提醒"])


if __name__ == "__main__":
    unittest.main()
