"""模块 → 测试范围的映射（#1411、#1452）：一次 mutation 只收集这个模块的测试。

mutmut 3.x 的 runner 绑定 pytest，本仓的 unittest 用例靠 pytest 原生收集，
`pytest_add_cli_args_test_selection` 决定统计阶段收哪些测试。键是相对仓库根的模块路径，
值是 pytest 目标。

每一行是**量出来的**，不是按 import 反推的：`polarity` 被 `row` 转手带进几乎所有用例，按
import 反推等于不筛选。取法是让整个套件在 coverage 的 `dynamic_context = test_function` 下跑
一遍，记下每个测试文件执行过该模块多少行，执行过的都进这一行（`reader` 除外，见下）。窄行会让
mutmut 把「没被选中的测试能杀死的 mutant」报成存活 / 无测试——那是尺子的问题，不是断言的问题。

`reader` 的行是唯一没有矩阵依据的：`Reader` 是 Protocol，方法体只有 `...`，模块的行只在 import
时执行，没有任何测试在执行期碰到它。留一个目标是为了让 mutmut 有得收集（空选择会让它退回全量
套件）；它的 `no_tests` 是预期结论，由 #1423 判断，别硬补测试。

`UNUSABLE` 列的是**在变异副本里跑不通**的测试：副本只有 `src/` 没有 `tool/`，所以起子进程
`python tool/run.py`、`python -c "import host"`、读 `android/` 源码、整仓扫文本的用例都会红。
红掉的用例会把碰过同一个函数的 mutant 误判成「杀死」，所以整份文件都跑不通的干脆不进表；
个别跑不通的按**方法** `--deselect` 摘掉，整类都受影响的按类摘——粒度尽量到方法而不是到类或
文件，是因为这些文件里剩下的用例往往是该模块最大的覆盖来源（`test_vocab` 一个文件就覆盖
`recipe_source` 一半以上；`PackagingEntryTests` 里只有起子进程那 3 条会红，按类摘会连带扔掉
同类的布局断言）。
"""
from collections.abc import Iterable, Sequence

MODULE_TESTS: dict[str, tuple[str, ...]] = {
    "tool/catalog/schema.py": (
        "tests/test_catalog.py", "tests/test_entries.py", "tests/test_honor_cle_an00.py",
        "tests/test_rmx3888_recipe.py", "tests/test_honor_recipe.py",
        "tests/test_xiaomi_24129pn74c_recipe.py", "tests/test_xiaomi_store_recipe.py",
        "tests/test_oppo_plp120_coloros17.py", "tests/test_xiaomi_ads_recipe.py",
        "tests/test_honor_wkl_recipe.py", "tests/test_recipe_setting_checked.py",
        "tests/test_oppo_pkt110_recipe.py", "tests/test_vivo_v2547a_recipe.py",
        "tests/test_xiaomi_2505apx7bc_recipe.py", "tests/test_oppo_plp120_search.py",
        "tests/test_vivo_2547da_android17_recipe.py", "tests/test_pja110_android16_recipe.py",
        "tests/test_phone_navigator.py", "tests/test_phk110_recipe.py", "tests/test_meizu_recipe.py",
        "tests/test_rmx3700_recipe.py", "tests/test_vivo_v2303a_recipe.py",
        "tests/test_vivo_v2309a_recipe.py", "tests/test_vivo_v2417a_recipe.py",
        "tests/test_oneplus_recipe.py", "tests/test_k70_recipe.py", "tests/test_k80pro_recipe.py",
        "tests/test_oppo_plp120_browser.py", "tests/test_adapt_cli.py",
        "tests/test_oneplus_plz110_recipe.py", "tests/test_phone_dismisser.py",
        "tests/test_oppo_pyb110_recipe.py", "tests/test_xiaomi_theme_recipe.py",
        "tests/test_redmi_24094rad4c_recipe.py", "tests/test_k90ultra_recipe.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_phone_settings_search.py",
        "tests/test_release_regressions.py", "tests/test_vivo_v2545a_recipe.py",
        "tests/test_phone_interface.py", "tests/test_vivo_2417_browser_entry.py",
        "tests/test_regressions.py", "tests/test_vivo_v1986a_recipe.py",
        "tests/test_recipe_call_snapshots.py", "tests/test_recipe_loader.py",
        "tests/test_oppo_pma110_recipe.py", "tests/test_phk110_android15_recipe.py",
        "tests/test_family.py", "tests/test_recipe_nav.py",
    ),
    "tool/polarity.py": (
        "tests/test_regressions.py", "tests/test_vocab.py", "tests/test_phone_interface.py",
        "tests/test_switch_plan.py", "tests/test_adapt_cli.py", "tests/test_off_title_fallback.py",
        "tests/test_honor_wkl_recipe.py", "tests/test_phone_toggler.py", "tests/test_honor_cle_an00.py",
        "tests/test_row.py", "tests/test_vivo_v2417a_recipe.py",
    ),
    "tool/channel_policy.py": (
        "tests/test_channel_classification.py", "tests/test_channel_outcomes.py",
        "tests/test_issue_regressions.py", "tests/test_page_and_link_regressions.py",
        "tests/test_feedback_safety.py", "tests/test_release_regressions.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_huawei_channels.py", "tests/test_channel_page.py", "tests/test_adb_link.py",
        "tests/test_phone_host.py", "tests/test_tap_notice_regressions.py",
    ),
    "tool/host.py": (
        "tests/test_coverage_note.py", "tests/test_android_view.py", "tests/test_phone_host.py",
        "tests/test_summary.py", "tests/test_result_retry.py", "tests/test_job.py",
    ),
    "tool/events.py": (
        "tests/test_events.py", "tests/test_engine_events.py", "tests/test_client_events.py",
        "tests/test_result_retry.py", "tests/test_adb_link.py", "tests/test_wait.py",
        "tests/test_run_commands.py", "tests/test_layout_and_verdict_regressions.py",
        "tests/test_channel_outcomes.py", "tests/test_channel_page.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_plan.py", "tests/test_entries.py",
        "tests/test_ui_session.py", "tests/test_issue_regressions.py", "tests/test_phone_interface.py",
        "tests/test_api_structure.py", "tests/test_phone_host.py", "tests/test_tap_notice_regressions.py",
        "tests/test_job_races.py", "tests/test_page_and_link_regressions.py", "tests/test_honor_recipe.py",
        "tests/test_honor_wkl_recipe.py", "tests/test_huawei_channels.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_phone_launcher.py", "tests/test_phone_toggler.py",
        "tests/test_regressions.py", "tests/test_vivo_v2303a_recipe.py",
        "tests/test_vivo_v2417a_recipe.py",
    ),
    "tool/recipe_meta.py": (
        "tests/test_entries.py", "tests/test_catalog.py", "tests/test_recipe_variants.py",
        "tests/test_verify_ledger.py", "tests/test_redmi_k90_2510drk44c.py",
        "tests/test_xiaomi_14pro_recipe.py", "tests/test_recipe_audit.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_oppo_pmx110_recipe.py",
        "tests/test_meizu_recipe.py", "tests/test_oppo_pkt110_recipe.py",
        "tests/test_recipe_meta_module.py", "tests/test_redmi_24094rad4c_recipe.py",
        "tests/test_xiaomi_24129pn74c_recipe.py", "tests/test_xiaomi_2505apx7bc_recipe.py",
        "tests/test_adapt_cli.py", "tests/test_honor_wkl_recipe.py", "tests/test_huawei_channels.py",
        "tests/test_k70_recipe.py", "tests/test_k80pro_recipe.py", "tests/test_k90ultra_recipe.py",
        "tests/test_oneplus_plz110_recipe.py", "tests/test_oneplus_recipe.py",
        "tests/test_oppo_plg110_recipe.py", "tests/test_oppo_pma110_recipe.py",
        "tests/test_phk110_android15_recipe.py", "tests/test_pja110_android16_recipe.py",
        "tests/test_regressions.py", "tests/test_rmx3888_recipe.py", "tests/test_vivo_v1986a_recipe.py",
        "tests/test_vivo_v2303a_recipe.py", "tests/test_vivo_v2309a_recipe.py",
        "tests/test_vivo_v2417a_recipe.py", "tests/test_run_commands.py",
    ),
    "tool/recipe_source.py": (
        "tests/test_recipe_source.py", "tests/test_vocab.py", "tests/test_entries.py",
        "tests/test_catalog.py", "tests/test_recipe_audit.py", "tests/test_phone_facade.py",
        "tests/test_family.py", "tests/test_recipe_nav.py", "tests/test_verify_ledger.py",
    ),
    "tool/recipe_pick.py": (
        "tests/test_recipe_variants.py", "tests/test_recipe_audit.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_xiaomi_2505apx7bc_recipe.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_verify_ledger.py",
        "tests/test_meizu_recipe.py", "tests/test_redmi_k90_2510drk44c.py",
        "tests/test_xiaomi_14pro_recipe.py", "tests/test_oppo_pkt110_recipe.py",
        "tests/test_redmi_24094rad4c_recipe.py", "tests/test_huawei_channels.py",
        "tests/test_phk110_android15_recipe.py", "tests/test_pja110_android16_recipe.py",
        "tests/test_oneplus_plz110_recipe.py", "tests/test_regressions.py", "tests/test_k70_recipe.py",
        "tests/test_k80pro_recipe.py", "tests/test_k90ultra_recipe.py",
        "tests/test_vivo_v1986a_recipe.py", "tests/test_xiaomi_24129pn74c_recipe.py",
        "tests/test_honor_wkl_recipe.py", "tests/test_oneplus_recipe.py",
        "tests/test_oppo_plg110_recipe.py", "tests/test_oppo_pma110_recipe.py",
        "tests/test_vivo_v2303a_recipe.py", "tests/test_vivo_v2309a_recipe.py",
        "tests/test_vivo_v2417a_recipe.py", "tests/test_run_commands.py",
    ),
    # Protocol，方法体是 `...`：见模块文档，保留一个目标只为让 mutmut 有得收集。
    "tool/reader.py": ("tests/test_phone_interface.py",),
    "tool/plan.py": (
        "tests/test_plan.py", "tests/test_result_retry.py", "tests/test_job.py",
        "tests/test_harmony_client.py", "tests/test_job_races.py", "tests/test_dispatcher_exclusion.py",
    ),
    "tool/summary.py": (
        "tests/test_summary.py", "tests/test_android_view.py", "tests/test_result_retry.py",
        "tests/test_job.py", "tests/test_ui_session.py", "tests/test_job_races.py",
    ),
    "tool/coverage_note.py": (
        "tests/test_coverage_note.py", "tests/test_android_view.py", "tests/test_summary.py",
        "tests/test_job.py", "tests/test_result_retry.py", "tests/test_job_races.py",
        "tests/test_ui_session.py",
    ),
    "tool/diagnostics.py": (
        "tests/test_diagnostics.py", "tests/test_run_commands.py", "tests/test_channel_outcomes.py",
        "tests/test_adb_link.py", "tests/test_page_and_link_regressions.py", "tests/test_phone_host.py",
        "tests/test_plan.py", "tests/test_job.py",
    ),
    # gui 侧（#1429），同样由覆盖矩阵量出：任务编排被几乎所有跑计划的用例碰到。
    "gui/dispatcher.py": (
        "tests/test_layout_and_verdict_regressions.py", "tests/test_client_events.py",
        "tests/test_plan.py", "tests/test_result_retry.py", "tests/test_run_commands.py",
        "tests/test_ui_session.py", "tests/test_job_races.py", "tests/test_channel_outcomes.py",
        "tests/test_api_structure.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_phone_host.py", "tests/test_tap_notice_regressions.py", "tests/test_adb_link.py",
        "tests/test_job.py", "tests/test_dispatcher_exclusion.py", "tests/test_summary.py",
        "tests/test_channel_page.py", "tests/test_updates.py", "tests/test_error_report.py",
        "tests/test_harmony_client.py", "tests/test_feedback_safety.py",
        "tests/test_issue_regressions.py", "tests/test_packaging_entry.py",
        "tests/test_page_and_link_regressions.py", "tests/test_release_regressions.py",
    ),
    "gui/tasks.py": (
        "tests/test_plan.py", "tests/test_result_retry.py", "tests/test_job.py",
        "tests/test_client_events.py", "tests/test_job_races.py", "tests/test_channel_outcomes.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_run_commands.py",
        "tests/test_ui_session.py", "tests/test_error_report.py",
        "tests/test_tap_notice_regressions.py", "tests/test_phone_host.py",
        "tests/test_api_structure.py", "tests/test_adb_link.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_summary.py",
    ),
    "gui/adb.py": (
        "tests/test_adb_link.py", "tests/test_plan.py", "tests/test_result_retry.py",
        "tests/test_channel_outcomes.py", "tests/test_client_events.py", "tests/test_run_commands.py",
        "tests/test_tap_notice_regressions.py", "tests/test_layout_and_verdict_regressions.py",
        "tests/test_packaging_entry.py", "tests/test_job.py", "tests/test_job_races.py",
        "tests/test_phone_host.py", "tests/test_page_and_link_regressions.py",
        "tests/test_issue_regressions.py", "tests/test_summary.py", "tests/test_updates.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_release_regressions.py",
        "tests/test_feedback_safety.py", "tests/test_ui_session.py", "tests/test_api_structure.py",
        "tests/test_error_report.py",
    ),
    "gui/reporter.py": (
        "tests/test_error_report.py", "tests/test_client_events.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_feedback_safety.py", "tests/test_job_races.py", "tests/test_plan.py",
        "tests/test_run_commands.py", "tests/test_ui_session.py", "tests/test_channel_outcomes.py",
        "tests/test_adb_link.py", "tests/test_issue_regressions.py", "tests/test_phone_host.py",
        "tests/test_result_retry.py", "tests/test_channel_page.py", "tests/test_api_structure.py",
        "tests/test_job.py", "tests/test_packaging_entry.py",
        "tests/test_page_and_link_regressions.py", "tests/test_release_regressions.py",
        "tests/test_summary.py", "tests/test_tap_notice_regressions.py", "tests/test_updates.py",
    ),
    "gui/updates.py": (
        "tests/test_updates.py", "tests/test_update_install.py", "tests/test_adb_link.py",
        "tests/test_api_structure.py", "tests/test_channel_outcomes.py", "tests/test_client_events.py",
        "tests/test_error_report.py", "tests/test_feedback_safety.py", "tests/test_issue_regressions.py",
        "tests/test_job.py", "tests/test_job_races.py", "tests/test_layout_and_verdict_regressions.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_packaging_entry.py",
        "tests/test_page_and_link_regressions.py", "tests/test_phone_host.py", "tests/test_plan.py",
        "tests/test_release_regressions.py", "tests/test_result_retry.py", "tests/test_run_commands.py",
        "tests/test_summary.py", "tests/test_tap_notice_regressions.py", "tests/test_ui_session.py",
    ),
    "gui/update_install.py": (
        "tests/test_update_install.py", "tests/test_adb_link.py", "tests/test_api_structure.py",
        "tests/test_channel_outcomes.py", "tests/test_client_events.py", "tests/test_error_report.py",
        "tests/test_feedback_safety.py", "tests/test_issue_regressions.py", "tests/test_job.py",
        "tests/test_job_races.py", "tests/test_layout_and_verdict_regressions.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_packaging_entry.py",
        "tests/test_page_and_link_regressions.py", "tests/test_phone_host.py", "tests/test_plan.py",
        "tests/test_release_regressions.py", "tests/test_result_retry.py", "tests/test_run_commands.py",
        "tests/test_summary.py", "tests/test_tap_notice_regressions.py", "tests/test_ui_session.py",
        "tests/test_updates.py", "tests/test_old_install_notice.py",
    ),
    # 手机版替换层（#1430），同样由覆盖矩阵量出。`view` 被界面用例、inproc 的日志分流（经
    # `machine_prefix`）与 summary 的宿主链接用例执行到；`test_android_smoke` 整份在副本里跑不通
    # （出包、读 `android/` 源码），不进任何行。
    "android/app/src/main/python/aac_android/view.py": (
        "tests/test_android_view.py", "tests/test_android_shim.py", "tests/test_summary.py",
    ),
    "android/app/src/main/python/aac_android/adb.py": ("tests/test_android_shim.py",),
    "android/app/src/main/python/aac_android/screen.py": ("tests/test_android_shim.py",),
    "android/app/src/main/python/aac_android/inproc.py": ("tests/test_android_shim.py",),
    "android/app/src/main/python/aac_android/u2.py": ("tests/test_android_shim.py",),
}

# 变异副本里跑不通的测试，按 pytest node id 摘掉。整份文件都跑不通的（`test_rules_guards`
# 收集期就 `import tool` 失败、`test_doc_consistency` 整仓扫文本）不进上面任何一行。
UNUSABLE: dict[str, tuple[str, ...]] = {
    "tests/test_adapt_cli.py": ("tests/test_adapt_cli.py::AdaptCliParityTests",),
    "tests/test_adb_link.py": ("tests/test_adb_link.py::BackendMissingTextTests",),
    # 副本里没有 `android/` 的 Kotlin 源码：唯一读它的两条按方法摘掉，其余用例照跑（#1430）。
    # `test_modules_are_fresh_per_top_level_run` 依赖真产品路径的模块 purge，在 `src` 视角的副本里
    # 判定不同（重跑读到 `2` 而不是 `1`），也与被测模块无关，按方法摘掉。
    "tests/test_android_shim.py": (
        "tests/test_android_shim.py::ShellFacadeTest::test_facade_exposes_the_names_python_calls",
        "tests/test_android_shim.py::ShellFacadeTest::test_result_lives_on_the_facade",
        "tests/test_android_shim.py::InprocTest::test_modules_are_fresh_per_top_level_run",
    ),
    "tests/test_harmony_client.py": ("tests/test_harmony_client.py::PackageTests",),
    "tests/test_layout_and_verdict_regressions.py": (
        "tests/test_layout_and_verdict_regressions.py::AppLabelPackagingTests",
    ),
    "tests/test_phone_host.py": (
        "tests/test_phone_host.py::WordingTests",
        "tests/test_phone_host.py::DisconnectHintTests",
        "tests/test_phone_host.py::PhoneBootTests",
        "tests/test_phone_host.py::ClickerTests",
    ),
    "tests/test_packaging_entry.py": (
        "tests/test_packaging_entry.py::PackagingEntryTests::test_module_entry_forwards_cli",
        "tests/test_packaging_entry.py::PackagingEntryTests::test_app_script_entry_forwards_cli",
        "tests/test_packaging_entry.py::PackagingEntryTests::test_launch_script_entry_forwards_cli",
    ),
    "tests/test_phone_navigator.py": ("tests/test_phone_navigator.py::CallGraphTests",),
    "tests/test_recipe_meta_module.py": ("tests/test_recipe_meta_module.py::ImportPurityTests",),
    "tests/test_recipe_nav.py": ("tests/test_recipe_nav.py::DriverTests",),
    "tests/test_result_retry.py": ("tests/test_result_retry.py::EngineEmitsFailedStepsTests",),
    "tests/test_run_commands.py": ("tests/test_run_commands.py::CliParityTests",),
    "tests/test_ui_session.py": (
        "tests/test_ui_session.py::LockTests::test_other_process_is_blocked_until_owner_exits",
    ),
    "tests/test_vocab.py": ("tests/test_vocab.py::SourceShapeTest", "tests/test_vocab.py::GapsCommandLineTest"),
}


def tests_for(modules: Sequence[str]) -> list[str]:
    """这些模块要收集的 pytest 参数：目标文件按首次出现的顺序去重，再追加 `--deselect`。"""
    ordered: dict[str, None] = {}
    for module in modules:
        for target in MODULE_TESTS.get(module, ()):
            ordered.setdefault(target, None)
    args = list(ordered)
    for target in ordered:
        for node_id in UNUSABLE.get(target, ()):
            args.extend(["--deselect", node_id])
    return args


def modules_in_paths(paths: Iterable[str]) -> list[str]:
    """路径里落进映射表的模块，按首次出现的顺序去重。

    这几个模块被大量测试间接 import，而改动面只看路径：`git diff --name-only` 的输出直接喂进来，
    不解析补丁内容、不按行文本匹配——同一行文本在文件里重复出现时不会误判，因为根本不看文本。
    """
    ordered: dict[str, None] = {}
    for path in paths:
        if path in MODULE_TESTS:
            ordered.setdefault(path, None)
    return list(ordered)


def unknown(modules: Iterable[str]) -> list[str]:
    """不在表里的模块。调用方据此报错，而不是静默跑出 0 个 mutant。"""
    return [module for module in modules if module not in MODULE_TESTS]


# 手机版替换层不在仓库根，按产品路径（Chaquopy 的 sourceSets 要求它留在原处）换个前缀映射到 `src`。
ANDROID_PREFIX = "android/app/src/main/python/aac_android/"
SOURCE_PREFIXES = {"tool/": "src/", "gui/": "src/gui/", ANDROID_PREFIX: "src/aac_android/"}


def source_path(module: str) -> str:
    """`tool/catalog/schema.py` → `src/catalog/schema.py`，`gui/tasks.py` → `src/gui/tasks.py`，
    `android/…/aac_android/view.py` → `src/aac_android/view.py`。

    mutmut 按相对路径去掉 `src.` 前缀生成 mutant 名，工作目录里的 `src` 是 `tool/`、`gui/` 与
    `aac_android/` 的镜像；测试按顶层模块名 import `tool/` 的包、按包名 import `gui/`（`from gui
    import tasks`）、按包名 import `aac_android`（`from aac_android import view`），两边只在 `src`
    这个视角上对齐。
    """
    for prefix, view in SOURCE_PREFIXES.items():
        if module.startswith(prefix):
            return view + module[len(prefix):]
    raise ValueError(f"mutation 不接这些位置之外的模块：{module}")


def only_mutate(modules: Sequence[str]) -> list[str]:
    """mutmut 的 `only_mutate` 模式，用的是 `src` 视角。"""
    return [source_path(module) for module in modules]
