# 一页的拨动计划归 plan_switches()：策略与点击循环分开

基线 `5251839`。

`tool/fast.py` 的 `off()`（基线 `5251839` 的 :656-734；改后自 :693 起）里，「这一页该拨哪些开关」与点击、回读、重试、翻页、打印叠在一起：目标选择（`want_state` / `keep` / `only` 名单 / 保护类放行 / `safe_mode`）、屏带过滤（8% / 98.5%）、点击节奏、三次重试、离开页面检测、`changed` 记账。屏带与 `checked` / `kept` 只落在汇总行里，没法单独断言。

## Decision

**目标选择收口为纯函数 `plan_switches(rows, keep=(), only=None, safe_mode=False, *, screen_h, disabled=None) -> SwitchPlan`；`off()` 只做点击 → 回读 → 重试 → 报告。**

`SwitchPlan` 是 frozen dataclass，四个字段：`targets`（`(标题, xy, want)`，只含需要点击的行）、`checked`（过了筛选的标题，含已在目标态、落在带外与因灰没点的）、`kept`（安全模式放过的普通开关）、`disabled`（因灰没点的标题）。

- `screen_h` 无默认值，屏带过滤留在策略里；带外行仍算 `checked`，只是不进 `targets`。
- `targets` 保持 `switches()` 的输入顺序；`checked` / `kept` 用 `frozenset`，调用方按屏并集。
- `want_state()` 与 `TRACK_WORDS` 不搬走：极性判据仍直接单测（`tests/test_regressions.py` 的 `test_protection_polarity`）。
- `off()` 的签名、人话、`p.changed`、退出码，以及点击顺序与「首下单独点」的节奏逐字不变。
- `disabled` 是调用方注入的「这个落点的开关是不是灰的」谓词（#333），`plan_switches()` 自己不读屏；`off()` 传的是按当前页面树判定的闭包，`chan_fast` 与它共用 `tool/row.py` 的 `disabled_at()`。判断规则：同一屏同名行**全部**为灰才算灰（双列卡片可能一灰一正常，不能把一个的失败当成另一个的灰态吞掉）；灰行不点击、不算失败，但仍算 `checked`。
- 页面加载期开关可能短暂不可用：`off()` 计划期发现灰行会再读一页确认，仍灰才跳过。

**两处语义只记录、不改代码：**

1. `only` 名单外只放行 `TRACK_WORDS`（广告 / 跟踪 / 追踪）的保护类开关。「关闭个性化推荐」虽然 `want_state` 也是 `True`，但没命中追踪词，名单外不动。整理一个具体条目时，顺手打开无关的个性化推荐属于越界。
2. `safe_mode` 只在 `only is None` 时抑制普通开关。给了 `only` 时按名单拨动，并且仍享受第 1 条的追踪放行——这是「安全模式不做任何猜测性点击」的唯一例外。`only` 本身就是参考脚本点名的集合；打开追踪保护不属于猜测性关闭。

## Considered Options

- **纯函数 + 冻结值对象**（采纳）vs **留在 `off()` 里加注释**。后者能保住行数，但屏带、`checked`、`kept` 继续只能靠跑完整点击循环测。
- **纯函数带 `screen_h`**（采纳）vs **带过滤留在驱动**。后者保住「纯函数只谈标题」，但换页时 `self.H` 会变，带过滤与目标集合会分处两层。
- **`SwitchPlan` 多字段**（采纳）vs **只返回 `targets`**。后者复现不了「核对 N 项」与安全模式文案；`checked` 含已在目标态与带外的行，不能由 `targets` 推出。第四个字段 `disabled` 是 #333 追加的：灰行不进 `targets`，但要单独说明，还要参与跨屏去重。
- **只动 `tool/fast.py`**（采纳）vs **新开模块**。新模块要么复制 `want_state` / `TRACK_WORDS`，要么把它们搬走并改更多调用点。

## Consequences

- **测试面分开**：策略在 `tests/test_switch_plan.py`，驱动在 `tests/test_phone_interface.py` 的 `OffDriverTests`；每个桩配 `assert_called*`。
- **对拍扩到 `SIZES × safe_mode × only`**，样本按屏宽高参数化。守卫按场景断言点到哪些标题、带外行一次不点、静态页重试确实补点；基线钉 `5251839`。
- **`CONTEXT.md` 补「拨动计划」**，并给「安全模式」补第 2 条例外。
- **灰态判定只有一份**：`tool/row.py` 的 `disabled_at(root, xy)`；`chan_fast.disabled_at(p, xy)` 只是它的前向壳，两边不各写一套。
- **本票不做**：点击 / 回读 / 重试分层、`run()` 的 fold、`recipes/` 解冻。
- **没有真机可验。** 验收是单元回归加改前改后对拍，与 ADR-0002 / ADR-0005 同一标准。
- **2026-11-02（#480）之后节奏不再逐字不变**：目标改成从下往上点，首击后多一次坐标核对，页面重排时剩下的目标改为点前重读。`plan_switches` 的策略面与「首下单独点」保留。
- **2026-11-02（#486）之后回读记账不再逐字不变**：点过的普通开关行从回读里消失、回读仍见到本屏计划时的非目标行且没跳走，按已关记入 `changed`，日志缀「（点后从列表消失）」；整页读空、跳走（含同 Activity 的子页）与保护类开关的消失仍报失败。同名双列的判定、补点与灰态都按每行状态算，不取最后读到的那一行；补点不跨页。
