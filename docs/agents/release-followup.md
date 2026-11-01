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

| Issue | 报告者 | 机型 / 系统 | 修复（进入的版本） | 要观察的输出 |
| ----- | ------ | ----------- | ------------------ | ------------ |
| #286 | @xicong | OPPO Find X8s / PKT110 / ColorOS 17.0.0.102 | #296 #297（0.2.9）、#347（0.3.0） | 母 issue：0.2.8 复测里除主题商店外各段已过、游戏中心已修；剩主题商店不再以 `-32002 Selector [text='我的']` 失败，等 0.3.0 复测 |
| #292 | @xicong | 同上 | #297（0.2.9） | 游戏中心已在 0.2.8 复测确认（「核对 1 项，调整 1 项」）；差广告跟踪段不再打印「✗ 没找到『隐私』」这句假失败，与 #286 一并确认后关闭 |
| #293 | @xicong | 同上 | #296（0.2.9） | 复用外部 adb server 后再关掉对方程序，报「手机和电脑的 adb 连接断开了」、后续段跳过，不再出现「本机没有安装 com.heytap.yoli」。0.2.8 复测没有触发这个场景，仍无真机证据 |
| #335 | @afive956 | OPPO Find X10 Pro Max / PMX110 / ColorOS 17 | #359（0.3.0） | `quickapp off` 后负一屏快递卡片能打开详情页；输出里 `com.nearme.instant.platform` 标「保留」，并提示 `hap://` 广告仍可能拉起快应用 |
| #337 | @KujouShiori | vivo V1986A / Funtouch 13.0 / Android 12 | #360（0.3.0） | `chan-scan` 列出 `VPushChannel_0` 的「运营消息」，`VPushChannel_1`（系统消息）/ `VPushChannel_2`（即时消息）仍不出现 |
| #357 | 机主（证据来自 #348） | 华为 M30 / HarmonyOS | #358（0.3.0） | USB 提示按带调试接口的设备取品牌，不再把别的 USB 外设说成「华硕手机」；由 #348 的报告者在下一版插线确认 |
| #367 | 机主 | POCO（`ro.product.brand=POCO`） | #369（0.3.0） | `run.py check` 的广告包一行出现 `com.miui.systemAdSolution`；`status-json` 的 `ads` 同步 |

最新发布版仍是 v0.2.9（2026-10-30T09:58Z），只包含 #296 / #297。0.2.9 之后合入 `main` 的 #347、#358、#359、#360、#369 都还没进任何安装包，所以这些票现在不发复测请求——让报告者拿旧版验新代码只会再收一份重复上报。下一版发布后一次性 @ 各自报告者。

0.3.0（2026-11-01T05:53Z）包含 #347、#358、#359、#360、#369。同日发复测请求：#286 @xicong（#292 / #293 一并确认）、#335 @afive956、#337 @KujouShiori、#348 @cyf3580（代 #357）；#367 是机主自己开的票，没有外部报告者可催；#397 按待真机反馈一节 @wowbbs 要数据。

#287 在 2026-10-31 用 0.2.9 复测失败后已离开本队列（摘掉 `waiting-for-verify`、改回 `needs-info`），它不在下面这张表的催复测范围里。

## 待真机反馈（不是 `waiting-for-verify`）

下面这张票缺的是真机数据，不是修复后的复测：代码还没动，票保持 `needs-info`，下次发版催复测时一并 `@` 对方即可，不算 `waiting-for-verify`。

| Issue | 谁 | 机型 / 系统 | 要什么 |
| ----- | -- | ----------- | ------ |
| #397 | @wowbbs | vivo X300 Ultra / V2547A / OriginOS 7 / Android 17 | V2547A 脚本的 `confirm2()` 注释已过时（引擎自 PR #239 起会读 Button 下级文字）。把广告跟踪段的 `confirm2()` 临时换成 `p.confirm()` 跑一次，或提供「温馨提示 → 取消 / 确认关闭」弹窗的 `uiautomator dump`。不依赖安装包，当前源码就能做 |

## 为什么不用 `ready-for-agent` 顶着

一个已修完、只等真机确认的 issue，长着和待实现 issue 一模一样的外观：代码不在发布版里，报告者还在遇到问题。`ready-for-agent` 会让下一个接手的智能体（或人）从头再实现一遍；`needs-info` 会让人以为缺的是诊断数据。两种误判在 2026-10-29 都发生过一次。
