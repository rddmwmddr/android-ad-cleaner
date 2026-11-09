"""配方验证台账（tool/verify_ledger.py，#916）：每个配方文件一行、缺记录显示「未记录」、三档都读得出。

只验外部行为：给定配方目录、已解析的台账和一个注入的「今天」，算出什么结果。
不钉真实日期，也不验输出的列宽。
"""
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

    def test_three_tiers_are_read_back_with_their_fields(self):
        for name in ("xiaomi-A/recipe.py", "oppo-B/recipe.py", "vivo-C/recipe.py"):
            self.recipe(name)
        self.recipe("honor-D/recipe_android15.py")
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
        self.assertEqual([row.path for row in rows],
                         ["xiaomi-A/recipe.py", "xiaomi-A/recipe_os4.py"])
        self.assertEqual([row.tier for row in rows], [verify_ledger.UNRECORDED, "部分验证"])

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
        lines = verify_ledger.render(self.dir, records, TODAY).rstrip("\n").split("\n")
        self.assertEqual([line.split("\t")[0] for line in lines],
                         ["oppo-B/recipe.py", "vivo-C/recipe.py", "xiaomi-A/recipe.py"])
        self.assertEqual(lines[-1].split("\t")[1:],
                         ["A_1.0", "2026-11-08", "机主", "已验证"])


if __name__ == "__main__":
    unittest.main()
