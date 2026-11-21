"""tests/ 的锚点登记（rule:dev.tests.anchor-registry）：每个测试文件要么是已声明的锚点，
要么是某份机型脚本的专用测试（文件名点名了它）。两者之外的新文件即红。

七个按批次组织的回归文件另有行为域归属：类里每条用例的 owner 是类上声明的 `DOMAIN`，
`DOMAIN_FILES` 之外的文件不该声明 `DOMAIN`。

每个锚点还带一个可选的断言数上限（软体量预算）：超限不算违规、不阻断合并，只在 CI
summary 里各列一行（量具与渲染在 devtools/unittest_summary.py）。上限只许降。

判据正文在 docs/agents/test-anchors.md，本文件是它的机械镜像：`ANCHORS` 与文档的
`## 锚点登记` 表、`DOMAINS` 与 `## 行为域` 表都由 tests/test_test_collection.py 逐项对拍。

`violations(root)` / `domain_violations(root)` 对给定根目录求值，不依赖真实仓库状态——反例用临时目录构造。
"""
import ast
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tool"))   # stdio 留在引擎目录

from stdio import use_utf8_console

use_utf8_console()

# 与 docs/agents/test-anchors.md 的 `## 锚点登记` 表逐项相同（文件名、理由与断言数上限都逐字），
# tests/test_test_collection.py 守着。理由里不要出现竖线，表会散架。
#
# 值是 `(理由, 断言数上限)`：上限是本文件初始实施时的实测值，此后只许降；`None` 表示不设预算。
# 超限不算违规、不阻断合并，只在 CI summary 里可见（见 docs/agents/test-anchors.md 的「体量预算」）。
ANCHORS = {
    # 引擎与读屏
    "test_adb_link.py": ("手机连接：adb 在哪、命令服务断开 / 读屏超时 / 后台屏没了三种结局怎么判、读屏探测在哪找。", 176),
    "test_row.py": ("「开关所属的那一行」的唯一定义：结构定界、几何分带、同名去重与自绘开关去重。", 67),
    "test_wait.py": ("「等到认得出」：超时、稳定、变化、受阻四个判据，外加等机主解锁。", 47),
    "test_entries.py": ("入口速查表与它怎么被用：每条入口有出处、文档同源、reach() 按直达与搜索回退，以及各品牌脚本进具体入口（齿轮、直达、浏览器 / 主题 / 商店 / 负一屏）。", 442),
    "test_vocab.py": ("品牌词库：词条有出处、键与入口速查相同、同页保留项只在那一页成立，以及 gaps 查漏。", 156),
    "test_events.py": ("引擎事件的词表与解析：六个 kind、固定前缀、坏行当没有，写出的行中文逐字、逐行 flush。", 18),
    "test_engine_events.py": ("引擎侧在语义发生地发事件，人话逐字不变。", 36),
    "test_client_events.py": ("客户端只认引擎事件：事件行不进日志、人话本身不改状态。", 35),
    "test_summary.py": ("结果摘要的唯一定义：一段 tail 怎么说成一句话，两个宿主与两条链路说同一句。", 16),
    "test_coverage_note.py": ("结果页验证档位提示的唯一定义：说不说的判据、按宿主分叉的措辞（整句逐字），与档位词表的对应。", 15),
    "test_channel_classification.py": ("渠道判定：哪些渠道算营销、受保护、默认不勾，扫描因此列出谁、排除谁。", 81),
    "test_channel_outcomes.py": ("渠道批处理的结局记账与上报：一项的结局是值，怎么记、怎么报由几张表定。", 217),
    "test_channel_page.py": ("渠道页：从哪条路走进去、认出的是不是渠道页、从哪一行拿开关。", 152),
    "test_channel_snapshot.py": ("屏幕快照 / 通知清单 / 意图 / 进度四个值类型：构造、JSON 往返，以及每个意图种类只经基座唯一执行点落地。", 60),
    "test_channel_decide.py": ("渠道页的认页决策是屏幕快照上的纯函数：认出哪一行、卡在哪一阶段、哪些行可拨。", 61),
    "test_channel_arrive.py": ("渠道页的到达决策：六条路线与三条失败路径各自该发哪个意图、结局是什么。", 31),
    "test_channel_toggle.py": ("渠道拨动的决定：能不能点、重试还是放弃、点后消失与灰态各自算什么。", 21),
    "test_channel_batch.py": ("渠道批处理策略：清单→队列的预筛、两趟门槛、重试挑行与收尾复查豁免，逐条结局用纯数据证明。", 43),
    # Phone 门面、两个基座与七个阶段
    "test_phone_facade.py": ("Phone 门面 + 两个基座 + 五个阶段的对外契约。", 66),
    "test_phone_base.py": ("两个基座可以各自独立构造，不必造整台 Phone。", 22),
    "test_phone_sessions.py": ("三个跨阶段会话对象，门面用显式属性转发过去。", 12),
    "test_phone_toggler.py": ("拨动阶段：这一页该关的开关真的被关掉，含确认框判定与等待、页顶复位与残留提示；`drive()` 装的假钟要还原。", 82),
    "test_phone_navigator.py": ("导航阶段的对外契约：go / tab / 入口与落点确认，含底部标签带内三层匹配与齿轮点完的落点校验。", 93),
    "test_phone_settings_search.py": ("设置搜索阶段：对外契约、搜索失败后的退场，以及设置页签名认 Setting 与 Preference 两族。", 35),
    "test_phone_dismisser.py": ("弹窗与推广位阶段：词表只有一份，推广位点了要退回；菜单的返回键与设置页里的说明行都不算弹窗 ✕。", 79),
    "test_phone_launcher.py": ("启动与落点阶段：前台归属、抢夺者现场与落点校验。", 47),
    "test_phone_interface.py": ("Phone 的接口面：读屏策略、探路包名过滤、安全模式与 adapter 名字。", 173),
    # 拨动与导航的策略面
    "test_switch_plan.py": ("plan_switches() 的策略面：这一页该拨哪些开关，与点击循环无关。", 47),
    "test_off_readback.py": ("readback() 与 pick_retry_rows()：回读结局与该补点哪一行。", 21),
    "test_off_title_fallback.py": ("只认行标题的页面：点开关本体不动时 off() 回退到点标题。", 24),
    "test_main_switch_bar.py": ("渠道页的 main_switch_bar：外层容器里包着真开关，不能按颜色当自绘开关。", 1),
    "test_ui_session.py": ("读屏服务占用、失败清理、跨进程互斥与失败后的收尾。", 39),
    "test_never_suspend.py": ("NEVER 保护集：挂了会坏功能的包，整批拒绝、不落一条命令到手机。", 13),
    # 机型脚本的基础设施
    "test_recipe_loader.py": ("机型脚本只有一个装载入口，测试不许自己 exec 一份脚本。", 8),
    "test_recipe_meta_module.py": ("配方元数据住中立模块：import 不背 CLI 副作用，脚本枚举跳过非目录项，头部三段缺省是空值（段名缺 name 也是空串）。", 10),
    "test_recipe_variants.py": ("同一型号按系统版本选脚本变体、变体要进安装包，型号目录里哪一份算主脚本，以及没有本型号脚本时参考脚本按录制版本在同族里挑、怎么比对版本。", 101),
    "test_recipe_setting_checked.py": ("机型脚本必须消费 p.setting() 的返回值，不能空跑还记成功。", 35),
    "test_recipe_nav.py": ("机型库的拆分守卫（例外 `.py` 的同名助手必须升格进 `recipe_lib`；`shared.py` 的实现必须被 ≥2 个家族使用）、名字表 owner 与三个兼容壳的一致守卫（`SurfaceTests`），以及调用序列对拍驱动自己管基线 worktree。", 22),
    "test_recipe_source.py": ("脚本事实层：实参按语法切分、形参回填与读不出态、页面标签与导入面、Intent 三种包名写法、语法错直接抛，以及库实现下扫与两份进程内缓存。", 99),
    "test_catalog.py": ("catalog 内核：页面树数据经唯一装载入口跑出与旧脚本逐条相同的调用序列、装载期拒绝非法数据与写错的点名（报错原文与边界值也逐字）、only 两态与 page-wide 全关，以及事实层降级出的每一行源码。", 241),
    "test_xiaomi_store_recipe.py": ("小米各机型的应用商店段：入口形态（回到首页 / 直达偏好页 / 底栏标签 / 顶栏齿轮）与收尾次序各一条，入口成功的那条路快照走不到。", 64),
    "test_xiaomi_theme_recipe.py": ("小米主题两段：下半屏「我的」的判据、换页慢机型的签名等待，以及齿轮点不到那条出口——快照在这里只看得到一次 settle。", 22),
    "test_xiaomi_ads_recipe.py": ("小米系统广告五台机：直达不通退回菜单的两个出口、设置搜索搜不到的那条失败，以及「安全」标签的重试轮与切完再翻一次——快照在「隐私与安全」那一步就断了。", 57),
    # 客户端、打包、更新与平台
    "test_backups.py": ("备份目录的命名、扫描与 <型号>-gui 兜底。", 35),
    "test_captures.py": ("失败现场落盘：两处留现场写原文、没目录不写、归档名与体积报数。", 18),
    "test_error_report.py": ("错误上报：内容脱敏、预览与发送一致、限频、安装编号与服务器回应。", 75),
    "test_diagnostics.py": ("设备诊断文本的唯一定义：给定一份整理好的 state，整段输出逐字等于什么，含按分支的措辞与脱敏。", 35),
    "test_updates.py": ("应用内更新：真实字节下载与状态迁移，网络与安装由边界替身接管。", 227),
    "test_update_install.py": ("在临时目录里真正换文件：回滚、保留卸载器与新进程健康回执。", 286),
    "test_win_preflight.py": ("Windows 启动失败归因：缺 WebView2、MOTW、托管 dll 被判远程。", 77),
    "test_win_dotnet_config.py": ("随包分发的 <exe>.config 让包内托管 dll 不被判成网络位置。", 11),
    "test_hdc_fetch.py": ("HDC 只在构建期下载、按钉死的 SHA-256 校验并解包。", 33),
    "test_hdc_lookup.py": ("找 hdc 的候选顺序，五档只有这一份。", 5),
    "test_packaging_entry.py": ("打包入口指向的文件存在、能 import、并给出 main。", 48),
    "test_entrypoint_refs.py": ("非测试入口对 gui.app 的引用得像真的一样存在。", 4),
    "test_source_text.py": ("源码文本的两条机械规则：不写裸零宽字符、基线钉提交 SHA。", 2),
    "test_stdio.py": ("标准流 UTF-8 的唯一出口：尽力而为、失败静默。", 2),
    "test_subprocess_text_mode.py": ("子进程的文本模式必须写清解码方式。", 3),
    "test_runtime_symbols.py": ("跨运行时符号：tool/ 在电脑与手机版跑两套依赖，静态引用的名字要真的存在。", 2),
    "test_declared_fields.py": ("构造处声明过的字段要直接读，不再 getattr 兜底。", 1),
    # tests/ 自身的守卫
    "test_test_collection.py": ("用例只在 tests/ 下定义，每个测试文件都落到已声明的锚点，锚点的断言数上限在两处登记上逐字对拍，测试文件之间不许有逐字节相同的用例，也不许重写继承来的用例。", 37),
    "test_family.py": ("族容器本身：case id 快照、结构句柄、产出与缺口四件校验、必须附理由的快照更新入口，以及四个族对得上各自的快照。", 82),
    "test_glob_scan.py": ("发现式 glob 的反空转：发现集为空时与「全仓合规」不可区分，每个模式对真实仓库求值一次，0 份即红。", 24),
    "test_rules_guards.py": ("规则守卫：文档内容、注册表、引擎结构与流程条目各自的机械判据。", 61),
    "test_rules_registry.py": ("规则注册表的五条不变式，锚点与登记双向一致，`code:` 规则点名的符号只在一处定义。", 16),
    "test_doc_consistency.py": ("文档与单一来源一致：ADR 字段表、品牌连点表、共享样式与教程截图，以及四条「配置即判据」的规则与 pyproject / .coveragerc 对拍。", 112),
    "test_web_client.py": ("前端用例的代跑与守卫：tests/js/ 的 jsdom 用例由它在 unittest 里跑。", 8),
    "test_fixtures.py": ("夹具本身的行为：样本、假时钟、时间轴与假 Phone。", 27),
    "test_compare_phone_state.py": ("两个对拍驱动自己管基线 worktree：未知 SHA 报错且不留下 worktree，不指定基线时仍认手工备好的 tool 目录。", 3),
    "test_mutation_scope.py": ("模块 → 测试范围的映射：严格档名单与它不漂、每个目标都在仓库里、选择结果去重保序、摘掉的方法确实挂在被收集的文件上，副本的 src 是 tool、gui 与手机版替换层的镜像，改动面只挑映射表里的模块、表外的 gui 与手机版模块逐条报出来，summary 一节的结论与 pragma 计数，以及「无可变异节点」的判据。", 59),
    # 手机版与鸿蒙
    "test_android_bundle.py": ("APK 里那批 gui 文件必须覆盖 gui/app.py 的导入期依赖。", 11),
    "test_tool_package.py": ("tool/ 的出厂引擎与仓库工具链边界：两份冻结名单与文件系统全等、引擎不拖进工具链、打包清单不含 devtools/。", 12),
    "test_android_shim.py": ("手机版替换层：不连手机，替换掉执行通道与读屏。", 540),
    "test_android_view.py": ("手机版界面的判断：结果怎么说、什么时候挡住开始、反馈网址怎么截。", 220),
    "test_android_version.py": ("单键 getprop 读不到版本时按分区属性回退。", 7),
    "test_android_smoke.py": ("真机冒烟：出包、装机、启动、执行、还原三段各自出结论。", 208),
    "test_api_structure.py": ("窗口桥契约与客户端三块的责任边界。", 15),
    "test_gui_import.py": ("import gui.app 不许有副作用：不建目录、不改 sys.path、不加载 tool/；`gui/toolpath.py` 是那份惰性加载的唯一出口，configure 之前加载要报可读的错。", 9),
    "test_job.py": ("一次执行的状态收成 Job，poll 只读锁内快照。", 24),
    "test_job_races.py": ("一次执行的发布点竞态：停止落在启动与登记之间仍要杀进程、running=false 的快照已带收尾行、旧执行的收尾行不串进新 Job。", 8),
    "test_dispatcher_exclusion.py": ("客户端调度器的互斥：还原、安装更新、执行与读屏检查谁在等谁，锁在别人手里时立刻回一句；停止与暂停必须等锁，判断落在临界区内。", 20),
    "test_result_retry.py": ("结果页重试：哪一档步骤可重试、广告开关步只重跑引擎报的段、多轮结果按 kind 就地合并。", 56),
    "test_harmony_bridge.py": ("鸿蒙窗口桥只转发，状态与构造逻辑不落在 Api 上。", 9),
    "test_harmony_client.py": ("鸿蒙接入后的选机、互斥、持久化、停止与旧数据兼容。", 89),
    "test_harmony_engine.py": ("桌面引擎的离线用例：合成的界面树与假手机。", 48),
    "test_harmony_vocab.py": ("鸿蒙词库守卫。", 43),
    # 计划与命令
    "test_plan.py": ("一次执行跑哪些步骤：Plan 规格的八个键与往返，以及按规格排出的任务、未执行行与重试轮。", 98),
    "test_run_commands.py": ("run.py 的命令接口与它产出的诊断：退出码只在出口、多余往返的守卫、「只是搬家」的对拍，以及设备名与收尾快照。", 111),
    "test_adapt_cli.py": ("adapt.py 三条子命令对外的退出码与两路输出，survey 试入口的三种结局与 `-s S adapt` 的转发，以及 TSV 解析、草稿生成、自检报告与探路导航。", 167),
    "test_chan_cli_baseline.py": ("渠道引擎三个子命令的 CLI 输出基线：scan / off / on 的退出码、输出行与分支守卫。", 6),
    # 适配工具与仓库流程
    "test_gh.py": ("工具层共用的 gh 会话：失败取错误输出、为空退回标准输出，以及判 JSON 的三档报错。", 15),
    "test_claim.py": ("开工认领：一条命令写认领评论并摘待办标签，仲裁只看票下评论。", 90),
    "test_triage_audit.py": ("triage 四条集合判据，登记表与脚本常量逐项对拍。", 36),
    "test_stale_scan.py": ("needs-info 停摆机制：判定与阈值、写入与幂等。", 101),
    "test_conventional.py": ("提交信息的 Conventional Commits 校验。", 32),
    "test_dco.py": ("每个非 merge 提交都带与作者邮箱一致的 signoff。", 27),
    "test_ticket_ref.py": ("分支名与 PR 正文指到同一张票。", 28),
    "test_comment_tickets.py": ("新写的行里挂的票号要与这次 PR 有关。", 32),
    "test_verify_ledger.py": ("配方验证台账：每个配方文件一行、缺记录显示未记录，以及 status-json 带出的覆盖度、证据来源与验证日期。", 81),
    "test_unittest_summary.py": ("CI 的测试结果表格与锚点体量：列取错或漏算跳过数即红，断言按口径计数、超限各列一行。", 29),
    "test_release_assets.py": ("下载页 REL 与 Release 附件的对账。", 81),
    "test_release_meta.py": ("发版校验清单从 Release 事实生成（devtools/release_meta.py）：退出码、清单文本与写盘。", 100),
    "test_followup.py": ("复测队列核对与写回：报出标签与队列的差异。", 105),
    "test_download_page_gitee.py": ("国内下载走 Gitee：取包、核 SHA256、匿名下载回验。", 16),
    "test_download_page_rows.py": ("下载页与网盘说明的行：手机版 APK 单独成行、说明里写「不用连电脑」并带校验值，页面 id 写错要在上传前停下。", 23),
    "test_old_install_notice.py": ("免安装版启动时提示旧名安装还在：文案与「同一版本只说一次」。", 12),
    # 跨车型的行为域
    "test_huawei_channels.py": ("华为渠道页的脱敏离线回归：已观察页面，不连手机。", 71),
    "test_page_and_link_regressions.py": ("一期社区反馈汇集的设备无关回归：渠道页归属与仿冒、内联开关、多用户解析、点击被拒、adb 掉线与 USB 诊断；每条用例的 owner 是所在类声明的行为域（见「行为域」）。", 126),
    "test_lock_and_disconnect_regressions.py": ("上报日志分类汇集的设备无关回归：锁屏判据与等机主解锁、灰态渠道、断线不带堆栈、脱敏与参考脚本；每条用例的 owner 是所在类声明的行为域（见「行为域」）。", 71),
    "test_layout_and_verdict_regressions.py": ("发布当天上报汇集的设备无关回归：卡片布局差异、vivo 旧页与直达、失败判定、停止不算失败、暂停与空报告；每条用例的 owner 是所在类声明的行为域（见「行为域」）。", 86),
    "test_tap_notice_regressions.py": ("发布后一夜上报汇集的设备无关回归：点击与确认落点、焦点回退、通知页读取、adb 镜像与提示音、vivo 慢过渡；每条用例的 owner 是所在类声明的行为域（见「行为域」）。", 39),
    "test_issue_regressions.py": ("社区反馈汇集的设备无关回归：模拟页面与系统回读，不以 UI 状态代替执行结果；每条用例的 owner 是所在类声明的行为域（见「行为域」）。", 135),
    "test_regressions.py": ("跨批次汇集的设备无关回归：输入、页面识别、开关保护、启动落点与打包入口；每条用例的 owner 是所在类声明的行为域（见「行为域」）。", 106),
    "test_release_regressions.py": ("发布回归汇集的设备无关用例：横屏、部分失败、通知默认选择与发布资源边界；每条用例的 owner 是所在类声明的行为域（见「行为域」）。", 85),
    "test_feedback_safety.py": ("用户反馈里的安全项：无障碍排查只读、通知保护与旧清单还原。", 30),
    "test_phone_host.py": ("手机版宿主的说法：没有电脑和数据线时该怎么说、界面与诊断里残留的桌面说法，以及唯一的控制流例外（不写插电常亮）。", 67),
    "test_recipe_call_snapshots.py": ("机型脚本的调用序列快照：47 份 × present / absent 两场景与入库数据逐条比对，段名归属与空转守卫。更新规则见 docs/agents/recipe-snapshots.md。", 15),
    "test_recipe_audit.py": ("本机函数审计：只收模块级函数、四档归属（含声明式钩子）的优先级与判据信号，以及 check 与 status-json 报的「本机策略：N 个」。", 64),
    "test_recipe_strategies.py": ("家族库按脚本常量选走法（齿轮 / 浏览器设置 / 页面等待 / 开关读取 / 按名关闭 / 入口点击）与认不出的值当场报错。", 19),
}

# 七个按批次组织的回归文件：用例的 owner 是它所在类声明的行为域（见
# docs/agents/test-anchors.md 的「行为域」）。这份文件名清单只此一处。
DOMAIN_FILES = (
    "test_issue_regressions.py",
    "test_layout_and_verdict_regressions.py",
    "test_lock_and_disconnect_regressions.py",
    "test_page_and_link_regressions.py",
    "test_regressions.py",
    "test_release_regressions.py",
    "test_tap_notice_regressions.py",
)

# 与 docs/agents/test-anchors.md 的 `## 行为域` 表逐项相同（标识、顺序与说明都逐字），
# tests/test_test_collection.py 守着。说明里不要出现竖线，表会散架。
DOMAINS = {
    "channel": "渠道列表与渠道页：从清单和页面认出营销渠道、跳过系统锁定项、点击后页面变了没有，批处理遇变就停。",
    "connection": "手机连接：adb 在哪、命令服务断开 / 读屏超时 / 后台屏没了三种结局怎么判，包清单与断线后的收尾。",
    "startup": "启动与落点：前台归属、权限门、安全模式、脚本选择，以及启动后有没有离开目标应用。",
    "result": "结果页与暂停：一次执行怎么说成一句话、哪一档步骤可重试、暂停落在哪个安全点。",
    "packages": "包与快应用：AD 包与 msa 的挂起还原、chain3 原值写回、按品牌或 ROM 取包。",
    "navigation": "导航与弹窗：搜索框输入、图标入口、底部标签与返回，以及弹窗和推广位怎么退。",
    "switch": "开关本身：标题去重、状态后缀、自绘开关与单选框、极性、点按与确认框。",
    "device_state": "设备状态：锁屏与等解锁、焦点归属、常亮写回，以及灰态渠道不算失败。",
    "desktop": "桌面客户端与打包：USB 诊断、adb 镜像、剪贴板、更新提示，以及随包资产清单。",
    "backup": "备份还原：备份目录与包清单落盘、扫描失败保留原件、跨盘路径。",
}

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
    import entries
    # 目录是 `<家族>/<型号>`：品牌段从 FAMILY 的键取（oneplus / redmi / realme 等家族别名不在路径里），
    # 型号段取第二层的目录名。
    brands = {_normalize(brand) for brand in entries.FAMILY}
    models, texts = set(), []
    for family in sorted(p for p in recipes.iterdir() if p.is_dir()):
        for folder in sorted(p for p in family.iterdir() if p.is_dir()):
            models.add(_normalize(folder.name))
            # 页面树（`.toml`）的头注与同目录例外 `.py` 也写着市场名；只读 `recipe*.py` 会让
            # 转成数据的机型在锚点发现里静默消失（#1266）。
            sources = sorted(folder.glob("recipe*.py")) + sorted(folder.glob("*.toml")) \
                + sorted(path for path in folder.glob("*.py")
                         if not path.name.startswith("recipe"))
            for script in sources:
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


def violations(root, anchors=None):
    """对给定根目录求值，返回违规描述；每条说清哪里不对、下一步该做什么。

    `anchors` 只为构造反例而可注入，默认取本文件的登记。
    """
    anchors = ANCHORS if anchors is None else anchors
    tests = root / "tests"
    present = ({p.name for p in tests.iterdir() if p.is_file() and TEST_FILE.match(p.name)}
               if tests.is_dir() else set())
    brands, models, recipe_text = recipe_tokens(root)
    found = []

    for name in sorted(anchors):
        if name not in present:
            found.append(f"锚点 {name} 在文件树里不存在；删掉登记或恢复文件")
    for name in sorted(present - set(anchors)):
        if recipe_owned(name, brands, models, recipe_text):
            continue
        found.append(f"{name} 没有登记锚点。新增用例要落进已声明的锚点（相近的："
                     f"{suggest(name, anchors)}）；确实要新开一个的话，在 ANCHORS 与 "
                     "docs/agents/test-anchors.md 里同时登记，写一句 why 与断言数上限")
    return found


def _test_methods(cls):
    """类体里直接定义的用例方法；继承来的不算（域由声明它的那个类负责）。"""
    return [stmt for stmt in cls.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test_")]


def _domain_statement(cls):
    """类体里的 `DOMAIN = …` 赋值；没有则 None。"""
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "DOMAIN" for target in stmt.targets):
            return stmt
    return None


def domain_violations(root, domains=None):
    """对给定根目录求值七个回归文件的行为域归属；每条说清哪里不对、下一步该做什么。

    `domains` 只为构造反例而可注入，默认取本文件的词表。
    """
    domains = DOMAINS if domains is None else domains
    tests = root / "tests"
    if not tests.is_dir():
        return ["tests/ 目录不存在；行为域守卫没有可检查的对象"]
    present = {path.name for path in tests.iterdir() if path.is_file()}
    found = []

    for name in DOMAIN_FILES:
        if name not in present:
            found.append(f"{name} 不存在；七个按批次组织的回归文件缺一，行为域守卫会空转")
            continue
        tree = ast.parse((tests / name).read_text(encoding="utf-8"))
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test_"):
                found.append(f"{name}: 模块层的 def {stmt.name} 不属于任何类；挪进一个测试类，"
                             "并让该类声明 DOMAIN")
        for cls in (stmt for stmt in tree.body if isinstance(stmt, ast.ClassDef)):
            if not _test_methods(cls):
                continue
            declared = _domain_statement(cls)
            if declared is None:
                found.append(f"{name}: 类 {cls.name} 没有声明 DOMAIN；在类里加一行 "
                             "DOMAIN = \"<域名>\"，词表见 docs/agents/test-anchors.md 的「行为域」")
                continue
            value = declared.value.value if isinstance(declared.value, ast.Constant) else None
            if value not in domains:
                found.append(f"{name}: 类 {cls.name} 的 DOMAIN = {value!r} 不在词表里；"
                             f"从 {', '.join(domains)} 里选一个")

    for path in sorted(path for path in tests.iterdir() if path.is_file() and TEST_FILE.match(path.name)):
        if path.name in DOMAIN_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (stmt for stmt in tree.body if isinstance(stmt, ast.ClassDef)):
            if _domain_statement(cls) is not None:
                found.append(f"{path.name}: 类 {cls.name} 声明了 DOMAIN，但只有七个按批次组织的回归文件"
                             "按行为域归属；新文件落进已有的锚点，不要自造域")
    return found


def main(argv=()):
    """`python3 devtools/test_anchors.py`：跑一遍真实仓库，列出每一处违规。

    退出码：0 全绿；1 有违规；2 参数不合规（这个脚本没有参数）。
    """
    if argv:
        print(f"不认识的参数 {' '.join(argv)}；这个脚本没有参数", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    found = violations(root) + domain_violations(root)
    if not found:
        print(f"{len(ANCHORS)} 个锚点、{len(DOMAINS)} 个行为域，全部合规。")
        return 0
    print("\n".join(found))
    print(f"{len(found)} 处违规。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
