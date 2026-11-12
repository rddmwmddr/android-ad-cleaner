# 手机版（APK）

在手机上直接跑去广告，不用连电脑、不用装别的 App。权限来自手机自带的「无线调试」：本 App 自己配对一次、自己连本机 adbd，以 shell 身份执行命令，和电脑上的 adb 一样，不需要 root（#622）。装了并授权 [Shizuku](https://shizuku.rikka.app/) 的手机也能用。

用户教程（截图 + 视频）：[docs/手机版教程](../docs/手机版教程/README.md)。

## 怎么做到不改引擎

后台和引擎都是桌面版那一份，原样打进 APK：`gui/app.py` 的 `Api`、`tool/`、`recipes/`。手机上只替换三处（另有一处措辞分叉：手机版没有电脑和数据线，引擎的排查提示按 `tool/host.py` 取词，见 [ADR-0019](../docs/adr/0019-phone-second-execution-host.md) 的增补段）：

| 桌面版 | 手机版（`app/src/main/python/aac_android/`） |
|---|---|
| `subprocess.run([adb, "-s", 序列号, "shell", …])` | `adb.py` 接管 subprocess，adb 占位文件的调用按 adb 语义回答，命令经 shell 门面执行（`bridge.py` → Kotlin `Shell`，底下是 `ShizukuShell` 或 `AdbShell`） |
| 每一步一个 Python 子进程 | `inproc.py` 在本进程线程里跑脚本：每步清掉 `tool/` 模块、换环境变量、按线程分流输出、`SystemExit` 当退出码 |
| `uiautomator2` / `adbutils` / `tool/ui_session.py` | `u2.py`：读屏走本 App 的 `ShellServer`（shell 身份连 UiAutomation，读所有屏的窗口），点按走 `input`，选择器在页面上本地匹配，不开网络端口 |

界面是手机版自己的，见下一节。一键走「检测 → 扫描 → 确认页」，用户在确认页点「开始」才执行。

手机版自己的处理：

- 执行与还原期间开前台服务，通知栏上可以点「暂停」。
- 同一期间在屏幕左缘显示悬浮胶囊（`main.py` 的 `visible()`）：HyperOS 会冻结退到后台的 App，前台服务和省电白名单都挡不住，有可见窗口的 App 不冻；悬浮窗权限经 shell 给本 App 自己开，不用用户去设置里找。
- 脚本跑了 60 秒还没完，看门狗每 60 秒把它卡在哪一行写进 logcat（`inproc.py` 的 `_watchdog`）：只进系统日志，不进界面，也不进错误上报。
- 结束后用 shell 身份 `am start` 回到本 App：App 自己在后台启动界面会被系统拦，前台服务也不豁免。

## 界面（ADR-0018）

Jetpack Compose + 官方 Material 3 Expressive，代码在 `app/src/main/java/.../ui/`。页面状态只有 `AppModel.kt` 的 `Screen`，经 `Backend` 调 `aac_android.main.call()`：普通方法名落到 `Api`，`view.xxx` 落到 `aac_android/view.py`（界面要用的判断，CI 测得到）。首次设置的三步文案与「现在是第几步」也在 `view.py` 的 `setup_guide()`：页面和通知栏读同一份；切到系统设置时通知栏显示当前步，回到 App 时清单滚到当前步（#646）。

| 规范元素 | 用在哪 |
|---|---|
| `MaterialExpressiveTheme`、`MotionScheme.expressive()`、动态取色 | 全局；安卓 12 以下用 `expressiveLightColorScheme` |
| `MaterialShapes`、`Morph` | 贯穿首页 → 准备 → 执行 → 完成的主形状（`Hero.kt`），换页时接着变形；步骤号、结果状态的小形状 |
| `LoadingIndicator`、`ContainedLoadingIndicator` | 启动、准备、扫描 |
| `CircularWavyProgressIndicator`、`LinearWavyProgressIndicator` | 执行进度（暂停时波浪收平）、还原中 |
| 按钮 M / L 尺寸与按下形变 | 主按钮 96dp，屏幕矮时 56dp |
| 标准 `ButtonGroup` | 暂停 / 停止（按下的变宽、旁边让位） |
| 连接按钮组 + `ToggleButton` | 反馈类型单选 |
| `HorizontalFloatingToolbar` | 确认页的已选数和开始 |
| `SegmentedListItem` | 所有列表 |
| `LargeFlexibleTopAppBar`、`MediumFlexibleTopAppBar` | 首次设置、确认页 |
| 强调字体、预测性返回、触感 | 标题与数字；可返回的页面跟手缩小；确认、失败、每进一步 |

中文字体常常只有常规和粗体两档，官方 500 的强调字重会落回常规，所以 `Theme.kt` 把强调样式调到 600 / 700。所有操作都留文字标签。图标是 Material Symbols Rounded（Apache-2.0），在 `res/drawable/`。

不连手机逐屏验收（只在 debug 构建）：

```bash
adb shell am start -n com.ahuamiao.adcleaner/.MainActivity --es demo home [--es sheet more]
```

页面和面板的名字在 `src/debug/.../Demo.kt`。`--es plan '<计划 JSON>'` 不经勾选，把计划交给真引擎（模拟器上没有营销渠道可选时用），`--es call pause` 发暂停。

## 内置无线调试（#622）

做法参考 Mika；adb 协议用 [libadb-android](https://github.com/MuntashirAkon/libadb-android)（GPL-3.0-or-later 或 Apache-2.0 双许可，本项目按 Apache-2.0 使用）。

- `AdbManager`：App 私有目录存 RSA 密钥与自签证书；经 mDNS 找无线调试的配对 / 连接端口，只连本机 `127.0.0.1`。
- 配对（#634）：「开始授权」先请求一次截屏，`PairingService`（mediaProjection 前台服务）等 mDNS 上冒出配对端口，截一帧、用打包的 ML Kit 拉丁文模型在本机认出 6 位配对码，配对、连接，再以 shell 身份把 App 调回前台。帧只在内存里，完成即停。不用悬浮引导卡：设置的 `SettingsBaseActivity` 默认隐藏第三方悬浮窗。mDNS 会留着上一个对话框的端口，用前先探端口。
- 退路：拒绝截屏、截到黑屏、15 秒认不出、等满 5 分钟没出现配对端口时，码填在通知栏输入框（`Pairing`）。vivo 会把通知里的「填写」按钮折起来，所以只当退路。
- 命令与读屏：连上后只开一条常驻 `exec:` 流，跑 APK 里的 `ShellServerMain` → `ShellServer`（shell 身份），所有命令、读屏按编号经它收发（`ServerClient`；Shizuku 那条路起的是同一个服务）。读屏用 UiAutomation，不开网络端口——以前借用的 u2.jar 读屏服务在 9008 端口对局域网开放、无鉴权（#623）。不给每条命令单开 adb 流：libadb 在对端关流时有竞态，小命令会丢输出和退出码。
- 首次连上后经 shell 给本 App 授 `WRITE_SECURE_SETTINGS`：之后无线调试被关（重启、换 Wi-Fi）时 App 自己打开、重连。第一次在某个网络上打开无线调试，系统会弹「允许在此网络上使用无线调试」，勾「始终允许」后才能免确认。
- 选择：Shizuku 已授权就用 Shizuku，否则用内置无线调试。判定与两句失败文案只在 `ShellBackend`（`pick()`），`Shell` 的 `connected()` / `ensure()` / `client()` 共用它；任何起命令服务的路径都先确认那条通道就绪再开流（`openWhenReady()`），不把 libadb 的 `connect() must be called first` 交给用户看（#1034）。Python 侧不感知。

## 读屏（#623）

手机版要读屏才认得出页面上的开关。以前借的是 uiautomator2 自带的 `u2.jar`：它在 9008 端口监听所有网卡、没有鉴权，执行期间同一个 Wi-Fi 下的设备能读屏、代点按。现在换成 App 自己的实现：

- `AndroidScreenReader`：以 shell 身份连 UiAutomation（`ActivityThread.systemMain` + 反射私有构造函数），`getWindowsOnAllDisplays()` 读所有屏的窗口，输出与 uiautomator 同格式的 XML，节点带 `display-id`。
- 读屏与屏幕尺寸走 `ShellServer` 的类型 5 / 6，也就是那条常驻的 stdin / stdout 管道——**不开任何端口**，`u2.jar` 不再打进 APK。
- `u2.py` 的点按 / 滑动 / 按键改走 `input`，选择器在拿到的页面上本地匹配，写字走 App 设的剪贴板 + 粘贴键（引擎本来就有这条回落）。
- 读屏代码在 `AndroidScreenReader` 里、经 `ScreenReader` 接口注入：`ShellServer` 仍只用 `java.io`，协议层能脱离安卓单测。

## 后台屏（#618）

执行与还原时优先在一块看不见的虚拟屏上跑，用户照常用主屏。做法参考 [Mika](https://github.com/wangzan101/mika)（Apache-2.0）：

- `Vd.java` 随 APK 打包，以 shell 身份用 `app_process` 启动（类路径就是本 APK），建与主屏同尺寸同密度的虚拟屏，每 4 秒续亮。
- `aac_android/screen.py` 把发往手机的命令改到这块屏：`am start` 加 `--display` 并另开一份任务（主屏开着同一个 App 时不把它搬走），`input` 加 `-d`，HOME、点亮屏幕、收起通知栏不发（只会作用到主屏），截图用它在 SurfaceFlinger 里的编号。查前台只看这块屏；这块屏带着 `ALWAYS_UNLOCKED` 时锁屏直接按未锁处理，`Vd` 降到没有这个标记的档位就按它那段照实读。
- `u2.py` 按屏号读屏（命令服务只回这块屏的窗口）；点按走 `input -d`；选择器在拿到的页面上自己匹配；写字走 App 设的剪贴板 + 粘贴键，引擎本来就有这条回落。
- 建不了屏（安卓 12 以下、系统不给 shell 建屏）就退回主屏模式。后台模式跑完不抢前台，按结果发通知（做完了 / 已停止 / 失败）。
- 靠桌面手势进入的入口（OPPO / vivo 负一屏）在后台屏上走不通，照常报「没找到」。

## 构建

```bash
android/build.sh assembleRelease
```

构建前会把 `tool/`、`recipes/`（不含 `zztest-*`）、`gui/app.py`、提示音和 `brand-taps.json` 同步进 assets。版本号读 `gui/app.py` 的 `VERSION`。

- 需要 JDK 17、Android SDK（compileSdk 37）、gradle 9.8.2，以及构建用的 Python 3.12。
- `build.sh` 认 `JAVA_HOME` / `ANDROID_HOME` / `GRADLE_HOME`，不设就用维护者机器上的默认值；构建用的 Python 3.12 由 `CHAQUOPY_PYTHON` 指定，不设时 `app/build.gradle.kts` 会退回本机 uv 装的那份 macOS aarch64 路径，配置期 `require()` 一查不到就直接失败——别的机器必须设。仓库里没有 `gradlew`，构建走 PATH 上的 `gradle`；构建目录固定落在 `~/Library/Caches/aac-android/`。维护者机器以外没有验证过完整构建。
- 协议层的 JVM 单测（`app/src/test/…/ShellServerTest.java`）不碰 Android：`cd android && gradle :app:testDebugUnitTest` 就能跑，读屏用假的 `ScreenReader` 注入；配置期同样要一份可执行的 Python 3.12。
- 正式签名读 `.private/android-signing/keystore.properties`，没有就退回 debug 签名。证书丢了，已安装的 App 就没法覆盖更新。
- 调试签名是仓库里的 `android/debug.keystore`（PKCS12，别名 `androiddebugkey`，口令 `android`），只签调试包、不是秘密。以前用 AGP 现生成的调试密钥，CI 每次都是新 runner、每跑一次换一把，冒烟覆盖安装必报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`（#1077）。

## 真机冒烟：CI 出包 → 装机 → 启动 → 从首页点到底 → 还原

维护者的一条命令。构建留在 CI，本机只要有 `adb` 与 `gh`：

```bash
.venv/bin/python android/smoke.py                 # origin 的 main 最新提交，跑完整主流程
.venv/bin/python android/smoke.py --fast          # 快速档：只跑执行段，不点界面
.venv/bin/python android/smoke.py --commit 9a5d6e6  # 指定提交或标签：推一个 smoke/<短 SHA> 临时分支，跑完删掉
.venv/bin/python android/smoke.py --ref some-branch  # 指定分支
.venv/bin/python android/smoke.py --screens          # 追加 demo 逐屏，逐页判进程与 FATAL
```

它触发 `android.yml`、等它跑完、下载 debug APK、`adb install -r` 覆盖安装、启动；默认从首页点到底：点「一键去广告」，等确认页出现，点「开始」，等 App 自己报这一轮跑完，再认完成页的结局（完成 / 有步骤没成功 / 已停止）。最后自动还原三项：挂起的包、快应用组件、营销通知渠道。

`--fast` 是兜底档：界面改文案、改布局让「认文字 + 点按」失效时，它按手机上现算的状态 JSON 下发一份计划（段名、要挂起的广告包、关不关快应用都从这份 JSON 来，不写死），交给 App 的 debug 计划入口只跑执行段，不经过检测与勾选。

结论分三段：构建 / 安装 + 启动 / 真流程 + 还原。「完成 N 步」数的是这一轮的任务步骤（结果行），含「存改动前的快照」「收尾」这类不碰设备的步，只记录、不参与判定——开发机本来就不指望适配；实际改了多少看各步的 `summary`（App 从引擎日志归纳的一行），引擎原文按行进了 `logcat.txt`，tag 是 `AacEngine`：`grep AacEngine logcat.txt`，手机上直接看用 `adb logcat -s AacEngine:I`（`inproc.py` 的 `_Mirror`；`#aac:` 的机器行不镜像，它们本来就不进界面；开跑前会把 logcat 环形缓冲临时调到 16 MiB、跑完按 main 那一档交回（`logcat -G` 没有按缓冲设尺寸的入口；读不到原档位时只调大、不改回，`note` 里会说）——设备默认的 256 KiB 在这台机器上只留约 110 秒，一轮引擎 215 秒，产物取的是跑完那一份 dump，不调大就只剩系统日志；调不动也会在 `note` 里明说，不静默）。人读摘要、`result.json`（三段结论与还原明细）、`run.json`（引擎返回的原始结果）、`logcat.txt` 按 commit 落在 `<临时目录>/aac-smoke/<短 SHA>/`（`--root` 可改），不入库——`logcat.txt` 里既有系统日志也有引擎原文（含包名、页面标题、通知渠道名），开发机上还可能有私人通知，别把产物贴进公开 issue。退出码 0 三段都过、1 有段失败、2 没跑起来（没设备、配对没就绪、找不到提交）。

- 开跑前先判 App 自己的 shell 通道（无线调试 / Shizuku）是不是 ready；不是就停下并提示重新授权，不触发 CI——这时跑一轮只会白等。手机上还没装 App、或装的是没有导出入口的旧版调试包时读不到状态，只提示一句、继续跑（这一轮装完才有入口）。
- 完整主流程的驱动全在桌面侧：读屏认文字、按坐标点按（`input tap`），不改 App。读屏走引擎同一个 adapter（`ui_session.connect`），不直连 `uiautomator dump`——这台一加上 `uiautomator dump` 会被系统 kill。认不出目标文字时带着「这一屏上有：…」停下，绝不猜。
- 点之前先确认这一屏是本 App 的：ColorOS 会把退到后台的 App 换成商店之类的界面，这时按坐标点会点到别人身上。读到别人的界面就重拉一次 App，继续等。
- UiAutomation 同一时刻只给一个使用者：App 正在扫通知或正在跑引擎时读屏会失败，那不是错误，接着等。所以执行本身照旧等 App 的导出（`--es call smoke`，不占 UiAutomation），跑完才读屏认完成页。
- 认文字靠的是界面文案（「一键去广告」「开始」「再做一次」「重新开始」）。改文案会让这条路失效，`--fast` 是兜底；`tests/test_android_smoke.py` 有一条守卫盯着这几个字还在 Kotlin 源里。
- 执行跑在后台屏上（见上面「后台屏」一节），所以靠桌面手势的段（OPPO / vivo 的负一屏）在这一轮里必然报「未完成」：HOME 不发、滑动只作用在后台屏，进不了速览。单独跑那一段（主屏模式）是通的。
- 计划固定下发两次（仅 `--fast`）：冷启动时界面在 onCreate 里先处理 intent，那时设备还没就绪，第一份会被丢掉；导出停住时会把计划连同导出入口再发一次，再停才判「没跑起来」。
- App 侧只有一个 debug 入口：`--es call smoke` 把 shell 状态与这一轮执行结果按块打到 logcat（入口只在 debug 源集，release 的 `Demo` 是空壳）。内容与分块在 `aac_android/view.py` 的 `smoke_export`：只留每一步的结果与摘要，不含日志行、引擎原始输出与上报载荷。
- 还原：挂起的包用跑完后的状态 JSON 现取；快应用走 `run.py quickapp on`；营销渠道清单从 App 私有目录（debug 包的 `run-as`）逐份取、按包名 + 渠道 ID 合并，不依赖电脑侧 backups——读不到私有目录本身是失败，会报「设备可能残留改动」，不当成「本来就没有清单」。任一失败重试一次，仍失败就停手，不自动重跑。
- 导出停住但引擎还在手机上跑时（20 分钟没等到结局），**不还原、也不跑逐屏**：那会和执行抢同一块屏，强停进程更会把执行杀在半截；报告里如实说「执行还在跑」。
- 构建失败、装机失败（签名冲突、系统拦截）、启动失败（进程不在、logcat 有 `FATAL EXCEPTION`）都停在当场，后面两段记「未执行」。
- 设备多于一台时用 `--serial` 指定；只连一台自动取。
- `--screens` 的页面名来自 `app/src/debug/.../Demo.kt`，每屏之间强停进程（demo 换后端且不还原）；它在主流程与还原之后跑。
- `--commit` / `--ref` 指定的是**被测 APK** 的来源；状态 JSON 与三条还原命令跑的是当前工作区的 `tool/`。拿它二分定位时要知道这一层不跟着提交走。

首次准备（配对只做一次）：

1. 开发机打开开发者选项与 USB 调试（[docs/00](../docs/00-打开开发者模式.md)），插 USB，`adb devices` 里要能看到它。
2. 调试包与正式包签名不同，`adb install -r` 覆盖不了：机器上装着正式包时先卸一次。之后一直用调试包覆盖。
   ColorOS / 一加首次装调试包会弹系统的安装引导页，要在手机上点一次「继续安装」；之后同签名覆盖安装不再弹。
3. 首次装好后在 App 里走一次「开始授权」（无线调试 + 配对，[docs/手机版教程](../docs/手机版教程/README.md) 的前三步）。配对状态与管理员授权靠「同签名 + 从不卸载」保住，所以**不要 `adb uninstall`**，否则下一次要重新配对。调试签名换了（例如从旧版临时密钥签的包升上来）时，必须 `adb uninstall` 一次，那一轮配对要重做。
   第一次跑冒烟时 App 还没装，配对检查会跳过：这一轮仍会点进主流程，但 App 还不能以 shell 身份执行，跑到「开始」之后会如实报失败；在手机上配对完再跑一次，才走得到「真流程 + 还原」这一段。之后每轮覆盖安装都不会丢配对。

## 在电脑上调试替换层

不打包，对着模拟器或连着的手机跑同一套替换层：

```bash
cd android/app/src/main/python
AAC_BRIDGE_ADB=$(which adb) AAC_BRIDGE_SERIAL=emulator-5554 python -c "from aac_android import main; ..."
```

`tests/test_android_shim.py` 不连手机，验 adb 语义、进程内脚本与选择器。

`app/src/test/java/com/ahuamiao/adcleaner/ShellServerTest.java` 用 JUnit 验命令服务的协议层：帧、stdout / stderr 分开、退出码、并发编号、取消。它只用 `java.io` 与 `ProcessBuilder`，不需要模拟器；开发机上把 sh 指到 `/bin/sh` 跑。

`app/src/test/java/com/ahuamiao/adcleaner/ShellBackendTest.kt` 验后端选择、没就绪时的两句文案与开流前的闸，不碰 Android 运行时（#1034）。

## 应用内更新（未发布，#888）

启动时检查版本，「更多 → 检查更新」可重新检查。国内默认 Gitee，也可选 GitHub；下载显示进度，可取消，大小和 SHA256 校验通过后才能安装。系统会要求允许本 App 安装应用，并请用户确认覆盖安装；包名、版本和签名必须与当前 App 匹配。无需卸载，数据和备份保留；正在执行或还原时不开始安装。

0.4.1 及更早版本仍要先手动覆盖安装第一版带更新功能的客户端。调试 APK 与正式 APK 签名不同，不能互相覆盖。实现边界见 [ADR-0030](../docs/adr/0030-in-app-update.md)。

Debug 构建可在模拟器验收系统安装入口（正式包没有这个入口）：先把同签名、更高版本 APK 放到 App 私有的 `files/data/updates/`，用 `adb -s <模拟器序列号> shell am start -n com.ahuamiao.adcleaner/.MainActivity --es call install-update --es path /data/user/0/com.ahuamiao.adcleaner/files/data/updates/candidate.apk --es version <候选版本>`。结果写入 `AACUpdateTest` 日志，系统授权与覆盖安装仍需在界面确认。界面演示可用 `--es demo home --es sheet update-downloading`（另有 `update` / `update-ready` / `update-error`）。
