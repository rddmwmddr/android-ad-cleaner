"""tests/ 的锚点登记（rule:dev.tests.anchor-registry）：每个测试文件要么是已声明的锚点，
要么在「待归并」名单里，要么是某份机型脚本的专用测试（文件名点名了它）。

判据正文在 docs/agents/test-anchors.md，本文件是它的机械镜像：`ANCHORS` 与文档的
`## 锚点登记` 表由 tests/test_test_collection.py 逐项对拍。`PENDING` 是临时逃生口，只收
存量票号文件，每条记着并到哪个已登记的文件；条数冻结在 `PENDING_CAP`，只许降。

`violations(root)` 对给定根目录求值，不依赖真实仓库状态——反例用临时目录构造。
"""
import difflib
import re
import sys
from pathlib import Path

from stdio import use_utf8_console

use_utf8_console()

# 与 docs/agents/test-anchors.md 的 `## 锚点登记` 表逐项相同（文件名与理由都逐字），
# tests/test_test_collection.py 守着。理由里不要出现竖线，表会散架。
ANCHORS = {
    # 引擎与读屏
    "test_adb_link.py": "手机连接：adb 在哪、命令服务断开 / 读屏超时 / 后台屏没了三种结局怎么判、读屏探测在哪找。",
    "test_row.py": "「开关所属的那一行」的唯一定义：结构定界、几何分带、同名去重与自绘开关去重。",
    "test_wait.py": "「等到认得出」：超时、稳定、变化、受阻四个判据，外加等机主解锁。",
    "test_entries.py": "入口速查表与它怎么被用：每条入口有出处、文档同源、reach() 按直达与搜索回退，以及各品牌脚本进具体入口（齿轮、直达、浏览器 / 主题 / 商店 / 负一屏）。",
    "test_vocab.py": "品牌词库：词条有出处、键与入口速查相同、同页保留项只在那一页成立。",
    "test_events.py": "引擎事件的词表与解析：六个 kind、固定前缀、坏行当没有。",
    "test_engine_events.py": "引擎侧在语义发生地发事件，人话逐字不变。",
    "test_client_events.py": "客户端只认引擎事件：事件行不进日志、人话本身不改状态。",
    "test_channel_classification.py": "渠道判定：哪些渠道算营销、受保护、默认不勾，扫描因此列出谁、排除谁。",
    "test_channel_outcomes.py": "渠道批处理的结局记账与上报：一项的结局是值，怎么记、怎么报由几张表定。",
    "test_channel_page.py": "渠道页：从哪条路走进去、认出的是不是渠道页、从哪一行拿开关。",
    # Phone 门面、两个基座与七个阶段
    "test_phone_facade.py": "Phone 门面 + 两个基座 + 五个阶段的对外契约。",
    "test_phone_base.py": "两个基座可以各自独立构造，不必造整台 Phone。",
    "test_phone_sessions.py": "三个跨阶段会话对象，门面用显式属性转发过去。",
    "test_phone_toggler.py": "拨动阶段：这一页该关的开关真的被关掉，含确认框判定与等待、页顶复位与残留提示。",
    "test_phone_navigator.py": "导航阶段的对外契约：go / tab / 入口与落点确认。",
    "test_phone_settings_search.py": "设置搜索阶段的两条对外契约。",
    "test_phone_dismisser.py": "弹窗与推广位阶段：词表只有一份，推广位点了要退回。",
    "test_phone_launcher.py": "启动与落点阶段：前台归属、抢夺者现场与落点校验。",
    "test_phone_interface.py": "Phone 的接口面：读屏策略、探路包名过滤、安全模式与 adapter 名字。",
    # 拨动与导航的策略面
    "test_switch_plan.py": "plan_switches() 的策略面：这一页该拨哪些开关，与点击循环无关。",
    "test_off_readback.py": "readback() 与 pick_retry_rows()：回读结局与该补点哪一行。",
    "test_off_title_fallback.py": "只认行标题的页面：点开关本体不动时 off() 回退到点标题。",
    "test_main_switch_bar.py": "渠道页的 main_switch_bar：外层容器里包着真开关，不能按颜色当自绘开关。",
    "test_ui_session.py": "读屏服务占用、失败清理、跨进程互斥与失败后的收尾。",
    "test_never_suspend.py": "NEVER 保护集：挂了会坏功能的包，整批拒绝、不落一条命令到手机。",
    # 机型脚本的基础设施
    "test_recipe_kit.py": "引擎注入的脚本前导：段包装、跳过出口、失败台账、锁屏中止、安全模式整页关闭与失败现场。",
    "test_recipe_loader.py": "机型脚本只有一个装载入口，测试不许自己 exec 一份脚本。",
    "test_recipe_meta_module.py": "配方元数据住中立模块：非 CLI 代码 import 它不背 CLI 副作用。",
    "test_recipe_variants.py": "同一型号按系统版本选脚本变体，变体要进安装包。",
    "test_recipe_setting_checked.py": "机型脚本必须消费 p.setting() 的返回值，不能空跑还记成功。",
    "test_recipe_preamble_migration.py": "机型脚本不再自带前导：结构守卫与每份脚本的行为守卫。",
    # 客户端、打包、更新与平台
    "test_backups.py": "备份目录的命名、扫描与 <型号>-gui 兜底。",
    "test_captures.py": "失败现场落盘：两处留现场写原文、没目录不写、归档名与体积报数。",
    "test_error_report.py": "错误上报：内容脱敏、预览与发送一致、限频、安装编号与服务器回应。",
    "test_updates.py": "应用内更新：真实字节下载与状态迁移，网络与安装由边界替身接管。",
    "test_update_install.py": "在临时目录里真正换文件：回滚、保留卸载器与新进程健康回执。",
    "test_win_preflight.py": "Windows 启动失败归因：缺 WebView2、MOTW、托管 dll 被判远程。",
    "test_win_dotnet_config.py": "随包分发的 <exe>.config 让包内托管 dll 不被判成网络位置。",
    "test_hdc_fetch.py": "HDC 只在构建期下载、按钉死的 SHA-256 校验并解包。",
    "test_hdc_lookup.py": "找 hdc 的候选顺序，五档只有这一份。",
    "test_packaging_entry.py": "打包入口指向的文件存在、能 import、并给出 main。",
    "test_entrypoint_refs.py": "非测试入口对 gui.app 的引用得像真的一样存在。",
    "test_source_text.py": "源码文本的两条机械规则：不写裸零宽字符、基线钉提交 SHA。",
    "test_stdio.py": "标准流 UTF-8 的唯一出口：尽力而为、失败静默。",
    "test_subprocess_text_mode.py": "子进程的文本模式必须写清解码方式。",
    "test_runtime_symbols.py": "跨运行时符号：tool/ 在电脑与手机版跑两套依赖，静态引用的名字要真的存在。",
    "test_declared_fields.py": "构造处声明过的字段要直接读，不再 getattr 兜底。",
    # tests/ 自身的守卫
    "test_test_collection.py": "用例只在 tests/ 下定义，且每个测试文件都落到已声明的锚点。",
    "test_rules_guards.py": "规则守卫：文档内容、注册表、引擎结构与流程条目各自的机械判据。",
    "test_rules_registry.py": "规则注册表的四条不变式，锚点与登记双向一致。",
    "test_doc_consistency.py": "文档与单一来源一致：ADR 字段表、品牌连点表、共享样式与教程截图。",
    "test_web_client.py": "前端用例的代跑与守卫：tests/js/ 的 jsdom 用例由它在 unittest 里跑。",
    "test_fixtures.py": "夹具本身的行为：样本、假时钟、时间轴与假 Phone。",
    "test_compare_phone_state.py": "对拍驱动自己管基线 worktree：未知 SHA 报错且不留下 worktree。",
    # 手机版与鸿蒙
    "test_android_bundle.py": "APK 里那批 gui 文件必须覆盖 gui/app.py 的导入期依赖。",
    "test_android_shim.py": "手机版替换层：不连手机，替换掉执行通道与读屏。",
    "test_android_view.py": "手机版界面的判断：结果怎么说、什么时候挡住开始、反馈网址怎么截。",
    "test_android_version.py": "单键 getprop 读不到版本时按分区属性回退。",
    "test_android_smoke.py": "真机冒烟：出包、装机、启动、执行、还原三段各自出结论。",
    "test_api_structure.py": "窗口桥契约与客户端三块的责任边界。",
    "test_gui_import.py": "import gui.app 不许有副作用：不建目录、不改 sys.path、不加载 tool/。",
    "test_job.py": "一次执行的状态收成 Job，poll 只读锁内快照。",
    "test_harmony_bridge.py": "鸿蒙窗口桥只转发，状态与构造逻辑不落在 Api 上。",
    "test_harmony_client.py": "鸿蒙接入后的选机、互斥、持久化、停止与旧数据兼容。",
    "test_harmony_engine.py": "桌面引擎的离线用例：合成的界面树与假手机。",
    "test_harmony_vocab.py": "鸿蒙词库守卫。",
    # 计划与命令
    "test_plan.py": "一次执行跑哪些步骤：Plan 规格的八个键与往返，以及按规格排出的任务、未执行行与重试轮。",
    "test_run_commands.py": "run.py 的命令接口与它产出的诊断：退出码只在出口、多余往返的守卫、「只是搬家」的对拍，以及设备名与收尾快照。",
    "test_adapt_cli.py": "adapt.py 三条子命令对外的退出码与两路输出。",
    # 适配工具与仓库流程
    "test_claim.py": "开工认领：一条命令写认领评论并摘待办标签，仲裁只看票下评论。",
    "test_triage_audit.py": "triage 四条集合判据，登记表与脚本常量逐项对拍。",
    "test_stale_scan.py": "needs-info 停摆机制：判定与阈值、写入与幂等。",
    "test_conventional.py": "提交信息的 Conventional Commits 校验。",
    "test_dco.py": "每个非 merge 提交都带与作者邮箱一致的 signoff。",
    "test_ticket_ref.py": "分支名与 PR 正文指到同一张票。",
    "test_comment_tickets.py": "新写的行里挂的票号要与这次 PR 有关。",
    "test_verify_ledger.py": "配方验证台账：每个配方文件一行、缺记录显示未记录。",
    "test_unittest_summary.py": "CI 的测试结果表格：列取错或漏算跳过数即红。",
    "test_release_assets.py": "下载页 REL 与 Release 附件的对账。",
    "test_release_meta.py": "发版校验清单从 Release 事实生成（tool/release_meta.py）：退出码、清单文本与写盘。",
    "test_followup.py": "复测队列核对与写回：报出标签与队列的差异。",
    "test_download_page_gitee.py": "国内下载走 Gitee：取包、核 SHA256、匿名下载回验。",
    "test_old_install_notice.py": "免安装版启动时提示旧名安装还在：文案与「同一版本只说一次」。",
    # 跨车型的行为域
    "test_huawei_channels.py": "华为渠道页的脱敏离线回归：已观察页面，不连手机。",
    "test_issue_regressions.py": "社区反馈回归：模拟页面与系统回读，不以 UI 状态代替执行结果。",
    "test_regressions.py": "设备无关的回归：输入、页面识别、开关保护与打包入口。",
    "test_release_regressions.py": "发布回归：横屏、部分失败、通知默认选择与发布资源边界。",
    "test_feedback_safety.py": "用户反馈里的安全项：无障碍排查只读、通知保护与旧清单还原。",
    "test_phone_host.py": "手机版宿主的说法：没有电脑和数据线时该怎么说，以及唯一的控制流例外（不写插电常亮）。",
}

# 存量票号文件，逐条记着并到哪个文件。只许降：`PENDING_CAP` 冻在当前条数，新增一条即超线。
# 目标可以是已登记的锚点，也可以是一份按机型规则豁免的脚本测试。
PENDING = {
    "test_adapt_assistant.py": "test_adapt_cli.py",
    "test_adapt_survey_690.py": "test_adapt_cli.py",
    "test_app_state_races_662.py": "test_job.py",
    "test_baidu_rows_android.py": "test_download_page_gitee.py",
    "test_bottom_tab_305.py": "test_phone_navigator.py",
    "test_bottom_tab_386.py": "test_phone_navigator.py",
    "test_browser_menu_753.py": "test_phone_dismisser.py",
    "test_community_1027.py": "test_issue_regressions.py",
    "test_dismiss_378.py": "test_phone_dismisser.py",
    "test_error_logs_1028.py": "test_issue_regressions.py",
    "test_exec_races_452.py": "test_job.py",
    "test_gear_landing_575.py": "test_phone_navigator.py",
    "test_phone_host_747.py": "test_phone_host.py",
    "test_recipe_verification_1124.py": "test_verify_ledger.py",
    "test_reference_by_version.py": "test_recipe_variants.py",
    "test_reports_026.py": "test_issue_regressions.py",
    "test_reports_1029.py": "test_issue_regressions.py",
    "test_retry_638.py": "test_job.py",
    "test_setting_search_exit_639.py": "test_phone_settings_search.py",
    "test_settings_page_960.py": "test_phone_settings_search.py",
    "test_vocab_gaps_690.py": "test_vocab.py",
}

# 字面量，不用 `len(PENDING)`：那样上限会跟着名单一起涨，「新增一条即红」就成了空转。
# 每并掉一条就把这个数减一；要加必须说明为什么（评审看得见）。
PENDING_CAP = 21

TEST_FILE = re.compile(r"^test_[A-Za-z0-9_]+\.py$")
# 文件名尾部的票号 / 日期：`test_xxx_1234`、`test_xxx_2026_11_12`、`test_xxx_2026-11-12`
TICKET_TAIL = re.compile(r"(_\d{3,4}|_\d{4}[-_]\d{2}[-_]\d{2})$")


def _normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def recipe_tokens(root):
    """机型标识：(品牌段集合, 型号段集合, 所有脚本正文的归一化串)。

    品牌段只够家族级测试用（`test_honor_recipe.py`）；型号段（`rmx3700` / `v2547da`）与正文里
    的市场名（`Redmi K70`）才让专属测试合规——后者是脚本注释里写着的别名，没有别名表。
    """
    recipes = root / "recipes"
    if not recipes.is_dir():
        return frozenset(), frozenset(), ""
    brands, models, texts = set(), set(), []
    for folder in sorted(p for p in recipes.iterdir() if p.is_dir()):
        brand, _, model = folder.name.partition("-")
        brands.add(_normalize(brand))
        if model:
            models.add(_normalize(model))
        for script in sorted(folder.glob("recipe*.py")):
            texts.append(script.read_text(encoding="utf-8", errors="replace"))
    return frozenset(brands), frozenset(models), _normalize(" ".join(texts))


def base_of(name):
    """去掉 `test_` 前缀、`.py` 后缀、`_recipe` 后缀与尾部票号，再归一化。"""
    stem = name[len("test_"):-len(".py")] if name.startswith("test_") else name
    if stem.endswith("_recipe"):
        stem = stem[:-len("_recipe")]
    while TICKET_TAIL.search(stem):
        stem = TICKET_TAIL.sub("", stem)
    return _normalize(stem)


def recipe_owned(name, brands, models, recipe_text):
    """这个文件名点名了一份真实的机型脚本？是则不必登记（按脚本目录命名即自动合规）。

    四档，从严到松：整串等于品牌段（家族级测试）；整串与某型号段互为子串（`oppoplp120search`
    含 `plp120`）；带三位以上数字串且该串是某型号段的一部分（`phk110android15` 的 `110`）；
    带数字且整串出现在某份脚本正文里（`test_k70_recipe` 对 `Redmi K70`）。

    光有品牌段不够：`test_vivo_chan_page` 只是用 vivo 的页面样本测渠道页，它没有点名任何
    一份脚本，所以仍要落到锚点。普通英文单词（`row`、`wait`）也因为「必须带数字」而被挡住。
    """
    base = base_of(name)
    if len(base) < 3:
        return False
    if base in brands:
        return True
    if any(model in base or base in model for model in models):
        return True
    if any(digit in model for digit in re.findall(r"\d{3,}", base) for model in models):
        return True
    for brand in brands:
        if base.startswith(brand):
            tail = base[len(brand):]
            if len(tail) >= 3 and any(tail in model for model in models):
                return True
    return any(ch.isdigit() for ch in base) and base in recipe_text


def suggest(name, anchors):
    """未登记的新文件该落到哪儿：按文件名给出最近的两个候选项。"""
    close = difflib.get_close_matches(name, sorted(anchors), n=2, cutoff=0.0)
    return "、".join(close) if close else "锚点清单里没有相近的名字"


def violations(root, anchors=None, pending=None, cap=None):
    """对给定根目录求值，返回违规描述；每条说清哪里不对、下一步该做什么。

    `anchors` / `pending` / `cap` 只为构造反例而可注入，默认取本文件的登记。
    """
    anchors = ANCHORS if anchors is None else anchors
    pending = PENDING if pending is None else pending
    cap = PENDING_CAP if cap is None else cap
    tests = root / "tests"
    present = ({p.name for p in tests.iterdir() if p.is_file() and TEST_FILE.match(p.name)}
               if tests.is_dir() else set())
    brands, models, recipe_text = recipe_tokens(root)
    found = []

    if len(pending) > cap:
        found.append(f"「待归并」名单 {len(pending)} 条，超过冻结上限 {cap}；只能缩不能长"
                     "（先把一条并进锚点，别往名单里塞新的）")
    both = sorted(set(anchors) & set(pending))
    if both:
        found.append("同一个文件既登记为锚点又在待归并名单里：" + "、".join(both))
    for name in sorted(anchors):
        if name not in present:
            found.append(f"锚点 {name} 在文件树里不存在；删掉登记或恢复文件")
    for name, target in sorted(pending.items()):
        if name not in present:
            found.append(f"待归并的 {name} 在文件树里不存在；它多半已经并掉了，从名单里删掉")
        if target not in present:
            found.append(f"{name} 的归并目标 {target} 不存在")
    registered = set(anchors) | set(pending)
    for name in sorted(present - registered):
        if recipe_owned(name, brands, models, recipe_text):
            continue
        found.append(f"{name} 没有登记锚点。新增用例要落进已声明的锚点（相近的："
                     f"{suggest(name, anchors)}）；确实要新开一个的话，在 ANCHORS 与 "
                     "docs/agents/test-anchors.md 里同时登记并写一句 why")
    return found


def main(argv=()):
    """`python3 tool/test_anchors.py`：跑一遍真实仓库，列出每一处违规。

    退出码：0 全绿；1 有违规；2 参数不合规（这个脚本没有参数）。
    """
    if argv:
        print(f"不认识的参数 {' '.join(argv)}；这个脚本没有参数", file=sys.stderr)
        return 2
    found = violations(Path(__file__).resolve().parents[1])
    if not found:
        print(f"{len(ANCHORS)} 个锚点、{len(PENDING)} 条待归并，全部合规。")
        return 0
    print("\n".join(found))
    print(f"{len(found)} 处违规。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
