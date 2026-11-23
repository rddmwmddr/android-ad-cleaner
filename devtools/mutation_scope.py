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
    # catalog 装载内核（#1541）：51 个测试文件执行过它。`tests/recipe_case.py` 换成继承它的子类
    # 文件（同 #1536）：矩阵把继承来的 case 记在定义处，而基类的 `RECIPE = None` 按文件收集会红；
    # 真正跑那些 case 的十二个子类本来就在矩阵里，行不比矩阵窄。
    "tool/catalog/loader.py": (
        "tests/test_adapt_cli.py", "tests/test_catalog.py", "tests/test_entries.py",
        "tests/test_honor_cle_an00.py", "tests/test_honor_recipe.py", "tests/test_honor_wkl_recipe.py",
        "tests/test_k70_recipe.py", "tests/test_k80pro_recipe.py", "tests/test_k90ultra_recipe.py",
        "tests/test_meizu_recipe.py", "tests/test_oneplus_plz110_recipe.py",
        "tests/test_oneplus_recipe.py", "tests/test_oppo_pkt110_recipe.py",
        "tests/test_oppo_plg110_recipe.py", "tests/test_oppo_plp120_browser.py",
        "tests/test_oppo_plp120_coloros17.py", "tests/test_oppo_plp120_search.py",
        "tests/test_oppo_pma110_recipe.py", "tests/test_oppo_pmx110_recipe.py",
        "tests/test_oppo_pyb110_recipe.py", "tests/test_phk110_android15_recipe.py",
        "tests/test_phk110_recipe.py", "tests/test_phone_dismisser.py",
        "tests/test_phone_interface.py", "tests/test_phone_navigator.py",
        "tests/test_phone_settings_search.py", "tests/test_pja110_android16_recipe.py",
        "tests/test_recipe_call_snapshots.py", "tests/test_recipe_loader.py", "tests/test_recipe_nav.py",
        "tests/test_recipe_setting_checked.py", "tests/test_redmi_24094rad4c_recipe.py",
        "tests/test_regressions.py", "tests/test_release_regressions.py",
        "tests/test_rmx3700_recipe.py", "tests/test_rmx3888_recipe.py",
        "tests/test_vivo_2417_browser_entry.py", "tests/test_vivo_2547da_android17_recipe.py",
        "tests/test_vivo_v1986a_recipe.py", "tests/test_vivo_v2303a_recipe.py",
        "tests/test_vivo_v2309a_recipe.py", "tests/test_vivo_v2417a_recipe.py",
        "tests/test_vivo_v2545a_recipe.py", "tests/test_vivo_v2547a_recipe.py",
        "tests/test_xiaomi_24129pn74c_recipe.py", "tests/test_xiaomi_2505apx7bc_recipe.py",
        "tests/test_xiaomi_25060rk16c_recipe.py", "tests/test_xiaomi_ads_recipe.py",
        "tests/test_xiaomi_store_recipe.py", "tests/test_xiaomi_theme_recipe.py",
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
    # 渠道判定族一（#1533），同样由覆盖矩阵量出：认页 / 到达的纯函数被大量读屏用例执行到。
    "tool/channel_decide.py": (
        "tests/test_adb_link.py", "tests/test_channel_arrive.py", "tests/test_channel_decide.py",
        "tests/test_channel_outcomes.py", "tests/test_channel_page.py", "tests/test_issue_regressions.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_page_and_link_regressions.py", "tests/test_phone_interface.py",
        "tests/test_phone_toggler.py", "tests/test_row.py", "tests/test_tap_notice_regressions.py",
    ),
    "tool/channel_arrive.py": (
        "tests/test_adb_link.py", "tests/test_channel_arrive.py", "tests/test_channel_classification.py",
        "tests/test_channel_decide.py", "tests/test_channel_outcomes.py", "tests/test_channel_page.py",
        "tests/test_feedback_safety.py", "tests/test_huawei_channels.py", "tests/test_issue_regressions.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_page_and_link_regressions.py", "tests/test_release_regressions.py", "tests/test_row.py",
        "tests/test_tap_notice_regressions.py",
    ),
    # 读屏基础族（#1536），同样由覆盖矩阵量出：这几份是认页 / 拨动的底座，几乎每个读屏用例
    # 都会执行到其中一两份，所以行很宽（`fast` 47 个测试文件、`wait` 40、`captures` 46）。
    # `tests/recipe_case.py` 不在任何行里：矩阵把继承来的 case 记在定义处（该文件），但它是助手
    # 模块，基类的 `RECIPE = None`，按文件目标收集会拿空数据跑出红（实测 `RecipeSafetyCase`）。
    # 真正跑这些 case 的是子类文件，下面按子类逐个列出——比矩阵里那一条更宽，不会把杀得掉的 mutant 报成存活。
    "tool/fast.py": (
        "tests/test_adb_link.py", "tests/test_captures.py",
        "tests/test_catalog.py", "tests/test_channel_arrive.py", "tests/test_channel_classification.py",
        "tests/test_channel_decide.py", "tests/test_channel_outcomes.py", "tests/test_channel_page.py",
        "tests/test_channel_snapshot.py", "tests/test_engine_events.py", "tests/test_entries.py",
        "tests/test_fixtures.py", "tests/test_honor_recipe.py", "tests/test_honor_wkl_recipe.py",
        "tests/test_issue_regressions.py", "tests/test_k70_recipe.py", "tests/test_k80pro_recipe.py",
        "tests/test_k90ultra_recipe.py", "tests/test_layout_and_verdict_regressions.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_main_switch_bar.py",
        "tests/test_off_title_fallback.py", "tests/test_oneplus_plz110_recipe.py",
        "tests/test_oneplus_recipe.py", "tests/test_oppo_pkt110_recipe.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_oppo_pyb110_recipe.py",
        "tests/test_page_and_link_regressions.py", "tests/test_phk110_recipe.py",
        "tests/test_phone_dismisser.py", "tests/test_phone_facade.py", "tests/test_phone_host.py",
        "tests/test_phone_interface.py", "tests/test_phone_launcher.py",
        "tests/test_phone_navigator.py", "tests/test_phone_sessions.py",
        "tests/test_phone_settings_search.py", "tests/test_phone_toggler.py",
        "tests/test_recipe_call_snapshots.py", "tests/test_recipe_nav.py", "tests/test_regressions.py",
        "tests/test_release_regressions.py", "tests/test_rmx3700_recipe.py", "tests/test_row.py",
        "tests/test_tap_notice_regressions.py", "tests/test_ui_session.py",
        "tests/test_vivo_2417_browser_entry.py", "tests/test_vivo_2547da_android17_recipe.py",
        "tests/test_vivo_v2417a_recipe.py", "tests/test_xiaomi_24129pn74c_recipe.py",
        "tests/test_xiaomi_2505apx7bc_recipe.py", "tests/test_xiaomi_25060rk16c_recipe.py"
    ),
    "tool/wait.py": (
        "tests/test_adapt_cli.py", "tests/test_adb_link.py", "tests/test_channel_arrive.py",
        "tests/test_channel_decide.py", "tests/test_channel_outcomes.py", "tests/test_channel_page.py",
        "tests/test_engine_events.py", "tests/test_entries.py", "tests/test_fixtures.py",
        "tests/test_huawei_channels.py", "tests/test_issue_regressions.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_off_title_fallback.py", "tests/test_oneplus_plz110_recipe.py",
        "tests/test_oppo_plp120_coloros17.py", "tests/test_oppo_plp120_search.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_oppo_pyb110_recipe.py",
        "tests/test_page_and_link_regressions.py", "tests/test_phone_base.py",
        "tests/test_phone_dismisser.py", "tests/test_phone_interface.py",
        "tests/test_phone_launcher.py", "tests/test_phone_navigator.py",
        "tests/test_phone_settings_search.py", "tests/test_phone_toggler.py",
        "tests/test_pja110_android16_recipe.py", "tests/test_recipe_call_snapshots.py",
        "tests/test_recipe_nav.py", "tests/test_redmi_k90_2510drk44c.py", "tests/test_regressions.py",
        "tests/test_row.py", "tests/test_tap_notice_regressions.py", "tests/test_vivo_v2417a_recipe.py",
        "tests/test_wait.py", "tests/test_xiaomi_14pro_recipe.py",
        "tests/test_xiaomi_24129pn74c_recipe.py", "tests/test_xiaomi_2505apx7bc_recipe.py",
        "tests/test_xiaomi_25060rk16c_recipe.py"
    ),
    "tool/captures.py": (
        "tests/test_adb_link.py", "tests/test_captures.py",
        "tests/test_catalog.py", "tests/test_channel_arrive.py", "tests/test_channel_decide.py",
        "tests/test_channel_outcomes.py", "tests/test_channel_page.py",
        "tests/test_channel_snapshot.py", "tests/test_engine_events.py", "tests/test_entries.py",
        "tests/test_fixtures.py", "tests/test_honor_recipe.py", "tests/test_honor_wkl_recipe.py",
        "tests/test_issue_regressions.py", "tests/test_k70_recipe.py", "tests/test_k80pro_recipe.py",
        "tests/test_k90ultra_recipe.py", "tests/test_layout_and_verdict_regressions.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_main_switch_bar.py",
        "tests/test_off_title_fallback.py", "tests/test_oneplus_plz110_recipe.py",
        "tests/test_oneplus_recipe.py", "tests/test_oppo_pkt110_recipe.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_page_and_link_regressions.py",
        "tests/test_phk110_recipe.py", "tests/test_phone_base.py", "tests/test_phone_dismisser.py",
        "tests/test_phone_facade.py", "tests/test_phone_host.py", "tests/test_phone_interface.py",
        "tests/test_phone_launcher.py", "tests/test_phone_navigator.py", "tests/test_phone_sessions.py",
        "tests/test_phone_settings_search.py", "tests/test_phone_toggler.py",
        "tests/test_recipe_call_snapshots.py", "tests/test_recipe_nav.py", "tests/test_regressions.py",
        "tests/test_release_regressions.py", "tests/test_rmx3700_recipe.py", "tests/test_row.py",
        "tests/test_run_commands.py", "tests/test_tap_notice_regressions.py",
        "tests/test_ui_session.py", "tests/test_vivo_2417_browser_entry.py",
        "tests/test_vivo_2547da_android17_recipe.py", "tests/test_xiaomi_24129pn74c_recipe.py",
        "tests/test_xiaomi_2505apx7bc_recipe.py", "tests/test_xiaomi_25060rk16c_recipe.py"
    ),
    # 渠道判定族二（#1537），同样由覆盖矩阵量出：批处理记账、拨动决定、隐藏名单与屏幕快照被
    # 读屏与回归用例执行到；`screen_snapshot` 是这一族的数据层，覆盖面最宽（38 个测试文件）。
    "tool/channel_batch.py": (
        "tests/test_adb_link.py", "tests/test_channel_arrive.py", "tests/test_channel_batch.py",
        "tests/test_channel_classification.py", "tests/test_channel_outcomes.py",
        "tests/test_channel_page.py", "tests/test_feedback_safety.py", "tests/test_issue_regressions.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_page_and_link_regressions.py", "tests/test_phone_host.py",
        "tests/test_tap_notice_regressions.py",
    ),
    "tool/channel_toggle.py": (
        "tests/test_channel_outcomes.py", "tests/test_channel_page.py", "tests/test_channel_toggle.py",
        "tests/test_feedback_safety.py", "tests/test_issue_regressions.py",
        "tests/test_page_and_link_regressions.py",
    ),
    "tool/ui_hidden.py": (
        "tests/test_channel_classification.py", "tests/test_channel_outcomes.py",
        "tests/test_feedback_safety.py", "tests/test_issue_regressions.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_page_and_link_regressions.py",
        "tests/test_release_regressions.py",
    ),
    "tool/screen_snapshot.py": (
        "tests/test_adb_link.py", "tests/test_catalog.py", "tests/test_channel_arrive.py",
        "tests/test_channel_classification.py", "tests/test_channel_decide.py",
        "tests/test_channel_outcomes.py", "tests/test_channel_page.py", "tests/test_channel_snapshot.py",
        "tests/test_channel_toggle.py", "tests/test_entries.py", "tests/test_fixtures.py",
        "tests/test_honor_recipe.py", "tests/test_honor_wkl_recipe.py", "tests/test_issue_regressions.py",
        "tests/test_layout_and_verdict_regressions.py", "tests/test_lock_and_disconnect_regressions.py",
        "tests/test_main_switch_bar.py", "tests/test_off_title_fallback.py",
        "tests/test_oneplus_plz110_recipe.py", "tests/test_oppo_pmx110_recipe.py",
        "tests/test_page_and_link_regressions.py", "tests/test_phone_base.py",
        "tests/test_phone_dismisser.py", "tests/test_phone_interface.py", "tests/test_phone_launcher.py",
        "tests/test_phone_navigator.py", "tests/test_phone_settings_search.py",
        "tests/test_phone_toggler.py", "tests/test_recipe_call_snapshots.py", "tests/test_recipe_nav.py",
        "tests/test_regressions.py", "tests/test_release_regressions.py", "tests/test_row.py",
        "tests/test_tap_notice_regressions.py", "tests/test_vivo_2417_browser_entry.py",
        "tests/test_vivo_2547da_android17_recipe.py", "tests/test_xiaomi_24129pn74c_recipe.py",
        "tests/test_xiaomi_25060rk16c_recipe.py",
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
    # 数据与词表（#1544），同样由覆盖矩阵量出：`entries` 被入口速查 / 词库 / adapt 的用例执行到，
    # `vocab` 只被它自己的用例与 `test_adapt_cli` 执行到。
    "tool/entries.py": (
        "tests/test_adapt_cli.py", "tests/test_catalog.py", "tests/test_entries.py",
        "tests/test_recipe_call_snapshots.py", "tests/test_vocab.py",
        "tests/test_xiaomi_24129pn74c_recipe.py",
    ),
    "tool/vocab.py": ("tests/test_adapt_cli.py", "tests/test_vocab.py"),
    # 手机拨动族（#1534）：`session` 只有三个 `__init__` 与 `set_app()` 被执行，44 份用例里绝大多数
    # 的接触来自 `Phone` 装配。`toggler` 不进表（实测见 ADR-0043「tool/ 其余模块（#1445）」）：
    # 纯函数与索引已被 13 份用例守住，存活集中在该模块自己的编排段（`off` 34、`confirm` 3）。
    "tool/phone/session.py": (
        # 矩阵把 `recipe_case.py` 里写的用例归到它自己名下，但那是只有被继承才跑得起来的基类
        # （单独收集时子类不给 `RECIPE`，`RecipeSafetyCase` 12 条全红）；按实际所有者换成三个子类文件。
        "tests/test_k70_recipe.py", "tests/test_k80pro_recipe.py",
        "tests/test_xiaomi_24129pn74c_recipe.py", "tests/test_adb_link.py", "tests/test_captures.py",
        "tests/test_catalog.py", "tests/test_channel_arrive.py", "tests/test_channel_decide.py",
        "tests/test_channel_outcomes.py", "tests/test_channel_page.py",
        "tests/test_channel_snapshot.py", "tests/test_engine_events.py", "tests/test_entries.py",
        "tests/test_fixtures.py", "tests/test_honor_recipe.py", "tests/test_honor_wkl_recipe.py",
        "tests/test_issue_regressions.py", "tests/test_layout_and_verdict_regressions.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_main_switch_bar.py",
        "tests/test_off_title_fallback.py", "tests/test_oneplus_plz110_recipe.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_page_and_link_regressions.py",
        "tests/test_phk110_recipe.py", "tests/test_phone_dismisser.py",
        "tests/test_phone_facade.py", "tests/test_phone_host.py", "tests/test_phone_interface.py",
        "tests/test_phone_launcher.py", "tests/test_phone_navigator.py",
        "tests/test_phone_sessions.py", "tests/test_phone_settings_search.py",
        "tests/test_phone_toggler.py", "tests/test_recipe_call_snapshots.py",
        "tests/test_recipe_nav.py", "tests/test_regressions.py",
        "tests/test_release_regressions.py", "tests/test_rmx3700_recipe.py", "tests/test_row.py",
        "tests/test_tap_notice_regressions.py", "tests/test_ui_session.py",
        "tests/test_vivo_2417_browser_entry.py", "tests/test_vivo_2547da_android17_recipe.py",
        "tests/test_xiaomi_25060rk16c_recipe.py",
    ),
    # 连接宿主（#1535），由覆盖矩阵量出：`Connection` / `wait_for` / `present` 被几乎所有跑读取的
    # 用例执行到，所以行很宽（51 个文件）。`tests/recipe_case.py` 是只有基类的助手模块（`RECIPE`
    # 为 None），pytest 按路径收集它时基类用例直接红，整份不进行；它的用例由 `_recipe.py`
    # 子类文件跑（同一条用例在真实数据上执行），不少杀。
    "tool/adb_link.py": (
        "tests/test_adb_link.py", "tests/test_captures.py",
        "tests/test_catalog.py", "tests/test_channel_arrive.py", "tests/test_channel_classification.py",
        "tests/test_channel_decide.py", "tests/test_channel_outcomes.py", "tests/test_channel_page.py",
        "tests/test_channel_snapshot.py", "tests/test_engine_events.py", "tests/test_entries.py",
        "tests/test_feedback_safety.py", "tests/test_fixtures.py", "tests/test_honor_recipe.py",
        "tests/test_honor_wkl_recipe.py", "tests/test_huawei_channels.py", "tests/test_issue_regressions.py",
        "tests/test_layout_and_verdict_regressions.py",
        "tests/test_lock_and_disconnect_regressions.py", "tests/test_main_switch_bar.py",
        "tests/test_off_title_fallback.py", "tests/test_oneplus_plz110_recipe.py",
        "tests/test_oppo_pmx110_recipe.py", "tests/test_page_and_link_regressions.py",
        "tests/test_phk110_recipe.py", "tests/test_phone_base.py", "tests/test_phone_dismisser.py",
        "tests/test_phone_facade.py", "tests/test_phone_host.py", "tests/test_phone_interface.py",
        "tests/test_phone_launcher.py", "tests/test_phone_navigator.py", "tests/test_phone_sessions.py",
        "tests/test_phone_settings_search.py", "tests/test_phone_toggler.py",
        "tests/test_recipe_call_snapshots.py", "tests/test_recipe_nav.py", "tests/test_recipe_variants.py",
        "tests/test_regressions.py", "tests/test_release_regressions.py", "tests/test_rmx3700_recipe.py",
        "tests/test_row.py", "tests/test_run_commands.py", "tests/test_tap_notice_regressions.py",
        "tests/test_ui_session.py", "tests/test_vivo_2417_browser_entry.py",
        "tests/test_vivo_2547da_android17_recipe.py", "tests/test_vivo_v2303a_recipe.py",
        "tests/test_vivo_v2417a_recipe.py", "tests/test_xiaomi_24129pn74c_recipe.py",
        "tests/test_xiaomi_25060rk16c_recipe.py",
    ),
    "tool/huawei_channels.py": ("tests/test_huawei_channels.py",),
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
    # devtools（#1515）：`check_ticket_ref` 单模块单测试文件。`WorkflowTest` 读
    # `.github/workflows/ticket-checks.yml`，副本里没有根级 `.github/`，按类摘掉（见 `UNUSABLE`）。
    "devtools/check_ticket_ref.py": ("tests/test_ticket_ref.py",),
    # devtools（#1517）：`commits` 没有独立测试文件，三份 `check_*` 共同 import 它、共同覆盖它。
    # 三份 `check_*` 各由自己的测试文件覆盖；读根级 `.github/` 与 `CLAUDE.md` 的类见 `UNUSABLE`。
    "devtools/commits.py": (
        "tests/test_dco.py", "tests/test_conventional.py", "tests/test_comment_tickets.py",
    ),
    "devtools/check_dco.py": ("tests/test_dco.py",),
    "devtools/check_conventional.py": ("tests/test_conventional.py",),
    "devtools/check_comment_tickets.py": ("tests/test_comment_tickets.py",),
    # devtools（#1520）：`gh` 被 `claim` / `stale` 共用，三份测试文件都真实执行它。
    # 另外几份执行 `gh` 的测试（`followup` / `triage_audit` / `release_*`）属于各自模块的行，
    # 这里不收：它们把副本里跑不通的根级读取一并拖进这一段。
    "devtools/gh.py": ("tests/test_gh.py", "tests/test_claim.py", "tests/test_stale_scan.py"),
    "devtools/claim.py": ("tests/test_claim.py",),
    "devtools/stale.py": ("tests/test_stale_scan.py",),
    # devtools（#1522）：`followup` / `triage_audit` / `release_assets` / `release_meta` 都经 `gh` 取数，
    # 但各有独立测试文件、互不共享；`gh` 已由上面那行进表，这里只收各自的行。副本里跑不通的根级读取
    # （`release_meta` 读 `index.html`、`followup` 读模块相对路径下不存在的 `docs/`）见 `UNUSABLE`。
    "devtools/followup.py": ("tests/test_followup.py",),
    "devtools/triage_audit.py": ("tests/test_triage_audit.py",),
    "devtools/release_assets.py": ("tests/test_release_assets.py",),
    "devtools/release_meta.py": ("tests/test_release_meta.py",),
    # devtools（#1519）：`test_anchors` 与 `unittest_summary` 作为一族。`test_anchors` 的判定逻辑
    # （`recipe_tokens` / `base_of` / `recipe_owned` / `violations` / `domain_violations`）与 CLI 入口由
    # `tests/test_test_collection.py` 的 `AnchorTests` / `DomainTests` / `AnchorMainTests` 逐条覆盖
    # （临时树上的反例），`unittest_summary` 由 `tests/test_unittest_summary.py` 覆盖；两处一并收集。
    "devtools/test_anchors.py": (
        "tests/test_test_collection.py", "tests/test_unittest_summary.py",
    ),
    "devtools/unittest_summary.py": ("tests/test_unittest_summary.py",),
    # devtools（#1518）：`glob_scan` 单模块单测试文件；`script_surface` 的唯一覆盖者就是手机版
    # 门面测试的 `ScriptSurfaceTests`。两份都要在副本里对真实仓库求值/读根级目录的用例摘掉，见 `UNUSABLE`。
    "devtools/glob_scan.py": ("tests/test_glob_scan.py",),
    "devtools/script_surface.py": ("tests/test_phone_facade.py",),
    # `tool/chan_fast.py` 在表外（#1533，ADR-0043「tool/ 其余模块（#1445）」）：实测 1804 个
    # mutant，杀死 1331、存活 462、无测试 6、超时 5。存活集中在整批编排段（`run` 112、`toggle` 57，
    # 加上 `_enter_app_page` 47、`_skeleton` 35、`undo_message` 20 等）；`run` / `toggle` 的清零要造
    # 整套 `Phone` / `ShellPhone` / `UiHidden` 替身并锁调用序列，落在成本闸门之外。模块整体才进表，
    # 故整份登记为表外已知缺口。
    # `tool/row.py` 在表外（#1536，ADR-0043「tool/ 其余模块（#1445）」）：实测 1256 个 mutant，杀死 1075、
    # 存活 181、无测试 0。存活都在纯函数里（`skeleton` 48、`title_label` 46、`summary` 29、`path` 16、
    # `switch_row` / `dedupe` 各 9），但同一语句上同时挂着可杀与不可区分（语义等价 / 边界等价）的变异
    # （`//2` 与 `/2`、`rsplit(...)[-1]` 的各种 maxsplit、`or ""` 的占位串），清零要先按行拆开这些语句、
    # 再给每条边界构造专用页面——那是改写读屏算术去适配尺子，不在本票的成本内。模块整体才进表，故整份
    # 登记为表外已知缺口。
    # `devtools/typecheck_recipes.py` 在表外（#1521，ADR-0043）：实测 179 个 mutant，存活 8、无测试 154。
    # 唯一覆盖是 `test_catalog` 的一个方法，只碰到 `_check_catalog`，且它还有 8 个存活；`recipes` /
    # `_check_python` / `main` 分别 54 / 28 / 72 个 mutant 全无测试。`_check_python` 起 mypy 子进程、
    # `main` 扫全部 recipes，补到存活 0、无测试 0 需要新建 harness，不是补一条断言——登记为表外已知缺口。
}

# 变异副本里跑不通的测试，按 pytest node id 摘掉。整份文件都跑不通的（`test_rules_guards`
# 收集期就 `import tool` 失败、`test_doc_consistency` 整仓扫文本）不进上面任何一行。
UNUSABLE: dict[str, tuple[str, ...]] = {
    "tests/test_adapt_cli.py": ("tests/test_adapt_cli.py::AdaptCliParityTests",),
    "tests/test_adb_link.py": ("tests/test_adb_link.py::BackendMissingTextTests",),
    # 副本里没有根级 `CLAUDE.md`：只摘读它的那条方法。退出码与命令名两条断言拆在同类另一条里，
    # 仍在变异里跑（#1520）。
    "tests/test_claim.py": (
        "tests/test_claim.py::PinnedContractTests::test_the_command_is_documented_in_claude_md",
    ),
    # 副本里没有根级 `.github/`：整类读 workflow 文件的用例按类摘掉（#1517）。
    "tests/test_comment_tickets.py": ("tests/test_comment_tickets.py::WorkflowTest",),
    # 副本里没有根级 `.github/`（`WorkflowTest`）与 `CLAUDE.md`（`DocumentedTypesTest`）：两类一起摘（#1517）。
    "tests/test_conventional.py": (
        "tests/test_conventional.py::WorkflowTest",
        "tests/test_conventional.py::DocumentedTypesTest",
    ),
    # 副本里没有根级 `.github/`：整类读 workflow 文件的用例按类摘掉（#1517）。
    "tests/test_dco.py": ("tests/test_dco.py::WorkflowTest",),
    # `RealQueueTests` 读 `followup.DOC`，它是模块相对路径 `…/docs/agents/release-followup.md`：副本里
    # 模块在 `mutants/src/devtools/` 下，`mutants/src/docs/` 不存在（`docs/` 只拷到 `mutants/` 根）。
    # 整类两条都在读它，按类摘掉（#1522）。
    "tests/test_followup.py": ("tests/test_followup.py::RealQueueTests",),
    # 副本里没有根级 `index.html`：只摘读它比对卡片顺序的那条方法，同类的清单生成断言照跑（#1522）。
    "tests/test_release_meta.py": (
        "tests/test_release_meta.py::PlanSumsTests::test_manifest_order_is_the_download_card_order",
    ),
    # 副本里没有 `android/` 的 Kotlin 源码：唯一读它的两条按方法摘掉，其余用例照跑（#1430）。
    # `test_modules_are_fresh_per_top_level_run` 依赖真产品路径的模块 purge，在 `src` 视角的副本里
    # 判定不同（重跑读到 `2` 而不是 `1`），也与被测模块无关，按方法摘掉。
    "tests/test_android_shim.py": (
        "tests/test_android_shim.py::ShellFacadeTest::test_facade_exposes_the_names_python_calls",
        "tests/test_android_shim.py::ShellFacadeTest::test_result_lives_on_the_facade",
        "tests/test_android_shim.py::InprocTest::test_modules_are_fresh_per_top_level_run",
    ),
    # 副本里 `ROOT` 是 `mutants/`：没有根级 `tool/`、`devtools/`。`RepoTests` 整类对真实仓库求值
    # （`scan(ROOT)`、读 `tests/test_source_text.py`）；`ExemptionTests` 里那条「豁免仍对得上空匹配」
    # 同样 `scan(ROOT)`，按方法摘掉，同类的负例用例照跑（#1518）。
    "tests/test_glob_scan.py": (
        "tests/test_glob_scan.py::RepoTests",
        "tests/test_glob_scan.py::ExemptionTests::test_every_exemption_still_matches_nothing_on_the_real_repo",
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
    # 副本里没有根级 `.github/`：整类读 workflow 文件的用例按类摘掉（#1515）。
    "tests/test_ticket_ref.py": ("tests/test_ticket_ref.py::WorkflowTest",),
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


def modules_for_tests(paths: Iterable[str]) -> list[str]:
    """改到的测试文件覆盖哪些模块：把 `MODULE_TESTS` 反过来读，按首次出现的顺序去重。

    改测试文件的 PR 里没有模块路径可看，删除用例检测就落在这里：文件出现在哪几行，
    那几行对应的模块本次都要跑（#1531）。索引现建现用——表只有几十行，爱惜它不如让它不会漂。
    """
    by_test: dict[str, list[str]] = {}
    for module, targets in MODULE_TESTS.items():
        for target in targets:
            by_test.setdefault(target, []).append(module)
    ordered: dict[str, None] = {}
    for path in paths:
        for module in by_test.get(path, ()):
            ordered.setdefault(module, None)
    return list(ordered)


def unknown(modules: Iterable[str]) -> list[str]:
    """不在表里的模块。调用方据此报错，而不是静默跑出 0 个 mutant。"""
    return [module for module in modules if module not in MODULE_TESTS]


# 手机版替换层不在仓库根，按产品路径（Chaquopy 的 sourceSets 要求它留在原处）换个前缀映射到 `src`。
ANDROID_PREFIX = "android/app/src/main/python/aac_android/"
SOURCE_PREFIXES = {
    "tool/": "src/",
    "gui/": "src/gui/",
    "devtools/": "src/devtools/",
    ANDROID_PREFIX: "src/aac_android/",
}


def source_path(module: str) -> str:
    """`tool/catalog/schema.py` → `src/catalog/schema.py`，`gui/tasks.py` → `src/gui/tasks.py`，
    `devtools/check_ticket_ref.py` → `src/devtools/check_ticket_ref.py`，
    `android/…/aac_android/view.py` → `src/aac_android/view.py`。

    mutmut 按相对路径去掉 `src.` 前缀生成 mutant 名，工作目录里的 `src` 是 `tool/`、`gui/`、
    `devtools/` 与 `aac_android/` 的镜像；测试按顶层模块名 import `tool/` 的包、按包名 import
    `gui/`（`from gui import tasks`）、`devtools/`（`from devtools import check_ticket_ref`）与
    `aac_android`（`from aac_android import view`），两边只在 `src` 这个视角上对齐。
    """
    for prefix, view in SOURCE_PREFIXES.items():
        if module.startswith(prefix):
            return view + module[len(prefix):]
    raise ValueError(f"mutation 不接这些位置之外的模块：{module}")


def only_mutate(modules: Sequence[str]) -> list[str]:
    """mutmut 的 `only_mutate` 模式，用的是 `src` 视角。"""
    return [source_path(module) for module in modules]
