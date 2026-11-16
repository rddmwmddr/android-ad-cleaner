"""模块 → 测试范围的映射（#1411）：一次 mutation 只收集这个模块的锚点测试。

mutmut 3.x 的 runner 绑定 pytest，本仓的 unittest 用例靠 pytest 原生收集，
`pytest_add_cli_args_test_selection` 决定统计阶段收哪些测试。表按「哪个测试文件是这个模块的
owner」手写，不做动态依赖分析：`polarity` 被 `row` 转手带进几乎所有用例，按 import 反推等于
不筛选，而 unittest + 假对象环境下按运行时调用图反推也不可靠。

选择窄是有意的。漏掉的覆盖会在清理该模块时以「存活」露出来，那时把杀死它的测试文件补进
这一行——补一行的成本远低于每次都收集全量。键是相对仓库根的模块路径，值是 pytest 目标。
"""
from collections.abc import Iterable, Sequence

MODULE_TESTS: dict[str, tuple[str, ...]] = {
    "tool/catalog/schema.py": ("tests/test_catalog.py",),
    "tool/polarity.py": ("tests/test_regressions.py",),
    "tool/channel_policy.py": ("tests/test_channel_classification.py",),
    "tool/host.py": ("tests/test_phone_host.py",),
    "tool/events.py": ("tests/test_events.py", "tests/test_engine_events.py"),
    "tool/recipe_meta.py": ("tests/test_recipe_meta_module.py",),
    "tool/recipe_source.py": ("tests/test_recipe_source.py",),
    "tool/recipe_pick.py": ("tests/test_recipe_variants.py",),
    "tool/reader.py": ("tests/test_phone_interface.py",),
    "tool/plan.py": ("tests/test_plan.py",),
    "tool/summary.py": ("tests/test_summary.py",),
    "tool/coverage_note.py": ("tests/test_coverage_note.py",),
    "tool/diagnostics.py": ("tests/test_diagnostics.py",),
}


def tests_for(modules: Sequence[str]) -> list[str]:
    """这些模块要收集的测试目标，按首次出现的顺序去重。"""
    ordered: dict[str, None] = {}
    for module in modules:
        for target in MODULE_TESTS.get(module, ()):
            ordered.setdefault(target, None)
    return list(ordered)


def unknown(modules: Iterable[str]) -> list[str]:
    """不在表里的模块。调用方据此报错，而不是静默跑出 0 个 mutant。"""
    return [module for module in modules if module not in MODULE_TESTS]


def source_path(module: str) -> str:
    """`tool/catalog/schema.py` → `src/catalog/schema.py`。

    mutmut 按相对路径去 `src.` 前缀生成 mutant 名，工作目录里的 `src` 是指向 `tool` 的符号链接；
    测试按顶层模块名 import（`from catalog.schema import …`），两边只在 `src` 这个视角上对齐。
    """
    prefix = "tool/"
    if not module.startswith(prefix):
        raise ValueError(f"mutation 只接 tool/ 下的模块：{module}")
    return "src/" + module[len(prefix):]


def only_mutate(modules: Sequence[str]) -> list[str]:
    """mutmut 的 `only_mutate` 模式，用的是 `src` 视角。"""
    return [source_path(module) for module in modules]
