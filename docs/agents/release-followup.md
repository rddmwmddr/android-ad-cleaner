# 发版后复测清单

Issues labelled `waiting-for-verify` have a fix on `main` that the reporter has not confirmed on hardware yet. Nothing closes them except the reporter's own reply after installing the release that contains the fix. This file is the queue of what each release owes.

发版本身——跑验证、打 tag、写 Release 正文、同步 README / `index.html` / `latest.json` / 网盘——见 [release.md](release.md)。这份文件只管发版**之后**。

## 每次发版后照做

1. 取出当前队列：

   ```bash
   gh issue list --label waiting-for-verify --state open
   ```

2. 逐条确认修复是否进了本次构建。版本号对不上就跳过 —— 让报告者跑旧版去验新代码，只会再收一份重复上报。

3. 在每条 issue 上留一条复测请求，`@` 报告者，写清装了哪个版本、要观察哪一句输出。模板见下。

4. 报告者确认后关闭 issue 并摘掉 `waiting-for-verify`；报告失败就摘标、改回 `needs-triage`，把日志当新证据重新归类。

## 复测请求模板

```text
0.2.x 已经发布，包含这次的修复（PR #NNN）。如果你还方便，请装新版再跑一次，把下面这一段的输出贴上来：

- 期望看到：<具体那一行的正确形态>
- 之前看到：<原来那句错误输出>

不方便复测也没关系，这条先留着，等有同机型的反馈再一起确认。
```

要点：说清装哪个版本、看哪一行、正确长什么样。别问「好了吗」—— 报告者没法据此判断，只会再发一张截图。

## 当前队列

0.3.1（2026-11-03T02:36Z）发布后同日发复测请求：#165、#220、#228、#286、#333、#407、#414、#415、#474、#498（各 @ 报告者）。机主或维护者自己开的票（#311 #378 #403 #420 #422 #426 #428 #452 #456 #460 #480 #486 #500 #510）没有外部报告者可催。

2026-11-03：#228 由 @WET1AND 用 `AndroidAdCleaner-0.3.1-windows-portable` 按原场景复测通过（`startup: webview2=installed motw=yes`、MOTW 提示文案正确、解除标记后 smoke 正常），当日摘掉 `waiting-for-verify` 并关闭；原始报告者 @AbyssOvO 未回复，这段确认来自同症状的独立报告者。

2026-11-03：#523 由 @gehongyan 在魅族 21 Pro（Flyme 12.6.0.0A）上拉取 `main` 最新代码重跑，浏览器与应用商店两段都能自己走完，原两条失败不再出现；报告者自行关闭，同日摘掉 `waiting-for-verify`。这次验证跑的是 `main` 源码而非发布版（修复随下一版发布），该票当时未登记进下表。

2026-11-04：把漏登记的外部票补进下表（#209、#218、#317、#330、#331、#336、#413、#469、#483）。同一轮对账还改了三张票的状态：#531 由报告者 @cyjx007 在 `main` 真机确认，关闭并摘标；#193 的复测贴出主题段仍失败的证据与根因，摘标转 `needs-triage`；#336 修好随 0.3.0 进包却从没发过复测请求，补发一条。

| Issue | 报告者 | 机型 / 系统 | 修复（进入的版本） | 要观察的输出 |
| ----- | ------ | ----------- | ------------------ | ------------ |
| #286 | @xicong | OPPO Find X8s / PKT110 / ColorOS 17.0.0.102 | #482、#519（未发布） | 主题商店与视频两段不再以「未找到入口」结束。主题商店 17.22 的「设置」读作「设置,有1条新通知」，脚本按文字包含或右上角图标都能进，落地页出现「服务管理 / 隐私」才算成功；游戏中心切「我的」会确认换了页，失败不再停在首页推荐流。失败时会打印停在哪一页 |
| #293 | @xicong | OPPO Find X8s / PKT110 / ColorOS 17.0.0.102 | #296（0.2.9） | 复用外部 adb server 后再关掉对方程序，报「手机和电脑的 adb 连接断开了」、后续段跳过，不再出现「本机没有安装 com.heytap.yoli」。0.2.8 复测没有触发这个场景，仍无真机证据 |
| #335 | @afive956 | OPPO Find X10 Pro Max / PMX110 / ColorOS 17 | #359（0.3.0） | `quickapp off` 后负一屏快递卡片能打开详情页；输出里 `com.nearme.instant.platform` 标「保留」，并提示 `hap://` 广告仍可能拉起快应用 |
| #337 | @KujouShiori | vivo V1986A / Funtouch 13.0 / Android 12 | #360（0.3.0） | `chan-scan` 列出 `VPushChannel_0` 的「运营消息」，`VPushChannel_1`（系统消息）/ `VPushChannel_2`（即时消息）仍不出现 |
| #357 | 机主（证据来自 #348） | 华为 M30 / HarmonyOS | #358（0.3.0） | USB 提示按带调试接口的设备取品牌，不再把别的 USB 外设说成「华硕手机」；由 #348 的报告者在下一版插线确认 |
| #367 | 机主 | POCO（`ro.product.brand=POCO`） | #369（0.3.0） | `run.py check` 的广告包一行出现 `com.miui.systemAdSolution`；`status-json` 的 `ads` 同步 |
| #278 | @axibaqimingzhenna | OPPO Find N5 / PKH110 / ColorOS 17.0.0.103 | #277（0.2.9） | 不带 `--ref` 直接跑 `recipe`，七段逐段跑完、不再整段「✗ 没找到」，广告跟踪报出真实核对项数。负一屏仍提示需机主手动，属已知限制 |
| #238 | @dgphust | HONOR PTP-AN20 / MagicOS 10.0.0.175 / Android 16 | #548（未发布） | 参考脚本主题段不再以「✗ 没找到『我的』/『设置』」结束，出现「主题·通知」「主题·个性化服务」两行核对；音乐段进到「音乐·消息和隐私」。市场 / 桌面文件夹段不在本次修复内（等 #547）。报告者跑 `main` 源码，不必等发版，2026-11-04 已发复测请求 |
| #329 | @your-boy | Xiaomi 17 Max / 2605EPN8EC / HyperOS OS4.0.3.0.XAFCNXM（Android 17） | #331 / PR #395（0.3.0） | 浏览器段四个设置入口逐个命中，不再连报「没找到隐私和安全 / 主页设置 / 搜索设置 / 功能设置」。系统广告段停在「更多安全设置」不受这次修复影响，结果一并贴 |
| #233 | @kitsonchung | 检测不到手机（电脑上的联想 USB 外设 / 华为 puraX） | #357 / PR #358（0.3.0） | 连接页的 USB 提示按带调试接口的实际设备说品牌并给华为排查建议，不再出现「电脑识别到联想手机，但没有调试接口」。puraX 那半若 `adb 设备` 仍是 0 台，按提示换线、USB 用途切「传输文件」、退出其他手机助手 |
| #240 | @KongdaV5 | Xiaomi 14 / 23127PN0CC / HyperOS OS3.0.303.0.WNCCNXM（Android 16） | #319（0.3.1） | `check` 的「机型脚本」一行从 `xiaomi-M154FF`（OS4.0）改为同族的 `redmi-23049RAD8C`（OS3.0）、版本判定「相同」；系统广告 / 主题 / 浏览器 / 天气和日历四段不再整段跳过。仍整段跳过则说明要按 OS3.0 另录一份，不是借哪份脚本的问题 |
| #209 | @Wqyy2020 | REDMI K90 Pro Max / 25102RKBEC / OS 4.0.5.0（Android 17） | 专用脚本 `xiaomi-25102RKBEC`（v0.2.6 起，无需改码） | 不带 `--ref` 重跑：`check` 的「机型脚本」一行写 `recipes/xiaomi-25102RKBEC/recipe.py` 且版本一致，六段不再整段「✗ 没找到」 |
| #218 | @Porridge10010 | Redmi Note 12 Turbo / 23049RAD8C / OS3.0.5.0.VMRCNXM（Android 15） | 专用脚本 `redmi-23049RAD8C`（v0.2.6 起，无需改码） | `check` 写 `recipes/redmi-23049RAD8C/recipe.py`；日志里的 `adb.exe: device '<序列号>' not found` 是连接断开，跑前退出手机助手类软件 |
| #317 | @tasuma-qwq | Xiaomi 14 Pro / 23116PN5BC / OS3.0.308.0.WNBCNXM（Android 16） | PR #406（0.3.0） | `check` 写本型号，不再出现「本型号没有；同品牌参考 `xiaomi-M154FF`」，也不再提示安全模式；`recipe` 不用手工指定脚本路径 |
| #330 | @lanzhihong6 | HUAWEI ALN-AL00 / HarmonyOS 4.2.0.223（Android 12） | PR #520（未发布） | 检出清单外变化并点回后，出现「已点回并复核通过」，或点名差异渠道的「没能完全恢复」；跑完用 `dumpsys package <包名>` 查 `POST_NOTIFICATIONS` 仍是原模式 |
| #331 | @huangxy777 | REDMI K80 Ultra / redmi-25060RK16C（Android 17） | PR #395（0.3.0） | 浏览器段五个入口逐个命中；仍失败时日志带「停在 …」点名卡在哪一页，不再只说「没找到」 |
| #336 | @KujouShiori | vivo V1986A / Funtouch OS 13.0（Android 12） | PR #387（0.3.0） | `chan-off` 的 11 个营销渠道不再全部「未确认」跳过；专用脚本 `recipes/vivo-V1986A` 自 v0.2.9 起在包里，`check` 应显示它 |
| #413 | @Crispy-Pancakezzzz | iQOO Z11 Turbo / V2536A / OriginOS 6（Android 16） | PR #466 / #473（0.3.1） | 浏览器段点 ✕ 后若被带到别的 App，日志出现 `· 点了 ✕ 后跳到 <包名>，疑似推广位，已退回（<控件>）` 且落回原页；商店「关于」页与清单文末「V2536A 的差异」一致 |
| #469 | @FROKING | Xiaomi 14 Ultra / 24031PN0DC / OS3.0.308.0.WNACNXM（Android 16） | #319（0.3.1） | `check` 的「机型脚本」一行从 `xiaomi-M154FF`（OS4.0）改为同族的 `xiaomi-2304FPN6DC`（OS3.0.308）、版本判定「相同」 |
| #483 | @lvkowk0330-dev | OnePlus 13 / PJZ110 / PJZ110_17.0.0.103(CN01)（Android 17） | #319 / #165（0.3.1） | `check` 从 `oppo-PLP120`（ColorOS 16.0.9）改为 `oppo-PMX110`（ColorOS 17）；`recipe --ref` 九段逐段贴「命中 / 跳过」 |
| #280 | @WeilianC | OPPO Find X10 Pro Max / PMX110 / ColorOS 17.0.0.116 | PR #563（未发布） | 不带 `--ref` 跑 `recipe`：下拉搜索走 `gs://search/setting` 后逐组回读（搜索范围 / 首页卡片管理 / 功能管理 / 消息管理 / 隐私），负一屏轮播点到「不显示轮播推荐」并回读，游戏中心先跳首进引导再找齿轮。浏览器「摇一摇广告」与商店「推荐卡片」点了没反应仍是系统限制，跳过即可 |

2026-11-04：`/triage` 复核 `needs-info` 队列，把四张「已修待复测」却挂在 `needs-info` 的票改回本队列 —— #329、#233、#240（上表新增），#348（已在 #357 行按「证据来自 #348」登记，不重复）。四张票在 `needs-info` 期间都没有新增报告者回复。

2026-11-02：#278 / #280 从 `ready-for-human` 改为 `waiting-for-verify`，同日按 0.3.0 发了复测请求。这两张票的机型脚本随 0.2.9 进包，之前挂着 `ready-for-human` 是因为 PR #277 / #279 合并时没有回归队列。

0.3.0（2026-11-01T05:53Z）包含 #347、#358、#359、#360、#369。同日发复测请求：#286 @xicong（#292 / #293 一并确认）、#335 @afive956、#337 @KujouShiori、#348 @cyf3580（代 #357）；#367 是机主自己开的票，没有外部报告者可催；#397 按待真机反馈一节 @wowbbs 要数据。

#287 在 2026-10-31 用 0.2.9 复测失败后已离开本队列（摘掉 `waiting-for-verify`、改回 `needs-info`），它不在下面这张表的催复测范围里。

#280 在 2026-11-04 离开本队列（摘掉 `waiting-for-verify`、改回 `ready-for-agent`）：同机型报告者复跑后证明「下拉搜索需手动」是脚本漏抄 `gs://search/setting` 这个已验证入口，轮播单选点反是脚本自己的判定错误，两条都不是系统限制。修复已进 PR #563（未发布），随发版重新入队催复测（上表末行）；浏览器「摇一摇广告」与商店「推荐卡片」仍按系统不响应点击处理。

### 2026-11-01 从 `needs-info` 归队

这一批的末条回复当时写的是「0.2.7 已有对应修复，请重跑」，语义是已修等复测，却一直挂在 `needs-info`，既不在本清单里，也没法被「下一个 agent 别重复实现」这条规则保护到。改回 `waiting-for-verify` 时已各自催过一次（0.2.7，均无回复），本表只登记，不要求每版重发。

| Issue | 报告者 | 机型 / 系统 | 修复（进入的版本） | 要观察的输出 |
| ----- | ------ | ----------- | ------------------ | ------------ |
| #168 | @fenghuo6183 | 双开 / 分身空间 | 分身空间通知回读（0.2.7） | 分身里的营销渠道也能关掉并回读确认 |
| #171 | @327236495g-gif | vivo V2506A | vivo 渠道页识别（0.2.4） | 各段不再整段失败 |
| #172 | @dov5ovo-alt | 三星 SM-F9710 / Android 17 | 三星渠道页眉判定与只读机主空间（0.2.4） | 关闭营销通知不再以退出码 1 结束 |
| #173 | @city0928 | OnePlus 8T / ColorOS 14 | ColorOS「通知管理」独立页识别（0.2.4） | 渠道开关能被认出并关掉 |
| #175 | @AlanGreens | realme RMX8899 / ColorOS 16 | 同上 | 同上 |
| #178 | @hhgvcc | vivo | 总页 / 渠道页区分与总开关回读（0.2.4） | 浏览器、应用商店、阅读锁屏三段可关 |
| #184 | @cool-chill | Xiaomi 14 Pro / 23116PN5BC | 「未确认」重试一轮（0.2.7） | 失败项归零或只剩明确报错的行 |
| #182 | @niajiege | 一加 12 / JD110 / ColorOS 16（Android 16） | ColorOS「通知管理」独立页识别（0.2.4） | 营销通知段不再整段「未确认」，不再以退出码 1 结束 |
| #201 | @jiangfrank-1987 | 三星 SM-S9280 / Android 16 | 三星渠道页眉判定（0.2.4） | 营销通知结果里「仍开着」明显减少 |
| #241 | @rhzhang9 | 华为 NAM-AL00 / HarmonyOS 4.2 | 华为 `own_row()` 渠道识别（0.2.7） | `chan-off` 不再对 22 项全部报「未确认」 |
| #246 | @zhangswings | vivo V2452A / Android 16 | `confirm()` 读 content-desc 按钮文字（PR #249） | 阅图锁屏两个开关回读为关闭 |
| #254 | @GukashaRe | vivo V2528A / OriginOS 6 | 读屏会话失败诊断与一次重试（0.2.6） | 卡在「连接手机读屏服务」时有可读原因，不静默 |
| #273 | @xinzangbing | 未检测 | adb 下载源与 SHA-256 校验（0.2.7） | 能自动下到 adb，或给出明确失败原因 |
| #170 | @Tian621-cx | OPPO Find 系列 | ColorOS「通知管理」独立页识别（0.2.4） | 营销渠道可关 |
| #179 | @jklowt2 | iQOO 15 | adb 断线重试与列出其他 adb（0.2.4） | 中途断线后不再整轮失败 |
| #258 | @lcbd7poa | Hisense HLTE217T / Android 8 | dumpsys 段名 `per-package config:`（0.2.7） | 渠道扫描能列出该机的营销渠道 |

#181 不在此列：那句「已有对应修复」说的是检测页**提示文案**（0.2.4 起说明为什么点不动），报告者遇到的小米「USB 调试（安全设置）」被拒属手机侧设置，不是代码缺陷，仍留 `needs-info`。

#182 是 2026-11-02 复核时补登的：末条与上表同批（0.2.7 催过一次、无回复），2026-11-01 复查时漏掉了，现按同一判据归队。

## 待真机反馈（不是 `waiting-for-verify`）

下面这张票缺的是真机数据，不是修复后的复测：代码还没动，票保持 `needs-info`，下次发版催复测时一并 `@` 对方即可，不算 `waiting-for-verify`。

| Issue | 谁 | 机型 / 系统 | 要什么 |
| ----- | -- | ----------- | ------ |
| #397 | @wowbbs | vivo X300 Ultra / V2547A / OriginOS 7 / Android 17 | V2547A 脚本的 `confirm2()` 注释已过时（引擎自 PR #239 起会读 Button 下级文字）。把广告跟踪段的 `confirm2()` 临时换成 `p.confirm()` 跑一次，或提供「温馨提示 → 取消 / 确认关闭」弹窗的 `uiautomator dump`。不依赖安装包，当前源码就能做 |

## 为什么不用 `ready-for-agent` 顶着

一个已修完、只等真机确认的 issue，长着和待实现 issue 一模一样的外观：代码不在发布版里，报告者还在遇到问题。`ready-for-agent` 会让下一个接手的智能体（或人）从头再实现一遍；`needs-info` 会让人以为缺的是诊断数据。两种误判在 2026-10-29 都发生过一次。
