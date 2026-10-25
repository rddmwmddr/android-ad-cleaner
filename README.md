# 手机去广告

关掉国产安卓手机系统里的广告、热搜、资讯推荐和营销推送。

介绍页：**https://rddmwmddr.github.io/android-ad-cleaner/**

## 下载桌面客户端

插上手机，点几下按钮。不需要 Python，也不需要 AI 工具。

> **2026-10-25 源码已更新，安装包仍为 0.2.0。** 小米搜索输入、机型脚本、vivo 清单链接及打包子进程等修复尚未进入下方安装包。改动、验证结果和待处理问题见 [更新记录](CHANGELOG.md)；提前使用可[从源码运行](docs/08-桌面客户端.md#从源码运行和打包)。

本轮还处理了 Windows 本地页面超时、荣耀截图越界、通知渠道误操作风险、vivo 快应用与备份问题。各 Issue 的处理范围和待验证项见 [社区问题处理记录](docs/09-社区问题处理.md)。仅支持通过 adb 连接的安卓设备，暂不支持使用 HDC 的原生鸿蒙。

| 电脑 | 下载 | 说明 |
|---|---|---|
| Mac · Apple 芯片（M1 及以后） | [AndroidAdCleaner-0.2.0-mac-arm64.dmg](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.2.0/AndroidAdCleaner-0.2.0-mac-arm64.dmg) | 已签名、通过苹果公证，双击就能打开 |
| Mac · Intel 芯片 | [AndroidAdCleaner-0.2.0-mac-intel.dmg](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.2.0/AndroidAdCleaner-0.2.0-mac-intel.dmg) | 同上 |
| Windows 10 / 11 · 安装版 | [AndroidAdCleaner-0.2.0-windows-setup.exe](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.2.0/AndroidAdCleaner-0.2.0-windows-setup.exe) | 弹「Windows 已保护你的电脑」时点「更多信息」→「仍要运行」 |
| Windows 10 / 11 · 免安装 | [AndroidAdCleaner-0.2.0-windows-portable.zip](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.2.0/AndroidAdCleaner-0.2.0-windows-portable.zip) | 解压后双击 `AndroidAdCleaner.exe` |

不知道 Mac 是哪种芯片：左上角苹果图标 → 关于本机，「芯片」写 Apple M 开头的选 Apple 芯片。所有版本：[Releases](https://github.com/rddmwmddr/android-ad-cleaner/releases)。用法：[docs/08-桌面客户端.md](docs/08-桌面客户端.md)。

| | |
|---|---|
| <img src="images/gui-1-connect.png" alt="连接手机"><br>**1 连接手机**：插线即认出手机，内置开启 USB 调试的图文教程 | <img src="images/gui-3-detect.png" alt="检测"><br>**2 检测**：型号、系统版本、机型脚本、快应用、广告组件 |
| <img src="images/gui-4-choose.png" alt="选择"><br>**3 选择要关的**：营销通知按渠道勾选，服务类默认不勾 | <img src="images/gui-6-run.png" alt="执行"><br>**4 执行**：进度条和实时日志 |
| <img src="images/gui-7-done.png" alt="完成"><br>**5 完成**：每一步的结果，最后提醒关闭开发者模式 | <img src="images/gui-8-feedback.png" alt="反馈"><br>**反馈**：自动附诊断信息，一键提交 GitHub Issue |

---


- 不 root，不解锁，不刷机，系统更新不受影响。
- 只拨系统和 App 自带的开关。挂起广告包这一步要机主点头，一条命令可以还原。
- 搜索、负一屏卡片、应用商店的安装和更新、天气预警、快递提醒，这些功能保留。

<p align="center"><img src="images/store-before.png" width="560" alt="改之前：软件商店首页满屏推荐"></p>
<p align="center">改之前：OPPO 软件商店首页。轮播图、必备、必玩、福利标签，全是推广位。</p>

---

## 处理哪些东西

| 类别 | 例子 | 怎么处理 |
|---|---|---|
| 系统广告 | 个性化广告、广告跟踪（OAID）、智能推荐服务 | 系统设置里的开关 |
| 热搜和资讯 | 下拉搜索的热榜、负一屏资讯、浏览器信息流 | 各 App 设置里的开关，浏览器切到简洁首页 |
| 推广位 | 商店的轮播、开屏、悬浮活动、签到福利 | 商店「服务管理」里的开关 |
| 营销推送 | 各 App 的「内容与营销」「活动优惠」通知 | 按渠道关，同一个 App 的订单、快递、更新通知保留 |
| 广告组件 | `com.opos.ads`、`com.miui.systemAdSolution` 等 | `pm suspend` 挂起，要机主同意 |
| 快应用 | 广告里一点就跳进去的「免安装小程序」 | `quickapp` 检测，`quickapp off` 关闭，见 [docs/07-快应用.md](docs/07-快应用.md) |

## 不做的事

- 不卸载、不停用系统应用（`pm uninstall`、`pm disable-user` 都不用）。
- 不改 system 分区，不装模块。
- 不替你同意任何 App 的用户协议。遇到协议页，点「取消」或「以后再说」。
- 不截账号页和手机号页。

---

## 四种用法

<p align="center"><img src="images/ways.png" width="460" alt="三种用法"></p>

> 用法一要先在手机上打开开发者模式和 USB 调试，带截图的教程：[docs/00-打开开发者模式.md](docs/00-打开开发者模式.md)。

| 用法 | 适合谁 | 要准备什么 | 文档 |
|---|---|---|---|
| **一：AI 智能体替你跑** | 有电脑，想省事 | 电脑、数据线、一个能执行命令的 AI 工具 | [docs/02-用AI智能体.md](docs/02-用AI智能体.md) |
| **二：聊天 AI 带你点** | 只有手机 | DeepSeek、豆包、ChatGPT 任意一个 | [docs/03-用聊天AI.md](docs/03-用聊天AI.md) |
| **三：照清单手动关** | 想自己掌握每一步 | 只要手机 | [docs/清单/](docs/清单/) |
| **四：桌面客户端** | 不想敲命令 | Mac（Apple / Intel 芯片）或 Windows 10/11、数据线 | [下载](#下载桌面客户端) · [说明](docs/08-桌面客户端.md) |


用法一的开场白，复制给 AI：

```text
请克隆 https://github.com/rddmwmddr/android-ad-cleaner ，读仓库里的 AGENTS.md，
然后帮我给连着电脑的这台手机去广告。每一步改之前告诉我要改什么。
```

---

## 实测过的机型

**机型脚本**：一台机型的自动操作步骤，记着「打开哪个 App、点哪几个字进设置页、关哪几个开关、留哪几个」。电脑照着它在手机上点，几分钟做完。设置页因型号和系统版本而不同，所以每个机型一份。

| 品牌 | 机型（型号） | 系统 | 机型脚本 | 手动清单 | 营销通知 |
|---|---|---|---|---|---|
| 荣耀 | PNM-AN10 | MagicOS 10 | ✅ 实测通过，重跑 4 分钟 | ✅ | ✅ 26 个渠道 |
| OPPO | Find N6（PLP120） | ColorOS 16.0.9 | ⚠️ 路径实测，整段待验证 | ✅ | ✅ 30 个渠道 |
| OPPO | Find X10 Pro Max（PMX110） | ColorOS 17 | — | ✅ | ✅ |
| OPPO | Find X9 Ultra（PMA120） | ColorOS 16.0.10 | ❌ 页面和 N6 不同，待补 | 部分 | ✅ 27 个渠道 |
| OPPO | Find N3 典藏版（PHN110） | ColorOS 16.0.5 | ❌ 待补 | 部分 | ✅ 27 个渠道 |
| 小米 | 18 Pro Max（M154FF） | HyperOS 4.0.24 | ✅ 2026-10-25 九段重跑通过，173 秒 | ✅ | ✅ |
| vivo | X300 Ultra（V2547DA） | OriginOS 6 | ⚠️ 脚本已补，整段待真机验证 | ✅ | ✅ |

表格反映当前源码。上述小米回归修复、vivo 机型脚本和客户端清单链接修复尚未进入已发布的 0.2.0 安装包，详细验证范围见 [更新记录](CHANGELOG.md)。

- 可先运行通用检测；通知渠道能否安全关闭取决于系统页面和权限，部分 vivo 页面会被跳过。广告跟踪入口也随品牌变化。
- 同一个品牌，系统小版本不同，设置页的名字和层级也会变。机型脚本按型号和系统版本存放，版本对不上时引擎会提示，找不到入口的步骤会跳过，不会乱点。
- 你的机型不在表里：照 [docs/04-给新机型写脚本.md](docs/04-给新机型写脚本.md) 做一份，欢迎提 PR。

---

## 一次完整的流程

<p align="center"><img src="images/flow.png" width="340" alt="处理流程"></p>

命令写法：

```bash
pip3 install -r requirements.txt
python3 tool/run.py devices                 # 看序列号、型号、有没有机型脚本
python3 tool/run.py -s <序列号> check        # 只读检查
python3 tool/run.py -s <序列号> backup       # 改动前快照
python3 tool/run.py -s <序列号> recipe       # 跑机型脚本
python3 tool/run.py -s <序列号> chan-scan    # 列营销通知渠道
python3 tool/run.py -s <序列号> chan-off backups/<型号>-<时间>/channels.tsv
python3 tool/run.py -s <序列号> quickapp     # 检测快应用；quickapp off 关闭
python3 tool/run.py -s <序列号> finish       # 收尾，提醒关闭开发者模式
python3 tool/run.py -s <序列号> dev-off --yes  # 从电脑关闭开发者模式（最后一步，执行后断开）
```

<p align="center"><img src="images/channel-off.png" width="420" alt="营销通知渠道关掉后的样子"></p>
<p align="center">营销通知按渠道关：天气的「内容与营销」关掉，天气预警保留。</p>

---

## 仓库结构

```text
AGENTS.md            给 AI 智能体读的操作规范
CHANGELOG.md         源码更新、验证结果与安装包发布状态
docs/
  00-打开开发者模式.md 带截图的分步教程
  01-准备工作.md      装 adb、连电脑、无线调试
  02-用AI智能体.md    WorkBuddy、Claude Code、Codex、Trae、Cursor
  03-用聊天AI.md      DeepSeek、豆包、ChatGPT
  04-给新机型写脚本.md
  05-还原.md
  06-常见问题.md
  07-快应用.md        什么是快应用、怎么检测和关闭
  08-桌面客户端.md     Mac / Windows 客户端的用法、数据位置、打包
  09-社区问题处理.md   Issue / PR 处理范围及待验证项
  清单/               各品牌的手动清单
prompts/             复制给聊天 AI 的提示词
tool/
  run.py             总入口
  fast.py            读屏、找入口、拨开关的引擎（uiautomator2）
  chan_fast.py       营销通知渠道
  explore.py         新机型探路（实验）
gui/                 桌面客户端（pywebview 界面 + PyInstaller 打包）
recipes/<品牌>-<型号>/recipe.py   各机型的机型脚本
images/              文档配图
tests/               不连接手机的引擎回归测试
```

## 反馈

遇到问题、想要新功能、希望支持你的手机，到 [Issues](https://github.com/rddmwmddr/android-ad-cleaner/issues/new/choose) 提交，选对应的模板。

用桌面客户端的话，点左下角「反馈问题」：会自动附上客户端版本、手机型号、系统版本和最近的日志（序列号已替换，不含应用列表和通知内容），打开 GitHub 页面后点提交即可。提交需要 GitHub 账号。

## 还原

见 [docs/05-还原.md](docs/05-还原.md)。挂起的包和通知渠道各一条命令；App 内的开关按清单路径手动打开。

## 声明

本项目只调用 Android 系统和厂商 App 公开提供的设置项。各厂商的界面随系统更新变化，使用前请备份，结果以你的手机为准。使用本项目造成的任何问题由使用者自行承担。

许可证：MIT
