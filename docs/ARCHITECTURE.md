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
| 命令与退出码 | 客户端 → 引擎 | `gui/app.py` 的 `Task` / `Job` | 一条命令一个 `cmd_*(serial, rest) -> int`，`sys.exit` 只在入口一处，转发型命令透出子进程码（[ADR-0005](adr/0005-run-command-handlers.md)） |
| 引擎输出的三态 | 引擎 → 客户端 | `gui/app.py` 的 `_log()`；手机版 `aac_android/view.py` | 人话行进界面；`#aac:event` 只改状态、不进日志；`#aac:payload` 只进上报（[ADR-0004](adr/0004-engine-state-events.md)、[ADR-0009](adr/0009-engine-payload-channel.md)） |
| 窗口桥 | 前端 → 客户端 | `gui/web/`；手机版改由 Compose 直接调 Python（[ADR-0018](adr/0018-android-compose-ui.md)） | `Api` 上的方法名与参数是前端唯一契约，内部的下载 / 上报 / 调度怎么分家都可以变（[ADR-0011](adr/0011-api-splitting.md)） |
| 读屏 adapter | 引擎 → 手机 | `tool/fast.py` 的 `Phone` | `Phone.reader` 是引擎看手机的唯一接口；桌面是 uiautomator2，手机是 `aac_android/u2.py`（[ADR-0001](adr/0001-phone-connection-module.md)、[ADR-0002](adr/0002-phone-state-interface.md)、[ADR-0019](adr/0019-phone-second-execution-host.md)） |

## 三、`tool/` 模块清单

一次执行会跑到的：

| 模块 | 拥有什么 |
|---|---|
| `run.py` | 总入口：命令分派、退出码、设备信息、备份的存取 |
| `fast.py` | 引擎出口：`Phone` 门面只做转发与组合；协作者都在 `tool/phone/`（下一张表），模块级名字仍从这里可 import（[ADR-0033](adr/0033-phone-phase-modules.md)） |
| `recipe_kit.py` | 机型脚本的前导：段包装、入口断言、跳过出口、两个台账（[ADR-0029](adr/0029-recipe-preamble-injection.md)） |
| `recipe_nav.py` | 机型脚本的公共导航助手：跨文件代码逐字相同的导航过程收在这里，由 `preamble()` 调 `install()` 注入；按家族分节（小米系 / vivo / OPPO / 其余·跨家族），同名但代码不同的是机型知识、留在脚本里覆盖（[ADR-0029](adr/0029-recipe-preamble-injection.md)） |
| `recipe_steps.py` | 机型脚本的公共段体：跨文件代码逐字相同的 `@step` 段体收在这里，由 `preamble()` 在导航之后调 `install()` 注入；脚本侧只留一行调用，段体依赖的模块常量按名字从执行作用域现取，同名但代码不同的是机型知识、留在脚本里（[ADR-0035](adr/0035-recipe-steps-injection.md)） |
| `recipe_meta.py` | 机型脚本头部的元数据：录制版本、机型列表、段名；只有正则，不背 CLI 入口的副作用 |
| `recipe_source.py` | 机型脚本的事实层：一份源码里的调用点与模块级常量，纯 AST，入口速查与词库共用（[ADR-0034](adr/0034-recipe-source-facts.md)） |
| `chan_fast.py` | 营销通知渠道：`ChannelPage`（到页 + 认行）、批处理循环 |
| `channel_policy.py` | 渠道判定：营销候选、扫描排除、默认不勾、受保护、前台服务 |
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
| 门面（包外） | `fast.py` 的 `Phone` | 只做转发与组合，公开名字一个不改 |

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
| `gen_brand_taps.py` | 从 `docs/手机版教程/brand-taps.json` 渲染连点表 |
| `gen_site_css.py` | 把仓库根 `site.css` 渲染进官网两页的共享样式块 |
| `verify_ledger.py` | 配方验证台账：读 `recipes/verified.toml`，每个配方文件一行、按距今天数降序，覆盖度与证据来源是两个维度（`entry()` 也供 `run.py` 的 `status-json` 取这三样），缺记录的条目 `entry()` 给「未记录 / 未知」、CLI 行只打「未记录」，验后改过标「待复核」，记录 build 对不上脚本 `BUILD` 的打「build 不符」（沿用 #916、#917、#918 的台账口径，#1124 拆出证据来源） |
| `check_dco.py` | PR 的 DCO 校验：逐个非 merge 提交比对 `Signed-off-by` 与作者邮箱（#848） |
| `check_conventional.py` | PR 的提交主题校验：`type(scope): subject`，类型清单 `TYPES` 也在这里（#849） |
| `check_ticket_ref.py` | PR 的票号校验：分支名以 `-<票号>` 结尾、正文有 `Refs #N` / `Closes #N` 且是同一张（#1001） |
| `check_comment_tickets.py` | PR 新增行里的票号要在正文引用的范围内，`docs/adr/` 与含「沿用」的行豁免（#1001） |

`commits.py` 不是命令：它是上面几条 PR 校验共用的 `base..head` 读取与 UTF-8 控制台，沿用 #848、#849 起的那份设计。

客户端侧：`gui/app.py` 是主体（`ClientData` / `AdbDownloader` / `Reporter` / `Dispatcher` / `Api`），`gui/launch.py` 是入口与打包冒烟，`gui/web/` 是桌面版的界面，`gui/winpreflight.py` 归因 Windows 启动失败，`gui/dotnet_config.py` 在打包时写随包的 `<exe>.config`。

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
