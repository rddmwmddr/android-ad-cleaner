# ADR-0030：三端应用内更新，共用清单和下载判断

状态：接受（#888，尚未随正式版本交付）

## 背景

0.4.1 的版本提示只打开网页。用户需要 Android、macOS、Windows 都能在应用里下载并安装，国内用户走 Gitee。直接下载最新附件不能确认平台、完整性或同一产品，也不能保证桌面替换失败后还能启动。

## 决定

`gui/updates.py` 持有版本比较、清单校验、渠道选择、下载状态和 SHA256 校验。`Api` 提供五个桥方法，网页和 Compose 仅展示快照。`check_update` 启动后台检查；`download_update` 选择 Gitee / GitHub；`update_state` 读进度；`cancel_update` 取消下载；`install_update` 在 `Dispatcher.claim` 占住旁路操作后再次校验文件并交给宿主安装器。所有更新操作单线程串行，下载不占手机任务槽，安装才占。跨进程另有两把文件锁（`gui/updates.py` 的 `file_lock`）：`download.lock` 让两个窗口不会同时写同一个 `.part`，`install.lock` 让两个助手不会同时替换程序。渠道偏好存入现有 settings。

官网 `android-ad-cleaner-latest.json` 保留 `version`，新增 `schema: 1` 与 `artifacts`。平台键为 `android-arm64`、`mac-arm64`、`mac-intel`、`windows`；每项包含固定文件名、字节数、SHA256、Gitee/GitHub 的版本固定地址。客户端只接受已知仓库、版本、平台的完整 URL，并拒绝 HTTPS 降级跳转。默认 Gitee，不根据语言或 IP 猜测地区，用户可以显式选择 GitHub。下载失败不偷偷切渠道，提供重试与手动切换；未完成文件清理，完整包原子改名。旧清单若版本更高但没有附件数据，会提示官网下载。

`gui/update_manifest.py` 从公开稳定 GitHub Release 的资产摘要生成清单；发布者先按既有 `upload_gitee.py` 回下载核对，再发布新清单。Windows 选择 Gitee 接受的现有 ZIP，不把 EXE 改后缀绕过平台限制。清单 HTTPS 与 GitHub 摘要提供传输、完整性约束；Windows 包尚无代码签名，不能声称具备发布者证书认证。

## 宿主安装

Android 的 Python `AndroidInstaller` 调 Kotlin `UpdateInstaller`，检查私有更新路径、包名、更高 versionCode、清单版本和签名证书集合。FileProvider 只暴露 `files/data/updates/`，安装用系统界面；未知来源权限不足时先打开系统授权页面。不给 shell 安装命令，不绕过用户确认，也不卸载旧版。

macOS 在只读挂载的 DMG 中找唯一 App，核对 bundle id、版本、codesign、Gatekeeper 及与当前 App 相同的 TeamIdentifier。准备成功后把旧 App 复制为独立更新助手。Windows 安全解压 ZIP，拒绝越界、保留名、重复和符号链接，只接受两份 EXE、各自 config 和 `_internal`；复制旧 CLI 及运行时作为助手。目录不可写时不提权，仍保留旧程序并给覆盖安装的说明。

`gui/update_install.py` 写计划，助手校验后取得跨进程安装锁，再写交接文件并回执，之后才关闭原窗口。另一个窗口的助手拿不到锁就退出，不能覆盖正在使用的交接文件。助手等待旧进程退出，在目标卷先复制完整新程序，再将原文件移入备份并替换；Windows 只换已知五个程序单元，卸载器和其他文件不动。新进程使用 `PYINSTALLER_RESET_ENVIRONMENT=1`，以免继承旧打包运行时。新版本 `Api.env()` 在窗口桥可用时写带随机 token 的健康回执；版本、程序路径、token 都匹配才清理备份。替换异常或等待新版超时会终止新进程、恢复旧文件、重新启动旧版，失败原因保存在更新目录供下一次更新窗口展示。若恢复自身遇到文件锁或权限变化，会保留备份位置供人工恢复。

## 限制和验证

更新先提示、再由用户下载与安装，不强制重启；0.4.1 及以前需手动装入第一版。清单不承诺增量下载或断点续传。进程可处理的失败有回滚；断电、进程被强杀、系统级磁盘故障不保证自动恢复。Mac 从 DMG 或 App Translocation 路径运行时不替换；管理员目录需要已有写权限。更新助手的缓存副本可能保留在数据目录，下次开始安装时清掉一天前的准备目录；回滚成功后两份 `.aac-*` 临时目录当场删除（替换中途失败时由 `Replacement` 自己清），恢复自身失败时保留备份位置供人工恢复。

测试通过临时目录实际替换文件，覆盖新进程崩溃、无健康回执、错误 token、部分替换失败、原进程不退出及清理失败；网络边界用实际字节模拟截断、损坏、断网、取消和双击；网页测试加载真实 HTML。Android 的身份比较与更新快照派生有 JVM 测试（轮询循环本身没有），系统安装与 macOS 公证检查仍需打包件/设备验收。
