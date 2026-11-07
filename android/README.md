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
- 选择：Shizuku 已授权就用 Shizuku，否则用内置无线调试（`Shell`）；Python 侧不感知。

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

## 在电脑上调试替换层

不打包，对着模拟器或连着的手机跑同一套替换层：

```bash
cd android/app/src/main/python
AAC_BRIDGE_ADB=$(which adb) AAC_BRIDGE_SERIAL=emulator-5554 python -c "from aac_android import main; ..."
```

`tests/test_android_shim.py` 不连手机，验 adb 语义、进程内脚本与选择器。

`app/src/test/java/com/ahuamiao/adcleaner/ShellServerTest.java` 用 JUnit 验命令服务的协议层：帧、stdout / stderr 分开、退出码、并发编号、取消。它只用 `java.io` 与 `ProcessBuilder`，不需要模拟器；开发机上把 sh 指到 `/bin/sh` 跑。
