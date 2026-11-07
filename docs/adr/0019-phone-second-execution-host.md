# 手机版是第二个执行宿主：引擎原样复用，接缝切在 Python 层

基线 `f0e6a9b`。

桌面版的形状是「电脑上的 Python 调 adb 驱动手机」：`tool/` 是引擎、`recipes/` 是各机型的机型脚本、
`gui/app.py` 的 `Api` 是客户端入口。手机版（#614）要在手机自己身上跑同一套东西——不连电脑、
不装 Shizuku 也能用（#622）——所以同一个进程里要同时有引擎、机型脚本和「拿 shell 身份点手机」的能力。

两台宿主的差别只有三处：命令怎么执行、每一步怎么起、屏幕怎么读。这三处都收在 Python 侧的窄口上，
引擎、机型脚本与结果文案一行都不用改。

## Decision

**引擎、`gui/app.py`、`tool/`、`recipes/` 原样打进 APK，替换只发生在 Python 的这三处接缝：**

- **命令**：`aac_android/adb.py` 接管 `subprocess` 的入口。第一个参数是本模块的 adb 占位文件时按 adb
  的语义自己回答（`devices` / `-s` / `shell` 等），是 Python 脚本时交给 `inproc`，其余照旧。真正的执行走
  `bridge.py` 的门面：已授权的 Shizuku 用 `ShizukuShell`，否则用内置无线调试的 `AdbShell`。门面与两条后端、
  一条常驻 `exec:` 流、读屏并入同一条管道，见 [ADR-0014](0014-phone-shell-channel.md)。
- **每一步**：`aac_android/inproc.py` 在本进程的线程里跑脚本，逐条还原桌面版子进程给引擎的保证——
  同一时刻一个顶层脚本（可重入锁，脚本里再调脚本在同一线程嵌套）；开跑前清掉 `tool/` 下已加载的模块，
  效果等同新进程；`stdout` / `stderr` 按线程分流；环境变量换进换出；`SystemExit` 的 code 当退出码；
  `spawn` 用 `Proc` 替身（迭代 `stdout`、`wait()`、`terminate()`）。停止是往脚本线程投
  `KeyboardInterrupt`，阻塞中的命令自带超时。Chaquopy 调 Java 在后台线程里跑、Python 侧轮询等待，
  不占解释器锁——一条卡住的命令不会把界面轮询、停止键与看门狗一起冻住。
- **读屏**：`aac_android/u2.py` 顶掉 `uiautomator2` / `adbutils` / `tool/ui_session.py`。读屏经 App 自己的
  `ShellServer`（shell 身份连 UiAutomation），点按、按键、截图走 `input` / `screencap`，选择器在拿到的
  页面上本地匹配；异常的类型名与继承关系照 `uiautomator2`，引擎按类型判断的地方不用改。细节见 ADR-0014。

**界面不在这三处里**：手机版界面是 Compose，与桌面版网页各一份，见 [ADR-0018](0018-android-compose-ui.md)。

**为什么切在 Python 层，而不是改引擎或改 Kotlin 侧：** 引擎与机型脚本是仓库里最大的一块资产，改引擎会让
两条宿主从接口处分叉，同一个机型脚本要按宿主各验一遍。而 adb 与 uiautomator2 在引擎里恰好都收敛在
`subprocess` 和少数几个读屏入口上，替换面窄；替换层还能在电脑上对着模拟器或真机跑（`AAC_BRIDGE_ADB` /
`AAC_BRIDGE_SERIAL`），不必装 APK 就能验。

## Considered Options

- **在手机上起一个真的 Python 进程**（否决）：Chaquopy 把解释器嵌进 App 进程，没有可单独启动的解释器，
  要真子进程就得自带一整套 runtime。
- **给引擎抽一个「命令执行器」接口，由 Kotlin 注入**（否决）：`tool/`、`gui/app.py`、`recipes/` 全要改，
  手机版与桌面版从接口处分叉，两边各验一遍。
- **手机专用精简引擎**（否决）：同一份机型脚本要维护两份行为，结果文案也会分叉。
- **每条命令单开一次 shell 往返**（否决，理由与竞态见 ADR-0014）。
- **继续借 `u2.jar` 读屏**（否决：9008 端口对局域网开放且无鉴权，见 ADR-0014）。

## Consequences

- 替换层不连手机就能测：`tests/test_android_shim.py` 验 adb 语义、进程内脚本与选择器；协议层的 JVM 单测
  在 `android/app/src/test/`。真机与模拟器仍有差别——模拟器上的 adbd 不校验授权，配对与授权路径只能真机验。
- 进程内跑脚本意味着脚本把进程弄崩会带走整个 App，桌面版只死一个子进程。卡在 Java 调用里的脚本，
  「停止」要等它返回才生效，`bridge.py` 自己按超时掐。
- 看门狗（`inproc.py` 的 `_watchdog`）只把卡住的位置写进 logcat，不进界面、不进错误上报；查「卡住」看
  `adb logcat`，不是看结果页。
- 失效条件：Shizuku / libadb 的接口与 `exec:` 流变了要跟（ADR-0014）；Chaquopy 升级会改 `callAttr`、
  线程附着与解释器锁的语义，`bridge.py` 「不放解释器锁」的做法依赖它；HyperOS 冻结退到后台 App 的策略
  收紧时，胶囊与前台服务这套绕法要重新验（`aac_android/main.py` 的 `visible()`）；`uiautomator2` 若改选择器
  语义，`u2.py` 的字段与掩码要跟。
- 当前钉的版本：Shizuku 13.1.5、Chaquopy 插件 17.2.0、AGP 9.5.1（`android/build.gradle.kts`、
  `android/app/build.gradle.kts`），compileSdk 37 与构建用 Python 3.12（`android/app/build.gradle.kts`）。
  升级时以这两个文件为准，不在这里复述。
