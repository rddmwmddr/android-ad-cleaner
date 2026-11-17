"""模块 → 测试范围的映射（#1411）：每一行都点到存在的测试，严格档名单与它不漂。

判据只看外部行为：映射表覆盖哪些模块、目标文件在不在、选择结果怎么去重。不跑 mutation
本身——那要几十秒，且由 devtools/mutation.py 负责。
"""
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from devtools import mutation, mutation_scope  # noqa: E402


def strict_modules():
    """pyproject 里那十二条严格档模块的名字（不含 `tool/` 前缀）。"""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for override in data["tool"]["mypy"]["overrides"]:
        names = override.get("module", [])
        if "polarity" in names:
            return list(names)
    raise AssertionError("pyproject.toml 里找不到严格档名单")


class MapTests(unittest.TestCase):
    def test_every_strict_module_is_mapped(self):
        missing = [f"tool/{m}.py" for m in strict_modules()
                   if f"tool/{m}.py" not in mutation_scope.MODULE_TESTS]
        self.assertEqual(missing, [])

    def test_the_catalog_schema_is_mapped(self):
        self.assertIn("tool/catalog/schema.py", mutation_scope.MODULE_TESTS)

    def test_every_target_exists(self):
        for module, targets in mutation_scope.MODULE_TESTS.items():
            for target in targets:
                with self.subTest(module=module, target=target):
                    self.assertTrue((ROOT / target).is_file(), f"{target} 不在仓库里")

    def test_every_module_has_at_least_one_target(self):
        empty = [m for m, targets in mutation_scope.MODULE_TESTS.items() if not targets]
        self.assertEqual(empty, [])

    def test_every_deselected_file_is_used_by_some_row(self):
        """`UNUSABLE` 里留着一份没人收集的文件，等于悄悄少跑一个测试。"""
        selected = {target for targets in mutation_scope.MODULE_TESTS.values() for target in targets}
        self.assertEqual(sorted(set(mutation_scope.UNUSABLE) - selected), [])

    def test_every_deselect_node_id_names_a_real_file(self):
        for path, node_ids in mutation_scope.UNUSABLE.items():
            for node_id in node_ids:
                with self.subTest(node_id=node_id):
                    self.assertTrue(node_id.startswith(path + "::"), node_id)
                    self.assertTrue((ROOT / path).is_file(), f"{path} 不在仓库里")


class SelectionTests(unittest.TestCase):
    def test_tests_for_dedupes_repeated_modules(self):
        once = mutation_scope.tests_for(["tool/events.py"])
        twice = mutation_scope.tests_for(["tool/events.py", "tool/events.py"])
        self.assertEqual(twice, once)
        files = [arg for arg in once if arg.startswith("tests/")]
        self.assertEqual(len(files), len(set(files)))

    def test_tests_for_drops_the_classes_that_cannot_run_in_the_copy(self):
        args = mutation_scope.tests_for(["tool/recipe_source.py"])
        self.assertIn("--deselect", args)
        self.assertIn("tests/test_vocab.py::SourceShapeTest", args)
        self.assertLess(args.index("tests/test_vocab.py"), args.index("--deselect"))

    def test_tests_for_keeps_first_seen_order(self):
        targets = mutation_scope.tests_for(["tool/summary.py", "tool/events.py"])
        self.assertEqual(targets[0], "tests/test_summary.py")

    def test_unknown_names_the_modules_without_a_row(self):
        self.assertEqual(mutation_scope.unknown(["tool/summary.py", "tool/nope.py"]), ["tool/nope.py"])

    def test_only_mutate_uses_the_src_view(self):
        self.assertEqual(mutation_scope.only_mutate(["tool/catalog/schema.py"]), ["src/catalog/schema.py"])

    def test_source_path_rejects_modules_outside_tool(self):
        with self.assertRaises(ValueError):
            mutation_scope.source_path("gui/app.py")


class PatchScopeTests(unittest.TestCase):
    def test_modules_in_paths_keeps_only_mapped_modules(self):
        self.assertEqual(mutation_scope.modules_in_paths(["tool/summary.py", "tool/row.py"]),
                         ["tool/summary.py"])

    def test_modules_in_paths_dedupes_and_keeps_order(self):
        paths = ["tool/plan.py", "tool/plan.py", "tool/summary.py"]
        self.assertEqual(mutation_scope.modules_in_paths(paths), ["tool/plan.py", "tool/summary.py"])

    def test_modules_in_paths_ignores_paths_outside_tool(self):
        self.assertEqual(mutation_scope.modules_in_paths(["recipes/a/b/c.toml", "tests/test_plan.py"]),
                         [])


class SummaryTests(unittest.TestCase):
    def test_section_reports_the_pragma_count(self):
        text = mutation.section(
            {"total": 10, "killed": 9, "survived": 0, "skipped": 0, "timeout": 0, "no_tests": 0},
            ["tool/summary.py"],
            1,
        )
        self.assertIn("pragma 豁免 1", text)
        self.assertIn("全绿", text)

    def test_section_calls_out_survivors(self):
        text = mutation.section(
            {"total": 3, "killed": 2, "survived": 1, "skipped": 0, "timeout": 0, "no_tests": 0},
            ["tool/plan.py"],
        )
        self.assertIn("有存活", text)

    def test_section_does_not_call_untested_mutants_survivors(self):
        """只有「无测试」时不能说「有存活」：那是测试选择不够，不是断言不够。"""
        text = mutation.section(
            {"total": 3, "killed": 3, "survived": 0, "skipped": 0, "timeout": 0, "no_tests": 2},
            ["tool/reader.py"],
        )
        self.assertIn("有 mutant 没有测试覆盖到", text)
        self.assertNotIn("有存活", text)

    def test_pragmas_counts_the_marker_in_the_module_source(self):
        self.assertEqual(mutation.pragmas(["tool/coverage_note.py"]), 1)


class NothingToMutateTests(unittest.TestCase):
    """`reader.py` 这种 `Protocol`：mutmut 退出 1，但没有 mutant 可判，不是失败。"""

    def workdir(self, payload):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        meta = root / "mutants" / "src" / "reader.py.meta"
        meta.parent.mkdir(parents=True)
        if payload is not None:
            meta.write_text(json.dumps(payload), encoding="utf-8")
        return root

    def test_an_empty_hash_table_is_a_conclusion(self):
        self.assertTrue(mutation.nothing_to_mutate(self.workdir({"hash_by_function_name": {}}),
                                                  ["tool/reader.py"]))

    def test_a_module_with_functions_still_fails(self):
        self.assertFalse(mutation.nothing_to_mutate(
            self.workdir({"hash_by_function_name": {"src.reader.x": "abc"}}), ["tool/reader.py"]))

    def test_missing_cache_is_not_a_conclusion(self):
        """没有 meta 说明这轮根本没跑到那一步，不能当成「没东西可判」。"""
        self.assertFalse(mutation.nothing_to_mutate(self.workdir(None), ["tool/reader.py"]))


if __name__ == "__main__":
    unittest.main()
