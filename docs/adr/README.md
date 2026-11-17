<!-- 由 devtools/gen_adr_index.py 生成：加 ADR 时写文件再跑一次，不要手改这张表。 -->

# ADR 索引

`docs/adr/` 下每一份决定的编号与标题，按编号排序。模块边界的决定写进这里；机制与取舍在各自文件里，目录里放什么、编号怎么取见 [docs/agents/domain.md](../agents/domain.md)。

- [0001](0001-phone-connection-module.md) — 手机连接是一个 module，传输是它的 adapter
- [0002](0002-phone-state-interface.md) — 一次渠道尝试的诊断归 chan_fast，读屏策略归 Phone
- [0003](0003-desktop-client-import-and-dependencies.md) — 客户端的 import 期什么都不做，路径与启动器从外面给
- [0004](0004-engine-state-events.md) — 引擎发事件，客户端不再嗅探人话
- [0005](0005-run-command-handlers.md) — 命令是 handler，退出码只有一个出口
- [0006](0006-channel-classification.md) — 渠道判定是一个具名判定集，不是一个类别
- [0007](0007-channel-page.md) — 一次渠道到达归 ChannelPage：到页与认行是一件事
- [0008](0008-switch-plan.md) — 一页的拨动计划归 plan_switches()：策略与点击循环分开
- [0009](0009-engine-payload-channel.md) — 引擎发上报载荷：机器行分为事件与载荷两类
- [0010](0010-execution-state.md) — 一次执行的状态归 Job：单写者 + 锁内快照，控制面拆开
- [0011](0011-api-splitting.md) — `Api` 拆成三块：门面转发，状态按产生者归属
- [0012](0012-bottom-tab-in-engine.md) — 点底部标签归引擎的 `Phone.tab()`：定位在引擎，落点确认留给调用方
- [0013](0013-settings-entry-in-engine.md) — 设置入口的判据归引擎的 `row.icon_hit()`：只认「恰好是设置」，怎么点留给脚本
- [0014](0014-phone-shell-channel.md) — 手机版的 shell 通道：双后端由门面收口，命令走一条常驻流
- [0015](0015-pairing-code-ocr.md) — 配对码：截一帧在手机上认出来，不让用户抄
- [0016](0016-settings-search-direct-action.md) — 系统设置搜索的直达动作留在引擎的 `Phone.setting()`：先试动作，失败即回设置首页
- [0017](0017-frontend-test-harness.md) — 前端测试基座用 jsdom + `node --test`，由 Python 回归命令代跑
- [0018](0018-android-compose-ui.md) — 手机版界面用 Compose 原生实现，不再共用桌面版网页
- [0019](0019-phone-second-execution-host.md) — 手机版是第二个执行宿主：引擎原样复用，接缝切在 Python 层
- [0020](0020-no-read-write-split.md) — 不把 `Phone` 拆成读屏与输入两个 adapter
- [0021](0021-readback-verdicts.md) — 回读判定出 `Phone`：每条目标一个结局，不与渠道那边共用类型
- [0022](0022-launch-foreground.md) — 启动期间的前台归属：读不出不算离开，连续外占才停段
- [0023](0023-not-run-steps-in-results.md) — 没执行的项也进结果：rc=0 + `skipped`，原因由客户端按选择页给出
- [0024](0024-off-title-fallback.md) — 补点两轮仍不动时，`off()` 回退到点行标题
- [0025](0025-site-shared-css.md) — 官网两页的共享样式收进 `site.css`，由生成器渲染进页面，页面仍是单文件
- [0026](0026-retry-failed-steps.md) — 结果页重试：按步骤 kind 合并，广告开关步按失败段名重跑
- [0027](0027-guard-mode.md) — 守护模式：独立只读复查，按锁屏状态分路，结局分四档
- [0028](0028-agent-audience-boundary.md) — 两个 agent 受众：`AGENTS.md` 是产品交付物，维护规范另有一处
- [0029](0029-recipe-preamble-injection.md) — 机型脚本的前导由引擎注入
- [0030](0030-in-app-update.md) — ADR-0030：三端应用内更新，共用清单和下载判断
- [0031](0031-harmony-desktop-integration.md) — ADR-0031：鸿蒙能力并入统一桌面客户端
- [0032](0032-reference-recipe-version-core.md) — ADR-0032：固定参考与同族脚本同池比版本核心
- [0033](0033-phone-phase-modules.md) — ADR-0033：`Phone` 按阶段拆成两个基座与五个阶段
- [0034](0034-recipe-source-facts.md) — 机型脚本的事实由一份纯 AST 层给出
- [0035](0035-recipe-steps-injection.md) — 机型脚本的段体由引擎注入
- [0036](0036-tool-gh-session.md) — 工具层的 `gh` 只经一处会话模块
- [0037](0037-recipe-declarative-loader.md) — 机型脚本按模块装载：声明式段、单一装载器与这次执行
- [0038](0038-recipe-catalog.md) — 机型脚本的终态：页面树数据 + 运行时 + 家族策略 + 本机例外
- [0039](0039-claude-md-startup-index.md) — `CLAUDE.md` 是启动索引：函数级细节归 `docs/ARCHITECTURE.md`
- [0040](0040-library-name-table-owner.md) — `recipe_lib` 是库名字表的唯一 owner：三个稳定 import 面只是兼容壳
- [0041](0041-tool-engine-devtools-seam.md) — `tool/` 是出厂引擎、`devtools/` 是仓库工具链：边界由目录本身表达
- [0042](0042-family-carried-test-cases.md) — 测试用例由「族」承载：让删除成为可判定动作
- [0043](0043-mutation-as-sufficiency-criterion.md) — 测试充分性由变异测试判定：覆盖率管执行，mutation 管断言
- [0044](0044-channel-snapshot-intent.md) — 渠道引擎沿「观察 → 决定 → 动作」再切一刀：屏幕快照与意图
- [0045](0045-device-vocabulary-script-surface.md) — 设备词汇与脚本面边界：门面补动词、catalog 收 shell
