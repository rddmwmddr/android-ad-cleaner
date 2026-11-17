# 架构总览

这份文件只回答三件事：**东西在哪、边界在哪、谁跨过边界说话。**
机制与取舍不在这里，每处结论都指向 `docs/adr/` 里的一份决定。

## 一、宿主与进程

| 谁 | 在哪跑 | 引擎怎么跑 |
|---|---|---|
| 桌面宿主 · 安卓客户端 | `gui/launch.py` → `gui/app.py` 的 `Api` | 安卓路径不跑引擎：排步骤、起子进程、收日志、上报错误、只读的 adb 查询；不点按、不改开关 |
| 桌面宿主 · 安卓引擎子进程 | `tool/run.py`，客户端为**每一步**起一个 | 读屏、点按、跑机型脚本 / 渠道 / 快应用 / 挂起；不知道这一步之外的事，不写界面、不上报 |
| 手机宿主 · 单进程 | `android/` 的 APK，`aac_android/inproc.py` | 在本进程的线程里跑**同一份** `tool/`；不是子进程，脚本把进程弄崩会带走整个 App |

鸿蒙桌面路径另由 `gui/harmony_client.py` 工作线程调用 `gui/harmony_engine.py`，通过随包 HDC 操作手机；窗口桥仍由 `Api` 提供。原状态、旧版记录迁移与统一互斥见 [ADR-0031](adr/0031-harmony-desktop-integration.md)。

两个执行宿主（桌面 / 手机）跑同一份引擎与机型脚本。替换只有三处：**命令怎么执行、每一步怎么起、屏幕怎么读**，都在 Python 层（[ADR-0019](adr/0019-phone-second-execution-host.md)）。另有一处**措辞分叉**：手机版没有电脑和数据线，引擎的排查提示按宿主取词（`tool/host.py` 的 `ON_PHONE` / `CLICKER` / `CLICK` / `TAPPED`，以及结果页验证档位提示的 `coverage_notes()`），客户端的诊断行同理（`gui/app.py` 的 `TAP_REFUSED`）；判定、控制流与机型脚本不分叉（ADR-0019 增补段）。

## 二、四条跨边界契约

| 契约 | 边界 | 谁消费 | 决定 |
|---|---|---|---|
| 命令与退出码 | 客户端 → 引擎 | `gui/tasks.py` 的 `Task`；`gui/dispatcher.py` 的 `Job` | 一条命令一个 `cmd_*(serial, rest) -> int`，`sys.exit` 只在入口一处，转发型命令透出子进程码（[ADR-0005](adr/0005-run-command-handlers.md)） |
| 引擎输出的三态 | 引擎 → 客户端 | `gui/dispatcher.py` 的 `_log()`；手机版 `aac_android/view.py` | 人话行进界面；`#aac:event` 只改状态、不进日志；`#aac:payload` 只进上报（[ADR-0004](adr/0004-engine-state-events.md)、[ADR-0009](adr/0009-engine-payload-channel.md)） |
| 窗口桥 | 前端 → 客户端 | `gui/web/`；手机版改由 Compose 直接调 Python（[ADR-0018](adr/0018-android-compose-ui.md)） | `Api` 上的方法名与参数是前端唯一契约，内部的下载 / 上报 / 调度怎么分家都可以变（[ADR-0011](adr/0011-api-splitting.md)） |
| 读屏 adapter | 引擎 → 手机 | `tool/fast.py` 的 `Phone` | 读屏 adapter 是引擎看手机的唯一接口，实体归 `Connection`（`conn.reader`），门面经设备动词对外（[ADR-0001](adr/0001-phone-connection-module.md)、[ADR-0002](adr/0002-phone-state-interface.md)、[ADR-0019](adr/0019-phone-second-execution-host.md)、[ADR-0045](adr/0045-device-vocabulary-script-surface.md)）；桌面是 uiautomator2，手机是 `aac_android/u2.py` |

## 三、`tool/` 模块清单（出厂引擎）

`tool/` 只放**出厂引擎**：随 APK 发到手机上，手机版与桌面版同一份。仓库工具链在 `devtools/`
（票务、发版与校验脚本，只在 CI 与本机跑、不随包），两边由目录本身分界——`syncEngine` 是整目录
glob，放进哪个目录就决定了它会不会进包（[ADR-0041](adr/0041-tool-engine-devtools-seam.md)），
`tests/test_tool_package.py` 守着这条边界。

一次执行会跑到的：

| 模块 | 拥有什么 |
|---|---|
| `run.py` | 总入口：命令分派、退出码、设备信息、备份的存取 |
| `fast.py` | 引擎出口：`Phone` 门面只做转发与组合；协作者都在 `tool/phone/`（下一张表），模块级名字仍从这里可 import（[ADR-0033](adr/0033-phone-phase-modules.md)） |
| `recipe_loader.py` | 机型脚本的唯一装载入口：按路径转发到 `tool/catalog`（`.toml` 页面树），不再有 `.py` 脚本分支；`fast.execute`、`adapt.check_draft`、`tests/fixtures.load_recipe` 三处都走它（[ADR-0038](adr/0038-recipe-catalog.md)） |
| `tool/catalog/` | 页面树的装载 + 校验 + 解释器（`loader.py` / `schema.py` / `interpreter.py` / `launch.py`）：数据的唯一执行入口，校验器与解释器共用 `load()`，未知 kind 与多余键在装载期就报错；每段的段体包成 action 经 `Runtime.run_step` 执行，段归属不断。`start` op 的拉起命令只在 `launch.py` 拼一次（`launch_command()`；`--windowingMode` 白名单与「哪些键走原始命令」也在那里），解释器读它（事实层在 #1478 也从这里取），别另拼一份。`recipe_loader.py` 把 `.toml` 转发到这里（[ADR-0038](adr/0038-recipe-catalog.md)、#1473） |
| `recipe_runtime.py` | 这一次执行（`rt`）：段过滤、跳过/断言出口（`page` / `require_switches` / `skip_in_safe_mode` / `start_or_skip`）、安全模式、分段台账、失败段与中止、时钟、每机型常量与回读确认数；段包装在 `Runtime.run_step()`，数据段按声明顺序执行（[ADR-0038](adr/0038-recipe-catalog.md)、#1268） |
| `recipe_kit.py` | 运行时名词的显式 re-export（`DONE` / `SkipStep` / `Runtime` 等）；`preamble()` / `@step` / 执行作用域都已删除（#1268） |
| [recipe_lib/](../recipe_lib/) | 机型库（沿用 #1269）：按家族分文件（`<家族>.py`）+ 跨家族共享（`shared.py`），文件内分「词汇 / 策略」。`__init__.py` 是库实现名字的唯一 owner（`LIBRARY` = 家族 `__all__` 的并集；`__all__` 再加一批面助手（`HELPERS`，不进 `LIBRARY`））。实现都是普通函数收 `(p, rt, …)`，数据用 `lib` 按名字点名；同一个名字有几套实测走法时由 `rt.constants` 里的机型常量选（`GEAR_STYLE` / `BROWSER_FLOW` / `MENU_STYLE` 等），缺省档保留旧行为。归属按家族数算，守卫在 `tests/test_recipe_nav.py`（[ADR-0038](adr/0038-recipe-catalog.md)、[ADR-0040](adr/0040-library-name-table-owner.md)、#1269） |
| `recipe_nav.py` / `recipe_strategies.py` / `recipe_steps.py` | `recipe_lib` 的三个兼容壳（[ADR-0040](adr/0040-library-name-table-owner.md)）：名字表 owner 是 `recipe_lib/__init__.py`，这三份只剩 `sys.path` 垫片 + `from recipe_lib import *` + `__all__` 转发；机型例外 `.py` 仍从这里取名字，但新实现与名单都不要写进壳里 |
| `recipe_audit.py` | 本机函数审计：每份脚本自己定义了哪些模块级函数、归哪一档，「本机策略：N 个」从哪来；`check` 与 `status-json` 取同一份计数（`counts()`），只读 AST、不 import、不连手机 |
| `recipe_meta.py` | 机型脚本头部的元数据：录制版本、机型列表、段名，以及对外的稳定身份（目录名，`recipe_id()`）；只有正则，不背 CLI 入口的副作用 |
| `recipe_source.py` | 机型脚本的事实层：一份源码里的调用点与模块级常量，纯 AST，入口速查与词库共用（[ADR-0034](adr/0034-recipe-source-facts.md)） |
| `chan_fast.py` | 营销通知渠道：`ChannelPage`（到页 + 认行的执行壳）、批处理循环的点击 / adb 往返 / 打印，结局词表与策略函数从 `channel_batch` 显式 re-export |
| `channel_batch.py` | 渠道批处理的策略：一项的结局与记账表（`OutcomeKind` / `RULES`）、清单 → 队列、两趟门槛、重试挑行、收尾复查豁免，都是值类型与纯函数（#1437） |
| `channel_decide.py` | 渠道页的认页决策：认页、页眉、组底、屏外名与可拨名单是屏幕快照上的纯函数（#1434） |
| `channel_arrive.py` | 渠道页的到达决策：走哪条路线、应用通知页上这一帧的下一步是快照与通知清单上的纯函数，输出意图（#1435） |
| `channel_toggle.py` | 渠道拨动的决定：这一行点不点、点完算不算成、点后消失与灰态各算什么，是屏幕快照上的纯函数（#1436） |
| `channel_policy.py` | 渠道判定：营销候选、扫描排除、默认不勾、受保护、前台服务 |
| `screen_snapshot.py` | 屏幕快照 / 通知清单 / 意图 / 进度四个值类型与它们的纯构造、JSON 往返；`Screen.snapshot()` 与 `Screen.apply()` 都从这里取一份定义（#1432） |
| `row.py` | 「开关所属的那一行」的唯一定义 |
| `wait.py` | 「等到页面认得出」与「等机主解锁」的唯一实现 |
| `events.py` | 事件行与载荷行的格式与判定 |
| `summary.py` | 一步结果怎么说成一句话：两个宿主共用这一份，界面只显示 `summary` 字段（[ADR-0019](adr/0019-phone-second-execution-host.md) 的增补段） |
| `coverage_note.py` | 结果页要不要为脚本的验证档位多一行：判据一份，措辞按宿主从 `host.py` 取，快照带 `coverage_note` 字段（[ADR-0010](adr/0010-execution-state.md) 的增补段） |
| `plan.py` | 一次执行跑哪些步骤的规格：八个键、默认值、宽容收与 JSON 往返；排任务与重试轮都从它取值 |
| `reader.py` | 读屏 adapter 的接口（`Reader`） |
| `adb_link.py` | 连接中断的判定与「等手机回来」 |
| `backups.py` | 备份目录的命名、扫描与兜底 |
| `entries.py` | 入口速查：品牌家族 × 分组 × 三档路径；`FAMILY` 也在这里 |
| `ui_hidden.py` | 「本机 UI 未暴露」渠道名单 |
| `ui_session.py` | 读屏会话的本机互斥 |
| `troubleshooting.py` | 读屏失败的排查提示 |
| `host.py` | 这次执行跑在哪个宿主（手机版 / 桌面），以及随之切换的称呼 |

`tool/phone/` 里是 [ADR-0033](adr/0033-phone-phase-modules.md) 的七个协作者模块（两个基座 + 五个阶段）
加三个跨阶段会话对象；两个基座与五个阶段分三层（`Connection` → `Screen` → 阶段），
`fast.py` 的 `Phone` 是包外的薄门面：

| 层 | 模块 | 拥有什么 |
|---|---|---|
| 基座一 | `phone/connection.py` | 连接与生命周期：设备、串号、断线判定、锁屏等待、日志开关 |
| 基座二 | `phone/screen.py` | 读屏与认行、页面诊断、视口几何（`W` / `H`）、动作原语（含翻页）、确认框的认法 |
| 跨阶段状态 | `phone/session.py` | 三个会话对象：丢失记录（`LostNote`）、启动会话（`LaunchSession`）、渠道会话（`ChannelSession`） |
| 阶段 | `phone/toggler.py` | 拨动：`off()` 与它的计划、回读、补点、结局 |
| 阶段 | `phone/launcher.py` | 启动与落点：拉起、前台归属、落点证据 |
| 阶段 | `phone/settings_search.py` | 设置搜索：进搜索框、输入、退化链、往返 |
| 阶段 | `phone/dismisser.py` | 弹窗与推广位：`dismiss()` 的退化链、点了 ✕ 之后的推广位退回 |
| 阶段 | `phone/navigator.py` | 导航：`tap` / `go` / `enter` / `entry` / `tab` / `top`、换页校验与等页 |
| 门面（包外） | `fast.py` 的 `Phone` | 只做转发与组合；公开面 = 设备概念（动词 + 8 条属性），不再是「内部字段的并集」（[ADR-0045](adr/0045-device-vocabulary-script-surface.md)） |

调用关系单向：两个基座不 import 任何阶段，阶段之间也不互相 import，只经注入的窄接口协作（导航与
启动拿弹窗的 `dismiss`）。阶段做事有两条路：观测与点击走 `Screen` 的动作原语，拉起 App、切设置页、
打字这类传输走它背后的 `Connection`（`reader.shell` / `_u2`）。`tests/test_phone_navigator.py` 的
`CallGraphTests` 只钉住两条——「阶段只 import 基座」与「包内无环」，基座反向 import 阶段今天没有守卫。

只有人手动敲命令才会跑的：

| 模块 | 拥有什么 |
|---|---|
| `adapt.py` | 新机型适配辅助：试入口 → 探路 → 勾选 → 草稿 → 自检 |
| `explore.py` | 探路：只读，列出像广告的开关 |
| `huawei_channels.py` | 华为 ALN-AL00 的清单式渠道处理，需人工审核清单，客户端不自动跑 |
| `verify_ledger.py` | 配方验证台账：读 `recipes/verified.toml`，每个配方文件一行、按距今天数降序，覆盖度与证据来源是两个维度（`entry()` 也供 `run.py` 的 `status-json` 取这三样），缺记录的条目 `entry()` 给「未记录 / 未知」、CLI 行只打「未记录」，段体正文改过标「待复核」（比记录里的 `body_hash` 与脚本现算的值；`--hash` 只打印刷新基线用的当前值），记录 build 对不上脚本 `BUILD` 的打「build 不符」（沿用 #916、#917、#918 的台账口径，沿用 #1124 的证据来源拆档，沿用 #1242 把判据从提交日期换成段体哈希） |

`devtools/` 里是 21 个仓库工具链模块，不随包；下面几份是人肉命令会直接跑的（[ADR-0041](adr/0041-tool-engine-devtools-seam.md)）：

| 模块 | 拥有什么 |
|---|---|
| `devtools/gen_brand_taps.py` | 从 `docs/手机版教程/brand-taps.json` 渲染连点表 |
| `devtools/gen_site_css.py` | 把仓库根 `site.css` 渲染进官网两页的共享样式块 |
| `devtools/gen_adr_index.py` | 从 `docs/adr/` 渲染编号 + 一级标题到 `docs/adr/README.md`，供 `CLAUDE.md` 只留一条指针（#1299） |
| `devtools/check_dco.py` | PR 的 DCO 校验：逐个非 merge 提交比对 `Signed-off-by` 与作者邮箱（#848） |
| `devtools/check_conventional.py` | PR 的提交主题校验：`type(scope): subject`，类型清单 `TYPES` 也在这里（#849） |
| `devtools/check_ticket_ref.py` | PR 的票号校验：分支名以 `-<票号>` 结尾、正文有 `Refs #N` / `Closes #N` 且是同一张（#1001） |
| `devtools/check_comment_tickets.py` | PR 新增行里的票号要在正文引用的范围内，`docs/adr/` 与含「沿用」的行豁免（#1001） |
| `devtools/mutation.py` | 一个模块的变异测试：搭工作目录、跑 mutmut、读回结局；`--since` 按改动面挑模块（#1411） |

`devtools/commits.py` 不是命令：它是上面几条 PR 校验共用的 `base..head` 读取与 UTF-8 控制台，沿用 #848、#849 起的那份设计。其余工具链脚本（`claim` / `followup` / `stale` / `triage_audit` / `gh` / `release_assets` / `release_meta` / `glob_scan` / `test_anchors` / `typecheck_recipes` / `unittest_summary` / `mutation_scope`）的指路在 `docs/agents/` 与 [ADR-0036](adr/0036-tool-gh-session.md)。

客户端侧：`gui/app.py` 是窗口桥与装配（`Api` / `ClientData`，adb 的那几张源表也留在这里当单一来源），其余各块按 owner 分住——`gui/toolpath.py` 是 `gui/` 到 `tool/` 的惰性加载，`gui/tasks.py` 是计划侧（`Task` … `retry_plan`，身份词表在 `tool/plan.py` 的 `StepKind`），`gui/dispatcher.py` 是执行编排（`Dispatcher` / `Job`），`gui/reporter.py` 是错误上报（`Reporter` / `scrub`），`gui/adb.py` 是 adb 路径解析、下载器与存活探测（`AdbDownloader`），`gui/startup.py` 是启动失败文案与写剪贴板；`gui/launch.py` 是入口与打包冒烟，`gui/web/` 是桌面版的界面，`gui/winpreflight.py` 归因 Windows 启动失败，`gui/dotnet_config.py` 在打包时写随包的 `<exe>.config`。

### 函数级细节

模块表回答「谁拥有它」，这一节回答「哪个函数管什么、哪些不许另写一份」：改这些模块之前先读这一段，别处不要另写一份实现。`CLAUDE.md` 的「## 开发」有一条总指针指向这里，那一条不可删——它是 agent 找到这一节的唯一入口（[ADR-0039](adr/0039-claude-md-startup-index.md)）。

两处入口先记在这里：**门面动词**（`shell` / `swipe` / `window_size` / `home` / `back` / `press` / `app_stop` / `tap_id` / `tap_id_if_present` / `set_text`，加上带守卫的 `click` 与翻页的 `scroll`）只定义在 `tool/phone/screen.py`，`Phone` 同名转发，引擎与脚本都不许绕过它们直连 `conn.reader`（[ADR-0045](adr/0045-device-vocabulary-script-surface.md)）；**脚本面声明**在 `tool/phone/surface.py` 的 `SCRIPT_SURFACE`，唯一来源，守卫是 `devtools/script_surface.py` 的 AST 扫描（`tests/test_phone_facade.py` 的 `ScriptSurfaceTests` 代跑）。

- 找「命令怎么分派、退出码怎么定」先看 `tool/run.py` 的 `dispatch()` 与 `COMMANDS`：一条命令一个 `cmd_*(serial, rest) -> int`，`sys.exit` 只在 `__main__` 一处；退出码语义见 [ADR-0005](adr/0005-run-command-handlers.md)。`tool/adapt.py` 的三条子命令同形状：取 `run.fail()` 与返回码，改它们时别把 `sys.exit` 加回 helper。 <!-- rule:dev.commands.single-dispatch -->
- 改「机型脚本长什么样」先看 `tool/recipe_loader.py` 与 `tool/catalog/`：数据形态是 `.toml` 页面树，唯一装载点是 `tool/catalog`（`fast.execute` 的 run 分支、`adapt.check_draft`、`tests/fixtures.load_recipe` 都走它）；同目录例外 `.py` 是普通模块，函数收 `(p, rt, …)`、顶部显式 import 库，装载器只把它 exec 进命名空间供 `code=` 与钩子取用。导入不产生设备动作；`@step` / `preamble` / `install` / `RecipeScope` 都已删除（#1268），别再写执行式段或模块级动作。<!-- rule:dev.recipes.module-body-shape -->
- 加一种 catalog op 先看 `tool/catalog/schema.py` 的 `OPS`：每种 op 一条 `OpSpec`，说清允许哪些键、必须带哪些键、哪些键装着子 op、产不产出词条 / 入口事实、哪些键要抽成词条。`OP_KEYS` / `OP_KINDS` / `NO_FACT_KINDS` 都是它的派生视图，别去改那三个名字背后的名单。另外两处仍是显式代码：`tool/catalog/interpreter.py` 的 `_HANDLERS` 要有处理器，事实层（`tool/recipe_source.py` 的 `_catalog_src`）要降级成词条 / 入口或让这个 op 声明 `no_fact=True`——这两处与声明要一起改。`tests/test_catalog.py` 的 `OpKindDeclarationTests` 守着声明与处理器表逐项相等、必填键 / 子 ops / 词条键与允许键的声明自洽、事实层显式登记，投影函数遇到没登记的 kind 直接报错，不静默穿透。<!-- rule:dev.catalog.op-kinds-declared-once -->
- 找「某个共享实现住哪、新助手该进家族库还是共享库」先看 `recipe_lib/`：一个家族一个文件（`recipe_lib/<家族>.py`），跨家族的进 `shared.py`，文件内分「词汇 / 策略」；都是普通函数收 `(p, rt, …)`，数据用 `lib` / `code` 按名字点名（解释器查 `tool/catalog/interpreter.py` 的 `LIBRARY`，查不到再查例外命名空间）。归属按**家族数**算（家族取自 `entries.FAMILY`）：只被一个家族用到的进家族文件，被 ≥2 个家族用到的进共享文件；家族文件允许单脚本变体。两条守卫在 `tests/test_recipe_nav.py`：例外 `.py` 里的同名助手出现在 ≥2 台机型（或本地重定义了库实现）却没进 `recipe_lib` 即红；`shared.py` 的每个实现必须被 ≥2 个家族使用。`tool/recipe_nav.py` / `recipe_strategies.py` / `recipe_steps.py` 只是兼容壳，名字表唯一 owner 是 `recipe_lib/__init__.py`（[ADR-0040](adr/0040-library-name-table-owner.md)），新实现不要写进这三个文件。没有执行作用域、没有工厂闭包、没有同名覆盖；再多加一套名字注入就是倒退。事实层只做字面量提取与库实现下扫（`library_sources()` + `scan_source` + `library_hits()`），不再解析 import 归属；词库扫段体与拨动策略的实现源码。 <!-- rule:dev.recipes.shared-sections -->
- 找「这份脚本经共享库实现还能关到哪些名字、用到哪些入口」先看 `tool/recipe_source.py` 的 `library_hits()`：库实现逐层下扫只在那里定义（只认有归属模块的调用、脚本层 import 过但没调用的也算、实参按位置回填），词库与入口速查都只做投影，别在消费方再写一份递归。 <!-- rule:dev.lib.single-walk -->
- 找「`ScreenLocked` 定义在哪儿、库层该从哪儿取引擎名字」先看 `tool/phone/errors.py`：安卓引擎侧这个异常只在那一处定义（鸿蒙宿主在 `gui/harmony_engine.py` 另有自己的一套，与它无关），`fast` 只是显式 re-export（`from fast import ScreenLocked` 仍是 ADR-0033 冻结的对外面，机型脚本与 `tests/` 照旧）；`recipe_lib/` 与 `tool/recipe_runtime.py` 只向下依赖工具层，不经引擎门面取名字——`bounds` / `icon_hit` 取 `row`、`want_state` 取 `polarity`；要整页开关就取门面 `p.switches()`，同名在函数内已被遮蔽时先把它捕成局部名（`honor.py` 的 `native`）再调，别伸进 `p.screen`（脚本面守卫 `dev.phone.script-surface` 只放行声明过的名字）。函数内 import 同样算越界，判据是模块归属不是书写位置。 <!-- rule:dev.recipe.lib-not-import-fast -->
- 找「适配新机型从哪一步开始」先看 `tool/adapt.py`：`survey` 只读试入口（只试 `entries.ENTRIES` 的直达、不走 `Phone.start`），`explore` / `gen` / `check` 是后三段；`-s 序列号 adapt <子命令>` 的转发只认 `ADAPT_SERIAL_SUBS`（`survey` / `explore` / `check`）；`gen`（不用带 `-s`）与未知子命令按这种形态调时，`dispatch()` 直接 `fail()`，不再静默打印帮助。 <!-- rule:dev.adapt.serial-subcommands -->
- 找「渠道引擎怎么决定、动作从哪儿落地」先看四个决策模块：认页在 `tool/channel_decide.py`、到达在 `tool/channel_arrive.py`、拨动在 `tool/channel_toggle.py`、批处理在 `tool/channel_batch.py`，四者都是屏幕快照 / 通知清单上的纯函数，输出 `Intent`；读屏一次经 `Screen.snapshot()` 产出一份 `ScreenSnapshot`，动作只有 `Screen.apply()` 一个执行点，`ChannelPage` 与 `run()` 只取快照、执行意图、带诊断与进度。四个决策模块不读屏、不点击、不 import `fast` / `chan_fast` / `phone.*`，判据在 `tests/test_rules_guards.py` 的 `ChannelDecideGuards`（[ADR-0044](adr/0044-channel-snapshot-intent.md)）。 <!-- rule:dev.channels.decisions-are-pure -->
- 找「怎么走到渠道页、认出哪一行的开关」先看 `tool/channel_arrive.py` 的 `route()` 与 `page_step()`：直达 / 转应用通知页 / 内联行 / 同名放弃四类只在那里判定（[ADR-0007](adr/0007-channel-page.md)），`ChannelPage.open()` / `_enter_app_page()` 只取快照、执行意图、把进度带回去；`channel_switch` / `inline_switch` / `wait_page` / `via_app_page` 是一行前向壳，不要往里加逻辑。认页、页眉、组底、屏外名与可拨名单的判定在 `tool/channel_decide.py`（喂一份屏幕快照，不读屏、不点击），别在壳里另写一份。 <!-- rule:dev.channels.page-entry -->
- 找「渠道怎么判营销 / 服务 / 受保护」先看 `tool/channel_policy.py` 的 `classify()`：七组判定只在那里定义（[ADR-0006](adr/0006-channel-classification.md)）；`chan_fast` 的扫描分支与 `gui/app.py` 的 `chan_scan()` 都消费它，不要另写词表。前台服务的证据来自渠道行（Android 14 起字段改名，两个都认，见 `screen_snapshot.FG_SERVICE_MARKS`；`chan_fast.parse()` 用 `foreground` out 参数带回），不在通知记录段。 <!-- rule:dev.channels.classification -->
- 找「一项渠道结局有哪些、怎么记账」先看 `tool/channel_batch.py` 的 `OutcomeKind` 与 `RULES`（`chan_fast` 显式 re-export）：15 个结局是封闭枚举，`RULES` 按成员给出失败 / 重试 / 拨动 / 复查豁免四件事，加结局要两处一起改；`tests/test_rules_guards.py` 的 `ChannelOutcomeGuards` 守着成员 ≡ 键。批处理的队列、两趟门槛、重试挑行与收尾复查也在同一模块（`plan_queue()` / `second_pass()` / `pick_retry()` / `account()` / `recheck_row()`），都吃通知清单与清单项、不读屏，`chan_fast.run()` 只执行、打印与退出。 <!-- rule:dev.channels.outcome-enum -->
- 找「开关所属的行」先看 `tool/row.py`：`line` 定界、`own` 收窄多开关容器、`title_of` 给行标题、`title_hit` 给标题文字的落点（`off()` 回退用）、`dedupe` 同一水平带、`control` 开关本体（卡片整体 checkable 时取内层 Switch）。`tool/phone/screen.py` 的 `switches()` 消费 `dedupe` / `control`，`channel_decide.py`（认页决策）共用 `SAME_LINE` 与 `own`，按名字筛候选文字节点共用 `named_nodes`（其顶部带阈值取 `geometry.TOP_BAND`，`row.TOP_BAND` 是显式 re-export）；`disabled_at` 判开关是不是灰的，`off()` 与 `chan_fast` 共用它，不要另写一份。设置入口（齿轮）的判据是 `icon_hit`，机型脚本从 `fast` 取这一份。 <!-- rule:dev.row.single-definition -->
- 找「屏幕带 / 图标命中 / 底部标签 / 确认按钮 / 可拨带这些判定用的比例」先看 `tool/geometry.py`：顶部带、页眉带、顶栏兜底、内联行高上限、确认按钮尺寸、图标取样区与尺寸上界、底部标签带与可拨带只在那一处定义，`row` / `fast` / `chan_fast` / `phone/screen` / `phone/toggler` / `phone/dismisser` / `phone/navigator` 都从它取；`row.TOP_BAND` 是显式 re-export。数值与它原本控制的判定逐条对应在各常量的注释里，`tests/test_rules_guards.py` 的 `GeometryGuards` 守着比例字面量只出现在这里。 <!-- rule:dev.geometry.single-owner -->
- 找「等页面认得出」先看 `tool/wait.py`：`settle` / `setting` / `ChannelPage.refresh` / `off` / `confirm` 都消费 `until()`，不要另写轮询循环；「等机主解锁」的文案、轮询间隔、站稳时间与默认预算只在 `wait_unlocked()` 里，两处调用点（`run.py` 起脚本之前、`Phone`）只传锁屏判据与亮屏命令。 <!-- rule:dev.wait.single-loop -->
- 找「引擎报给客户端的状态」先看 `tool/events.py`：六个 kind 与事件行格式只在那里定义（[ADR-0004](adr/0004-engine-state-events.md)），引擎侧 `emit()`、`gui/dispatcher.py` 的 `_log()` 都走它；`failed_steps` 是唯一带载荷的 kind，客户端用 `parse_data()` 取整份字典，其余仍用 `parse()` 取 kind，不要按中文文案判断状态。 <!-- rule:dev.events.vocabulary -->
- 改「一行输出怎么进界面」先看两处：`gui/dispatcher.py` 的 `_log()` 决定它进 `Job.lines` 还是只当事件；`tool/summary.py` 的 `summarize()` 在认不出模式时直接取 `results[].tail` 末行——`tail` 是第二个落点，机器行不能进。两个宿主调同一份，结果行带 `summary` 字段、界面只显示它，桌面与手机版不再各写一份摘要。验证档位提示同理：说不说的判据与按宿主分叉的措辞在 `tool/coverage_note.py`（措辞表在 `tool/host.py`），快照带 `coverage_note` 字段。 <!-- rule:dev.ui.result-line-routing -->
- 找「没勾的项为什么出现在结果里」先看 `gui/tasks.py` 的 `plan_tasks()`：计划本身（八个键与默认值）是 `tool/plan.py` 的 `Plan`，`plan_tasks()` 第一行把传进来的字典或对象收成它；勾了的排 `Task`，没勾的排一条 `skip_reason` 非空的，由 `not_run_result()` 记成 `rc=0` + `skipped` 的结果行（[ADR-0023](adr/0023-not-run-steps-in-results.md)）；原因分三档——没勾、这台机本来就没有或之前已做、通知没扫成，取自 `Api._offered()`（`last_status` + `last_chans`）。真因故障跳过的行仍是 `rc≠0`，别把它并进这一档。 <!-- rule:dev.ui.not-run-rows -->
- 找「哪一步还能重试、重试重跑什么」先看 `gui/tasks.py` 的 `retryable()` / `retry_plan()`：可重试 = `rc≠0` 且没 `stopped`，广告开关步只取结果行里的 `failed_steps` 段名（[ADR-0026](adr/0026-retry-failed-steps.md)）。重试轮重建的也是 `Plan`（`tool/plan.py`），不再手工拼字典。合并按 `Task.kind` 就地覆盖，两个宿主读同一个 `poll()` 的 `retry` 计数，别在前端或 `view.py` 再算一份；段名来自引擎的 `failed_steps` 事件（[ADR-0004](adr/0004-engine-state-events.md) 增补段）。 <!-- rule:dev.ui.retry-plan -->
- 找「这一步是什么身份」先看 `tool/plan.py` 的 `StepKind`：`backup` / `ads` / `recipe` / `channels` / `quickapp` / `finish` 六个成员只在那里声明，`plan_tasks()` 排任务、`retry_plan()` 的对齐键与 `tool/coverage_note.py` 判「有没有脚本那一行」都取它的成员，别处别再写字面量；计划侧那九个符号（`Task` … `retry_plan`）住 `gui/tasks.py`，`gui/app.py` 只留显式 re-export（[ADR-0011](adr/0011-api-splitting.md) 的增补段）。 <!-- rule:dev.client.step-kind-single-owner -->
- 找「读屏 adapter」先看 `tool/reader.py`：它是引擎看手机的统一接口，实体归 `tool/phone/connection.py` 的 `Connection`（`conn.reader`）；门面只把它当构造参数与传输出口用，不再转发 `reader` / `d` 两个别名（[ADR-0045](adr/0045-device-vocabulary-script-surface.md)），新增读屏能力先加进 `Reader`。 <!-- rule:dev.reader.unified-adapter -->
- 找「这台机该跑哪份脚本」先看 `tool/recipe_pick.py` 的 `recipe_for()`：型号直选、同版本变体、同族参考与版本核心比较只在那里（`run.py` 的 `check` / `recipe` / `devices` / `status-json` 只是消费者，各传一次 `root=ROOT`）。`root` 是 keyword-only：不给时用模块自己算的仓库根，测试要对着假 `recipes` 树跑时传它就够，别再 `patch` 模块全局。`recipe_meta.recipe_files()`（有哪些文件）与 `verify_ledger.build_matches()`（只做裸前缀、故意更严）回答的不是同一个问题，两处有意不合并。 <!-- rule:dev.recipes.pick-single-owner -->
- 找「某个品牌某个分组的入口怎么进」先看 `tool/entries.py`：品牌家族 `FAMILY` 只在那里定义（`run.py` 的广告包、参考脚本与版本比较都从它取，别再建第二份），`ENTRIES` 是品牌 × 分组的三档入口，`reach()` 按直达 → 搜索回退、都不通返回 `None`，`markdown()` 生成 `docs/清单/入口速查.md`。直达档两种走法：`am start -n 页面`，或公开 Intent（`Direct.action` → `am start -f 0x10008000 -a 动作 -p 包名`，落点仍按包名 / 页面核对）。条目必须有出处（机型脚本里用过，或某份品牌清单里写着），`tests/test_entries.py` 守着这几条。 <!-- rule:dev.entries.source-and-family -->
- 找「这句话该说电脑还是说本 App」先看 `tool/host.py`：`ON_PHONE` / `CLICKER` / `CLICK` 只在那里定义（手机版由 `boot()` 设 `AAC_HOST=phone`），客户端诊断行的 `TAP_REFUSED` 在 `gui/app.py`。分叉的只有措辞，判定与控制流不分叉（[ADR-0019](adr/0019-phone-second-execution-host.md) 的增补段），唯一的控制流例外是手机版不写插电常亮（`chan_fast.keep_awake()`、`run.py` 的 `recipe` 与 `finish`），别让它变成按宿主分叉的判定。`tool/troubleshooting.py` 是显式转发、`tool/adb_link.py` 直接取；传给引擎的宿主标记只认 `ENGINE_HOST`、不继承用户 shell 的 `AAC_HOST`。读屏失败分三种结局，判据在 `adb_link`：`LIB_GONE` 认「命令服务断开」这一族（走 `link_lost`），`read_failed()` 认「读屏请求超时」（只报这一步没完成，后面的照常跑），`screen_gone()` 认「后台屏没了」（整段收场，与 `Connection` 构造共用同一份判定，结尾按场景分「未点击」与「这一步没有完成」）。 <!-- rule:dev.host.wording -->
- 改「连不上时诊断里怎么说」先看 `tool/diagnostics.py` 的 `diagnostics()`：措辞、排版与脱敏只在那里，`usb_parse` / `usb_hw_id` / `usb_guid_note` / `usb_facts` / `usb_hint` 与 USB 相关的常量同址。进来的 `state` 是 `Api` 整理好的普通映射（设备状态元组、`last_status`、已预渲染跳过原因的结果行、末 60 行日志、用户目录、序列号），`probe` 只有 `adb_version` 与惰性的 `usb_devices`（只在 0 台分支问）。跑本机命令的 `usb_phones()` / `other_adb()`、手机版整段换掉措辞的 `os_name()`、属执行域的 `skip_reason()` 故意留在 `gui/app.py`——那边才没有理由再拼一份诊断文本。 <!-- rule:dev.client.diagnostics-owner -->
- 找「这个开关该开还是该关」先看 `tool/polarity.py`：`NEG_PREFIX` / `AD_WORDS` / `TRACK_WORDS` 与 `want_state()` 只在那里定义，`tool/fast.py` 只是显式 re-export；加一个否定词会同时改变引擎与词库（[ADR-0008](adr/0008-switch-plan.md) 的增补段）。 <!-- rule:dev.polarity.word-lists -->
- 找「某个开关叫什么、哪一页要留着什么」先看 `tool/vocab.py`：从机型脚本现算每个 `(家族, 分组)` 的词条与同页保留项，生成 `docs/清单/词库.md`；只认 `p.off()` / `close_named()` 的字面量与模块级常量。方向取自 `polarity.want_state()`，不按调用名猜。同页保留项只在那一页成立，不产出跨页禁词表（[ADR-0008](adr/0008-switch-plan.md)）。写完脚本跑 `python3 tool/vocab.py gaps <目录名>` 查漏。 <!-- rule:doc.vocab.generated-from-recipes -->
- 找「这一页该拨哪些开关」先看 `tool/phone/toggler.py` 的 `plan_switches()` 与 `SwitchPlan`：目标选择、屏带过滤、`checked` / `kept` / `disabled` 只在那里定义；灰态由调用方注入的 `disabled=` 谓词给出（`off()` 会复读一页确认），`off()` 先回页顶（`Screen.scroll_top()`）再点击 → 回读 → 重试 → 报告（确认框挡着先点掉，判据是 `Screen.confirm_target`；补点两轮仍不动时回退到点行标题，[ADR-0024](adr/0024-off-title-fallback.md)）。回读的结论由 `readback()` 给出（结局词表见 `CONTEXT.md` 的「回读」），补点该点哪一行由 `pick_retry_rows()` 给出；两个函数都不读屏、不点击，`page_same` 与 `disabled` 由调用方注入。`tool/fast.py` 仍是 `from fast import ...` 的出口，模块级名字照旧可 import。 <!-- rule:dev.switches.plan-and-readback -->
- 找「点名的开关没出现时怎么报」先看 `tool/recipe_runtime.py` 的 `Runtime.require_switches()` / `Runtime.page()`（注入面拆除后搬到这里）：文案、`contains`（关键词匹配）、`optional` 名单只在那里定义，报错里带的现场由 `tool/phone/screen.py` 的 `Screen.page_evidence()` / `Screen.note_miss()` 给出（与入口失败的「停在 / 标题 / 开关 / 结构」同形，末尾列当次读到的标题）。机型脚本与数据别另写一份 `require(all(...))`：解释器的 `require_switches` / `page` op 也走这两处。<!-- rule:dev.switches.missing-target-evidence -->
- 找「启动后算不算还在目标 App」先看 `tool/phone/launcher.py` 的 `_launch()` / `check_foreground()`：`unknown_focus()` 判「读不出 ≠ 离开」，连续 `FOREIGN_STREAK` 帧外占才停段，启动等待按 `LAUNCH_WAIT` 计、顺延不超过 `LAUNCH_HARD_STOP`；只有确认落在目标 App 时才读页面文字、关弹窗（[ADR-0022](adr/0022-launch-foreground.md)）。 <!-- rule:dev.launch.foreground-ownership -->
- 找「怎么点 App 底部标签」先看 `tool/phone/navigator.py` 的 `Navigator.tab()`：三层匹配只在那里定义，底部带的上界取 `geometry.TAB_BAND`（[ADR-0012](adr/0012-bottom-tab-in-engine.md)）；它不重试、不确认落点、找不到不回退，需要文字确认的普通导航仍用 `Navigator.go()`。 <!-- rule:dev.navigation.bottom-tab -->
- 找「按文字导航该用哪个方法」先看 `docs/04-给新机型写脚本.md` 的「该用哪个导航方法」：`start` / `entry` / `enter` / `setting` / `go` / `tap` / `tab` 失败时是 `raise` 还是返回 `False`，选错会点错地方；`setting` 失败只返回 `False`，这一段没兜底时必须 `raise`，否则本段空跑还按成功记（#776）。`Screen.focus()` 是当前前台窗口（多数是 `包名/页面名`，锁屏与通知栏抢焦点时是裸窗口名），不是焦点控件。 <!-- rule:dev.navigation.raise-vs-false -->
- 找「Windows 启动失败是缺 WebView2、被 MOTW 拦还是托管的 dll 被判成远程来源」先看 `gui/winpreflight.py`：注册表三态、两个关键 dll 的 `Zone.Identifier` 判定与 `load_rejected()` 认的那两个原文子串只在那里定义（[ADR-0003](adr/0003-desktop-client-import-and-dependencies.md)）；`gui/startup.py` 的 `startup_advice()` 只按结论选文案，顺序是缺运行时 → MOTW → 原文拒载 → 未确认 → 兜底；`startup_failed()` 先经 `win_clipboard()` 把整段写进剪贴板再弹窗，写不进去才退回「按 Ctrl+C」（#811）——启动建议、两条复制提示与写剪贴板都只有 `gui/startup.py` 这一份，`gui/app.py` 只留显式 re-export 与转发壳（弹窗标题取它的 `APP_NAME`）。随包的 `<exe>.config` 由 `gui/dotnet_config.py` 写，`windows.spec` 收集完产物后调用。 <!-- rule:dev.windows.startup-verdicts -->
- 找「免安装版启动时该不该提示旧版还在」先看 `gui/winpreflight.py` 的 `old_install_present()`：旧产品名「安卓去广告」、四处卸载键（HKCU / HKLM 各含 32 位视图）与当前 exe 目录的比较只在那里定义；`gui/app.py` 的 `Api.old_install_notice()` 只把结论变成一条提示，用户点「知道了」后 `settings.json` 的 `old_install_noticed` 记下这一版、下次不再出现；不写注册表，也不自动卸载（#872）。 <!-- rule:dev.windows.old-install-notice -->
- 找「手机版替换层」先看 `android/app/src/main/python/aac_android/`：`adb.py` / `bridge.py` / `inproc.py` / `u2.py` 是替换层落地的四个文件（[ADR-0019](adr/0019-phone-second-execution-host.md)）。引擎、`tool/`、`recipes/` 与桌面版同一份；新增读屏能力要先加进 `u2.py` 与 `tool/reader.py` 两边。 <!-- rule:dev.android.replacement-layer -->
- 找「手机版界面」先看 `android/app/src/main/java/com/ahuamiao/adcleaner/ui/AppModel.kt`：页面流程只有 `Screen` 一个状态，每次切换都经过它的方法（[ADR-0018](adr/0018-android-compose-ui.md)）；带判断的逻辑放 `aac_android/view.py`，别写进 Kotlin。手机版不再加载 `gui/web/`。 <!-- rule:dev.android.screen-state -->
- 找「这个脚本会不会随包发到手机上」先看它所在的目录：`tool/` 是出厂引擎（随 APK 发到手机上），`devtools/` 是仓库工具链（只在 CI 与本机跑，[ADR-0041](adr/0041-tool-engine-devtools-seam.md)）。`syncEngine` 是整目录 glob，往 `tool/` 放一个新脚本它就自动进包，所以「会不会随包」由目录回答。两份冻结名单（引擎 43、工具链 21）与三条守卫在 `tests/test_tool_package.py`：`tool/` 顶层模块必须与名单全等、引擎 import 了工具链即红、打包清单不含 `devtools/`。 <!-- rule:dev.tool.engine-toolchain-seam -->

## 四、一次执行的路径

```
备份 → 挂起广告组件 → 任务步骤（广告开关 / 营销通知 / 快应用）→ 收尾 → 结果
```

- 步骤清单由 `plan_tasks()` 按用户的选择拼出，每一步是一个 `Task`（标题 + `kind` + 脚本 + 参数）。没勾的项也在清单里，只是带 `skip_reason`、不碰手机，照样在结果里占一行（[ADR-0023](adr/0023-not-run-steps-in-results.md)）。
- 没做成的步可以在结果页再跑一轮：`retry_plan()` 按各步的 `kind` 与失败段名重建一份计划，新 `Job` 接住上一轮的结果、按 `kind` 就地覆盖（[ADR-0026](adr/0026-retry-failed-steps.md)）。
- 状态全部收在 `Job` 里：单写者 + 锁内快照，界面轮询只拿快照（[ADR-0010](adr/0010-execution-state.md)）。
- 引擎发回来的东西分三路：人话进日志、事件改状态、载荷进上报（见「四条契约」）。
- 广告开关那一步里，「这一页该拨哪些」是纯函数 `plan_switches()` 算的，点击与回读在 `off()` 里，两者都在 `tool/phone/toggler.py`（[ADR-0008](adr/0008-switch-plan.md)）。
- 营销通知那一步里，「到页 + 认行」归 `ChannelPage`，判定归 `channel_policy.classify()`（[ADR-0007](adr/0007-channel-page.md)、[ADR-0006](adr/0006-channel-classification.md)）。

## 五、状态

- **桌面宿主与引擎：稳定。** 模块边界由 ADR-0001–0020 与 ADR-0033 钉住；主流程不做整体重构。「按读 / 写拆」仍然不成立（[ADR-0020](adr/0020-no-read-write-split.md)），`Phone` 已沿阶段轴拆成两个基座 + 五个阶段 + 薄门面（[ADR-0033](adr/0033-phone-phase-modules.md)），七步搬迁走完。
- **手机宿主：provisional。** ADR-0014 / 0018 / 0019 落地晚于其余决定，Kotlin 侧未在本机编译，配对、自动重开无线调试、后台屏等仍待真机验收——读这一层时不要当成定稿。
