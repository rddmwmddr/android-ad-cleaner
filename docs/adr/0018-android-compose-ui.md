# 手机版界面用 Compose 原生实现，不再共用桌面版网页

基线 `dfda2c46`（#664，叠在 #663 上）。

手机版原来的界面是 WebView 加载桌面版 `gui/web/index.html`，再注入 `assets/mobile/mobile.js` 改写页面：
首页整页替换，一键流程靠匹配按钮文字找「下一步」，文案靠字符串替换改成手机上的说法。
这次要按 Material 3 Expressive 重做界面，这套规范的核心元素（形状变形、波浪进度、弹簧动效、
连接按钮组、分段列表、动态取色、预测性返回）只有 Compose 有官方实现。

## Decision

**手机版界面用 Jetpack Compose 和官方 `androidx.compose.material3` 1.5 写，后台不动：界面经
`aac_android.main.call()` 调 `gui/app.py` 的 `Api`，和原来一样。桌面版网页不动。**

- 页面流程只有一个状态：`ui/AppModel.kt` 的 `Screen`。每条流程是一个协程，换流程就取消上一条，
  它的结果不会再改页面。`#662` 查出的页面流程竞态（定时器重叠、等待期间换页）在这里没有容身之处。
- `AppModel` 放在 `AacApp`（进程级）：Activity 被系统回收、从通知点回来，都接着这一份。
- 带判断的逻辑放 `aac_android/view.py`（结果怎么说、什么时候挡住开始、反馈网址怎么截），CI 不连手机也测得到。
  Kotlin 只管画。
- 一键不直接开跑：检测、扫描做完停在确认页，默认勾选和桌面版一致，用户点「开始」才执行（机主 11-07 要求）。
- 演示数据和真引擎验收入口只在 debug 构建（`src/debug/.../Demo.kt`），发布版是空实现。

## Considered Options

- **留在 WebView，用 CSS 仿**：弹簧和形状变形都做不到官方效果，波浪进度要自己画，预测性返回接不上；
  `mobile.js` 改写桌面版页面这条路本身也越来越脆（#647 记着它测不到）。
- **`material3` 1.4 稳定版**：不带 Expressive 的公开 API。
- **`material3` 1.5.0-alpha16 及更早**：能留在 AGP 8，但 API 已改了很多轮，迟早要升。
  1.5.0-rc01 要求 compileSdk 37、AGP 9.1，Chaquopy 17.2 支持到 AGP 9.5，所以直接到位。

## Consequences

- 手机版和桌面版不再共用页面。改流程、文案要看两边；`summarize()` 现在有两份
  （`gui/web/index.html`、`view.py`），靠 `tests/test_android_view.py` 守手机这一份。
- 工具链升级：AGP 9.5（内置 Kotlin 2.3，不再单独用 `kotlin-android` 插件）、Gradle 9.8、compileSdk 37。
  `targetSdk` 仍是 35，系统行为不变。
- APK 从 43.9 MB 变成 50.0 MB，多出来的是 Compose 库；少打进去的是网页和教程图。
- 1.5 还是 RC。`LoadingIndicator`、`MaterialShapes` 在它里面仍标实验性，升版本时可能要改。
- Compose 页面没有自动化测试；验收靠 debug 构建逐屏截图加真机。ADR-0017 前端测试基座里手机版 `mobile.js` 那部分随文件一起去掉，
  手机版的判断在 `view.py`，用 Python 测；`gui/web` 那部分不受影响。
- 首次设置的三步文案与「现在是第几步」在 `view.py` 的 `setup_guide()`（#646）：页面和通知栏读同一份。
  Kotlin 只做解析、把每一步的 `key` 映射到系统动作（打开哪个设置页、开始授权），以及按「在不在前台、
  当前是不是这一步」决定发不发通知（`Native.setupNotice`，用户能划掉）。
  通知在 App 发现状态变化时更新（`onResume` / `refreshState`），没有后台轮询：用户在设置页里自己往下走，
  通知栏仍显示离开 App 时的步号。第 3 步不另发一条——那一段由 `PairingService` 的前台通知给，
  再发一条「回 App 重新开始」会把人推进 ADR-0015 说的重开死循环；没点「开始授权」就切到设置页的用户，
  这一步的通知栏里没有内容。
- 手机版教程的截图和视频按旧界面拍，要重拍。
