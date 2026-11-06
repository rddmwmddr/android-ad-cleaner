# 手机版（APK）

在手机上直接跑去广告，不用连电脑。权限来自 [Shizuku](https://shizuku.rikka.app/)：用户在手机上用「无线调试」启动它，本 App 就能以 shell 身份执行命令，和电脑上的 adb 一样，不需要 root。

## 怎么做到不改引擎

界面、后台、引擎都是桌面版那一份，原样打进 APK：`gui/web/index.html`、`gui/app.py` 的 `Api`、`tool/`、`recipes/`。手机上只替换三处：

| 桌面版 | 手机版（`app/src/main/python/aac_android/`） |
|---|---|
| `subprocess.run([adb, "-s", 序列号, "shell", …])` | `adb.py` 接管 subprocess，adb 占位文件的调用按 adb 语义回答，命令经 Shizuku 执行（`bridge.py` → Kotlin `ShizukuShell`） |
| 每一步一个 Python 子进程 | `inproc.py` 在本进程线程里跑脚本：每步清掉 `tool/` 模块、换环境变量、按线程分流输出、`SystemExit` 当退出码 |
| `uiautomator2` / `adbutils` / `tool/ui_session.py` | `u2.py`：同一个 `u2.jar` 经 Shizuku 以 shell 身份启动，App 直连本机 9008 端口发 jsonrpc |

界面经 WebView 加载 `index.html`；`assets/mobile/mobile.js` 补上 `pywebview` 桥，把首页换成 Shizuku 状态和「一键去广告」（自动走检测 → 扫描 → 开始执行，勾选与桌面版默认一致）。

手机版自己的处理：

- 执行与还原期间开前台服务，通知栏上可以点「暂停」。
- 结束后用 shell 身份 `am start` 回到本 App：App 自己在后台启动界面会被系统拦，前台服务也不豁免。

## 后台屏（#618）

执行与还原时优先在一块看不见的虚拟屏上跑，用户照常用主屏。做法参考 [Mika](https://github.com/wangzan101/mika)（Apache-2.0）：

- `Vd.java` 随 APK 打包，经 Shizuku 以 shell 身份用 `app_process` 启动（类路径就是本 APK），建与主屏同尺寸同密度的虚拟屏，每 4 秒续亮。
- `aac_android/screen.py` 把发往手机的命令改到这块屏：`am start` 加 `--display` 并另开一份任务（主屏开着同一个 App 时不把它搬走），`input` 加 `-d`，HOME、点亮屏幕、收起通知栏不发（只会作用到主屏），查前台 / 锁屏只看这块屏，截图用它在 SurfaceFlinger 里的编号。
- `u2.py` 读屏只留这块屏的窗口；点按走 `input -d`；选择器在过滤后的页面上自己匹配；不经读屏服务写字（它只找主屏的输入框），引擎自动退到剪贴板 + 粘贴。
- 建不了屏（安卓 12 以下、系统不给 shell 建屏）就退回主屏模式。后台模式跑完不抢前台，发通知。
- 靠桌面手势进入的入口（OPPO / vivo 负一屏）在后台屏上走不通，照常报「没找到」。

## 构建

```bash
android/build.sh assembleRelease
```

构建前会把 `tool/`、`recipes/`（不含 `zztest-*`）、`gui/app.py`、`gui/web/`、教程图和 `u2.jar` 同步进 assets。版本号读 `gui/app.py` 的 `VERSION`。

- 需要 JDK 17、Android SDK、gradle 8.10.2，以及本机的 Python 3.12（Chaquopy 编译用，路径在 `app/build.gradle.kts`）。
- `u2.jar` 取自 `gui/.venv` 里装的 uiautomator2 3.7.1：先按客户端的说明装好 `gui/.venv`。
- 正式签名读 `.private/android-signing/keystore.properties`，没有就退回 debug 签名。证书丢了，已安装的 App 就没法覆盖更新。

## 在电脑上调试替换层

不打包，对着模拟器或连着的手机跑同一套替换层：

```bash
cd android/app/src/main/python
AAC_BRIDGE_ADB=$(which adb) AAC_BRIDGE_SERIAL=emulator-5554 python -c "from aac_android import main; ..."
```

`tests/test_android_shim.py` 不连手机，验 adb 语义、进程内脚本与选择器。
