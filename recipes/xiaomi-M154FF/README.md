# 小米 18 Pro Max（M154FF）/ 18 Fold（2608BPX34C）/ REDMI K90（2510DRK44C）

HyperOS OS4.0.24 / Android 17，2026-11-07 本机整轮复测。脚本 `BUILD` 是 `OS4.0`，`MODELS` 同时收
18 Pro Max（`M154FF`）、18 Fold（`2608BPX34C`）与 REDMI K90 基础款（`2510DRK44C`）：三台系统底包都是
`CP2A.260605.016`，差别在 App 版本——商店、浏览器、全局搜索、手机管家升级后入口变了，脚本每一步都
兼容新旧两种入口，找不到就跳过。18 Fold 的路径来自 Issue #2 的社区记录（2026-10-24），K90 来自
Issue #929 的社区记录（2026-11-10），**这两台都没有在本仓库验证**，维护方没有这两台机器。

```bash
python3 tool/run.py -s <序列号> backup
python3 tool/run.py -s <序列号> recipe
python3 tool/run.py -s <序列号> finish
```

可只跑某一段，例如 `recipe 浏览器`。开关是逐段点名的：先确认页面与目标开关都在，拨完回读，再比较
同页其他开关的状态。本脚本不挂起组件、不处理快应用和通知渠道、不关闭开发者模式。

## 验证范围

| 机器与版本 | 验过什么 |
|---|---|
| M154FF，HyperOS OS4.0.24 / Android 17 | 2026-11-07 九段整轮全过。手机上那一轮（#666 的手机包）150 秒、浏览器段失败；改直达后 97 秒、全部通过 |
| M154FF，同上 | 同一轮的分段用时见下表，电脑经无线 adb 跑，只跑到全局搜索段 |
| M154FF，同上 | 2026-10-22 按菜单路径录制，2026-10-25 九段重跑通过；2026-10-29 一次「USB 调试（安全设置）」没打开时九段全「没找到」（147 秒、关 0 个），打开后同一份脚本一次跑通，首轮关 18 项、紧接的复跑核对 22 项（Issue #191；这一轮在改直达之前） |
| 18 Fold，`CP2A.260605.016` | 只有 Issue #2 的社区路径记录，本次提速未验证 |
| REDMI K90（`2510DRK44C`），`CP2A.260605.016` / OS4.0.5.0.XPKCNXM | 只有 Issue #929 的社区记录（2026-11-10）：九段中八段跑通、关 16 项，主题段要先挂起 `com.miui.systemAdSolution` 再跑（补关 2 项，累计 18 项）；本仓库未复跑 |

2026-11-07 两轮的开关当时都已关过，验的是「到得了页面、读得对状态」；从开启状态关起的是
2026-10-29 那一轮（改直达之前）。

## 分段用时

2026-11-07 电脑经无线 adb，改前 / 改后（秒）：

| 段落 | 改前 | 改后 |
|---|---|---|
| 系统广告 | 77 | 6 |
| 下载管理 | 23 | 9 |
| 浏览器 | 87 | 43 |
| 应用商店 | 81 | 77 |

这一轮跑到全局搜索段时电脑侧的 adb 服务掉了（macOS 本地网络权限），没有跑完整轮；「九段全过」与
整轮 150 → 97 秒来自手机上那一轮。

## 未验证项

- 18 Fold 没有真机验证：共用这份脚本，`2608BPX34C` 的路径只有 Issue #2 的社区记录。
- REDMI K90（`2510DRK44C`）没有本仓库的真机验证：登记依据是 Issue #929 的社区实测，维护方没有这台机器。
- 「直达打不开时走老路」只有单测（`tests/test_direct_entries_667.py`）：真机上这几段都能直达，回退分支没有被触发过。
- 浏览器「基本模式」（拒绝协议后落到 basicmode 页）只有单测（`tests/test_browser_basic_mode_414.py`），假设直达会被转到这一页。
- 18 Fold 这类没有 `.BrowserSettingsActivity` 的版本，「主页设置 / 搜索设置 / 功能设置」三个子项会跳过，这条路同样只有单测。

## 脚本结构

九段，同名同序。下表「入口」写直达页，「回退」是打不开时走的老路。

| 段 | 入口 | 回退 |
|---|---|---|
| 系统广告 | `com.android.settings/.ad.AdServiceSettings`（首屏读「个性化广告推荐」） | 设置首页 → 隐私与安全 →（18 Fold 先切「安全」）→ 更多安全设置 → 广告服务 |
| 应用商店 | `com.xiaomi.market/.ui.MarketPreferenceActivity`（「通知设置」） | 拉起商店 → 我的 → 齿轮 |
| 手机管家 | `com.miui.securitycenter/com.miui.securityscan.ui.settings.SettingsActivity` | — |
| 下载管理 | `com.android.providers.downloads.ui/.activity.InfoFlowSettingActivity`（「资源推荐」） | 拉起下载管理 → 右上「更多」→ 设置 → 信息流设置 |
| 主题 | 拉起主题商店转到 `com.android.thememanager`（没装商店时直起管理包的代理标签页）→ 我的 → 齿轮 | — |
| 浏览器 | `com.android.browser/.preferences.activity.CustomizationPreferenceActivity`（「个性化内容推荐」），再试子页 `.BrowserSettingsActivity` | 拉起浏览器 → 工具栏齿轮或底部「我的」→ 齿轮；落在 basicmode 页则跳过本段 |
| 全局搜索 | `com.android.quicksearchbox/.preferences.SearchSettingsPreferenceActivity` → 首页展示模块 | — |
| 负一屏 | `com.miui.personalassistant/.settings.PASettingActivity` | — |
| 天气和日历 | 日历 `com.android.calendar/.settings.UserExperienceActionBarActivity`（「内容推广」）；天气拉起后 → 城市管理 → 右上「更多」→ 设置 | — |

系统广告不用 HyperOS 的设置搜索：搜索框用 `setText` 输入中文会卡住、一直打「%」。

改动的边界：商店关「隐私设置 → 个性化服务」，有「模式切换」时切到极简模式，通知设置里只关「新手帮助」
——「推送消息」是父开关，一并关掉会连点赞与评论消息一起没了；浏览器不改首页布局（默认 / 探索版 /
自定义主页），「宫格位推送」「猜你想搜」「小说」新版没有就跳过；负一屏保留搜索框与出行助手；
天气和日历只动「用户体验计划」那一页。

落点判据与试过但没用上的 Activity 记在 [docs/清单/小米-HyperOS.md](../../docs/清单/小米-HyperOS.md)。
