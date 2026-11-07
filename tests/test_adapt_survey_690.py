"""#690：adapt survey 试入口（三种结局、只读边界）与 `-s S adapt <子命令>` 的转发。

运行：python -m unittest discover -s tests -v
"""
import contextlib
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adapt
import entries
import run
import vocab
from fixtures import Clock, fake_adb, phone_mock

DIRECT = entries.Direct("com.android.settings", ".ad.AdServiceSettings", "个性化广告推荐")
ONE_FAMILY = {"xiaomi": {"系统广告": entries.Entry(menu="设置 → 广告服务", direct=(DIRECT,))}}


def word(text, group="系统广告", family="xiaomi", kind=vocab.OFF):
    return vocab.Word(text, kind, family, group, "系统·广告服务", "xiaomi-M154FF/recipe.py", 10)


def survey_phone(focus="", texts=(), start=("", 0), packages="package:com.android.settings\n", brand="xiaomi"):
    """假手机：只回答 survey 会问的四件事（品牌、am start、读屏、安装表），其余 Mock 记调用。"""
    p = phone_mock()
    p.locked.return_value = False
    p.focus.return_value = focus
    node = ET.fromstring('<node text="x"/>')
    p.texts.return_value = [(text, (0, 0, 1, 1), node) for text in texts]

    def shell(cmd, timeout=None):
        if cmd.startswith("getprop ro.product.brand"):
            return types.SimpleNamespace(output=brand, exit_code=0)
        if cmd.startswith("am start"):
            return types.SimpleNamespace(output=start[0], exit_code=start[1])
        if cmd == "pm list packages":
            return types.SimpleNamespace(output=packages, exit_code=0)
        return types.SimpleNamespace(output="", exit_code=0)

    p.reader.shell.side_effect = shell
    return p


def run_survey(p, words):
    clock = Clock()
    out = io.StringIO()
    with patch.object(entries, "ENTRIES", ONE_FAMILY), contextlib.redirect_stdout(out):
        rows = adapt.survey(p, "xiaomi", words, now=clock.time, sleep=clock.sleep)
    return rows, out.getvalue()


class SurveyResultTests(unittest.TestCase):
    def test_landed_page_reports_only_the_words_of_its_own_group(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings",
                         texts=("个性化 广告推荐", "系统工具广告", "热搜"))
        rows, out = run_survey(p, [word("个性化广告推荐"), word("别的开关"),
                                   word("热搜", group="全局搜索")])
        self.assertEqual([row["landed"] for row in rows], [True])
        self.assertIn("✓ 系统广告 com.android.settings.ad.AdServiceSettings", out)
        # 空格差异按 key_of() 归一化后仍算命中；同家族别的分组的词不报
        self.assertIn("同组词条：个性化广告推荐", out)
        self.assertNotIn("别的开关", out)
        self.assertNotIn("热搜", out)

    def test_wrong_landing_reports_the_actual_focus_and_no_page_text(self):
        p = survey_phone(focus="com.android.settings/.Settings", texts=("个性化广告推荐",))
        rows, out = run_survey(p, [word("个性化广告推荐")])
        self.assertEqual([row["landed"] for row in rows], [False])
        self.assertIn("落在别处（实际 com.android.settings/.Settings）", out)
        self.assertNotIn("个性化广告推荐", out)          # 只打实际包/类，不打页面文字

    def test_am_start_error_is_reported_as_unopenable(self):
        p = survey_phone(start=("Error: Activity not started, unable to resolve Intent", 0))
        rows, out = run_survey(p, [word("个性化广告推荐")])
        self.assertEqual(rows[0]["landed"], False)
        self.assertIn("✗ 打不开  系统广告 com.android.settings.ad.AdServiceSettings", out)

    def test_nonzero_exit_code_is_unopenable_even_with_quiet_output(self):
        p = survey_phone(start=("", 1))
        rows, _out = run_survey(p, [word("个性化广告推荐")])
        self.assertEqual(rows[0]["landed"], False)

    def test_agreement_popup_is_only_annotated(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("同意", "个性化广告推荐"))
        _rows, out = run_survey(p, [word("个性化广告推荐")])
        self.assertIn("弹着协议，没有点", out)
        p.tap.assert_not_called()
        p.click.assert_not_called()

    def test_survey_never_taps_or_clicks(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("个性化广告推荐",))
        run_survey(p, [word("个性化广告推荐")])
        p.tap.assert_not_called()
        p.click.assert_not_called()
        p.off.assert_not_called()
        p.dismiss.assert_not_called()

    def test_app_and_search_tail_lines(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=(), packages="")
        _rows, out = run_survey(p, [])
        self.assertIn("同族脚本用过的 App：装了 0 / 1 个（没装：com.android.settings）", out)
        self.assertIn("设置搜索词可试：无", out)


class SurveyEntryTests(unittest.TestCase):
    def run_cmd(self, phone, argv=("-s", "FAKE")):
        out = io.StringIO()
        with patch.object(adapt, "Phone") as factory, \
                patch.object(adapt.vocab, "scan", return_value=types.SimpleNamespace(words=[word("个性化广告推荐")])), \
                patch.object(entries, "ENTRIES", ONE_FAMILY), contextlib.redirect_stdout(out):
            factory.return_value.__enter__.return_value = phone
            code = adapt.cmd_survey(list(argv))
        return code, out.getvalue()

    def test_any_landing_exits_zero_and_goes_home(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("个性化广告推荐",))
        code, _out = self.run_cmd(p)
        self.assertEqual(code, 0)
        p.reader.press.assert_called_once_with("home")

    def test_no_landing_exits_one(self):
        p = survey_phone(focus="com.android.settings/.Settings")
        with patch.object(adapt, "survey", return_value=[{"landed": False}]):
            code, _out = self.run_cmd(p)
        self.assertEqual(code, 1)

    def test_locked_phone_exits_one_without_a_single_tap(self):
        p = survey_phone()
        p.locked.return_value = True
        with self.assertRaises(SystemExit) as caught:
            self.run_cmd(p)
        self.assertIn("锁屏", str(caught.exception.code))
        p.tap.assert_not_called()
        p.click.assert_not_called()
        p.off.assert_not_called()
        calls = [str(call) for call in p.reader.shell.call_args_list]
        self.assertFalse([call for call in calls if "am start" in call], calls)

    def test_family_without_direct_entries_exits_one(self):
        p = survey_phone(brand="huawei")
        with self.assertRaises(SystemExit) as caught:
            self.run_cmd(p)
        self.assertIn("还没有直达入口记录", str(caught.exception.code))

    def test_missing_serial_prints_usage(self):
        with self.assertRaises(SystemExit) as caught:
            adapt.cmd_survey([])
        self.assertIn("用法", str(caught.exception.code))


class DispatchTest(unittest.TestCase):
    """文档写的 `-s 序列号 adapt <子命令>` 要真转发；gen 不碰手机，仍打印帮助。"""

    def setUp(self):
        fake_adb(self)

    def forward(self, argv):
        with patch.object(run, "py") as spy, contextlib.redirect_stdout(io.StringIO()):
            code = run.dispatch(argv)
        return code, spy

    def test_documented_order_is_forwarded(self):
        code, spy = self.forward(["-s", "FAKE", "adapt", "survey"])
        spy.assert_called_once_with("adapt.py", "survey", "-s", "FAKE")
        self.assertIs(code, spy.return_value)

    def test_explore_keeps_its_package_arguments(self):
        _code, spy = self.forward(["-s", "FAKE", "adapt", "explore", "com.a", "com.b"])
        spy.assert_called_once_with("adapt.py", "explore", "-s", "FAKE", "com.a", "com.b")

    def test_gen_and_unknown_subcommands_still_print_help(self):
        for argv in (["-s", "FAKE", "adapt", "gen", "f.tsv"], ["-s", "FAKE", "adapt", "nope"]):
            code, spy = self.forward(argv)
            self.assertEqual(code, 0)
            spy.assert_not_called()

    def test_bare_adapt_still_accepts_the_engine_order(self):
        _code, spy = self.forward(["adapt", "survey", "-s", "FAKE"])
        spy.assert_called_once_with("adapt.py", "survey", "-s", "FAKE")


if __name__ == "__main__":
    unittest.main()
