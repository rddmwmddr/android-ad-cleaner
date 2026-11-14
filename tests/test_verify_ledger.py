"""配方验证台账（tool/verify_ledger.py，沿用 #916、#917、#918；段体哈希判据见 #1242）：
每个配方文件一行、缺记录显示「未记录」、按距今天数降序、末行三档分布、段体正文改过的标「待复核」、
记录的 build 对不上脚本 BUILD 的标「build 不符」。

覆盖度（`tier`）与证据来源（`evidence`）是两个维度：前两类用例里 `entry()` 单独验「台账里没有这份脚本
时退回未记录 / 未知」，`rows()` 验两个值都被带到行上。

前两类用例只验外部行为：给定配方目录、已解析的台账、一个注入的「今天」、注入的段体哈希与注入的
脚本 BUILD，算出什么结果；不钉真实日期，也不验输出的列宽。`body_hash()` 用临时脚本文件验「归一」
到底消掉了哪些差异：注释与格式不算改，段体正文或段名改了才算改（例外 `.py` 是整文件，顺序进哈希，
见 `ExceptionBodyTest`）。

最后一类是数据契约：直接读真实 `recipes/` 与 `recipes/verified.toml`，不注入假数据——它的价值就是
「真实数据符合契约」（形状照 tests/test_vocab.py 的 RealRecipesTest）。

末尾还有 `status-json` 那一段（#1124）：覆盖度、证据来源与验证日期由引擎现读台账再透传给客户端。
"""
import contextlib
import io
import json
import os
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
        model = path.stem.split("-", 1)[0]
        path.write_text(f'model = "{model}"\nmodels = ["{model}"]\nbuild = "PMX110_17.0.0"\n',
                        encoding="utf-8")

    def recipes(self, *names):
        for name in names:
            self.recipe(name)

    def test_three_coverage_values_are_read_back_with_their_fields(self):
        self.recipes("xiaomi/A/A.toml", "oppo/B/B.toml", "vivo/C/C.toml",
                     "honor/D/D-android15.toml")
        records = {
            "xiaomi/A/A.toml": {"build": "A_1.0.2(CN01)", "date": "2026-11-08", "by": "机主",
                                   "tier": "全部", "evidence": "现场"},
            "oppo/B/B.toml": {"build": "B_2.1", "date": "2026-09-01", "by": "@someone",
                                 "tier": "部分", "evidence": "报告者自述"},
            "vivo/C/C.toml": {"build": "C_3.0", "date": "2026-01-05", "by": "@someone",
                                 "tier": "未记录", "evidence": "未知"},
            "honor/D/D-android15.toml": {"build": "D_4.0", "date": "2026-11-09", "by": "机主",
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
        self.assertIn("vivo/C/C.toml\t未记录",
                      verify_ledger.render(self.dir, records, TODAY).splitlines())
        # 覆盖度与证据来源是两列，互不代替：同样的「部分」可以来自报告者自述，也可以来自用例
        line = next(line for line in verify_ledger.render(self.dir, records, TODAY).splitlines()
                    if line.startswith("oppo/B/B.toml\t"))
        self.assertEqual(line.split("\t")[5:], ["部分", "报告者自述"])

    def test_coverage_and_evidence_round_trip_through_a_toml_file(self):
        """读写往返：写进 toml 的两个字段，`load()` + `entry()`/`rows()` 原样读回来。"""
        self.recipe("xiaomi/A/A.toml")
        path = Path(self.dir, "verified.toml")
        path.write_text('["xiaomi/A/A.toml"]\nbuild = "A_1.0"\ndate = "2026-11-08"\n'
                        'by = "机主"\ntier = "全部"\nevidence = "用例"\n', encoding="utf-8")
        records = verify_ledger.load(path)
        self.assertEqual(verify_ledger.entry(records, "xiaomi/A/A.toml"),
                         ("全部", "用例", "2026-11-08"))
        [row] = verify_ledger.rows(self.dir, records, TODAY)
        self.assertEqual((row.tier, row.evidence), ("全部", "用例"))

    def test_a_script_missing_from_the_ledger_reads_as_unrecorded_and_unknown(self):
        """台账里没有这份脚本时给「未记录 / 未知 / 空」，不抛错：缺数据本身就是一个结论。"""
        records = {"xiaomi/A/A.toml": {"build": "A_1.0", "date": "2026-11-08", "by": "机主",
                                          "tier": "全部", "evidence": "现场"}}
        self.assertEqual(verify_ledger.entry(records, "oppo/B/B.toml"),
                         (verify_ledger.UNRECORDED, verify_ledger.UNKNOWN_EVIDENCE, ""))
        self.assertEqual(verify_ledger.entry({}, ""),
                         (verify_ledger.UNRECORDED, verify_ledger.UNKNOWN_EVIDENCE, ""))

    def test_recipe_without_a_record_still_gets_a_row(self):
        self.recipe("xiaomi/A/A.toml")
        self.recipe("oppo/B/B.toml")
        records = {"xiaomi/A/A.toml": {"build": "A_1.0.2(CN01)", "date": "2026-11-08",
                                          "by": "机主", "tier": "全部"}}
        rows = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY)}
        self.assertEqual(len(rows), 2)      # 缺数据不能让配方从输出里消失
        missing = rows["oppo/B/B.toml"]
        self.assertEqual(missing.tier, verify_ledger.UNRECORDED)
        self.assertEqual((missing.build, missing.date, missing.verifier), ("", "", ""))
        self.assertIsNone(missing.days)
        self.assertIn("oppo/B/B.toml\t未记录",
                      verify_ledger.render(self.dir, records, TODAY).splitlines())

    def test_variants_in_one_folder_are_separate_rows(self):
        self.recipe("xiaomi/A/A.toml")
        self.recipe("xiaomi/A/A-os4.toml")
        records = {"xiaomi/A/A-os4.toml": {"build": "OS4.0.1", "date": "2026-10-01",
                                              "by": "@someone", "tier": "部分"}}
        rows = verify_ledger.rows(self.dir, records, TODAY)
        self.assertEqual({row.path: row.tier for row in rows},
                         {"xiaomi/A/A.toml": verify_ledger.UNRECORDED,
                          "xiaomi/A/A-os4.toml": "部分"})

    def test_days_come_from_the_injected_today(self):
        self.recipe("xiaomi/A/A.toml")
        self.recipe("oppo/B/B.toml")
        records = {
            "xiaomi/A/A.toml": {"build": "A_1.0", "date": "2026-10-30", "by": "机主", "tier": "全部"},
            "oppo/B/B.toml": {"build": "B_2.0", "date": "2026-11-09", "by": "机主", "tier": "全部"},
        }
        got = {row.path: row.days for row in verify_ledger.rows(self.dir, records, TODAY)}
        self.assertEqual(got, {"xiaomi/A/A.toml": 10, "oppo/B/B.toml": 0})

    def test_render_prints_one_line_per_recipe(self):
        for name in ("xiaomi/A/A.toml", "oppo/B/B.toml", "vivo/C/C.toml"):
            self.recipe(name)
        records = {"xiaomi/A/A.toml": {"build": "A_1.0", "date": "2026-11-08",
                                          "by": "机主", "tier": "全部"}}
        lines = verify_ledger.render(self.dir, records, TODAY).splitlines()[:-1]  # 末行是分布
        self.assertEqual({line.split("\t")[0] for line in lines},
                         {"xiaomi/A/A.toml", "oppo/B/B.toml", "vivo/C/C.toml"})
        [line] = [line for line in lines if line.startswith("xiaomi/A/A.toml\t")]
        self.assertEqual(line.split("\t")[2:], ["A_1.0", "2026-11-08", "机主", "全部", "未知"])

    def test_rows_carry_days_and_render_sorts_them_descending(self):
        for name in ("xiaomi/A/A.toml", "oppo/B/B.toml", "vivo/C/C.toml"):
            self.recipe(name)
        records = {
            "xiaomi/A/A.toml": {"build": "A_1.0", "date": "2026-10-30", "by": "机主", "tier": "全部"},
            "oppo/B/B.toml": {"build": "B_2.0", "date": "2026-11-08", "by": "@someone", "tier": "部分"},
        }
        lines = verify_ledger.render(self.dir, records, TODAY).splitlines()[:-1]  # 末行是分布
        self.assertEqual([line.split("\t")[0] for line in lines],
                         ["xiaomi/A/A.toml", "oppo/B/B.toml", "vivo/C/C.toml"])
        self.assertEqual(lines[0].split("\t")[1:], ["10", "A_1.0", "2026-10-30", "机主", "全部", "未知"])
        self.assertEqual(lines[1].split("\t")[1], "1")
        self.assertEqual(lines[2].split("\t")[1], verify_ledger.UNRECORDED)

    def test_a_future_verification_date_is_not_negative(self):
        self.recipe("xiaomi/A/A.toml")
        records = {"xiaomi/A/A.toml": {"build": "A_1.0", "date": "2026-11-20",
                                          "by": "机主", "tier": "全部"}}
        self.assertEqual(verify_ledger.rows(self.dir, records, TODAY)[0].days, 0)

    def test_review_flag_marks_scripts_whose_step_body_hash_moved(self):
        for name in ("xiaomi/A/A.toml", "oppo/B/B.toml", "vivo/C/C.toml", "honor/D/D.toml"):
            self.recipe(name)
        records = {
            "xiaomi/A/A.toml": {"build": "A_1.0", "date": "2026-11-01", "by": "机主",
                                   "tier": "全部", "body_hash": "aaaaaaaaaaaaaaaa"},
            "oppo/B/B.toml": {"build": "B_2.0", "date": "2026-11-08", "by": "机主",
                                 "tier": "全部", "body_hash": "bbbbbbbbbbbbbbbb"},
            "vivo/C/C.toml": {"build": "C_3.0", "date": "2026-10-01", "by": "机主",
                                 "tier": "部分", "body_hash": "cccccccccccccccc"},
        }
        hashes = {
            "xiaomi/A/A.toml": "aaaaaaaaaaaaaaaa",   # 段体没变
            "oppo/B/B.toml": "bbbbbbbbbbbbbbbb",     # 段体没变
            "vivo/C/C.toml": "dddddddddddddddd",     # 段体改过
            "honor/D/D.toml": "eeeeeeeeeeeeeeee",    # 没有验证记录，无从比较
        }
        rows = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY, hashes=hashes)}
        self.assertFalse(rows["xiaomi/A/A.toml"].review)
        self.assertFalse(rows["oppo/B/B.toml"].review)
        self.assertTrue(rows["vivo/C/C.toml"].review)
        self.assertFalse(rows["honor/D/D.toml"].review)
        # 哈希本身不进输出行：判据在行尾的那个词上
        lines = verify_ledger.render(self.dir, records, TODAY, hashes=hashes).splitlines()
        self.assertEqual([line.split("\t")[0] for line in lines if line.endswith("待复核")],
                         ["vivo/C/C.toml"])
        self.assertNotIn("cccccccccccccccc", "\n".join(lines))

    def test_a_record_without_a_hash_is_not_marked_for_review(self):
        """旧记录没有 body_hash 时是「尚未建立基线」，不是「改过」：把无从比较当成改过会让
        整份旧台账一上来全红，反而看不出哪一份真的变过。"""
        for name in ("xiaomi/A/A.toml", "oppo/B/B.toml"):
            self.recipe(name)
        records = {
            "xiaomi/A/A.toml": {"build": "A_1.0", "date": "2026-11-01", "by": "机主", "tier": "全部"},
            "oppo/B/B.toml": {"build": "B_2.0", "date": "2026-11-08", "by": "机主", "tier": "全部",
                                 "body_hash": "b" * 16},
        }
        hashes = {"xiaomi/A/A.toml": "a" * 16, "oppo/B/B.toml": ""}   # 后一份当前哈希也读不到
        rows = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY, hashes=hashes)}
        self.assertFalse(rows["xiaomi/A/A.toml"].review)
        self.assertFalse(rows["oppo/B/B.toml"].review)

    def test_an_explicitly_unrecorded_tier_has_no_days_or_review_flag(self):
        self.recipe("vivo/C/C.toml")
        records = {"vivo/C/C.toml": {"build": "C_3.0", "date": "2026-01-05",
                                        "by": "@someone", "tier": "未记录",
                                        "body_hash": "c" * 16}}
        hashes = {"vivo/C/C.toml": "d" * 16}
        [row] = verify_ledger.rows(self.dir, records, TODAY, hashes=hashes)
        self.assertEqual(row.tier, verify_ledger.UNRECORDED)
        self.assertIsNone(row.days)          # 没有可信记录：日期不参与排序、分档，也不标待复核
        self.assertFalse(row.review)
        self.assertEqual(verify_ledger.render(self.dir, records, TODAY, hashes=hashes).splitlines()[0],
                         f"vivo/C/C.toml\t{verify_ledger.UNRECORDED}")

    def test_distribution_splits_rows_into_three_buckets_and_sums_to_all(self):
        days = {"a": "2026-11-09", "b": "2026-10-10", "c": "2026-10-09",
                "d": "2026-08-11", "e": "2026-08-10"}
        for name in days:
            self.recipe(f"{name}/X/X.toml")
        self.recipe("f/X/X.toml")     # 没有记录，并入最旧一档
        records = {f"{name}/X/X.toml": {"build": name.upper(), "date": day,
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
        self.recipes("xiaomi/A/A.toml", "oppo/B/B.toml", "vivo/C/C.toml")
        records = {
            "xiaomi/A/A.toml": {"build": "A_1.0.2(CN01)", "date": "2026-11-08",
                                   "by": "机主", "tier": "部分"},
            "oppo/B/B.toml": {"build": "B_3.0", "date": "2026-11-08", "by": "机主", "tier": "部分"},
            "vivo/C/C.toml": {"build": "C_3.0", "date": "2026-11-08", "by": "机主", "tier": "部分"},
        }
        builds = {"xiaomi/A/A.toml": "A_1.0", "oppo/B/B.toml": "B_2.0", "vivo/C/C.toml": ""}
        rows = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY, builds=builds)}
        self.assertFalse(rows["xiaomi/A/A.toml"].build_mismatch)
        self.assertTrue(rows["oppo/B/B.toml"].build_mismatch)    # 记录不是脚本声明的 B_2.0 打头
        self.assertFalse(rows["vivo/C/C.toml"].build_mismatch)   # 脚本没声明 BUILD，无从比较
        lines = verify_ledger.render(self.dir, records, TODAY, builds=builds).splitlines()
        marked = [line.split("\t")[0] for line in lines if line.endswith(verify_ledger.BUILD_MISMATCH)]
        self.assertEqual(marked, ["oppo/B/B.toml"])

    def test_a_record_without_a_build_fails_the_prefix_check(self):
        self.recipe("xiaomi/A/A.toml")
        records = {"xiaomi/A/A.toml": {"date": "2026-11-08", "by": "机主", "tier": "部分"}}
        [row] = verify_ledger.rows(self.dir, records, TODAY, builds={"xiaomi/A/A.toml": "A_1.0"})
        self.assertTrue(row.build_mismatch)   # 记录缺 build 就不是「对得上」

    def test_a_missing_record_is_not_reported_as_a_build_mismatch(self):
        self.recipe("xiaomi/A/A.toml")
        [row] = verify_ledger.rows(self.dir, {}, TODAY, builds={"xiaomi/A/A.toml": "A_1.0"})
        self.assertEqual((row.tier, row.build_mismatch), (verify_ledger.UNRECORDED, False))

    def test_an_unrecorded_record_is_not_checked_against_the_script_build(self):
        """「未记录」是说这份脚本没有可信记录，不是「验的时候脚本是旧版」：build 不参与校验，
        否则只想登记「还没验」的人会被报成版本不符。"""
        self.recipe("vivo/C/C.toml")
        records = {"vivo/C/C.toml": {"build": "", "date": "", "by": "", "tier": "未记录"}}
        rows = verify_ledger.rows(self.dir, records, TODAY, builds={"vivo/C/C.toml": "C_3.0"})
        self.assertFalse(rows[0].build_mismatch)
        self.assertEqual(verify_ledger.render(self.dir, records, TODAY,
                                              builds={"vivo/C/C.toml": "C_3.0"}).splitlines()[0],
                         f"vivo/C/C.toml\t{verify_ledger.UNRECORDED}")

    def test_review_and_build_mismatch_marks_share_the_line_tail(self):
        self.recipe("xiaomi/A/A.toml")
        records = {"xiaomi/A/A.toml": {"build": "OLD_1.0", "date": "2026-11-01",
                                          "by": "机主", "tier": "部分",
                                          "body_hash": "b" * 16}}
        line = verify_ledger.render(self.dir, records, TODAY, hashes={"xiaomi/A/A.toml": "a" * 16},
                                    builds={"xiaomi/A/A.toml": "A_2.0"}).splitlines()[0]
        self.assertTrue(line.endswith(f"{verify_ledger.REVIEW} · {verify_ledger.BUILD_MISMATCH}"))

    def test_declared_builds_are_read_from_the_scripts(self):
        self.recipe("xiaomi/A/A.toml")
        Path(self.dir, "oppo", "B").mkdir(parents=True)
        Path(self.dir, "oppo", "B", "B.toml").write_text('model = "B"\nmodels = ["B"]\n', encoding="utf-8")
        self.assertEqual(verify_ledger.declared_builds(self.dir),
                         {"xiaomi/A/A.toml": "PMX110_17.0.0", "oppo/B/B.toml": ""})


class BodyHashTest(unittest.TestCase):
    """段体哈希的归一（#1242）：只改注释 / 键顺序 / 段的先后不算改；段体内容或段名改了才算改。

    用临时页面树文件，不装载脚本、不碰真实 `recipes/`。两个分区各一条：一条把「迁移里会发生、
    但不该改哈希」的写法都试一遍，另一条是真正该翻成待复核的改动。
    """

    BEFORE = '''model = "A"
build = "A_1.0"

[[segment]]
name = "系统广告"
ops = [{ kind = "off", only = ["个性化广告推荐"], page = "系统·广告服务" }]

[[segment]]
name = "应用商店"
ops = [{ kind = "start", pkg = "com.xiaomi.market" }]
'''

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, text, name):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def hash_of(self, text, name="A.toml"):
        return verify_ledger.body_hash(self.write(text, name))

    def test_comments_key_order_and_segment_order_do_not_change_the_hash(self):
        """这条守的是「迁移不该翻成待复核」：注释、空白、键顺序、段的先后全变，段体内容还是那些。"""
        after = '''# 注释不吃进哈希
build = "A_1.0"
model = "A"

[[segment]]
name = "应用商店"
ops = [ { pkg = "com.xiaomi.market", kind = "start" } ]

[[segment]]
name = "系统广告"
ops = [
  { page = "系统·广告服务", only = ["个性化广告推荐"], kind = "off" },
]
'''
        self.assertEqual(self.hash_of(self.BEFORE), self.hash_of(after))

    def test_a_changed_step_body_or_step_name_changes_the_hash(self):
        body_changed = self.BEFORE.replace('"个性化广告推荐"', '"个性化推荐"')
        name_changed = self.BEFORE.replace('name = "系统广告"', 'name = "系统·广告"')
        self.assertNotEqual(self.hash_of(self.BEFORE), self.hash_of(body_changed))
        self.assertNotEqual(self.hash_of(self.BEFORE), self.hash_of(name_changed))

    def test_a_removed_step_changes_the_hash(self):
        fewer = self.BEFORE.split('[[segment]]\nname = "应用商店"')[0]
        self.assertNotEqual(self.hash_of(self.BEFORE), self.hash_of(fewer))

    def test_hashes_are_listed_by_path_with_a_short_digest(self):
        self.hash_of(self.BEFORE, "xiaomi/A/A.toml")
        self.hash_of('model = "B"\nbuild = "B_9.0"\n', "oppo/B/B.toml")
        hashes = verify_ledger.body_hashes(self.dir)
        self.assertEqual(set(hashes), {"xiaomi/A/A.toml", "oppo/B/B.toml"})
        self.assertRegex(hashes["xiaomi/A/A.toml"], rf"^[0-9a-f]{{{verify_ledger.HASH_LEN}}}$")
        listing = verify_ledger.hash_listing(self.dir)
        self.assertEqual([line.split("\t")[0] for line in listing.splitlines()],
                         ["oppo/B/B.toml", "xiaomi/A/A.toml"])
        self.assertEqual(listing.splitlines()[1].split("\t")[1], hashes["xiaomi/A/A.toml"])


class ExceptionBodyTest(unittest.TestCase):
    """同名例外 `.py` 也算段体（#1276）：B 段之后一段的知识可以整个住在 `code=` 函数里，
    只哈希 `[[segment]]` 数据会让「改过」看不出来。

    按整文件哈希，不按段收窄：例外 `.py` 只服务同目录同名的那份数据，被 `code=` 点名的函数还会
    调用同文件的助手、读模块级常量，按段收窄得把解释器的名字解析与传递闭包复刻一遍，漏一个就是又
    一次「改过看不出来」。代价是同文件里改了不相干的函数也会翻成待复核——那个文件本来就只为这一份
    数据存在。
    """

    TOML = '''model = "A"
build = "A_1.0"

[[segment]]
name = "广告跟踪"
code = "step_ads"

[[segment]]
name = "应用商店"
ops = [{ kind = "start", pkg = "com.xiaomi.market" }]
'''

    EXCEPTION = '''def step_ads(p, rt):
    p.off(only=["个性化广告推荐"], page="广告跟踪")
'''

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, text, name):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def hash_of(self, text, name="A.toml"):
        return verify_ledger.body_hash(self.write(text, name))

    def test_a_changed_exception_function_body_changes_the_hash(self):
        """票面判据：改 `code=` 指向的例外函数体 → 这一份的哈希变 → 台账翻成待复核。"""
        self.write(self.TOML, "A.toml")
        self.write(self.EXCEPTION, "A.py")
        before = verify_ledger.body_hash(self.dir / "A.toml")
        self.write(self.EXCEPTION.replace('"个性化广告推荐"', '"个性化推荐"'), "A.py")
        self.assertNotEqual(before, verify_ledger.body_hash(self.dir / "A.toml"))

    def test_a_module_level_constant_in_the_exception_also_counts(self):
        """`code=` 函数读的模块级常量（如 PMA110 的 `THEME`）不在任何函数体里。"""
        self.write(self.TOML, "A.toml")
        self.write(self.EXCEPTION, "A.py")
        before = verify_ledger.body_hash(self.dir / "A.toml")
        self.write('THEME = "com.heytap.themestore/.SettingActivity"\n\n' + self.EXCEPTION, "A.py")
        self.assertNotEqual(before, verify_ledger.body_hash(self.dir / "A.toml"))

    def test_comments_and_docstrings_in_the_exception_do_not_change_the_hash(self):
        """与 `.py` 机型脚本同档的归一：注释、docstring 不是行为，改它不该翻成待复核。

        旧树也绿（那时例外 `.py` 根本不参与哈希），守的是不回退。"""
        self.write(self.TOML, "A.toml")
        self.write(self.EXCEPTION, "A.py")
        before = verify_ledger.body_hash(self.dir / "A.toml")
        self.write('''# 注释不进哈希
"""模块说明也不进。"""


def step_ads(p, rt):
    """段说明。"""
    p.off(only=["个性化广告推荐"], page="广告跟踪")
''', "A.py")
        self.assertEqual(before, verify_ledger.body_hash(self.dir / "A.toml"))

    def test_a_py_only_script_still_hashes_its_step_bodies_only(self):
        """旧形态的 `.py` 脚本没有同名例外这一项：模块级常量改不改都不动哈希（沿用 #1242 的口径）。

        旧树也绿，守的是不回退——`_exception_body()` 认后缀时不能把自己算进去。"""
        script = '''from recipe_runtime import step

SETTINGS = "com.android.settings/.Settings"


@step("广告")
def ads(p, rt):
    p.off(only=["个性化广告推荐"], page="广告")
'''
        self.assertEqual(self.hash_of(script, "X.py"),
                         self.hash_of(script.replace("com.android.settings", "com.x"), "X.py"))


class RealRecipesContractTest(unittest.TestCase):
    """真实仓库的数据契约，无注入点：每份配方都有条目、记录的 build 对得上脚本 BUILD、
    覆盖度与证据来源都是已知取值、日期格式合法、每条记录都有段体哈希基线。台账真正的失效方式是
    「新配方悄悄不在里面」与「新条目忘了记基线」，这一类就是拦它。"""

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

    def test_every_record_has_the_six_fields(self):
        for path, record in sorted(self.records.items()):
            with self.subTest(path):
                self.assertEqual(set(record), {"build", "date", "by", "tier", "evidence", "body_hash"})
                for field in ("build", "date", "by", "evidence", "body_hash"):
                    self.assertIsInstance(record[field], str)
                # 每一条都已建立基线（2026-11-13 迁移前一次性写入）：空串或格式不对就没有判据了
                self.assertRegex(record["body_hash"], rf"^[0-9a-f]{{{verify_ledger.HASH_LEN}}}$")

    def test_every_recipe_gets_a_well_formed_hash(self):
        """真实 47 份脚本都算得出哈希。哈希是跨平台判据（CI 的 Linux 3.13、Windows 3.12），
        序列化因此不走 `ast.dump()`；跨版本对拍由本地两条解释器各跑一次 `--hash` 完成，这里只守
        覆盖与形状。"""
        hashes = verify_ledger.body_hashes(self.dir)
        self.assertEqual(set(hashes), set(self.paths))
        for path, value in sorted(hashes.items()):
            with self.subTest(path):
                self.assertRegex(value, rf"^[0-9a-f]{{{verify_ledger.HASH_LEN}}}$")

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
        # `recipe` 是脚本身份，`recipe_path` 才是仓库相对路径（分隔符跟着平台走）；台账键另在引擎侧统一成 "/"
        self.assertEqual(st["recipe"], "M154FF")
        self.assertEqual(st["recipe_path"], os.path.join("recipes", "xiaomi", "M154FF", "M154FF.toml"))
        load.assert_called_once_with(LEDGER_PATH)
        record = LEDGER["xiaomi/M154FF/M154FF.toml"]
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
