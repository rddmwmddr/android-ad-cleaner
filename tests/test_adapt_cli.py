"""adapt.py 三条子命令对外的退出码与两路输出，与改动前逐字节相同（#708）。

基线 `tests/baselines/adapt_cli.json` 由 `tests/make_adapt_cli_baseline.py` 在
`git archive 294ff50` 的干净副本上生成，喂的是同一份用例（`tests/adapt_cli_cases.py`）。

需要手机的档位不进对拍：`check` 的锁屏与报告结论要真的读屏，`explore` 要真的连手机，
它们的退出码在本文件后半的进程内断言里。`OSError` 的系统文案由 harness 规范化
（见 `tests/adapt_cli_driver.py`），其余逐字比对。

后半还有 #690 的 `survey` 三种结局与 `-s S adapt <子命令>` 转发、#740 的误用不再静默成功，
以及 adapt 与 ADR-0005 同形状（退出只留在 `__main__`）的守卫。
"""
import ast
import contextlib
import io
import json
import sys
import tempfile
import tomllib
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
sys.path.insert(0, str(ROOT / "tests"))
import adapt_cli_cases  # noqa: E402
import adapt_cli_driver  # noqa: E402
import adapt  # noqa: E402
import entries  # noqa: E402
import explore  # noqa: E402
import recipe_loader  # noqa: E402
import run  # noqa: E402
import vocab  # noqa: E402
from fixtures import Clock, fake_adb, phone_mock  # noqa: E402

BASELINE = ROOT / "tests" / "baselines" / "adapt_cli.json"


class AdaptCliParityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_every_subcommand_is_covered(self):
        """三条子命令与参数分派都要有用例，每条带守卫断言，漏一条这里就红。"""
        covered = {spec["argv"][0] for spec in adapt_cli_cases.CASES}
        self.assertTrue({"gen", "check", "explore"} <= covered)
        self.assertTrue(any(spec["argv"][0] not in ("gen", "check", "explore") for spec in adapt_cli_cases.CASES))
        missing = [spec["name"] for spec in adapt_cli_cases.CASES if not spec["expect"]]
        self.assertEqual(missing, [])

    def test_matches_baseline(self):
        for spec in adapt_cli_cases.CASES:
            with self.subTest(spec["name"]), tempfile.TemporaryDirectory() as work:
                got = adapt_cli_driver.run_once(ROOT, spec, work)
                # 守卫断言先跑：证明这条用例真的走到了目标分支，而不是两边都停在同一个错误上。
                printed = got["stdout"] + got["stderr"]
                for needle in spec["expect"]:
                    self.assertIn(needle, printed)
                self.assertEqual(got, self.baseline["cases"][spec["name"]])


# ---------- #708 的进程内断言：adapt 的解析、草稿、自检与探路 ----------
TSV = """包名\t页面\t开关\t状态\t像广告\t人工勾选
# 在末列写「关」挑出要关的开关
com.heytap.market\t设置 > 隐私\t个性化推荐\t开\t★\t关
com.heytap.market\t设置 > 隐私\t应用安全\t开\t\t
com.heytap.market\t设置 > 服务管理\t活动弹窗\t开\t★\t
com.heytap.market\t设置\t限制广告跟踪\t开\t★\t关
com.heytap.browser\t设置 > 隐私\t个性化推荐\t开\t★\t是
com.heytap.browser\t\t（没找到设置入口）\t\t\t
"""


def write_tsv(directory, text=TSV, name="探路-PJA110.tsv"):
    path = Path(directory) / name
    path.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))   # BOM + CRLF
    return path


def draft_phone(switch_lists, tap_ok=True):
    """能跑草稿的 Mock 手机：入口都点得到，开关状态按 switch_lists 回读。"""
    p = phone_mock()                       # safe_mode 在这里是明确的 False，不是 Mock 的真值
    p.W, p.H, p.miss, p.changed = 1168, 1712, 0, []
    p.locked.return_value = False
    p.find.return_value = None
    p.tap.return_value = tap_ok
    p.scroll_more.return_value = False
    p.top.return_value = None
    p.off.return_value = 0
    p.switches.side_effect = switch_lists
    p.d.shell.return_value = types.SimpleNamespace(output="PJA110_14.0.0.812")
    return p


class TsvParseTests(unittest.TestCase):
    def test_bom_crlf_comment_and_header_are_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
        self.assertEqual([r["pkg"] for r in rows],
                         ["com.heytap.market"] * 4 + ["com.heytap.browser"] * 2)
        self.assertEqual(rows[0]["title"], "个性化推荐")
        self.assertEqual(rows[0]["pick"], "关")
        self.assertEqual(rows[-1]["title"], "（没找到设置入口）")

    def test_legacy_five_column_tsv_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.tsv"
            path.write_text("com.a\t设置\t个性化推荐\t开\t★\n", encoding="utf-8")
            rows = adapt.parse_tsv(path)
        self.assertEqual(rows[0]["pick"], "")

    def test_missing_pick_file_reports_its_reason_instead_of_exiting(self):
        """helper 只把文案交回调用方，退出码归 cmd_gen（ADR-0005 的形状）。"""
        titles, error = adapt.read_pick_file("/不存在的清单.txt")
        self.assertIsNone(titles)
        self.assertEqual(error, "找不到勾选清单 /不存在的清单.txt")


class SelectionTests(unittest.TestCase):
    def test_marks_and_pick_file_select_only_human_choices(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
            pick = Path(d) / "pick.txt"
            pick.write_text("# 人工确认\n活动弹窗\n", encoding="utf-8")
            titles, error = adapt.read_pick_file(pick)
            self.assertIsNone(error)
            groups, protection, ad_left = adapt.select_rows(rows, titles)
        self.assertEqual(groups, [
            ("com.heytap.market", "设置 > 隐私", ["个性化推荐"]),
            ("com.heytap.market", "设置 > 服务管理", ["活动弹窗"]),
            ("com.heytap.browser", "设置 > 隐私", ["个性化推荐"]),
        ])
        self.assertEqual(protection, ["限制广告跟踪"])     # 勾了也不写进草稿
        self.assertEqual(ad_left, 0)

    def test_protection_switch_marked_still_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
            groups, protection, _ = adapt.select_rows(rows)
        self.assertNotIn("限制广告跟踪", [n for _, _, names in groups for n in names])
        self.assertEqual(protection, ["限制广告跟踪"])

    def test_unmarked_suspected_ad_switch_is_reported_not_selected(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
            groups, _, ad_left = adapt.select_rows(rows)
        titles = [n for _, _, names in groups for n in names]
        self.assertNotIn("活动弹窗", titles)
        self.assertEqual(ad_left, 1)


class DraftGenTests(unittest.TestCase):
    def gen(self, directory, extra=()):
        out = Path(directory) / "草稿.toml"
        with contextlib.redirect_stdout(io.StringIO()):
            adapt.cmd_gen([str(write_tsv(directory)), "-o", str(out), *extra])
        return out.read_text(encoding="utf-8")

    def test_draft_header_carries_build_models_and_unverified_marks(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d)
        self.assertIn('build = ""', src)
        self.assertIn('models = ["PJA110"]', src)                    # 型号从文件名认出
        self.assertIn("待验证草稿", src)
        self.assertIn("这不是适配成果", src)
        self.assertIn("不要直接放进 recipes/", src)
        tomllib.loads(src)                                           # 生成物必须是合法 TOML

    def test_step_literal_format_survives_run_recipe_meta(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "草稿.toml"
            with contextlib.redirect_stdout(io.StringIO()):
                adapt.cmd_gen([str(write_tsv(d)), "-o", str(out)])
            meta = run.recipe_meta(str(out))
        self.assertEqual(meta["steps"], ["com.heytap.market · 设置 > 隐私", "com.heytap.browser · 设置 > 隐私"])
        self.assertEqual(meta["models"], ["PJA110"])
        self.assertEqual(meta["build"], "")

    def test_switches_are_written_as_named_only_list(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d)
        self.assertIn('{kind = "off", only = ["个性化推荐"], page = "设置 > 隐私"}', src)
        self.assertNotIn("keep =", src)                               # 草稿不做整页全关

    def test_navigation_paths_come_from_explore(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d)
        self.assertIn('{kind = "entry", text = "隐私"}', src)
        self.assertNotIn('text = "设置"', src)   # 第一跳是 start 的包名，不单列 entry

    def test_model_and_build_options_override(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d, ["--model", "PLP120", "--build", "PLP120_16.0.9"])
        self.assertIn('build = "PLP120_16.0.9"', src)
        self.assertIn('models = ["PLP120"]', src)

    def test_skeleton_is_data_only(self):
        """草稿只有页面树数据：不再产 `.py` 脚本，也就不该出现 `@step` / 注入名 import（#1268）。"""
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d)
        self.assertNotIn("@step", src)
        self.assertNotIn("from recipe_kit", src)
        self.assertNotIn("TYPE_CHECKING", src)

    def test_generated_draft_loads_through_the_only_loader(self):
        """`adapt check` 与正式数据走同一个装载器：草稿能在 `recipe_loader.load()` 里装满段，
        且导入不产生任何设备动作。"""
        with tempfile.TemporaryDirectory() as d:
            out = self.draft_path(d)
            phone = phone_mock()
            with contextlib.redirect_stdout(io.StringIO()):
                recipe = recipe_loader.load(str(out), phone)
        self.assertEqual([step.name for step in recipe.steps],
                         ["com.heytap.market · 设置 > 隐私", "com.heytap.browser · 设置 > 隐私"])
        self.assertEqual(phone.mock_calls, [], "装载草稿不该碰手机")

    def draft_path(self, directory):
        out = Path(directory) / "草稿.toml"
        with contextlib.redirect_stdout(io.StringIO()):
            adapt.cmd_gen([str(write_tsv(directory)), "-o", str(out)])
        return out

    def test_docs_04_shows_the_same_skeleton(self):
        """文档与生成器同步（页面树形态 #1270）：docs/04 贴出的骨架里每个 op 行必须与
        `render_catalog_draft()` 产出的原样一致，反过来也成立——改一边漏一边即红。"""
        doc = (ROOT / "docs" / "04-给新机型写脚本.md").read_text(encoding="utf-8")
        draft = adapt.render_catalog_draft([("com.heytap.market", "设置 > 隐私", ["个性化推荐"])],
                                           model="PLP120", build="", source="探路-PLP120.tsv")
        op_lines = [line.strip() for line in draft.splitlines() if "{kind" in line]
        self.assertTrue(op_lines, "生成的骨架里没有 op 行")
        for line in op_lines:
            self.assertIn(line, doc, f"docs/04 的骨架缺这一行：{line}")
        for line in ('model = "PLP120"', 'models = ["PLP120"]', 'build = ""'):
            self.assertIn(line, doc, f"docs/04 缺这一行：{line}")

    def test_py_output_is_rejected(self):
        """`-o x.py` 是已删除的死路径：明确报错，不静默产出一份装载器不认的脚本（#1268）。"""
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "草稿.py"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = adapt.cmd_gen([str(write_tsv(d)), "-o", str(out)])
            self.assertFalse(out.exists())
        self.assertEqual(code, 1)
        self.assertIn(".toml", err.getvalue())

    def test_no_selection_refuses_to_generate(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "empty.tsv"
            path.write_text("com.a\t设置\t个性化推荐\t开\t★\t\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = adapt.cmd_gen([str(path), "-o", str(Path(d) / "x.toml")])
            self.assertFalse((Path(d) / "x.toml").exists())
        self.assertEqual(code, 1)
        self.assertIn("没有勾选任何开关", err.getvalue())

    def test_successful_generation_returns_zero(self):
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                code = adapt.cmd_gen([str(write_tsv(d)), "-o", str(Path(d) / "草稿.toml")])
        self.assertEqual(code, 0)


class CheckReportTests(unittest.TestCase):
    def draft(self, directory):
        out = Path(directory) / "草稿.toml"
        with contextlib.redirect_stdout(io.StringIO()):
            adapt.cmd_gen([str(write_tsv(directory)), "-o", str(out)])
        return out

    def test_all_closed_report_matches_readback(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.draft(d)
            p = draft_phone([[]] * 10)
            p.off.return_value = 1               # 每段关掉一项：回读确认数来自 p.off 的返回值
            self.assertIs(p.safe_mode, False)
            with contextlib.redirect_stdout(io.StringIO()):
                report = adapt.check_draft(p, str(out))
                self.assertIs(p.safe_mode, True)   # 自检必须把手机切进安全模式
        self.assertEqual(report, {"verified": 2, "failed_steps": []})
        self.assertTrue(adapt.print_report(report))
        self.assertEqual(p.off.call_count, 2)

    def test_check_draft_runs_through_the_only_loader(self):
        """`adapt check` 与正式数据共用一处装载：草稿交给 `recipe_loader.run()`，不自带 exec。"""
        with tempfile.TemporaryDirectory() as d:
            out = self.draft(d)
            p = draft_phone([[]] * 10)
            with patch.object(adapt.recipe_loader, "run", wraps=adapt.recipe_loader.run) as run:
                with contextlib.redirect_stdout(io.StringIO()):
                    adapt.check_draft(p, str(out))
        run.assert_called_once_with(str(out), p, only=[])
        self.assertIs(p.safe_mode, True)        # 装载前就切进安全模式，草稿不会整页全关

    def test_check_rejects_a_py_path(self):
        """`check` 只认 `.toml`：`.py` 报告一句明确错误，不静默失败（#1268）。"""
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "草稿.py"
            out.write_text("BUILD = ''\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, ".toml"):
                adapt.check_draft(draft_phone([]), str(out))

    def test_unconfirmed_readback_is_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.draft(d)
            p = draft_phone([[]] * 10)
            p.off.return_value = 0               # 点了但回读没确认
            with contextlib.redirect_stdout(io.StringIO()):
                report = adapt.check_draft(p, str(out))
        self.assertEqual(report, {"verified": 0, "failed_steps": []})
        self.assertEqual(p.off.call_count, 2)
        self.assertFalse(adapt.print_report(report))

    def test_partial_completion_is_never_worded_as_success(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = adapt.print_report({"verified": 1, "failed_steps": ["com.example · 设置 > 隐私"]})
        self.assertFalse(ok)
        self.assertIn("部分完成", out.getvalue())
        self.assertIn("不能把部分完成当成适配成功", out.getvalue())

    def run_check_entry(self, draft_path, phone=None):
        """走 check 的真实入口（`adapt.main(["check", …])`），拿返回的退出码。"""
        p = phone or draft_phone([[]] * 10)
        with patch.object(adapt, "Phone") as P, contextlib.redirect_stdout(io.StringIO()):
            P.return_value.__enter__.return_value = p
            return adapt.main(["check", "-s", "FAKE_SERIAL", str(draft_path)])

    def test_locked_phone_exits_one_before_running_the_draft(self):
        """锁屏是 check 的第三条退出：返回码 1 + 逐字文案，且不碰插电常亮、不跑草稿。"""
        p = draft_phone([])
        p.locked.return_value = True
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            with patch.object(adapt, "Phone") as P, contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(err):
                P.return_value.__enter__.return_value = p
                code = adapt.main(["check", "-s", "FAKE_SERIAL", str(self.draft(d))])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue(), "手机锁屏了，请机主解锁后再跑\n")
        p.d.shell.assert_not_called()
        p.off.assert_not_called()

    def test_close_failure_keeps_the_lock_message_unprinted(self):
        """旧实现里那句锁屏文案是挂起的 `SystemExit`，`Phone` 关闭抛错时它不会被打出来。
        返回码写法要保住同一个时机：文案等 `__exit__` 跑完才渲染（ADR-0005 的 `cmd_recipe` 同型）。"""
        p = draft_phone([])
        p.locked.return_value = True
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d, \
             patch.object(adapt, "Phone") as P, contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(err):
            P.return_value.__enter__.return_value = p
            P.return_value.__exit__.side_effect = RuntimeError("读屏服务没关掉")
            with self.assertRaises(RuntimeError):
                adapt.main(["check", "-s", "FAKE_SERIAL", str(self.draft(d))])
        self.assertEqual(err.getvalue(), "")

    def test_all_closed_check_exits_zero(self):
        p = draft_phone([[]] * 10)
        p.off.return_value = 1
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_check_entry(self.draft(d), p), 0)

    def test_partial_completion_check_exits_one(self):
        p = draft_phone([[]] * 10)
        p.off.side_effect = [1, RuntimeError("第二段没做成")]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_check_entry(self.draft(d), p), 1)


class ExploreNavigationTests(unittest.TestCase):
    def entry_phone(self, focus_seq, tap_seq, names=("隐私", "通知", "电池")):
        p = Mock()
        p.W, p.H = 1168, 1712
        p.switches.return_value = []
        p.scroll_more.return_value = False
        p.top.return_value = None
        p.focus.side_effect = focus_seq
        p.tap.side_effect = tap_seq

        def node(text):
            return ET.fromstring(f'<node text="{text}" package="com.example" bounds="[60,300][600,360]"/>')

        p.texts.return_value = [(n, (60, 300, 600, 360), node(n)) for n in names]
        return p

    def test_back_to_home_is_bounded_and_reports_reason(self):
        p = Mock(); p.focus.return_value = "com.example/.Sub"
        reason = explore.back_to(p, "com.example/.Settings", tries=3)
        self.assertIn("com.example/.Sub", reason)
        self.assertEqual(p.back.call_count, 3)                      # 有界，不会一直按返回

    def test_back_to_home_stops_as_soon_as_settings_page_is_back(self):
        p = Mock(); p.focus.side_effect = ["com.example/.Sub", "com.example/.Sub", "com.example/.Settings"]
        self.assertIsNone(explore.back_to(p, "com.example/.Settings"))
        self.assertEqual(p.back.call_count, 2)

    def test_stuck_subpage_stops_package_without_endless_restarts(self):
        p = self.entry_phone(["com.example/.Settings"] + ["com.example/.Sub"] * 10,
                             [True, True, True, False, False, False])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            explore.explore(p, "com.example", [])
        self.assertIn("探路到此为止", out.getvalue())
        self.assertEqual(p.back.call_count, 3)
        self.assertEqual(p.start.call_count, 2)                     # 首次 + 一次恢复，不反复重启
        p.d.app_stop.assert_called_once_with("com.example")
        tapped = [c.args[0] for c in p.tap.call_args_list]
        self.assertNotIn("通知", tapped)
        self.assertNotIn("电池", tapped)

    def test_recovered_settings_page_continues_remaining_entries(self):
        p = self.entry_phone(["com.example/.Settings"] + ["com.example/.Sub"] * 4 + ["com.example/.Settings2"] * 8,
                             [True] * 7)
        with contextlib.redirect_stdout(io.StringIO()):
            explore.explore(p, "com.example", [])
        tapped = [c.args[0] for c in p.tap.call_args_list]
        for entry in ("隐私", "通知", "电池"):
            self.assertIn(entry, tapped)
        self.assertEqual(p.start.call_count, 2)
        self.assertEqual(p.back.call_count, 3)                      # 只有第一次回不去时按了返回
        p.d.app_stop.assert_called_once_with("com.example")

    def test_recovery_is_capped_at_two_per_package(self):
        """重进设置页每次都成功、但焦点始终回不去：同一个 App 最多恢复 2 次，然后明确中断。
        注意 back_to 失败时连报错文案里的 focus 一共消费 5 次（explore.py:71），
        所以每个「卡住段」给 5 个非 home 的焦点值，恢复落点单独给一个设置首页值。"""
        focus_seq = (["com.example/.Settings"]
                     + ["com.example/.Sub1"] * 5 + ["com.example/.Settings2"]
                     + ["com.example/.Sub2"] * 5 + ["com.example/.Settings3"]
                     + ["com.example/.Sub3"] * 5 + ["com.example/.Settings4"]
                     + ["com.example/.Sub4"] * 5 + ["com.example/.Settings5"]
                     + ["com.example/.Sub5"] * 5 + ["com.example/.Settings6"])
        p = self.entry_phone(focus_seq, [True] * 20,
                             names=["隐私", "通知", "电池", "声音", "显示"])
        out = io.StringIO()
        with patch.object(explore, "open_settings", wraps=explore.open_settings) as reopen:
            with contextlib.redirect_stdout(out):
                explore.explore(p, "com.example", [])
        self.assertIn("探路到此为止", out.getvalue())                # 连踩 3 次恢复后中断本 App
        self.assertEqual(reopen.call_count, 4)                      # 首次 + 3 次恢复，之后不再重进
        self.assertEqual(p.start.call_count, 4)                     # 重启次数有界
        tapped = [c.args[0] for c in p.tap.call_args_list]
        for entry in ("隐私", "通知", "电池"):
            self.assertIn(entry, tapped)                            # 前 3 个条目都探过
        for entry in ("声音", "显示"):
            self.assertNotIn(entry, tapped)                         # 中断后不再探剩下的条目
        p.d.app_stop.assert_called_once_with("com.example")


class EntryShapeTests(unittest.TestCase):
    """adapt 与 ADR-0005 同形状——命令只返回退出码，退出只留在 `__main__` 那一处。"""

    def test_help_prints_the_module_doc_and_returns_zero(self):
        """用法说明与 `__doc__` 逐字相等。旧树也绿，守的是不回退。
        不进子进程对拍：3.13 起编译器会去掉文档字符串的公共缩进，3.12 不会，
        同一份源码跨版本逐字不同（与 test_run_commands 同一条理由）。"""
        for argv in ([], ["-h"], ["--help"]):
            with self.subTest(argv), contextlib.redirect_stdout(out := io.StringIO()):
                self.assertEqual(adapt.main(argv), 0)
            self.assertEqual(out.getvalue(), adapt.__doc__ + "\n")

    def test_unknown_subcommand_returns_one_and_names_the_choices(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(adapt.main(["bogus"]), 1)
        self.assertEqual(err.getvalue(), "adapt 后面跟 survey / explore / gen / check。用法：run.py adapt --help\n")

    def test_error_rendering_is_the_same_function_as_run(self):
        """错误渲染只留一份：ADR-0005 的 `run.fail()` 是「自述型文案」的唯一出处。"""
        self.assertIs(adapt.fail, run.fail)

    def test_exit_lives_only_at_the_entry(self):
        """helper 与命令入口里不许再出现 `sys.exit`：退出码的唯一出口是 `__main__` 那一行。"""
        tree = ast.parse(Path(adapt.__file__).read_text(encoding="utf-8"))
        exits = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "exit" and getattr(node.func.value, "id", "") == "sys"]
        system_exits = [node for node in ast.walk(tree)
                        if isinstance(node, ast.Name) and node.id == "SystemExit"]
        self.assertEqual(exits, [])
        self.assertEqual(len(system_exits), 1)


# ---------- #690 / #740：survey 试入口与 `-s S adapt <子命令>` 的转发 ----------
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
    """#690：survey 试入口的三种结局，且只读。"""

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

    def test_public_intent_entries_are_probed_with_the_action(self):
        """Intent 档没有页面名可指定，survey 走与 reach() 同一条拉起命令（#956）。"""
        direct = entries.Direct("com.heytap.market",
                                "com.heytap.market.mine.cn.setting.ui.SettingActivity",
                                action="oppo.intent.action.APP_SETTINGS")
        p = survey_phone(focus="com.heytap.market/com.heytap.market.mine.cn.setting.ui.SettingActivity",
                         packages="package:com.heytap.market\n")
        fmap = {"oppo": {"软件商店": entries.Entry(menu="软件商店 → 我的 → 右上齿轮", direct=(direct,))}}
        rows, _out = run_survey(p, [], family="oppo", family_map=fmap)
        self.assertEqual([row["landed"] for row in rows], [True])
        command = next(cmd for cmd in shell_calls(p) if cmd.startswith("am start"))
        self.assertEqual(command, "am start -W -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market")

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
    """#740：文档写的 `-s 序列号 adapt <子命令>` 要真转发；gen 不碰手机，误带 -s 时明确报错。"""

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
        探路 TSV 没生成却看着像成功。"""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, spy = self.forward(["-s", "FAKE", "adapt", "gen", "f.tsv"])
        self.assertEqual(code, 1)
        self.assertIn("run.py adapt gen", err.getvalue())
        spy.assert_not_called()
        self.shell.assert_not_called()              # 不碰手机的子命令不做设备检查

    def test_missing_or_unknown_subcommand_is_a_failure_not_silent_help(self):
        """`-s S adapt` 与 `-s S adapt nope` 也该以 1 退出并指向正确写法。"""
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
