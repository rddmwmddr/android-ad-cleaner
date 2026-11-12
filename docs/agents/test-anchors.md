# 测试文件的锚点登记

`tests/` 下的每个 `test_*.py` 只有两种合法归属：一个已声明的**锚点**，或某份机型脚本的**专用测试**。两者之外的新文件即红。

守卫是 [tool/test_anchors.py](../../tool/test_anchors.py) 的 `violations(root)`：对给定根目录求值的纯函数，反例用临时目录构造，不依赖真实仓库状态。[tests/test_test_collection.py](../../tests/test_test_collection.py) 在回归里代跑它，本地也可以 `python3 tool/test_anchors.py` 直接跑一遍（退出码 0 全绿、1 有违规）。

## 两种归属

**锚点**：登记在下面的 `## 锚点登记` 表与 `tool/test_anchors.py` 的 `ANCHORS` 里，两边逐字对拍——改一处漏掉另一处即红。每个锚点带一句 why，说的是这个文件在守什么；半年后判断「这个文件该不该留」靠的就是它。

**机型脚本的专用测试**：文件名点名了 `recipes/` 下的某份脚本就自动合规，不逐个登记。点名的形式有三种：目录名的品牌段（`test_honor_recipe.py`）、型号段（`test_rmx3888_recipe.py`）、或脚本头注里的市场名（`test_k70_recipe.py`，对应 `recipes/redmi-23113RKC6C`）。给新机型写脚本时，按脚本目录给测试文件命名即可。

## 新增用例往哪儿放

先找被测的对象：某个 `tool/` 模块、`Phone` 的门面或某个阶段、一条已经登记的行为域——落进它对应的锚点文件。没有对应的，再问「这是不是一份机型脚本的专用测试」，是就按脚本命名。两者都不是时才新开锚点，两处同时登记并写 why。

票号不消失：并进锚点时，把票号写进用例 docstring 的首行，仍然可以 `grep`；关票时把用例位置写进票，两条合起来就是从票到用例、从用例到票的完整引用。

报红文案会按文件名给出最近的两个锚点作为候选，但那只是提示，不是建议——「这条用例属于门面还是某个阶段」仍是人的判断。

## 已知漏口

豁免判据看的是文件名：一个文件名如果恰好带着机型词（`test_k70_1234.py`），会被当成机型测试放过去。那种文件本来多半也确实是该机型的专用测试，代价可以接受。新写机型测试时按脚本目录命名、不挂票号：票号写在 docstring 首行，文件名里读不出它守的是哪份脚本（`test_honor_cle_an00_671.py` → `test_honor_cle_an00.py`）。

反过来，改名去掉了机型词、又没登记的文件会红——这是对的，它此时已经说不出自己守的是哪份脚本了。

豁免只看文件名与 `recipes/` 的名字和正文，不读那个测试文件的内容：名字里只有品牌（`test_vivo_chan_page.py`）不算点名任何一份脚本，仍要落到锚点；品牌加型号片段（`test_honor_wkl_recipe.py` 的 `wkl`）才算。

守卫只扫 `tests/` 顶层。`tests/` 下将来若出现子目录，里面的 `test_*.py` 会被 `discover` 收到却不受这条规则约束——目前没有，出现时要先把守卫改成递归再放进去。

## 锚点登记

| 文件 | 为什么 |
|---|---|
| `test_adb_link.py` | 手机连接：adb 在哪、命令服务断开 / 读屏超时 / 后台屏没了三种结局怎么判、读屏探测在哪找。 |
| `test_row.py` | 「开关所属的那一行」的唯一定义：结构定界、几何分带、同名去重与自绘开关去重。 |
| `test_wait.py` | 「等到认得出」：超时、稳定、变化、受阻四个判据，外加等机主解锁。 |
| `test_entries.py` | 入口速查表与它怎么被用：每条入口有出处、文档同源、reach() 按直达与搜索回退，以及各品牌脚本进具体入口（齿轮、直达、浏览器 / 主题 / 商店 / 负一屏）。 |
| `test_vocab.py` | 品牌词库：词条有出处、键与入口速查相同、同页保留项只在那一页成立，以及 gaps 查漏。 |
| `test_events.py` | 引擎事件的词表与解析：六个 kind、固定前缀、坏行当没有。 |
| `test_engine_events.py` | 引擎侧在语义发生地发事件，人话逐字不变。 |
| `test_client_events.py` | 客户端只认引擎事件：事件行不进日志、人话本身不改状态。 |
| `test_summary.py` | 结果摘要的唯一定义：一段 tail 怎么说成一句话，两个宿主与两条链路说同一句。 |
| `test_coverage_note.py` | 结果页验证档位提示的唯一定义：说不说的判据、按宿主分叉的措辞，与档位词表的对应。 |
| `test_channel_classification.py` | 渠道判定：哪些渠道算营销、受保护、默认不勾，扫描因此列出谁、排除谁。 |
| `test_channel_outcomes.py` | 渠道批处理的结局记账与上报：一项的结局是值，怎么记、怎么报由几张表定。 |
| `test_channel_page.py` | 渠道页：从哪条路走进去、认出的是不是渠道页、从哪一行拿开关。 |
| `test_phone_facade.py` | Phone 门面 + 两个基座 + 五个阶段的对外契约。 |
| `test_phone_base.py` | 两个基座可以各自独立构造，不必造整台 Phone。 |
| `test_phone_sessions.py` | 三个跨阶段会话对象，门面用显式属性转发过去。 |
| `test_phone_toggler.py` | 拨动阶段：这一页该关的开关真的被关掉，含确认框判定与等待、页顶复位与残留提示。 |
| `test_phone_navigator.py` | 导航阶段的对外契约：go / tab / 入口与落点确认，含底部标签带内三层匹配与齿轮点完的落点校验。 |
| `test_phone_settings_search.py` | 设置搜索阶段：对外契约、搜索失败后的退场，以及设置页签名认 Setting 与 Preference 两族。 |
| `test_phone_dismisser.py` | 弹窗与推广位阶段：词表只有一份，推广位点了要退回；菜单的返回键与设置页里的说明行都不算弹窗 ✕。 |
| `test_phone_launcher.py` | 启动与落点阶段：前台归属、抢夺者现场与落点校验。 |
| `test_phone_interface.py` | Phone 的接口面：读屏策略、探路包名过滤、安全模式与 adapter 名字。 |
| `test_switch_plan.py` | plan_switches() 的策略面：这一页该拨哪些开关，与点击循环无关。 |
| `test_off_readback.py` | readback() 与 pick_retry_rows()：回读结局与该补点哪一行。 |
| `test_off_title_fallback.py` | 只认行标题的页面：点开关本体不动时 off() 回退到点标题。 |
| `test_main_switch_bar.py` | 渠道页的 main_switch_bar：外层容器里包着真开关，不能按颜色当自绘开关。 |
| `test_ui_session.py` | 读屏服务占用、失败清理、跨进程互斥与失败后的收尾。 |
| `test_never_suspend.py` | NEVER 保护集：挂了会坏功能的包，整批拒绝、不落一条命令到手机。 |
| `test_recipe_kit.py` | 引擎注入的脚本前导：段包装、跳过出口、失败台账、锁屏中止、安全模式整页关闭与失败现场。 |
| `test_recipe_loader.py` | 机型脚本只有一个装载入口，测试不许自己 exec 一份脚本。 |
| `test_recipe_meta_module.py` | 配方元数据住中立模块：非 CLI 代码 import 它不背 CLI 副作用。 |
| `test_recipe_variants.py` | 同一型号按系统版本选脚本变体、变体要进安装包，以及没有本型号脚本时参考脚本按录制版本在同族里挑。 |
| `test_recipe_setting_checked.py` | 机型脚本必须消费 p.setting() 的返回值，不能空跑还记成功。 |
| `test_recipe_preamble_migration.py` | 机型脚本不再自带前导：结构守卫与每份脚本的行为守卫。 |
| `test_recipe_nav.py` | 公共导航的注入面：前导调用它、实现从执行作用域取前导名字、脚本不留逐字副本，以及调用序列对拍驱动自己管基线 worktree。 |
| `test_recipe_steps.py` | 段体的注入面：前导调用它、实现从执行作用域取前导名字与模块常量、脚本不留逐字副本，以及事实层两张表的合并。 |
| `test_recipe_source.py` | 脚本事实层：实参按语法切分、形参回填与读不出态、Intent 三种包名写法，以及语法错直接抛。 |
| `test_backups.py` | 备份目录的命名、扫描与 <型号>-gui 兜底。 |
| `test_captures.py` | 失败现场落盘：两处留现场写原文、没目录不写、归档名与体积报数。 |
| `test_error_report.py` | 错误上报：内容脱敏、预览与发送一致、限频、安装编号与服务器回应。 |
| `test_updates.py` | 应用内更新：真实字节下载与状态迁移，网络与安装由边界替身接管。 |
| `test_update_install.py` | 在临时目录里真正换文件：回滚、保留卸载器与新进程健康回执。 |
| `test_win_preflight.py` | Windows 启动失败归因：缺 WebView2、MOTW、托管 dll 被判远程。 |
| `test_win_dotnet_config.py` | 随包分发的 <exe>.config 让包内托管 dll 不被判成网络位置。 |
| `test_hdc_fetch.py` | HDC 只在构建期下载、按钉死的 SHA-256 校验并解包。 |
| `test_hdc_lookup.py` | 找 hdc 的候选顺序，五档只有这一份。 |
| `test_packaging_entry.py` | 打包入口指向的文件存在、能 import、并给出 main。 |
| `test_entrypoint_refs.py` | 非测试入口对 gui.app 的引用得像真的一样存在。 |
| `test_source_text.py` | 源码文本的两条机械规则：不写裸零宽字符、基线钉提交 SHA。 |
| `test_stdio.py` | 标准流 UTF-8 的唯一出口：尽力而为、失败静默。 |
| `test_subprocess_text_mode.py` | 子进程的文本模式必须写清解码方式。 |
| `test_runtime_symbols.py` | 跨运行时符号：tool/ 在电脑与手机版跑两套依赖，静态引用的名字要真的存在。 |
| `test_declared_fields.py` | 构造处声明过的字段要直接读，不再 getattr 兜底。 |
| `test_test_collection.py` | 用例只在 tests/ 下定义，且每个测试文件都落到已声明的锚点。 |
| `test_rules_guards.py` | 规则守卫：文档内容、注册表、引擎结构与流程条目各自的机械判据。 |
| `test_rules_registry.py` | 规则注册表的四条不变式，锚点与登记双向一致。 |
| `test_doc_consistency.py` | 文档与单一来源一致：ADR 字段表、品牌连点表、共享样式与教程截图。 |
| `test_web_client.py` | 前端用例的代跑与守卫：tests/js/ 的 jsdom 用例由它在 unittest 里跑。 |
| `test_fixtures.py` | 夹具本身的行为：样本、假时钟、时间轴与假 Phone。 |
| `test_compare_phone_state.py` | 对拍驱动自己管基线 worktree：未知 SHA 报错且不留下 worktree。 |
| `test_android_bundle.py` | APK 里那批 gui 文件必须覆盖 gui/app.py 的导入期依赖。 |
| `test_android_shim.py` | 手机版替换层：不连手机，替换掉执行通道与读屏。 |
| `test_android_view.py` | 手机版界面的判断：结果怎么说、什么时候挡住开始、反馈网址怎么截。 |
| `test_android_version.py` | 单键 getprop 读不到版本时按分区属性回退。 |
| `test_android_smoke.py` | 真机冒烟：出包、装机、启动、执行、还原三段各自出结论。 |
| `test_api_structure.py` | 窗口桥契约与客户端三块的责任边界。 |
| `test_gui_import.py` | import gui.app 不许有副作用：不建目录、不改 sys.path、不加载 tool/。 |
| `test_job.py` | 一次执行的状态收成 Job，poll 只读锁内快照。 |
| `test_job_races.py` | 一次执行的发布点竞态：停止落在启动与登记之间仍要杀进程、running=false 的快照已带收尾行、旧执行的收尾行不串进新 Job。 |
| `test_dispatcher_exclusion.py` | 客户端调度器的互斥：还原、安装更新、执行与读屏检查谁在等谁，锁在别人手里时立刻回一句；停止与暂停必须等锁，判断落在临界区内。 |
| `test_result_retry.py` | 结果页重试：哪一档步骤可重试、广告开关步只重跑引擎报的段、多轮结果按 kind 就地合并。 |
| `test_harmony_bridge.py` | 鸿蒙窗口桥只转发，状态与构造逻辑不落在 Api 上。 |
| `test_harmony_client.py` | 鸿蒙接入后的选机、互斥、持久化、停止与旧数据兼容。 |
| `test_harmony_engine.py` | 桌面引擎的离线用例：合成的界面树与假手机。 |
| `test_harmony_vocab.py` | 鸿蒙词库守卫。 |
| `test_plan.py` | 一次执行跑哪些步骤：Plan 规格的八个键与往返，以及按规格排出的任务、未执行行与重试轮。 |
| `test_run_commands.py` | run.py 的命令接口与它产出的诊断：退出码只在出口、多余往返的守卫、「只是搬家」的对拍，以及设备名与收尾快照。 |
| `test_adapt_cli.py` | adapt.py 三条子命令对外的退出码与两路输出，survey 试入口的三种结局与 `-s S adapt` 的转发，以及 TSV 解析、草稿生成、自检报告与探路导航。 |
| `test_claim.py` | 开工认领：一条命令写认领评论并摘待办标签，仲裁只看票下评论。 |
| `test_triage_audit.py` | triage 四条集合判据，登记表与脚本常量逐项对拍。 |
| `test_stale_scan.py` | needs-info 停摆机制：判定与阈值、写入与幂等。 |
| `test_conventional.py` | 提交信息的 Conventional Commits 校验。 |
| `test_dco.py` | 每个非 merge 提交都带与作者邮箱一致的 signoff。 |
| `test_ticket_ref.py` | 分支名与 PR 正文指到同一张票。 |
| `test_comment_tickets.py` | 新写的行里挂的票号要与这次 PR 有关。 |
| `test_verify_ledger.py` | 配方验证台账：每个配方文件一行、缺记录显示未记录，以及 status-json 带出的覆盖度、证据来源与验证日期。 |
| `test_unittest_summary.py` | CI 的测试结果表格：列取错或漏算跳过数即红。 |
| `test_release_assets.py` | 下载页 REL 与 Release 附件的对账。 |
| `test_release_meta.py` | 发版校验清单从 Release 事实生成（tool/release_meta.py）：退出码、清单文本与写盘。 |
| `test_followup.py` | 复测队列核对与写回：报出标签与队列的差异。 |
| `test_download_page_gitee.py` | 国内下载走 Gitee：取包、核 SHA256、匿名下载回验。 |
| `test_download_page_rows.py` | 下载页与网盘说明的行：手机版 APK 单独成行、说明里写「不用连电脑」并带校验值，页面 id 写错要在上传前停下。 |
| `test_old_install_notice.py` | 免安装版启动时提示旧名安装还在：文案与「同一版本只说一次」。 |
| `test_huawei_channels.py` | 华为渠道页的脱敏离线回归：已观察页面，不连手机。 |
| `test_page_and_link_regressions.py` | 一期社区反馈引出的跨模块回归：渠道页归属与仿冒、内联开关、多用户解析、点击被拒、adb 掉线与 USB 诊断。 |
| `test_lock_and_disconnect_regressions.py` | 上报日志归类的跨模块回归：锁屏判据与等机主解锁、灰态渠道、断线不带堆栈、脱敏与参考脚本。 |
| `test_layout_and_verdict_regressions.py` | 发布当天上报的回归：卡片布局差异、vivo 旧页与直达、失败判定、停止不算失败、暂停与空报告。 |
| `test_tap_notice_regressions.py` | 发布后一夜上报扫出的回归：点击与确认落点、焦点回退、通知页读取、adb 镜像与提示音、vivo 慢过渡。 |
| `test_issue_regressions.py` | 社区反馈回归：模拟页面与系统回读，不以 UI 状态代替执行结果。 |
| `test_regressions.py` | 设备无关的回归：输入、页面识别、开关保护与打包入口。 |
| `test_release_regressions.py` | 发布回归：横屏、部分失败、通知默认选择与发布资源边界。 |
| `test_feedback_safety.py` | 用户反馈里的安全项：无障碍排查只读、通知保护与旧清单还原。 |
| `test_phone_host.py` | 手机版宿主的说法：没有电脑和数据线时该怎么说、界面与诊断里残留的桌面说法，以及唯一的控制流例外（不写插电常亮）。 |
