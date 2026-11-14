"""本机函数审计（tool/recipe_audit.py，#1240）：按脚本列本机模块级函数、判它归哪一档，并给出
「本机策略：N 个」。

三档归属只看函数体自己调了哪些名字（直接调用）：拨动策略 > 引擎词汇 > 真机型知识。用例分四层：

1. 判据本身：`definitions()` 只收模块级、`@step` 段体不算；`tier_of()` 的优先级与命中的信号。
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

# 三档各一个本机函数，外加两个 `@step` 段体：一个叫 `_`（现在的写法），一个叫别的名字
# （vivo-V2417A 就是这样），两者都只有装饰器能认出来。
RECIPE = '''"""假机型脚本：只给审计用例用。"""
BUILD = "OS9.9"
MODELS = ["FAKEA"]

@step("系统广告")
def _():
    p.off(only=["广告"])

@step("浏览器")
def browser():
    p.start("com.example.browser")

def open_settings():
    """引擎词汇：导航与落点。"""
    p.tap(p.find("设置"))

def close_exact():
    """拨动策略：这一页的开关怎么关。"""
    for row in p.switches():
        p.off(only=[row.get("text")])

def build_id():
    """真机型知识：只有这一台才要的版本守卫。"""
    return p.d.shell("getprop ro.build.display.id")
'''

OTHERS = '''"""假机型脚本：与 FAKEA 定义同名的 open_settings，用来验「涉及机型数」。"""
@step("系统广告")
def _():
    p.off()

def open_settings():
    p.tap(p.find("设置"))
'''

EMPTY = '''"""假机型脚本：只有段体，没有本机函数。"""
@step("系统广告")
def _():
    p.off()
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
    def test_step_bodies_are_not_local_functions(self):
        """段体是脚本的段落，不是一份实现：`@step` 挂了段名的都不算，叫 `_` 与否都一样。"""
        names = [name for name, _line in recipe_audit.definitions(RECIPE)]
        self.assertEqual(names, ["open_settings", "close_exact", "build_id"])

    def test_line_is_the_definition_line(self):
        lines = dict(recipe_audit.definitions(RECIPE))
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
        self.assertEqual(recipe_audit.tier_of(["p.d.shell", "RuntimeError"]),
                         (recipe_audit.KNOWLEDGE, ()))
        self.assertEqual(recipe_audit.tier_of([]), (recipe_audit.KNOWLEDGE, ()))

    def test_the_declarative_hooks_are_their_own_tier(self):
        """`tail` / `guard` / `wrap` / `detail` 按名字判成钩子，不看函数体调了什么（#1244）。

        不收的话十几个 `tail()` 会混进真机型知识，本机策略数也被收尾打印淹没。"""
        source = ('def tail():\n    print(rt.verified)\n'
                  'def guard():\n    require(p.d.shell("getprop x") == "1", "型号不符")\n'
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
        self.assertIn("- `build_id`：真机型知识（没有判据信号，只调了 p.d.shell）", out)

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


if __name__ == "__main__":
    unittest.main()
