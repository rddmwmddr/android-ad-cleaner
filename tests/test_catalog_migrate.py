"""迁移转换器（#1260）：段体的三列分类（converted / missing-key / unrepresentable）、覆盖率口径，
以及转换产物能过 catalog 校验器。转换器是临时工具（删除条件见 ADR-0038），但迁移期受这组用例保护。

判据只看分类与产物是否合法，不看转换器内部实现；真实仓库的覆盖率另有一条集成用例兜底（≥80% 采纳线）。
"""
import ast
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

import catalog_migrate as migrate  # noqa: E402
from catalog import schema  # noqa: E402

SOURCE = '''
from recipe_kit import step

@step("简单")
def _():
    p.start("com.x")
    p.off(only=["A", "B"], page="p")
    p.back(2)

@step("循环")
def _():
    for x in ("a", "b"):
        p.tap(x)
    p.back()

def probe():
    check_audio()


@step("知识")
def _():
    probe()
'''


def _status(reports, name):
    for report in reports:
        if report.name == name:
            return report
    raise AssertionError(f"没有段 {name}")


class ClassificationTests(unittest.TestCase):
    """三列：能落到现有 op 的 converted、要补一条通用语义的 missing-key、只能 code= 的 unrepresentable。"""

    def setUp(self):
        self.reports = migrate.convert(SOURCE)

    def test_simple_segment_is_converted_with_ops(self):
        report = _status(self.reports, "简单")
        self.assertEqual(report.status, migrate.CONVERTED)
        kinds = [op["kind"] for op in report.ops]
        self.assertEqual(kinds, ["start", "off", "back"])
        self.assertEqual(report.ops[1]["only"], ["A", "B"])
        self.assertEqual(report.ops[2]["n"], 2)

    def test_loop_segment_needs_a_runtime_op(self):
        report = _status(self.reports, "循环")
        self.assertEqual(report.status, migrate.MISSING_KEY)
        self.assertIn("for_each", report.reason)

    def test_segment_calling_model_knowledge_is_unrepresentable(self):
        """`probe()` 既不导航也不拨开关——归 `knowledge` 档，任何通用语义都表达不了。"""
        report = _status(self.reports, "知识")
        self.assertEqual(report.status, migrate.UNREPRESENTABLE)
        self.assertIn("probe", report.reason)


class ProductionTests(unittest.TestCase):
    """转换产物能过 catalog 校验器：converted 段渲染出的 TOML 是合法数据。"""

    def test_rendered_toml_validates(self):
        reports = [r for r in migrate.convert(SOURCE) if r.status == migrate.CONVERTED]
        toml = migrate.render_toml(reports, model="X")
        schema.validate(tomllib.loads(toml))   # 不抛即合法


class MeasureTests(unittest.TestCase):
    """覆盖率 = (converted + missing-key) / 段体总数；unrepresentable 是残余。"""

    def test_coverage_math(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "xiaomi" / "X"
            model.mkdir(parents=True)
            (model / "recipe.py").write_text(SOURCE, encoding="utf-8")
            result = migrate.measure(tmp)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["converted"], 1)
        self.assertEqual(result["missing_key"], 1)
        self.assertEqual(result["unrepresentable"], 1)
        self.assertAlmostEqual(result["coverage"], 2 / 3)

    def test_real_repo_clears_the_adoption_bar(self):
        """真实仓库的覆盖率应 ≥80%（#1260 的采纳判定）。跌破说明脚本形态或分类口径变了，要回 grilling。

        分母不能是空集：每个含 `.py` 的家族目录分别量一遍，各自 `total > 0`（#1263）。
        """
        result = migrate.measure(str(ROOT / "recipes"))
        self.assertEqual(families_without_measured_segments(result, ROOT / "recipes"), set(),
                         "有家族还带 @step 脚本、却一段体都没进测量：分母是空集，覆盖率在空转")
        self.assertGreaterEqual(result["coverage"], 0.80,
                                f"覆盖率跌破 80%：{result['coverage']:.1%}，选择停工回 grilling")

    def test_family_measure_predicate_catches_a_hidden_step_script(self):
        """反例：家族里有 `@step` 脚本，但文件名不匹配 `recipe*.py` 导致漏扫，该家族 total 为 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "demo" / "M"
            model.mkdir(parents=True)
            (model / "foo.py").write_text(
                "from recipe_kit import step\n\n@step('x')\ndef _():\n    p.back()\n", encoding="utf-8")
            result = migrate.measure(tmp)
            self.assertEqual(families_without_measured_segments(result, tmp), {"demo"})


def families_without_measured_segments(result, recipes_dir):
    """还带 `@step` 脚本、却在这份 measure 结果里一段体都没量的家族集合（#1263 的发现口径判据）。"""
    per_family = {}
    for rel, row in result["scripts"].items():
        family = rel.split("/")[0]
        per_family[family] = per_family.get(family, 0) + row["total"]
    return {family for family in families_with_step_scripts(recipes_dir) if per_family.get(family, 0) == 0}


def families_with_step_scripts(recipes_dir):
    """`recipes/` 下「还有 `@step` 段体脚本」的家族集合（发现口径独立于 migrate 自己的 glob）。

    例外 `.py`（只有普通函数、无 `@step`）的家族量出 0 段体是正常的，不算分母空集；只有还留着
    `@step` 脚本的家族，`total` 才必须 > 0（#1263）。"""
    out = set()
    for py in Path(recipes_dir).rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and any(
                    isinstance(d, ast.Call) and getattr(d.func, "id", None) == "step"
                    for d in node.decorator_list):
                out.add(py.relative_to(recipes_dir).parts[0])
                break
    return out


if __name__ == "__main__":
    unittest.main()
