# 一次渠道到达归 ChannelPage：到页与认行是一件事

基线 `e1a8001`。「走到某个渠道页」和「认出这一行的开关」散在 `tool/chan_fast.py` 的十一个函数里，不是架构体检报告说的六个：`notification_focus():277`、`titled():297`、`top_title():302`、`group_floor():319`、`off_screen_name():324`、`allow_switches():338`、`channel_switch():360`、`inline_switch():385`、`page_switch():437`、`wait_page():444`、`via_app_page():460`；此外 `page_hint():555` 只在失败时补一句诊断，`toggle():597` 把它们串起来。

历次 ROM 适配都落在这片：华为同名行（#287）、vivo 两页同一个 Activity、ColorOS 独立宿主包。每次补丁只改其中一两个函数，其余九个不会跟着变，所以「下次适配该改哪里」没有答案。

## Decision

**一个 `ChannelPage` 拥有「到达」，`toggle()` 只做拨动。**

`ChannelPage(p, name, pk="", cid="", vivo_app=None)` 是**有状态对象**：`vivo_app`（从应用通知页记下的 App 名，用来区分 vivo 的总页与渠道页）是一次到达过程的中间状态，不是整批的、也不是某一次读屏的。两个出口：

| 方法 | 职责 | 基线对应 |
|---|---|---|
| `open(rounds=12)` | 选路线、发深链、必要时转应用通知页、等到认得出 | `toggle()` 的 :610-619 加上 `wait_page`、`via_app_page` |
| `refresh(rounds=6)` | 只在当前页重认一次，不导航 | 点击循环与 `undo()` 里的 `wait_page(rounds=6)` |

返回 `Reached(switch)` 或 `Unreached(stage, why, hint)`。

**路线决策收进 `open()`。** 基线里「能不能直达」的两条判据——`truncated(cid)`（系统把长渠道 ID 缩略成 `com.se...`，不能钻）与 `p.vivo_seen`（这台机器渠道页与应用通知页同一个 Activity，只能从列表进）——连同 `am start` 命令一起从 `toggle()` 上移。不这样收，「到达」就不含「怎么到达」，新 ROM 的适配仍要改两处。

**诊断是返回值，不是外部袋子。** `why` / `stage` / 页面结构摘要（原 `page_hint()`）归 `Unreached`，因为「为什么没到」是 `open()` 自己知道的最后事实；`page_hint()` 因此降级成一行的前向壳，实现在 `ChannelPage._hint()`。`Attempt` 不删——它被 7 个测试文件直接断言、被对拍脚本记录——但**降级为旧接口的数据袋**：`ChannelPage` 不读不写它，由一行的前向壳搬运。`Unreached` 不复制 `vivo_app`：那是到达过程中的中间状态，留在对象上就够，没人从失败结果里读它。

**旧函数名保留为一行的前向壳。** `channel_switch` / `inline_switch` / `page_switch` / `wait_page` / `via_app_page` / `page_hint` 被 7 个 `tests/test_*.py` 直接调用（数法：`grep -rlE 'chan\.(channel_switch|inline_switch|page_switch|wait_page|via_app_page)' tests` 命中 8 个文件，减去探针脚本 `compare_chan_pages.py`）；探针本身也必须能在冻结基线与新实现上跑同一份代码。改名会把「对拍脚本改对了没」变成新的失效点，与 ADR-0002 保留 `Phone.d` 写穿别名是同一个判断。要改的只有那些**桩住 `toggle()` 内部**的用例：它们的缝从模块函数挪到了 `ChannelPage` 的方法（`refresh` / `_enter_app_page` / `_hint`），不跟着改的 patch 会静默失效。

**等待预算按次数，挂在调用点上。** `open()` 默认 12、`refresh()` 默认 6，与基线一致；`tool/wait.py` 已写明这里不能换成秒（慢机型会提前放弃）。

**`disabled_at()` 留在 `toggle()`。** 「开关是灰的」问的是这个开关能不能拨，不是有没有到这一页；它还要额外读一次屏，放进 `open()` 会让到达变贵、时序也变。

**`p.systemui_text` / `p.vivo_seen` 仍归 `Phone`。** 写入点从模块函数搬进 `ChannelPage._focus()`（`notification_focus()` 降级为一行的前向壳），归属不变，守 ADR-0002。

**错误契约不变。** `ScreenLocked` / `DeviceLost` / `StopBatch` 照旧重抛，读屏抛的 `RuntimeError` 照旧冒泡给 `toggle()` 的宽 `except` 转成 `Outcome(ERROR)`。把「读屏失败」收成 `Unreached` 会让报告者看到「跳过」而不是故障，与 `CONTEXT.md` 里「未确认 = 不知道」的定义冲突。

## Considered Options

- **有状态对象**（采纳）vs **纯函数 + 返回值携带全部状态**。后者的 `Reached` 要同时装下「当前开关」与「重认所需的一切」，等于把 `vivo_app` 藏进返回值再取出来。
- **一行前向壳**（采纳）vs **彻底改名并同步改测试与对拍脚本**。见上：对拍的探针必须在两边都能跑。
- **`open()` 吸收路线决策**（采纳）vs **只认页、发命令留在 `toggle()`**。后者保住了 `toggle()` 的行数，但把「该不该直达」这条最常被 ROM 改动的判据留在收口之外。
- **诊断进 `Unreached`**（采纳）vs **`ChannelPage` 继续写 `Attempt`**。后者只是把写 `at` 的代码搬了个位置，报告指出的「`stage`/`why` 是补丁」没有变化。
- **`disabled_at` 留 `toggle()`**（采纳）vs **`Reached(greyed=)`**。见上。

## Consequences

- **前向壳会长期留在 `chan_fast.py`。** 它把测试面与实现解耦：摘掉壳的前提是测试与对拍脚本都改到新接口，那是一次独立的改动，不是本 ADR 的一部分。往壳里加新逻辑等于绕过收口。
- **对拍要扩到编排层。** `tests/compare_chan_pages.py` 原来只比认页层的三个函数，而这次动的是「深链发不发、失败转不转应用通知页」。新增一段 `toggle()` 探针，比结局与文案、`am start` 命令、点击坐标与次数、滑动次数：九类场景 × 两种屏尺寸 —— 直达 / 应用通知页 / 内联 / 同名放弃 / 截断 ID / vivo 六条路线，加锁屏 / 读屏报错 / 断线三条失败路径。页面坐标按屏宽高取比例，否则 720 那一边的开关落在屏外，六个场景会一起变成「没认出」，守卫数字就不再证明走到了哪条分支。每条分支各设一个断言（认出开关、点了渠道行、放弃、跳过深链、三种失败各一条），任一条一组都没走到就以非零退出。
- **`p.focus()` 的调用次数允许减少、不允许增加**；`dumpsys` 走 `p.reader.shell`，已在 `shells` 里逐条比对。本轮实测 0 组变化。
- **`CONTEXT.md` 补两个词**：「渠道页」与「到达」。
- **本票不做**：`run()` 批处理的 fold、`fast.py` 把「该拨哪些开关」抽成纯函数、`recipes/` 解冻。
- **没有真机可验。** 验收是单元回归加改前改后对拍，与 ADR-0002 / ADR-0005 同一标准。

## 增补：到达的路线与逐帧下一步搬出 `ChannelPage`（#1409，接管）

[ADR-0044](0044-channel-snapshot-intent.md) 沿「观察 → 决定 → 动作」把渠道引擎再切一刀：`ChannelPage` 仍拥有一次到达（入口、诊断与 `vivo_app` 这个中间状态），但**路线选择与逐帧的下一步**改成 `tool/channel_arrive.py` 的纯函数（`route()` / `page_step()` / `after_click()` / `scroll_fallback()` / `after_scroll()`），认页与认行判定在 `tool/channel_decide.py`；`open()` / `_enter_app_page()` 只取快照、执行意图、把进度带回去。本文记的前向壳与「一个对象拥有到达」的结论不变；上面「本票不做」里的 `run()` 批处理 fold 由 #1437 接管。
