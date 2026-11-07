"""品牌词库（tool/vocab.py）与 adapt survey：词从脚本里读对、按品牌分、只打印已知的词。"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import adapt  # noqa: E402
import vocab  # noqa: E402


def recipes(**files):
    """{"xiaomi-A1": 源码} → 临时 recipes 目录。"""
    tmp = tempfile.TemporaryDirectory()
    for name, src in files.items():
        folder = Path(tmp.name, name)
        folder.mkdir()
        folder.joinpath("recipe.py").write_text(textwrap.dedent(src), encoding="utf-8")
    return tmp


class ReadRecipeTest(unittest.TestCase):
    def read(self, src):
        return vocab.read_recipe(textwrap.dedent(src))

    def test_only_and_keep(self):
        w = self.read('p.off(only=["个性化推荐", "开屏广告"], keep=["应用更新"], page="x")')
        self.assertEqual(w["off"], ["个性化推荐", "开屏广告"])
        self.assertEqual(w["keep"], ["应用更新"])

    def test_word_lists_in_variables(self):
        w = self.read('''
            HOT = ["热搜", "资讯"]
            p.off(only=HOT, page="x")
        ''')
        self.assertEqual(w["off"], ["热搜", "资讯"])

    def test_word_lists_in_for_loops(self):
        w = self.read('''
            for name in ["营销服务推荐", "热门推荐管理"]:
                p.off(only=[name], page="x")
        ''')
        self.assertEqual(w["off"], ["营销服务推荐", "热门推荐管理"])

    def test_page_tables_in_for_loops(self):
        w = self.read('''
            for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"])]:
                pass
        ''')
        self.assertEqual(w["entries"], ["主页设置", "搜索设置"])
        self.assertEqual(w["off"], ["宫格位推送", "猜你想搜"])

    def test_entries_from_every_helper(self):
        w = self.read('''
            maybe("隐私设置")
            tap_any("隐私", "隐私政策")
            p.tap("服务管理", exact=True)
            p.entry("通知设置", scrolls=2)
            p.go("我的", "设置")
            p.tab("发现")
        ''')
        self.assertEqual(w["entries"], ["隐私设置", "隐私", "隐私政策", "服务管理", "通知设置", "我的", "设置", "发现"])

    def test_search_words_and_packages(self):
        w = self.read('''
            p.setting("广告", "广告与隐私")
            p.start("com.a.b", ".Settings")
            p.start(pkg)
        ''')
        self.assertEqual(w["search"], ["广告"])
        self.assertEqual(w["packages"], ["com.a.b"])

    def test_close_named_lists_count_as_off(self):
        w = self.read('close_named(["智能推荐服务"], "标题", "com.a", "页")')
        self.assertEqual(w["off"], ["智能推荐服务"])


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = recipes(**{
            "xiaomi-A1": 'p.off(only=["推送消息", "广告"], page="x")\np.start("com.x.app", ".SettingActivity")',
            "redmi-B2": 'p.off(only=["广告"], keep=["推送消息"], page="x")\np.start("com.x.app")',
            "vivo-V1": 'p.off(only=["广告"], page="x")',
            "oppo-P1": 'p.off(only=["广告"], page="x")',
            "zzz-T1": 'p.off(only=["不该进库"], page="x")',
        })
        self.addCleanup(self.tmp.cleanup)
        self.brands = vocab.scan(self.tmp.name)

    def test_sub_brands_merge_into_the_family(self):
        self.assertEqual(self.brands["xiaomi"].models, {"A1", "B2"})
        self.assertEqual(self.brands["xiaomi"].off["广告"], {"A1", "B2"})

    def test_unknown_brand_stays_out(self):
        self.assertEqual(set(self.brands), {"xiaomi", "vivo", "oppo"})

    def test_a_word_closed_on_one_model_and_kept_on_another_is_flagged(self):
        self.assertEqual(vocab.conflicts(self.brands["xiaomi"]), ["推送消息"])
        self.assertEqual(vocab.conflicts(self.brands["vivo"]), [])

    def test_common_words_span_brands(self):
        self.assertEqual(set(vocab.common_words(self.brands)), {"广告"})

    def test_speedups_list_models_that_open_the_app_without_the_page(self):
        ups = vocab.speedups(self.tmp.name)
        self.assertEqual(ups["xiaomi"], [("com.x.app.SettingActivity", ["A1"], ["B2"])])

    def test_app_home_pages_are_not_speedups(self):
        tmp = recipes(**{"xiaomi-A1": 'p.start("com.x.app", ".MainTabActivity")', "xiaomi-B2": 'p.start("com.x.app")'})
        self.addCleanup(tmp.cleanup)
        self.assertEqual(vocab.speedups(tmp.name), {})


class GapsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = recipes(**{
            "honor-A1": 'close_named(["个性化广告推荐", "摇一摇"], "音乐", "com.a", "页")',
            "honor-B2": 'p.off(only=["摇一摇"], page="x")',
            "vivo-V1": 'p.off(only=["别的品牌"], page="x")',
        })
        self.addCleanup(self.tmp.cleanup)

    def test_lists_words_other_models_of_the_brand_close(self):
        # 真实发生过：CLE-AN00 的音乐段漏了 WKL-AN20 关掉的两个广告开关
        self.assertEqual(vocab.gaps(self.tmp.name, "honor-B2"), {"个性化广告推荐": {"A1"}})

    def test_words_from_other_brands_are_not_gaps(self):
        self.assertNotIn("别的品牌", vocab.gaps(self.tmp.name, "honor-B2"))

    def test_nothing_missing(self):
        self.assertEqual(vocab.gaps(self.tmp.name, "honor-A1"), {})

    def test_unknown_folder(self):
        self.assertIsNone(vocab.gaps(self.tmp.name, "honor-NOPE"))
        self.assertIsNone(vocab.gaps(self.tmp.name, "nokia-A1"))


class DocTest(unittest.TestCase):
    def test_doc_is_generated_from_the_recipes(self):
        doc = (ROOT / "docs" / "清单" / "词库.md").read_text(encoding="utf-8")
        self.assertEqual(doc, vocab.markdown(str(ROOT / "recipes")),
                         "机型脚本变了：跑 python3 tool/vocab.py > docs/清单/词库.md")

    def test_real_recipes_are_all_readable(self):
        brands = vocab.scan(str(ROOT / "recipes"))
        self.assertIn("个性化推荐", brands["xiaomi"].off.keys() | brands["vivo"].off.keys())
        self.assertGreater(sum(len(b.models) for b in brands.values()), 30)

    def test_community_doc_carries_no_contact_or_serial(self):
        doc = (ROOT / "docs" / "清单" / "词库-社区线索.md").read_text(encoding="utf-8")
        self.assertIn("未经核实", doc)
        self.assertNotRegex(doc, r"[\w.]+@[\w.]+")
        self.assertNotRegex(doc, r"\b[A-Z0-9]{14,}\b")


class CommunityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = recipes(**{"xiaomi-A1": 'p.off(only=["广告服务"], page="x")\np.start("com.miui.x", ".KnownSettings")'})
        self.addCleanup(self.tmp.cleanup)

    def found(self, *bodies):
        items = [{"number": i + 1, "title": "", "body": b} for i, b in enumerate(bodies)]
        return vocab.community(items, self.tmp.name)

    def test_new_ad_word_is_collected_with_its_issue(self):
        self.assertEqual(self.found("小米上有个「热门推荐」开关")["xiaomi"]["words"], {"热门推荐": {1}})

    def test_word_already_in_a_recipe_is_skipped(self):
        self.assertEqual(self.found("小米的「广告服务」")["xiaomi"]["words"], {})

    def test_non_ad_quotes_and_sentences_are_skipped(self):
        words = self.found("小米「蓝牙」「没有关闭任何广告」「关了 12 个广告」")["xiaomi"]["words"]
        self.assertEqual(words, {})

    def test_issue_about_two_brands_gives_no_words(self):
        self.assertEqual(dict(self.found("小米和 vivo 都有「热门推荐」")), {})

    def test_activity_goes_to_its_family_by_package(self):
        found = self.found("页面 com.vivo.x/.PrivacySettings 还有 com.unknown.y/.Page")
        self.assertEqual(found["vivo"]["activities"], {"com.vivo.x.PrivacySettings": {1}})
        self.assertEqual(set(found), {"vivo"})

    def test_known_page_and_package_fragment_are_skipped(self):
        found = self.found("com.miui.x/.KnownSettings com.miui.x/.settings")
        self.assertEqual(found["xiaomi"]["activities"], {})

    def test_bare_activity_name_gets_its_package(self):
        found = self.found("com.miui.y/PrivacyPage")
        self.assertEqual(found["xiaomi"]["activities"], {"com.miui.y.PrivacyPage": {1}})


class SurveyTest(unittest.TestCase):
    PAGE = ("com.a", "com.a.SettingActivity")

    def phone(self, shown, start="Status: ok", installed=True, focus="com.a/com.a.SettingActivity"):
        p = Mock()
        p.focus.return_value = focus

        def shell(cmd):
            out = Mock()
            out.output = ("package:/x" if installed else "") if cmd.startswith("pm path") else start
            return out

        p.d.shell.side_effect = shell
        p.texts.return_value = [(t, (0, 0, 1, 1), None) for t in shown]
        return p

    def brand(self):
        b = vocab.Brand(models={"A"})
        b.off["个性化广告"].add("A")
        b.entries["隐私设置"].add("A")
        b.entries["设置"].add("A")
        b.packages["com.a"].add("A")
        return b

    def run_survey(self, p):
        lines = []
        rows = adapt.survey(p, self.brand(), {self.PAGE: {"A"}}, log=lines.append)
        return rows, "\n".join(lines)

    def test_reports_known_words_on_the_page(self):
        rows, out = self.run_survey(self.phone(["个性化广告", "隐私设置", "设置"]))
        self.assertEqual(rows[0]["switches"], ["个性化广告"])
        self.assertEqual(rows[0]["entries"], ["隐私设置"])
        self.assertIn("✓", out)

    def test_never_prints_page_text_outside_the_vocabulary(self):
        # 页面上可能有账号名和装机列表
        _, out = self.run_survey(self.phone(["肉呆的账号", "个性化广告"]))
        self.assertNotIn("肉呆的账号", out)

    def test_never_taps_anything(self):
        p = self.phone(["同意", "个性化广告"])
        rows, out = self.run_survey(p)
        p.click.assert_not_called()
        p.tap.assert_not_called()
        p.off.assert_not_called()
        p.start.assert_not_called()         # p.start 的弹窗处理会替人点「取消」
        self.assertTrue(rows[0]["agreement"])
        self.assertIn("没有点", out)

    def test_app_not_installed_is_skipped_and_listed(self):
        rows, out = self.run_survey(self.phone([], installed=False))
        self.assertEqual(rows, [])
        self.assertIn("0 / 1", out)
        self.assertIn("没装：com.a", out)

    def test_page_that_will_not_open(self):
        rows, out = self.run_survey(self.phone([], start="Error: Activity not started"))
        self.assertFalse(rows[0]["opened"])
        self.assertIn("打不开", out)

    def test_landing_in_another_app_reads_nothing(self):
        p = self.phone(["个性化广告"], focus="com.other/.Main")
        rows, out = self.run_survey(p)
        self.assertFalse(rows[0]["landed"])
        self.assertEqual(rows[0]["switches"], [])
        self.assertIn("落到别处", out)

    def test_dollar_in_a_page_name_is_quoted(self):
        p = self.phone([])
        adapt.survey(p, self.brand(), {("com.a", "com.a.S$Inner"): {"A"}}, log=lambda _: None)
        started = [c.args[0] for c in p.d.shell.call_args_list if c.args[0].startswith("am start")]
        self.assertIn("'com.a.S$Inner'", started[0])


class RouteTest(unittest.TestCase):
    def test_documented_form_reaches_adapt(self):
        import run
        with patch.object(run, "py", return_value=0) as py:
            run.dispatch(["-s", "S", "adapt", "survey"])
            py.assert_called_once_with("adapt.py", "survey", "-s", "S")
            py.reset_mock()
            run.dispatch(["-s", "S", "adapt", "explore", "com.a"])
            py.assert_called_once_with("adapt.py", "explore", "-s", "S", "com.a")


if __name__ == "__main__":
    unittest.main()
