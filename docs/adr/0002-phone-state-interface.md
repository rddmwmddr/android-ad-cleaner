# 一次渠道尝试的诊断归 chan_fast，读屏策略归 Phone

> **后续**：[ADR-0045](0045-device-vocabulary-script-surface.md) 之后，本 ADR 给出的 `Phone.reader` 命名与 `Phone.d` 写穿别名都已从门面退场（读 `p.conn.reader`，脚本走门面动词）。「只命名、不收窄」这条判断仍是当时的取舍记录，正文不复改。

`Phone` 上原本挂着六个别人写、别人读的字段：`sysui`（读屏要不要算 systemui 的文字）、`vivo_seen` / `vivo_app`（vivo 的两页同一个 Activity）、`why` / `stage`（这次渠道尝试卡在哪）、`pkg_now`（探路时前台是哪个包）。读的地方一律 `getattr(p, "x", 默认值)`，写名字写错也不报错，只静默少一段诊断；测试只能 `.__new__` 之后逐项赋值，28 处、10 个文件。`AAC_REF` 环境变量同样改写 `off()` 的语义。

这次把它们按**生命周期**拆开：一次渠道尝试内的诊断（`why` / `stage` / `vivo_app`）归 `chan_fast` 的 `Attempt`；读屏策略与设备记忆（`systemui_text` / `vivo_seen`）归 `Phone` 构造处声明；`pkg_now` 消失，改成 `entries(p, pkg)` 的参数；`AAC_REF` 变成 `Phone.safe_mode`。

## Considered Options

- **按生命周期拆**（采纳）vs **一个 `Session` 装下全部**。后者看着更「深」，但那六个字段有三种寿命：每次认页重置、整批粘滞、一次尝试。混在一个袋子里，正是 `toggle()` 每次开头手工清空 `vivo_app / why / stage`（原 `chan_fast.py:551`）这个补丁存在的原因。
- **诊断归 `chan_fast` 的 `Attempt`**（采纳）vs 全声明在 `Phone` 上。前者的消费者（`channel_switch` / `inline_switch` / `via_app_page` / `wait_page` / `undo` / `toggle`）全在同一个模块里，搬过去是真正的 locality；后者只是把 `getattr` 换成声明，接口照样宽。
- **`sysui` 做成 `texts()` 的参数**（否）vs 声明成 `Phone` 的字段（采纳）。参数化要求每个 `texts()` 调用点自己知道页面身份，等于反复调 `notification_focus()`（每次一次 `dumpsys`），行为和耗时都变。
- **读屏 adapter 只命名、不收窄**（采纳）vs 直接收成 `shell` / `dump_hierarchy` / `window_size` / `screenshot` 四个方法。`Phone` 同时管读屏与打字（`jsonrpc`、`self.d(selector)`），不先把这两件事拆开就收窄，只是换个名字。`p.d` 保留写穿 property：`recipes/` 里 85 处 `p.d.xxx` 与测试的 98 处引用都不动。
- **`AAC_REF` 改成参数**（采纳）vs 保留环境变量。它跨的进程边界只有 `run.py recipe` → `fast.py run` 一跳，`recipes/` 里 0 处引用；改成 `fast.py run [--ref]` 不需要额外的兼容层。

## Consequences

- `Phone.__init__` 声明了 `safe_mode` / `systemui_text` / `vivo_seen`，`pause_at_lock_check` 的 `getattr` 兜底一并去掉：忘了初始化的 `.__new__` 装配会在第一次读的时候炸，而不是静默走默认值。
- `tests/fixtures.py` 的 `phone_stub()` 成为这些默认值的唯一装配点，只有一处偏离构造处：`pause_at_lock_check` 默认 `False`，因为假手机后面没有客户端在点「暂停」。屏尺寸 `W` / `H` 与读屏 adapter 不设默认，它们是每条用例的前提。
- `Phone.reader` 是 adapter 的名字，`Phone.d` 是它的历史别名（写穿 property）。`chan_fast.parse()` 仍然收 `ShellPhone`——那是 adb 连接自带的 `d = self`，不是 `Phone`。
- 没有真机可验，验收是单测加改前改后对拍，驱动在 `tests/compare_phone_state.py`（把改动前的 `tool/` 导出成基线，一条命令跑两边）：`texts()` 228 组（页面样本 × 两种屏尺寸 × 策略开 / 关）、`entries()` 116 组（页面 × 包名）、`off()` 2 组（安全模式开 / 关），逐项一致。守卫：翻策略有 2 组输出真的变了，换包名有 2 页输出真的变了，安全模式把同一页的点击从 6 次降到 3 次。
