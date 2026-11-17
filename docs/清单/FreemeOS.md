# 卓易 FreemeOS 手动清单

以下读数与入口在酷派 CPDAY3（`ro.product.brand=coolpad`、`ro.product.manufacturer=CP`、型号 `CPDAY3`、卓易 FreemeOS 11.0）上于 2026-11-15 由报告者逐项核对，仓库还没有这台机的机型脚本。`adapt survey` 对这个家族仍会拒绝：家族词库只从机型脚本现算，现在还是空的；探路走 `adapt explore -s <序列号>`，不给包名也会挑出卓易系的 App。

与 #455（FreemeLite `XY20286501`，`ro.product.brand=5G`）同属卓易系：两台 `ro.build.freeme.label` 一致，`coolpad` 与 `5g` 在 `entries.FAMILY` 里都归 `freeme`。

## 机型读数

| 属性 | 值 |
|---|---|
| `ro.product.brand` / `ro.product.manufacturer` | `coolpad` / `CP` |
| `ro.product.model` | `CPDAY3` |
| `ro.build.display.id` | `coolpad_CPDAY3_V1.0` |
| `ro.build.freeme.label` / `ro.build.freeme.version` | `FreemeOS` / `11.0` |
| `ro.build.freeme.customer.branch` | `Droi_6560M` |
| `ro.build.version.release` / `sdk` | `13` / `30` |

版本对齐用 `display.id` 与 `ro.build.freeme.*`：本机 `release=13`、`sdk=30`，fingerprint 底包是 `RP1A.200720.011`（Android 11），三者不一致，`sdk` 对不上任何一方。

## 入口

| 位置 | 广告开关 | 本机结果 |
|---|---|---|
| `am start -n com.freeme.secureguard/com.zhuoyi.security.lite.SC_SettingActivity` | 安全管家设置页；其中的「关于我们」进 `com.zhuoyi.security.lite.agreement.AboutMeActivity`，「个性化广告」在这一页 | 直达可用。裸启动 `com.freeme.secureguard` 会被系统转到这个设置页，按包名判「没进入前台」 |
| 安全管家 → 设置 → 关于我们 → 个性化广告 | 「个性化广告」（核对时是开） | **UI 不可达**：点开关本体、点行标题都不改状态，也不弹确认框；设置库里没有对应明文键。按厂商远端控制处理 |

「关于我们」是按 `AboutMeActivity` 读出的页面名，界面上的逐字标题没有记录下来。探路时启动的是 `com.freeme.secureguardmanager`，设置页却在 `com.freeme.secureguard` 里：写脚本时按后者写。

实测直达用的是裸 `am start -n`；引擎的直达档会带清栈参数 `-f 0x10008000`，本机没试过带参写法。若届时判「没落在这一页」，照 #165 的先例改用裸启动（`Direct.keep_task`）。

## 通知渠道

`chan-scan` 在本机列出 `TencentAdNetCH1` / `ADroiUnion` 两条，但都挂在 `com.freeme.secureguard` 上（#455 那台挂在 `com.freeme.launcher`），且**系统锁定为灰色**：`dumpsys notification` 的渠道行带 `mImportanceLockedByOEM=true`、`mBlockableSystem=false`、`mFgServiceShown=false`，`chan-off` 拨 0 条。现有锁定判据（`chan_fast.scan()`）只看 `fixedImportance=true` 与 `mBlockableSystem=false`，`mImportanceLockedByOEM` 不参与判断；这个字段要不要另开一档，本次不动。

## 只作线索的厂商开关

报告者另用 `settings put` 关了四个厂商开关（`key_gopush_ads_switch_state`、`show_install_advertisement`、`freeme_service_app_recommendation`、`freeme_ue_plan`）并把 OAID 置全 0。这些不是界面路径，工具的三类动作（拨系统开关、关通知渠道、`pm suspend` 挂起包）都不覆盖，不进脚本。

## 覆盖范围

本文覆盖 `com.freeme.secureguard` 的设置页与上述两条锁定渠道。桌面推荐位、浏览器、卓易商店与主题的设置入口（探路时没找到或启动后离开前台）不在本次范围内；「个性化广告」是否真的 UI 不可达，等报告者按票上的复验请求再确认。
