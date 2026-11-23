# vivo V2502A（Android 17）

页面树数据 `V2502A.toml`，`build = PD2502B_A_17.1.13.6`（真机 `ro.build.display.id` =
`PD2502B_A_17.1.13.6.W10`）。结构沿用同族 `V2547DA-android17.toml`，只换机型身份字段；所有库名
（`direct_page` / `global_search_entry` / `store_settings_direct` / `gear` / `off_unnamed` /
`browser_recommendations` / `i_manager_ads` / `weather_service` 等）都落在 `recipe_lib/vivo.py` +
`recipe_lib/shared.py`，**本机不需要例外 `.py`**。

```bash
python3 tool/run.py -s <序列号> backup
python3 tool/run.py -s <序列号> recipe
python3 tool/run.py -s <序列号> finish
```

## 验证范围

| 机器与版本 | 验过什么 |
|---|---|
| `PD2502B_A_17.1.13.6.W10`，**简体中文界面** | 2026-11-23 本机 `recipe --ref`：本轮新关 **8 个**开关——应用商店 个性化广告推荐；浏览器 下载管理页展示热门应用 / 下载管理页展示下载热榜 / 个性化内容 / 第三方应用来源个性化推荐 / 个性化广告推荐；i管家 应用个性化推荐 / 清理个性化推荐。系统广告、全局搜索、阅图锁屏、天气四段的目标开关本机**本来就已 [关]**，脚本核对 0 调整 |
| 同上（简体界面） | 2026-11-23 `adapt check recipes/vivo/V2502A/V2502A.toml` 安全模式自检：**7 段全部可达、未完成步骤 0 个**；因目标开关本已 [关]，回读确认关闭 0 项（= 无东西可关，不是失败）。仅商店「服务管理」页 6 项是只读标题、非标准 `Switch`，`off()` 核对 0 安全跳过（见下「实测差异」）；浏览器段冷启动后四个子页全部命中

## 本机与参考（V2547DA-android17）的实测差异

- **商店直达不通**：这版 `com.bbk.appstore/.ui.menu.AppstoreSettingsActivity` **未导出**，`am start` 抛
  `SecurityException: not exported from uid …`。脚本按约定不中断，回退「我的 → 齿轮」。
- **齿轮入口是有的**（参考脚本注释曾写「没有可读到的齿轮入口」，本机不成立）：它是右上角
  `Button text='' content-desc='设置'`（bounds ≈ `[1099,159][1199,259]`，屏宽 1260）。engine
  `screen.py` 在 `text` 为空时回退匹配 `content-desc`，所以简体下 `gear` 进得去设置页。
- **商店「服务管理」子页存在，但本机是「只读标题」形态**：齿轮进 `AppstoreSettingsActivity` → 关于
  (`AppStoreAboutActivity`) → 服务管理 (`com.bbk.appstore.manage.settings.about.FunctionManagerActivity`) 全链路可达。
  参考脚本点名的 6 项（签到有礼 / 顶部轮播图 / 顶部栏目 / 开屏 / 摇一摇 / 限时推广）**逐项在屏，但都是只读
  标题 TextView、没有标准 `Switch` 控件**，engine `off()` 读不到 → `adapt check` 报「核对 0 / 调整 0」并安全跳过
  （属 AGENTS §7「开关点不动」，**不是页面缺失、不是语言问题**）。差异：参考列表里的「悬浮窗」本机没有；
  保留项「我的服务」本机标题叫「我的页-我的服务」。广告/个性化在「关于 → 个性化推荐」子页，已能关掉。
  **商店版本 `V10.6.21.0`**（关于页读到），商店自更新后此形态可能变。

## 未覆盖 / 已知限制（不在本脚本内）

- **繁体界面全程 0 改动**：脚本判据是简体中文，繁体（本机曾为 `zh-HK`，非 `zh-TW`）下逐段「没找到」。
  切简体后立刻关成 8 个。这是引擎判据层的语言问题，见 Issue **#1526**，不是机型不适配。
- **快应用 `com.vivo.hybrid` 关不掉**：这台系统拒绝写入快应用服务开关（回读校验失败、保留原值），属
  AGENTS §6「vivo 快应用挂不起」，与本脚本无关。
- **负一屏（未脚本）**：`com.vivo.hiboard/.settings.AppletSettingActivity` adb 直达抛 `SecurityException`
  （未导出）。同族同样只能从桌面左滑进入，参考脚本 `V2547DA-android17.toml` 也没这段，本机不脚本。
  要人工做见 `docs/清单/vivo-OriginOS.md` §2。
- **商店消息提醒（本机不可达）**：`FunctionManagerActivity` 与设置主页都没有可点的「消息提醒/通知」
  类条目——`docs/清单` 里 V2324HA / V2309A 有的这条路径本机这版商店（V10.6.21.0）不暴露。

## 脚本结构

七段、同名同序：系统广告、全局搜索、阅图锁屏、应用商店、浏览器、i管家、天气。到达方式与保留项与同族
Android 17 变体一致（系统广告/全局搜索/阅图锁屏直达优先；商店直达不通走齿轮；浏览器走右上菜单；
i管家、天气直达）。保留项：全局搜索历史记录与应用建议、商店「我的服务」「空间清理」、天气气象预警/
异常天气/地震预警、浏览器选「极简首页」。

同族差异见 [docs/清单/vivo-OriginOS.md](../../../docs/清单/vivo-OriginOS.md)。
