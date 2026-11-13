# 肉呆去广告

关掉国产安卓手机系统里的广告、热搜、资讯推荐和营销推送。

介绍页：**https://rddmwmddr.github.io/android-ad-cleaner/**

如果大家有其他需求可以加VX和电报群：

https://t.me/+A5X3Mxzs-Cg3NjYx

<img width="1080" height="1596" alt="IMG_7235" src="https://github.com/user-attachments/assets/6197911c-7b6d-47eb-a698-107b99865aee" />


## 下载桌面客户端

插上手机，点几下按钮。不需要 Python，也不需要 AI 工具。

> **v0.4.4 · 2026-11-13**：这一版给一加 16 与真我 GT5 Pro 补了机型脚本，修好了长列表页只关最后一段、vivo 锁屏段一直没生效等几处问题；引擎里把各机型脚本里重复的段体与导航收成共用一份，用起来不变。0.4.1 及以前没有应用内更新，要先手动装一次 0.4.2；从 0.4.2 起可以在 App 里检查、下载并安装更新，手机版仍需在系统弹窗里确认；0.2.7 起的客户端左下角会提示新版；请重新下载，已有备份会保留。详见 [更新记录](CHANGELOG.md)，错误日志上报说明见 [这里](docs/12-错误日志上报.md)。官网：https://ahuamiao.com/sites/other/android-ad-removal-intro.html

此前版本已处理 Windows 本地页面超时、荣耀截图越界、通知渠道误操作风险、vivo 快应用与备份问题。各 Issue 的处理范围和待验证项见 [社区问题处理记录](docs/09-社区问题处理.md)。0.4.2 起 Mac / Windows 客户端也能连纯血鸿蒙手机，这条通道还没有在鸿蒙真机上复测，见 [鸿蒙接入说明](harmony/README.md)。

| 设备 | 下载 | 说明 |
|---|---|---|
| Mac · Apple 芯片（M1 及以后） | [AndroidAdCleaner-0.4.4-mac-arm64.dmg](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.4.4/AndroidAdCleaner-0.4.4-mac-arm64.dmg) | 已签名、通过苹果公证，双击就能打开 |
| Mac · Intel 芯片（macOS 11 及以上） | [AndroidAdCleaner-0.4.4-mac-intel.dmg](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.4.4/AndroidAdCleaner-0.4.4-mac-intel.dmg) | 同上 |
| Windows 10 / 11 · 安装版 | [AndroidAdCleaner-0.4.4-windows-setup.exe](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.4.4/AndroidAdCleaner-0.4.4-windows-setup.exe) | 弹「Windows 已保护你的电脑」时点「更多信息」→「仍要运行」；和旧版共用安装标识，会原地升级 |
| Windows 10 / 11 · 免安装 | [AndroidAdCleaner-0.4.4-windows-portable.zip](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.4.4/AndroidAdCleaner-0.4.4-windows-portable.zip) | 解压后双击 `AndroidAdCleaner.exe`；不会替换、也不会卸载已安装的旧版 |
| 安卓手机 · 手机版（安卓 11 及以上） | [AndroidAdCleaner-0.4.4-android-arm64.apk](https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v0.4.4/AndroidAdCleaner-0.4.4-android-arm64.apk) | 不用连电脑，安装和授权见[手机版教程](docs/手机版教程/README.md) |

不知道 Mac 是哪种芯片：左上角苹果图标 → 关于本机，「芯片」写 Apple M 开头的选 Apple 芯片。所有版本：[Releases](https://github.com/rddmwmddr/android-ad-cleaner/releases)；国内下载走 [Gitee](https://gitee.com/rddmw/android-ad-cleaner/releases)，不用登录（Windows 安装版只在 GitHub 上）。国内走 Gitee 时拿到的是 Windows 免安装版，它不会替换已安装的旧版：要顶掉旧版，用安装版覆盖安装，或先在 Windows「设置」的应用列表里卸载旧的「安卓去广告」（0.3.2 及更早版本装的名字）再删掉旧快捷方式；卸载只删程序目录，数据与备份保留；免安装版启动时若发现旧版还在，也会在界面里提示一次。用法：[docs/08-桌面客户端.md](docs/08-桌面客户端.md)。

> 手机版是不用连电脑的安卓 App（见下面[用法五](#五种用法)）：安装包在上面的表里，安装、授权与还原步骤见[手机版教程](docs/手机版教程/README.md)；想自己构建看 [android/](android/README.md)。

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

## 五种用法

<p align="center"><img src="images/ways.png" width="460" alt="用法示意"></p>

> 用法一要先在手机上打开开发者模式和 USB 调试，带截图的教程：[docs/00-打开开发者模式.md](docs/00-打开开发者模式.md)。

| 用法 | 适合谁 | 要准备什么 | 文档 |
|---|---|---|---|
| **一：AI 智能体替你跑** | 有电脑，想省事 | 电脑、数据线、一个能执行命令的 AI 工具 | [docs/02-用AI智能体.md](docs/02-用AI智能体.md) |
| **二：聊天 AI 带你点** | 只有手机 | DeepSeek、豆包、ChatGPT 任意一个 | [docs/03-用聊天AI.md](docs/03-用聊天AI.md) |
| **三：照清单手动关** | 想自己掌握每一步 | 只要手机 | [docs/清单/](docs/清单/) |
| **四：桌面客户端** | 不想敲命令 | Mac（Apple / Intel 芯片）或 Windows 10/11、数据线 | [下载](#下载桌面客户端) · [说明](docs/08-桌面客户端.md) |
| **五：手机版 App** | 不想连电脑 | 安卓 11 及以上、Wi-Fi；安装包在[下载表](#下载桌面客户端)里 | [教程](docs/手机版教程/README.md) |


用法一的开场白，复制给 AI：

```text
请克隆 https://github.com/rddmwmddr/android-ad-cleaner ，读仓库里的 AGENTS.md，
然后帮我给连着电脑的这台手机去广告。每一步改之前告诉我要改什么。
```

---

## 实测过的机型

**机型脚本**：一台机型的自动操作步骤，记着「打开哪个 App、点哪几个字进设置页、关哪几个开关、留哪几个」。电脑照着它在手机上点，几分钟做完。设置页因型号和系统版本而不同，所以每个机型一份。

| 品牌 | 机型（型号） | 系统 | 脚本 | 清单 | 营销通知 |
|---|---|---|---|---|---|
| 魅族 | 21 Pro（MEIZU 21 Pro） | Flyme 12.6.0.0A<br>Android 16 | ⚠️ 10-30 | ✅ | ✅ 8 |
| 华为 | ALN-AL00 | HarmonyOS 4.2.0.223<br>Android 12 | ⚠️ | ✅ | ⚠️ 48 |
| 荣耀 | PNM-AN10 | MagicOS 10 | ✅ | ✅ | ✅ 26 |
| 荣耀 | WKL-AN20 | MagicOS 11.0.0.111<br>Android 17 | ⚠️ 10-28 | ✅ | ✅ 13 |
| 荣耀 | Magic V Flip2（CLE-AN00） | MagicOS 10.0.0.175<br>Android 16 | ✅ 11-07 | ✅ | ✅ 3 |
| 一加 | 15T（PLZ110） | ColorOS 17.0.0.107<br>Android 17 | ⚠️ 11-08 | 部分 | ✅ |
| 一加 | Ace 2 Pro（PJA110） | ColorOS 14.0.0.812<br>Android 14 | ⚠️ | 部分 | ✅ 23 |
| 一加 | Ace 2 Pro（PJA110） | ColorOS 16.0.5.1201<br>Android 16 | ⚠️ | 部分 | — |
| 一加 | 13T（PKX110） | ColorOS 16.0.10.500<br>Android 16 | ✅ 10-28 | ✅ | ✅ 17 |
| 一加 | Ace 6T（PLR110） | ColorOS 17.0.0.101<br>Android 17 | ✅ 10-31 | ✅ | — |
| 一加 | 一加 16（PYB110） | ColorOS 17.0.0.157<br>Android 17 | ✅ 11-12 | ✅ | — |
| OPPO | Find N6（PLP120） | ColorOS 16.0.9 | ⚠️ | ✅ | ✅ 30 |
| OPPO | Find X8s（PKT110） | ColorOS 17.0.0.102<br>Android 17 | ✅ 10-28 | ✅ | ✅ 26 |
| OPPO | Find X9 Ultra（PMA110） | ColorOS 17.0.0.106<br>Android 17 | ✅ 10-29 | ✅ | ✅ 6 |
| OPPO | Find X9 Pro（PLG110） | ColorOS 16.0.10.501<br>Android 16 | ✅ 11-01 | ✅ | ✅ 60 |
| OPPO | Find X10 Pro Max（PMX110） | ColorOS 17.0.0.116<br>Android 17 | ✅ 11-07 | 部分 | ✅ 3 |
| OPPO | Find X9 Ultra（PMA120） | ColorOS 16.0.10 | ❌ | 部分 | ✅ 27 |
| OPPO | Find N3 典藏版（PHN110） | ColorOS 16.0.5 | ❌ | 部分 | ✅ 27 |
| OPPO | Find N5（PKH110） | ColorOS 17.0.0.103<br>Android 17 | ✅ 10-29 | ✅ | ✅ 42 |
| 小米 | 18 Pro Max（M154FF） | HyperOS 4.0.24 | ✅ 11-07 | ✅ | ✅ |
| 小米 | 17 Ultra 标准版（2512BPNDAC） | HyperOS OS4.0.5.0.XPACNXM<br>Android 17 | ✅ 10-28 | ✅ | ✅ 1 |
| 小米 | 17（25113PN0EC） | HyperOS 4<br>Android 17 | — | ✅ | ✅ |
| 小米 | 15（24129PN74C） | HyperOS OS4.0.0.22.XOCCNXM<br>Android 17 | ✅ 10-29 | ✅ | — |
| 小米 | 13 Ultra（2304FPN6DC） | HyperOS OS3.0.308<br>Android 16 | ✅ 10-28 | ✅ | — |
| 小米 | 14 Pro（23116PN5BC） | HyperOS OS3.0.308.0.WNBCNXM<br>Android 16 | ⚠️ 10-29 | ✅ | ✅ 60 |
| 小米 | Pad 7（2410CRP4CC） | HyperOS OS2.0.208<br>Android 15 | ✅ 10-28 | ✅ | — |
| 小米 | REDMI K80 至尊版（25060RK16C） | HyperOS 2<br>Android 16 | ✅ 10-27 | ✅ | ✅ 3 |
| 小米 | 15（24129PN74C） | HyperOS OS3.0.307.0.WOCCNXM<br>Android 16 | ⚠️ 10-29 | ✅ | ✅ 17 |
| 小米 | REDMI K90 Pro Max（25102RKBEC） | HyperOS OS4.0.2.0.XPMCNXM<br>Android 17 | ✅ 10-27 | ✅ | ✅ 26 |
| 小米 | REDMI K90 Ultra（M332BF） | HyperOS OS4.0.4.0.XHPCNXM<br>Android 17 | ⚠️ 10-31 | ✅ | ✅ 19 |
| 小米 | REDMI K90（2510DRK44C） | HyperOS OS4.0.5.0.XPKCNXM<br>Android 17 | ⚠️ 11-10 | ✅ | ✅ 8 |
| 小米 | MIX Flip 2（2505APX7BC） | HyperOS<br>Android 16 | ⚠️ 11-05 | ✅ | ✅ 22 |
| 小米 | REDMI K80 Pro（24122RKC7C） | HyperOS OS3.0.304.0.WOMCNXM<br>Android 16 | ✅ 10-29 | ✅ | ✅ 48 |
| 小米 | Redmi Note 14 Pro（24090RA29C） | HyperOS 3.0.309.0<br>Android 16 | ✅ 10-26 | ✅ | ✅ 11 |
| 小米 | Redmi Note 14 5G（24094RAD4C） | HyperOS OS3.0.306.0.WOQCNXM<br>Android 16 | ✅ 10-30 | ✅ | ✅ 3 |
| 小米 | Redmi Note 13（23124RA7EO） | HyperOS OS2.0.213.0.VNHRUXM<br>Android 15 | — | ✅ | — |
| Redmi | Note 12 Turbo（23049RAD8C） | HyperOS OS3.0.5.0 | ✅ | ✅ | ✅ |
| Redmi | K70（23113RKC6C） | HyperOS 3.0.307.0<br>Android 16 | ⚠️ | ✅ | — |
| Redmi | K70 Pro（23117RK66C） | HyperOS OS3.0.306.0.WNMCNXM<br>Android 16 | ✅ 10-30 | ✅ | ✅ 17 |
| vivo | X300 Ultra（V2547DA） | OriginOS 6 | ✅ 10-28 | ✅ | ✅ |
| vivo | X300 Ultra（V2547DA） | Android 17 | ✅ 11-07 | ✅ | — |
| vivo | X Fold6（V2545A） | OriginOS 6 Fold<br>Android 16 | ✅ | 部分 | ⚠️ |
| vivo（iQOO） | V2324HA | Android 16 | ✅ 10-27 | ✅ | ⚠️ 3 |
| vivo | V2361A | OriginOS 16 | ⚠️ 10-26 | ✅ | — |
| vivo（iQOO） | V1986A | Funtouch OS 13.0<br>Android 12 | ✅ 10-30 | ✅ | ⚠️ 8 |
| vivo | V2417A | OriginOS 6<br>Android 16 | ✅ 10-30 | ✅ | ✅ 5 |
| vivo | X300 Ultra（V2547A） | OriginOS 7 | ✅ 10-25 | ✅ | ⚠️ |
| vivo（iQOO） | Z11 Turbo（V2536A） | OriginOS 6<br>Android 16 | — | ✅ | — |
| vivo | V2309A | OriginOS 6<br>Android 16 | ✅ 11-03 | ✅ | — |
| vivo | V2303A | OriginOS 7<br>Android 17 | ⚠️ 11-04 | ✅ | — |
| 一加 | Ace 2（PHK110） | ColorOS 16.0.5<br>Android 16 | ✅ 10-25 | ✅ | ⚠️ 11 |
| 一加 | Ace 2（PHK110） | ColorOS 15.0.0.601<br>Android 15 | ⚠️ 10-29 | 部分 | — |
| realme | GT Neo5 SE（RMX3700） | ColorOS 16.0.5.1300<br>Android 16 | ✅ 11-02 | ✅ | — |
| realme | 真我 GT5 Pro（RMX3888） | ColorOS 15.0.0.420<br>Android 15 | ⚠️ | ✅ | ✅ 12 |
| 三星 | Galaxy Note10+ 5G（SM-N9760） | One UI 4<br>Android 12 | ⚠️ 11-05 | ✅ | ⚠️ 10 |

符号：✅ 真机跑通；⚠️ 只跑到部分段落、待复测，营销通知列还表示有渠道没关；❌ 未适配；— 无专用脚本、没有渠道，或这一项没跑过。清单列的「部分」表示有专属清单但要手动补几项。脚本列的日期是最近一次真机实测，没有日期表示只做了路径级核对；每份脚本的覆盖度与证据来源另记在 `recipes/verified.toml`，`python3 tool/verify_ledger.py` 可列。营销通知列是最后确认关闭的渠道数，✅ 不带数字表示当时没记数。

表格反映当前脚本和验证范围。小米 10、荣耀 Magic7 Pro 等反馈已修复可定位的通用缺陷，但仍需对应真机复测；同品牌参考脚本不等于专用适配，详细记录见 [归档记录](docs/归档/CHANGELOG-0.3.0及更早.md)。

- 可先运行通用检测；通知渠道能否安全关闭取决于系统页面和权限，部分 vivo 页面会被跳过。广告跟踪入口也随品牌变化。
- 同一个品牌，系统小版本不同，设置页的名字和层级也会变。机型脚本按型号和系统版本存放，版本对不上时引擎会提示，找不到入口的步骤会跳过，不会乱点。
- 你的机型不在表里：照 [docs/04-给新机型写脚本.md](docs/04-给新机型写脚本.md) 做一份，欢迎提 PR。

**验证记录**（按表格行序，记着每台机的实测日期、用时、回读数与已知差异）

- **魅族 21 Pro（MEIZU 21 Pro）**：10-30 真机分段验证目标均已关闭；浏览器与应用商店两段改过待复测；从开启状态自动关闭待验证，其他版本停止。营销通知本机关闭 8 个营销渠道。
- **华为 ALN-AL00**：脚本列讲的是营销通知命令行工具，需先人工审核清单，客户端不自动运行，[用法](docs/清单/华为-ALN-AL00-营销通知.md)；手动清单见[范围与路径](docs/清单/华为-HarmonyOS.md)。营销通知本次人工审核 79 个候选：关闭 48 个、31 个原已整体屏蔽，不代表新脚本整轮成绩。
- **荣耀 PNM-AN10**：实测通过，重跑 4 分钟。营销通知 26 个渠道。
- **荣耀 WKL-AN20**：2026-10-28 路径逐项实测，新脚本整轮待复测、用时未测；音乐需手动开页，见[说明](recipes/honor-WKL-AN20/README.md)。营销通知人工关闭 13 个渠道，其他渠道和总开关未变。
- **荣耀 Magic V Flip2（CLE-AN00）**：2026-11-07 电脑整轮 325 秒、13 段 12 段完成（主题未同意协议跳过）；手机版 2 分 20 秒，负一屏在后台屏上进不去，也跳过。营销通知关 3 个渠道，复查仍开着 0 个。
- **一加 15T（PLZ110）**：2026-11-08 贡献者真机七段分段核对；专用脚本整轮未验证，商店标题匹配待 #861。手动清单只覆盖部分，见清单。营销通知本轮人工确认清单，其他渠道及总开关未变。
- **一加 Ace 2 Pro（PJA110）**：源码新增 3 项个性化 + 6 项商店推广位关闭并回读，没有真机整轮记录。手动清单部分，见实测记录。营销通知关闭 23 个，总开关不变；天气提醒差异见实测。
- **一加 Ace 2 Pro（PJA110，ColorOS 16）**：脚本入口照同代系统（ColorOS 16）在一加 Ace 2 与 OPPO 机型上已实测的路径改写，本机未跑过、等复测；差异见[清单](docs/清单/OPPO-ColorOS.md)。营销通知未测。
- **一加 13T（PKX110）**：2026-10-28 实测：广告跟踪 76 项、商店两段、小布建议；浏览器/下拉搜索/负一屏见清单差异。营销通知 17 个渠道。
- **一加 Ace 6T（PLR110）**：2026-10-31 贡献者真机九段全跑 224 秒；本仓库无该机型，未复测，见[清单差异](docs/清单/OPPO-ColorOS.md)。营销通知未测。
- **一加 16（PYB110）**：2026-11-12 本机九段全跑 397 秒，二次重跑幂等；商店「我的」页没有设置文字行，走 `APP_SETTINGS` 直达，负一屏的个性化开关挪到了「隐私」里，见[清单差异](docs/清单/OPPO-ColorOS.md)。营销通知未测。
- **OPPO Find N6（PLP120）**：路径实测，整段待验证。营销通知 30 个渠道。
- **OPPO Find X8s（PKT110）**：10-28 真机整段重跑通过：广告跟踪 96 项 + 搜索与建议等 12 项逐项回读确认。营销通知 26 个渠道。
- **OPPO Find X9 Ultra（PMA110）**：2026-10-29 八段整轮通过，重跑 211 秒，回读确认 173 项；见[说明](recipes/oppo-PMA110/README.md)。营销通知独立关闭并回读 6 个营销渠道，其他原有渠道及总开关未变。
- **OPPO Find X9 Pro（PLG110）**：2026-11-01 九段逐项实测通过，回读确认 165 项；见[说明](recipes/oppo-PLG110/README.md)。营销通知 60 个营销渠道全部关闭并回读确认（0 遗留）。
- **OPPO Find X10 Pro Max（PMX110）**：社区实测 2026-11-05 八段整轮 540 秒、退出码 0（该机当时未装游戏中心）；2026-11-06 同机按段提速（游戏中心当天已装）：广告跟踪 1623→41 秒、游戏中心由失败转为 27 秒、视频 31→22 秒、负一屏 41→38 秒；2026-11-07 从开启状态整轮 485 秒，实际调整 15 项、回读 46 项，退出码 1 只因负一屏段读不到轮播单选（#801）；本仓库未复跑；见[说明](recipes/oppo-PMX110/README.md)。手动清单要保留搜索数据源、消息通知与卡片。营销通知本次独立关闭 3 个，总开关未变。
- **OPPO Find X9 Ultra（PMA120）**：页面和 N6 不同，待补。营销通知 27 个渠道。
- **OPPO Find N3 典藏版（PHN110）**：待补。营销通知 27 个渠道。
- **OPPO Find N5（PKH110）**：2026-10-29 七段实测通过，重跑 144 秒；负一屏需手动（设置页受权限保护）。营销通知 42 个渠道。
- **小米 18 Pro Max（M154FF）**：2026-11-07 九段全过（设置页改直达，150 → 97 秒）；浏览器段不再依赖首页，后台屏也能跑；见[说明](recipes/xiaomi-M154FF/README.md)。
- **小米 17 Ultra 标准版（2512BPNDAC）**：10-28 九段实测通过，重跑 176 秒。营销通知 1 个渠道（商店「其他」）。
- **小米 17（25113PN0EC）**：无专用脚本。手动清单见[清单](docs/清单/小米-HyperOS.md)。营销通知本机没有营销渠道，1 个候选属服务类，已跳过。
- **小米 15（24129PN74C）· HyperOS OS4.0.0.22.XOCCNXM**：10-29 九段实测通过，重跑 164 秒。营销通知未跑。
- **小米 13 Ultra（2304FPN6DC）**：10-28 九段通过，复跑 3 分 16 秒。营销通知未跑。
- **小米 14 Pro（23116PN5BC）**：10-29 社区实测，与 13 Ultra 共用脚本：安全模式下九段跑通、275 秒、19 项关闭并回读；浏览器「搜索设置」未命中，正常模式整轮待复测。营销通知 60 个渠道（64 候选，人工剔除 4 条服务类）。
- **小米 Pad 7（2410CRP4CC）**：10-28 四段通过，复跑 61 秒。营销通知未跑。
- **小米 REDMI K80 至尊版（25060RK16C）**：底包 BP2A.250605.031.A3；10-27 真机九段通过，重跑 3 分钟。营销通知 3 个渠道。
- **小米 15（24129PN74C）· HyperOS OS3.0.307.0.WOCCNXM**：10-29 路径逐项实测、开关已实际关闭；新脚本整轮待复测、用时未测，底包同 K80 但浏览器/商店入口不同。营销通知 17 个渠道，全部关闭。
- **小米 REDMI K90 Pro Max（25102RKBEC）**：10-27 九段实测通过，重跑 169 秒。营销通知 26 个渠道。
- **小米 REDMI K90 Ultra（M332BF）**：10-31 社区实测，@Sin1ery 本机九段跑通、复跑 179 秒、0 调整；按他的实测规格重写、本仓库未复跑，待其复测，见[实测记录](docs/16-红米K90至尊实测.md)。手动清单见[清单](docs/清单/小米-HyperOS.md)。营销通知 19 个渠道（21 候选，剔除 2 条服务类）。
- **小米 REDMI K90（2510DRK44C）**：11-10 社区实测（[Issue #929](https://github.com/rddmwmddr/android-ad-cleaner/issues/929)）：借 18 Pro Max 脚本跑通九段中的八段、关 16 项；挂起 `com.miui.systemAdSolution` 后主题段补关 2 项，累计 18 项。已按本型号登记进 `recipes/xiaomi-M154FF`，本仓库未在该机复跑。手动清单见[清单](docs/清单/小米-HyperOS.md)。营销通知 8 个第三方渠道全部关闭并回读确认（系统 App 的 msa 营销渠道是系统锁定、不可关闭）。
- **小米 MIX Flip 2（2505APX7BC）**：底包 BP2A.250605.031.A3；11-05 社区实测（合盖外屏）：该机借同底包参考脚本跑通六段，主题 / 浏览器 / 天气 / 日历四处入口不同；专用脚本按该机实测路径写成、本仓库未复跑、用时未测，待其复测，见[说明](recipes/xiaomi-2505APX7BC/README.md)。手动清单见[清单](docs/清单/小米-HyperOS.md)。营销通知关闭 22 个渠道，复查仍开着 0 个。
- **小米 REDMI K80 Pro（24122RKC7C）**：10-29 九段实测，首轮关 20 项，复跑 172 秒；[实测记录](docs/15-红米K80Pro实测.md)。营销通知 48 个渠道（54 候选）。
- **小米 Redmi Note 14 Pro（24090RA29C）**：10-26 八段实测通过，整轮约 5 分钟。营销通知 11 个渠道。
- **小米 Redmi Note 14 5G（24094RAD4C）**：10-30 八段实测：20 项新关闭（记账修复前统计，不含普通点击关掉的 4 项），复跑 291 秒、21 项回读、调整 0 项。营销通知 3 个渠道，全部关闭。
- **小米 Redmi Note 13 海外版 / 俄区（23124RA7EO）**：无专用脚本，界面是俄语，引擎按中文找不到入口。手动清单见[清单](docs/清单/小米-HyperOS.md#海外版-hyperosredmi-note-1323124ra7eo的差异)（11-01 社区实测，adb + 手动）。营销通知未跑。
- **Redmi Note 12 Turbo（23049RAD8C）**：实测通过，九段 3.5 分钟。
- **Redmi K70（23113RKC6C）**：9 段专用脚本，目标 20 项；[实测记录](docs/13-红米K70实测.md)。营销通知未测。
- **Redmi K70 Pro（23117RK66C）**：10-30 九段整轮 235 秒，25 项回读、0 调整、0 异常；[实测记录](docs/14-红米K70Pro实测.md)。营销通知 17 个渠道，其他已有渠道和总开关不变。
- **vivo X300 Ultra（V2547DA）· OriginOS 6**：2026-10-28 实测通过，七段全通（124 秒）；见[适配说明](recipes/vivo-V2547DA/README.md)。
- **vivo X300 Ultra（V2547DA）· Android 17（PD2547D_A_17.1.10.2.W10）**：2026-11-07 七段全过（设置页改直达，91 → 62 秒）；商店「个性化推荐」页仍按位置点、不靠标题（[#220](https://github.com/rddmwmddr/android-ad-cleaner/issues/220)）；见[适配说明](recipes/vivo-V2547DA/README.md)。手动清单见[清单差异](docs/清单/vivo-OriginOS.md)。营销通知未测。
- **vivo X Fold6（V2545A）**：实测通过，7 段 121 秒（合上外屏）。手动清单部分（负一屏、i 管家需手动）。营销通知仅 1 条候选，应用级开关已跳过。
- **vivo（iQOO）V2324HA**：原系统（PD2324J_A_16.2.13.1.W10）；2026-10-27 实测，七段全通，重跑 2.5 分钟。营销通知 5 个渠道，关 3 个、跳过 1 个。
- **vivo V2361A**：系统 OriginOS 16（PD2361B_A_16.2.12.2.W10）；2026-10-26 路径逐页实测、开关已实际关闭，引擎整段待验证。
- **vivo（iQOO）V1986A**：系统 Funtouch OS 13.0 / Android 12（PD1986_A_8.21.29）；2026-10-30 三段实测通过，重跑 55 秒。营销通知 11 个营销渠道人工关 8 个；本机 `chan-off` 认不出通知页（[#336](https://github.com/rddmwmddr/android-ad-cleaner/issues/336)），源码已按同一判据放宽认页、待报告者复测。手动清单见[清单差异](docs/清单/vivo-OriginOS.md)。
- **vivo V2417A**：系统 OriginOS 6 / Android 16（PD2417D_A_16.2.14.1.W10）；社区实测 10-30 八段整段跑通、回读核对 32 项、幂等复跑 179 秒；11-02 浏览器升到 31.3.0.0 后入口变了，改走「我的 → 设置」，八段仍通过；维护方未在本机复跑；[适配说明](recipes/vivo-V2417A/README.md)。营销通知通用流程关闭 5 个明确营销渠道。
- **vivo X300 Ultra（V2547A）**：2026-10-25 实测通过，重跑 126 秒。营销通知只有应用级总开关。
- **vivo（iQOO）Z11 Turbo（V2536A）**：系统 OriginOS 6 / Android 16（PD2536B_A_16.0.12.8.W10）；无专用脚本，用 `--ref` 安全模式实测。手动清单见[清单差异](docs/清单/vivo-OriginOS.md)。
- **vivo V2309A**：系统 OriginOS 6 / Android 16（PD2309E_A_16.2.15.0.W10）；社区实测 11-03 从开启状态七段整段跑通，26 个开关逐个关闭、回读核对（213 秒），复跑轮调整 0 项（165 秒）；维护方未在本机复跑；商店「个性化推荐」子页的开关此前读不到（同坐标去重并掉），修复已合入 `main`，11-04 已在该机复测通过（[#531](https://github.com/rddmwmddr/android-ad-cleaner/issues/531)）；[#530](https://github.com/rddmwmddr/android-ad-cleaner/issues/530)。手动清单见[清单差异](docs/清单/vivo-OriginOS.md)。
- **vivo V2303A**：系统 OriginOS 7 / Android 17（CP2A.260605.016）；2026-11-04 社区实测，七段安全模式自检关闭 25 项、逐段回读确认；维护方未在本机复跑，整轮用时未测（[#579](https://github.com/rddmwmddr/android-ad-cleaner/issues/579)）。手动清单见[清单差异](docs/清单/vivo-OriginOS.md)。
- **一加 Ace 2（PHK110）· ColorOS 16.0.5**：2026-10-25 路径实测、整段重跑约 85 秒。营销通知 11 个关闭，1 个受限。
- **一加 Ace 2（PHK110）· ColorOS 15.0.0.601**：2026-10-29 手动路径实测；自动脚本尚未整段真机验证。手动清单部分路径；营销通知渠道按独立流程处理。
- **realme GT Neo5 SE（RMX3700）**：2026-11-02 六段真机实测通过（广告跟踪、软件商店、浏览器、下拉搜索、小布建议、应用建议）；下拉搜索重跑 83 秒、幂等。
- **realme 真我 GT5 Pro（RMX3888）**：按报告者 2026-11-11 的实测路径写成（[#1083](https://github.com/rddmwmddr/android-ad-cleaner/issues/1083)），未在真机复跑，待复测。主题、视频、游戏中心三段在本机没有可做的入口，脚本显式跳过并说明原因；与同族脚本的差异见[清单](docs/清单/OPPO-ColorOS.md)。营销通知是报告者按清单 §5 人工核对后跑的：14 条候选剔到 12 条，`chan-off` 全关、复查「仍开着 0 个」。
- **三星 Galaxy Note10+ 5G（SM-N9760）**：系统 One UI 4 / Android 12（SP1A.210812.016.N9760ZCU6HZE1）；只有「广告」一段；2026-11-05 社区实测，保护开关「关 → 开」并回读确认，单段执行 5 秒；维护方未在该机复跑。营销通知 13 条营销渠道人工关 10 条，3 条因应用级禁用等效关闭；`chan-off` 13 条全跳过（渠道在「通知类别」子页，首层无渠道行）。手动清单见[清单](docs/清单/三星-OneUI.md)。

---

## 一次完整的流程

<p align="center"><img src="images/flow.png" width="340" alt="处理流程"></p>

命令写法：

```bash
pip3 install -r requirements.txt
python3 tool/run.py devices                 # 看序列号、型号、有没有机型脚本
python3 tool/run.py -s <序列号> check        # 只读检查
python3 tool/run.py -s <序列号> backup       # 改动前快照
python3 tool/run.py -s <序列号> suspend <包…> # 可选：机主同意后挂起广告组件，要排在跑机型脚本之前
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
AGENTS.md            给用户侧 AI 智能体的操作手册（产品契约）
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
  手机版教程/         手机版（APK）的分步教程：截图 + 视频
prompts/             复制给聊天 AI 的提示词
tool/
  run.py             总入口
  fast.py            读屏、找入口、拨开关的引擎（uiautomator2）
  chan_fast.py       营销通知渠道
  explore.py         新机型探路（实验）
gui/                 桌面客户端（pywebview 界面 + PyInstaller 打包）
android/             手机版 APK（引擎与桌面版同一份，界面是 Compose）
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
