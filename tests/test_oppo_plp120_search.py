"""PLP120 参考脚本：ColorOS 17 的搜索段先用全局搜索自己的 scheme，旧版本仍走桌面入口（#165）。

ColorOS 17 的桌面搜索页没有「设置」入口，`SearchSettingActivity` 又未导出（SecurityException）；
参考脚本以前只认桌面下滑那条路，四段子页全部空跑。这里守住：
能直达就执行、直达不了退回旧入口、两条都不通只报一句跳过原因；
认页不能把同一个包里的搜索首页当成设置页；借给别的机型时不动内容源。
"""
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock

RECIPE = ROOT / "recipes/oppo-PLP120/recipe.py"
SEARCH_PACKAGE = "com.heytap.quicksearchbox"
SETTINGS_FOCUS = f"{SEARCH_PACKAGE}/{SEARCH_PACKAGE}.ui.activity.SearchSettingActivity"
HOME_FOCUS = f"{SEARCH_PACKAGE}/{SEARCH_PACKAGE}.ui.activity.SearchHomeActivity"
LAUNCHER_SEARCH = "com.android.launcher/com.android.launcher.LauncherSearchActivity"
# 冻结的认页词表：以后删词、改词都要在这里一起改，否则真机上认不出设置页不会报红。
RECOGNIZED_TITLES = {"搜索范围", "功能管理", "搜索引擎", "消息管理", "账号与隐私"}
SETTINGS_TEXTS = ["搜索范围", "自定义搜索结果", "搜索引擎", "功能管理"]


def load(phone, only=("__no_steps__",), out=None):
    scope, _ = load_recipe(phone, RECIPE, only, out)
    return scope


def texts(*labels):
    return [(label, (0, 0, 0, 0), {}) for label in labels]


class Plp120SearchEntryTests(unittest.TestCase):
    def phone(self, focus, labels, tap=False):
        p = phone_mock(W=1080, H=2340)
        p.locked.return_value = False
        p.focus.return_value = focus
        p.texts.return_value = texts(*labels)
        p.tap.return_value = tap
        return p

    def run_search_settings(self, scope):
        with patch.object(scope["time"], "sleep"):
            return scope["search_settings"]()

    def test_scheme_entry_opens_the_search_settings_page(self):
        """ColorOS 17：scheme 落在全局搜索设置页时直接使用，不再去桌面下滑。"""
        p = self.phone(SETTINGS_FOCUS, SETTINGS_TEXTS)
        scope = load(p)
        self.assertTrue(self.run_search_settings(scope))
        self.assertIn("gs://search/setting", p.d.shell.call_args_list[0].args[0])
        p.tap.assert_not_called()

    def test_wait_keeps_polling_until_the_settings_page_renders(self):
        """Android 17 页面画得慢：设置页要过几次采样才认得出，不能只判一次。"""
        calls = {"n": 0}

        def focus():
            calls["n"] += 1
            return SETTINGS_FOCUS if calls["n"] >= 4 else HOME_FOCUS

        p = self.phone(HOME_FOCUS, SETTINGS_TEXTS)
        p.focus.side_effect = focus
        scope = load(p)
        self.assertTrue(self.run_search_settings(scope))
        self.assertGreaterEqual(calls["n"], 4)

    def test_search_home_is_not_mistaken_for_the_settings_page(self):
        """同一个包的搜索首页上也有「搜索范围」文字：前台 Activity 不是设置页就不算打开。"""
        p = self.phone(HOME_FOCUS, ["搜索范围"], tap=False)
        scope = load(p)
        self.assertFalse(self.run_search_settings(scope))
        self.assertEqual([call.args[0] for call in p.tap.call_args_list], ["设置"])

    def test_old_build_falls_back_to_the_desktop_search_entry(self):
        """ColorOS 16：scheme 打不开设置页时，仍走桌面下滑 → 搜索页底部「设置」。"""
        p = self.phone(LAUNCHER_SEARCH, ["语音输入"])
        tapped = {"done": False}
        after_tap = {"n": 0}

        def focus():
            if not tapped["done"]:
                return LAUNCHER_SEARCH
            after_tap["n"] += 1
            return SETTINGS_FOCUS if after_tap["n"] >= 3 else LAUNCHER_SEARCH

        def tap(label, **kwargs):
            tapped["done"] = True
            return label == "设置"

        p.focus.side_effect = focus
        p.texts.side_effect = lambda: texts(*(SETTINGS_TEXTS if tapped["done"] else ["语音输入"]))
        p.tap.side_effect = tap
        scope = load(p)
        self.assertTrue(self.run_search_settings(scope))
        commands = [call.args[0] for call in p.d.shell.call_args_list]
        self.assertIn("gs://search/setting", commands[0])
        self.assertTrue(any("input keyevent HOME" in c for c in commands))
        self.assertTrue(any("input swipe" in c for c in commands))
        self.assertGreaterEqual(after_tap["n"], 3)

    def test_step_prints_one_skip_reason_instead_of_empty_sub_sections(self):
        """两条入口都不通：只打印一句跳过原因，不再进四段子页各报一次没找到。"""
        p = self.phone(LAUNCHER_SEARCH, ["语音输入"], tap=False)
        out = io.StringIO()
        with patch.object(time, "sleep"):
            load(p, only=("下拉搜索",), out=out)
        log = out.getvalue()
        self.assertIn("跳过", log)
        self.assertIn("全局搜索设置页", log)
        p.off.assert_not_called()
        self.assertEqual([call.args[0] for call in p.tap.call_args_list], ["设置"])

    def test_recognized_page_titles_are_frozen(self):
        """认页词表写死在测试里：删词、改词会当场变红。"""
        scope = load(self.phone(SETTINGS_FOCUS, SETTINGS_TEXTS))
        self.assertEqual(scope["SEARCH_TITLES"], RECOGNIZED_TITLES)

    def test_step_runs_the_search_sub_sections_when_the_page_opens(self):
        """能直达设置页时，搜索范围 / 功能管理 / 隐私三段照常执行。"""
        p = self.phone(SETTINGS_FOCUS, SETTINGS_TEXTS, tap=True)
        with patch.object(time, "sleep"):
            load(p, only=("下拉搜索",))
        calls = p.off.call_args_list
        self.assertEqual([call.kwargs["page"] for call in calls],
                         ["下拉搜索·搜索范围", "下拉搜索·功能管理", "下拉搜索·隐私"])
        self.assertEqual(calls[0].kwargs["only"],
                         ["榜单", "小说", "购物", "个性化推荐", "精选资讯"])

    def test_borrowed_recipe_leaves_content_sources_alone(self):
        """借给别的机型时（安全模式）只关推荐位：榜单 / 小说 / 购物在 ColorOS 17 上是内容源。"""
        p = self.phone(SETTINGS_FOCUS, SETTINGS_TEXTS, tap=True)
        p.safe_mode = True
        with patch.object(time, "sleep"):
            load(p, only=("下拉搜索",))
        self.assertEqual(p.off.call_args_list[0].kwargs["only"], ["个性化推荐", "精选资讯"])

    def test_group_title_does_not_block_the_privacy_sub_page(self):
        """ColorOS 17 的「账号与隐私」是分组标题、点不进去：要能直接找到下面的「隐私」。"""
        p = self.phone(SETTINGS_FOCUS, SETTINGS_TEXTS)

        def tap(label, **kwargs):
            return label != "账号与隐私"

        p.tap.side_effect = tap
        with patch.object(time, "sleep"):
            load(p, only=("下拉搜索",))
        pages = [call.kwargs["page"] for call in p.off.call_args_list]
        self.assertIn("下拉搜索·隐私", pages)


if __name__ == "__main__":
    unittest.main()
