"""配方验证台账（tool/verify_ledger.py，#916、#917、#918）：每个配方文件一行、缺记录显示「未记录」、
按距今天数降序、末行三档分布、验证之后改过的标「待复核」、记录的 build 对不上脚本 BUILD 的标「build 不符」。

覆盖度（`tier`）与证据来源（`evidence`）是两个维度：前两类用例里 `entry()` 单独验「台账里没有这份脚本
时退回未记录 / 未知」，`rows()` 验两个值都被带到行上。

前两类用例只验外部行为：给定配方目录、已解析的台账、一个注入的「今天」、注入的改动日期与注入的
脚本 BUILD，算出什么结果；不钉真实日期，也不验输出的列宽。`changed_dates()` 单独在临时 git 仓库里验。

最后一类是数据契约：直接读真实 `recipes/` 与 `recipes/verified.toml`，不注入假数据——它的价值就是
「真实数据符合契约」（形状照 tests/test_vocab.py 的 RealRecipesTest）。

末尾还有 `status-json` 那一段（#1124）：覆盖度、证据来源与验证日期由引擎现读台账再透传给客户端。
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import run  # noqa: E402
import verify_ledger  # noqa: E402

TODAY = date(2026, 11, 9)


class RowsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def recipe(self, name):
        path = Path(self.dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('BUILD = "PMX110_17.0.0"\n', encoding="utf-8")

    def recipes(self, *names):
        for name in names:
            self.recipe(name)

    def test_three_coverage_values_are_read_back_with_their_fields(self):
        self.recipes("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py",
                     "honor-D/recipe_android15.py")
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0.2(CN01)", "date": "2026-11-08", "by": "机主",
                                   "tier": "全部", "evidence": "现场"},
            "oppo-B/recipe.py": {"build": "B_2.1", "date": "2026-09-01", "by": "@someone",
                                 "tier": "部分", "evidence": "报告者自述"},
            "vivo-C/recipe.py": {"build": "C_3.0", "date": "2026-01-05", "by": "@someone",
                                 "tier": "未记录", "evidence": "未知"},
            "honor-D/recipe_android15.py": {"build": "D_4.0", "date": "2026-11-09", "by": "机主",
                                            "tier": "全部", "evidence": "机主自测"},
        }
        got = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY)}
        self.assertEqual(set(got), set(records))
        for path, record in records.items():
            with self.subTest(path):
                self.assertEqual(got[path].tier, record["tier"])
                self.assertEqual(got[path].evidence, record["evidence"])
                self.assertEqual((got[path].build, got[path].date, got[path].verifier),
                                 (record["build"], record["date"], record["by"]))
        # 记成「未记录」的行和缺记录的行一样只打路径：没有可信记录，其余几样就不该出现
        self.assertIn("vivo-C/recipe.py\t未记录",
                      verify_ledger.render(self.dir, records, TODAY).splitlines())
        # 覆盖度与证据来源是两列，互不代替：同样的「部分」可以来自报告者自述，也可以来自用例
        line = next(line for line in verify_ledger.render(self.dir, records, TODAY).splitlines()
                    if line.startswith("oppo-B/recipe.py\t"))
        self.assertEqual(line.split("\t")[5:], ["部分", "报告者自述"])

    def test_coverage_and_evidence_round_trip_through_a_toml_file(self):
        """读写往返：写进 toml 的两个字段，`load()` + `entry()`/`rows()` 原样读回来。"""
        self.recipe("xiaomi-A/recipe.py")
        path = Path(self.dir, "verified.toml")
        path.write_text('["xiaomi-A/recipe.py"]\nbuild = "A_1.0"\ndate = "2026-11-08"\n'
                        'by = "机主"\ntier = "全部"\nevidence = "用例"\n', encoding="utf-8")
        records = verify_ledger.load(path)
        self.assertEqual(verify_ledger.entry(records, "xiaomi-A/recipe.py"),
                         ("全部", "用例", "2026-11-08"))
        [row] = verify_ledger.rows(self.dir, records, TODAY)
        self.assertEqual((row.tier, row.evidence), ("全部", "用例"))

    def test_a_script_missing_from_the_ledger_reads_as_unrecorded_and_unknown(self):
        """台账里没有这份脚本时给「未记录 / 未知 / 空」，不抛错：缺数据本身就是一个结论。"""
        records = {"xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-11-08", "by": "机主",
                                          "tier": "全部", "evidence": "现场"}}
        self.assertEqual(verify_ledger.entry(records, "oppo-B/recipe.py"),
                         (verify_ledger.UNRECORDED, verify_ledger.UNKNOWN_EVIDENCE, ""))
        self.assertEqual(verify_ledger.entry({}, ""),
                         (verify_ledger.UNRECORDED, verify_ledger.UNKNOWN_EVIDENCE, ""))

    def test_recipe_without_a_record_still_gets_a_row(self):
        self.recipe("xiaomi-A/recipe.py")
        self.recipe("oppo-B/recipe.py")
        records = {"xiaomi-A/recipe.py": {"build": "A_1.0.2(CN01)", "date": "2026-11-08",
                                          "by": "机主", "tier": "全部"}}
        rows = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY)}
        self.assertEqual(len(rows), 2)      # 缺数据不能让配方从输出里消失
        missing = rows["oppo-B/recipe.py"]
        self.assertEqual(missing.tier, verify_ledger.UNRECORDED)
        self.assertEqual((missing.build, missing.date, missing.verifier), ("", "", ""))
        self.assertIsNone(missing.days)
        self.assertIn("oppo-B/recipe.py\t未记录",
                      verify_ledger.render(self.dir, records, TODAY).splitlines())

    def test_variants_in_one_folder_are_separate_rows(self):
        self.recipe("xiaomi-A/recipe.py")
        self.recipe("xiaomi-A/recipe_os4.py")
        records = {"xiaomi-A/recipe_os4.py": {"build": "OS4.0.1", "date": "2026-10-01",
                                              "by": "@someone", "tier": "部分"}}
        rows = verify_ledger.rows(self.dir, records, TODAY)
        self.assertEqual({row.path: row.tier for row in rows},
                         {"xiaomi-A/recipe.py": verify_ledger.UNRECORDED,
                          "xiaomi-A/recipe_os4.py": "部分"})

    def test_days_come_from_the_injected_today(self):
        self.recipe("xiaomi-A/recipe.py")
        self.recipe("oppo-B/recipe.py")
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-10-30", "by": "机主", "tier": "全部"},
            "oppo-B/recipe.py": {"build": "B_2.0", "date": "2026-11-09", "by": "机主", "tier": "全部"},
        }
        got = {row.path: row.days for row in verify_ledger.rows(self.dir, records, TODAY)}
        self.assertEqual(got, {"xiaomi-A/recipe.py": 10, "oppo-B/recipe.py": 0})

    def test_render_prints_one_line_per_recipe(self):
        for name in ("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"):
            self.recipe(name)
        records = {"xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-11-08",
                                          "by": "机主", "tier": "全部"}}
        lines = verify_ledger.render(self.dir, records, TODAY).splitlines()[:-1]  # 末行是分布
        self.assertEqual({line.split("\t")[0] for line in lines},
                         {"xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"})
        [line] = [line for line in lines if line.startswith("xiaomi-A/recipe.py\t")]
        self.assertEqual(line.split("\t")[2:], ["A_1.0", "2026-11-08", "机主", "全部", "未知"])

    def test_rows_carry_days_and_render_sorts_them_descending(self):
        for name in ("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"):
            self.recipe(name)
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-10-30", "by": "机主", "tier": "全部"},
            "oppo-B/recipe.py": {"build": "B_2.0", "date": "2026-11-08", "by": "@someone", "tier": "部分"},
        }
        lines = verify_ledger.render(self.dir, records, TODAY).splitlines()[:-1]  # 末行是分布
        self.assertEqual([line.split("\t")[0] for line in lines],
                         ["xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"])
        self.assertEqual(lines[0].split("\t")[1:], ["10", "A_1.0", "2026-10-30", "机主", "全部", "未知"])
        self.assertEqual(lines[1].split("\t")[1], "1")
        self.assertEqual(lines[2].split("\t")[1], verify_ledger.UNRECORDED)

    def test_a_future_verification_date_is_not_negative(self):
        self.recipe("xiaomi-A/recipe.py")
        records = {"xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-11-20",
                                          "by": "机主", "tier": "全部"}}
        self.assertEqual(verify_ledger.rows(self.dir, records, TODAY)[0].days, 0)

    def test_review_flag_marks_scripts_changed_after_verification(self):
        for name in ("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py", "honor-D/recipe.py"):
            self.recipe(name)
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-11-01", "by": "机主", "tier": "全部"},
            "oppo-B/recipe.py": {"build": "B_2.0", "date": "2026-11-08", "by": "机主", "tier": "全部"},
            "vivo-C/recipe.py": {"build": "C_3.0", "date": "2026-10-01", "by": "机主", "tier": "部分"},
        }
        changed = {
            "xiaomi-A/recipe.py": "2026-11-08",   # 验完之后改过
            "oppo-B/recipe.py": "2026-11-08",     # 与验证同一天
            "vivo-C/recipe.py": "2026-09-30",     # 验证之前改的
            "honor-D/recipe.py": "2026-11-08",    # 没有验证记录，无从比较
        }
        rows = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY, changed=changed)}
        self.assertTrue(rows["xiaomi-A/recipe.py"].review)
        self.assertEqual(rows["xiaomi-A/recipe.py"].changed_on, "2026-11-08")
        self.assertFalse(rows["oppo-B/recipe.py"].review)
        self.assertFalse(rows["vivo-C/recipe.py"].review)
        self.assertFalse(rows["honor-D/recipe.py"].review)
        lines = verify_ledger.render(self.dir, records, TODAY, changed=changed).splitlines()
        self.assertEqual([line.split("\t")[0] for line in lines if line.endswith("待复核")],
                         ["xiaomi-A/recipe.py"])

    def test_an_explicitly_unrecorded_tier_has_no_days_or_review_flag(self):
        self.recipe("vivo-C/recipe.py")
        records = {"vivo-C/recipe.py": {"build": "C_3.0", "date": "2026-01-05",
                                        "by": "@someone", "tier": "未记录"}}
        changed = {"vivo-C/recipe.py": "2026-06-01"}
        [row] = verify_ledger.rows(self.dir, records, TODAY, changed=changed)
        self.assertEqual(row.tier, verify_ledger.UNRECORDED)
        self.assertIsNone(row.days)          # 没有可信记录：日期不参与排序、分档，也不标待复核
        self.assertFalse(row.review)
        self.assertEqual(verify_ledger.render(self.dir, records, TODAY, changed=changed).splitlines()[0],
                         f"vivo-C/recipe.py\t{verify_ledger.UNRECORDED}")

    def test_distribution_splits_rows_into_three_buckets_and_sums_to_all(self):
        days = {"a": "2026-11-09", "b": "2026-10-10", "c": "2026-10-09",
                "d": "2026-08-11", "e": "2026-08-10"}
        for name in days:
            self.recipe(f"{name}-X/recipe.py")
        self.recipe("f-X/recipe.py")     # 没有记录，并入最旧一档
        records = {f"{name}-X/recipe.py": {"build": name.upper(), "date": day,
                                           "by": "机主", "tier": "部分"}
                   for name, day in days.items()}
        rows = verify_ledger.rows(self.dir, records, TODAY)
        self.assertEqual([row.days for row in rows], [91, 90, 31, 30, 0, None])
        counts = verify_ledger.distribution(rows)
        self.assertEqual(counts, (2, 2, 2))     # 0/30 · 31/90 · 91/未记录
        self.assertEqual(sum(counts), len(rows))
        self.assertEqual(verify_ledger.render(self.dir, records, TODAY).splitlines()[-1],
                         "30 天以内 2 · 31–90 天 2 · 90 天以上 2（共 6 份）")

    def test_recorded_build_must_start_with_the_scripts_declared_build(self):
        self.recipes("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py")
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0.2(CN01)", "date": "2026-11-08",
                                   "by": "机主", "tier": "部分"},
            "oppo-B/recipe.py": {"build": "B_3.0", "date": "2026-11-08", "by": "机主", "tier": "部分"},
            "vivo-C/recipe.py": {"build": "C_3.0", "date": "2026-11-08", "by": "机主", "tier": "部分"},
        }
        builds = {"xiaomi-A/recipe.py": "A_1.0", "oppo-B/recipe.py": "B_2.0", "vivo-C/recipe.py": ""}
        rows = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY, builds=builds)}
        self.assertFalse(rows["xiaomi-A/recipe.py"].build_mismatch)
        self.assertTrue(rows["oppo-B/recipe.py"].build_mismatch)    # 记录不是脚本声明的 B_2.0 打头
        self.assertFalse(rows["vivo-C/recipe.py"].build_mismatch)   # 脚本没声明 BUILD，无从比较
        lines = verify_ledger.render(self.dir, records, TODAY, builds=builds).splitlines()
        marked = [line.split("\t")[0] for line in lines if line.endswith(verify_ledger.BUILD_MISMATCH)]
        self.assertEqual(marked, ["oppo-B/recipe.py"])

    def test_a_record_without_a_build_fails_the_prefix_check(self):
        self.recipe("xiaomi-A/recipe.py")
        records = {"xiaomi-A/recipe.py": {"date": "2026-11-08", "by": "机主", "tier": "部分"}}
        [row] = verify_ledger.rows(self.dir, records, TODAY, builds={"xiaomi-A/recipe.py": "A_1.0"})
        self.assertTrue(row.build_mismatch)   # 记录缺 build 就不是「对得上」

    def test_a_missing_record_is_not_reported_as_a_build_mismatch(self):
        self.recipe("xiaomi-A/recipe.py")
        [row] = verify_ledger.rows(self.dir, {}, TODAY, builds={"xiaomi-A/recipe.py": "A_1.0"})
        self.assertEqual((row.tier, row.build_mismatch), (verify_ledger.UNRECORDED, False))

    def test_an_unrecorded_record_is_not_checked_against_the_script_build(self):
        """「未记录」是说这份脚本没有可信记录，不是「验的时候脚本是旧版」：build 不参与校验，
        否则只想登记「还没验」的人会被报成版本不符。"""
        self.recipe("vivo-C/recipe.py")
        records = {"vivo-C/recipe.py": {"build": "", "date": "", "by": "", "tier": "未记录"}}
        rows = verify_ledger.rows(self.dir, records, TODAY, builds={"vivo-C/recipe.py": "C_3.0"})
        self.assertFalse(rows[0].build_mismatch)
        self.assertEqual(verify_ledger.render(self.dir, records, TODAY,
                                              builds={"vivo-C/recipe.py": "C_3.0"}).splitlines()[0],
                         f"vivo-C/recipe.py\t{verify_ledger.UNRECORDED}")

    def test_review_and_build_mismatch_marks_share_the_line_tail(self):
        self.recipe("xiaomi-A/recipe.py")
        records = {"xiaomi-A/recipe.py": {"build": "OLD_1.0", "date": "2026-11-01",
                                          "by": "机主", "tier": "部分"}}
        line = verify_ledger.render(self.dir, records, TODAY, changed={"xiaomi-A/recipe.py": "2026-11-08"},
                                    builds={"xiaomi-A/recipe.py": "A_2.0"}).splitlines()[0]
        self.assertTrue(line.endswith(f"{verify_ledger.REVIEW} · {verify_ledger.BUILD_MISMATCH}"))

    def test_declared_builds_are_read_from_the_scripts(self):
        self.recipe("xiaomi-A/recipe.py")
        Path(self.dir, "oppo-B").mkdir()
        Path(self.dir, "oppo-B", "recipe.py").write_text('# 无 BUILD\nVERIFIED = 0\n', encoding="utf-8")
        self.assertEqual(verify_ledger.declared_builds(self.dir),
                         {"xiaomi-A/recipe.py": "PMX110_17.0.0", "oppo-B/recipe.py": ""})


class ChangedDatesTest(unittest.TestCase):
    """生产路径：从 git 取每个配方最后一次改动的作者日期。用临时仓库，不碰真实 `recipes/`。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.recipes = self.root / "recipes"
        self.recipes.mkdir()

    def git(self, *args, env=None):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, env=env,
                       capture_output=True)

    def commit_recipe(self, name, author_date):
        path = self.recipes / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('BUILD = "A_1.0"\n', encoding="utf-8")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
               "GIT_AUTHOR_DATE": f"{author_date}T10:00:00+0800",
               "GIT_COMMITTER_DATE": "2026-11-20T10:00:00+0800"}
        self.git("add", "-A", env=env)
        # 本机全局的 commit-msg 钩子会查 DCO、可能还带签名，临时仓库里一律关掉
        self.git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-qm", name, env=env)

    def test_author_date_of_the_last_commit_touching_each_recipe(self):
        self.git("init", "-q")
        self.commit_recipe("xiaomi-A/recipe.py", "2026-11-05")
        self.commit_recipe("oppo-B/recipe.py", "2026-10-01")
        # 提交日期（2026-11-20）故意晚于作者日期：rebase 会改写前者，不该被它带偏
        self.assertEqual(verify_ledger.changed_dates(self.recipes),
                         {"xiaomi-A/recipe.py": "2026-11-05", "oppo-B/recipe.py": "2026-10-01"})

    def test_a_folder_outside_git_yields_no_dates(self):
        (self.recipes / "xiaomi-A").mkdir()
        (self.recipes / "xiaomi-A" / "recipe.py").write_text('BUILD = "A_1.0"\n', encoding="utf-8")
        self.assertEqual(verify_ledger.changed_dates(self.recipes), {})


class RealRecipesContractTest(unittest.TestCase):
    """真实仓库的数据契约，无注入点：每份配方都有条目、记录的 build 对得上脚本 BUILD、
    覆盖度与证据来源都是已知取值、日期格式合法。台账真正的失效方式是「新配方悄悄不在里面」，
    这一类就是拦它。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = str(ROOT / "recipes")
        cls.records = verify_ledger.load(os.path.join(cls.dir, "verified.toml"))
        cls.paths = verify_ledger.recipe_paths(cls.dir)

    def test_every_recipe_file_has_a_record(self):
        missing = sorted(set(self.paths) - set(self.records))
        self.assertEqual(missing, [],
                         "新配方要在 recipes/verified.toml 里登记，内容可以是「未记录」：\n" + "\n".join(missing))

    def test_no_record_is_left_for_a_recipe_that_no_longer_exists(self):
        stale = sorted(set(self.records) - set(self.paths))
        self.assertEqual(stale, [], "配方改名或删除后，台账里的旧 key 要跟着删：\n" + "\n".join(stale))

    def test_every_record_has_the_five_fields(self):
        for path, record in sorted(self.records.items()):
            with self.subTest(path):
                self.assertEqual(set(record), {"build", "date", "by", "tier", "evidence"})
                for field in ("build", "date", "by", "evidence"):
                    self.assertIsInstance(record[field], str)

    def test_recorded_builds_start_with_the_scripts_declared_build(self):
        builds = verify_ledger.declared_builds(self.dir)
        bad = [f"{path}: 记录 {self.records[path]['build']!r} 不以脚本 BUILD {builds[path]!r} 打头"
               for path in self.paths
               if path in self.records and self.records[path]["tier"] != verify_ledger.UNRECORDED
               and not verify_ledger.build_matches(self.records[path]["build"], builds[path])]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_tiers_are_known_words_and_dates_are_strict_iso(self):
        for path, record in sorted(self.records.items()):
            with self.subTest(path):
                self.assertIn(record["tier"], verify_ledger.TIERS)
                self.assertIn(record["evidence"], verify_ledger.EVIDENCE_KINDS)
                day = record["date"]
                if record["tier"] == verify_ledger.UNRECORDED:
                    self.assertEqual(day, "")   # 没有可信记录就不该有日期，否则排序与分档会被假数据带偏
                else:
                    self.assertEqual(str(date.fromisoformat(day)), day, "日期要写成 YYYY-MM-DD 且真有这一天")


# ---------- #1124：`status-json` 带出覆盖度、证据来源与验证日期 ----------
# 三个值都由引擎从 `recipes/verified.toml` 现读，客户端只透传。这里守两件外部行为：
# 真机上有的脚本，出来的是台账里那一行；台账里没有的脚本，出来的是「未记录 / 未知 / 空」而不是崩。
# 读设备的那几个协作方替身化只是为了把 `status-json` 跑起来——它们的输出由 CLI 逐字节对拍守着
# （`tests/baselines/run_cli.json`），这里断言的是台账确实被读、读到的是哪份路径。
LEDGER = verify_ledger.load(os.path.join(ROOT, "recipes", "verified.toml"))
LEDGER_PATH = os.path.join(run.RECIPES, "verified.toml")


def status_json(device=None):
    """跑一次 `status-json`，返回 (JSON, 台账读取的替身)；`device` 是 `info()` 的返回值。"""
    device = device or {"model": "M154FF", "brand": "Xiaomi", "name": "Xiaomi 13",
                        "build": "OS4.0.24", "os": "OS4.0.24"}
    out = io.StringIO()
    with patch.object(run, "info", return_value=device), \
         patch.object(run, "locked", return_value=False), \
         patch.object(run, "ad_packages", return_value=()), \
         patch.object(run, "quickapps", return_value=[]), \
         patch.object(run, "sh", return_value=""), \
         patch.object(run, "fold_open", return_value=False), \
         patch.object(run, "input_blocked", return_value=False), \
         patch.object(verify_ledger, "load", wraps=verify_ledger.load) as load, \
         contextlib.redirect_stdout(out):
        assert run.cmd_status_json("S", []) == 0
    return json.loads(out.getvalue().strip().splitlines()[-1]), load


class StatusJsonVerificationTests(unittest.TestCase):
    def test_values_come_from_the_ledger_row_for_this_script(self):
        st, load = status_json()
        # `recipe` 是仓库相对路径，分隔符跟着平台走；台账键另在引擎侧统一成 "/"
        self.assertEqual(st["recipe"], os.path.join("recipes", "xiaomi-M154FF", "recipe.py"))
        load.assert_called_once_with(LEDGER_PATH)
        record = LEDGER["xiaomi-M154FF/recipe.py"]
        self.assertEqual((st["recipe_coverage"], st["recipe_evidence"], st["recipe_verified"]),
                         (record["tier"], record["evidence"], record["date"]))

    def test_a_script_missing_from_the_ledger_is_unrecorded_and_unknown(self):
        """没有专用脚本的机型：三个值照样有，是「未记录 / 未知 / 空」，不是异常也不是缺键。
        没有脚本可查时连台账都不该读。"""
        st, load = status_json(device={"model": "NOPE-1", "brand": "Foo", "name": "Foo NOPE-1",
                                       "build": "X", "os": "X"})
        self.assertIsNone(st["recipe"])
        load.assert_not_called()
        self.assertEqual((st["recipe_coverage"], st["recipe_evidence"], st["recipe_verified"]),
                         (verify_ledger.UNRECORDED, verify_ledger.UNKNOWN_EVIDENCE, ""))


if __name__ == "__main__":
    unittest.main()
