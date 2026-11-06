# 系统设置搜索的直达动作留在引擎的 `Phone.setting()`：先试动作，失败即回设置首页

基线 `32449eca`（#650）。

ColorOS 的 `oplus.intent.action.settings.MAIN_SEARCH` 能直接打开系统设置的搜索页，输入框已聚焦。
旧路径是「`am start` SETTINGS → 找搜索框文字 → 点框 → 等输入框」，每一步都要一次读屏。

## Decision

**引擎在 `Phone.setting()` 里先试 `SEARCH_ACTION`；`am start` 退出码非零或输出带
`Error` / `unable to resolve` 就立即回退到设置首页的老路。** `path=` 按结果下一行的位置文字
挑同名结果。

- 动作常量是 `Phone.SEARCH_ACTION`，只放 ColorOS 这一条。
- 成败看 `am start` 的退出码，不等「期望页面出现」：没有这条路的机型当场返回，不白等 2.5 秒。
- `path` 依赖「位置文字紧跟在结果下一行」；布局变了会静默回落到慢菜单，不会误点。

## Considered Options

- **每个机型脚本自己起 action**：同一条 shell 命令要在 12+ 个调用点复制，`entries.reach()`
  的诊断路径也用不上。
- **放进 `entries` 的品牌表**：那张表是给人看的入口清单，`Phone` 不认识品牌，脚本也不 import 它。
- **先等页面再判成败**：非 ColorOS 每处 `setting()` 白等 2.5 秒；vivo V2303A 每进一个子页都
  重新 `p.setting()`，会被放大。

## Consequences

- 非 ColorOS 的每次 `setting()` 多一次 `am start`，退出码非零即返回，代价是一次 shell 往返。
- 其它 ColorOS 机型（一加、真我、PHK110 / PLG110）自动受益，不用改脚本。
- 没有真机 dump 佐证 `path` 的下一行形态；PMX110 上的 4 秒是贡献者实测，维护方未复跑。
