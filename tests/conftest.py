"""mutation 的进程内缓存清理（#1454）。

mutmut 3.8 的 `PytestRunner` 在同一个解释器里跑统计阶段与全部 mutant 的测试。第一轮扫描留下的
`lru_cache` 在后续 mutant 上仍然命中，被变异的那段代码根本不执行，于是判成 survived。每个
mutant 的 `pytest.main()` 都是一次新会话，所以在会话开头把 `tool/` 里的进程级缓存清掉，缓存
只在本会话内成立。

`_CACHED_ENTRIES` 是 `tool/` 里所有进程级缓存的登记表；新增 `@functools.lru_cache` /
`@functools.cache` 时一并登记，`tests/test_mutation_scope.py` 的守卫盯着两处不漂。
"""
import importlib

# 同一个解释器里跑完统计与全部 mutant：不清掉，后一个 mutant 会读到前一个留下的扫描结果。
_CACHED_ENTRIES = (
    "recipe_source._scan_cached",
    "recipe_source.library_sources",
)


def pytest_sessionstart(session):
    # `src` 不在 `sys.path` 上的跑法（手工单跑、别的宿主）不归这里管，不要因此把 conftest 弄崩。
    for entry in _CACHED_ENTRIES:
        module_name, _, attribute = entry.rpartition(".")
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        getattr(module, attribute).cache_clear()
