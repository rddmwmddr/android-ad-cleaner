"""#690：adapt survey 试入口（三种结局、只读边界）与 `-s S adapt <子命令>` 的转发；#740：带 -s 的误用不再静默成功。

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
    p.expect_page.return_value = True          # 默认看见判据文字；要测不看见时用例自己改
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


def run_survey(p, words, family="xiaomi", family_map=ONE_FAMILY):
    clock = Clock()
    out = io.StringIO()
    with patch.object(entries, "ENTRIES", family_map), contextlib.redirect_stdout(out):
        rows = adapt.survey(p, family, words, now=clock.time, sleep=clock.sleep)
    return rows, out.getvalue()


def shell_calls(p):
    return [call.args[0] for call in p.reader.shell.call_args_list]


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

    def test_launch_command_expands_relative_activity_and_clears_task(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings")
        run_survey(p, [])
        self.assertIn("am start -W -f 0x10008000 -n "
                      "com.android.settings/com.android.settings.ad.AdServiceSettings", shell_calls(p))

    def test_keep_task_pages_start_without_clear_task(self):
        """带清栈参数会立刻退出的页面只能裸启动（#165），否则 survey 会把它误报成落在别处。"""
        direct = entries.Direct("com.heytap.browser", ".settings.component.BrowserPreferencesPage", keep_task=True)
        p = survey_phone(focus="com.heytap.browser/com.heytap.browser.settings.component.BrowserPreferencesPage")
        fmap = {"oppo": {"浏览器": entries.Entry(menu="浏览器 → 设置", direct=(direct,))}}
        rows, _out = run_survey(p, [], family="oppo", family_map=fmap)
        self.assertEqual([row["landed"] for row in rows], [True])
        command = next(cmd for cmd in shell_calls(p) if cmd.startswith("am start"))
        self.assertNotIn("-f", command)

    def test_dollar_in_activity_is_shell_quoted(self):
        """vivo 的 `$` 类名不 quote 会被 shell 当变量吃掉。"""
        direct = entries.Direct("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo")
        p = survey_phone(focus="com.android.settings/com.android.settings.Settings$AdAndPrivacyActivityForOsTwo")
        fmap = {"vivo": {"系统广告": entries.Entry(menu="设置 → 广告与隐私", direct=(direct,))}}
        run_survey(p, [], family="vivo", family_map=fmap)
        command = next(cmd for cmd in shell_calls(p) if cmd.startswith("am start"))
        self.assertIn("'com.android.settings/com.android.settings.Settings$AdAndPrivacyActivityForOsTwo'", command)

    def test_landed_but_missing_expect_text_is_not_a_pass(self):
        """reach() 还要求看见判据文字：焦点对上了但内容不是那一页，引擎会换下一档。"""
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("别的文字",))
        p.expect_page.return_value = False
        rows, out = run_survey(p, [])
        self.assertEqual([(row["landed"], row["expect"]) for row in rows], [(True, False)])
        self.assertIn("! 系统广告 com.android.settings.ad.AdServiceSettings  落在这一页，但没看到「个性化广告推荐」", out)

    def test_half_dump_is_treated_as_empty_page_not_a_crash(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings")
        p.texts.side_effect = ET.ParseError
        rows, out = run_survey(p, [word("个性化广告推荐")])
        self.assertEqual([row["landed"] for row in rows], [True])
        self.assertIn("✓", out)
        self.assertNotIn("同组词条", out)


class SurveyEntryTests(unittest.TestCase):
    def run_cmd(self, phone, argv=("-s", "FAKE"), scanned=None):
        scanned = [word("个性化广告推荐")] if scanned is None else scanned
        out, err = io.StringIO(), io.StringIO()
        with patch.object(adapt, "Phone") as factory, \
                patch.object(adapt.vocab, "scan", return_value=types.SimpleNamespace(words=scanned)), \
                patch.object(entries, "ENTRIES", ONE_FAMILY), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            factory.return_value.__enter__.return_value = phone
            code = adapt.cmd_survey(list(argv))
        self.factory, self.err = factory, err.getvalue()
        return code, out.getvalue()

    def test_any_landing_exits_zero_and_goes_home(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("个性化广告推荐",))
        code, _out = self.run_cmd(p)
        self.assertEqual(code, 0)
        self.factory.assert_called_once_with("FAKE")
        p.reader.press.assert_called_once_with("home")

    def test_landed_without_the_expect_text_exits_one(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("别的文字",))
        p.expect_page.return_value = False
        code, _out = self.run_cmd(p)
        self.assertEqual(code, 1)

    def test_unknown_brand_exits_one(self):
        p = survey_phone(brand="nokia")
        code, _out = self.run_cmd(p)
        self.assertEqual(code, 1)
        self.assertIn("认不出品牌", self.err)

    def test_empty_vocabulary_exits_one(self):
        p = survey_phone()
        code, _out = self.run_cmd(p, scanned=[])
        self.assertEqual(code, 1)
        self.assertIn("词库是空的", self.err)

    def test_no_landing_exits_one(self):
        p = survey_phone(focus="com.android.settings/.Settings")
        with patch.object(adapt, "survey", return_value=[{"landed": False}]):
            code, _out = self.run_cmd(p)
        self.assertEqual(code, 1)

    def test_locked_phone_exits_one_without_a_single_tap(self):
        p = survey_phone()
        p.locked.return_value = True
        code, _out = self.run_cmd(p)
        self.assertEqual(code, 1)
        self.assertIn("锁屏", self.err)
        p.tap.assert_not_called()
        p.click.assert_not_called()
        p.off.assert_not_called()
        calls = [str(call) for call in p.reader.shell.call_args_list]
        self.assertFalse([call for call in calls if "am start" in call], calls)

    def test_family_without_direct_entries_exits_one(self):
        p = survey_phone(brand="huawei")
        code, _out = self.run_cmd(p)
        self.assertEqual(code, 1)
        self.assertIn("还没有直达入口记录", self.err)

    def test_missing_serial_prints_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = adapt.cmd_survey([])
        self.assertEqual(code, 1)
        self.assertIn("用法", err.getvalue())


class DispatchTest(unittest.TestCase):
    """文档写的 `-s 序列号 adapt <子命令>` 要真转发；gen 不碰手机，误带 -s 时明确报错。"""

    def setUp(self):
        fake_adb(self)

    def forward(self, argv, out=None):
        with patch.object(run, "py") as spy, patch.object(run, "adb_shell") as shell, \
                contextlib.redirect_stdout(out or io.StringIO()):
            code = run.dispatch(argv)
        self.shell = shell
        return code, spy

    def test_documented_order_is_forwarded(self):
        code, spy = self.forward(["-s", "FAKE", "adapt", "survey"])
        spy.assert_called_once_with("adapt.py", "survey", "-s", "FAKE")
        self.assertIs(code, spy.return_value)

    def test_forwarding_checks_the_device_first_so_the_error_is_readable(self):
        """设备不在时要在 run.py 里就变成人话，别让子进程抛 traceback（ADR-0005 的 NoAdb/断线出口）。"""
        self.forward(["-s", "FAKE", "adapt", "survey"])
        self.shell.assert_called_once_with("FAKE", "getprop ro.product.brand")

    def test_explore_keeps_its_package_arguments(self):
        _code, spy = self.forward(["-s", "FAKE", "adapt", "explore", "com.a", "com.b"])
        spy.assert_called_once_with("adapt.py", "explore", "-s", "FAKE", "com.a", "com.b")

    def test_check_is_forwarded_too(self):
        """三条要序列号的子命令各有一条守卫（#740 审查指出 check 那条先前没人走）。"""
        _code, spy = self.forward(["-s", "FAKE", "adapt", "check", "草稿.py"])
        spy.assert_called_once_with("adapt.py", "check", "-s", "FAKE", "草稿.py")

    def test_help_is_still_a_help(self):
        """`-s S adapt --help` 是求助不是误用：与顶层 -h 一样打印总入口帮助、rc 0（ADR-0005）。"""
        out = io.StringIO()
        code, spy = self.forward(["-s", "FAKE", "adapt", "--help"], out=out)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), run.__doc__ + "\n")
        spy.assert_not_called()
        self.shell.assert_not_called()

    def test_gen_with_a_serial_points_at_the_working_form(self):
        """gen 不碰手机，`-s S adapt gen` 是误用：以前打印总入口帮助并以 0 退出，
        探路 TSV 没生成却看着像成功（#740）。"""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, spy = self.forward(["-s", "FAKE", "adapt", "gen", "f.tsv"])
        self.assertEqual(code, 1)
        self.assertIn("run.py adapt gen", err.getvalue())
        spy.assert_not_called()
        self.shell.assert_not_called()              # 不碰手机的子命令不做设备检查

    def test_missing_or_unknown_subcommand_is_a_failure_not_silent_help(self):
        """`-s S adapt` 与 `-s S adapt nope` 也该以 1 退出并指向正确写法（#740）。"""
        for argv in (["-s", "FAKE", "adapt"], ["-s", "FAKE", "adapt", "nope"]):
            err = io.StringIO()
            with self.subTest(argv), contextlib.redirect_stderr(err):
                code, spy = self.forward(argv)
            self.assertEqual(code, 1)
            self.assertIn("adapt survey", err.getvalue())
            spy.assert_not_called()
            self.shell.assert_not_called()

    def test_bare_adapt_still_accepts_the_engine_order(self):
        _code, spy = self.forward(["adapt", "survey", "-s", "FAKE"])
        spy.assert_called_once_with("adapt.py", "survey", "-s", "FAKE")
        self.shell.assert_not_called()              # 老写法仍由 adapt.py 自己管设备


if __name__ == "__main__":
    unittest.main()
