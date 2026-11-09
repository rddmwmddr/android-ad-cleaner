"""配方验证台账（tool/verify_ledger.py，#916、#917）：每个配方文件一行、缺记录显示「未记录」、
按距今天数降序、末行三档分布、验证之后改过的标「待复核」。

前两类用例只验外部行为：给定配方目录、已解析的台账、一个注入的「今天」与注入的改动日期，
算出什么结果；不钉真实日期，也不验输出的列宽。`changed_dates()` 单独在临时 git 仓库里验。
"""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

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

    def test_three_tiers_are_read_back_with_their_fields(self):
        self.recipes("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py",
                     "honor-D/recipe_android15.py")
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0.2(CN01)", "date": "2026-11-08", "by": "机主", "tier": "已验证"},
            "oppo-B/recipe.py": {"build": "B_2.1", "date": "2026-09-01", "by": "@someone", "tier": "部分验证"},
            "vivo-C/recipe.py": {"build": "C_3.0", "date": "2026-01-05", "by": "@someone", "tier": "未记录"},
            "honor-D/recipe_android15.py": {"build": "D_4.0", "date": "2026-11-09", "by": "机主", "tier": "已验证"},
        }
        got = {row.path: row for row in verify_ledger.rows(self.dir, records, TODAY)}
        self.assertEqual(set(got), set(records))
        for path, record in records.items():
            with self.subTest(path):
                self.assertEqual(got[path].tier, record["tier"])
                self.assertEqual((got[path].build, got[path].date, got[path].verifier),
                                 (record["build"], record["date"], record["by"]))
        # 记成「未记录」的行和缺记录的行一样只打路径：没有可信记录，四样就不该出现
        self.assertIn("vivo-C/recipe.py\t未记录",
                      verify_ledger.render(self.dir, records, TODAY).splitlines())

    def test_recipe_without_a_record_still_gets_a_row(self):
        self.recipe("xiaomi-A/recipe.py")
        self.recipe("oppo-B/recipe.py")
        records = {"xiaomi-A/recipe.py": {"build": "A_1.0.2(CN01)", "date": "2026-11-08",
                                          "by": "机主", "tier": "已验证"}}
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
                                              "by": "@someone", "tier": "部分验证"}}
        rows = verify_ledger.rows(self.dir, records, TODAY)
        self.assertEqual({row.path: row.tier for row in rows},
                         {"xiaomi-A/recipe.py": verify_ledger.UNRECORDED,
                          "xiaomi-A/recipe_os4.py": "部分验证"})

    def test_days_come_from_the_injected_today(self):
        self.recipe("xiaomi-A/recipe.py")
        self.recipe("oppo-B/recipe.py")
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-10-30", "by": "机主", "tier": "已验证"},
            "oppo-B/recipe.py": {"build": "B_2.0", "date": "2026-11-09", "by": "机主", "tier": "已验证"},
        }
        got = {row.path: row.days for row in verify_ledger.rows(self.dir, records, TODAY)}
        self.assertEqual(got, {"xiaomi-A/recipe.py": 10, "oppo-B/recipe.py": 0})

    def test_render_prints_one_line_per_recipe(self):
        for name in ("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"):
            self.recipe(name)
        records = {"xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-11-08",
                                          "by": "机主", "tier": "已验证"}}
        lines = verify_ledger.render(self.dir, records, TODAY).splitlines()[:-1]  # 末行是分布
        self.assertEqual({line.split("\t")[0] for line in lines},
                         {"xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"})
        [line] = [line for line in lines if line.startswith("xiaomi-A/recipe.py\t")]
        self.assertEqual(line.split("\t")[2:], ["A_1.0", "2026-11-08", "机主", "已验证"])

    def test_rows_carry_days_and_render_sorts_them_descending(self):
        for name in ("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"):
            self.recipe(name)
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-10-30", "by": "机主", "tier": "已验证"},
            "oppo-B/recipe.py": {"build": "B_2.0", "date": "2026-11-08", "by": "@someone", "tier": "部分验证"},
        }
        lines = verify_ledger.render(self.dir, records, TODAY).splitlines()[:-1]  # 末行是分布
        self.assertEqual([line.split("\t")[0] for line in lines],
                         ["xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"])
        self.assertEqual(lines[0].split("\t")[1:], ["10", "A_1.0", "2026-10-30", "机主", "已验证"])
        self.assertEqual(lines[1].split("\t")[1], "1")
        self.assertEqual(lines[2].split("\t")[1], verify_ledger.UNRECORDED)

    def test_a_future_verification_date_is_not_negative(self):
        self.recipe("xiaomi-A/recipe.py")
        records = {"xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-11-20",
                                          "by": "机主", "tier": "已验证"}}
        self.assertEqual(verify_ledger.rows(self.dir, records, TODAY)[0].days, 0)

    def test_review_flag_marks_scripts_changed_after_verification(self):
        for name in ("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py", "honor-D/recipe.py"):
            self.recipe(name)
        records = {
            "xiaomi-A/recipe.py": {"build": "A_1.0", "date": "2026-11-01", "by": "机主", "tier": "已验证"},
            "oppo-B/recipe.py": {"build": "B_2.0", "date": "2026-11-08", "by": "机主", "tier": "已验证"},
            "vivo-C/recipe.py": {"build": "C_3.0", "date": "2026-10-01", "by": "机主", "tier": "部分验证"},
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
                                           "by": "机主", "tier": "部分验证"}
                   for name, day in days.items()}
        rows = verify_ledger.rows(self.dir, records, TODAY)
        self.assertEqual([row.days for row in rows], [91, 90, 31, 30, 0, None])
        counts = verify_ledger.distribution(rows)
        self.assertEqual(counts, (2, 2, 2))     # 0/30 · 31/90 · 91/未记录
        self.assertEqual(sum(counts), len(rows))
        self.assertEqual(verify_ledger.render(self.dir, records, TODAY).splitlines()[-1],
                         "30 天以内 2 · 31–90 天 2 · 90 天以上 2（共 6 份）")


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


if __name__ == "__main__":
    unittest.main()
