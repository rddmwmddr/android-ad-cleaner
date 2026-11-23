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
import wait  # noqa: E402
from fixtures import shell_result, Clock, fake_adb, phone_mock  # noqa: E402

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
    p.shell.return_value = shell_result("PJA110_14.0.0.812")
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
        self.assertEqual(err.getvalue(),
                         "没有勾选任何开关：在 TSV 末列「人工勾选」写「关」，或用 --pick 给清单文件。"
                         "工具不自动决定关哪些开关。\n")

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
        p.shell.assert_not_called()
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
        p.app_stop.assert_called_once_with("com.example")
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
        p.app_stop.assert_called_once_with("com.example")

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
        p.app_stop.assert_called_once_with("com.example")


class VendorPickTests(unittest.TestCase):
    """不给包名时按启动器列表挑厂商 App；卓易系四个前缀也要认得出（#1293）。"""

    def test_picks_freeme_packages_alongside_the_older_vendors(self):
        listed = "\n".join([
            f"{pkg}/.MainActivity" for pkg in (
                "com.freeme.secureguard", "com.freeme.launcher", "com.freeme.secureguardmanager",
                "com.zhuoyi.market", "com.feimi.theme", "com.droi.store",
                "com.miui.securitycenter", "com.android.settings", "org.example.app",
            )])
        self.assertEqual(explore.vendor_packages(listed), [
            "com.droi.store", "com.feimi.theme", "com.freeme.launcher", "com.freeme.secureguard",
            "com.freeme.secureguardmanager", "com.miui.securitycenter", "com.zhuoyi.market"])


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
            return shell_result(brand, 0)
        if cmd.startswith("am start"):
            return shell_result(start[0], start[1])
        if cmd == "pm list packages":
            return shell_result(packages, 0)
        return shell_result("", 0)

    p.shell.side_effect = shell
    return p


def run_survey(p, words, family="xiaomi", family_map=ONE_FAMILY):
    clock = Clock()
    out = io.StringIO()
    with patch.object(entries, "ENTRIES", family_map), contextlib.redirect_stdout(out):
        rows = adapt.survey(p, family, words, now=clock.time, sleep=clock.sleep)
    return rows, out.getvalue()


def shell_calls(p):
    return [call.args[0] for call in p.shell.call_args_list]


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
        p.press.assert_called_once_with("home")

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
        calls = [str(call) for call in p.shell.call_args_list]
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


# ---------- explore.py：条目筛选、读页、进设置、探路与 main ----------

def xnode(text="", package="com.example"):
    attrs = f'text="{text}" bounds="[0,0][0,0]"'
    if package is not None:
        attrs += f' package="{package}"'
    return ET.fromstring(f"<node {attrs}/>")


def xtexts(*items, package="com.example"):
    """[(文字, (左, 上, 右, 下), 包名?)] → `p.texts()` 的形状；包名写 None 表示节点没有这个属性。"""
    rows = []
    for item in items:
        text, bounds = item[0], item[1]
        rows.append((text, bounds, xnode(text, item[2] if len(item) > 2 else package)))
    return rows


class ExploreEntriesTests(unittest.TestCase):
    def listing(self, items, switches=(), W=1000, H=1000, pkg="com.example"):
        p = Mock()
        p.W, p.H = W, H
        p.switches.return_value = switches
        p.texts.return_value = xtexts(*items)
        return explore.entries(p, pkg)

    def test_plain_titles_are_kept_and_noise_is_dropped(self):
        out = self.listing([
            ("隐私", (100, 300, 300, 360)),
            ("通知", (100, 900, 300, 960)),
            ("返回", (100, 700, 300, 760)),                  # ENTRY_SKIP
            ("这是一个超过十二个字的页面标题啊", (100, 800, 300, 860)),
            ("我", (100, 400, 300, 460)),                    # 太短
            ("在顶部", (100, 0, 300, 20)),                   # 屏幕顶部 10% 以内
            ("别的包", (100, 500, 300, 560), "com.other"),    # 别的窗口的字
            ("右侧取值", (600, 500, 800, 560)),              # 右侧的取值文字
            ("开启", (100, 600, 300, 660)),                  # 只有状态词
            ("12.5%", (100, 650, 300, 710)),                # 只有数字
            ("隐私", (100, 300, 300, 360)),                  # 去重
        ])
        self.assertEqual(out, ["隐私", "通知"])

    def test_length_boundary_is_twelve_and_top_band_is_inclusive(self):
        twelve = "一二三四五六七八九十甲乙"
        thirteen = "一二三四五六七八九十甲乙丙"
        out = self.listing([
            (twelve, (100, 300, 300, 360)),
            (thirteen, (100, 320, 300, 380)),                # 13 个字：超过上限
            ("顶边", (100, 90, 300, 110)),                    # cy 正好是 H*0.1
        ])
        self.assertEqual(out, [twelve, "顶边"])

    def test_left_edge_at_half_width_is_inside_and_anything_past_it_is_not(self):
        out = self.listing([
            ("正好一半", (500, 300, 700, 360)),
            ("右侧", (600, 500, 800, 560)),
        ])
        self.assertEqual(out, ["正好一半"])

    def test_titles_on_a_switch_row_are_left_for_the_switch_reader(self):
        out = self.listing([
            ("普通开关", (100, 360, 300, 370)),               # cy=365：与 y=365 的开关同一行
            ("跨组的标题", (100, 330, 300, 350)),             # cy=340：在上一组
        ], switches=[("x", True, (360, 365))])                # 365//60=6，365//61=5
        self.assertEqual(out, ["跨组的标题"])

    def test_half_pixel_from_the_centre_line_is_still_in_the_top_band(self):
        """`(tp + b) // 2` 与 `/ 2` 只在 H*0.1 落在半个像素上时分得开。"""
        out = self.listing([("低处", (100, 171, 200, 172))], W=1000, H=1712)   # 171 < 171.2 ≤ 171.5
        self.assertEqual(out, [])

    def test_a_filtered_title_does_not_stop_later_titles(self):
        out = self.listing([
            ("这是一个超过十二个字的页面标题啊", (100, 300, 300, 360)),
            ("隐私", (100, 400, 300, 460)),
        ])
        self.assertEqual(out, ["隐私"])
        out = self.listing([("开启", (100, 300, 300, 360)), ("通知", (100, 400, 300, 460))])
        self.assertEqual(out, ["通知"])

    def test_a_node_without_a_package_is_not_this_page(self):
        self.assertEqual(self.listing([("无包名", (100, 300, 300, 360), None)]), [])


class ExploreReadPageTests(unittest.TestCase):
    def read(self, pages, path=("设置",), pkg="com.example"):
        p = Mock()
        p.switches.side_effect = pages
        p.scroll_more.side_effect = [True] * (len(pages) - 1) + [False]
        rows = []
        explore.read_page(p, list(path), rows, pkg)
        return rows, p

    def test_rows_carry_page_state_and_the_ad_star(self):
        rows, p = self.read([[("广告推荐", True, (0, 0)), ("隐私", False, (0, 60))],
                             [("首页精选", False, (0, 120))]])
        self.assertEqual(rows, [
            ("com.example", "设置", "广告推荐", "开", "★", ""),
            ("com.example", "设置", "隐私", "关", "", ""),
            ("com.example", "设置", "首页精选", "关", "★", ""),
        ])
        self.assertEqual(p.switches.call_count, 2)
        p.top.assert_called_once_with(6)

    def test_the_same_switch_survives_only_once(self):
        rows, _p = self.read([[("隐私", False, (0, 0)), ("隐私", True, (0, 60))]])
        self.assertEqual(rows, [("com.example", "设置", "隐私", "关", "", "")])

    def test_empty_switch_titles_are_not_rows(self):
        rows, _p = self.read([[(None, False, (0, 0)), ("通知", True, (0, 60))]])
        self.assertEqual([row[2] for row in rows], ["通知"])

    def test_a_page_that_never_stops_scrolling_is_bounded(self):
        p = Mock()
        p.switches.return_value = []
        p.scroll_more.return_value = True
        explore.read_page(p, ["设置"], [], "com.example")
        self.assertEqual(p.switches.call_count, 8)
        p.top.assert_called_once_with(6)

    def test_scroll_more_false_ends_the_loop_after_one_read(self):
        rows, p = self.read([[("隐私", False, (0, 0))]], path=("设置", "隐私"))
        self.assertEqual(rows, [("com.example", "设置 > 隐私", "隐私", "关", "", "")])
        self.assertEqual(p.switches.call_count, 1)


class ExploreOpenSettingsTests(unittest.TestCase):
    def phone(self, texts, find=False, tap=False):
        p = Mock()
        p.texts.return_value = [(text, (0, 0, 1, 1), xnode(text)) for text in texts]
        p.find.return_value = find
        p.tap.return_value = tap
        return p

    def test_settings_entry_is_found_through_the_search_fallbacks(self):
        p = self.phone(["首页"], tap=False)
        p.tap.side_effect = [False, True]                    # 第一档「设置」没找到，第二档「设置中心」进得去
        self.assertIsNone(explore.open_settings(p, "com.example"))
        p.start.assert_called_once_with("com.example", settle=2.5)
        self.assertEqual([call.args[0] for call in p.tap.call_args_list], ["设置", "设置中心"])
        for call in p.tap.call_args_list:
            self.assertEqual(call.kwargs, {"exact": True, "scrolls": 3})

    def test_me_tab_is_tapped_once_with_the_tab_edge(self):
        p = self.phone(["首页"])
        p.find.side_effect = lambda text, **kwargs: text == "我的"
        p.tap.return_value = True
        self.assertIsNone(explore.open_settings(p, "com.example"))
        me_calls = [call for call in p.tap.call_args_list if call.args[0] == "我的"]
        self.assertEqual(len(me_calls), 1)
        self.assertEqual(me_calls[0].kwargs, {"exact": True, "scrolls": 0})
        self.assertEqual(p.find.call_args.kwargs, {"exact": True, "edge_ok": "tab"})

    def test_agreement_page_is_named_and_left_alone(self):
        p = self.phone(["同意", "隐私政策"], find=True, tap=True)
        self.assertEqual(explore.open_settings(p, "com.example"), "协议页")
        p.tap.assert_not_called()

    def test_thirty_texts_is_no_longer_an_agreement_page(self):
        p = self.phone(["同意"] + ["x"] * 29, tap=False)       # 正好 30 条
        self.assertEqual(explore.open_settings(p, "com.example"), "没找到设置入口")

    def test_missing_settings_entry_is_reported(self):
        self.assertEqual(explore.open_settings(self.phone(["首页"], tap=False), "com.example"),
                         "没找到设置入口")


class ExploreBackToTests(unittest.TestCase):
    def test_already_home_returns_none_without_pressing_back(self):
        p = Mock()
        p.focus.return_value = "com.example/.Settings"
        self.assertIsNone(explore.back_to(p, "com.example/.Settings"))
        p.back.assert_not_called()

    def test_returning_home_on_the_last_read_returns_none(self):
        p = Mock()
        home = "com.example/.Settings"
        # 循环三次都没回到首页；循环之后那一次读到了首页
        p.focus.side_effect = ["com.example/.Sub"] * 3 + [home, home]
        self.assertIsNone(explore.back_to(p, home, tries=3))

    def test_unknown_page_is_named_in_the_reason(self):
        p = Mock()
        p.focus.side_effect = ["", "", "", "", ""]        # 3 次循环 + 判等 + 报错文案各读一次
        reason = explore.back_to(p, "com.example/.Settings", tries=3)
        self.assertEqual(reason, "返回 3 次后仍停在 未知页面，不在设置首页")


class ExploreWalkTests(unittest.TestCase):
    def test_each_entry_gets_its_own_read_and_failed_taps_are_skipped(self):
        p = Mock()
        p.focus.return_value = "com.example/.Settings"
        p.tap.side_effect = [False, True, True]              # 第一项点不开，后两项点得开
        rows, reads, opens = [], Mock(), Mock()
        opens.return_value = None
        out = io.StringIO()
        with patch.object(explore, "entries", return_value=["甲", "乙", "丙"]), \
                patch.object(explore, "read_page", reads), \
                patch.object(explore, "open_settings", opens), \
                contextlib.redirect_stdout(out):
            explore.explore(p, "com.example", rows)
        self.assertIn("### com.example", out.getvalue())
        opens.assert_called_once_with(p, "com.example")
        self.assertEqual([call.args[1] for call in reads.call_args_list], [["设置"], ["设置", "乙"], ["设置", "丙"]])
        for call in reads.call_args_list:
            self.assertEqual(call.args[0], p)
            self.assertIs(call.args[2], rows)
            self.assertEqual(call.args[3], "com.example")
        for call in p.tap.call_args_list:
            self.assertEqual(call.kwargs, {"exact": True, "scrolls": 4})
        p.app_stop.assert_called_once_with("com.example")

    def test_entries_after_the_twenty_fifth_are_left_for_the_next_run(self):
        p = Mock()
        p.focus.return_value = "com.example/.Settings"
        p.tap.return_value = True
        reads = Mock()
        with patch.object(explore, "entries", return_value=[f"项{i}" for i in range(26)]), \
                patch.object(explore, "read_page", reads), \
                patch.object(explore, "open_settings", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            explore.explore(p, "com.example", [])
        self.assertEqual(reads.call_count, 26)               # 首次读设置页 + 25 个子页

    def test_an_entry_that_was_already_walked_is_not_walked_twice(self):
        p = Mock()
        p.focus.return_value = "com.example/.Settings"
        p.tap.return_value = True
        reads = Mock()
        with patch.object(explore, "entries", return_value=["甲", "甲", "乙"]), \
                patch.object(explore, "read_page", reads), \
                patch.object(explore, "open_settings", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            explore.explore(p, "com.example", [])
        self.assertEqual([call.args[1] for call in reads.call_args_list],
                         [["设置"], ["设置", "甲"], ["设置", "乙"]])

    def test_an_unopenable_settings_page_is_one_placeholder_row(self):
        rows, out = [], io.StringIO()
        nested = ("com.example", "", "（协议页）", "", "", "")
        with patch.object(explore, "open_settings", return_value="协议页"), contextlib.redirect_stdout(out):
            explore.explore(Mock(), "com.example", rows)
        self.assertEqual(rows, [nested])
        self.assertIn("  协议页", out.getvalue())

    def test_recovery_message_names_the_failure_and_reports_the_reopened_page(self):
        p = Mock()
        p.focus.side_effect = (["com.example/.Settings"] + ["com.example/.Sub"] * 6)
        p.tap.return_value = True
        out = io.StringIO()
        with patch.object(explore, "entries", return_value=["甲"]), \
                patch.object(explore, "read_page"), \
                patch.object(explore, "open_settings", side_effect=[None, "协议页"]) as opens, \
                contextlib.redirect_stdout(out):
            explore.explore(p, "com.example", [])
        self.assertTrue(all(call.args == (p, "com.example") for call in opens.call_args_list))
        self.assertIn("失败：协议页", out.getvalue())
        self.assertNotIn("后页面也不对", out.getvalue())

    def test_recovery_with_a_wrong_page_says_so(self):
        p = Mock()
        # 首次焦点=设置首页；back_to 失败那 4 次读焦点都不在首页；重进后落到别的包
        p.focus.side_effect = (["com.example/.Settings"] + ["com.example/.Sub"] * 5
                               + ["com.other/.X"])
        p.tap.return_value = True
        out = io.StringIO()
        with patch.object(explore, "entries", return_value=["甲"]), \
                patch.object(explore, "read_page"), \
                patch.object(explore, "open_settings", return_value=None) as opens, \
                contextlib.redirect_stdout(out):
            explore.explore(p, "com.example", [])
        self.assertTrue(all(call.args == (p, "com.example") for call in opens.call_args_list))
        self.assertIn("后页面也不对，本 App 探路到此为止", out.getvalue())


class ExploreMainTests(unittest.TestCase):
    def phone(self):
        p = Mock()
        p.shell.side_effect = lambda command: {
            "cmd package query-activities --brief -a android.intent.action.MAIN"
            " -c android.intent.category.LAUNCHER": "com.miui.securitycenter/.Main\ncom.android.settings/.Settings\n",
            "getprop ro.product.model": "PJA110\n",
        }.get(command, "")
        return p

    def run_main(self, argv, phone, walk=None):
        fake = walk or (lambda p, pkg, rows: rows.extend([
            (pkg, "设置", "广告推荐", "开", "★", ""),
            (pkg, "设置", "推送通知", "关", "★", ""),
            (pkg, "设置", "隐私", "开", "", ""),
        ]))
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as work, contextlib.chdir(work):
            with patch.object(explore, "Phone", return_value=phone) as factory, \
                    patch.object(sys, "argv", ["explore.py", *argv]), \
                    patch.object(explore, "explore", side_effect=fake) as walker, \
                    patch.object(explore.time, "time", side_effect=[100.0, 137.0]), \
                    contextlib.redirect_stdout(out):
                explore.main()
            files = sorted(Path(work).iterdir())
            text = files[0].read_text(encoding="utf-8") if files else ""
        return out.getvalue(), text, files, factory, walker

    def test_vendor_apps_are_discovered_and_the_report_is_written(self):
        out, text, files, factory, walker = self.run_main(["-s", "SER"], phone := self.phone())
        factory.assert_called_once_with("SER", log=False)
        self.assertIs(walker.call_args.args[0], phone)
        self.assertEqual([path.name for path in files], ["探路-PJA110.tsv"])
        self.assertEqual(text.splitlines(), [
            "包名\t页面\t开关\t状态\t像广告\t人工勾选",
            "# 在末列写「关」挑出要关的开关，再跑：python3 tool/run.py adapt gen 探路-PJA110.tsv",
            "com.miui.securitycenter\t设置\t广告推荐\t开\t★\t",
            "com.miui.securitycenter\t设置\t推送通知\t关\t★\t",
            "com.miui.securitycenter\t设置\t隐私\t开\t\t",
        ])
        self.assertIn("探了 1 个 App，37 秒；开着的疑似广告开关 1 个 → 探路-PJA110.tsv", out)
        self.assertIn("  com.miui.securitycenter  设置  「广告推荐」", out)
        self.assertIn("在 探路-PJA110.tsv 末列「人工勾选」写「关」", out)

    def test_a_crashing_package_is_reported_and_the_rest_continue(self):
        def walk(p, pkg, rows):
            if pkg == "com.broken":
                raise RuntimeError("断线了")
            rows.append((pkg, "设置", "隐私", "开", "", ""))

        out, text, _files, _factory, walker = self.run_main(
            ["-s", "SER", "com.example", "com.broken"], phone := self.phone(), walk)
        self.assertIs(walker.call_args.args[0], phone)
        self.assertIn("  ✗ 断线了", out)
        self.assertIn("com.example\t设置\t隐私\t开\t\t", text)
        self.assertNotIn("com.broken", text)


# ---------- adapt.py：生成 / 自检 / 试入口 / 子命令分派的细部断言 ----------

class ExploreCommandTests(unittest.TestCase):
    def test_usage_when_serial_is_missing(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(adapt.cmd_explore([]), 1)
        self.assertEqual(err.getvalue(), "用法：run.py adapt explore -s <序列号> [包名 …]\n")

    def test_short_rest_is_usage_not_an_index_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(adapt.cmd_explore(["-s"]), 1)
        self.assertIn("用法", err.getvalue())

    def test_a_bare_serial_is_a_valid_call(self):
        with patch.object(adapt, "script_cmd", return_value=["py", "explore.py"]) as command, \
                patch.object(adapt.subprocess, "call", return_value=0):
            self.assertEqual(adapt.cmd_explore(["-s", "SER"]), 0)
        command.assert_called_once_with("explore.py", "-s", "SER")

    def test_serial_and_packages_are_forwarded_to_the_explore_script(self):
        with patch.object(adapt, "script_cmd", return_value=["py", "explore.py"]) as command, \
                patch.object(adapt.subprocess, "call", return_value=3) as call:
            self.assertEqual(adapt.cmd_explore(["-s", "SER", "com.a", "com.b"]), 3)
        command.assert_called_once_with("explore.py", "-s", "SER", "com.a", "com.b")
        call.assert_called_once_with(["py", "explore.py"])


class DispatchCallsTests(unittest.TestCase):
    def test_each_subcommand_receives_the_remaining_arguments(self):
        for name, attribute in (("survey", "cmd_survey"), ("explore", "cmd_explore"),
                                ("gen", "cmd_gen"), ("check", "cmd_check")):
            with self.subTest(name), patch.object(adapt, attribute, return_value=7) as command:
                self.assertEqual(adapt.main([name, "alpha", "beta"]), 7)
            command.assert_called_once_with(["alpha", "beta"])


class TsvPickEncodingTests(unittest.TestCase):
    def test_indented_comment_is_not_a_row(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.tsv"
            path.write_text("  # 注\ncom.a\t设置\t开\t★\t\t\n", encoding="utf-8")
            rows = adapt.parse_tsv(path)
        self.assertEqual([row["pkg"] for row in rows], ["com.a"])

    def test_pick_file_tolerates_bom_and_indented_comments(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pick.txt"
            path.write_bytes(b"\xef\xbb\xbf" + "  广告推荐\n # 注\n\n隐私\n".encode("utf-8"))
            titles, error = adapt.read_pick_file(path)
        self.assertIsNone(error)
        self.assertEqual(titles, ["广告推荐", "隐私"])


class SelectRowsDetailTests(unittest.TestCase):
    def row(self, title, pick="", ad="", pkg="com.a", page="设置"):
        return {"pkg": pkg, "page": page, "title": title, "state": "开", "ad": ad, "pick": pick}

    def test_empty_title_is_a_placeholder_and_counts_no_ad(self):
        groups, protection, ad_left = adapt.select_rows([self.row("", ad="★")])
        self.assertEqual((groups, protection, ad_left), ([], [], 0))

    def test_placeholder_after_the_failure_marker_is_skipped_even_when_picked(self):
        rows = [self.row("（没找到设置入口）", pick="关"), self.row("隐私", pick="关")]
        groups, _protection, _ad = adapt.select_rows(rows)
        self.assertEqual(groups, [("com.a", "设置", ["隐私"])])

    def test_uppercase_marks_are_selected(self):
        groups, _p, _a = adapt.select_rows([self.row("隐私", pick="Y")])
        self.assertEqual(groups, [("com.a", "设置", ["隐私"])])

    def test_protection_switch_is_reported_when_picked_by_an_uppercase_mark(self):
        groups, protection, _a = adapt.select_rows([self.row("限制广告跟踪", pick="Y")])
        self.assertEqual((groups, protection), ([], ["限制广告跟踪"]))

    def test_protection_switch_matched_by_pick_list_is_reported(self):
        _groups, protection, _a = adapt.select_rows([self.row("限制广告跟踪")], ["限制广告跟踪"])
        self.assertEqual(protection, ["限制广告跟踪"])

    def test_unselected_ad_switches_are_counted_not_overwritten(self):
        _groups, _p, ad_left = adapt.select_rows([self.row("甲", ad="★"), self.row("乙", ad="★")])
        self.assertEqual(ad_left, 2)


class StepNameTests(unittest.TestCase):
    def test_quotes_backslashes_and_newlines_are_removed(self):
        self.assertEqual(adapt.step_name('com."a"', 'x\\y\r\nz'), "com.a · xyz")


class DraftHeaderTests(unittest.TestCase):
    def render(self, groups=None, model="PJA110", build="", source="探路-PJA110.tsv"):
        groups = groups or [("com.heytap.market", "设置 > 隐私", ["个性化推荐"])]
        return adapt.render_catalog_draft(groups, model=model, build=build, source=source)

    def test_header_lines_name_the_generator_and_its_limits(self):
        src = self.render()
        self.assertIn("# ===================== 待验证草稿（页面树）· adapt gen 生成 =====================", src)
        self.assertIn("# 自检：python3 tool/run.py -s <序列号> adapt check <本文件>", src)
        self.assertIn("# 页面树只装机型知识；失败怎么收场、顺序、重试、台账归运行时（ADR-0038）。", src)
        self.assertIn("来源：探路-PJA110.tsv", src)

    def test_generation_time_is_a_readable_minute_stamp(self):
        src = self.render()
        self.assertRegex(src, r"# 生成时间：\d{4}-\d{2}-\d{2} \d{2}:\d{2}；来源：")

    def test_non_ascii_data_is_written_raw(self):
        src = self.render(groups=[("com.example", "设置 > 隐私", ["个性化推荐"])], model="小米")
        self.assertIn('model = "小米"', src)
        self.assertIn('models = ["小米"]', src)
        self.assertIn('"个性化推荐"', src)
        self.assertIn('page = "设置 > 隐私"', src)

    def test_no_model_yields_an_empty_models_list(self):
        src = self.render(model="")
        self.assertIn("models = []", src)

    def test_non_ascii_build_and_package_are_written_raw_too(self):
        src = self.render(groups=[("小米.商店", "设置", ["广告"])], build="小米 OS 1.0")
        self.assertIn('build = "小米 OS 1.0"', src)
        self.assertIn('pkg = "小米.商店"', src)
        self.assertIn('name = "小米.商店 · 设置"', src)


class GenArgumentTests(unittest.TestCase):
    def run_gen(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adapt.cmd_gen(argv)
        return code, out.getvalue(), err.getvalue()

    def test_an_option_at_the_end_is_reported_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            for option in ("-o", "--pick", "--model", "--build"):
                with self.subTest(option):
                    code, _out, err = self.run_gen([str(write_tsv(d)), option])
                    self.assertEqual(code, 1)
                    self.assertEqual(err, f"选项 {option} 后面要跟值\n")

    def test_unknown_option_names_the_usage(self):
        code, _out, err = self.run_gen(["--bogus", "x.tsv"])
        self.assertEqual(code, 1)
        self.assertIn("不认识的选项 --bogus。用法：run.py adapt gen <探路-型号.tsv> [-o 输出.toml] "
                      "[--pick 清单.txt] [--model 型号] [--build 录制版本]", err)

    def test_only_one_tsv_is_accepted(self):
        code, _out, err = self.run_gen(["a.tsv", "b.tsv"])
        self.assertEqual(code, 1)
        self.assertEqual(err, "只收一个探路 TSV 文件；要合并多份结果请先手工合并\n")

    def test_missing_tsv_shows_the_usage(self):
        code, _out, err = self.run_gen([])
        self.assertEqual(code, 1)
        self.assertEqual(err, "用法：run.py adapt gen <探路-型号.tsv> [-o 输出.toml] [--pick 清单.txt] "
                              "[--model 型号] [--build 录制版本]\n")

    def test_missing_file_is_named(self):
        code, _out, err = self.run_gen(["/nope/探路.tsv"])
        self.assertEqual((code, err), (1, "找不到 /nope/探路.tsv\n"))

    def test_empty_tsv_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "empty.tsv"
            path.write_text("包名\t页面\t开关\t状态\t像广告\t人工勾选\n", encoding="utf-8")
            code, _out, err = self.run_gen([str(path)])
        self.assertEqual((code, err), (1, f"{path} 里没有数据行\n"))

    def test_pick_option_reads_the_list_and_selects_by_title(self):
        with tempfile.TemporaryDirectory() as d:
            tsv = Path(d) / "探路-PJA110.tsv"
            tsv.write_text("com.a\t设置\t个性化推荐\t开\t★\t\n", encoding="utf-8")
            pick = Path(d) / "pick.txt"
            pick.write_text("个性化推荐\n", encoding="utf-8")
            out = Path(d) / "草稿.toml"
            code, stdout, _err = self.run_gen([str(tsv), "--pick", str(pick), "-o", str(out)])
            src = out.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn('only = ["个性化推荐"]', src)
        self.assertIn("草稿已生成", stdout)

    def test_missing_pick_file_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            code, _out, err = self.run_gen([str(write_tsv(d)), "--pick", "/nope/pick.txt"])
        self.assertEqual((code, err), (1, "找不到勾选清单 /nope/pick.txt\n"))

    def test_unknown_pick_titles_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            pick = Path(d) / "pick.txt"
            pick.write_text("不存在甲\n不存在乙\n", encoding="utf-8")
            code, stdout, _err = self.run_gen([str(write_tsv(d)), "--pick", str(pick),
                                               "-o", str(Path(d) / "x.toml")])
        self.assertEqual(code, 0)
        self.assertIn("⚠ 勾选清单里这些开关在探路结果里找不到，未写进草稿：不存在乙、不存在甲", stdout)

    def test_protection_and_unpicked_ad_switches_are_reported(self):
        text = TSV.replace(
            "com.heytap.market\t设置 > 隐私\t应用安全\t开\t\t",
            "com.heytap.market\t设置 > 隐私\t应用安全\t开\t\t\n"
            "com.heytap.market\t设置\t限制广告跟踪\t开\t★\t关\n")
        with tempfile.TemporaryDirectory() as d:
            code, stdout, _err = self.run_gen([str(write_tsv(d, text=text)), "-o", str(Path(d) / "x.toml")])
        self.assertEqual(code, 0)
        self.assertIn("⚠ 这些是保护类开关（打开才是保护），没有写进草稿：限制广告跟踪、限制广告跟踪", stdout)
        self.assertIn("另有 1 个疑似广告开关没有勾选，未写进草稿（工具不自动决定关哪些）", stdout)


class GenOutputTests(unittest.TestCase):
    def run_gen(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adapt.cmd_gen(argv)
        return code, out.getvalue(), err.getvalue()

    def test_default_output_uses_the_model_from_the_tsv_name(self):
        with tempfile.TemporaryDirectory() as d, contextlib.chdir(d):
            code, stdout, _err = self.run_gen([str(write_tsv(d))])
            files = sorted(path.name for path in Path(d).iterdir())
        self.assertEqual(code, 0)
        self.assertIn("草稿-PJA110.toml", files)
        self.assertIn("草稿已生成：草稿-PJA110.toml（2 段，2 个开关，均为待验证）", stdout)

    def test_default_output_without_a_model_is_the_plain_draft_name(self):
        with tempfile.TemporaryDirectory() as d, contextlib.chdir(d):
            tsv = Path(d) / "results.tsv"
            tsv.write_text("com.a\t设置\t个性化推荐\t开\t★\t关\n", encoding="utf-8")
            code, stdout, _err = self.run_gen([str(tsv)])
            files = sorted(path.name for path in Path(d).iterdir())
        self.assertEqual(code, 0)
        self.assertIn("草稿.toml", files)
        self.assertIn("没能从文件名认出型号，MODELS 为空；补型号用 --model，或直接把文件名改成 探路-<型号>.tsv\n",
                      stdout)

    def test_missing_build_warns_and_next_steps_are_printed(self):
        with tempfile.TemporaryDirectory() as d, contextlib.chdir(d):
            code, stdout, _err = self.run_gen([str(write_tsv(d))])
        self.assertEqual(code, 0)
        self.assertIn("BUILD 为空：自检时不比对系统版本；转正式脚本前请填上录制版本"
                      "（小米系填 ro.mi.os.version.incremental，别填 ro.build.display.id 的 Android 底包）", stdout)
        self.assertIn("下一步：python3 tool/run.py -s <序列号> adapt check 草稿-PJA110.toml", stdout)
        self.assertIn("自检通过也不等于适配完成：请人工在手机上核对每一步，再决定是否转为正式机型脚本。\n",
                      stdout)

    def test_given_model_and_build_silence_the_two_warnings(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.toml"
            code, stdout, _err = self.run_gen([str(write_tsv(d, name="results.tsv")), "-o", str(out),
                                               "--model", "PJA110", "--build", "PJA110_14"])
            src = out.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertNotIn("没能从文件名认出型号", stdout)
        self.assertNotIn("BUILD 为空", stdout)
        self.assertIn('build = "PJA110_14"', src)

    def test_option_before_the_tsv_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.toml"
            code, _stdout, _err = self.run_gen(["-o", str(out), str(write_tsv(d))])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())

    def test_write_failure_names_the_target(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "missing-dir" / "x.toml"
            code, _out, err = self.run_gen([str(write_tsv(d)), "-o", str(target)])
        self.assertEqual(code, 1)
        self.assertIn(f"写不出 {target}：", err)

    def test_source_file_name_lands_in_the_header(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.toml"
            self.run_gen([str(write_tsv(d)), "-o", str(out)])
            src = out.read_text(encoding="utf-8")
        self.assertIn("来源：探路-PJA110.tsv", src)


class CheckDraftShellTests(unittest.TestCase):
    def draft(self, directory, build=""):
        out = Path(directory) / "草稿.toml"
        extra = ["--build", build] if build else []
        with contextlib.redirect_stdout(io.StringIO()):
            adapt.cmd_gen([str(write_tsv(directory)), "-o", str(out), *extra])
        return out

    def phone(self, build="PJA110_14.0.0.812", osv="OS2.0.1.0"):
        p = draft_phone([[]] * 10)
        p.off.return_value = 1
        answers = {"getprop ro.build.display.id": build,
                   "getprop ro.mi.os.version.incremental": osv}

        def shell(command):
            return shell_result(answers[command])

        p.shell.side_effect = shell
        return p

    def run_draft(self, path, phone):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report = adapt.check_draft(phone, str(path))
        return report, out.getvalue()

    def test_capture_task_and_both_version_commands(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.phone()
            self.run_draft(self.draft(d), p)
        self.assertEqual(p.screen.captures.task, "adapt")
        commands = [call.args[0] for call in p.shell.call_args_list]
        self.assertEqual(commands, ["getprop ro.build.display.id", "getprop ro.mi.os.version.incremental"])

    def test_matching_display_id_produces_no_warning(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d, build="PJA110_14")
            _report, out = self.run_draft(path, self.phone())
        self.assertNotIn("⚠", out)

    def test_matching_os_version_produces_no_warning(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d, build="OS2.0")
            _report, out = self.run_draft(path, self.phone())
        self.assertNotIn("⚠", out)

    def test_mismatch_warns_with_the_system_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d, build="XXX")
            _report, out = self.run_draft(path, self.phone(osv=""))
        self.assertIn("⚠ 草稿标注 BUILD XXX，这台是 PJA110_14.0.0.812：按安全模式跑（只关点名的开关）", out)

    def test_draft_without_build_is_not_compared(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d, build="")
            _report, out = self.run_draft(path, self.phone())
        self.assertNotIn("⚠", out)

    def test_a_draft_without_a_build_key_uses_no_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "草稿.toml"
            path.write_text('[[segment]]\nname = "x"\nops = [{kind = "start", pkg = "com.a"}]\n',
                            encoding="utf-8")
            _report, out = self.run_draft(path, self.phone())
        self.assertNotIn("⚠", out)


class ReportOutputTests(unittest.TestCase):
    def render(self, report):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = adapt.print_report(report)
        return ok, out.getvalue()

    def test_all_closed_is_a_pass_with_the_caveat(self):
        ok, text = self.render({"verified": 1, "failed_steps": []})
        self.assertTrue(ok)
        self.assertEqual(text.splitlines(), [
            "",
            "================ 适配报告（草稿 · 安全模式自检） ================",
            "  回读确认关闭：1 项",
            "  未完成步骤：0 个",
            "结论：自检通过——勾选的开关都已找到并回读确认关闭。",
            "      这仍不代表适配完成：请人工在手机上核对入口和效果，再决定是否转为正式机型脚本。",
            "==================================================================",
        ])

    def test_partial_completion_lists_the_failed_steps(self):
        ok, text = self.render({"verified": 2, "failed_steps": ["甲", "乙"]})
        self.assertFalse(ok)
        self.assertIn("  未完成步骤：2 个（甲、乙）\n", text)
        self.assertIn("结论：部分完成——已确认关闭的项见上；没做成的那几步必须人工在手机上核对，\n", text)
        self.assertIn("      不能把部分完成当成适配成功。\n", text)
        self.assertNotIn("XX", text)

    def test_zero_readbacks_is_a_failure_without_a_failed_list_tail(self):
        ok, text = self.render({"verified": 0, "failed_steps": []})
        self.assertFalse(ok)
        self.assertIn("  未完成步骤：0 个", text)
        self.assertNotIn("XXXX", text)
        self.assertIn("结论：自检未通过——没有回读确认关闭任何开关。请把上面的开关名和步骤名交给人工核对。\n", text)
        self.assertNotIn("XX", text)


class CheckCommandTests(unittest.TestCase):
    def draft(self, directory):
        out = Path(directory) / "草稿.toml"
        with contextlib.redirect_stdout(io.StringIO()):
            adapt.cmd_gen([str(write_tsv(directory)), "-o", str(out)])
        return out

    def phone(self, stay="7"):
        p = draft_phone([[]] * 10)
        p.off.return_value = 1
        p.locked.return_value = False

        def shell(command):
            return shell_result(stay if command.endswith("stay_on_while_plugged_in") else "PJA110_14")

        p.shell.side_effect = shell
        return p

    def run_check(self, argv, phone=None):
        p = phone or self.phone()
        out, err = io.StringIO(), io.StringIO()
        with patch.object(adapt, "Phone") as factory, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            factory.return_value.__enter__.return_value = p
            code = adapt.main(["check", *argv])
        return code, out.getvalue(), err.getvalue(), factory, p

    def test_usage_when_the_serial_is_missing(self):
        code, _out, err, factory, _p = self.run_check([])
        self.assertEqual(code, 1)
        self.assertEqual(err, "用法：run.py adapt check -s <序列号> <草稿.toml> [段名 …]\n")
        factory.assert_not_called()

    def test_short_rest_is_usage_not_an_index_error(self):
        code, _out, err, _factory, _p = self.run_check(["-s", "SER"])
        self.assertEqual(code, 1)
        self.assertIn("用法", err)

    def test_serial_and_draft_reach_the_phone_and_the_loader(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d)
            p = self.phone()
            with patch.object(adapt, "check_draft", return_value={"verified": 1, "failed_steps": []}) as draft:
                code, _out, _err, factory, _p = self.run_check(
                    ["-s", "SER", str(path), "段甲"], p)
        self.assertEqual(code, 0)
        factory.assert_called_once_with("SER")
        draft.assert_called_once_with(p, str(path), ["段甲"])

    def test_missing_draft_is_named(self):
        code, _out, err, _factory, _p = self.run_check(["-s", "SER", "/nope/草稿.toml"])
        self.assertEqual((code, err), (1, "找不到 /nope/草稿.toml\n"))

    def test_safety_mode_notice_is_printed(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d)
            _code, out, _err, _factory, _p = self.run_check(["-s", "SER", str(path)])
        self.assertIn("⚠ 安全模式自检：这份是待验证草稿，只关 only= 点名的开关，找不到就如实报告。\n", out)
        self.assertNotIn("XX", out)

    def test_stay_awake_value_is_restored(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d)
            _code, _out, _err, _factory, p = self.run_check(["-s", "SER", str(path)], self.phone(stay="7"))
        commands = [call.args[0] for call in p.shell.call_args_list]
        self.assertEqual(commands[:2], ["settings get global stay_on_while_plugged_in",
                                        "settings put global stay_on_while_plugged_in 7"])
        self.assertEqual(commands[-1], "settings put global stay_on_while_plugged_in 7")

    def test_non_numeric_stay_awake_value_restores_zero(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.draft(d)
            _code, _out, _err, _factory, p = self.run_check(["-s", "SER", str(path)], self.phone(stay="abc"))
        self.assertEqual(p.shell.call_args_list[-1].args[0],
                         "settings put global stay_on_while_plugged_in 0")


class InstalledPackagesTests(unittest.TestCase):
    def test_package_lines_are_split_once_and_noise_is_ignored(self):
        p = phone_mock()
        p.shell.return_value = shell_result("package:com.a package:com.b\nnoise\npackage:com.c\n")
        self.assertEqual(adapt._installed_packages(p),
                         {"com.a package:com.b", "com.c"})
        p.shell.assert_called_once_with("pm list packages")

    def test_an_empty_listing_is_an_empty_set(self):
        p = phone_mock()
        p.shell.return_value = shell_result("")
        self.assertEqual(adapt._installed_packages(p), set())


class OutputOnly:
    """拉起结果的最小形状：`output` 与 `exit_code`。"""

    def __init__(self, output, exit_code=0):
        self.output = output
        self.exit_code = exit_code


class LaunchFailureTests(unittest.TestCase):
    def test_output_without_an_exit_code_is_judged_by_its_text(self):
        self.assertFalse(adapt._launch_failed(OutputOnly("landed")))
        self.assertTrue(adapt._launch_failed(OutputOnly("EXCEPTION: nope")))
        self.assertTrue(adapt._launch_failed(OutputOnly("", 1)))

    def test_error_words_are_case_insensitive(self):
        self.assertTrue(adapt._has_launch_error("Error: nope"))
        self.assertTrue(adapt._has_launch_error("java.lang.exception"))
        self.assertFalse(adapt._has_launch_error(""))

    def test_nonzero_exit_code_fails_even_with_quiet_output(self):
        self.assertTrue(adapt._launch_failed(shell_result("", 1)))
        self.assertFalse(adapt._launch_failed(shell_result("", 0)))


TWO_FAMILY = {"xiaomi": {
    "系统广告": entries.Entry(menu="设置 → 广告服务", direct=(
        entries.Direct("com.a", ".A"),), app="com.app1",
        search=(entries.Search("广告", "广告"),)),
    "全局搜索": entries.Entry(menu="设置 → 搜索", direct=(
        entries.Direct("com.b", ".B"),), search=(entries.Search("隐私", "隐私"),)),
}}


class SurveyDetailTests(unittest.TestCase):
    def survey(self, p, words=(), family="xiaomi", family_map=ONE_FAMILY):
        clock = Clock()
        out = io.StringIO()
        with patch.object(entries, "ENTRIES", family_map), contextlib.redirect_stdout(out):
            rows = adapt.survey(p, family, list(words), now=clock.time, sleep=clock.sleep)
        return rows, out.getvalue()

    def test_landed_row_carries_all_five_fields(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings",
                         texts=("个性化 广告推荐",))
        rows, _out = self.survey(p, [word("个性化广告推荐")])
        self.assertEqual(rows, [{"group": "系统广告", "page": "com.android.settings.ad.AdServiceSettings",
                                 "landed": True, "expect": True, "words": ["个性化广告推荐"]}])

    def test_unopenable_row_carries_all_five_fields(self):
        p = survey_phone(start=("Error: Activity not started", 0))
        rows, _out = self.survey(p)
        self.assertEqual(rows, [{"group": "系统广告", "page": "com.android.settings.ad.AdServiceSettings",
                                 "landed": False, "expect": False, "words": []}])

    def test_landed_but_unexpected_page_carries_all_five_fields(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("别的",))
        p.expect_page.return_value = False
        rows, _out = self.survey(p)
        self.assertEqual(rows, [{"group": "系统广告", "page": "com.android.settings.ad.AdServiceSettings",
                                 "landed": True, "expect": False, "words": []}])

    def test_unknown_family_is_an_empty_run(self):
        p = survey_phone()
        rows, out = self.survey(p, family="nope", family_map=ONE_FAMILY)
        self.assertEqual(rows, [])
        self.assertIn("设置搜索词可试：无", out)

    def one_entry(self, *directs):
        return {"xiaomi": {"系统广告": entries.Entry(menu="m", direct=directs)}}

    def test_a_failed_entry_does_not_stop_the_next_direct(self):
        fmap = self.one_entry(entries.Direct("com.a", ".A"), entries.Direct("com.b", ".B"))
        p = survey_phone(focus="com.b/.B")
        base = survey_phone().shell.side_effect

        def shell(command, timeout=None):
            if command.startswith("am start") and "com.a/" in command:
                return shell_result("Error: nope")
            return base(command, timeout)

        p.shell.side_effect = shell
        rows, _out = self.survey(p, family_map=fmap)
        self.assertEqual([row["landed"] for row in rows], [False, True])

    def test_a_wait_failure_row_carries_all_five_fields_and_does_not_stop(self):
        fmap = self.one_entry(entries.Direct("com.b", ".B"), entries.Direct("com.c", ".C"))
        p = survey_phone(focus="com.c/.C")
        with patch.object(entries, "ENTRIES", fmap), \
                patch.object(wait, "until", side_effect=[False, True]), \
                contextlib.redirect_stdout(io.StringIO()):
            clock = Clock()
            rows = adapt.survey(p, "xiaomi", [], now=clock.time, sleep=clock.sleep)
        self.assertEqual(rows[0], {"group": "系统广告", "page": "com.b.B", "landed": False,
                                   "expect": False, "words": []})
        self.assertEqual([row["landed"] for row in rows], [False, True])

    def test_a_landed_but_unexpected_entry_does_not_stop_the_next_direct(self):
        fmap = self.one_entry(entries.Direct("com.b", ".B", "要看见甲"), entries.Direct("com.b", ".B"))
        p = survey_phone(focus="com.b/.B", texts=("没有判据文字",))
        p.expect_page.side_effect = [False]
        rows, _out = self.survey(p, family_map=fmap)
        self.assertEqual([(row["landed"], row["expect"]) for row in rows], [(True, False), (True, True)])
        p.expect_page.assert_called_once_with("要看见甲", 3)

    def test_wait_until_is_called_with_the_survey_budget(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings")
        clock = Clock()
        with patch.object(entries, "ENTRIES", ONE_FAMILY), \
                patch.object(wait, "until", return_value=True) as until, \
                contextlib.redirect_stdout(io.StringIO()):
            adapt.survey(p, "xiaomi", [], now=clock.time, sleep=clock.sleep)
        kwargs = until.call_args.kwargs
        self.assertEqual(kwargs, {"timeout": 4, "poll": 0.2, "now": clock.time, "sleep": clock.sleep})

    def test_unknown_page_text_is_named_in_the_log(self):
        p = survey_phone(focus="")
        _rows, out = self.survey(p)
        self.assertIn("落在别处（实际 未知页面）  系统广告 com.android.settings.ad.AdServiceSettings", out)

    def test_agreement_is_annotated_only_when_present(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("同意",))
        _rows, out = self.survey(p)
        self.assertIn("✓ 系统广告 com.android.settings.ad.AdServiceSettings（弹着协议，没有点）", out)

    def test_no_agreement_means_no_annotation(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("别的文字",))
        _rows, out = self.survey(p)
        self.assertIn("✓ 系统广告 com.android.settings.ad.AdServiceSettings\n", out)
        self.assertNotIn("弹着协议", out)
        self.assertNotIn("XXXX", out)

    def test_hits_are_joined_and_deduplicated(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings",
                         texts=("个性化广告推荐", "系统工具广告", "推荐"))
        rows, out = self.survey(p, [word("个性化广告推荐"), word("个性化广告推荐"), word("系统工具广告")])
        self.assertIn("同组词条：个性化广告推荐、系统工具广告", out)
        self.assertEqual(rows[0]["words"], ["个性化广告推荐", "系统工具广告"])

    def test_app_and_search_tail_lines(self):
        p = survey_phone(focus="com.a/.A", packages="package:com.a\n")
        _rows, out = self.survey(p, family_map=TWO_FAMILY)
        self.assertIn("同族脚本用过的 App：装了 1 / 3 个（没装：com.app1、com.b）", out)
        self.assertIn("设置搜索词可试：广告、隐私", out)

    def test_a_family_without_apps_does_not_ask_the_phone(self):
        fmap = {"xiaomi": {"甲": entries.Entry(menu="m")}}
        p = survey_phone()
        _rows, out = self.survey(p, family_map=fmap)
        self.assertNotIn("pm list packages", shell_calls(p))
        self.assertIn("同族脚本用过的 App：装了 0 / 0 个", out)
        self.assertIn("设置搜索词可试：无", out)

    def test_nothing_missing_leaves_no_missing_tail(self):
        p = survey_phone(focus="com.a/.A", packages="package:com.a\npackage:com.app1\npackage:com.b\n")
        _rows, out = self.survey(p, family_map=TWO_FAMILY)
        self.assertIn("同族脚本用过的 App：装了 3 / 3 个\n", out)
        self.assertNotIn("没装", out)


class SurveyCommandDetailTests(unittest.TestCase):
    def run_cmd(self, phone, argv=("-s", "FAKE"), scanned=None, family_map=ONE_FAMILY,
                label=None, brand="xiaomi"):
        scanned = [word("个性化广告推荐")] if scanned is None else scanned
        labels = {"xiaomi": "小米", "huawei": "华为"} if label is None else label
        out, err = io.StringIO(), io.StringIO()
        with patch.object(adapt, "Phone") as factory, \
                patch.object(adapt.vocab, "scan", return_value=types.SimpleNamespace(words=scanned)) as scan, \
                patch.object(entries, "ENTRIES", family_map), \
                patch.object(entries, "LABEL", labels), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            factory.return_value.__enter__.return_value = phone
            code = adapt.cmd_survey(list(argv))
        return code, out.getvalue(), err.getvalue(), scan

    def test_recipes_directory_is_passed_to_the_vocabulary_scan(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("个性化广告推荐",))
        code, _out, _err, scan = self.run_cmd(p)
        self.assertEqual(code, 0)
        scan.assert_called_once_with(str(ROOT / "recipes"))

    def test_short_rest_is_usage_not_an_index_error(self):
        code, _out, err, _scan = self.run_cmd(survey_phone(), argv=("-s",))
        self.assertEqual(code, 1)
        self.assertIn("用法：run.py -s <序列号> adapt survey", err)

    def test_usage_message_is_verbatim(self):
        code, _out, err, _scan = self.run_cmd(survey_phone(), argv=[])
        self.assertEqual((code, err), (1, "用法：run.py -s <序列号> adapt survey\n"))

    def test_locked_phone_message_is_verbatim(self):
        p = survey_phone()
        p.locked.return_value = True
        code, _out, err, _scan = self.run_cmd(p)
        self.assertEqual((code, err), (1, "手机锁屏了，请机主解锁后再跑\n"))

    def test_unknown_brand_names_the_empty_brand(self):
        code, _out, err, _scan = self.run_cmd(survey_phone(brand=""), family_map=ONE_FAMILY)
        self.assertEqual(code, 1)
        self.assertIn("认不出品牌「空」：入口速查只收了小米的机型", err)

    def test_family_without_direct_entries_uses_the_label(self):
        p = survey_phone(brand="huawei")
        code, _out, err, _scan = self.run_cmd(p, family_map={"huawei": {"系统广告": entries.Entry(menu="m")}})
        self.assertEqual(code, 1)
        self.assertIn("华为还没有直达入口记录：用 adapt explore 探路", err)

    def test_empty_vocabulary_uses_the_label(self):
        code, _out, err, _scan = self.run_cmd(survey_phone(), scanned=[])
        self.assertEqual(code, 1)
        self.assertIn("小米的词库是空的：还没有这个家族的机型脚本，先用 adapt explore 探路", err)

    def test_headline_counts_the_direct_entries(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("个性化广告推荐",))
        _code, out, _err, _scan = self.run_cmd(p)
        self.assertIn("小米：试 1 个直达入口，屏幕会跳，不要碰手机。", out)

    def test_missing_label_falls_back_to_the_family_name(self):
        p = survey_phone(brand="huawei")
        code, _out, err, _scan = self.run_cmd(
            p, family_map={"huawei": {"系统广告": entries.Entry(menu="m")}}, label={})
        self.assertEqual(code, 1)
        self.assertIn("huawei还没有直达入口记录：用 adapt explore 探路", err)

    def test_empty_vocabulary_without_a_label_falls_back_to_the_family_name(self):
        code, _out, err, _scan = self.run_cmd(survey_phone(), scanned=[], label={})
        self.assertEqual(code, 1)
        self.assertIn("xiaomi的词库是空的：还没有这个家族的机型脚本，先用 adapt explore 探路", err)

    def test_headline_without_a_label_falls_back_to_the_family_name(self):
        p = survey_phone(focus="com.android.settings/.ad.AdServiceSettings", texts=("个性化广告推荐",))
        _code, out, _err, _scan = self.run_cmd(p, label={})
        self.assertIn("xiaomi：试 1 个直达入口", out)

    def test_unknown_brand_lists_the_labels_of_every_family(self):
        family_map = {"xiaomi": ONE_FAMILY["xiaomi"],
                      "huawei": {"系统广告": entries.Entry(menu="m")}}
        code, _out, err, _scan = self.run_cmd(survey_phone(brand="nokia"), family_map=family_map)
        self.assertEqual(code, 1)
        self.assertIn("入口速查只收了小米、华为的机型", err)


if __name__ == "__main__":
    unittest.main()
