# 渠道引擎沿「观察 → 决定 → 动作」再切一刀：屏幕快照与意图

基线 `ebf97120`（spec #1409 的集成分支尖端）。七个子票：#1431（阈值 owner）、#1432（四个值类型与唯一执行点）、#1433（结局封闭枚举）、#1434（认页决策）、#1435（到达决策）、#1436（拨动决策）、#1437（批处理 fold），收口是 #1438。

## 问题

[ADR-0020](0020-no-read-write-split.md) 把本仓库的复杂度写成沿**观察 → 决定 → 动作 → 报告**分布，并且已经沿这条线切过：`row.py` / `wait.py`（观察）、`plan_switches()`（决定，ADR-0008）、`off()`（动作）、`ChannelPage`（到达，ADR-0007）、`events.py`（报告，ADR-0004）。渠道引擎是例外：它的每个阶段都在同一棵活树上既判断又点击，认页、到达、拨动、批处理全在「读一屏 → 决定点哪 → 点 → 再读」的同一个循环里（`main` 的 `tool/chan_fast.py` 1255 行）。于是：

- **判断错误只能上真机复现。** 近期 bug 的根因全在这一层：回读误报（#486）、同坐标开关（#531）、确认框时序（#555）、判据词（#604）、✕ 误点（#378）、同名行误认（#1120）。判断没有可替换的接口，喂一份录下来的页面去断言「该点哪一行」这件事做不到。
- **几何阈值散在六个模块里。** `0.22H` 有五个副本（`row.TOP_BAND` 一处、`chan_fast` 四处），另有 0.18 / 0.15 / 0.4 / 0.2 / 0.08–0.985 / 0.3 / 0.12 / 0.85 / 0.92 / 0.975 各一到两处。屏幕带比例要变时，满仓找不到同一个数。
- **结局是裸字符串。** 15 个 kind 定义在一处、`RULES` 是唯一记账表，但 kind 没有类型，拼错只在跑到那一支时炸，并静默产出一个空结局。
- **批处理从来没有被切过。** `run()` 的队列构造、两趟判定、重试挑行与收尾复查与点击、adb 往返、打印交织在一起，只能跑一整批看输出。

## Decision

**一次读屏产出一份屏幕快照；决定是快照上的纯函数、输出意图；动作只有一个执行点。**

### 一次读屏产出 `ScreenSnapshot`

`tool/screen_snapshot.py` 定义四个值：`ScreenSnapshot`（前台包与 Activity、屏宽高、开关行、文字、文字签名、还能不能往下滚）、`ChannelList`（通知清单）、`Intent`（对设备的一个动作）、`Progress`（跨帧累积）。快照与意图是 frozen 的，带 `to_json()` / `from_json()`——「喂一份 dump → 断言意图」的用例输入就是这个格式。`Screen.snapshot()` 只读一次树、一次前台，行与文字的取法仍只有一份（`text_hits()` / `switch_row_data()`，与 `Screen.texts()` / `Screen.switch_rows()` 同源）。只认标题的调用点传 `with_rows=False`：不算行，也就不给自绘开关多截一张图。

### 决定是快照上的纯函数，输出意图

`IntentKind` 是封闭枚举（`TAP` / `SCROLL` / `BACK` / `OPEN` / `HOME` / `TYPE` / `SETTINGS`），等待与重试不属于意图。四个决策模块都吃快照或通知清单，不读屏、不点击、不 import `fast` / `chan_fast` / `phone.*`：

| 模块 | 决定什么 |
|---|---|
| `tool/channel_decide.py` | 认页、页眉、组底、屏外名、可拨名单（#1434） |
| `tool/channel_arrive.py` | 第一段走哪条路线（直达 / 应用通知页）、应用通知页上这一帧的下一步、动作回来之后怎么收场（#1435） |
| `tool/channel_toggle.py` | 这一行点不点、点完算不算成、点后消失与灰态各算什么（#1436） |
| `tool/channel_batch.py` | 一项的结局与记账表、清单 → 队列、两趟门槛、重试挑行、收尾复查豁免（#1437） |

### 动作只有一个执行点

`Screen.apply(intent)` 按种类分派到基座的动作原语；`ChannelPage` 与 `run()` 只取快照、`apply()` 意图、把诊断与进度带回去。这是**渠道引擎自己的**动作出口：`launcher` 与设置搜索用裸 `am start` 绕过基座、文本输入走读屏适配器，那两处不在本决定内（ADR-0020 的「不做」保持）。

### 通知清单与快照分开

`ChannelList` 来自一次 `dumpsys notification`，不是当前这一屏，所以不塞进快照。按包探测的两项（通知权限状态、appops 模式）也不预读：它们是一次额外 adb 往返，eager 化会改变调用次数，也就是行为。

### 进度显式跨帧

`Progress`（已点标题、页数、上一帧签名、试过的走法）由循环持有、逐次传入传出，**不进快照**：快照是一屏的事实，历史是循环的事实。调单帧判断的用例不用先喂一串页面。

### 阈值一个 owner

判定用的比例收进 `tool/geometry.py`（20 个常量），`row` / `fast` / `chan_fast` / `phone/screen` / `phone/toggler` / `phone/dismisser` / `phone/navigator` 都从它取；数值一个不改（#1431）。

### 结局是封闭枚举

`OutcomeKind` 与 `RULES` 搬进 `tool/channel_batch.py`：15 个成员是 `StrEnum`，`RULES` 仍是唯一一张「怎么记账」的表，`chan_fast` 显式 re-export 旧名字。

## 当时为什么不做、现在为什么做

三份旧决定都记过「不做」：

- **ADR-0007** 的 Consequences 写「本票不做：`run()` 批处理的 fold」——那一次只把「到达怎么走」收进 `ChannelPage`，批处理留在 `run()` 里。
- **ADR-0008** 的 Consequences 写「本票不做：点击 / 回读 / 重试分层」，它记下的理由是成本：把判定抽出 `off()` 要么复制 `want_state` / `TRACK_WORDS`、要么搬走并改更多调用点。
- **ADR-0033** 把渠道那套结局词表记成「留给后面单独的决定」——那次只拆 `Phone`，渠道侧一行不改。

这次能做，靠的是两件此前没有的东西：

1. **「决策纯、I/O 在驱动」已经有了先例。** `tests/test_row.py`（内联 XML → 纯几何判定）、`tests/test_switch_plan.py` 与 `tests/test_off_readback.py`（策略纯函数 + 注入谓词）证明这个形状在本仓跑得通，只是渠道引擎还没用上；把判断抽走不再是赌一个新的测试形态。
2. **零行为变化可以被证伪。** 对拍驱动从 #1431 起支持钉基线提交（`tests/compare_chan_pages.py --baseline <SHA>`：认页 / 进页 / 编排三层 × 两种屏尺寸，同一份探针分别跑冻结基线与当前 `tool/`）。在此之前，「结构变了、行为没变」只能靠人读 diff；现在每一票不零差异就得停下来另议。这个能力也是分层顺序（认页 → 到达 → 拨动 → 批处理，每票只动一段）成立的前提。

另有一笔账：结局词表与批处理 fold 各被推后过一次，而它们与本次同属一个概念——**这一项最后的结局是什么**。再分开做，就要把同一个取舍重新论证一遍。

## 接管了哪些旧结论

| 旧决定 | 这次接管了什么 |
|---|---|
| [ADR-0007](0007-channel-page.md) | 「一个 `ChannelPage` 拥有到达」保留为执行壳：它仍拥有一次到达的入口、诊断与 `vivo_app` 这个中间状态，但**路线与逐帧的下一步**已搬到 `channel_arrive` 的纯函数，「到达」不再等于「怎么到达」的实现。`run()` 批处理的 fold 由 #1437 接管。 |
| [ADR-0008](0008-switch-plan.md) | 「本票不做：点击 / 回读 / 重试分层」里的点击层由本决定接管（渠道侧）；回读那层已由 ADR-0021 落地。`run()` 的 fold 同 ADR-0007。 |
| [ADR-0021](0021-readback-verdicts.md) | 「回读判定出 `Phone`」是这一刀的先例，这次把同一做法沿用到渠道。它的「不与渠道共用类型」结论**保留**，判据见下一节。它记的 `chan_fast → fast` 反向依赖仍在（`chan_fast` 仍 `from fast import Phone`），所以两套结局空间今天也合不到一处。 |
| [ADR-0020](0020-no-read-write-split.md) | 结论不变，另加一小节说明本决定沿的是它写下的那条阶段轴，不是被它拒绝的读写拆分。 |

## 判据：什么时候允许新开一套结局词表

今天并存四套词表，不统一：

| 词表 | 项数 | 出处 | 回答什么 |
|---|---|---|---|
| 渠道一项的结局 | 15 | `tool/channel_batch.py` 的 `OutcomeKind` / `RULES` | 这一项最后怎么了，以及它对整批怎么记账 |
| 回读 | 4 | `tool/phone/toggler.py` 的 `REACHED` / `VANISHED` / `MISSED` / `GREYED` | 这一下点击生效了没有 |
| 守护复查 | 4 档 | [ADR-0027](0027-guard-mode.md) 的「被改回 / 找不到 / 灰的 / 未确认」 | 现在还是不是目标态 |
| 任务「没执行」 | 三档原因 | `gui/tasks.py` 的 `plan_tasks()` | 这一项为什么没跑 |

**判据：只有粒度差一个量级、且无法共用一个记账表时，才允许新开一套词表。** 同名不同义比同名复用更坏——复用会让两边的记账互相顶替，而拼错一个名字的代价只在跑到那一支时才现形。

逐条对照：

- 渠道那 15 项每一项都带五件横切账目（`fail_close` / `fail_open` / `retry` / `toggled` / `exempt`）；回读与守护复查都没有方向、没有批次，也没有「拨了 N 个」。
- 回读问「这一次点击」，守护复查问「现在还是不是目标态」，两者发生在不同的执行里（ADR-0027）；并成一套会让「点了没生效」与「后来被改回」变成同一个说法。
- 「没执行」是计划侧的原因（用户没勾、这台机本来没有、通知没扫成），不是设备侧结局，而且它在 `gui/` 侧生成，引擎根本看不到。
- 反例：渠道的 `GREYED` 是「系统锁定、收尾复查豁免」，回读的 `GREYED` 是「没到目标态且开关是灰的」；渠道的 `MISMATCH` 是「界面状态与渠道实际状态不一致」，回读的 `MISSED` 是「没到目标态」。这几对都推不出对方，谁也不能顶替谁。

将来真要新开第五套，先回答三问：它回答的问题是不是前四套之一换个说法；它的每一项能不能落进某一张已有的记账表；把两套并起来是不是要么丢信息、要么长出一堆只有一边用的字段。三问都过了才新开。

## Considered Options

- **快照 + 纯决策 + 唯一执行点**（采纳）vs **只把阈值与结局枚举收口**。后者改动面小，但判断仍在循环里，判断类 bug 仍只能上真机复现——那正是这一层的全部问题。
- **`ChannelList` 进快照**（否决）：它来自 `dumpsys`，不是这一屏；塞进去会让每一份 dump 都拖着一份通知清单，也会诱导把额外 adb 往返提前。
- **进度进快照**（否决）：快照必须是一屏的事实；历史进快照，调单帧判断就得先喂历史，用例立刻变回「造整台手机」。
- **分帧决策 + 循环执行**（采纳）vs **每帧一个大函数返回完整计划**。前者让每条边界用例只断言一帧的意图；后者会把收场信号、诊断与进度一起塞进返回值。
- **批处理留在 `run()`、只抽结局枚举**（否决）：两趟门槛与重试挑行是这一层里最常被讨论的策略，留在循环里就只能整批对拍。
- **统一四套词表**（否决，见上一节）：粒度差一个量级，同名不同义。

## Consequences

- **`chan_fast.py` 1255 → 1067 行，引擎多六个模块**（`geometry` / `screen_snapshot` / `channel_decide` / `channel_arrive` / `channel_toggle` / `channel_batch`），引擎名单从 37 个顶层模块变为 43 个，`tests/test_tool_package.py` 的 `ENGINE` 与 [ADR-0041](0041-tool-engine-devtools-seam.md) 的计数同步。
- **三条新守卫**在 `tests/test_rules_guards.py`：`ChannelDecideGuards`（四个决策模块不 import 引擎 / 基座、不调用动作原语）、`ChannelOutcomeGuards`（枚举成员 ≡ `RULES` 的键，往回加一个假 kind 即红）、`GeometryGuards`（比例字面量只许出现在 `tool/geometry.py`）。前两条登记进规则注册表（`dev.channels.decisions-are-pure`、`dev.channels.outcome-enum`）。
- **新用例从 dump 进、从意图或输出出**：`tests/test_channel_snapshot.py` / `test_channel_decide.py` / `test_channel_arrive.py` / `test_channel_toggle.py` / `test_channel_batch.py`。既有「桩住 `p.click` 读 `call_args_list`」的写法保留，它们断言的是接口。
- **前向壳仍留在 `chan_fast.py`**：`channel_switch` / `inline_switch` / `page_switch` / `wait_page` / `via_app_page` / `page_hint` 被 8 个测试文件与对拍探针直接调用（ADR-0007），往壳里加逻辑等于绕过收口。
- **`tool/phone/` 的五个阶段没有重构**：只在基座新增了快照产出（`Screen.snapshot()`）与唯一执行点（`Screen.apply()`）。ADR-0033 的形状原样保留。
- **零运行时行为变化**：用户可见文案、CLI 参数与退出码、「拨了 N 个」计数、`p.*` 面与 `huawei_channels` 依赖的三个名字（`ShellPhone` / `parse` / `truncated`）都不动。证据是每票合入前后对拍零差异，不是代码形状。
- **不统一四套结局词表**，只把「何时可新开一套」写成上面的判据；`AGENTS.md`（交付给用户侧执行 agent 的手机操作手册）不动。
- **没有真机可验。** 验收是单元回归加改前改后对拍，与 ADR-0002 / ADR-0005 / ADR-0007 / ADR-0008 同一标准。
