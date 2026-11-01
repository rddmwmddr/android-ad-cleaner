# 手机去广告

关掉国产安卓手机系统里的广告、热搜、资讯推荐和营销推送。

介绍页：**https://rddmwmddr.github.io/android-ad-cleaner/**

## 下载桌面客户端

插上手机，点几下按钮。不需要 Python，也不需要 AI 工具。

> **v0.3.0 · 2026-11-01**：修 0.2.9 之后社区报告的十几个问题（华为同名渠道行、vivo 旧系统和「运营消息」渠道、安卓 17 页面没画完就找入口、小米商店误点、OPPO 关快应用后快递卡片打不开、POCO 广告组件、连接提示品牌认错等）；新增 vivo X Fold6、Redmi Note 14 5G、一加 Ace 6T、小米 14 Pro 机型脚本和新机型适配辅助 `run.py adapt`；引擎重构，用法不变。旧版不会自动更新，0.2.7 起的客户端左下角会提示新版；请重新下载，已有备份会保留。详见 [更新说明](https://github.com/rddmwmddr/android-ad-cleaner/releases)，错误日志上报说明见 [这里](docs/12-错误日志上报.md)。官网：https://ahuamiao.com/sites/other/android-ad-removal-intro.html

此前版本已处理 Windows 本地页面超时、荣耀截图越界、通知渠道误操作风险、vivo 快应用与备份问题。各 Issue 的处理范围和待验证项见 [社区问题处理记录](docs/09-社区问题处理.md)。仅支持通过 adb 连接的安卓设备，暂不支持使用 HDC 的原生鸿蒙。

| 电脑 | 下载 | 说明 |
|---|---|---|
| Mac · Apple 芯片（M1 及以后） | [AndroidAdCleaner-0.3.0-mac-arm64.dmg](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.3.0/AndroidAdCleaner-0.3.0-mac-arm64.dmg) | 已签名、通过苹果公证，双击就能打开 |
| Mac · Intel 芯片（macOS 11 及以上） | [AndroidAdCleaner-0.3.0-mac-intel.dmg](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.3.0/AndroidAdCleaner-0.3.0-mac-intel.dmg) | 同上 |
| Windows 10 / 11 · 安装版 | [AndroidAdCleaner-0.3.0-windows-setup.exe](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.3.0/AndroidAdCleaner-0.3.0-windows-setup.exe) | 弹「Windows 已保护你的电脑」时点「更多信息」→「仍要运行」 |
| Windows 10 / 11 · 免安装 | [AndroidAdCleaner-0.3.0-windows-portable.zip](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.3.0/AndroidAdCleaner-0.3.0-windows-portable.zip) | 解压后双击 `AndroidAdCleaner.exe` |

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
| 魅族 | 21 Pro（MEIZU 21 Pro） | Flyme 12.6.0.0A / Android 16 | ⚠️ 10-30 真机分段验证目标均已关闭；从开启状态自动关闭待验证，其他版本停止 | ✅ | ✅ 本机 8 个营销渠道 |
| 华为 | ALN-AL00 | HarmonyOS 4.2.0.223 / Android 12 | ⚠️ 营销通知命令行工具，需先人工审核清单，客户端不自动运行；[用法](docs/清单/华为-ALN-AL00-营销通知.md) | [范围与路径](docs/清单/华为-HarmonyOS.md) | 本次人工审核 79 个候选：关闭 48 个、31 个原已整体屏蔽；不代表新脚本整轮成绩 |
| 荣耀 | PNM-AN10 | MagicOS 10 | ✅ 实测通过，重跑 4 分钟 | ✅ | ✅ 26 个渠道 |
| 荣耀 | WKL-AN20 | MagicOS 11.0.0.111 / Android 17 | ⚠️ 2026-10-28 路径逐项实测，新脚本整轮待复测、用时未测；音乐需手动开页，见[说明](recipes/honor-WKL-AN20/README.md) | ✅ | ✅ 人工关闭 13 个渠道，其他渠道和总开关未变 |
| 一加 | Ace 2 Pro（PJA110） | ColorOS 14.0.0.812 / Android 14 | 源码新增：3 项个性化 + 6 项商店推广位关闭并回读 | 部分，见实测记录 | ✅ 23 个，总开关不变；天气提醒差异见实测 |
| 一加 | 13T（PKX110） | ColorOS 16.0.10.500 / Android 16 | ✅ 2026-10-28 实测：广告跟踪 76 项、商店两段、小布建议；浏览器/下拉搜索/负一屏见清单差异 | ✅ | ✅ 17 个渠道 |
| 一加 | Ace 6T（PLR110） | ColorOS 17.0.0.101 / Android 17 | ✅ 2026-10-31 贡献者真机九段全跑 224 秒；本仓库无该机型，未复测，见[清单差异](docs/清单/OPPO-ColorOS.md) | ✅ | —（未测） |
| OPPO | Find N6（PLP120） | ColorOS 16.0.9 | ⚠️ 路径实测，整段待验证 | ✅ | ✅ 30 个渠道 |
| OPPO | Find X10 Pro Max（PMX110） | ColorOS 17 | — | ✅ | ✅ |
| OPPO | Find X8s（PKT110） | ColorOS 17.0.0.102(CN01) / Android 17 | ✅ 10-28 真机整段重跑通过：广告跟踪 96 项 + 搜索与建议等 12 项逐项回读确认 | ✅ | ✅ 26 个渠道 |
| OPPO | Find X9 Ultra（PMA110） | ColorOS 17.0.0.106(CN01) / Android 17 | ✅ 2026-10-29 八段整轮通过，重跑 211 秒，回读确认 173 项；见[说明](recipes/oppo-PMA110/README.md) | ✅ | ✅ 独立关闭并回读 6 个营销渠道，其他原有渠道及总开关未变 |
| OPPO | Find X9 Pro（PLG110） | ColorOS 16.0.10.501(CN01) / Android 16 | ✅ 2026-11-01 九段逐项实测通过，回读确认 165 项；见[说明](recipes/oppo-PLG110/README.md) | ✅ | ✅ 60 个营销渠道全部关闭并回读确认（0 遗留） |
| OPPO | Find X10 Pro Max（PMX110） | ColorOS 17.0.0.116 / Android 17 | ✅ 源码新增：9 段，全跑约 4 分钟；下拉搜索需手动，浏览器「摇一摇广告」点不动 | ✅ | ✅ 45 个渠道 |
| OPPO | Find X9 Ultra（PMA120） | ColorOS 16.0.10 | ❌ 页面和 N6 不同，待补 | 部分 | ✅ 27 个渠道 |
| OPPO | Find N3 典藏版（PHN110） | ColorOS 16.0.5 | ❌ 待补 | 部分 | ✅ 27 个渠道 |
| OPPO | Find N5（PKH110） | ColorOS 17.0.0.103 / Android 17 | ✅ 2026-10-29 七段实测通过，重跑 144 秒；负一屏需手动（设置页受权限保护） | ✅ | ✅ 42 个渠道 |
| 小米 | 18 Pro Max（M154FF） | HyperOS 4.0.24 | ✅ 10-25 前轮九段通过，新增兼容改动待复测 | ✅ | ✅ |
| 小米 | 17 Ultra 标准版（2512BPNDAC） | HyperOS OS4.0.5.0.XPACNXM / Android 17 | ✅ 10-28 九段实测通过，重跑 176 秒 | ✅ | ✅ 1 个渠道（商店「其他」） |
| 小米 | 17（25113PN0EC） | HyperOS 4 / Android 17 | — 无专用脚本 | ✅ 见[清单](docs/清单/小米-HyperOS.md) | ✅ 无营销渠道；1 个候选属服务类，已跳过 |
| 小米 | 15（24129PN74C） | HyperOS OS4.0.0.22.XOCCNXM / Android 17 | ✅ 10-29 九段实测通过，重跑 164 秒 | ✅ | —（未跑） |
| 小米 | 13 Ultra（2304FPN6DC） | HyperOS OS3.0.308 / Android 16 | ✅ 10-28 九段通过，复跑 3 分 16 秒 | ✅ | —（未跑） |
| 小米 | 14 Pro（23116PN5BC） | HyperOS OS3.0.308.0.WNBCNXM / Android 16 | ⚠️ 10-29 社区实测：与 13 Ultra 共用脚本，安全模式下九段跑通、275 秒、19 项关闭并回读；浏览器「搜索设置」未命中，正常模式整轮待复测 | ✅ | ✅ 60 个渠道（64 候选，人工剔除 4 条服务类） |
| 小米 | Pad 7（2410CRP4CC） | HyperOS OS2.0.208 / Android 15 | ✅ 10-28 四段通过，复跑 61 秒 | ✅ | —（未跑） |
| 小米 | REDMI K80 至尊版（25060RK16C） | HyperOS 2（BP2A.250605.031.A3）/ Android 16 | ✅ 10-27 真机九段通过，重跑 3 分钟 | ✅ | ✅ 3 个渠道 |
| 小米 | 15（24129PN74C） | HyperOS OS3.0.307.0.WOCCNXM / Android 16 | ⚠️ 10-29 路径逐项实测、开关已实际关闭；新脚本整轮待复测、用时未测，底包同 K80 但浏览器/商店入口不同 | ✅ | ✅ 17 个渠道，全部关闭 |
| 小米 | REDMI K90 Pro Max（25102RKBEC） | HyperOS OS4.0.2.0.XPMCNXM / Android 17 | ✅ 10-27 九段实测通过，重跑 169 秒 | ✅ | ✅ 26 个渠道 |
| 小米 | REDMI K80 Pro（24122RKC7C） | HyperOS OS3.0.304.0.WOMCNXM / Android 16 | ✅ 10-29 九段实测，首轮关 20 项，复跑 172 秒；[实测记录](docs/15-红米K80Pro实测.md) | ✅ | ✅ 48 个渠道（54 候选） |
| 小米 | Redmi Note 14 Pro（24090RA29C） | HyperOS 3.0.309.0 / Android 16 | ✅ 10-26 八段实测通过，整轮约 5 分钟 | ✅ | ✅ 11 个渠道 |
| 小米 | Redmi Note 14 5G（24094RAD4C） | HyperOS OS3.0.306.0.WOQCNXM / Android 16 | ✅ 10-30 八段实测：20 项新关闭（记账修复前统计，不含普通点击关掉的 4 项），复跑 291 秒、21 项回读、调整 0 项 | ✅ | ✅ 3 个渠道，全部关闭 |
| Redmi | Note 12 Turbo（23049RAD8C） | HyperOS OS3.0.5.0 | ✅ 实测通过，九段 3.5 分钟 | ✅ | ✅ |
| Redmi | K70（23113RKC6C） | HyperOS 3.0.307.0 / Android 16 | ⚠️ 9 段专用脚本，目标 20 项；[实测记录](docs/13-红米K70实测.md) | ✅ | —（未测通知） |
| Redmi | K70 Pro（23117RK66C） | HyperOS OS3.0.306.0.WNMCNXM / Android 16 | ✅ 10-30 九段整轮 235 秒，25 项回读、0 调整、0 异常；[实测记录](docs/14-红米K70Pro实测.md) | ✅ | ✅ 17 个渠道，其他已有渠道和总开关不变 |
| vivo | X300 Ultra（V2547DA） | OriginOS 6 | ✅ 2026-10-28 实测通过，七段全通（124 秒） | ✅ | ✅ |
| vivo | X Fold6（V2545A） | OriginOS 6 Fold / Android 16 | ✅ 实测通过，7 段 121 秒（合上外屏） | 部分（负一屏、i 管家需手动） | ⚠️ 仅 1 条候选，应用级开关已跳过 |
| vivo（iQOO） | V2324HA | 原系统 Android 16（PD2324J_A_16.2.13.1.W10） | ✅ 2026-10-27 实测，七段全通，重跑 2.5 分钟 | ✅ | 5 个渠道，关 3 个、跳过 1 个 |
| vivo | V2361A | OriginOS 16（PD2361B_A_16.2.12.2.W10） | ⚠️ 2026-10-26 路径逐页实测、开关已实际关闭；引擎整段待验证 | ✅ | — |
| vivo（iQOO） | V1986A | Funtouch OS 13.0 / Android 12（PD1986_A_8.21.29） | ✅ 2026-10-30 三段实测通过，重跑 55 秒 | ✅ 见[清单差异](docs/清单/vivo-OriginOS.md) | ⚠️ 11 个营销渠道人工关 8 个；本机 `chan-off` 认不出通知页（[#336](https://github.com/rddmwmddr/android-ad-cleaner/issues/336)），源码已按同一判据放宽认页、待报告者复测 |
| vivo | V2417A | OriginOS 6 / Android 16（PD2417D_A_16.2.14.1.W10） | ✅ 2026-10-30 八段整段实测通过，回读核对 32 项，幂等复跑 179 秒；[适配说明](recipes/vivo-V2417A/README.md) | ✅ | ✅ 通用流程关闭 5 个明确营销渠道 |
| vivo | X300 Ultra（V2547A） | OriginOS 7 | ✅ 2026-10-25 实测通过，重跑 126 秒 | ✅ | ⚠️ 只有应用级总开关 |
| 一加 | Ace 2（PHK110） | ColorOS 16.0.5 / Android 16 | ✅ 2026-10-25 路径实测、整段重跑约 85 秒 | ✅ | 11 个关闭，1 个受限 |
| 一加 | Ace 2（PHK110） | ColorOS 15.0.0.601 / Android 15 | 2026-10-29 手动路径实测；自动脚本尚未整段真机验证 | 部分路径 | 渠道按独立流程处理 |

表格反映当前脚本和验证范围。小米 10、荣耀 Magic7 Pro 等反馈已修复可定位的通用缺陷，但仍需对应真机复测；同品牌参考脚本不等于专用适配，详细记录见 [归档记录](docs/归档/CHANGELOG-0.3.0及更早.md)。

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
CHANGELOG.md         本版起的变更记录（一条一行）；详细历史见 docs/归档/
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
