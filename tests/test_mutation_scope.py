"""模块 → 测试范围的映射（#1411）：每一行都点到存在的测试，严格档名单与它不漂。

判据只看外部行为：映射表覆盖哪些模块、目标文件在不在、选择结果怎么去重，以及 `tool/` 里的
进程级缓存有没有进 `tests/conftest.py` 的清理表（#1454）。不跑 mutation 本身——那要几十秒，
且由 devtools/mutation.py 负责。
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

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


def _cache_names(tree):
    """这个模块里哪些名字指向 `functools.cache` / `functools.lru_cache`（模块别名与直接 import 都算）。"""
    modules = {"functools"}
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "functools":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "functools":
            for alias in node.names:
                if alias.name in ("cache", "lru_cache"):
                    names.add(alias.asname or alias.name)
    return modules, names


def _is_cache_decorator(item, modules, names):
    target = item.func if isinstance(item, ast.Call) else item
    if isinstance(target, ast.Name):
        return target.id in names
    return (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
            and target.value.id in modules and target.attr in ("cache", "lru_cache"))


def cached_functions(root):
    """`tool/` 下模块级、被 `functools.cache` / `functools.lru_cache` 装饰的函数，点名成 `模块.函数`。

    只看模块级：函数体内新建的缓存跟着那次调用走，不会跨 pytest 会话留下来。
    """
    found = set()
    for path in sorted((root / "tool").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules, names = _cache_names(tree)
        module = ".".join(path.relative_to(root / "tool").with_suffix("").parts)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                _is_cache_decorator(item, modules, names) for item in node.decorator_list
            ):
                found.add(f"{module}.{node.name}")
    return found


def registered_cache_entries(root):
    """`tests/conftest.py` 的 `_CACHED_ENTRIES` 里登记的那些点名。"""
    tree = ast.parse((root / "tests" / "conftest.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "_CACHED_ENTRIES"):
            return set(ast.literal_eval(node.value))
    raise AssertionError("tests/conftest.py 里找不到 _CACHED_ENTRIES")


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

    def test_source_path_keeps_gui_under_its_package(self):
        """`gui/` 的模块在副本里按包名 import（`from gui import tasks`），所以落在 `src/gui/` 下。"""
        self.assertEqual(mutation_scope.source_path("gui/tasks.py"), "src/gui/tasks.py")

    def test_source_path_keeps_the_android_layer_under_aac_android(self):
        """手机版替换层按包名 import（`from aac_android import view`），落在 `src/aac_android/` 下。"""
        self.assertEqual(
            mutation_scope.source_path("android/app/src/main/python/aac_android/view.py"),
            "src/aac_android/view.py")

    def test_only_mutate_uses_the_android_src_view(self):
        module = "android/app/src/main/python/aac_android/view.py"
        self.assertEqual(mutation_scope.only_mutate([module]), ["src/aac_android/view.py"])

    def test_source_path_rejects_modules_outside_the_source_view(self):
        with self.assertRaises(ValueError):
            mutation_scope.source_path("devtools/mutation.py")


class WorkdirTests(unittest.TestCase):
    def test_workdir_for_keeps_the_gui_prefix_in_the_slug(self):
        """`gui/tasks.py` 与 `tool/tasks.py` 若同日出现，别共用一个工作目录。"""
        self.assertEqual(mutation.workdir_for(["gui/tasks.py"]).name, "gui_tasks")
        self.assertEqual(mutation.workdir_for(["tool/summary.py"]).name, "summary")

    def test_workdir_for_keeps_the_aac_prefix_in_the_slug(self):
        """手机版 `view.py` 与 `tool/` 里的同名模块别共用一个工作目录。"""
        self.assertEqual(
            mutation.workdir_for(["android/app/src/main/python/aac_android/view.py"]).name,
            "aac_view")


@unittest.skipIf(os.name == "nt", "建符号链接要开发者模式；变异 job 只在 Linux 上跑")
class SourceMirrorTests(unittest.TestCase):
    """副本里的 `src` 是镜像：目录真建、文件逐条链接，两个包都 import 得到。

    mutmut 的 `os.walk` 不跟随目录符号链接，所以不能只放一条 `src -> tool`；`gui/` 的模块要
    落在 `src/gui/` 下，测试才能按 `from gui import tasks` 取到被变异的文件。
    """

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.workdir = root / ".mutmut" / "sample"
        mutation.link_sources(self.workdir)
        self.src = self.workdir / "src"

    def test_src_is_a_real_directory(self):
        self.assertFalse(self.src.is_symlink())
        self.assertTrue(self.src.is_dir())

    def test_every_tool_entry_is_mirrored_at_the_src_root(self):
        missing = [name for name in (ROOT / "tool").iterdir()
                   if name.name != "__pycache__" and not (self.src / name.name).exists()]
        self.assertEqual(missing, [])

    def test_every_gui_entry_is_mirrored_under_the_gui_package(self):
        missing = [name for name in (ROOT / "gui").iterdir()
                   if name.name != "__pycache__" and not (self.src / "gui" / name.name).exists()]
        self.assertEqual(missing, [])

    def test_every_android_entry_is_mirrored_under_the_aac_android_package(self):
        """手机版替换层在 `android/app/src/main/python/` 下，也要进 `src/aac_android/`（#1430）。"""
        real = ROOT / "android" / "app" / "src" / "main" / "python" / "aac_android"
        missing = [name for name in real.iterdir()
                   if name.name != "__pycache__" and not (self.src / "aac_android" / name.name).exists()]
        self.assertEqual(missing, [])

    def test_the_mirror_skips_bytecode_cache(self):
        self.assertEqual(sorted(self.src.rglob("__pycache__")), [])

    def test_files_are_linked_not_copied(self):
        """链接让源码只有一份：改了仓库里的模块，副本立刻跟上。"""
        self.assertTrue((self.src / "gui" / "tasks.py").is_symlink())
        self.assertEqual((self.src / "catalog" / "schema.py").resolve(),
                         (ROOT / "tool" / "catalog" / "schema.py").resolve())

    def test_the_android_files_are_linked_to_the_real_source(self):
        """手机版的镜像也指回 `android/app/src/main/python/` 里的真源码。"""
        real = ROOT / "android" / "app" / "src" / "main" / "python" / "aac_android" / "view.py"
        self.assertTrue((self.src / "aac_android" / "view.py").is_symlink())
        self.assertEqual((self.src / "aac_android" / "view.py").resolve(), real.resolve())

    def test_relinking_replaces_a_stale_src_link(self):
        """旧的 `src -> tool` 形态要能被下一次运行换掉，不然副本里没有 `gui`。"""
        stale = self.workdir / "src"
        shutil.rmtree(stale)
        stale.symlink_to(Path("..") / ".." / "tool")
        mutation.link_sources(self.workdir)
        self.assertFalse(self.src.is_symlink())
        self.assertTrue((self.src / "gui" / "tasks.py").exists())


class PatchScopeTests(unittest.TestCase):
    def test_modules_in_paths_keeps_only_mapped_modules(self):
        self.assertEqual(mutation_scope.modules_in_paths(["tool/summary.py", "tool/row.py"]),
                         ["tool/summary.py"])

    def test_modules_in_paths_dedupes_and_keeps_order(self):
        paths = ["tool/plan.py", "tool/plan.py", "tool/summary.py"]
        self.assertEqual(mutation_scope.modules_in_paths(paths), ["tool/plan.py", "tool/summary.py"])

    def test_modules_in_paths_reads_gui_modules(self):
        self.assertEqual(mutation_scope.modules_in_paths(["gui/tasks.py", "gui/app.py"]),
                         ["gui/tasks.py"])

    def test_modules_in_paths_reads_the_android_layer(self):
        module = "android/app/src/main/python/aac_android/view.py"
        self.assertEqual(mutation_scope.modules_in_paths([module]), [module])

    def test_modules_in_paths_ignores_paths_outside_tool(self):
        self.assertEqual(mutation_scope.modules_in_paths(["recipes/a/b/c.toml", "tests/test_plan.py"]),
                         [])


class ScopeReportTests(unittest.TestCase):
    """改到 `gui/` 但落在表外时报出来：缺席要看得见，不是遗忘的（#1429）。"""

    def scope(self, paths):
        with mock.patch.object(mutation, "changed_paths", return_value=paths):
            return mutation.scope_of("origin/main")

    def test_unmapped_gui_modules_are_reported(self):
        modules, unmapped = self.scope(["gui/app.py", "gui/web/app.js", "tests/test_plan.py"])
        self.assertEqual(modules, [])
        self.assertEqual(unmapped, ["gui/app.py"])

    def test_mapped_gui_modules_are_not_reported_as_skipped(self):
        modules, unmapped = self.scope(["gui/tasks.py"])
        self.assertEqual(modules, ["gui/tasks.py"])
        self.assertEqual(unmapped, [])

    def test_unmapped_android_modules_are_reported(self):
        """手机版替换层落表前的模块逐条报「本次不判」，缺席要看得见（#1430）。"""
        module = "android/app/src/main/python/aac_android/main.py"
        modules, unmapped = self.scope([module, "tests/test_android_view.py"])
        self.assertEqual(modules, [])
        self.assertEqual(unmapped, [module])

    def test_mapped_android_modules_are_not_reported_as_skipped(self):
        module = "android/app/src/main/python/aac_android/view.py"
        modules, unmapped = self.scope([module])
        self.assertEqual(modules, [module])
        self.assertEqual(unmapped, [])


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


class CacheClearRegistryTests(unittest.TestCase):
    """`tool/` 里的进程级缓存都要进 `tests/conftest.py` 的清理表（#1454）。

    mutmut 拿同一个解释器跑完全部 mutant，不清掉的缓存会让被变异的那段代码不执行，假存活。
    """

    def test_every_cached_function_is_registered(self):
        missing = sorted(cached_functions(ROOT) - registered_cache_entries(ROOT))
        self.assertEqual(missing, [])

    def test_every_registered_entry_names_a_cached_function(self):
        """登记表里的点名要还指着真缓存：删掉缓存时忘了摘，清理表就成了空转。"""
        stale = sorted(registered_cache_entries(ROOT) - cached_functions(ROOT))
        self.assertEqual(stale, [])

    def test_the_scanner_sees_every_spelling(self):
        """守卫自己不能瞎：`functools.lru_cache(maxsize=None)`、模块别名与 `from functools import` 都要认。"""
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "tool").mkdir()
        (root / "tool" / "sample.py").write_text(
            "import functools as ft\n"
            "from functools import cache\n"
            "from functools import lru_cache as memo\n"
            "\n"
            "@functools.lru_cache(maxsize=None)\n"
            "def a():\n"
            "    return 1\n"
            "\n"
            "@ft.cache\n"
            "def b():\n"
            "    return 2\n"
            "\n"
            "@cache\n"
            "def c():\n"
            "    return 3\n"
            "\n"
            "@memo(maxsize=2)\n"
            "def d():\n"
            "    return 4\n"
            "\n"
            "def nested():\n"
            "    @functools.cache\n"
            "    def e():\n"
            "        return 5\n"
            "    return e\n"
            "\n"
            "def plain():\n"
            "    return 6\n",
            encoding="utf-8")
        self.assertEqual(cached_functions(root), {"sample.a", "sample.b", "sample.c", "sample.d"})


if __name__ == "__main__":
    unittest.main()
