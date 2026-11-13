"""真我 GT5 Pro（RMX3888 / ColorOS 15）机型脚本（#1083）：九段各自的去向与三处显式跳过。

脚本按报告者实测的落点写成，本仓库没有这台手机，所以这里只钉「路径与去向」：进哪一页、
关哪些点名的开关、哪几段在本机没有入口时按跳过收尾而不静默空跑。落点本身对不对要等真机复测。
"""
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))

from fixtures import load_recipe, phone_mock
from recipe_kit import MissingPackage
from recipe_meta import recipe_meta

RECIPE = ROOT / "recipes/oppo/RMX3888/RMX3888.toml"
SETTINGS = "com.android.settings"
MARKET = "com.heytap.market"
BROWSER = "com.heytap.browser"
STEPS = ["广告跟踪", "负一屏", "下拉搜索", "软件商店", "浏览器", "主题", "视频", "游戏中心", "小布建议"]


def make_phone(focus=SETTINGS + "/com.oplus.settings.OplusSettingsActivity"):
    p = phone_mock(W=1080, H=2400)
    p.locked.return_value = False
    p.texts.return_value = []
    p.find.return_value = True
    p.off.return_value = 0
    p.switches.return_value = []
    p.entry.return_value = False
    p.tap.return_value = True
    p.tab.return_value = True
    p.in_settings_page.return_value = True
    p.focus.return_value = focus
    return p


def run(phone, step):
    out = io.StringIO()
    scope, _ = load_recipe(phone, RECIPE, only=(step,), out=out)
    return scope, out.getvalue()


class MetaTests(unittest.TestCase):
    def test_meta_declares_the_model_the_build_and_nine_steps(self):
        meta = recipe_meta(RECIPE)
        self.assertEqual(meta["models"], ["RMX3888"])
        self.assertEqual(meta["build"], "RMX3888_15.0.0.420")
        self.assertEqual(meta["steps"], STEPS)

    def test_store_keep_holds_features_and_not_promotions(self):
        scope = load_recipe(make_phone(), RECIPE, None)[0]
        keep = scope["STORE_KEEP"]
        for name in ("帮助与客服", "应用安全", "我的专区：应用工具", "应用使用记录", "首页：AI搜索"):
            self.assertIn(name, keep)
        for name in ("首页：活动弹窗", "软件专区：福利", "游戏专区：活动集合"):
            self.assertNotIn(name, keep)


class AdTrackingTests(unittest.TestCase):
    def test_walks_the_privacy_more_path_and_closes_the_whole_page(self):
        p = make_phone("com.android.settings/com.oplus.settings.feature.notification.oaid.OAIDActivity")
        scope, _ = run(p, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual([call.args[0] for call in p.tap.call_args_list],
                         ["隐私", "更多", "设备标识与广告", "广告跟踪"])
        self.assertEqual(p.off.call_args.kwargs["page"], "广告跟踪")
        self.assertIsNone(p.off.call_args.kwargs.get("only"))

    def test_falls_back_when_the_more_group_is_missing(self):
        """有的版本「隐私」页没有「更多」这一级分组标题：退回直接点「设备标识与广告」。"""
        p = make_phone("com.android.settings/com.oplus.settings.feature.notification.oaid.OAIDActivity")
        p.tap.side_effect = lambda text, **kw: text != "更多"
        scope, _ = run(p, "广告跟踪")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual([call.args[0] for call in p.tap.call_args_list],
                         ["隐私", "更多", "隐私", "设备标识与广告", "广告跟踪"])
        p.off.assert_called_once()

    def test_safe_mode_skips_without_touching_the_phone(self):
        p = make_phone()
        p.safe_mode = True
        scope, printed = run(p, "广告跟踪")
        self.assertEqual(scope["SKIPPED_STEPS"], ["广告跟踪"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("安全模式不做整页全关", printed)
        p.d.shell.assert_not_called()
        p.tap.assert_not_called()
        p.off.assert_not_called()


class NegativeScreenTests(unittest.TestCase):
    FOCUS = "com.coloros.assistantscreen/com.oplus.assistantscreen.AssistantScreenActivity"

    def test_skips_when_the_layer_has_no_recommendation_rows(self):
        """本机这一层两个入口都没有：按跳过收尾并说明原因，不静默空跑。"""
        p = make_phone(self.FOCUS)
        p.entry.return_value = True                     # 「我的」入口在
        p.find.return_value = False                     # 两个推荐开关都不在
        p.scroll_more.return_value = False
        scope, printed = run(p, "负一屏")
        self.assertEqual(scope["SKIPPED_STEPS"], ["负一屏"])
        self.assertIn("没有可关的推荐位", printed)
        p.off.assert_not_called()

    def test_rows_are_probed_read_only_never_clicked(self):
        """存在性探测只能用 p.find：`maybe()` / `p.entry` 找到就点，点在开关行上把开关拨了。"""
        p = make_phone(self.FOCUS)
        p.entry.return_value = True
        p.find.side_effect = lambda text, **kw: text == "搜索框提示词"
        p.switches.return_value = []
        run(p, "负一屏")
        self.assertEqual([c.args[0] for c in p.entry.call_args_list], ["我的"])
        self.assertNotIn("搜索框提示词", [c.args[0] for c in p.tap.call_args_list])
        self.assertEqual([c.kwargs["only"] for c in p.off.call_args_list], [["搜索框提示词"]])

    def test_the_recommendation_service_master_switch_is_never_toggled(self):
        """「推荐服务」会连天气、步数、清理卡片一起删掉：只点开它的子页，关下面的轮播推荐。"""
        p = make_phone(self.FOCUS)
        p.entry.return_value = True
        p.find.side_effect = lambda text, **kw: text == "推荐服务"
        p.switches.return_value = []                    # 它是入口行，不是开关行
        run(p, "负一屏")
        p.off.assert_not_called()
        p.tap.assert_any_call("推荐服务", exact=True)
        p.tap.assert_any_call("不显示", exact=True, scrolls=0)

    def test_a_switch_row_named_recommendation_service_is_left_alone(self):
        """万一某版把它做成开关行：一个字都不动，留着给机主手动关轮播。"""
        p = make_phone(self.FOCUS)
        p.entry.return_value = True
        p.find.side_effect = lambda text, **kw: text == "推荐服务"
        p.switches.return_value = [("推荐服务", True, (40, 900, 1040, 1000))]
        _scope, printed = run(p, "负一屏")
        self.assertIn("按约定不拨", printed)
        self.assertNotIn("推荐服务", [c.args[0] for c in p.tap.call_args_list])
        p.off.assert_not_called()


class StoreTests(unittest.TestCase):
    def test_personal_recommendation_is_a_sub_page(self):
        p = make_phone()
        p.focus.side_effect = [MARKET + "/com.heytap.market.mine.ui.SettingActivity",
                               MARKET + "/com.heytap.market.mine.PersonalRecommendActivity"]
        scope, _ = run(p, "软件商店")
        self.assertEqual(scope["FAILED_STEPS"], [])
        pages = [(c.args, c.kwargs) for c in p.off.call_args_list]
        self.assertEqual(pages[0][1]["page"], "商店·服务管理")
        self.assertEqual(pages[1], ((), {"only": ["个性化推荐"], "page": "商店·个性化推荐"}))
        # 个性化推荐是入口行，要真的点进子页，不能在隐私页上就地关
        p.tap.assert_any_call("个性化推荐", exact=True)


class BrowserTests(unittest.TestCase):
    def test_a_missing_ad_management_entry_does_not_fake_success(self):
        """40.9.14.1 的「隐私」页已没有「广告管理」：打印出来、不关任何东西，本段不算失败。"""
        p = make_phone(BROWSER + "/com.heytap.browser.settings.component.BrowserPreferencesPage")
        p.tap.side_effect = lambda text, **kw: text != "广告管理"
        scope, printed = run(p, "浏览器")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("没有「广告管理」", printed)
        p.off.assert_not_called()


class VideoTests(unittest.TestCase):
    def test_skips_when_the_app_is_only_a_local_player(self):
        p = make_phone()
        p.entry.return_value = False
        scope, printed = run(p, "视频")
        self.assertEqual(scope["SKIPPED_STEPS"], ["视频"])
        self.assertIn("本地视频播放器", printed)
        p.off.assert_not_called()


class GameCenterTests(unittest.TestCase):
    def test_skips_through_the_engine_when_the_app_is_not_installed(self):
        p = make_phone()
        p.start.side_effect = MissingPackage("本机没有安装 com.nearme.gamecenter")
        scope, printed = run(p, "游戏中心")
        self.assertEqual(scope["SKIPPED_STEPS"], ["游戏中心"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("本机没有安装", printed)


class ThemeTests(unittest.TestCase):
    def test_skips_when_the_store_has_no_launch_screen(self):
        p = make_phone()
        p.start.side_effect = RuntimeError("无法打开 com.oplus.themestore：** No activities found to run")
        scope, printed = run(p, "主题")
        self.assertEqual(scope["SKIPPED_STEPS"], ["主题"])
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("没有启动界面", printed)

    def test_other_launch_failures_are_still_failures(self):
        """跳过只认「没有启动界面」这一种；被别的 App 抢前台这类仍记未完成。"""
        p = make_phone()
        p.start.side_effect = RuntimeError("com.oplus.themestore 没有进入前台，跳过本段（停在 com.android.launcher/.Launcher）")
        scope, printed = run(p, "主题")
        self.assertEqual(scope["FAILED_STEPS"], ["主题"])
        self.assertEqual(scope["SKIPPED_STEPS"], [])
        self.assertIn("没有进入前台", printed)


class SearchTests(unittest.TestCase):
    FOCUS = "com.heytap.quicksearchbox/com.heytap.quicksearchbox.ui.activity.SearchSettingActivity"

    def test_suspended_search_box_is_skipped_with_the_reason(self):
        p = make_phone("com.android.systemui/com.android.systemui.SuspendedAppActivity")
        scope, printed = run(p, "下拉搜索")
        self.assertEqual(scope["SKIPPED_STEPS"], ["下拉搜索"])
        self.assertIn("被挂起", printed)
        p.off.assert_not_called()

    def test_only_recommendation_rows_are_named(self):
        p = make_phone(self.FOCUS)
        scope, _ = run(p, "下拉搜索")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual([c.kwargs["only"] for c in p.off.call_args_list],
                         [["个性化推荐", "精选资讯"], ["搜索框提示词"], ["个性化推荐"]])
        self.assertEqual([c.kwargs["page"] for c in p.off.call_args_list],
                         ["下拉搜索·搜索范围", "下拉搜索·功能管理", "下拉搜索·隐私"])


class XiaobuTests(unittest.TestCase):
    FOCUS = "com.coloros.sceneservice/com.coloros.sceneservice.settings.SettingsActivity"

    def test_the_entry_is_called_ai_not_oppo_ai(self):
        p = make_phone(self.FOCUS)
        p.tap.side_effect = lambda text, **kw: text in ("AI", "资讯服务")
        scope, _ = run(p, "小布建议")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertEqual([c.args[0] for c in p.tap.call_args_list], ["AI", "资讯服务"])
        self.assertEqual(p.off.call_args.kwargs["only"], ["资讯服务"])

    def test_master_switch_already_off_is_reported_without_touching_anything(self):
        p = make_phone(self.FOCUS)
        p.tap.side_effect = lambda text, **kw: text == "AI"
        scope, printed = run(p, "小布建议")
        self.assertEqual(scope["FAILED_STEPS"], [])
        self.assertIn("总开关默认已关", printed)
        p.off.assert_not_called()

    def test_missing_entry_fails_instead_of_running_empty(self):
        p = make_phone(self.FOCUS)
        p.tap.side_effect = lambda text, **kw: False
        scope, _ = run(p, "小布建议")
        self.assertEqual(scope["FAILED_STEPS"], ["小布建议"])
        p.off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
