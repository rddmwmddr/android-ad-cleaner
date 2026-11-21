"""mutation 的进程内状态清理（#1454、#1516）。

mutmut 3.8 的 `PytestRunner` 在同一个解释器里跑统计阶段与全部 mutant 的测试。第一轮扫描留下的
`lru_cache` 在后续 mutant 上仍然命中，被变异的那段代码根本不执行，于是判成 survived。每个
mutant 的 `pytest.main()` 都是一次新会话，所以在会话开头把 `tool/` 里的进程级缓存清掉，缓存
只在本会话内成立。

`_CACHED_ENTRIES` 是 `tool/` 里所有进程级缓存的登记表；新增 `@functools.lru_cache` /
`@functools.cache` 时一并登记，`tests/test_mutation_scope.py` 的守卫盯着两处不漂。

同理，devtools 模块在 import 期 `sys.path.insert`、随即 `use_utf8_console()` 改写标准流，且都不
还原。mutmut 在父进程里跑统计阶段、之后每个 mutant 从父进程 fork，残留的全局状态会漏进每一个
mutant 子进程，让后续 mutant 在错的环境里被判定（#1516）。`_DEVTOOLS_IMPORTING_FILES` 是导入
devtools 的测试文件登记表，这些文件的用例在**每条用例**的边界上快照 / 回填 `sys.path`、
`sys.modules` 与标准流对象；名单漂移同样由 `test_mutation_scope.py` 的守卫双向对拍。
"""
import importlib
import sys
from pathlib import Path

# 同一个解释器里跑完统计与全部 mutant：不清掉，后一个 mutant 会读到前一个留下的扫描结果。
_CACHED_ENTRIES = (
    "recipe_source._scan_cached",
    "recipe_source.library_sources",
)

# 导入 devtools 的测试文件（相对 `tests/` 的文件名）。这些文件的用例会触发或再触发 devtools 的
# import 期改写，按用例快照 / 回填全局状态。名单与 `import devtools` 的实际集合由守卫双向对拍。
_DEVTOOLS_IMPORTING_FILES = {
    "test_catalog.py",
    "test_claim.py",
    "test_comment_tickets.py",
    "test_conventional.py",
    "test_dco.py",
    "test_doc_consistency.py",
    "test_followup.py",
    "test_gh.py",
    "test_glob_scan.py",
    "test_mutation_scope.py",
    "test_phone_facade.py",
    "test_release_assets.py",
    "test_release_meta.py",
    "test_rules_guards.py",
    "test_stale_scan.py",
    "test_test_collection.py",
    "test_ticket_ref.py",
    "test_triage_audit.py",
    "test_unittest_summary.py",
}

_TESTS_DIR = Path(__file__).resolve().parent
_DEVTOOLS_SCOPE = frozenset(_TESTS_DIR / name for name in _DEVTOOLS_IMPORTING_FILES)


def _snapshot_globals():
    """记下用例开始前的 `sys.path`、`sys.modules` 与标准流对象，供 `_restore_globals` 回填。"""
    return list(sys.path), dict(sys.modules), sys.stdout, sys.stderr


def _restore_globals(saved):
    """把 `_snapshot_globals` 的快照回填进解释器。

    import 期的 `reconfigure` 是原地改编码，没法也不该在测试里反向调用（`StdioGuards` 禁止别处
    出现那种写法）；这里只负责流对象被换掉的情况，编码若被 import 期改过就留在改过的样子。
    """
    path, modules, stdout, stderr = saved
    sys.path[:] = path
    sys.modules.clear()
    sys.modules.update(modules)
    sys.stdout, sys.stderr = stdout, stderr


def pytest_sessionstart(session):
    # `src` 不在 `sys.path` 上的跑法（手工单跑、别的宿主）不归这里管，不要因此把 conftest 弄崩。
    for entry in _CACHED_ENTRIES:
        module_name, _, attribute = entry.rpartition(".")
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        getattr(module, attribute).cache_clear()


def pytest_runtest_setup(item):
    # 只给导入 devtools 的文件付快照成本；`Path(item.path)` 是 pytest 7+ 的现代 API。
    if Path(str(item.path)).resolve() in _DEVTOOLS_SCOPE:
        item._devtools_globals = _snapshot_globals()


def pytest_runtest_teardown(item, nextitem):
    saved = getattr(item, "_devtools_globals", None)
    if saved is not None:
        del item._devtools_globals
        _restore_globals(saved)
