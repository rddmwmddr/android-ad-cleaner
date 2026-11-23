"""本机函数审计（tool/recipe_audit.py，#1240）：按脚本列本机模块级函数、判它归哪一档，并给出
「本机策略：N 个」。

三档归属只看函数体自己调了哪些名字（直接调用）：拨动策略 > 引擎词汇 > 真机型知识。用例分四层：

1. 判据本身：`definitions()` 只收模块级；`tier_of()` 的优先级与命中的信号。
2. 一份源码与一个配方目录的计数：`counts()` / `audit()`，含「同名函数出现在几台机型」。
3. CLI：过滤、退出码，以及**不写任何文件**。
4. `run.py` 的出口：`check` 的那一行与 `status-json` 的 `recipe_local`——数字来自同一个 `counts()`。

第 2、3 层用临时目录里的假脚本，不碰真实 `recipes/`；真实配方只做一条形状体检（段体不进出清单）。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import recipe_audit  # noqa: E402
import run  # noqa: E402

# 三档各一个本机函数。
RECIPE = '''"""假机型脚本：只给审计用例用。"""
BUILD = "OS9.9"
MODELS = ["FAKEA"]

def open_settings():
    """引擎词汇：导航与落点。"""
    p.tap(p.find("设置"))

def close_exact():
    """拨动策略：这一页的开关怎么关。"""
    for row in p.switches():
        p.off(only=[row.get("text")])

def build_id():
    """真机型知识：只有这一台才要的版本守卫。"""
    return p.shell("getprop ro.build.display.id")
'''

OTHERS = '''"""假机型脚本：与 FAKEA 定义同名的 open_settings，用来验「涉及机型数」。"""

def open_settings():
    p.tap(p.find("设置"))
'''

EMPTY = '''"""假机型脚本：没有本机函数，只有模块级常量。"""
BUILD = "OS9.9"
'''


def fake_tree(root):
    """三份假脚本：同家族的两台 + 另一家族的一台。返回 recipes 目录（按家族/型号两层，#1261）。"""
    recipes = Path(root, "recipes")
    for family, model, source in (("xiaomi", "FAKEA", RECIPE), ("xiaomi", "FAKEB", OTHERS),
                                  ("vivo", "FAKEC", EMPTY)):
        (recipes / family / model).mkdir(parents=True)
        (recipes / family / model / "recipe.py").write_text(source, encoding="utf-8")
    return recipes


class DefinitionsTests(unittest.TestCase):
    def test_line_is_the_definition_line(self):
        lines = dict(recipe_audit.definitions(RECIPE))
        self.assertEqual(sorted(lines), ["build_id", "close_exact", "open_settings"])
        self.assertEqual(lines["close_exact"], RECIPE.splitlines().index("def close_exact():") + 1)

    def test_nested_definitions_are_not_module_level(self):
        src = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
        self.assertEqual(recipe_audit.definitions(src), (("outer", 1),))


class TierTests(unittest.TestCase):
    def test_strategy_wins_when_a_body_both_navigates_and_toggles(self):
        """既导航又拨开关的算策略，那正是要收走的那一类；命中的信号一起给出来。"""
        tier, signals = recipe_audit.tier_of(["p.tap", "p.switches", "p.off"])
        self.assertEqual(tier, recipe_audit.STRATEGY)
        self.assertEqual(signals, ("p.off", "p.switches"))

    def test_navigation_only_is_vocabulary(self):
        self.assertEqual(recipe_audit.tier_of(["p.start", "p.focus"]),
                         (recipe_audit.VOCABULARY, ("p.focus", "p.start")))

    def test_neither_signal_is_device_knowledge(self):
        """读屏库直调、getprop 这类逃生口不是词汇也不是策略：它们才是该留在机型脚本里的知识。"""
        self.assertEqual(recipe_audit.tier_of(["p.shell", "RuntimeError"]),
                         (recipe_audit.KNOWLEDGE, ()))
        self.assertEqual(recipe_audit.tier_of([]), (recipe_audit.KNOWLEDGE, ()))

    def test_the_declarative_hooks_are_their_own_tier(self):
        """`tail` / `guard` / `wrap` / `detail` 按名字判成钩子，不看函数体调了什么（#1244）。

        不收的话十几个 `tail()` 会混进真机型知识，本机策略数也被收尾打印淹没。"""
        source = ('def tail():\n    print(rt.verified)\n'
                  'def guard():\n    require(p.shell("getprop x") == "1", "型号不符")\n'
                  'def helper():\n    return tail\n')
        found = {function.name: function for function in recipe_audit.classify(source)}
        self.assertEqual(found["tail"].tier, recipe_audit.HOOK)
        self.assertEqual(found["guard"].tier, recipe_audit.HOOK)
        self.assertNotEqual(found["helper"].tier, recipe_audit.HOOK)


class CountsTests(unittest.TestCase):
    def test_counts_one_recipe_by_tier(self):
        self.assertEqual(recipe_audit.counts(RECIPE),
                         {"total": 3, "strategy": 1, "vocabulary": 1, "knowledge": 1, "hook": 0})

    def test_counts_a_recipe_with_no_local_functions(self):
        self.assertEqual(recipe_audit.counts(EMPTY),
                         {"total": 0, "strategy": 0, "vocabulary": 0, "knowledge": 0, "hook": 0})

    def test_classify_keeps_the_signals_as_evidence(self):
        found = {function.name: function for function in recipe_audit.classify(RECIPE)}
        self.assertEqual((found["close_exact"].tier, found["close_exact"].signals),
                         (recipe_audit.STRATEGY, ("p.off", "p.switches")))
        self.assertEqual((found["build_id"].tier, found["build_id"].signals),
                         (recipe_audit.KNOWLEDGE, ()))


class AuditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.recipes = fake_tree(tmp.name)

    def test_totals_and_models_per_name(self):
        report = recipe_audit.audit(str(self.recipes))
        self.assertEqual([script.script for script in report.scripts],
                         ["vivo/FAKEC/recipe.py", "xiaomi/FAKEA/recipe.py", "xiaomi/FAKEB/recipe.py"])
        self.assertEqual(report.counts(),
                         {"scripts": 3, "total": 4, "strategy": 1, "vocabulary": 2, "knowledge": 1,
                          "hook": 0})
        # open_settings 在 FAKEA 与 FAKEB 上各有一份：这就是「该不该升格」的可见证据
        self.assertEqual(report.names["open_settings"], ("FAKEA", "FAKEB"))
        self.assertEqual(len(report.names["close_exact"]), 1)

    def test_family_comes_from_the_brand_segment(self):
        report = recipe_audit.audit(str(self.recipes))
        self.assertEqual({script.script: script.family for script in report.scripts},
                         {"xiaomi/FAKEA/recipe.py": "xiaomi", "xiaomi/FAKEB/recipe.py": "xiaomi",
                          "vivo/FAKEC/recipe.py": "vivo"})

    def test_filters_pick_family_model_and_tier(self):
        report = recipe_audit.audit(str(self.recipes))
        by_family = recipe_audit.filtered(report, family="vivo")
        self.assertEqual([script.model for script in by_family.scripts], ["FAKEC"])
        by_model = recipe_audit.filtered(report, model="fakeb")
        self.assertEqual([script.model for script in by_model.scripts], ["FAKEB"])
        self.assertEqual(by_model.counts()["total"], 1)
        by_tier = recipe_audit.filtered(report, tier=recipe_audit.KNOWLEDGE)
        self.assertEqual([script.model for script in by_tier.scripts], ["FAKEA"])
        self.assertEqual(by_tier.counts(),
                         {"scripts": 1, "total": 1, "strategy": 0, "vocabulary": 0, "knowledge": 1,
                          "hook": 0})


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.recipes = fake_tree(tmp.name)
        patcher = patch.object(recipe_audit, "_recipes_dir", return_value=str(self.recipes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = recipe_audit.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_json_has_the_totals_and_the_per_function_tiers(self):
        rc, out, _err = self.run_cli(["--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["totals"]["total"], 4)
        self.assertEqual(data["totals"]["shared"], 1)      # open_settings 出现在两台机型上
        functions = {f["name"]: f for s in data["scripts"] for f in s["functions"]}
        self.assertEqual(functions["close_exact"]["tier"], "strategy")
        self.assertEqual(functions["open_settings"]["models"], ["FAKEA", "FAKEB"])

    def test_text_names_the_tier_and_the_signal(self):
        rc, out, _err = self.run_cli(["--model", "FAKEA"])
        self.assertEqual(rc, 0)
        self.assertIn("过滤：机型 FAKEA", out)
        self.assertIn("- `close_exact`：拨动策略（命中 p.off、p.switches） · 机型 1 台", out)
        # 真机型知识的现场是「两档信号都不占」：把它调过的名字打出来，判据才能当场复核
        self.assertIn("- `build_id`：真机型知识（没有判据信号，只调了 p.shell）", out)

    def test_summary_skips_the_per_script_sections(self):
        rc, out, _err = self.run_cli(["--summary"])
        self.assertEqual(rc, 0)
        self.assertIn("| 小米 |", out)
        self.assertNotIn("## 按脚本", out)

    def test_filters_are_accepted_by_label_too(self):
        self.assertEqual(self.run_cli(["--family", "小米"])[0], 0)
        self.assertEqual(self.run_cli(["--tier", "拨动策略"])[0], 0)

    def test_bad_arguments_exit_with_the_reason(self):
        self.assertEqual(self.run_cli(["--tier", "nope"])[0], 1)
        self.assertEqual(self.run_cli(["--family", "nope"])[0], 1)
        rc, _out, err = self.run_cli(["--model", "NOPE"])
        self.assertEqual(rc, 1)
        self.assertIn("没有 NOPE 这个型号", err)
        self.assertEqual(self.run_cli(["--bogus"])[0], 2)
        self.assertEqual(self.run_cli(["--family"])[0], 2)

    def test_writes_nothing(self):
        """只读：跑一遍之后配方目录里的文件一个不多、一个不少。"""
        before = sorted(os.walk(self.recipes))
        self.run_cli(["--json"])
        self.run_cli([])
        self.assertEqual(sorted(os.walk(self.recipes)), before)


class RealRecipesTests(unittest.TestCase):
    def test_the_real_tree_classifies_and_never_lists_a_step_body(self):
        report = recipe_audit.audit(str(ROOT / "recipes"))
        self.assertTrue(report.scripts)
        self.assertGreater(report.counts()["total"], 0)
        self.assertNotIn("_", report.names)
        for script in report.scripts:
            for function in script.functions:
                self.assertIn(function.tier, recipe_audit.TIERS)
                self.assertTrue(function.models)


# ---------- run.py 的两个出口：`check` 的那一行与 `status-json` 的 `recipe_local` ----------
# 数字本身由上面几层用假脚本验；这里守的是「出口拿的是 `counts()` 的结果、字段名与文案不再变」。
COUNTS = {"total": 3, "strategy": 1, "vocabulary": 1, "knowledge": 1, "hook": 0}
DEVICE = {"model": "M154FF", "brand": "Xiaomi", "name": "Xiaomi 13",
          "build": "OS4.0.24", "os": "OS4.0.24", "android": "15"}


class RunOutputTests(unittest.TestCase):
    def test_status_json_carries_the_counts_of_the_script_that_will_run(self):
        out = io.StringIO()
        with patch.object(run, "info", return_value=DEVICE), \
             patch.object(run, "locked", return_value=False), \
             patch.object(run, "ad_packages", return_value=()), \
             patch.object(run, "quickapps", return_value=[]), \
             patch.object(run, "sh", return_value=""), \
             patch.object(run, "fold_open", return_value=False), \
             patch.object(run, "input_blocked", return_value=False), \
             patch.object(run.recipe_audit, "counts_for", return_value=COUNTS) as counts, \
             contextlib.redirect_stdout(out):
            self.assertEqual(run.cmd_status_json("S", []), 0)
        status = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(status["recipe_local"], COUNTS)
        # 数的是将要跑的那份脚本：读的是它的源码，不是缓存或另一份
        counts.assert_called_once_with(str(Path(run.RECIPES, "xiaomi", "M154FF", "M154FF.toml")))

    def test_status_json_without_a_script_says_none(self):
        out = io.StringIO()
        device = {"model": "NOPE-1", "brand": "Foo", "name": "Foo NOPE-1", "build": "X", "os": "X"}
        with patch.object(run, "info", return_value=device), \
             patch.object(run, "locked", return_value=False), \
             patch.object(run, "ad_packages", return_value=()), \
             patch.object(run, "quickapps", return_value=[]), \
             patch.object(run, "sh", return_value=""), \
             patch.object(run, "fold_open", return_value=False), \
             patch.object(run, "input_blocked", return_value=False), \
             contextlib.redirect_stdout(out):
            self.assertEqual(run.cmd_status_json("S", []), 0)
        status = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertIsNone(status["recipe"])
        self.assertIsNone(status["recipe_local"])

    def test_check_prints_the_strategy_and_the_breakdown(self):
        out = io.StringIO()
        with patch.object(run, "info", return_value=DEVICE), \
             patch.object(run, "locked", return_value=False), \
             patch.object(run, "input_blocked", return_value=False), \
             patch.object(run, "ad_packages", return_value=()), \
             patch.object(run, "quickapps", return_value=[]), \
             patch.object(run, "sh", return_value=""), \
             patch.object(run, "suspended", return_value=False), \
             patch.object(run.recipe_audit, "counts_for", return_value=COUNTS), \
             contextlib.redirect_stdout(out):
            self.assertEqual(run.cmd_check("S", []), 0)
        self.assertIn("本机策略：1 个；本机函数 3 个（引擎词汇 1、真机知识 1）", out.getvalue())

    def test_a_broken_script_degrades_instead_of_crashing_both_diagnostics(self):
        """语法错的脚本不能让 `check` / `status-json` 整条崩：`status-json` 崩了 GUI 与真机冒烟都拿不到
        JSON。读不出计数时 `recipe_local` 记 None、`check` 那行不打印，其余诊断照常出。"""
        status, listing = io.StringIO(), io.StringIO()
        with patch.object(run, "info", return_value=DEVICE), \
             patch.object(run, "locked", return_value=False), \
             patch.object(run, "input_blocked", return_value=False), \
             patch.object(run, "ad_packages", return_value=()), \
             patch.object(run, "quickapps", return_value=[]), \
             patch.object(run, "sh", return_value=""), \
             patch.object(run, "suspended", return_value=False), \
             patch.object(run, "fold_open", return_value=False), \
             patch.object(run.recipe_audit, "counts_for", side_effect=SyntaxError("坏脚本")):
            with contextlib.redirect_stdout(status):
                self.assertEqual(run.cmd_status_json("S", []), 0)
            with contextlib.redirect_stdout(listing):
                self.assertEqual(run.cmd_check("S", []), 0)
        payload = json.loads(status.getvalue().strip().splitlines()[-1])
        self.assertIsNone(payload["recipe_local"])
        self.assertIn("机型：", listing.getvalue())          # 别的诊断照常出
        self.assertNotIn("本机策略", listing.getvalue())     # 这一行读不出就不打印


# ---------- 判据细部：调用名、行号、计数、占位与输出形状 ----------

def tl(name, tier, line=1, signals=(), calls=(), models=()):
    return recipe_audit.LocalFunction(name, line, tier, signals, calls, models)


def sample_report():
    return recipe_audit.Report((
        recipe_audit.Script("other/M2/x.toml", "", "M2", (
            tl("open", "knowledge", 9, (), (), ("M2", "M1")),
        )),
        recipe_audit.Script("xiaomi/M1/M1.toml", "xiaomi", "M1", (
            tl("open", "strategy", 3, ("p.off",), ("p.off",), ("M2", "M1")),
            tl("nav", "vocabulary", 4, ("p.start",), ("p.start",), ("M1",)),
            tl("hook", "hook", 5, (), (), ("M1",)),
        )),
    ))


class CallFactsTests(unittest.TestCase):
    def test_rt_prefix_is_stripped_and_the_definition_line_is_kept(self):
        found = recipe_audit.classify('''def close():\n    rt.require_switches()\n    p.off()\n''')[0]
        self.assertEqual((found.name, found.line), ("close", 1))
        self.assertEqual(found.calls, ("p.off", "require_switches"))
        self.assertEqual(found.tier, "strategy")

    def test_counts_sum_every_function_of_a_tier(self):
        src = '''def one():\n    p.off()\n\ndef two():\n    p.setting()\n'''
        self.assertEqual(recipe_audit.counts(src)["strategy"], 2)


class CountsForTests(unittest.TestCase):
    def write(self, directory, name, text):
        path = Path(directory) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_python_script_is_counted_from_its_source(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "recipe.py", '''def a():\n    p.off()\n\ndef b():\n    p.start()\n''')
            counts = recipe_audit.counts_for(str(path))
        self.assertEqual(counts, {"total": 2, "strategy": 1, "vocabulary": 1,
                                  "knowledge": 0, "hook": 0})

    def test_toml_without_a_companion_has_no_local_functions(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "M1.toml", '[[segment]]\nname = "x"\nops = []\n')
            counts = recipe_audit.counts_for(str(path))
        self.assertEqual(counts, {"total": 0, "strategy": 0, "vocabulary": 0,
                                  "knowledge": 0, "hook": 0})

    def test_toml_without_a_segment_key_has_no_code_functions(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "M1.toml", 'model = "M1"\n')
            self.write(d, "M1.py", "def a():\n    p.off()\n\ndef b():\n    p.start()\n")
            counts = recipe_audit.counts_for(str(path))
        self.assertEqual(counts, {"total": 2, "strategy": 1, "vocabulary": 1,
                                  "knowledge": 0, "hook": 0})

    def test_toml_companion_drops_the_code_functions(self):
        toml = ('[[segment]]\nname = "x"\ncode = "impl"\nops = []\n')
        companion = '''def impl():\n    p.off()\n\ndef helper1():\n    p.start()\n\ndef helper2():\n    p.tap()\n'''
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, "M1.toml", toml)
            self.write(d, "M1.py", companion)
            counts = recipe_audit.counts_for(str(path))
        self.assertEqual(counts, {"total": 2, "strategy": 0, "vocabulary": 2,
                                  "knowledge": 0, "hook": 0})


class PlaceTests(unittest.TestCase):
    def test_family_and_model_come_from_the_two_path_segments(self):
        self.assertEqual(recipe_audit._place("xiaomi/M154FF/M154FF.toml"),
                         ("xiaomi", "M154FF"))

    def test_unregistered_family_is_empty(self):
        self.assertEqual(recipe_audit._place("other/M1/x.toml"), ("", "M1"))

    def test_a_single_segment_path_uses_it_for_both(self):
        self.assertEqual(recipe_audit._place("single.toml"), ("", "single.toml"))

    def test_a_two_segment_path_takes_the_second_as_the_model(self):
        self.assertEqual(recipe_audit._place("xiaomi/M1"), ("xiaomi", "M1"))


class FilteredDetailTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.report = recipe_audit.audit(str(fake_tree(tmp.name)))

    def test_family_filter_skips_the_first_unrelated_script(self):
        kept = recipe_audit.filtered(self.report, family="xiaomi")
        self.assertEqual([script.family for script in kept.scripts], ["xiaomi", "xiaomi"])

    def test_model_matches_the_family_segment_too(self):
        kept = recipe_audit.filtered(self.report, model="xiaomi")
        self.assertEqual([script.model for script in kept.scripts], ["FAKEA", "FAKEB"])

    def test_norm_lowercases_and_drops_punctuation(self):
        self.assertEqual(recipe_audit._norm("A-b C"), "abc")


class CatalogAuditTests(unittest.TestCase):
    def test_code_functions_are_not_local_helpers_and_a_missing_companion_does_not_stop(self):
        with tempfile.TemporaryDirectory() as d:
            recipes = Path(d, "recipes")
            (recipes / "aaa" / "M1").mkdir(parents=True)
            (recipes / "aaa" / "M1" / "M1.toml").write_text(
                '[[segment]]\nname = "x"\ncode = "impl"\nops = []\n', encoding="utf-8")
            (recipes / "aaa" / "M1" / "M1.py").write_text(
                "def impl():\n    p.off()\n\ndef helper():\n    p.start()\n", encoding="utf-8")
            (recipes / "aab" / "M0").mkdir(parents=True)
            (recipes / "aab" / "M0" / "M0.toml").write_text('model = "M0"\n', encoding="utf-8")
            (recipes / "aab" / "M0" / "M0.py").write_text("def lone():\n    p.off()\n", encoding="utf-8")
            (recipes / "aac" / "M9").mkdir(parents=True)
            (recipes / "aac" / "M9" / "M9.toml").write_text('model = "M9"\n', encoding="utf-8")
            (recipes / "xiaomi" / "M2").mkdir(parents=True)
            (recipes / "xiaomi" / "M2" / "recipe.py").write_text(
                "def close():\n    p.setting()\n", encoding="utf-8")
            report = recipe_audit.audit(str(recipes))
        by_script = {script.script: script for script in report.scripts}
        self.assertEqual([f.name for f in by_script["aaa/M1/M1.toml"].functions], ["helper"])
        self.assertEqual([f.name for f in by_script["aab/M0/M0.toml"].functions], ["lone"])
        self.assertEqual(by_script["aac/M9/M9.toml"].functions, ())   # 没有同名例外：0 个本机函数，也不拦住后面的脚本
        self.assertEqual([f.name for f in by_script["xiaomi/M2/recipe.py"].functions], ["close"])


class FamilyTotalsTests(unittest.TestCase):
    def test_each_family_row_has_counts_and_a_label(self):
        with tempfile.TemporaryDirectory() as d:
            rows = recipe_audit._family_totals(recipe_audit.audit(str(fake_tree(d))))
        self.assertEqual(rows, [
            {"family": "vivo", "label": "vivo", "scripts": 1, "total": 0,
             "strategy": 0, "vocabulary": 0, "knowledge": 0, "hook": 0},
            {"family": "xiaomi", "label": "小米", "scripts": 2, "total": 4,
             "strategy": 1, "vocabulary": 2, "knowledge": 1, "hook": 0},
        ])

    def test_unregistered_family_is_labelled_未登记(self):
        with tempfile.TemporaryDirectory() as d:
            recipes = Path(d, "recipes")
            (recipes / "other" / "M1").mkdir(parents=True)
            (recipes / "other" / "M1" / "recipe.py").write_text("def f():\n    p.off()\n", encoding="utf-8")
            rows = recipe_audit._family_totals(recipe_audit.audit(str(recipes)))
        self.assertEqual(rows[0]["family"], "")
        self.assertEqual(rows[0]["label"], "未登记")


class JsonShapeTests(unittest.TestCase):
    def test_json_carries_every_field(self):
        data = recipe_audit.as_json(sample_report())
        self.assertEqual(data, {
            "totals": {"scripts": 2, "total": 4, "strategy": 1, "vocabulary": 1,
                       "knowledge": 1, "hook": 1, "names": 3, "shared": 1},
            "families": [
                {"family": "", "label": "未登记", "scripts": 1, "total": 1,
                 "strategy": 0, "vocabulary": 0, "knowledge": 1, "hook": 0},
                {"family": "xiaomi", "label": "小米", "scripts": 1, "total": 3,
                 "strategy": 1, "vocabulary": 1, "knowledge": 0, "hook": 1},
            ],
            "scripts": [
                {"script": "other/M2/x.toml", "family": "", "model": "M2", "functions": [
                    {"name": "open", "line": 9, "tier": "knowledge", "signals": [],
                     "calls": [], "models": ["M2", "M1"]},
                ]},
                {"script": "xiaomi/M1/M1.toml", "family": "xiaomi", "model": "M1", "functions": [
                    {"name": "open", "line": 3, "tier": "strategy", "signals": ["p.off"],
                     "calls": ["p.off"], "models": ["M2", "M1"]},
                    {"name": "nav", "line": 4, "tier": "vocabulary", "signals": ["p.start"],
                     "calls": ["p.start"], "models": ["M1"]},
                    {"name": "hook", "line": 5, "tier": "hook", "signals": [], "calls": [],
                     "models": ["M1"]},
                ]},
            ],
        })


class EvidenceTests(unittest.TestCase):
    def test_hook_is_named_as_engine_called(self):
        self.assertEqual(recipe_audit._evidence(tl("tail", "hook")),
                         "声明式钩子，由引擎调用")

    def test_knowledge_lists_what_it_called(self):
        self.assertEqual(recipe_audit._evidence(tl("f", "knowledge", calls=("p.shell", "p.focus"))),
                         "没有判据信号，只调了 p.shell、p.focus")

    def test_function_without_calls_says_so(self):
        self.assertEqual(recipe_audit._evidence(tl("f", "knowledge")), "函数体没有调用")


class RenderTextTests(unittest.TestCase):
    EXPECTED = "\n".join([
        "本机函数：4 个（拨动策略 1、引擎词汇 1、真机型知识 1、声明式钩子 1） · 2 份脚本"
        " · 3 个名字，其中 1 个出现在 ≥2 台机型",
        "",
        "## 按家族",
        "",
        "| 家族 | 脚本 | 本机函数 | 拨动策略 | 引擎词汇 | 真机型知识 | 声明式钩子 |",
        "|---|---|---|---|---|",
        "| 未登记 | 1 | 1 | 0 | 0 | 1 | 0 |",
        "| 小米 | 1 | 3 | 1 | 1 | 0 | 1 |",
        "",
        "## 按脚本",
        "",
        "### other/M2/x.toml（未登记 M2）",
        "",
        "本机函数 1 个（拨动策略 0、引擎词汇 0、真机型知识 1、声明式钩子 0）",
        "",
        "- `open`：真机型知识（函数体没有调用） · 机型 2 台 · 行 9",
        "",
        "### xiaomi/M1/M1.toml（小米 M1）",
        "",
        "本机函数 3 个（拨动策略 1、引擎词汇 1、真机型知识 0、声明式钩子 1）",
        "",
        "- `open`：拨动策略（命中 p.off） · 机型 2 台 · 行 3",
        "- `nav`：引擎词汇（命中 p.start） · 机型 1 台 · 行 4",
        "- `hook`：声明式钩子（声明式钩子，由引擎调用） · 机型 1 台 · 行 5",
        "",
    ])

    def test_full_report_is_verbatim(self):
        self.assertEqual(recipe_audit.render(sample_report()), self.EXPECTED)

    def test_summary_is_the_table_only(self):
        text = recipe_audit.render(sample_report(), per_script=False)
        self.assertEqual(text, "\n".join(self.EXPECTED.splitlines()[:8]) + "\n")
        self.assertNotIn("## 按脚本", text)

    def test_filter_line_names_the_three_conditions(self):
        text = recipe_audit.render(sample_report(), family="xiaomi", model="M1", tier="strategy")
        self.assertTrue(text.startswith("过滤：家族 小米、机型 M1、归属 拨动策略\n\n本机函数："))

    def test_empty_report_says_nothing_matched(self):
        text = recipe_audit.render(recipe_audit.Report(()))
        self.assertEqual(text, "\n".join([
            "本机函数：0 个（拨动策略 0、引擎词汇 0、真机型知识 0、声明式钩子 0） · 0 份脚本"
            " · 0 个名字，其中 0 个出现在 ≥2 台机型",
            "", "## 按家族", "",
            "| 家族 | 脚本 | 本机函数 | 拨动策略 | 引擎词汇 | 真机型知识 | 声明式钩子 |",
            "|---|---|---|---|---|",
            "", "## 按脚本", "", "没有匹配的脚本。", "",
        ]))

    def test_family_filter_line_falls_back_to_the_argument(self):
        text = recipe_audit.render(sample_report(), family="nope")
        self.assertTrue(text.startswith("过滤：家族 nope\n\n本机函数："))


class MainTests(unittest.TestCase):
    USAGE = ("用法：python3 tool/recipe_audit.py [--family 家族] [--model 机型] [--tier 归属]"
             " [--summary] [--json]")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.recipes = fake_tree(tmp.name)
        patcher = patch.object(recipe_audit, "_recipes_dir", return_value=str(self.recipes))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = recipe_audit.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_help_prints_the_usage_and_exits_zero(self):
        for argv in (["-h"], ["--help"]):
            with self.subTest(argv):
                self.assertEqual(self.run_cli(argv), (0, self.USAGE + "\n", ""))

    def test_no_arguments_runs_the_whole_audit(self):
        rc, out, _err = self.run_cli([])
        self.assertEqual(rc, 0)
        self.assertIn("## 按脚本", out)

    def test_unknown_option_is_usage_error_two(self):
        self.assertEqual(self.run_cli(["--bogus"]),
                         (2, "", f"不认识的参数 --bogus\n{self.USAGE}\n"))

    def test_option_without_a_value_is_usage_error_two(self):
        self.assertEqual(self.run_cli(["--family"]),
                         (2, "", f"--family 后面要跟一个值\n{self.USAGE}\n"))

    def test_unknown_family_lists_the_available_ones(self):
        rc, _out, err = self.run_cli(["--family", "nope"])
        self.assertEqual(rc, 1)
        self.assertEqual(err, "认不出家族 nope；可用的："
                              + "、".join(sorted(set(recipe_audit.FAMILY.values()))) + "\n")

    def test_unknown_tier_lists_the_available_ones(self):
        rc, _out, err = self.run_cli(["--tier", "nope"])
        self.assertEqual(rc, 1)
        self.assertEqual(err, "认不出归属 nope；可用的：strategy（拨动策略）、vocabulary（引擎词汇）、"
                              "knowledge（真机型知识）、hook（声明式钩子）\n")

    def test_summary_then_json_still_reaches_json(self):
        rc, out, _err = self.run_cli(["--summary", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["totals"]["total"], 4)

    def test_an_option_after_json_is_still_parsed(self):
        rc, _out, err = self.run_cli(["--summary", "--json", "--bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("不认识的参数 --bogus", err)

    def test_filtered_gets_all_three_conditions(self):
        with patch.object(recipe_audit, "filtered", wraps=recipe_audit.filtered) as filtered:
            self.run_cli(["--family", "小米", "--model", "FAKEA", "--tier", "拨动策略"])
        self.assertEqual(filtered.call_args.args[1:], ("xiaomi", "FAKEA", "strategy"))

    def test_json_output_is_indented_and_keeps_chinese_raw(self):
        rc, out, _err = self.run_cli(["--json"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith('{\n  "totals"'))
        self.assertIn("小米", out)

    def test_summary_and_full_render_get_the_same_positional_conditions(self):
        with patch.object(recipe_audit, "render", return_value="") as render:
            self.run_cli([])
            self.assertEqual(render.call_args.kwargs, {})
            self.assertEqual(render.call_args.args[1:], ("", "", ""))
            self.run_cli(["--summary"])
        self.assertIs(render.call_args.kwargs["per_script"], False)
        self.assertEqual(render.call_args.args[1:], ("", "", ""))


class RecipesDirTests(unittest.TestCase):
    def test_the_audit_reads_the_repository_recipes(self):
        self.assertEqual(recipe_audit._recipes_dir(), str(ROOT / "recipes"))


if __name__ == "__main__":
    unittest.main()
