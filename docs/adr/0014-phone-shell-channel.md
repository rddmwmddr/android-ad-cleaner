# 手机版的 shell 通道：双后端由门面收口，命令走一条常驻流

基线 `84b4a64`。

手机版（#614）要拿到 shell 身份才能拨别人 App 的开关，最初只有 Shizuku 一条路：用户得先装 Shizuku，
再按它的说明用无线调试启动一次。普通用户卡在这一步——装什么、为什么要装、装完还要做什么，三句话解释不完。

#622 加了第二条路：App 自己完成无线调试配对、自己连本机 adbd。#614 把「怎么执行命令」写死在 Shizuku
上，现在同一个位置有两种答案，`Phone` 以上的引擎、界面、机型脚本不感知它。

## Decision

**`Shell` 门面收口后端选择，命令走一条常驻 `exec:` 流。**

- 后端选择：Shizuku 已授权就用 Shizuku，否则用内置无线调试（安卓 11 起）。两者的差别不外泄，
  Python 侧只换了一个类名（`aac_android/bridge.py`）。
- `need_pair` 页给一条次级入口「已装 Shizuku？改用 Shizuku」。**不记偏好**：已授权的 Shizuku 永远优先，
  用户想去掉这条依赖就停掉 Shizuku。
- 命令通道：连上后只开一条常驻 `exec:` 流，跑 APK 内的 `ShellServer`，按编号收发，
  stdout / stderr / 退出码分开（详见 `ShellServer` 的协议注释）。**不给每条命令单开 adb 流。**
- 取消：协议加类型 4。`ShellServer` 维护在跑的命令，收到取消就 `destroy` 并**不回包**；
  App 侧取消时立刻把该 id 从待回队列摘掉。类型 4 只对「执行」生效，对常驻进程无效。
- 读屏（#623）：协议加类型 5（读屏）/ 6（屏幕尺寸），与命令共用同一条流，**不开网络端口**。
  读屏实现是 `AndroidScreenReader`（shell 身份连 UiAutomation，读所有屏的窗口），
  经 `ScreenReader` 接口注入到 `ShellServer`；读屏代码不写进协议层。
  进程入口因此分成两个类：`ShellServerMain` 负责 Android 那一侧（主线程 Looper、系统 Context），
  `ShellServer` 只管协议。
- 门面契约分两个名字：`ensure()` 可能建连接（最多 4 秒，失败后 10 秒内不再试），
  `connected()` 只查现状。`wait-for-device` 用前者，`devices` / `get-state` 用后者。
- 首次连上后经 shell 给本 App 授 `WRITE_SECURE_SETTINGS`；之后无线调试被关（重启、换网络）时
  App 自己写 `adb_wifi_enabled=1` 并重连。这两件事要写在配对页文案里；后台执行期间自动重开时
  在「执行状态」频道发一条通知，用户在看界面时不发。

## Considered Options

- **只走 Shizuku**（#614 的现状）vs **双后端**。前者把安装第三方 App 当前置条件，正是这张票要消除的门槛。
- **一条常驻流**（采纳）vs **每条命令一条 adb 流**。libadb 在对端关流时有竞态，模拟器上
  `getprop` 这类小命令会丢掉全部输出和退出码；一条流从头用到尾就碰不到它。
- **自己定协议**（采纳）vs **复用 adb shell v2**。v2 的帧是给 adbd 的，经过 `exec:` 流之后
  还要两头解一遍；自有协议只有六种类型、两端各一份实现。
- **读屏并进命令服务**（采纳，`ScreenReader` 注入）vs **继续用 uiautomator2 的 `u2.jar`**。
  后者在 9008 端口监听所有网卡且无鉴权，同一个 Wi-Fi 下的设备能读屏、代点按；并进同一条管道就不开端口，
  代价是读屏依赖 Android 私有 API，只能放在 `AndroidScreenReader` 里、由真机验。
- **类型 4 不回包**（采纳）vs **回一个专用退出码**。回包会和进程自然完成的回包撞同一个 id，
  而 App 侧摘掉待回项之后并不需要这个确认。
- **`ensure()` / `connected()` 分开**（采纳）vs **一个 `ready()` 既查又连**。后者让每轮状态轮询
  都可能等 4 秒 mDNS，也让人分不清「现在能用」和「去试试能不能用」。
- **只连 `127.0.0.1`**（采纳）vs **允许局域网连接**。后者要把本机 shell 暴露到网络上，
  而这个能力的目的是「手机自己管自己」。

## Consequences

- 安卓 10 及以下没有无线调试，仍只有 Shizuku 与电脑版两条路，界面按版本分流。
- libadb-android 是 GPL-3.0-or-later / Apache-2.0 双许可，按 Apache-2.0 使用，`android/README.md` 致谢。
- 自动重开无线调试依赖首次配对时自授的那条权限。授权失败或系统在新网络上要求重新确认时，
  自动重连会失败——这条路径要有日志，不能静默。
- `ShellServer` 只用 `java.io` 与 `ProcessBuilder`，不依赖 Android，可以脱离模拟器做 JVM 单测：
  协议帧、stdout / stderr / 退出码分开、并发编号、取消、类型 5 / 6 与读屏实现解耦。读屏本身在
  `AndroidScreenReader` 里，只能真机 / 模拟器上验。
- 真机验收归 #622：模拟器上的 adbd 不校验授权，配对这一步在模拟器里走不到。
