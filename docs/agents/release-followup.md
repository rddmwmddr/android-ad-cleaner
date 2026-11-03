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

| Issue | 报告者 | 机型 / 系统 | 修复（进入的版本） | 要观察的输出 |
| ----- | ------ | ----------- | ------------------ | ------------ |
| #286 | @xicong | OPPO Find X8s / PKT110 / ColorOS 17.0.0.102 | #482、#519（未发布） | 主题商店与视频两段不再以「未找到入口」结束。主题商店 17.22 的「设置」读作「设置,有1条新通知」，脚本按文字包含或右上角图标都能进，落地页出现「服务管理 / 隐私」才算成功；游戏中心切「我的」会确认换了页，失败不再停在首页推荐流。失败时会打印停在哪一页 |
| #293 | @xicong | OPPO Find X8s / PKT110 / ColorOS 17.0.0.102 | #296（0.2.9） | 复用外部 adb server 后再关掉对方程序，报「手机和电脑的 adb 连接断开了」、后续段跳过，不再出现「本机没有安装 com.heytap.yoli」。0.2.8 复测没有触发这个场景，仍无真机证据 |
| #335 | @afive956 | OPPO Find X10 Pro Max / PMX110 / ColorOS 17 | #359（0.3.0） | `quickapp off` 后负一屏快递卡片能打开详情页；输出里 `com.nearme.instant.platform` 标「保留」，并提示 `hap://` 广告仍可能拉起快应用 |
| #337 | @KujouShiori | vivo V1986A / Funtouch 13.0 / Android 12 | #360（0.3.0） | `chan-scan` 列出 `VPushChannel_0` 的「运营消息」，`VPushChannel_1`（系统消息）/ `VPushChannel_2`（即时消息）仍不出现 |
| #357 | 机主（证据来自 #348） | 华为 M30 / HarmonyOS | #358（0.3.0） | USB 提示按带调试接口的设备取品牌，不再把别的 USB 外设说成「华硕手机」；由 #348 的报告者在下一版插线确认 |
| #367 | 机主 | POCO（`ro.product.brand=POCO`） | #369（0.3.0） | `run.py check` 的广告包一行出现 `com.miui.systemAdSolution`；`status-json` 的 `ads` 同步 |
| #278 | @axibaqimingzhenna | OPPO Find N5 / PKH110 / ColorOS 17.0.0.103 | #277（0.2.9） | 不带 `--ref` 直接跑 `recipe`，七段逐段跑完、不再整段「✗ 没找到」，广告跟踪报出真实核对项数。负一屏仍提示需机主手动，属已知限制 |
| #280 | @afive956 | OPPO Find X10 Pro Max / PMX110 / ColorOS 17.0.0.116 | #279（0.2.9） | 不带 `--ref` 直接跑 `recipe`，九段逐段跑完、不再整段「✗ 没找到」。摇一摇广告与软件商店「推荐卡片」点了没反应、下拉搜索需手动，都是已记录的系统限制，不算回归 |

2026-11-02：#278 / #280 从 `ready-for-human` 改为 `waiting-for-verify`，同日按 0.3.0 发了复测请求。这两张票的机型脚本随 0.2.9 进包，之前挂着 `ready-for-human` 是因为 PR #277 / #279 合并时没有回归队列。

0.3.0（2026-11-01T05:53Z）包含 #347、#358、#359、#360、#369。同日发复测请求：#286 @xicong（#292 / #293 一并确认）、#335 @afive956、#337 @KujouShiori、#348 @cyf3580（代 #357）；#367 是机主自己开的票，没有外部报告者可催；#397 按待真机反馈一节 @wowbbs 要数据。

#287 在 2026-10-31 用 0.2.9 复测失败后已离开本队列（摘掉 `waiting-for-verify`、改回 `needs-info`），它不在下面这张表的催复测范围里。

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
