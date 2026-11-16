"""模块 → 测试范围的映射（#1411）：每一行都点到存在的测试，严格档名单与它不漂。

判据只看外部行为：映射表覆盖哪些模块、目标文件在不在、选择结果怎么去重。不跑 mutation
本身——那要几十秒，且由 devtools/mutation.py 负责。
"""
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))

from devtools import mutation_scope  # noqa: E402


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


class SelectionTests(unittest.TestCase):
    def test_tests_for_dedupes_repeated_modules(self):
        targets = mutation_scope.tests_for(["tool/events.py", "tool/events.py"])
        self.assertEqual(targets, ["tests/test_events.py", "tests/test_engine_events.py"])

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


if __name__ == "__main__":
    unittest.main()
