# vivo / OriginOS 手动清单

路径实测机型：

- vivo X300 Ultra（V2547DA，OriginOS 6，Android 16），2026-10-22。
- vivo X300 Ultra（V2547A，OriginOS 7，Android 17），2026-10-25。
- vivo X Fold6（V2545A，OriginOS 6 Fold，Android 16），2026-10-26。

iQOO 结构相近。当前源码有 `recipes/vivo-V2547DA/`、`recipes/vivo-V2547A/`、`recipes/vivo-V2545A/` 三份机型脚本，均已真机整段跑通验证（V2547DA 124 秒，V2547A 126 秒，V2545A 121 秒）。三份脚本对应不同机型与系统版本，入口差异见下文「OriginOS 7（Android 17）的不同之处」和「X Fold6 的差异」；版本对不上时引擎会走安全模式。发布与验证范围见[归档记录](../归档/CHANGELOG-0.3.0及更早.md)。
符号：🔴 关掉　🟢 保留　⚠️ 注意

---

## 1. 系统：广告与隐私

**路径**：设置 → 安全 → 更多安全设置 → 广告与隐私

- 🔴 个性化广告、个性化推荐、智能推荐服务

## 2. 负一屏

**路径**：桌面从左边缘向右滑 → 右上齿轮 → 更多设置 → 个性化推荐

- 🔴 服务推荐、资讯推荐
- 🔴 内容精选、热点资讯
- 🟢 小V建议（航班、快递提醒）
- ⚠️ 便捷生活 → 推荐服务不要关：那 10 个图标（扫码、手电筒、计算器等）都靠它补位，关了整块变空。

## 3. 全局搜索

**路径**：设置 → 系统管理与升级 → 全局搜索

- 🔴 首页展示内容 → 搜索框推荐词、推荐卡片
- 🔴 推荐热搜榜单 → 热门搜索
- 🔴 个性化内容 → 广告个性化
- 🟢 历史记录、应用建议、搜索结果个性化

## 4. 应用商店

**路径**：应用商店 → 我的 → 设置

- 🔴 关于 → 个性化推荐
- 🔴 服务管理 → 签到有礼、顶部轮播图、顶部栏目、开屏、摇一摇、悬浮窗、限时推广
- 🟢 我的服务、空间清理
- ⚠️ 开屏引导页「开启消息推送接收活动」取消勾选。

## 5. 浏览器

**路径**：浏览器 → 我的 → 齿轮

- 🔴 首页设置 → 极简首页；首页上滑展示资讯
- 🔴 隐私权限设置 → 个性化内容、第三方应用来源个性化推荐
- 🔴 网页浏览设置 → 网页下载相关推荐
- 🔴 更多设置 → WiFi 连接跳转新闻资讯
- ⚠️ 浏览器页面常跳到资讯、小说、领金币弹窗，一步一看。

## 6. 阅图锁屏

**路径**：设置 → 桌面、锁屏与壁纸 → 锁屏设置 → 阅图锁屏

- 🔴 阅图锁屏（关「锁屏横滑进入阅图」时总开关跟着关）
- 🟢 锁屏壁纸不变

## 7. i 管家

**路径**：i 管家 → 设置 → 关于 → 个性化设置

- 🔴 应用个性化推荐

## 8. 天气

**路径**：天气 → 设置 → 天气服务

- 🔴 天气相关热点资讯通知
- 🟢 气象预警、异常天气、地震预警

## 9. 营销通知

vivo 推送分类的渠道：`VPushChannel_0`（运营消息）、`VPushChannel_4`（精彩消息）、`VPushChannel_6`（推荐消息）。

- 🔴 支付宝运营、精彩；抖音运营、推荐；云服务推送；使用技巧智能推送建议；Play 特惠；Edge 热门资讯、突发新闻
- ⚠️ OriginOS 7 社区实测（[PR #20](https://github.com/rddmwmddr/android-ad-cleaner/pull/20)）：`com.vivo.systemuiplugin` 应用总页的「允许通知」是应用级总开关，关闭会连订单、聊天通知一起关。源码在总页不点开关，做法见下文。
- ⚠️ 渠道页由 `com.vivo.systemuiplugin` 处理，不要强行停止它。

V2547A 上的实测数据（2026-10-25，改的就是页面顶部那个「允许通知」）：

| 操作 | dumpsys 里 AppSettings 的 importance | 该渠道自己的 mImportance |
|---|---|---|
| 点掉「允许通知」 | `DEFAULT` → `NONE`（整个 App 的通知全关） | `2`，一动不动 |
| 再点回来 | `NONE` → `DEFAULT` | `2` |

这一页的顶栏是 App 名时，「允许通知」管整个 App。客户端和 `chan-off` 在这一页不点开关：从这一页点进渠道行，顶栏变成渠道名、且不同于 App 名时才操作（X300 Ultra / OriginOS 6 真机通过）。认不出渠道页就跳过这一项，不用关掉整个 App 的通知代替，订单、聊天提醒都保留。

另外 dumpsys 与手机页面会不一致：vivo 把渠道开关存在自家通知服务里，`dumpsys notification`
的 `mImportance` 不跟着变，所以别拿 dumpsys 判断 vivo 上到底关没关，以手机页面为准。

## 10. 广告包和快应用

这台没有挂起任何包，App 内开关够用。

- ⚠️ 快应用 `com.vivo.hybrid`：X300 Ultra（V2547A，Android 17）上系统拒绝挂起（[Issue #7](https://github.com/rddmwmddr/android-ad-cleaner/issues/7)）。根据 [PR #20](https://github.com/rddmwmddr/android-ad-cleaner/pull/20) 的真机证据，当前源码在能读到 `switch_quick_app_service` 时，通过系统服务开关关闭并验证，先备份原值；`quickapp on` 按本设备备份还原，找不到备份不会直接写成开启。这版实现在 V2547A 上已整段跑通：`quickapp off` 写入 `{"original": "1"}` 并把开关置 0，`quickapp on` 还原成 1 后自动删除记录文件。
- 🟢 智慧生活 `com.vivo.vhome` 属于智能家居功能，即使注册了 `hap://` 入口也不作为快应用广告组件处理。

原始实测（V2547A，2026-10-25）：`pm suspend`、`pm disable-user`、`pm uninstall --user 0`
三条路都要 root，全部抛 `SecurityException`，所以挂起这条路在 vivo 上不通：

```text
java.lang.SecurityException: Cannot suspend com.vivo.hybrid, no root permission
java.lang.SecurityException: Cannot disable com.vivo.hybrid no root permission
Failure [only root can delete system app for a particular user]
```

真正生效的是 secure 里的总开关 `switch_quick_app_service`（`quickapp off` 走的就是它）。
开关由 `1` 改成 `0` 之后逐入口用 `am start -W` 复核（`-W` 会直接回报实际启动的 Activity，
比事后看前台 Activity 可靠——上一版就是事后看，读到了残留记录，把第三行写错了）：

| 入口 | 结果 |
|---|---|
| `hap://` 链接（`DispatcherActivity`） | `Activity: com.vivo.hybrid/.main.activity.QuickAppSwitchOpenActivity` ——「快应用服务已关闭，是否重新开启服务？」，应用没起来 |
| 桌面「快应用中心」持久化快捷方式（`action.LAUNCH` + `EXTRA_APP=com.quickapp.center`） | 同上，落在同一个拦截页 |
| 直接启动 `com.vivo.hybrid/.main.DispatcherActivity` | `Status: ok` 但 Activity 随即自行结束，焦点退回桌面，没有进入任何快应用 |

- ⚠️ 关掉总开关后，桌面上那个「快应用中心」图标还在，点开会弹「快应用服务已关闭」，
  要点「确认开启」才会恢复。想去掉图标只能长按手动删。
- ⚠️ 如果靠快应用做签到、攒积分，别关这个开关：关掉后这些入口全部停在拦截页，签到会断。
- 还原：`quickapp on`。原值记在 `backups/<型号>-<时间>/quickapp-setting.json`。

---

## OriginOS 7（Android 17）的不同之处

实测机型 vivo X300 Ultra（V2547A，构建 `PD2547B_A_17.1.10.2.W10`），2026-10-25。
注意 `ro.vivo.os.name` 报的是 `Funtouch`，系统显示名要看 `ro.vivo.os.build.display.id`（OriginOS 7）。

| 项目 | OriginOS 6（V2547DA） | OriginOS 7（V2547A） |
|---|---|---|
| 广告与隐私 | 设置 → 安全 → 更多安全设置 → 广告与隐私 | 设置页搜「广告与隐私」，点结果直达 |
| 浏览器设置 | 我的 → 齿轮 | 首页右上「菜单」→ 设置（底部没有「我的」） |
| 浏览器隐私权限 | 个性化内容、第三方应用来源个性化推荐 | 多一项「个性化广告推荐」 |
| 天气设置 | 天气 → 设置 | 右上 `more_btn` → 设置（页内那个「更多」是展开按钮） |
| i 管家 | 设置 → 关于 → 个性化设置 | 同左，但首屏体检动画期间点「设置」会被吞，要重试 |
| 关开关的确认框 | — | 弹「温馨提示 → 取消 / 确认关闭」，按钮 `text` 是空的 |

几处实测到的 id 和 Activity（换机型或版本可能变）：

- 系统设置搜索框：`com.android.settings:id/vigour_search_edit`。首页那个「搜索设置项」本身是个 EditText，
  输入关键词后它自己也含这几个字，按文字查找会先命中它，点上去页面根本不跳、也不报错。
- 应用商店设置：`com.bbk.appstore/.ui.menu.AppstoreSettingsActivity`
- 浏览器菜单按钮：`com.vivo.browser:id/menu_btn`，设置页 `...setting.common.activity.SettingActivity`
- 负一屏设置面板：`com.vivo.hiboard/.settings.AppletSettingActivity`
- 阅图锁屏：`com.vivo.magazine/.ui.MagazineSettings`
- 天气：`com.vivo.weather:id/more_btn`，设置页 `com.vivo.weather/.WeatherSettings`

⚠️ 负一屏「热点资讯」页的 8 行开关，整行节点的标题全串成了页标题「热点资讯」；这一页还有 3 个单选钮
（悬浮 / 经典 / 卡片形态）也是 checkable，按「找 checkable 节点」的通用写法会把它当开关一起拨掉。
机型脚本 `recipes/vivo-V2547A/recipe.py` 里已按行还原标题、排除单选钮。

---

## vivo 的坑

| 现象 | 对策 |
|---|---|
| 负一屏、全局搜索、主题、i 管家的设置页拉不起来 | 只能从 App 或系统设置里点进去 |
| 列表行和开关各有一个状态 | 以开关本身为准 |

---

## V2324HA（iQOO，Android 16 / PD2324J_A_16.2.13.1.W10）差异

2026-10-27 实测，机型脚本 `recipes/vivo-V2324HA/`，七段全通、重跑约 2.5 分钟。和上面 X300 Ultra 的路径不一样的地方：

| 位置 | 本机实际路径 | 备注 |
|---|---|---|
| 应用商店·服务管理 | 商店 → 我的 → 设置 → **关于** → 下滑到「服务管理」 | 不在设置页第一层；页面是 `FunctionManagerActivity`，7 个营销开关 + 「管理页-我的服务」「空间清理」保留 |
| 应用商店·个性化推荐 | 设置 → 关于 → 「个性化推荐」 | `SettingUserRecommendActivity`；⚠️ 两个开关读屏里没有标题（只有「关闭，开关」），引擎会按保护类开关跳过，属安全策略，不绕过 |
| 应用商店·通知 | 设置 → 「应用商店提醒类型」 | 「消息通知设置」是标题行、点不动；提醒类型页 9 个开关 |
| 浏览器·设置入口 | 首页右上角 **菜单** → 设置 | 没有底部「我的」；`SettingActivity` |
| 浏览器·隐私 | 设置 → 隐私权限设置 | 是 `SettingActivity` 内的子页，4 个开关（含个性化广告推荐）|
| 全局搜索 | 设置 → 系统管理与升级 → 全局搜索 | 本版**没有「推荐热搜榜单」**入口，只剩首页展示内容、个性化内容 |
| 天气 | `am start -n com.vivo.weather/.WeatherSettings` | 天气首页只有「更多」，没有「设置」文字，齿轮找不到 |
| 快应用 | `com.vivo.hybrid` | 系统服务开关可关，`quickapp off` 备份原值后关闭并回读 |
## 补充：OriginOS 16 实测差异（V2361A，2026-10-26）
机型脚本：`recipes/vivo-V2361A/`。以下差异来自 V2361A 真机逐页实测。
| 位置 | V2547DA（OriginOS 6） | V2361A（OriginOS 16） |
| 系统设置页 | 普通列表 | 顶部有**悬浮搜索框**（y≈360-460），翻页后第一行会被盖住，直接点会误触搜索 |
| 开关控件 | 单个 Switch | 每行有**两个** Switch 节点：外层整行容器（clickable）、内层真开关。点外层会跳页不改状态 |
| 关闭确认 | 部分有 | 多数弹「确定 / 确认关闭」确认框，必须点掉 |
| 全局搜索 | 有独立的「推荐热搜榜单」入口 | 无该入口，热搜相关收在「首页展示内容 → 推荐卡片」 |
| 全局搜索·首页展示内容 | 搜索框推荐词、推荐卡片 | 搜索框推荐词、语音搜索、历史记录、推荐卡片 |
| 全局搜索·个性化内容 | 广告个性化 | 应用建议个性化、热门推荐个性化、搜索结果个性化、广告个性化 |
| 阅图锁屏 | 关「锁屏横滑进入阅图」带动总开关 | 反过来：关总开关「阅图锁屏」带动「锁屏横滑进入阅图」 |
| 应用商店 | 我的 → 设置 → 关于 | 一致；「个性化推荐」「服务管理」都在「关于」里 |
| 商店·个性化推荐 | 只有「个性化推荐」 | 多一项「个性化广告推荐」 |
| 天气 | 天气 → 设置 | 天气 → 更多 → 设置 |
| 浏览器 | 可正常进设置 | 本机为首次启动，停在「同意 / 不同意」协议页，未处理（规范不代用户同意协议） |
| 负一屏 | 左边缘右滑进入 | 左边缘右滑未进入，本机可能未开启或入口不同，待确认 |

| 关开关弹出的确认框，按钮点不到 | 按钮节点的 text 是空的，标题挂在子节点里，要按按钮子树里的文字找 |
| 点列表项左侧的文字没反应 | 点整行中间。商店「服务管理」、浏览器各设置项都这样 |
| 负一屏子页 back 多退一层，后面的项全找不到 | 用 Activity 确认还在 `AppletSettingActivity`，不在就重新滑进来 |
| 渠道页只有一个「允许通知」，关完整个 App 的通知都没了 | 那一页是应用总页。从总页点进渠道行再关；认不出渠道页就跳过，不关整个 App |
| `dumpsys notification` 的渠道状态和手机页面不一致 | vivo 开关存在自家通知服务里，以手机页面为准 |
| `pm suspend` / `disable-user` / `uninstall --user 0` 全报 SecurityException | 要 root。快应用用 `quickapp off`（改 `switch_quick_app_service`） |
| 备份里 `disabled.txt` 第一行是 `Error: Shell does not have permission to access user 666` | `pm list packages` 不带 `--user 0` 会遍历分身/隐私空间；工具已改成带 `--user 0` |

## V1986A（iQOO Neo 系）差异：Funtouch OS 13.0 / Android 12

2026-10-30 实测，构建 `PD1986_A_8.21.29`（`ro.vivo.os.name` 报 `Funtouch`，`ro.vivo.os.version` 13.0，Android 12）。
机型脚本 `recipes/vivo-V1986A/`：三段（系统广告 / 阅图锁屏 / 应用商店），整轮重跑 55 秒。

⚠️ **这台不是 OriginOS**：本文件上面按 OriginOS 写的路径都要先按本表核对，多数对得上，但锁屏和通知差得较多。

| 位置 | 本机实际路径 | 备注 |
|---|---|---|
| 广告与隐私 | 设置 → 安全 → 更多安全设置 → 广告与隐私（`AdAndPrivacyActivityForOsTwo`） | 与清单一致；个性化广告、个性化推荐、智能推荐服务三个开关都在这一页 |
| 锁屏设置 | `com.android.systemui/com.vivo.keyguard.views.KeyguardSettings` | **整页在 systemui 里**。引擎默认过滤 systemui 文字（那是状态栏），脚本读/点「阅图锁屏」前要 `p.sysui = True` |
| 阅图锁屏 | `com.vivo.magazine/.ui.MagazineSettings` | 本机「阅图锁屏」「轮播壁纸」「锁屏横滑进入阅图」实测都已关 |
| 应用商店 | 我的（**底部导航栏**）→ 设置 → 关于 → 服务管理 / 个性化推荐 | 底部标签 y 在 92% 以下，`p.find()` 默认不点导航栏，脚本按坐标点最后一个标签 |
| 商店·关于入口 | 点标题文字「关于」不跳转 | 要点**副标题**「包括禁用服务设置…」所在行的中间（`x≈0.4W`） |
| 商店·服务管理 | 9 个开关：签到有礼、顶部轮播图、顶部栏目、开屏、摇一摇、悬浮球、限时推广 + 我的页-我的服务、空间清理 | 前 7 个关，后 2 个保留 |
| 商店·个性化推荐 | `SettingUserRecommendActivity`，标题带状态「个性化推荐，开启 / 关闭」 | 点完标题就变，引擎按标题回读会误报「关不掉」，要按开关自身的 checked 回读 |
| i管家 | `com.iqoo.secure` V8.9.7.5，设置 → 关于 里**没有**「个性化设置」 | 本版无该开关 |
| 全局搜索 | 设置里没有独立入口，「桌面下滑」实测为「无」 | `com.vivo.globalsearch` 装着但没挂到桌面下滑 |
| 负一屏 | `com.vivo.hiboard` 的 `vHidden=1`（未启用），桌面左滑进不去 | 没有内容可关 |
| 快应用 | `com.vivo.hybrid` **未安装** | `quickapp` 无组件可处理 |
| 浏览器 / 天气 | 没有 `com.vivo.browser`；`com.vivo.weather` 未安装（另装 `com.vivo.dream.weather`） | 天气未实测，待补 |
| 营销通知 | 通知页宿主是 **`com.android.systemui`**，不是 `com.vivo.systemuiplugin`；`CHANNEL_NOTIFICATION_SETTINGS` 的 `CHANNEL_ID` 被忽略（直达只能打开应用总页）；渠道行在「类别」分组下面，首屏没有；渠道页顶栏**没有** `originui_vtoolbar_normal_title` id | 本机 `chan-off` 11 个渠道全部跳过，见 [#336](https://github.com/rddmwmddr/android-ad-cleaner/issues/336)。人工按「顶栏文字 == 渠道名 + 同行右侧『允许通知』开关」关掉 8 个；源码已按同一判据放宽认页（顶栏无 id 时按几何认、渠道行在「类别」下翻页找），待报告者复测 |
| 运营消息 | 渠道名就叫「运营消息」（`VPushChannel_0`），属营销分类；`VPushChannel_1/2` 是系统消息 / 即时消息，属服务类要保留 | `chan-scan` 按分类号放行 `VPushChannel_0/4/6`，不再被 `SKIP` 的「消息」滤掉，`1/2` 仍跳过，见 [#337](https://github.com/rddmwmddr/android-ad-cleaner/issues/337) |

## V2417A（OriginOS 6 / Android 16）差异

2026-10-30 在 `PD2417D_A_16.2.14.1.W10` 真机逐页实测，专用脚本为 `recipes/vivo-V2417A/recipe.py`。应用版本、验证范围及执行记录见[适配说明](../../recipes/vivo-V2417A/README.md)。

| 位置 | 本机路径或差异 |
|---|---|
| 系统广告与隐私 | `com.android.settings/.Settings$AdAndPrivacyActivityForOsTwo` 可直接启动；shell 中须引用 `$`，用 `settle=0` 避免消弹窗误点“关闭后”说明。设置首页悬浮搜索框可能遮住翻页后首行，脚本避开该入口 |
| 全局搜索 | `.view.SearchSettingsActivity` 可直接启动；“推荐热搜榜单”在“首页展示内容”里，不是全局搜索设置的第一层 |
| 阅图锁屏 | `.ui.MagazineSettings` 可直接启动；只处理“阅图锁屏”“锁屏横滑进入阅图” |
| 应用商店 | 设置页未导出；冷启动可能出现“月度精品”，点“进入首页”后走“我的 → 设置 → 关于” |
| 商店个性化 | 两个开关标题附带“开启/关闭”状态字，关闭需确认；按稳定标题回读，不把状态文字当按钮 |
| 商店服务管理 | 七项推广中的悬浮项叫“悬浮球”；“我的页-我的服务”和“空间清理”保留 |
| 浏览器 | “菜单 → 设置”；设置页未导出；极简首页另有关“首页上滑展示资讯”，更多设置底部还有下载页热门应用/热榜开关 |
| 手机管家、天气 | `.MainSettings`、`.WeatherSettings` 可直接启动；天气只关说明为“热点资讯通知”的“天气服务” |
| 负一屏 | 设置页未导出，从桌面第一页右滑进入，HOME 也可能恢复已打开的负一屏；服务推荐、资讯推荐、内容精选、热点资讯可单独处理，便捷生活与小V建议保留 |
| 通知、快应用 | 通用通知流程已安全关闭 5 个明确营销渠道；快应用可用系统服务开关关闭并回读，均不写入机型脚本自动执行 |

---

## X Fold6 的差异

实测：V2545A，OriginOS 6 Fold，Android 16，`PD2545B_A_16.0.16.0.W10`，2026-10-26。机型脚本 `recipes/vivo-V2545A/`，7 段全跑通，121 秒。上面 1–10 节的开关本身和 X300 Ultra 一致，差别都在「怎么走到那个页面」。

| 段落 | X300 Ultra（V2547DA） | X Fold6（V2545A） |
|---|---|---|
| 全局搜索 | 有「推荐热搜榜单」；首页展示内容里有搜索框推荐词 | **没有热搜榜单**；文档页只剩「搜索项」和「个性化内容」，只有「广告个性化」要关 |
| 阅图锁屏 | 直接拨开关 | 拨完弹「保持开启 / 关闭」确认框；按钮文字在子 TextView 上，`Button` 节点取不到 text |
| 应用商店 | 我的 → 右上齿轮 | 底部 tab 和齿轮都只有 `content-desc`；个性化开关在 **关于 → 个性化推荐** 子页，标题在开关行外，只能按 `Switch` 节点配对；服务管理仍在 **关于 → 服务管理** |
| 浏览器 | 我的 → 齿轮 | 底部 **菜单 → 设置**；`极简首页` 是单选项不是开关；隐私页多一个「个性化广告推荐」 |
| 天气 | 设置（齿轮） | 右上 **更多 → 设置** |
| i 管家 | 齿轮 → 关于 | 首次启动强制同意用户协议，工具不代点；同意后手动关「应用个性化推荐」 |

折叠相关的两点：

- **必须合上用外屏。** 展开时内屏 2504×2312（比值 0.92），`run.py` 的 `fold_open()` 会拦下；外屏 1120×2528（比值 0.44）才是单栏布局。用 `am start` 启动 App 时若不指定 display，可能落到内屏（display 0）而当前是关闭状态，表现为「没有进入前台」。
- **营销通知**：本机 `chan-scan` 只有 1 条候选（微博热点），且 vivo 通知页的开关是应用级总开关，`chan-off` 按保护逻辑跳过。负一屏仍要手动：桌面右滑 → 右上齿轮 → 更多设置 → 个性化推荐。
