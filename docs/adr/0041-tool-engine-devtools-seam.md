# `tool/` 是出厂引擎、`devtools/` 是仓库工具链：边界由目录本身表达

父票 #1389（C7），落地子票 #1390（判据与棘轮）与 #1391（物理搬移）。

## 问题

「哪些模块会随包发到手机上」今天没有任何模块边界表达它，只由打包脚本的 glob 决定。
`android/app/build.gradle.kts` 的 `syncEngine` 按整目录拷贝：

```kotlin
from(repo.resolve("tool")) { into("tool"); include("**/*.py", "*.dex") }
```

于是 `tool/` 下新建一个脚本——哪怕只是 CI 用的票号校验——它都会自动进 APK。同一处的 `gui/`
那一档已是**显式文件名清单**，即「包清单」这种写法仓库里早有先例；`tool/` 这一档却没有。
`tool/` 顶层 56 个模块里，19 个是只在 CI 与本机跑的仓库工具链（占 `tool/` 体积的 22%），
它们就这样被悄悄打进包。

`tool/` 这个名字的语义必须等于「出厂引擎」：打开目录就能判断一个脚本会不会随包，
而不是靠记住打包配置。

## Decision

### 边界由目录表达：`tool/` 引擎，`devtools/` 仓库工具链

- **出厂引擎**留在 `tool/`：随 APK 发到手机上，手机版与桌面版同一份。
- **仓库工具链**搬进新顶层目录 `devtools/`：只在 CI 与本机跑，不随包。

判据不是名字白名单，而是「路径 = 归属」：一个模块随不随包，看它在哪个目录。
`syncEngine` 是整目录 glob，把工具链文件搬出 `tool/`，包会自动收窄，打包脚本一个字不用改。

### 不用 `tools/`

`tools/` 与 `tool/` 只差一个 `s`，是最容易被后来人和 agent 认错的一对。`devtools/` 在语义上
与「仓库侧开发工具」对齐，与引擎目录不再形近。

### 工具链是**真包**、平铺、保留直接跑文件

- **真包**：`devtools/__init__.py` + 调用点写 `from devtools.claim import claim`。这批模块的调用点
  只有 CI workflow、`tests/` 与人肉命令，数量远小于引擎侧；真包让调用点自带出处，且 `devtools`
  是全新命名空间、零历史包袱。
- **平铺**：模块在 `devtools/` 下不再分 `checks/` `release/` `issue/`——二十来个一眼看得完，
  再分一层就要定第二套归类判据。
- **保留直接跑文件**：`python3 devtools/claim.py <票号>` 照旧可用，不改 `-m`。`-m` 要求 cwd 在
  仓库根、要改十几处文档与 CI，收益只是形式统一。

### `stdio` 是唯一的跨边依赖，方向是「工具链 → 引擎」

`tool/stdio.py`（标准流 UTF-8 的唯一出口）留 `tool/`：它随包、被引擎用。13 个工具链模块
`from stdio import use_utf8_console`，搬进 `devtools/` 后各自把 `sys.path` 指回 `tool/`，
`from stdio import` 语句一字不变。依赖方向只许「工具链 → 引擎」，引擎侧不 import 任何工具链模块。

### 两份冻结名单与三条守卫

`tests/test_tool_package.py` 冻结两份名单——引擎 43 个顶层模块、工具链 22 个顶层模块——
并用三条用例守它：

1. `tool/` 的顶层 `.py` 恰好是引擎名单，`devtools/` 的顶层 `.py`（除 `__init__.py`）恰好是工具链
   名单：两处都无遗漏、无多余，`devtools/` 还必须是真包。
2. 逐个 import 引擎模块（含 `phone/` `catalog/` 两个子包）后，`sys.modules` 里不得出现任何
   工具链裸名，也不得有 `devtools` 或 `devtools.*`——引擎 import 了工具链，那个模块就会随包发到手机上。
3. 打包清单不含 `devtools/`：`syncEngine` 的 gradle 文本里没有 `resolve("devtools")`，
   `gui.bundle_data` 的产物里没有 `devtools/` 开头的相对路径。

三条都承重：搬移后 `tool/` 只剩引擎，往它下面放一个工具链脚本或把依赖反着引都会报红。判据只看
文件系统与 import 后的 `sys.modules`，不写 AST 扫——AST 与书写形态耦合（同 C2a / C3 / #1280 的既有判据）。

### 落地：两段都已完成

第一段（#1390）不动物理布局，先把两份名单与可达性钉死成可执行的棘轮；第二段（#1391）把 19 个
工具链模块搬进 `devtools/`、名单路径从 `tool/` 改成 `devtools/`，并改写了调用点与几十处指针。
名单内容不变，第 3 条从「前瞻」变成「承重」。引擎侧的模块名、`sys.path` 根与手机侧代码在搬移里
一个字节都没动，搬移完成时 `tool/` 顶层是那 37 个引擎模块。此后 `tool/geometry.py`（#1431，判定用的
屏幕几何比例的唯一 owner）作为引擎模块加入，引擎名单是 38 个；`syncEngine` 的整目录 glob 自动收它。
`tool/channel_decide.py`（#1434，渠道认页决策的纯函数）同此，引擎名单是 39 个。
`tool/screen_snapshot.py`（#1432 的值类型）、`tool/channel_arrive.py`（#1435，渠道到达决策）与
`tool/channel_toggle.py`（#1436，渠道拨动决策）同此，引擎名单是 42 个。
`tool/channel_batch.py`（#1437，渠道批处理的策略与结局词表）同此，引擎名单是 43 个。

### 引擎侧的硬约束

引擎侧的模块名与 `sys.path` 根一律不变；`aac_android/inproc.py` 的 `_purge()` 前缀不动。
手机侧代码零改动——这是本方向的硬约束，搬移时若做不到，停下来单独确认。
