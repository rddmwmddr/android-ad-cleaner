# 测试文件的锚点登记

`tests/` 下的每个 `test_*.py` 只有两种合法归属：一个已声明的**锚点**，或某份机型脚本的**专用测试**。两者之外的新文件即红。

守卫是 [devtools/test_anchors.py](../../devtools/test_anchors.py) 的 `violations(root)`：对给定根目录求值的纯函数，反例用临时目录构造，不依赖真实仓库状态。[tests/test_test_collection.py](../../tests/test_test_collection.py) 在回归里代跑它，本地也可以 `python3 devtools/test_anchors.py` 直接跑一遍（退出码 0 全绿、1 有违规）。

## 两种归属

**锚点**：登记在下面的 `## 锚点登记` 表与 `devtools/test_anchors.py` 的 `ANCHORS` 里，两边逐字对拍——改一处漏掉另一处即红。每个锚点带一句 why，说的是这个文件在守什么（半年后判断「这个文件该不该留」靠的就是它），以及一个断言数上限（见「体量预算」）。

**机型脚本的专用测试**：文件名点名了 `recipes/` 下的某份脚本就自动合规，不逐个登记。点名的形式有三种：目录名的品牌段（`test_honor_recipe.py`）、型号段（`test_rmx3888_recipe.py`）、或脚本头注里的市场名（`test_k70_recipe.py`，对应 `recipes/xiaomi/23113RKC6C`）。给新机型写脚本时，按脚本目录给测试文件命名即可。

跨文件共用的助手与继承用的基类放在 [tests/recipe_case.py](../../tests/recipe_case.py)（非 `test_` 前缀，因此不登记锚点）。用例收进基类后 `grep -l recipe_case tests/` 能列出所有用到它的机型（继承基类的与只借助手的都在内）——继承来的用例在文件里看不见，这条就是这个代价的补偿。

## 新增用例往哪儿放

先找被测的对象：某个 `tool/` 模块、`Phone` 的门面或某个阶段、一条已经登记的行为域——落进它对应的锚点文件。没有对应的，再问「这是不是一份机型脚本的专用测试」，是就按脚本命名。两者都不是时才新开锚点，两处同时登记并写 why 与断言数上限。

票号不消失：并进锚点时，把票号写进用例 docstring 的首行，仍然可以 `grep`；关票时把用例位置写进票，两条合起来就是从票到用例、从用例到票的完整引用。

报红文案会按文件名给出最近的两个锚点作为候选，但那只是提示，不是建议——「这条用例属于门面还是某个阶段」仍是人的判断。

## 已知漏口

豁免判据看的是文件名：一个文件名如果恰好带着机型词（`test_k70_1234.py`），会被当成机型测试放过去。那种文件本来多半也确实是该机型的专用测试，代价可以接受。新写机型测试时按脚本目录命名、不挂票号：票号写在 docstring 首行，文件名里读不出它守的是哪份脚本（`test_honor_cle_an00_671.py` → `test_honor_cle_an00.py`）。

反过来，改名去掉了机型词、又没登记的文件会红——这是对的，它此时已经说不出自己守的是哪份脚本了。

豁免只看文件名与 `recipes/` 的名字和正文，不读那个测试文件的内容：名字里只有品牌（`test_vivo_chan_page.py`）不算点名任何一份脚本，仍要落到锚点；品牌加型号片段（`test_honor_wkl_recipe.py` 的 `wkl`）才算。

守卫只扫 `tests/` 顶层。`tests/` 下将来若出现子目录，里面的 `test_*.py` 会被 `discover` 收到却不受这条规则约束——目前没有，出现时要先把守卫改成递归再放进去。

机型测试之间的去重守卫（`tests/test_test_collection.py` 的 `duplicate_cases()`）只挡逐字节相同：改一个字、换个变量名就绕过去了。它挡的是复制粘贴，不是「两条用例其实在验同一件事」——后者仍归评审。同一文件里的副本也不管，那份归文件自己。同一文件的 `shadowed_cases()` 补另一个方向：继承了基类又在文件里写同名 `def test_` 会静默盖掉基类那份，它按 `class X(recipe_case.Y)` 认继承，写成别的形式（`from recipe_case import Y`）就看不见。

## 族

同一被测入口、同一种断言形态的用例，可以收进 `tests/` 顶层一个**族模块**（非 `test_` 前缀的 `.py`）：一份 case 数据、一个消费循环、一份快照、一根结构守卫。族是这套测试架构里「可删除的单位」——case 的 owner 换成它依赖的结构项，结构来源退场，整族跟着退场。

**什么时候新用例进族**：同一被测入口 + 同一种断言形态，且输入有可程序访问的结构来源（`OPS`、入口表、词库、规则词表这类常量），于是 case 行写得成纯数据字面量。

**什么时候独立成函数**：写不进数据行（需要 Callable / Lambda / Name）、断言形态不同、或输入不是数据（子进程、真进程、需要手机）——这些只能是 `test_*.py` 里的 `def test_`。

两条硬约束：

- 族模块放 `tests/` **顶层**、用非 `test_` 前缀：子目录里的 `test_*.py` 会被 `discover` 收到却不受锚点守卫约束，族模块别放进去。快照在 `tests/snapshots/<族名>.json`，更新必须 `--update --reason "…"`，且 `--reason` 要带一个票号引用（如 `seed (#1395)`）——对不上一张票的更新直接被拒（退出码 2）。
- 句柄必须**从 case 的构造内容派生**，不写手写字符串字面量——手写句柄等于给结构造第二个 owner。
- 登记是手写元组，发现是自动的：`tests/test_family.py` 的 `FAMILIES` 要列全四个族，`test_every_family_module_is_registered` 拿 `tests/*_family.py` 双向核对——新族漏登记，它会静默逃出 `dev.tests.family-carries-cases` 的检查。

## 行为域

七个按批次组织的回归文件（`test_issue_regressions.py`、`test_layout_and_verdict_regressions.py`、`test_lock_and_disconnect_regressions.py`、`test_page_and_link_regressions.py`、`test_regressions.py`、`test_release_regressions.py`、`test_tap_notice_regressions.py`）里，用例的 owner 是它所在类声明的行为域：类属性 `DOMAIN = "<英文标识>"`。同一份文件可以承载多个域，混合域的类已按用例拆开，所以「一条用例属于哪个域」等于它所在类声明的 `DOMAIN`——一个 `def` 只属于一个域。新开一个含用例的类而不声明域即红；七个文件之外的文件不许声明域，新文件要落进已有锚点。

判据是 `devtools/test_anchors.py` 的 `domain_violations(root)`，词表是同一文件的 `DOMAINS`，与下表逐项对拍；文件名清单只在 `DOMAIN_FILES` 一处。归属换成域而不是票号，是为了行为退役时能按域找到该删的类。这里列的是实测十域，票面写的「渠道 / 连接 / 启动 / 结果页」只是其中之四。

| 英文标识 | 中文名 | 这个域在守什么 |
|---|---|---|
| `channel` | 渠道 | 渠道列表与渠道页：从清单和页面认出营销渠道、跳过系统锁定项、点击后页面变了没有，批处理遇变就停。 |
| `connection` | 连接 | 手机连接：adb 在哪、命令服务断开 / 读屏超时 / 后台屏没了三种结局怎么判，包清单与断线后的收尾。 |
| `startup` | 启动 | 启动与落点：前台归属、权限门、安全模式、脚本选择，以及启动后有没有离开目标应用。 |
| `result` | 结果页 | 结果页与暂停：一次执行怎么说成一句话、哪一档步骤可重试、暂停落在哪个安全点。 |
| `packages` | 包与快应用 | 包与快应用：AD 包与 msa 的挂起还原、chain3 原值写回、按品牌或 ROM 取包。 |
| `navigation` | 导航 | 导航与弹窗：搜索框输入、图标入口、底部标签与返回，以及弹窗和推广位怎么退。 |
| `switch` | 开关 | 开关本身：标题去重、状态后缀、自绘开关与单选框、极性、点按与确认框。 |
| `device_state` | 设备状态 | 设备状态：锁屏与等解锁、焦点归属、常亮写回，以及灰态渠道不算失败。 |
| `desktop` | 桌面与打包 | 桌面客户端与打包：USB 诊断、adb 镜像、剪贴板、更新提示，以及随包资产清单。 |
| `backup` | 备份还原 | 备份还原：备份目录与包清单落盘、扫描失败保留原件、跨盘路径。 |

## 体量预算

`## 锚点登记` 的第三列是每个锚点的**断言数上限**，与 `devtools/test_anchors.py` 的 `ANCHORS` 第二项逐字对拍。这是软预算：**超限不红、不阻断合并**，只在 CI summary 的「锚点体量」一节里各列一行（当前值与上限）；本地跑 `python3 devtools/unittest_summary.py <日志>` 也看得到。量具与渲染都在 `devtools/unittest_summary.py`（`assertions_in` / `budget_rows` / `budget_section`），两个平台的 job 各出一份，AST 现算、两边结果相同。

**计量单位是断言数**：文件里的 `assert` 语句、以 `assert` 开头的方法调用（含 Mock 的 `assert_called_once` 这类）与 `self.fail(...)` 本身各算一条；`failUnless` 一类旧别名，以及 `chan.failed(...)` / `failure_message(...)` 这类同前缀的非断言调用都不数。不按 `def test_` 个数，因为函数个数会被「把几条用例并进一个函数」压下去——`for` 循环配一条 `assert` 就能把三十条用例写成一条，函数数掉到 1 而保护一点没少。断言数在这个动作里不变，函数数会变，所以只有前者配当预算。

**上限是初始实施时的实测值，此后只许降**。超了要么把文件拆开（体量本来就到该拆的时候了），要么在评审里说明这次为什么不能拆、要动哪一处上限——改数字必须同时改 `ANCHORS` 与 `## 锚点登记` 表，两处对拍会挡住只改一处。

这条纪律**没有机械守卫**：超限不返红，把上限调高也不返红，`docs/agents/rules.toml` 里没有它的条目。这是票面的要求「可见而不阻断」——机械冻结上限就等于阻断合并。所以只有 CI summary 那一行与评审能看住它，别在注册表里找守卫。

**族模块不受这条预算约束**：族是 `tests/` 顶层的非 `test_*.py`（`TEST_FILE` 不抓），它们的 case 由 `tests/snapshots/<族名>.json` 与结构守卫管（见上面「族」一节）。把用例搬进族会让锚点的断言数下降，这不是预算在奖励搬运——族的规模由它自己的 case 快照盯住，锚点预算只盯「还没搬进族的那些」。

上限列写 `—` 表示这个锚点不设预算；目前没有一处这么写。它不是体量超限的逃生口：真要留空，评审里得说清为什么这个文件不该有边界。

## 锚点登记

| 文件 | 为什么 | 断言数上限 |
|---|---|---:|
| `test_adb_link.py` | 手机连接：adb 在哪、命令服务断开 / 读屏超时 / 后台屏没了三种结局怎么判、读屏探测在哪找。 | 176 |
| `test_row.py` | 「开关所属的那一行」的唯一定义：结构定界、几何分带、同名去重与自绘开关去重。 | 67 |
| `test_wait.py` | 「等到认得出」：超时、稳定、变化、受阻四个判据，外加等机主解锁。 | 47 |
| `test_entries.py` | 入口速查表与它怎么被用：每条入口有出处、文档同源、reach() 按直达与搜索回退，以及各品牌脚本进具体入口（齿轮、直达、浏览器 / 主题 / 商店 / 负一屏）。 | 442 |
| `test_vocab.py` | 品牌词库：词条有出处、键与入口速查相同、同页保留项只在那一页成立，以及 gaps 查漏。 | 156 |
| `test_events.py` | 引擎事件的词表与解析：六个 kind、固定前缀、坏行当没有，写出的行中文逐字、逐行 flush。 | 18 |
| `test_engine_events.py` | 引擎侧在语义发生地发事件，人话逐字不变。 | 36 |
| `test_client_events.py` | 客户端只认引擎事件：事件行不进日志、人话本身不改状态。 | 35 |
| `test_summary.py` | 结果摘要的唯一定义：一段 tail 怎么说成一句话，两个宿主与两条链路说同一句。 | 16 |
| `test_coverage_note.py` | 结果页验证档位提示的唯一定义：说不说的判据、按宿主分叉的措辞（整句逐字），与档位词表的对应。 | 15 |
| `test_channel_classification.py` | 渠道判定：哪些渠道算营销、受保护、默认不勾，扫描因此列出谁、排除谁。 | 81 |
| `test_channel_outcomes.py` | 渠道批处理的结局记账与上报：一项的结局是值，怎么记、怎么报由几张表定。 | 217 |
| `test_channel_page.py` | 渠道页：从哪条路走进去、认出的是不是渠道页、从哪一行拿开关。 | 152 |
| `test_channel_snapshot.py` | 屏幕快照 / 通知清单 / 意图 / 进度四个值类型：构造、JSON 往返，以及每个意图种类只经基座唯一执行点落地。 | 60 |
| `test_channel_decide.py` | 渠道页的认页决策是屏幕快照上的纯函数：认出哪一行、卡在哪一阶段、哪些行可拨。 | 61 |
| `test_channel_arrive.py` | 渠道页的到达决策：六条路线与三条失败路径各自该发哪个意图、结局是什么。 | 31 |
| `test_channel_toggle.py` | 渠道拨动的决定：能不能点、重试还是放弃、点后消失与灰态各自算什么。 | 21 |
| `test_channel_batch.py` | 渠道批处理策略：清单→队列的预筛、两趟门槛、重试挑行与收尾复查豁免，逐条结局用纯数据证明。 | 43 |
| `test_phone_facade.py` | Phone 门面 + 两个基座 + 五个阶段的对外契约。 | 66 |
| `test_phone_base.py` | 两个基座可以各自独立构造，不必造整台 Phone。 | 22 |
| `test_phone_sessions.py` | 三个跨阶段会话对象，门面用显式属性转发过去。 | 12 |
| `test_phone_toggler.py` | 拨动阶段：这一页该关的开关真的被关掉，含确认框判定与等待、页顶复位与残留提示；`drive()` 装的假钟要还原。 | 82 |
| `test_phone_navigator.py` | 导航阶段的对外契约：go / tab / 入口与落点确认，含底部标签带内三层匹配与齿轮点完的落点校验。 | 93 |
| `test_phone_settings_search.py` | 设置搜索阶段：对外契约、搜索失败后的退场，以及设置页签名认 Setting 与 Preference 两族。 | 35 |
| `test_phone_dismisser.py` | 弹窗与推广位阶段：词表只有一份，推广位点了要退回；菜单的返回键与设置页里的说明行都不算弹窗 ✕。 | 79 |
| `test_phone_launcher.py` | 启动与落点阶段：前台归属、抢夺者现场与落点校验。 | 47 |
| `test_phone_interface.py` | Phone 的接口面：读屏策略、探路包名过滤、安全模式与 adapter 名字。 | 173 |
| `test_switch_plan.py` | plan_switches() 的策略面：这一页该拨哪些开关，与点击循环无关。 | 47 |
| `test_off_readback.py` | readback() 与 pick_retry_rows()：回读结局与该补点哪一行。 | 21 |
| `test_off_title_fallback.py` | 只认行标题的页面：点开关本体不动时 off() 回退到点标题。 | 24 |
| `test_main_switch_bar.py` | 渠道页的 main_switch_bar：外层容器里包着真开关，不能按颜色当自绘开关。 | 1 |
| `test_ui_session.py` | 读屏服务占用、失败清理、跨进程互斥与失败后的收尾。 | 39 |
| `test_never_suspend.py` | NEVER 保护集：挂了会坏功能的包，整批拒绝、不落一条命令到手机。 | 13 |
| `test_recipe_loader.py` | 机型脚本只有一个装载入口，测试不许自己 exec 一份脚本。 | 8 |
| `test_recipe_meta_module.py` | 配方元数据住中立模块：import 不背 CLI 副作用，脚本枚举跳过非目录项，头部三段缺省是空值（段名缺 name 也是空串）。 | 10 |
| `test_recipe_variants.py` | 同一型号按系统版本选脚本变体、变体要进安装包，型号目录里哪一份算主脚本，以及没有本型号脚本时参考脚本按录制版本在同族里挑、怎么比对版本。 | 101 |
| `test_recipe_setting_checked.py` | 机型脚本必须消费 p.setting() 的返回值，不能空跑还记成功。 | 35 |
| `test_recipe_nav.py` | 机型库的拆分守卫（例外 `.py` 的同名助手必须升格进 `recipe_lib`；`shared.py` 的实现必须被 ≥2 个家族使用）、名字表 owner 与三个兼容壳的一致守卫（`SurfaceTests`），以及调用序列对拍驱动自己管基线 worktree。 | 22 |
| `test_recipe_source.py` | 脚本事实层：实参按语法切分、形参回填与读不出态、页面标签与导入面、Intent 三种包名写法、语法错直接抛，以及库实现下扫与两份进程内缓存。 | 99 |
| `test_catalog.py` | catalog 内核：页面树数据经唯一装载入口跑出与旧脚本逐条相同的调用序列、装载期拒绝非法数据与写错的点名（报错原文与边界值也逐字）、only 两态与 page-wide 全关，以及事实层降级出的每一行源码。 | 241 |
| `test_xiaomi_store_recipe.py` | 小米各机型的应用商店段：入口形态（回到首页 / 直达偏好页 / 底栏标签 / 顶栏齿轮）与收尾次序各一条，入口成功的那条路快照走不到。 | 64 |
| `test_xiaomi_theme_recipe.py` | 小米主题两段：下半屏「我的」的判据、换页慢机型的签名等待，以及齿轮点不到那条出口——快照在这里只看得到一次 settle。 | 22 |
| `test_xiaomi_ads_recipe.py` | 小米系统广告五台机：直达不通退回菜单的两个出口、设置搜索搜不到的那条失败，以及「安全」标签的重试轮与切完再翻一次——快照在「隐私与安全」那一步就断了。 | 57 |
| `test_backups.py` | 备份目录的命名、扫描与 <型号>-gui 兜底。 | 35 |
| `test_captures.py` | 失败现场落盘：两处留现场写原文、没目录不写、归档名与体积报数。 | 18 |
| `test_error_report.py` | 错误上报：内容脱敏、预览与发送一致、限频、安装编号与服务器回应。 | 75 |
| `test_diagnostics.py` | 设备诊断文本的唯一定义：给定一份整理好的 state，整段输出逐字等于什么，含按分支的措辞与脱敏。 | 35 |
| `test_updates.py` | 应用内更新：真实字节下载与状态迁移，网络与安装由边界替身接管。 | 227 |
| `test_update_install.py` | 在临时目录里真正换文件：回滚、保留卸载器与新进程健康回执。 | 286 |
| `test_win_preflight.py` | Windows 启动失败归因：缺 WebView2、MOTW、托管 dll 被判远程。 | 77 |
| `test_win_dotnet_config.py` | 随包分发的 <exe>.config 让包内托管 dll 不被判成网络位置。 | 11 |
| `test_hdc_fetch.py` | HDC 只在构建期下载、按钉死的 SHA-256 校验并解包。 | 33 |
| `test_hdc_lookup.py` | 找 hdc 的候选顺序，五档只有这一份。 | 5 |
| `test_packaging_entry.py` | 打包入口指向的文件存在、能 import、并给出 main。 | 48 |
| `test_entrypoint_refs.py` | 非测试入口对 gui.app 的引用得像真的一样存在。 | 4 |
| `test_source_text.py` | 源码文本的两条机械规则：不写裸零宽字符、基线钉提交 SHA。 | 2 |
| `test_stdio.py` | 标准流 UTF-8 的唯一出口：尽力而为、失败静默。 | 2 |
| `test_subprocess_text_mode.py` | 子进程的文本模式必须写清解码方式。 | 3 |
| `test_runtime_symbols.py` | 跨运行时符号：tool/ 在电脑与手机版跑两套依赖，静态引用的名字要真的存在。 | 2 |
| `test_declared_fields.py` | 构造处声明过的字段要直接读，不再 getattr 兜底。 | 1 |
| `test_test_collection.py` | 用例只在 tests/ 下定义，每个测试文件都落到已声明的锚点，锚点的断言数上限在两处登记上逐字对拍，测试文件之间不许有逐字节相同的用例，也不许重写继承来的用例。 | 37 |
| `test_family.py` | 族容器本身：case id 快照、结构句柄、产出与缺口四件校验、必须附理由的快照更新入口，以及四个族对得上各自的快照。 | 82 |
| `test_glob_scan.py` | 发现式 glob 的反空转：发现集为空时与「全仓合规」不可区分，每个模式对真实仓库求值一次，0 份即红。 | 24 |
| `test_rules_guards.py` | 规则守卫：文档内容、注册表、引擎结构与流程条目各自的机械判据。 | 61 |
| `test_rules_registry.py` | 规则注册表的五条不变式，锚点与登记双向一致，`code:` 规则点名的符号只在一处定义。 | 16 |
| `test_doc_consistency.py` | 文档与单一来源一致：ADR 字段表、品牌连点表、共享样式与教程截图，以及四条「配置即判据」的规则与 pyproject / .coveragerc 对拍。 | 112 |
| `test_web_client.py` | 前端用例的代跑与守卫：tests/js/ 的 jsdom 用例由它在 unittest 里跑。 | 8 |
| `test_fixtures.py` | 夹具本身的行为：样本、假时钟、时间轴与假 Phone。 | 27 |
| `test_compare_phone_state.py` | 两个对拍驱动自己管基线 worktree：未知 SHA 报错且不留下 worktree，不指定基线时仍认手工备好的 tool 目录。 | 3 |
| `test_mutation_scope.py` | 模块 → 测试范围的映射：严格档名单与它不漂、每个目标都在仓库里、选择结果去重保序、摘掉的方法确实挂在被收集的文件上，副本的 src 是 tool、gui 与手机版替换层的镜像，改动面只挑映射表里的模块、表外的 gui 与手机版模块逐条报出来，summary 一节的结论与 pragma 计数，以及「无可变异节点」的判据。 | 59 |
| `test_android_bundle.py` | APK 里那批 gui 文件必须覆盖 gui/app.py 的导入期依赖。 | 11 |
| `test_tool_package.py` | tool/ 的出厂引擎与仓库工具链边界：两份冻结名单与文件系统全等、引擎不拖进工具链、打包清单不含 devtools/。 | 12 |
| `test_android_shim.py` | 手机版替换层：不连手机，替换掉执行通道与读屏。 | 540 |
| `test_android_view.py` | 手机版界面的判断：结果怎么说、什么时候挡住开始、反馈网址怎么截。 | 220 |
| `test_android_version.py` | 单键 getprop 读不到版本时按分区属性回退。 | 7 |
| `test_android_smoke.py` | 真机冒烟：出包、装机、启动、执行、还原三段各自出结论。 | 208 |
| `test_api_structure.py` | 窗口桥契约与客户端三块的责任边界。 | 15 |
| `test_gui_import.py` | import gui.app 不许有副作用：不建目录、不改 sys.path、不加载 tool/；`gui/toolpath.py` 是那份惰性加载的唯一出口，configure 之前加载要报可读的错。 | 9 |
| `test_job.py` | 一次执行的状态收成 Job，poll 只读锁内快照。 | 24 |
| `test_job_races.py` | 一次执行的发布点竞态：停止落在启动与登记之间仍要杀进程、running=false 的快照已带收尾行、旧执行的收尾行不串进新 Job。 | 8 |
| `test_dispatcher_exclusion.py` | 客户端调度器的互斥：还原、安装更新、执行与读屏检查谁在等谁，锁在别人手里时立刻回一句；停止与暂停必须等锁，判断落在临界区内。 | 20 |
| `test_result_retry.py` | 结果页重试：哪一档步骤可重试、广告开关步只重跑引擎报的段、多轮结果按 kind 就地合并。 | 56 |
| `test_harmony_bridge.py` | 鸿蒙窗口桥只转发，状态与构造逻辑不落在 Api 上。 | 9 |
| `test_harmony_client.py` | 鸿蒙接入后的选机、互斥、持久化、停止与旧数据兼容。 | 89 |
| `test_harmony_engine.py` | 桌面引擎的离线用例：合成的界面树与假手机。 | 48 |
| `test_harmony_vocab.py` | 鸿蒙词库守卫。 | 43 |
| `test_plan.py` | 一次执行跑哪些步骤：Plan 规格的八个键与往返，以及按规格排出的任务、未执行行与重试轮。 | 98 |
| `test_run_commands.py` | run.py 的命令接口与它产出的诊断：退出码只在出口、多余往返的守卫、「只是搬家」的对拍，以及设备名与收尾快照。 | 111 |
| `test_adapt_cli.py` | adapt.py 三条子命令对外的退出码与两路输出，survey 试入口的三种结局与 `-s S adapt` 的转发，以及 TSV 解析、草稿生成、自检报告与探路导航。 | 167 |
| `test_chan_cli_baseline.py` | 渠道引擎三个子命令的 CLI 输出基线：scan / off / on 的退出码、输出行与分支守卫。 | 6 |
| `test_gh.py` | 工具层共用的 gh 会话：失败取错误输出、为空退回标准输出，以及判 JSON 的三档报错。 | 15 |
| `test_claim.py` | 开工认领：一条命令写认领评论并摘待办标签，仲裁只看票下评论。 | 90 |
| `test_triage_audit.py` | triage 四条集合判据，登记表与脚本常量逐项对拍。 | 36 |
| `test_stale_scan.py` | needs-info 停摆机制：判定与阈值、写入与幂等。 | 101 |
| `test_conventional.py` | 提交信息的 Conventional Commits 校验。 | 32 |
| `test_dco.py` | 每个非 merge 提交都带与作者邮箱一致的 signoff。 | 27 |
| `test_ticket_ref.py` | 分支名与 PR 正文指到同一张票。 | 28 |
| `test_comment_tickets.py` | 新写的行里挂的票号要与这次 PR 有关。 | 32 |
| `test_verify_ledger.py` | 配方验证台账：每个配方文件一行、缺记录显示未记录，以及 status-json 带出的覆盖度、证据来源与验证日期。 | 81 |
| `test_unittest_summary.py` | CI 的测试结果表格与锚点体量：列取错或漏算跳过数即红，断言按口径计数、超限各列一行。 | 29 |
| `test_release_assets.py` | 下载页 REL 与 Release 附件的对账。 | 81 |
| `test_release_meta.py` | 发版校验清单从 Release 事实生成（devtools/release_meta.py）：退出码、清单文本与写盘。 | 100 |
| `test_followup.py` | 复测队列核对与写回：报出标签与队列的差异。 | 105 |
| `test_download_page_gitee.py` | 国内下载走 Gitee：取包、核 SHA256、匿名下载回验。 | 16 |
| `test_download_page_rows.py` | 下载页与网盘说明的行：手机版 APK 单独成行、说明里写「不用连电脑」并带校验值，页面 id 写错要在上传前停下。 | 23 |
| `test_old_install_notice.py` | 免安装版启动时提示旧名安装还在：文案与「同一版本只说一次」。 | 12 |
| `test_huawei_channels.py` | 华为渠道页的脱敏离线回归：已观察页面，不连手机。 | 71 |
| `test_page_and_link_regressions.py` | 一期社区反馈汇集的设备无关回归：渠道页归属与仿冒、内联开关、多用户解析、点击被拒、adb 掉线与 USB 诊断；每条用例的 owner 是所在类声明的行为域（见「行为域」）。 | 126 |
| `test_lock_and_disconnect_regressions.py` | 上报日志分类汇集的设备无关回归：锁屏判据与等机主解锁、灰态渠道、断线不带堆栈、脱敏与参考脚本；每条用例的 owner 是所在类声明的行为域（见「行为域」）。 | 71 |
| `test_layout_and_verdict_regressions.py` | 发布当天上报汇集的设备无关回归：卡片布局差异、vivo 旧页与直达、失败判定、停止不算失败、暂停与空报告；每条用例的 owner 是所在类声明的行为域（见「行为域」）。 | 86 |
| `test_tap_notice_regressions.py` | 发布后一夜上报汇集的设备无关回归：点击与确认落点、焦点回退、通知页读取、adb 镜像与提示音、vivo 慢过渡；每条用例的 owner 是所在类声明的行为域（见「行为域」）。 | 39 |
| `test_issue_regressions.py` | 社区反馈汇集的设备无关回归：模拟页面与系统回读，不以 UI 状态代替执行结果；每条用例的 owner 是所在类声明的行为域（见「行为域」）。 | 135 |
| `test_regressions.py` | 跨批次汇集的设备无关回归：输入、页面识别、开关保护、启动落点与打包入口；每条用例的 owner 是所在类声明的行为域（见「行为域」）。 | 106 |
| `test_release_regressions.py` | 发布回归汇集的设备无关用例：横屏、部分失败、通知默认选择与发布资源边界；每条用例的 owner 是所在类声明的行为域（见「行为域」）。 | 85 |
| `test_feedback_safety.py` | 用户反馈里的安全项：无障碍排查只读、通知保护与旧清单还原。 | 30 |
| `test_phone_host.py` | 手机版宿主的说法：没有电脑和数据线时该怎么说、界面与诊断里残留的桌面说法，以及唯一的控制流例外（不写插电常亮）。 | 67 |
| `test_recipe_call_snapshots.py` | 机型脚本的调用序列快照：47 份 × present / absent 两场景与入库数据逐条比对，段名归属与空转守卫。更新规则见 docs/agents/recipe-snapshots.md。 | 15 |
| `test_recipe_audit.py` | 本机函数审计：只收模块级函数、四档归属（含声明式钩子）的优先级与判据信号，以及 check 与 status-json 报的「本机策略：N 个」。 | 64 |
| `test_recipe_strategies.py` | 家族库按脚本常量选走法（齿轮 / 浏览器设置 / 页面等待 / 开关读取 / 按名关闭 / 入口点击）与认不出的值当场报错。 | 19 |
