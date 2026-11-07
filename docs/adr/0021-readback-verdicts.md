# 回读判定出 `Phone`：每条目标一个结局，不与渠道那边共用类型

基线 `91fda6b`。前置是 [ADR-0008](0008-switch-plan.md)，它把「这一页该拨哪些开关」收成 `plan_switches()`，并明写「本票不做：点击 / 回读 / 重试分层」。本票做掉其中「回读」这一层。

`off()`（`tool/fast.py`）里回读与补点的判定原本是两个闭包：`wrong()` 返回 `still / grey / vanished` 三个 set，调用方拿回来手工做 `page_greyed |= grey`、`if t in still and t in grey: continue`。同一个概念（这一项最后的结局是什么）在 `tool/chan_fast.py` 里已经是值对象 `Outcome` + 13 种 kind + `RULES` 表。两边形态不一致本身不是问题，问题是 `off()` 那段判定只能整段跑：要断言一条边界，得先用页面时间轴编排一串换页。

## Decision

**回读的结论改成「每条目标一个结局」，判定抽成模块级纯函数，放 `tool/fast.py` 靠 `SwitchPlan`。**

- 四个结局：`REACHED`（到了目标态）、`VANISHED`（点过之后整行从列表消失，按已关记账，#486）、`MISSED`（没到目标态）、`GREYED`（没到且开关是灰的，#333）。前两个算拨到；`GREYED` 单列一档，因为它的说法与失败不同（「被上级开关禁用」而不是「关不掉」）。
- `readback(targets, rows, *, clicked, others, page_same, disabled) -> {标题: 结局}`：不读屏、不点击。`rows` 由调用方读好传入，`disabled` 注入 `row.disabled_at`，与 `plan_switches()` 同一套写法。
- 结局**按标题合并**（同名双列共享一个结局，与原来 `states.setdefault(title, []).append(on)` 一致）；汇报与 `done` 计数仍按 `targets` 条目遍历，同名两条各打一行、各记一次。
- `page_same` 是零参数可调用对象，只在「点过、且行已从列表消失」时才被问——保持原来没有消失行就不读前台的惰性。
- 补点挑行同样出 `Phone`：`pick_retry_rows(targets, rows, still, disabled)` 一标题一行、跳过灰的、按状态而不是按标题挑（#403）。判灰的规则由 `still_greyed()` 一处给出，回读与补点共用。
- 三次回读之间夹着 `sleep(0.25 / 0.8 / 0.4)` 的收尾序列、以及灰态说明的跨屏去重（同一标题全程只说明一次）留在 `off()`，逐字不动。

## Considered Options

- **每条目标一个结局**（采纳）vs **把三个 set 包成一个 `Readback(still, grey, vanished)`**。后者几乎不改调用方：调用方照样要手工合并、照样要自己从 `still` 里减掉 `grey`，等于只换了变量名。
- **`fast.py` 内另定义**（采纳）vs **复用 `chan_fast.Outcome`** vs **挪到共享模块**。`chan_fast` 反向依赖 `fast`（`from fast import Phone, …`），复用必须先挪共享模块、动 `chan_fast` 的 import 面；且两个结局空间粒度差一个量级——fast 只关心「到没到目标态」，chan 还要区分渠道不存在 / 已删除 / UI 未暴露。同名不同义比同名复用更坏。
- **不建 `RULES` 表**（采纳）vs **照抄 `chan_fast.RULES`**。fast 的四个结局在汇报处就是四个分支，没有 `fail_close` / `fail_open` / `retry` / `toggled` / `exempt` 那样的横切账目；建表只会让两边看起来同构。
- **`page_same` 传惰性 thunk**（采纳）vs **改成必读参数**。后者每屏多一次 adb 往返，属于行为变化，不在纯重构的范围里。
- **保留三次回读的显式序列**（采纳）vs **改成循环**。那段时序被既有用例逐条断言（三个 `sleep` 值、`switches.call_count`、`focus.call_count`），循环化会一并改写读数次数。
- **只抽判定、行数降到 ~129**（采纳）vs **继续压到 ~80**。后者要动点击循环里的首击探测与 `shift` 重排，那是 #480 的时序逻辑，风险面比本票大。

## Consequences

- `off()` 155 → 129 行；新增 `readback()` 27 行、`still_greyed()` 7 行、`pick_retry_rows()` 14 行、`still_open()` 3 行。
- 新用例 `tests/test_off_readback.py` 直接喂 `rows` 与假谓词，不再需要页面时间轴；`tests/test_phone_interface.py` 里整段 `off()` 的用例一行不改，改前改后都绿。
- 对外人话输出、`p.changed`、返回值 `done`、退出码逐字不变（对拍 `tests/compare_phone_state.py` 的 `off` 分支 12 组零差异）。
- `CONTEXT.md` 的「回读」条目补一句结局词表；`CLAUDE.md` 的 `plan_switches` 指引补 `readback()` 与 `pick_retry_rows()`。
- **`chan_fast.Outcome` 不动**。两边仍是两套类型；将来若要统一，先解决 `chan_fast` → `fast` 的反向依赖。
- **没有真机可验。** 验收是单元回归加对拍，真机复测进下一版 `waiting-for-verify` 清单，与 ADR-0008 同一标准。
