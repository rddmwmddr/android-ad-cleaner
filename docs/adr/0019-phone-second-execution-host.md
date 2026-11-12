# 手机版是第二个执行宿主：引擎原样复用，接缝切在 Python 层

基线 `f0e6a9b`。

桌面版的形状是「电脑上的 Python 调 adb 驱动手机」：`tool/` 是引擎、`recipes/` 是各机型的机型脚本、
`gui/app.py` 的 `Api` 是客户端入口。手机版（#614）要在手机自己身上跑同一套东西——不连电脑、
不装 Shizuku 也能用（#622）——所以同一个进程里要同时有引擎、机型脚本和「拿 shell 身份点手机」的能力。

两台宿主的差别只有三处：命令怎么执行、每一步怎么起、屏幕怎么读。这三处都收在 Python 侧的窄口上，
引擎、机型脚本与结果文案一行都不用改。（2026-11-07 修订：多出第四处——引擎的排查提示按宿主取词，
见文末「增补：措辞也按宿主分叉」；判定仍不分叉。控制流后来也分出一处：手机版不写插电常亮，
见「增补：手机版不碰插电常亮」。）

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
- **手机专用精简引擎**（否决）：同一份机型脚本要维护两份行为，结果文案也会整段分叉。有限的一处措辞分叉是另一回事，见文末增补。
- **每条命令单开一次 shell 往返**（否决，理由与竞态见 ADR-0014）。
- **继续借 `u2.jar` 读屏**（否决：9008 端口对局域网开放且无鉴权，见 ADR-0014）。

## Consequences

- 替换层不连手机就能测：`tests/test_android_shim.py` 验 adb 语义、进程内脚本与选择器；协议层的 JVM 单测
  在 `android/app/src/test/`。真机与模拟器仍有差别——模拟器上的 adbd 不校验授权，配对与授权路径只能真机验。
- 进程内跑脚本意味着脚本把进程弄崩会带走整个 App，桌面版只死一个子进程。卡在 Java 调用里的脚本，
  「停止」要等它返回才生效，`bridge.py` 自己按超时掐。
- 看门狗（`inproc.py` 的 `_watchdog`）只把卡住的位置写进 logcat，不进界面、不进错误上报；查「卡住」看
  `adb logcat`，不是看结果页。引擎行本身也在进界面的同时镜像一份到 logcat（`inproc.py` 的 `_Mirror`，
  tag `AacEngine`）：这条通道只有手机宿主有，桌面版的引擎输出本来就重定向到文件；机器行
  （`view.MACHINE_PREFIX`）不镜像，它们只改状态、只进上报（ADR-0009）。
- 失效条件：Shizuku / libadb 的接口与 `exec:` 流变了要跟（ADR-0014）；Chaquopy 升级会改 `callAttr`、
  线程附着与解释器锁的语义，`bridge.py` 「不放解释器锁」的做法依赖它；HyperOS 冻结退到后台 App 的策略
  收紧时，胶囊与前台服务这套绕法要重新验（`aac_android/main.py` 的 `visible()`）；`uiautomator2` 若改选择器
  语义，`u2.py` 的字段与掩码要跟。
- 当前钉的版本：Shizuku 13.1.5、Chaquopy 插件 17.2.0、AGP 9.5.1（`android/build.gradle.kts`、
  `android/app/build.gradle.kts`），compileSdk 37 与构建用 Python 3.12（`android/app/build.gradle.kts`）。
  升级时以这两个文件为准，不在这里复述。

## 增补：措辞也按宿主分叉（#729）

**引擎的排查提示多出一处宿主依赖，只换说法，不换判定。** 手机版没有电脑、数据线和 USB 授权框，
而模块级常量里的排查动作是照着桌面版写的：`troubleshooting.XIAOMI_INPUT`（「电脑能读屏幕」「拔掉数据线重新插上」）
与 `UI_INSTALL_FAILED`（「拔插数据线」）、`fast` 的「系统拒绝了电脑发出的点击」、
`adb_link.HINT` / `REPEAT`（「退出电脑上的手机助手类软件」）。
这些走的是 `DeviceLost(HINT + …)`、异常文案与打印行，手机版用户照样看得到，照着做会去找不存在的东西。

- **机制**：`aac_android/main.py` 的 `boot()` 在导入 `gui/app.py` 之前设 `AAC_HOST=phone`；`tool/host.py`
  导入时读一次得到 `ON_PHONE` 与 `CLICKER`，`troubleshooting.py` 显式转发（`from host import ON_PHONE as ON_PHONE`），
  `adb_link.py` 直接取。引擎每次执行前清 `tool/` 下已加载的模块、换上这次的环境变量再导入，所以每次执行
  都是新值——与 `fast.TAPPED`、`chan_fast.ON_PHONE` 的取法一致。
- **边界**：分叉的只有措辞，以及由措辞带出的一条「要不要提示」——`chan_fast.keep_awake()` 在手机版设不上
  插电常亮时不打警告，因为手机版由 App 自己的屏幕锁兜底（#728）。判定、控制流、机型脚本与结果页的
  计数口径都不分叉（手机版后来干脆不写插电常亮，那是第二处分叉，见文末「增补：手机版不碰插电常亮」）。
  手机版的「点击被拒」告警也随之删掉「中途还会锁屏」：那句是 `#666` 从 Compose
  改写中恢复的措辞，但 #728 起屏幕已由 App 自己兜着，原话不再成立（#747）。
  客户端自己产出的诊断行也走这条路：`gui/app.py` 的 `TAP_REFUSED` 由 `boot()` 覆盖，路径与 `LINK_LOST` 相同（#747）。
- **为什么不在客户端做后置替换**：断线原因和排查动作是引擎产出的，客户端手上只有整段文本；按关键词
  替换等于猜语义，改一句引擎文案就静默失效。
- **为什么不另做一个「手机版引擎」**：那会把机型脚本与判定一起分叉，正是本文否决精简引擎的理由。
- **失效条件**：`gui/app.py` 的 `child_env()` 只认客户端自己给的 `HOST`（手机版 `boot()` 设成 `"phone"`），
  继承来的 `AAC_HOST` 一律 `pop` 掉——和 `AAC_EVENTS` 同一边，用户 shell 里的同名导出不能让引擎换一套
  说法（#747）；客户端若开始按这些文案做状态判断，这套分叉就重新变成行为分叉，得改回事件行（ADR-0004）。

## 增补：手机版不碰插电常亮（#731）

**手机版从头到尾不写 `stay_on_while_plugged_in`。** 这是第一处真正的控制流分叉：除了说法不同，
两台宿主做的事也不同。

- **为什么**：写 7 是为了「改开关期间别息屏」，桌面版有两个生命周期兜住它——`run.py` 的
  「备份原值 → 收尾还原」与 `chan_fast.keep_awake()` 的「批开头打开 → finally 还原」。手机版从 #728 起
  由 App 自己的屏幕锁保亮屏，这项设置是桌面时代的遗留；而它唯一的还原点是「收尾」，断线正好会跳过
  那一步——小米 15 Ultra 的 0.4.0 上报里，设置就留在了 7。
- **机制**：`tool/host.py` 的 `ON_PHONE`。`chan_fast.keep_awake()` 照读原值（返回口径不变）但不写，
  批尾的还原跟着跳过；`run.py` 的 `cmd_recipe` 不读不写，`cmd_finish` 连「插电常亮」那句话也不说。
  桌面版逐字不动。
- **顺带分清两种读屏失败**：`adb_link.LIB_GONE` 补上手机版命令服务的断开文案（`命令服务断开` /
  `命令服务已断开` / `命令服务不可用`），它们和别的断线一样走 `link_lost`、整批停下。手机版以这条消息
  本身为证据，不再要求 `get-state` 二次确认——那个查询由同一个 bridge 回答，通道死了它照样回「device」
  （`lost_from` 里写作 `ON_PHONE or not present(...)`，桌面版的双向确认不变）。`读屏请求超时` **不**进
  `LIB_GONE`——那只是慢一次，由 `adb_link.read_failed()` 换成一句「这一步没有完成」，该渠道算失败，
  后面的渠道与步骤照常跑（Redmi K80 靠这一点跑完）。`chan_fast` 与 `fast` 两个入口都只报这一句，
  不再打印 Python 堆栈。
- **失效条件**：手机版若不再持有屏幕锁，或某品牌插电时仍会息屏，这条分叉要重新评估——届时回到
  「桌面版那两处生命周期」的写法，而不是再添一处隐藏的还原点。
