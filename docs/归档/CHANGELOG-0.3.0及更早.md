# 更新记录

## 未发布

| 现象 | 来源 | 处理 |
|---|---|---|
| 渠道页认不出、报「应用通知页里没找到这一行」时，上报里只有一句「标题 / 开关各几个」，看不到页面结构；适配华为、荣耀这类「渠道名只写在 CheckBox 上」的布局（0.2.9 报告里 194 次）只能等个别报告者手动导 `uiautomator dump` | [#428](https://github.com/rddmwmddr/android-ad-cleaner/issues/428)（承接 [#426](https://github.com/rddmwmddr/android-ad-cleaner/issues/426) / [#427](https://github.com/rddmwmddr/android-ad-cleaner/issues/427) 的同一卡点） | 失败上报附一份**脱敏页面骨架**，判定逻辑未改。以文字或 content-desc 命中渠道名的节点为锚（精确命中优先，最多 8 个），带从页面根到所在行的祖先链与行子树；一个锚都没有时退回带开关的行（≤3 行），再退回屏内前 40 个节点。每节点一行：绝对层级、类名末段、屏宽高百分比 bounds、`c/k/v/s/e/T/D/N/M/P` 标记（`N`/`M` 分别是文字 / 无障碍描述等于渠道名，`P` 只是包含）与截短到 40 字符的 `resource-id`；**不含任何页面文字**。单份 ≤4KB、节点 ≤80（超出在头部写「剪枝 N」）；一次运行最多 2 份不同布局，同布局失败多少渠道都只留第一份（按结构行哈希去重）。只在「应用通知页里没找到这一行」触发；应用通知整体关闭（`no_row`，见 #426）不触发，不占预算。新增 `#aac:payload` 机器行通道（[ADR-0009](docs/adr/0009-engine-payload-channel.md)）：客户端 `_log()` 剥前缀后单独收进 `job["payloads"]`，上报时拼在 `log` 末尾的 `[页面骨架]` 段——发送前预览可见，不进界面日志与步骤摘要 `tail`，也不会在「最近失败的完整诊断」里重复；上报字段结构未变。服务端独立字段 `skeletons` 的规格（0–2 项、每项 ≤4096 字符、缺省视为空数组）写进 [docs/12](docs/12-错误日志上报.md)，本轮不动服务端。`python -m unittest discover -s tests` 803 项全过（基线干净副本 `22f9dd6`（分支基点）780 项，新增 23 项，2 项既有 skip 照旧；归档副本里 `test_compare_phone_state` 因缺 `.git` 报 1 项环境错误，后续 main 的 #446 已修，与本改动无关），Python 3.12 与 ruff 0.17.3 同过。**无真机**：华为 / 荣耀 / 三星页面样本按报告者 dump 结构造，骨架在真机上的实际形态要等下一版上报验证 |
| OPPO Find X9 Pro（PLG110，ColorOS 16.0.10.501(CN01) / Android 16）没有专用脚本，只能借用同品牌参考脚本 | 2026-11-01 社区真机实测（[#436](https://github.com/rddmwmddr/android-ad-cleaner/pull/436)） | 新增九段专用脚本 `recipes/oppo-PLG110/recipe.py`：广告跟踪、软件商店、浏览器、下拉搜索、负一屏、视频、游戏中心、小布建议、主题商店；锁定 `BUILD = "PLG110_16.0.10"`。与 ColorOS 17 的差异写进 `docs/清单/OPPO-ColorOS.md`：浏览器「广告管理」「个性化管理」在「隐私」下的二级页，视频是两个独立开关「个性化广告推荐」「个性化内容推荐」，负一屏设置入口不能从 Activity 直达、走桌面右滑 → 我的 → 设置。`read_switches()` 新增 `expect=` 提前退出，游戏中心「个性化推荐管理」标签过多时不必读满上限；软件商店服务管理按 `STORE_PROMOTIONS` 点名关 27 项推广位，其余核心服务保留。`python -m unittest discover -s tests` 773 项全过（基线干净副本 `origin/main@f4a78b4` 768 项，新增 5 项，2 项既有 skip 照旧），3.12 与 ruff 0.17.3 同过。**本仓库没有该机型**：九段逐项回读、60 个营销渠道、`com.opos.ads` 与 `com.oppo.instant.local.service` 的实测数字均为贡献者单机报告，未复测 |
| ColorOS 11/12（OPPO PBDM00 / Android 10）跑 `chan-off` 时 6 条渠道全部跳过，每条都写「停在 com.coloros.notificationmanager/…AppNotificationSettingsActivity；应用通知页没有打开」——两句自相矛盾；同一句「应用通知页没有打开」在 0.2.9 的 95 份报告里出现 174 次，其中红米一台机器 112 次停在第三方自动化工具 `com.aliothmoon.maafw.man`（MaaFramework），用户看不出是别人挡着 | [#415](https://github.com/rddmwmddr/android-ad-cleaner/issues/415)、[#422](https://github.com/rddmwmddr/android-ad-cleaner/issues/422) | 通知页身份白名单 `NOTIFY_HOSTS` 新增 `com.coloros.notificationmanager`：ColorOS 11/12 的通知页宿主是 `coloros`，ColorOS 14 起才是 `oplus`。正则与 oplus 条目同构，只认 `Channel` / `AppNotificationSettingsActivity`；「允许通知」总开关仍由 `_recognise()` 的 `AppNotification` 判定压住（去掉这条守卫，新用例会拿到应用总页上的开关而返红），该包的未知 Activity 与别的包冒用这个 Activity 名同样不认。`ChannelPage._focus()` 把读到的前台原文留在 `raw_focus`，应用通知页判空时据此点名是谁占着页面，分五类：前台为空或只读到窗口名（如 `NotificationShade`，不是「包名/Activity」）时沿用原文案、目标应用自己、已知通知宿主但 Activity 不认识（多半是新系统；只说「这个 Activity 没在已知列表里」——说成「不是通知设置页」会让人去退出一个系统包，说成「就是通知设置页」又把白名单的判据反过来）、系统设置但不是通知页、其余包（含桌面、启动器与第三方自动化工具）。不为此另发一次 dumpsys，也不劝「先暂停它」——桌面和启动器同样落进最后一类，包名对报告者已足够定位。`toggle()` 的「停在 …」是 `open()` 返回后另读的前台，两处各管一段、措辞不重叠。`_enter_app_page` 里另两处「翻页时离开了」不变。新增 13 项设备无关回归（基线干净副本 `origin/main@6b499f3` 718 项，本分支 731 项，2 项既有 skip 照旧），3.12 与 ruff 0.17.3 同过。没有 ColorOS 11 真机：页面样本按报告者的 dump 结构造，最终仍需报告者复测 |
| `quickapp check / off / on` 每轮全量拉 `dumpsys usagestats`（部分机型上是大文件）并对快应用表 10 个包逐个 `pm path`，`quickapp off` 一轮 49 条 adb；`status-json` 的 `fold_open()` 一行里调两次 `wm size`；`record()` 与 `cmd_suspend` 各写各的 `suspended.txt`、都不看已有行，同名包反复挂起/关闭时文件越写越长；`hap://` 接管提示只显示第一个应答组件 | 内部优化（[#335](https://github.com/rddmwmddr/android-ad-cleaner/issues/335) 复测时顺带发现） | 五处：① `quickapps(serial, with_usage=…)`——`quickapp off` / `on`、`check` 汇总行、`off` 收尾回读都不拉 usagestats（只有 `quickapp check` 的「近期打开次数」读它，`status-json` 的 `used` 字段照旧带真实值）；② 装机判定先用一次 `pkg_list("--user 0")` 批量过滤，两条通路都没读到包名时（HyperOS 4，#192）退回逐包 `pm path`，行为与批量前一致；③ `fold_open()` 的 `wm size` 只读一次；④ 两处写入口都收进 `record()` 并写前去重（读侧 `sorted(set(...))` 不变；`cmd_suspend` 把已定位的快照目录传给 `record(…, backup=d)`，不因去重多打一轮 `info()`）；⑤ `hap://` 提示对 `pm query-activities` 的应答组件去重后全部列出，单一组件时文案逐字不变。两处行为变化：`suspended.txt` 不再写重复行（读侧本就有去重，`unsuspend` 行为不变）；多个组件应答 `hap://` 时提示全部点名（旧文案只点第一个，误导排查）。CLI 对拍 29 组逐字节零差异：假 adb 同时回答批量清单与逐包 `pm path` 两套问题（`QUICKAPP_INSTALLED`），旧实现吃新规则输出不变、新实现与冻结基线一致；`quickapp-没有组件` / `quickapp-未知子命令` 的守卫断言改为 `pm list packages`（枚举通路变了，守卫语义不变）。纯调用序列收益（同规则下）：`check` 24→14、`quickapp off` 49→29、`quickapp on` 23→13、`status-json` 27→17（`wm size` 2→1），29 组里 7 组共少发 89 条 adb。新增 6 项设备无关回归（usagestats 门、批量清单替换逐包 `pm path`、清单读不到退回、`hap://` 多应答全列、`wm size` 只读一次、`suspended.txt` 去重），换回旧 `run.py` 6 项全部转红。`python -m unittest discover -s tests` 737 项全过（基线干净副本 `origin/main@ddafe9a` 731 项，新增 6 项，2 项 skip 照旧；逐字节对拍 `test_matches_baseline` 在 Windows 跳过，本机用 `.cmd` 假 adb 包装对拍过，CI 上照常跑）。无真机依赖，纯命令层优化 |

- 引擎核心重构（架构体检候选 6，[#423](https://github.com/rddmwmddr/android-ad-cleaner/issues/423)）：`off()` 把「这一页该拨哪些开关」收成纯函数 `plan_switches()` / `SwitchPlan`，点击、回读、三次重试、离页与记账仍留在 `off()`。**无行为变化**：筛选规则（含 `only` 名单外的追踪类保护开关放行）、屏带 8% / 98.5%、点击顺序与节奏、汇总文案、`p.changed` 与退出码均未改；改前改后对拍（基线 `5251839`）零差异：268 组读屏（`tests/` 全部可解析 `<hierarchy>` × 两种屏尺寸 × 读屏策略开 / 关）、136 组包名过滤、12 组 `off` 场景（两种屏尺寸 × 安全模式 × 三档 `only`）。

| 华为 / 荣耀应用通知页报「应用通知页里没找到这一行」：0.2.9 上报的 370 次里有 156 次（14 份报告）是页面「标题无、开关 1 个」——应用通知已被系统整体关掉，应用通知页就不会列出这个渠道。引擎记成「未确认」→ 算失败、进「仍开着」 | [#426](https://github.com/rddmwmddr/android-ad-cleaner/issues/426) | `notifications_denied()` 以前只读安卓 13 起的 `POST_NOTIFICATIONS` 权限；安卓 12 的华为 / 荣耀没有这个权限，判据从未生效。现在先看权限读数：`granted=true` 直接判没关，读不到这条权限才退回 `cmd appops get <包名> POST_NOTIFICATION`，`ignore` / `deny` 算整体关闭。`Unreached` 新增结构化字段 `no_row`——确认过停在应用通知页、且这一屏除了总开关再没有别的开关（应用通知整体关闭时的样子）；只靠「这轮没认出行」不算数，渠道名写在 CheckBox 上（#427）或被 `own()` 跳过时行还在页面上。`toggle()` 只在关闭方向、`no_row` 且 `notifications_denied()` 为真时产出既有的 `APP_DENIED`（不算失败、不进「仍开着」），其余情形照旧报「未确认…跳过」，给用户看的那段文案逐字不变；还原方向不受这条判据影响。读不出来（命令报错、格式不认识、`No operations`）一律按「没关」处理，不降级——宁可漏判，也不把真实失败静默吞掉。`python -m unittest discover -s tests` 768 项全过（基线干净副本 `origin/main@13a191f` 758 项，新增 10 项，2 项既有 skip 照旧），Python 3.12 与 ruff 0.17.3 同过。**没有真机复测**：「appops 为 ignore 时应用通知页只列总开关」这条推断来自 #330 在 ALN-AL00 上的观察，尚未在 #426 覆盖的机型上直接验证。同一卡点的第一种（渠道名只写在 CheckBox 上，194 次）拆到 [#427](https://github.com/rddmwmddr/android-ad-cleaner/issues/427)，等真机页面导出后再动 |

| PR 上的检查只跑 Linux，Windows 专属的用例要到打发布包才暴露（0.2.9 因此红了 3 个用例） | 内部工程（[#421](https://github.com/rddmwmddr/android-ad-cleaner/issues/421)） | `test.yml` 增加 `unittest-windows` job，PR 阶段跑同一套回归；顺带修掉 #443 新用例在 Windows 管道下的编码问题（[#440](https://github.com/rddmwmddr/android-ad-cleaner/pull/440)） |

## 0.3.0 · 2026-11-01

给用户看的变化：华为渠道行与同名分组标题的区分（#287）、vivo 旧系统渠道页（#336）与「运营消息」渠道（#337）、安卓 17 页面没画完就找入口（#331）、小米应用商店误把正文当设置入口（#305）、OPPO 关快应用后负一屏快递卡片打不开（#335）、POCO 广告组件（#367）、连接提示品牌认错（#357）、Android 版本为空（#195）、魅族其他机型可借用 21 Pro 参考脚本（#379）；新增 vivo X Fold6、Redmi Note 14 5G、一加 Ace 6T、小米 14 Pro（共用 13 Ultra 脚本）机型脚本；新增新机型适配辅助 `run.py adapt`。其余是引擎重构（ADR-0004 至 ADR-0007）：客户端改用结构化事件判断暂停 / 锁屏 / 读屏被占用 / 断开，`run.py` 按命令拆分，渠道分类和渠道页识别各收成一处。发版前 698 项设备无关回归通过；Android 15 模拟器验证检测、读屏、营销通知扫描 / 关闭 / 还原、快照、收尾，客户端执行流程的暂停 / 继续 / 停止与提示音。没有真机复测。

2026-10-26 新增 `run.py adapt` 四段流水线：探路 → 人工勾选 → 生成草稿 → 安全模式自检（采纳 [#61](https://github.com/rddmwmddr/android-ad-cleaner/pull/61) 的设计，按本仓库当前模型落地）。

- 新增一加 Ace 6T（PLR110，ColorOS 17.0.0.101 / Android 17）机型脚本 `recipes/oneplus-PLR110/recipe.py`，九段：广告跟踪、软件商店、浏览器、主题商店、视频、游戏中心、小布建议、负一屏、下拉搜索。贡献者 2026-10-31 真机实测整轮 224 秒；本仓库没有该机型，未复测。与 ColorOS 16 通用路径的差异写进 [docs/清单/OPPO-ColorOS.md](../清单/OPPO-ColorOS.md)：广告跟踪走设置首页的「隐私与安全」，并在广告跟踪页「更多选项 → 全部关闭」一次关完，关完回读这一屏，仍有开着的开关就退回逐项关；负一屏按页面内容判断而不是焦点窗口；浏览器用直达 Activity `com.heytap.browser/.settings.component.BrowserPreferencesPage` 进设置页；视频入口改叫「个性化管理」；下拉搜索的设置入口在搜索页底部，要先收起键盘。
- Redmi Note 14 5G（24094RAD4C）在当前 `main` 上复跑时，主题商店冷启动仍可能晚于固定 3 秒才显示底部「我的」，导致主题段报入口未找到。主题段现在每次先清理可识别的开屏 / 更新层，再查底部标签，最多尝试 5 次；补了等待成功的回归测试。2026-11-01 真机完整复跑八段 232 秒，下载管理 2 项、浏览器 4 项和其他目标共 21 项回读均为关闭，调整 0 项。
- `adapt explore`：复用 `tool/explore.py` 只读探路，输出 `探路-<型号>.tsv` 新增「人工勾选」列。从子页返回设置首页改成有界重试（最多 3 次）：回不去就重进设置页恢复，同一个 App 最多恢复 2 次，再失败就打印原因、明确中断本 App 并继续下一个；恢复后以实际落点刷新首页坐标。改前是「回退 2 次 → 重进一次 → 失败即停本 App」，两种写法都不会死循环，差别在恢复预算与落点坐标。
- `adapt gen`：把人工勾选的开关生成 recipe 草稿，不碰手机。保持 `@step("...")` 字面格式（`run.py` 的步骤名解析依赖它）和 `only=` 点名式；头部带 `BUILD`/`MODELS` 与通篇「待验证」标注；保护类开关（打开才是保护）不写进草稿；没有勾选任何开关时拒绝生成，不自动决定关哪些。
- `adapt check`：置 `Phone.safe_mode` 跑草稿（exec 注入 `p`/`ONLY`，与 `fast.py` 的 `run` 分支一致），回读统计后输出适配报告：回读确认几个/没找到几个/待人工确认几个/未完成几段；部分完成明确表述为部分完成，不说成成功。原提交写的是 `AAC_REF` 环境变量，该变量在 [#344](https://github.com/rddmwmddr/android-ad-cleaner/issues/344) 已换成 `Phone.safe_mode`，照原样落地等于自检没进安全模式——草稿模板恰好只用 `off(only=…)` 才没出事，手改过的草稿写裸 `p.off()` 会整页全关。落地时改置 `safe_mode`，并补了一条旧实现下必红的守卫用例。
- 引擎核心未改：`fast.py` 的开关、回读、安全模式逻辑，`ui_session.py`、`channel_policy.py` 均未改动；`run.py` 现有子命令行为不变（新增的 `adapt` 在 `dispatch()` 里按 `devices` 的办法先于 `-s` 校验分派）。

**验证**：新增 24 项设备无关回归（基线 `origin/main@3ca4afd` 601 项，本分支 625 项，2 项既有 skip 照旧）：探路 TSV 解析、草稿生成格式与 `run.py recipe_meta` 兼容、探路导航有界中断与恢复、适配报告数字与 mock 回读一致、check 退出码与恢复上限的规格数字、自检置 `safe_mode`。2026-10-26 报告者在 Redmi K50 Ultra（22081212C / diting，Android 15 / SDK 35，HyperOS V816，USB 调试已授权）上完成 `adapt explore` 真机探路：9 个 App（范围与 `recipes/xiaomi-M154FF` 一致）230 秒完成，产出探路 TSV，标记 3 个开着的疑似广告开关（主题商店：个性化推荐、早安画报×2），另有 4 个疑似开关已处于关闭状态；多个 App 没找到设置入口或启动后离开前台，工具按设计打印失败原因、跳过并继续下一个，未出现死循环。2026-10-26 机主勾选上述 3 个开关后完成 `adapt gen` + `adapt check` 真机自检：安全模式下回读确认关闭 2 项（主题商店「个性化推荐」「早安画报」）；第 3 段（经「设置 > 按分类轮播多张精美壁纸」路径关同一个早安画报）因前一段落在画报子页后主题商店无法回到前台而未完成（完整草稿连跑中可复现），工具如实报告「部分完成」——该开关已由「设置 > 锁屏画报」路径回读确认关闭，但此路径未验证到底。

**不宣称**：本工具不代表可自动适配任何机型；生成物均为待验证草稿，不等于适配完成；自检通过只证明勾选的开关「进得去、关得掉、回读确认」，转正式机型脚本前必须人工在手机上核对。文档中 Linux（arm64）adb 安装说明（`1:8.1.1-1+r23-5.4-1+eagle`，无 `adb pair`，无线调试不可用、USB 调试正常）验证日期为 2026-10-26，不代表其他版本与其他发行版。


| 现象 | 来源 | 处理 |
|---|---|---|
| `AndroidAdCleaner.exe` 在 Windows 上打不开、弹窗一律说「缺少微软 Edge WebView2 运行时」，可注册表里 `pv` 明明在——便携版 zip 解压出来的 `_internal\pythonnet\runtime\Python.Runtime.dll` 与 `_internal\clr_loader\ffi\dlls\amd64\ClrLoader.dll` 带 `Zone.Identifier`（「来自网络」标记），.NET 加载器拒载，`import clr` 失败，被 `except Exception` 误判成缺运行时 | [#228](https://github.com/rddmwmddr/android-ad-cleaner/issues/228) | 新增 `gui/winpreflight.py` 只做归因：`webview2_state()` 读 HKLM、WOW6432Node、HKCU 三处 EdgeUpdate 键给 `installed` / `missing` / `unknown`；`blocked_files(root)` 只查上面两个 dll 的 `Zone.Identifier`（不全扫解压目录）；注册表读取与 ADS 探测都从外面注入。`gui/app.py` 的启动失败分支改成按归因出文案：真缺运行时保留原文案并跳官网；MOTW 命中给「对 zip 右键 → 属性 → 解除锁定后重新解压」与 `Get-ChildItem . -Recurse -File | Unblock-File` 两条路，且不跳官网；注册表读不出来（`unknown`）只说「状态没能确认」并给出官网与反馈地址，不再断言不是缺运行时；已装且没被锁定才说按别的原因退出。`--smoke-gui` 在 `raise` 前多打一行 `startup: webview2=… motw=…`。文档同步 `docs/08`、`index.html` FAQ（入口改成同时覆盖两种提示）、`docs/09` 判据表、`gui/baidu_rows.py` 生成的网盘安装说明；`docs/adr/0003` 记下「PyInstaller 能收进同级模块」的实测，当初否掉 `gui/runner.py` 的打包顾虑据此证伪。**未做**：启动时全扫解压目录、自动解除锁定、失败留痕与上报（窗口没起来，上报通道走不通）。`python -m unittest discover -s tests` 718 项全过（基线干净副本 `origin/main@5251839` 698 项，新增 20 项，2 项既有 skip 照旧）。三处注册表键各有一条用例，删掉其中一条用例会返红（已实测）。CI 复现不了这条（runner 自己解压目录不打 MOTW），真机待报告者用新便携版复测 |
| 「走到某个渠道页」和「认出这一行的开关」散在 `tool/chan_fast.py` 的十一个函数里（`notification_focus` / `titled` / `top_title` / `group_floor` / `off_screen_name` / `allow_switches` / `channel_switch` / `inline_switch` / `page_switch` / `wait_page` / `via_app_page`），历次 ROM 适配（华为同名行 #287、vivo 两页同 Activity、ColorOS 独立宿主包）都只改其中一两个，其余不会跟着变 | 内部重构（架构体检候选 5，[ADR-0007](../adr/0007-channel-page.md)，[#399](https://github.com/rddmwmddr/android-ad-cleaner/issues/399)） | 新增 `ChannelPage(p, name, pk, cid, vivo_app)`，出口 `open(rounds=12)` 与 `refresh(rounds=6)`，返回 `Reached(switch)` / `Unreached(stage, why, hint, vivo_app)`。路线决策（`truncated(cid)`、`p.vivo_seen`）连同 `am start` 深链命令从 `toggle()` 上移，`open()` 内部再按「直达 → 应用通知页 → 内联行 → 同名放弃」走。`page_hint()` 降级为一行前向壳，页面结构摘要进 `Unreached.hint`；`toggle()` 的「未确认…跳过（停在 …；…）」文案逐字不变。`toggle()` 只剩打开 → `disabled_at()` 判灰 → 点击 → 回读 → `side_effects()` 检查，`undo()` 收进 `ChannelPage`。`Attempt` 降级为旧接口的数据袋，`notification_focus` / `channel_switch` / `inline_switch` / `page_switch` / `wait_page` / `via_app_page` / `page_hint` 保留为一行前向壳（测试面与对拍探针两边可跑）。**行为逐字不变**：`p.systemui_text` / `p.vivo_seen` 仍归 `Phone`（写入点搬进 `_focus()`，守 ADR-0002），异常契约不变（`ScreenLocked` / `DeviceLost` / `StopBatch` 重抛，`RuntimeError` 仍冒泡成 `Outcome(ERROR)`）。对拍 `tests/compare_chan_pages.py` 新增编排层探针（`toggle()` × 九类场景 × 两种屏尺寸，页面坐标按屏宽高取比例，否则 720 下开关落在屏外、六个场景一起退化成「没认出」）：4050 组零差异，守卫非零——认页层认出开关 86 组 / 认得顶栏标题 220 组 / 进页点了行 136 组，编排层九条分支各 2 组（直达、应用通知页、内联、同名放弃、截断 ID、vivo、锁屏、读屏报错、断线）。另做一次证伪：去掉「截断 ID 跳过深链」那条判据后，对拍报出 2 组差异且 `truncated` 守卫降到 0。`p.focus()` 调用次数 0 组变化。`python -m unittest discover -s tests` 686 项全过（基线干净副本 `main@e1a8001` 678 项，新增 8 项，2 项既有 skip 照旧），3.12 与 ruff 0.17.3 同过。无真机可验 |
| 机型脚本进设置页后立刻探测入口，Android 17 上页面还没画完就连续报五个「没找到」，整段失败；失败时只打一句「没找到」，分不清「没加载完」和「入口真的没了」 | [#331](https://github.com/rddmwmddr/android-ad-cleaner/issues/331) | `Phone` 新增 `entry()`：先 `await_page()` 等当前页站稳（走 `wait.until`，预算与轮询间隔可传，默认 2.4 秒 / 0.2 秒），再交给 `tap()`；一轮没命中不算结论，等页预算摊到两轮，第二轮等「与上一轮不同」的页面（`changed_from`），预算耗尽才判失败。找不到时 `note_miss()` 打印「停在哪个 Activity；标题 N 个，开关 M 个；结构 …」，与渠道「未确认」日志同一份控件链渲染（`row.link()`，`chan_fast.chain()` 改为转调），按仓库规则不打印页面文字；只在页面解析失败时省略摘要，断线（`DeviceLost`）照常冒泡。18 份机型脚本的 `maybe()` 统一改为转调 `p.entry()`，`redmi-23117RK66C` 的必需入口 `enter()` 与 `vivo-V2547A` 的 `tap_row()` 也改走等页。小米系 4 份脚本的齿轮入口原来点完就当成功，现在要 `Phone.in_settings_page()` 认出设置页（点击被吞时不 back、继续找「我的」），否则入口全打在旧页上。`entry()` 前后仍清零段级 `miss`，可选入口失败不会让后面的必需入口被「快速放弃」。正常路径输出不变，代价是每个可选入口固定多约 0.2 秒与两次读屏。回归用假设备时间轴复现「空白页 → 完整设置页」「一屏一屏往上长」「第一轮只等到半页、第二轮画完」：改前五入口全失败、中间页会被当成终点；改后逐项命中，页面始终空白时在 2.4 秒预算内判失败。`docs/04` 补 `p.entry` / `p.await_page` 两个动作，`docs/09` 登记 Android 17 真机缺口。`python -m unittest discover -s tests` 677 项全过（基线干净副本 `origin/main@4f65662` 664 项，新增 13 项，2 项既有 skip 照旧）。Android 17 真机未复测 |
| 营销 / 服务 / 受保护三种渠道判定散在两处、各用不同匹配域：`chan_fast.SKIP` 只看渠道名、命中就不进候选清单；`gui/app.py` 的 `SERVICE` 匹配整行 TSV、命中只是默认不勾；两份「服务类」词表互相重叠却又不相同，加一个词要先判断该改哪一份 | 内部重构（架构体检候选 3，[ADR-0006](../adr/0006-channel-classification.md)） | `tool/channel_policy.py` 新增 `classify()`，返回具名判定而不是单一类别：`marketing_candidate`（`KW`）、`scan_excluded`（`SKIP` 且非 vivo 营销 ID）、`default_unchecked`（`SERVICE`）、`protected`、`vivo_marketing_id`；`chan_fast.scan()` 与 `gui/app.py` 的 `chan_scan()` 都改读它，两处不再各写一份词表。厂商营销 ID 的 OR 收进 classify（`scan_excluded = SKIP 且非 vivo`）。旧 `SERVICE` 里两个依赖 TSV 形状的词条改成字段规则：`youtube\t2\t` → 包名尾部 `youtube` 且渠道 ID 为 `2`，`\t其他$` → 最后一个字段恰为「其他」。`protected_channel()` 保留为下层判据，`toggle` / `verify` / `huawei_channels` 三处直调不动。**判定逐条不变**：测试内冻结基线的 `KW` / `SKIP` / `VIVO_MARKETING` / `SERVICE` 原文，配 150 条语料（104 条逐词条样例覆盖每个词条，46 条边界与组合：有无非空应用名列、`youtube` 渠道、包名 / 应用名误命中、vivo 各个分类号）逐条对拍，差异为零；两处已知分歧原样保留并钉住（带非空应用名列的「其他」不被 `\t其他$` 命中；服务类裸词会命中包名或应用名），另开票处理。`python -m unittest discover -s tests` 647 项全过（基线干净副本 `origin/main@4f67b59` 638 项，新增 9 项，2 项既有 skip 照旧） |
| 小米 / 红米（HyperOS）跑机型脚本时，应用商店「我的」页那行正文「去功能设置里重新开启」先被 `gear()` 当成设置入口，点进「功能设置」子页，商店段四个入口全找不到；主题商店的「设置壁纸」同样会被先命中 | [#305](https://github.com/rddmwmddr/android-ad-cleaner/issues/305)（第二样本见 [#374](https://github.com/rddmwmddr/android-ad-cleaner/issues/374) 的评论） | `gear()` 的入口匹配是子串判断（`"设置" in d`，`d` 拼了 content-desc + resource-id + 正文），屏幕上任何含「设置」两个字的可点行都会先中。13 份小米 / 红米脚本的 `gear()` 改为 `icon_hit()`：只认**正好**是「设置」/「settings」/「setting」的描述或正文，或 id 最后一段里以 `setting` 开头的词（`iv_setting` 要认；商店「我的」页的 `securitySettingSwitchLayout` 不算——setting 前面粘着 security，点进去是「应用安全检测」）。`recipes/xiaomi-2512BPNDAC/` 里 2026-10-28 真机验证过的那版只认描述与 id，会让工具栏上 `text="设置"`、`clickable="false"` 的图标（靠尺寸启发式命中的那一类）失配，`tests/test_release_regressions.py` 抓到后一并补上正文精确匹配。兜底路径逐字保留：正文「设置」的 `p.find(..., exact=True)`、右上「更多」菜单、`toolbar_only` 的上沿限制。原匹配里的「更多」/`more` 排除条件随子串匹配一起删掉——精确匹配下已不可能命中含「更多」的描述或正文。**第二层原因**（底部标签读作「我的，有新消息」，精确匹配「我的」返回空，商店段仍卡在第一步）按票面第二条修复方向落在引擎：`Phone.go()` 在精确匹配当前屏找不到时退回包含匹配点一次，落点仍由 `expect` 确认，点错照样返回 `False`，所以 [#247](https://github.com/rddmwmddr/android-ad-cleaner/issues/247) 那种「包含匹配点到开关说明行」的风险不成立（`find(nav=True)` 也仍然排除开关行）；只放宽 `go()`，`tap()` 的语义不动，`docs/04` 的 `p.go` 一行同步写明。没有新真机样本，回归把 13 份脚本逐一跑页面样本：改动前共 51 处红——12 份各在 4 类干扰样本（商店正文、主题「设置壁纸」、只留干扰行、`securitySettingSwitchLayout`）上红，合计 48；`xiaomi-2512BPNDAC` 另在「不可点的工具栏图标」与 `iv_setting` 这两种形态上红（它原有的白名单过窄，正是本票要修的那一类），各 1；`go()` 的退回只有「标签带后缀」一条红。`python -m unittest discover -s tests` 638 项全过（基线 `origin/main@a3df736` 625 项，新增 13 项，2 项既有 skip 照旧） |
| vivo X Fold6（V2545A，OriginOS 6 Fold / Android 16）没有专用脚本，只能借用 X300 Ultra 的参考路径 | 2026-10-26 真机实测（[#54](https://github.com/rddmwmddr/android-ad-cleaner/pull/54)） | 新增七段专用脚本 `recipes/vivo-V2545A/`，锁定 `PD2545B_A_16`，入口沿用同代 OriginOS 6 路径并逐步真机核对；整段重跑 121 秒、七段零失败。整段只用 `only=[...]` 点名关闭，找不到入口就跳过。实测差异：全局搜索没有「推荐热搜榜单」，只剩「广告个性化」要关；阅图锁屏关开关弹「保持开启 / 关闭」确认框，按钮文字挂在子 TextView 上；应用商店底部 tab 与右上齿轮只有 `content-desc`，个性化开关在「关于 → 个性化推荐」且标题在开关行外，按同行 `Switch` 节点配对；浏览器入口为底部「菜单 → 设置」，极简首页是单选项；天气入口为右上「更多 → 设置」；i 管家首次启动强制同意用户协议，按硬规则不代点，只打印手动路径。折叠屏必须合上用外屏：内屏 2504×2312（比值 0.92）会被 `fold_open()` 拦下，外屏 1120×2528（0.44）才是单栏布局；`am start` 未指定 display 可能落到已关闭的内屏。快应用 `com.vivo.hybrid` 经 `switch_quick_app_service` 关闭并回读，`chan-scan` 只返回 1 条候选（微博热点）且该页为应用级总开关，`chan-off` 按保护逻辑跳过。脚本自己点的开关与 `p.off()` 一样记进 `p.changed`（收尾「关了 N 个」与 `run-log.txt` 都读它），并如实区分「本来就是关」和「这次关掉」；二次确认走引擎的 `p.confirm()`，不再自定义点击任意「关闭 / 确定」文字。`docs/清单/vivo-OriginOS.md` 补「X Fold6 的差异」一节，README 机型表新增一行。支持边界：负一屏、i 管家「应用个性化推荐」、微博热点渠道仍需手动。`python -m unittest discover -s tests` 601 项全过（本 PR 未改测试，与基线 `origin/main@3ca4afd` 相同，2 项既有 skip 照旧） |
| `tool/run.py` 的 12 条命令挤在一个近 280 行的 `main()` 里，退出码由 18 处散落的 `sys.exit` 决定——包括传输 helper `adb_shell()` 自己终止进程，以及 import 期就解析 adb 的模块常量 `ADB = adb_bin()`；命令之间没有进程内 interface，13 处测试只能 `patch.object(sys, "argv")` + `assertRaises(SystemExit)`，失败文案是 `SystemExit.code` 还是 `1` 各写各的 | 内部重构（架构体检候选 2，[ADR-0005](../adr/0005-run-command-handlers.md)） | 每条命令一个 `cmd_<名字>(serial, rest) -> int`，由一张 `COMMANDS` 表分派（`chan-off` / `chan-on` 两个薄包装共用一份实现）；`SystemExit` 只在 `if __name__ == "__main__": raise SystemExit(main())` 一处，handler 里不再有 `sys.exit`；错误文案由唯一的 `fail(msg)` 产生（文案进 stderr、返回 1），转发子进程码的五条（`ui-check` / `recipe` / `chan-off` / `chan-on` / `chan-scan`）逐值透出、不归一；`adb_shell()` 改抛 `DeviceLost` 交给出口渲染（`link_lost` 事件仍在构造时发），模块常量 `ADB` 改成惰性 `adb()` + 专用异常 `NoAdb`。改抛之后有两处旧代码看不见的陷阱，都已封住：`quickapp off` / `on` 里 `except (RuntimeError, OSError, ValueError)` 原来抓不到 `SystemExit`，改抛会把断线报成「某个组件关闭失败」（#293 反对的混判），两处 `except` 前各加一条 `except (adb_link.DeviceLost, NoAdb): raise`；`recipe` 的 `finally` 里恢复插电常亮，旧 `sys.exit("文案")` 要等 `finally` 跑完才打印，新写法改成先算 `message` / `rc`、`finally` 之后再渲染。两处行为变化：进程内调 `main()` 时错误文案立即写 stderr（旧 `sys.exit("文案")` 由解释器在进程退出时才打），以及没有 adb 时 `-h` 与无参数不再被 import 期拦下（以前连帮助都看不到）；`devices` 与参数写错的路径仍先报「找不到 adb」。对拍：`tests/baselines/run_cli.json` 由 `git archive e319126` 的干净副本对一份假 adb 跑出，29 组——落在 10 条命令上共 28 组（`devices` 2、`check` 2、`backup` 3、`recipe` 1、`suspend` 4、`unsuspend` 3、`quickapp` 6、`finish` 2、`status-json` 2、`dev-off` 3），加参数格式错 1 组，逐字节比对退出码与两路输出，每组配守卫断言（假 adb 收到的 argv 序列，或「一条都没发」）；`ui-check` / `chan-scan` / `chan-off` / `chan-on` 会真起子进程、输出取决于本机 adb 服务，改在进程内替身化后断言转发码与子命令参数。`python -m unittest discover -s tests` 586 项全过（基线干净副本 `origin/main@e319126` 568 项，新增 18 项，2 项既有 skip 照旧） |
| 客户端判断「暂停了 / 手机锁屏了 / 读屏被占用 / 手机已断开」靠 `startswith` / `in` 匹配引擎打印的中文句子（`gui/app.py` 的 `_log()` 与 `_work()`），改一句文案就静默坏掉暂停、提示音与后续步骤跳过；同一件「读屏被占用」有三种写法（`UIAUTOMATION_BUSY` / `DeviceBusyError` / 「正在使用这台手机的读屏服务」）；测试也把中文串当输入喂 `_log` | 内部重构（架构体检候选 1，[ADR-0004](../adr/0004-engine-state-events.md)） | 引擎在人类可读行之外另发一行 `#aac:event {"kind": …}`（[tool/events.py](../../tool/events.py)，只有客户端设了 `AAC_EVENTS` 才发，`_run()` 那条路不发），五个 kind：`paused` / `resumed` / `locked` / `ui_busy` / `link_lost`，发送点分别是 `fast.pause_point()`、两处 `wait_unlocked()`、两处占用抛出处、`DeviceLost` 构造。客户端 `_log()` 命中前缀先剥再解析——事件行不进界面、不进上报日志；`_work()` 改查本次步骤的事件集合。`@channels` 哨兵与按 argv 猜 `needs_ui` 换成 `Task(title, script, args, uses_ui, channels)` 描述符。人话逐字不变：五个发送点各设 / 不设 `AAC_EVENTS` 对拍，另加三句人话字面量断言。三处行为变化：`REPEAT`（「…已断开…」）现在也触发后续步骤跳过（以前因不含「断开了」漏判）；读屏占用只在真正抛出处判定，不再因报错里出现同名串误判；在步骤边界暂停期间点「停止」，客户端现在把「已暂停」复位（旧实现停止后仍一直报已暂停）。`python -m unittest discover -s tests` 568 项全过（基线干净副本 `origin/main@f46cd97` 538 项，新增 30 项，2 项既有 skip 照旧） |
| POCO 机型（`ro.product.brand` 为 `POCO`）跑 `check` 广告包一行为空，客户端检测页也拿不到 `com.miui.systemAdSolution`，「挂起广告组件」不会出现 | [#367](https://github.com/rddmwmddr/android-ad-cleaner/issues/367) | `AD_PKGS` 的键是 `ro.product.brand` 原值，只有 `Xiaomi` / `Redmi` / `OPPO` / `OnePlus` / `realme` / `HONOR` / `vivo` 七个；品牌族归一 `FAMILY` 早已把 POCO 归到 xiaomi，但 `check` 与 `status-json` 两处直接 `AD_PKGS.get(i["brand"])`，没经过它。`AD_PKGS` 的键改为品牌族（`oppo` / `honor` / `xiaomi` / `vivo`，包列表逐字不变），新增 `ad_packages(brand)` 一处取法，两个入口都改调它；七个原有品牌的 `check` 文本与 `status-json` 的 `ads` 逐字不变。没有 POCO 真机，回归用假 adb 与假 `info()`：`brand=POCO` 时 `check` 列出 `com.miui.systemAdSolution`、`status-json` 的 `ads` 含该包，旧实现这两条必红；`brand=iQOO` 仍为空作守卫，另加七个原有品牌原值取到的包列表与改前逐项相同的用例。`python -m unittest discover -s tests` 538 项全过（基线 `origin/main@f0235ba` 534 项，新增 4 项，2 项既有 skip 照旧） |
| 复盘 #355：文档里的用例总数被 rebase 打回三次（518 → 524 → 527 → 533），两轴审查各报了两次数字对不上；基线数在主副本上数，被并行会话未提交的 6 个用例污染，得出过错误结论；非测试入口 `gui/shots.py` 在 `Api()` 改成必填参数时静默坏掉，全量回归一片绿；`CLAUDE.md` 里把测试已经守住的规则又复述了一遍 | 内部重构（复盘，#355） | `CODING_STANDARDS.md` 第 1 条补「改过基线的数字要重算、写下时标明基线、优先写新增项」；`CLAUDE.md` 的回归条补「数基线总数用 `git archive origin/main` 的干净副本」；新增 `tests/test_entrypoint_refs.py`——AST 扫 `gui/` 下 import 了 `app` 的脚本，`app.<名字>` 要在模块上存在、`app.<名字>(…)` 的实参要能绑定到签名，并用「把 `shots.py` 改回 `app.Api()`」证伪过（同时报出属性不存在与 `missing a required argument`）；`CLAUDE.md` 里那条 import 副作用规则退成导航指针，`docs/adr/` 的清单补到 0001–0003。不改产品行为，`python -m unittest discover -s tests` 534 项全过（基线 `origin/main@d61ea71` 533 项，新增 1 项） |
| vivo 上跑 `chan-scan`，11 条该关的营销渠道只列出 1 条，其余 10 条 `VPushChannel_0`「运营消息」全不见 | [#337](https://github.com/rddmwmddr/android-ad-cleaner/issues/337) | `chan_fast.SKIP` 里的单字「消息」本意排除聊天 / 私信，却把 vivo 固定编在 `VPushChannel_0/4/6` 的营销分类整类剔掉，与 AGENTS.md §5 冲突。扫描候选改为：渠道 ID 命中厂商营销分类号（`VIVO_MARKETING`）时越过 `SKIP`，营销关键词仍要命中——不越过关键词，否则同 ID 下的服务类渠道会进客户端清单并被默认勾选（`gui/app.py` 的 `SERVICE` 不含「消息」）；保护名单仍最高。同机的 `VPushChannel_1`（系统消息）/ `VPushChannel_2`（即时消息）、其他 vivo 分类号、非 vivo 名字含「消息」的渠道行为逐字不变。没有 vivo 真机，回归用假设备喂 dumpsys 文本：`VPushChannel_0` 的「运营消息」进清单，`4` / `6` 同样进，1/2 不进，`VPushChannel_0` 下名字不含营销词的「订单物流」与「找机位推荐」不进，`VPushChannel_7` / `VPushChannel_0x` / 非 vivo `promo` 仍不进；旧实现下「运营消息」「4/6」「1/2 不放行」三条必失败，另三条是防回退的守护。`python -m unittest discover -s tests` 520 项全过（新增 6 项，2 项既有 skip 照旧） |
| OPPO / 一加 / realme 跑 `quickapp off` 后，负一屏快递卡片还在，点「全部」打不开详情页，弹「快应用服务框架目前无法使用。该应用是由Shell所管理。」 | [#335](https://github.com/rddmwmddr/android-ad-cleaner/issues/335) | 快应用平台 `com.nearme.instant.platform` 承载快递详情页。PMX110 / ColorOS 17 逐个单独挂起实测：挂 `com.oppo.instant.local.service` 或 `com.nearme.instant.card` 时快递卡片与详情页都正常，只有挂平台才复现。`run.py` 新增 `QUICKAPP_KEEP`，`quickapp off` 不挂平台并在输出里标「保留」，`quickapp check` 同步标注；保留平台意味着 `hap://` 仍能拉起快应用，两处输出如实提示「广告仍可能跳进快应用」。客户端检测页的「已关闭」判据改为「除保留项外全部关闭」，选择页不再把保留项列进要关闭的名单，并点名快递卡片依赖它。`docs/07-快应用.md` 与 `docs/清单/OPPO-ColorOS.md` 补实测结论与取舍。没有第二台真机（逐组件实测由报告者在 PMX110 上完成），回归用假设备：`quickapp off` 只下挂另两个组件、`quickapp check` 输出保留与 `hap://` 提示，去掉 `QUICKAPP_KEEP` 时 3 项转红；`python -m unittest discover -s tests` 512 项全过（新增 4 项，2 项既有 skip 照旧） |
| `import gui.app` 在 import 期就 `os.makedirs` 用户数据目录、改 `sys.path`，于是测试只能用 18 处 `importlib.util.spec_from_file_location` 把它以十几个模块名反复拉起来；`Api()` 构造即跑 `find_adb()`（`adb version`，8 秒超时），15 处用例都在真跑；数据目录的 7 条派生路径各算各的；备份目录的命名、扫描、`<型号>-gui` 兜底和 `AAC_BACKUPS` 的读取散在 `tool/run.py`、`gui/app.py`、`tool/fast.py` 三处算、四处读 | 内部重构（[#355](https://github.com/rddmwmddr/android-ad-cleaner/issues/355)） | `gui/app.py` 的 import 期不再碰磁盘与 `sys.path`：工具模块改成 `_tool()` 惰性取（第一次真正用到才把 `tool/` 加进 `sys.path`）；数据目录收进 `ClientData(root)`（构造只算路径，`ensure()` 才建，`_install_id` 写入前补上原来靠 import 副作用的那次建目录）；`Api(data_dir, adb=None, runner=None)` 三个参数由入口给，`find_adb` 移到入口 `client_api()`（窗口与截图脚本共用）；新增 `tool/backups.py` 的 `Backups(root)`，命名 / 扫描 / `-gui` 兜底各一处，root 由调用方注入（客户端是 `<数据目录>/backups`，命令行是 `AAC_BACKUPS` 或仓库根的 `backups/`），`run.py` 的 `latest_backup` 与 `status-json`、`gui` 的 `_latest_backup`、`fast.py` 的 run-log 目录都改成读它；`Runner` 收「怎么起一个 tool 子进程」，`_run` / `_work` 走它。测试回到正常 `import gui.app`（3 处 `bundle_data` 同样改成 `from gui.bundle_data import`），18 处 spec 加载归零。逐字不变：对外文案、退出码、GUI 行为、`--cli` 启动方式、`_MEIPASS` 布局、`AAC_BACKUPS` 语义，以及 `<型号>-gui` 在字典序上优先于带时间备份这条既有行为；现有三类 subprocess patch 照旧生效。新增用例：`import gui.app` 的子进程测试（临时 `HOME`/`APPDATA` 下不建目录、不改 `sys.path`、不加载 `tool/` 模块，改前必红）与备份目录对拍（7 组目录树喂给新旧两份实现，含 `-gui` 优先与 model 为空，两条目标分支各配守卫）。`python -m unittest discover -s tests` 533 项全过（新增 13 项；同一台机器上 `git archive origin/main` 的干净副本是 520 项）。没有 Windows、没有打包环境：`--cli` 子进程、`_MEIPASS`、`--smoke-gui` 未在打包件上验证，依据是 `cmd_for` / `cli_main` 逐字未改、`child_env` 只多收一个备份根（值与原 `BACKUPS` 相同）加单测。模块边界与五个被否的选项见 `docs/adr/0003` |
| Redmi Note 14 5G（24094RAD4C）没有专用脚本，检测时只能借用 Xiaomi 18 Pro Max 的参考路径 | 2026-10-30 真机实测 | 新增八段专用脚本 `recipes/redmi-24094RAD4C/`，锁定 HyperOS OS3.0.306.0；沿用适配 Note 14 Pro 时验证过的入口，主题段处理实测出现的「跳过广告 N 秒」开屏窗。下载管理和浏览器的二次确认开关会吞掉引擎默认短按，脚本改用普通点击、确认并核对其他开关未变，关掉的开关与 `p.off()` 一样记进 `p.changed`（收尾的「关了 N 个」与 `run-log.txt` 都读它）。应用商店保持标准模式和自动升级，浏览器保留小说、我的网盘等功能入口。首轮统计 20 项——该数来自记账修复前的引擎，下载管理的 2 项与浏览器的 2 项未计入；复跑 291 秒、21 项目标回读全部关闭、调整 0 项；营销通知 3 个候选全部关闭并回读为 0。脚本回归和全套测试通过 |
| `fast.Phone` 的 interface 有一半没声明：`sysui` / `vivo_seen` / `vivo_app` / `why` / `stage` / `pkg_now` 由别的模块临时挂上，读的地方一律 `getattr(p, "x", 默认值)`，写错名字也不报错；测试只能 `.__new__` 后逐项赋值（28 处、10 个文件），`AAC_REF` 环境变量还改写 `off()` 的语义 | 内部重构（[#344](https://github.com/rddmwmddr/android-ad-cleaner/issues/344)） | 按生命周期拆开：一次渠道尝试内的诊断（`why` / `stage` / `vivo_app`）搬进 `chan_fast.Attempt`，由 `toggle()` 创建、作为必填参数穿过 `channel_switch` / `inline_switch` / `page_switch` / `wait_page` / `via_app_page` / `undo`，不再手工清空上一个渠道的残留；读屏策略与设备记忆（`systemui_text`（改名自 `sysui`）/ `vivo_seen` / `safe_mode`）在 `Phone.__init__` 声明，`getattr` 兜底全删，忘了初始化会在第一次读时炸；`pkg_now` 消失，改成 `entries(p, pkg)` 的参数；`AAC_REF` 换成 `Phone.safe_mode`，由 `run.py` 追加的 `fast.py run --ref` 传下去（版本不符时 `fast.py` 自己置位）。读屏 adapter 起名 `tool/reader.py` 的 `Reader`：`Phone.reader` 是名字，`p.d` 保留为写穿 property，`recipes/` 85 处 `p.d.xxx` 与测试引用一行不改；`Phone` 也可以从注入的 reader 构造。逐字不变：`NOT_CONFIRMED` 的整句（`stage` ＋ `page_hint` ＋ `why` 的拼法）、安全模式的提示、各入口退出码与 `--ref` 的对外用法。测试装配迁到 `phone_stub()`（它补齐构造处的默认值，只有 `pause_at_lock_check` 默认为 `False`——假手机后面没有客户端在点「暂停」）。模块边界与五个被否的选项见 `docs/adr/0002`。没有真机，验收是对拍，驱动在 `tests/compare_phone_state.py`（改动前的 `tool/` 当基线，一条命令跑两边）：`texts()` 228 组（`tests/` 全部可解析页面样本 × 两种屏尺寸 × 读屏策略开 / 关）、`entries()` 116 组（页面 × 包名）、`off()` 2 组（安全模式开 / 关，改前靠 `AAC_REF=1`、改后靠 `p.safe_mode`），逐项一致；守卫断言确认对拍真的走到目标分支——翻策略有 2 组输出不同，换包名有 2 页不同，安全模式把同一页的点击从 6 次降到 3 次。`python -m unittest discover -s tests` 504 项全过（新增 10 项，2 项既有 skip 照旧） |

| OPPO Find X8s（PKT110）0.2.8 实测：「关闭各 App 里的广告开关」其余各段全过，只有主题商店一段失败，报 `{'code': -32002, 'data': "Selector [text='我的']", 'method': 'wait'}` | [#286](https://github.com/rddmwmddr/android-ad-cleaner/issues/286) | 主题商店首页的「检测到新版本 17.22.0beta2」弹窗盖住底部标签栏。脚本那几句用的是读屏库的裸 `d(text=…).click()`，元素等不到就等满 20 秒抛 -32002，把脚本自己的「边等边关弹窗」整套绕过了。三处改动：`Phone.dismiss()` 新增更新弹窗规则——页面上有「检测到新版本」这类标题就先点拒绝类按钮，且不受「带滚动列表就不点」的守卫限制（更新说明常放在可滚动容器里）；正常设置面板没有这种标题，仍不会被误点。主题商店与视频两段的「我的」改成会关弹窗并校验的 `p.tap(..., scrolls=0)` + `require`，找不到时报出原因而不是抛读屏库的异常。`tap(scrolls=0)` 的兜底窗口从 3 秒放宽到 6 秒，覆盖启动后几秒才弹的更新弹窗；只在找不到目标时多等，正常路径不变。没有 PKT110 真机，同一批用例在改动前的 `fast.py` 上两条必失败（更新弹窗返回 `None`、底栏 4.4 秒后才出现时放弃），改后全过；`python -m unittest discover -s tests` 508 项全过（新增 5 项） |

| 连接页的 USB 提示拿设备管理器里第一条手机类设备当品牌：华为 M30 连不上时提示「电脑识别到华硕手机的调试接口」，华为的排查建议（仅充电模式下允许 ADB 调试、HarmonyOS NEXT 不支持 adb）一并丢掉 | [#357](https://github.com/rddmwmddr/android-ad-cleaner/issues/357)（来自 [#348](https://github.com/rddmwmddr/android-ad-cleaner/issues/348)） | `usb_hint()` 的品牌只从**带调试接口**的设备里取，电脑上另插的外设不再顶替用户的手机；多台手机同时插着时不猜是哪台，逐条列出「品牌 + 状态」并提示只留一台。单台时的三种文案与驱动建议逐字不变。没有 Windows 可插手机，验收是 `usb_hint()` 纯函数用例：同一份设备列表换顺序结果一致、非手机设备不参与命名、两台都不在调试模式时逐台列出；旧实现下新用例两条必失败（提示成「华硕手机」）。`python -m unittest discover -s tests` 510 项全过（新增 2 项） |

| agent 环境：以 `Mock()` 冒充 `Phone` 的用例（14 个文件 54 处）在 `Phone` 新增声明字段后静默走真值分支——`safe_mode` 当真、`Phone.start` 走 `reader` 而用例改的是 `p.d`，0.2.9 的 `test_vivo_v2417a_recipe` 因此红过一次；对拍脚本留在 `/tmp`，CHANGELOG 的数字无法复现；票的关闭判据与「票即 spec」都靠临场推断（`#344` 被问住、ADR/CONTEXT 被 Spec 审成 scope creep）；rebase 停在半途就去跑回归；`Phone` 里漏了一处 `getattr` 兜底 | 内部重构（复盘） | `tests/fixtures.py` 新增 `phone_mock()`：以 Mock 冒充 `Phone` 时补齐构造处声明的开关，并让 `d` 与 `reader` 指向同一个 Mock；`test_vivo_v2417a_recipe.py` 的九处装配迁过去。`docs/agents/issue-tracker.md` 新增「票的生命周期」：实现合入即关、未做的 Follow-up 转入跟踪票、票的「方案」段写全 grilling 定下的交付物（Spec 审查只认票面）。`CLAUDE.md` 的 CHANGELOG 一条补上「rebase 后先 `--continue` 再跑回归与对拍，`## 未发布` 被已发版小节吸收时重新开出来」。`CODING_STANDARDS.md` 新增判断项：`Phone` 构造处声明的字段直接读，不用 `getattr` 兜底。不改产品行为，`python -m unittest discover -s tests` 504 项全过 |

| `check` 首行的 Android 版本为空：HyperOS 4（24129PN74C）上单键 `getprop ro.build.version.release` 返回空，而完整 `getprop` dump 给的是陈旧的 `6.0.1` / SDK `21`，两条通路各缺一半 | [#195](https://github.com/rddmwmddr/android-ad-cleaner/issues/195) | `prop()` 之上加 `android_release()`：按 `ro.build.version.release` → `ro.build.version.release_or_codename` → `ro.system.build.version.release` → `ro.product.build.version.release` → `ro.system_ext.build.version.release` 顺序取第一个非空值。**不退回完整 dump**——这台 dump 里的值是假的，宁可为空也不报错版本。其他机型第一个 key 就命中，行为不变。读数函数本身不编造版本，五个 key 都读不到返回空串，由 `info()` 显示成「未知」——诊断输出留空会被当成没读到。真机验证：这台 `check` 首行从空变成 `Android 17`；`python -m unittest discover -s tests` 575 项全过（基线 `origin/main@e319126` 568 项，新增 7 项，2 项既有 skip 照旧） |

| vivo 旧系统（Funtouch 13 / Android 12）`chan-off` 11 个营销渠道全部跳过：渠道页顶栏是没有 resource-id 的 TextView，渠道行又在应用通知页的「类别」分组下面、首屏读不到 | [#336](https://github.com/rddmwmddr/android-ad-cleaner/issues/336) | `top_title()` 在拿不到 toolbar id 时按几何兜底：顶部 15% 内、几乎横跨整屏的那段文字才算顶栏标题（半屏宽的多半是行内标签，拿它当标题会把应用总开关当成渠道开关）。`via_app_page()` 的 vivo 分支：分组标题「类别」在屏内时只认它以下的同名行（不在屏内时照旧不设这个限制）；行已读进 dump、坐标却在屏下时自己翻一页找它，滑完查一次焦点、页面没动就停，不当成「没找到这一行」；应用通知页上读到 App 名就先记下，往下翻页后顶栏收起也能认渠道页。认不出照旧跳过、不点页面上的第一个开关；直达深链的取舍不变（这台机器忽略渠道 ID，跳过直达是对的）。新增 17 项设备无关回归（基线 `origin/main@4f67b59` 638 项，本分支 655 项，2 项既有 skip 照旧），样本按报告者 2026-10-30 的真机 dump 造。既有页面样本对拍 `python tests/compare_chan_pages.py <改动前的 tool 目录>`：共 3840 组（认页 3200 组、进页 640 组），`channel_switch` 零差异；`top_title` 20 组变化，都来自同一份设置页搜索框样本（720 宽）由空变成「搜索框」，方向是更保守的跳过；`via_app_page` 22 组变化，都是样本里屏下有同名行时多翻一页再放弃，没有多点行、也没有把未完成报成成功。**没有真机复测**：机器在报告者手上，修复要等他复测后才算通过 |

| 魅族不在品牌族表：除 21 Pro 外所有魅族机型 `check` 只报「机型脚本：没有」，连「同品牌参考 …」这句都没有，尽管仓库里有 `recipes/meizu-MEIZU 21 Pro` | [#379](https://github.com/rddmwmddr/android-ad-cleaner/issues/379) | `run.py` 的 `FAMILY` 补 `meizu`，`REFERENCE` 显式钉 `meizu-MEIZU 21 Pro`（不靠目录名排序取第一份，社区再提一份魅族脚本时别的机型用的参考不跟着变）。只加这两条不够：魅族脚本的 `step()` 每段硬校验型号与 `BUILD`、不认 `--ref`，借过去 8 段全部是「型号或系统版本不符，未操作」。改成安全模式下不因型号/版本拒跑，逐段找入口、找不到就跳过，与另外四族的参考脚本一致。代价是 21 Pro 本机版本不符时也从「每段停下」变成「逐段跑」，整页全关仍由安全模式挡着。魅族广告包名无证据，`AD_PKGS` 不补。`python -m unittest discover -s tests` 683 项全过（基线干净副本 `origin/main@e1a8001` 678 项，新增 5 项，2 项既有 skip 照旧）。MEIZU 22 真机未复测 |

| 小米 14 Pro（23116PN5BC，HyperOS OS3.0.308.0.WNBCNXM / Android 16）不在 13 Ultra 脚本的 `MODELS` 里，`check` 报「本型号没有；同品牌参考 `recipes/xiaomi-M154FF`」，而 M154FF 是按 HyperOS OS4 录的；用户只能手工指定 `recipes/xiaomi-2304FPN6DC` 并强制安全模式 | [#317](https://github.com/rddmwmddr/android-ad-cleaner/issues/317) | `recipes/xiaomi-2304FPN6DC/recipe.py` 的 `MODELS` 加入 `23116PN5BC`，与 `2304FPN6DC` 共用这份 OS3.0.308 脚本（写法同 `xiaomi-M154FF` 里的 18 Fold）。脚本内容不变：不新增段、不改已命中的开关、不动其它型号。型号命中后「是否参考」为假，`cmd_recipe` 的 `safe_mode` 只剩版本比对：报告者的 `ro.build.display.id` 是 Android 底包 `BP2A.250605.031.A3`，HyperOS 号 `OS3.0.308.0.WNBCNXM` 与录制版本 `OS3.0.308` 对得上，不再打印安全模式提示。报告者原轮是手工指定脚本 + 安全模式跑的：9 段全完、19 项开关关闭且每步回读，浏览器「搜索设置」一页没命中目标开关（票面列为 out of scope，是这层入口不同还是这台没有这个开关仍未确认）。`python -m unittest discover -s tests` 689 项全过（基线干净副本 `origin/main@6a07b2c` 684 项，新增 5 项，2 项既有 skip 照旧）。正常模式整轮未真机复测 |

## 0.2.9 · 2026-10-30

Rikki Lv 的手机连接重构和华为同名渠道行修复（#287）；合并 12 个社区 PR：10 个新机型脚本、1 个华为营销通知命令行工具、同一型号按系统版本选脚本。

| 现象 | 来源 | 处理 |
|---|---|---|
| 同一个 seam 上挂着四个 adapter，各写一遍「找 adb → 带 `-s` 执行 → 认 `client_gone` → `wait_for` → 抛 `lost`」；三份 adb 查找列表互不相同（`adb_link.adb_path` 漏 `~/platform-tools`，`run.adb_bin` 漏 `ADBUTILS_ADB_PATH`，`gui.find_adb` 另有客户端下载目录与版本闸门） | 内部重构（[#334](https://github.com/rddmwmddr/android-ad-cleaner/issues/334)） | `tool/adb_link.py` 新增 `Connection`：`shell` / `push` / `alive` / `mark_lost` / `lost_reason`，「等它回来重试一次」与「确认断开后只报一句」只在这里。传输是 adapter——`adb` 命令行（本模块自带）、读屏库的 shell（`fast.Phone` 注入）、测试假 transport。`run.adb_shell`、`chan_fast.ShellPhone`、`fast.Phone._resilient_shell`、`gui.adb_present` / `Api._adb` 都改为消费它，`troubleshooting.accessibility_summary` 的 adb 查找换成 `adb_path()`（它那条只读命令本身没变），`ShellPhone` 里 `from run import ADB` 的反向依赖去掉；`adb_path(first=())` 收口三份查找列表，`≥ 1.0.41` 的版本闸门仍只在客户端。逐字不变：`HINT`、`REPEAT`、「adb 读取失败：」、「adb 传文件失败：」、「找不到 adb。安装方法见 docs/01-准备工作.md」，以及各入口的退出码。行为上只多三处：`run.py` 现在也认 `ADBUTILS_ADB_PATH`；客户端候选顺序统一为「下载目录 → `ADB` → `ADBUTILS_ADB_PATH` → `PATH` → 系统 SDK → `~/platform-tools` → `~/android-tools` → Windows 默认安装目录 / homebrew / `/usr/local/bin`」（原来客户端不看 `ADB` 环境变量）；完全没装 adb 时 `chan_fast` 走它一贯的「✗ …」前缀打印同一句，不再直接 `sys.exit`。模块边界与四个被否的选项见 `docs/adr/0001`。没有真机，验收是对拍：五个回答序列（一次成功 / 断线后回来 / 断线且等不回来 / 等回来但第二次还断 / 普通失败）× 三个入口（`run.adb_shell`、`chan_fast.ShellPhone.shell`、`fast.Phone._resilient_shell`）15 组，另加 `gui.adb_present` 5 组（`device` / `offline` / 空 / 断线原文 / 等 10 秒超时）与「一次掉线不毒掉整批」1 组，比较 argv、重试次数、抛出的异常类型与消息、退出码、返回的布尔，逐项一致；另有 17 条直接断言断线策略、等待语义与查找顺序的用例，以及 7 条守卫断言，确认对拍真的走到了「断线」与「非断线的命令失败」两条路。`python -m unittest discover -s tests` 409 项全过（新增 22 项，2 项既有 skip 照旧） |
| agent 环境：本地跑不了 CI 的静态检查（`requirements.txt` 只有 uiautomator2）；对拍没有「必须证伪」的规则，只喂成功路径的用例会冒充证据；造一个不连手机的 `Phone` 要在 28 处各自 `.__new__` 再逐项赋值 | 内部重构 | `CLAUDE.md` 的静态检查改成可直接执行的 `uvx ruff@0.17.3 check --select F,E9 tool tests gui`（与 CI 同版本），并补两条容易踩的约定：worktree 用主副本解释器的绝对路径、CHANGELOG 新行落在 `## 未发布` 且 rebase 后复核；`CODING_STANDARDS.md` 新增「对拍要能证伪」——每个入口至少各有一条断线 / 非断线失败 / 超时的用例，每条配守卫断言，附本次「两边都 `IndexError` 却判一致」的反例；`tests/fixtures.py` 新增 `phone_stub()`，`fake_phone()` 改为建在它上面，不连手机的 `Phone` 装配只此一处。不改产品行为，`python -m unittest discover -s tests` 411 项全过（新增 2 项） |
| 华为 CET-AL00（HarmonyOS 4.2）的应用通知页把分组名和渠道名写成同一个词，两行各自都带一个合格开关：0.2.8 那次关了 4 个渠道，31 次报「未确认」，结束时 26 个仍开着，日志只有一句「同名 2 行」，没有任何结构可定位 | [#287](https://github.com/rddmwmddr/android-ad-cleaner/issues/287) | 两行都合格时再按几何分一次：渠道行的标题和它自己的开关在同一水平带上（中心错开不超过两者中较高的那个的高度）才算，仍不止一行照样放弃、不猜。放弃时每一行都留下「行高百分比 + 错开距离 + 控件链」（不含页面文字），下一次上报能直接定位。没有华为真机，模拟页面回归：分组行借来的开关错开 280px 时选中渠道行，两行同带时仍然拒绝 |

### 社区

- **同一型号按系统版本选机型脚本**（#338）：`recipes/<型号>/` 里可以放 `recipe_*.py` 变体，录制版本和手机对上时用变体，否则用 `recipe.py`。首个变体是一加 Ace 2 的安卓 15 路径。合并时补了打包清单：原来只打包 `recipe.py`，变体进不了安装包。
- **小米 15（24129PN74C）两份脚本**：#312 是 HyperOS 3（OS3.0.307，`recipe.py`），#298 是 HyperOS 4（OS4.0.0.22，改名为变体 `recipe_os4.py`）。两份都是真机实测，按系统版本自动选。
- **新机型脚本**：OPPO Find X9 Ultra PMA110 / ColorOS 17（#300）、OPPO Find X10 Pro Max PMX110 / ColorOS 17（#279）、OPPO Find N5 PKH110 / ColorOS 17（#277）、REDMI K80 Pro 24122RKC7C（#295）、Redmi K70 Pro 23117RK66C（#324）、vivo V2417A / iQOO Z9 Turbo+（#339）、vivo V1986A / Funtouch 13（#341）。都由贡献者在自己的手机上录制，检测到用户协议或权限申请时停下、不代点。K80 Pro 的实测记录改为 `docs/15-红米K80Pro实测.md`（和 K70 Pro 的 14 号撞了）。
- 这一轮没合：#54 vivo X Fold6（10-28 要求改的两处还没改）、#61 适配辅助工具、#32 小米专属优化模块（超出范围）。
- **魅族 21 Pro（Flyme 12.6.0.0A / Android 16）机型脚本**（#275）：系统应用跟踪、全局搜索、浏览器、应用商店、主题、天气、手机管家、锁屏画报。只在型号和系统版本完全一致时操作，其他版本每段停下；遇到协议或权限申请、小窗里有别的应用就停；只关点名的开关，处理确认框后回读。贡献者真机分段验证，整段自动跑待验证。魅族不在同品牌参考表里，其他魅族机型不借用这份脚本。
- **华为 ALN-AL00（HarmonyOS 4.2.0.223）营销通知命令行工具**（#332，`tool/huawei_channels.py`）：按人工审核过的清单，在应用通知页里逐个点渠道复选框；每一步核对清单外渠道和应用总开关有没有变，变了就停；点复选框时系统顺带把应用通知权限从 default 改成 allow，退出时只把这一项改回去；改前存快照。合并时调整：不注册成机型脚本（原 PR 是 `recipes/huawei-ALN-AL00/`）。当成机型脚本时没有清单就报失败，Mate 60 Pro 用户在客户端里每次都会多一个失败步骤；现在客户端不会自动运行它，用法见 [华为-ALN-AL00-营销通知](../清单/华为-ALN-AL00-营销通知.md)。

## 0.2.8 · 2026-10-30

0.2.7 之后 Rikki Lv 的修复与重构（#205 #192 #194 #287 #292 #293，统一「行」和「等页面」的写法，PR 自动跑回归和静态检查），加上 vivo 转场慢的修复。

| 现象 | 来源 | 处理 |
|---|---|---|
| vivo「点这一行后页面没变；标题顶部」：0.2.7 的 91 份上报里 vivo 38 份，这句出现 212 次 | 错误日志 10-30 | 「标题顶部」说明跳过时渠道页已经打开：vivo 转场慢，`settle` 没等到页面变化就放弃了。vivo 改为照常认页（顶栏是渠道名、不同于刚记下的 App 名、只有一个「允许通知」开关），认不出才算没变；别的品牌不变，避免把应用总页的开关当成渠道开关。没有 vivo 真机，模拟页面回归 |
| 复用外部 adb server 时，用户按提示关掉自带 adb 的工具（Iriun Webcam 等）后整轮中断，后面三段连报「本机没有安装 xxx」 | [#293](https://github.com/rddmwmddr/android-ad-cleaner/issues/293) | 客户端连的是 `127.0.0.1:5037`，对方先起的 server 被复用，对方退出后连接彻底消失，而 `pm path` 在断连时同样没有输出。`start()` 启动失败且 `pm path` 无包名时先分辨：命令输出里带 adb 客户端错误（`device … not found` 等）或手机已不在设备列表（`adb_link.present()`）就报「adb 连接断开」并附排查说明，不再报成没装。首次确认断连后本轮记下状态，剩下的机型脚本段立刻跳过、只报一句「连接已断开」，不再逐段等重试或逐段误判。没有能复现的外部 adb server 环境，仅单元回归 |
| 「拨了 N 个」把没确认、点不动的项也算了进去，看不出实际拨动了几个 | 内部重构 | 渠道批处理的结局改成显式值（`Outcome`：已关好 / 系统锁定 / 应总开关关 / 页面没认出 / 点错开关 / 断开 / 锁屏…），算不算失败、要不要重试由一张表决定，不再靠人话字符串前缀判断结局。逐项输出文案和退出码口径不变；「拨了 N 个」改为实际处理成功的项数（第二遍重试成功的也算，失败的、没确认的不再计入） |
| OPPO Find X8s（PKT110 / ColorOS 17）游戏中心报「未找到入口「设置」」；同一份日志每次还有一行「✗ 没找到「隐私」」，随后广告跟踪正常 | [#292](https://github.com/rddmwmddr/android-ad-cleaner/issues/292) | 游戏中心 14.43.3 把「设置」做成「我的」页右上角的齿轮图标，没有文字，脚本按文字找必然失败。新增 `Phone.tap_icon()`：在右上角区域找没有文字的可点图标（按 x 从右往左），点完要求新页出现「隐私开关设置」或「隐私」（**精确匹配**，页面上本来就有「隐私政策」时不能算点对）才算成功；最多等 2.4 秒看页面画出来，不是目标页就退回原页换下一个，全失败打印当前页文字。`oppo-PKT110` 与参考脚本 `oppo-PLP120` 都是文字优先、图标兜底；「我的」也改成会校验的 `p.tap()`。广告跟踪段改为先找「隐私与安全」再退回「隐私」，不再先白翻一轮、打一行失败。没有 ColorOS 17 真机，仅单元回归 |
| 华为 Mate 50（CET-AL00，HarmonyOS 4.2.0.220，底层安卓 12）应用通知页里渠道名和分组名同名，5 个渠道报「这一行的开关没认出」，整批在误点「运营活动」后停止 | [#287](https://github.com/rddmwmddr/android-ad-cleaner/issues/287) | `inline_switch` 以前只要同名文字出现两处就放弃。现在逐个候选按同一套条件判定（行里恰有一个开关、行高不超过屏高 20%、行内没有应用总开关），只留合格的行：恰有一行合格就用它，两行都合格仍然放弃、不猜。跳过时 `why` 带上第一行的原因和控件链，下一次上报能直接看到结构。分组名与渠道名同名是推断（日志只有手数与开关数），没有华为真机，需反馈者用下一版复测 |
| 第 2 步「改动前快照」在小米 15 / HyperOS 4 上三个包列表文件是 0 字节、命令却报成功；`check` 里以前手工 `pm disable-user` 关过的快应用被判成「未关闭」 | [#192](https://github.com/rddmwmddr/android-ad-cleaner/issues/192) | 这台 ROM 上 `pm list packages` 任何参数都无输出且 exit 0。新增 `pkg_list()`：`pm list` 读不到包名时回退 `cmd package list packages`（参数相同），快照的 sys / user / disabled 三份清单和 `quickapps()` 的已禁用集合都走它。`backup` 先用不带参数的完整清单探活（带过滤参数的清单本来就可能为空），两条通路都读不到包名时报失败、不留半成品快照目录；快照里保留手机返回的报错原文，便于排障 |
| 纵横小说同一渠道在清单里出现两行，差别只是渠道 ID 和名称末尾的空格；带空格那行「未确认」，收尾误报「营销渠道仍开着 1 个」 | [#194](https://github.com/rddmwmddr/android-ad-cleaner/issues/194) | 读系统回读时渠道 ID、渠道名都去掉两头空格，按（包名、渠道 ID）合并成一条；已删除的重复记录不覆盖有效记录。读清单时同样去空格并按渠道去重，旧清单也能用，收尾按渠道计数 |
| 「关闭营销通知」在 HyperOS 3 / Android 16 跑到第 19 条左右整段中断，报 `AdbError: shell output invalid` | [#205](https://github.com/rddmwmddr/android-ad-cleaner/issues/205) | 读锁屏、焦点窗口、通知权限的 `dumpsys` 管道末尾原来用 `grep -m4` / `grep -m1` / `head -12`，读够就退出，`dumpsys` 收到 SIGPIPE 后往输出里写 Broken pipe，adbutils 找不到结束标记便抛异常。现在改成 `grep` 过滤后由 `sed -n` 截断，它会读完整个输入再输出，行数和取首行的语义都不变。REDMI K80 / HyperOS 3 报告者实测去掉 `-m1` 后 71 条渠道全部关闭 |
| 同一件事「开关所属的那一行」有三处定义（固定 6 层、列表直接子项、行内唯一开关容器），华为 / 旧版荣耀的卡片布局只在其中一处修好过 | 内部重构 | `tool/row.py` 收下唯一定义：结构上从起点往上到可点 / 可勾选的控件、或滚动列表的直接子项为止，行里不止一个开关时再收窄到最内层（`line` / `own`）；平铺列表没有容器可分，标题按竖直距离分带（`title_of`）；控件链数据（`path`）。`fast.switch_row`、`Phone.switches()`、`chan_fast.inline_switch` / `via_app_page` 都改为消费它，不再各修各的。逐项输出文案与退出码不变；对 40 个现有页面样本（每个跑 1080×2340 与 1168×1712 两种屏尺寸）改前改后逐字对拍，`switches()` 结果、行归属、控件链全部一致，唯一变化是列表子项里的开关行不再被当成导航行——`switch_row` 在 3 个现有布局的 7 个文字节点上由假变真，`tap` 不会再去点开关的说明文字 |
| 「页面还没画出来」有九段各自为政的等待循环（六个调用点，`setting` 一段里就有四段），预算从 0.8 秒到 8 秒、判据六种，慢机型上的失败改一处修不到别处 | 内部重构 | 新增 `tool/wait.py` 的 `until(sample, timeout 或 tries, poll, stable, same, changed_from, blocked)`：预算、轮询间隔、稳定判据都是参数，采样器由调用点提供。`settle`、`tap_icon` 认页段、`setting` 的四段、`off` 开头等开关、`wait_page`、`via_app_page` 认页共九段改为共用它；锁屏由 `blocked` 采样器转成 `ScreenLocked`，「这一页永远认不出来」由采样器抛 `GiveUp` 立刻结束，`wait.py` 不依赖 `fast` / `chan_fast`。预算分两种，按各调用点原来怎么数的选：`timeout` 是挂钟秒数，`tries` 是采样次数。`settle` / `tap_icon` / `setting` 原来用挂钟，`wait_page` / `off` / `via_app_page` 认页原来数轮次——数轮次的这几处不能改成秒，慢机型一轮读屏更久，按秒算会把等待缩短、反而更容易失败（一轮读屏 0.5 秒时 `wait_page` 旧实现能等 8.4 秒，换算成 2.4 秒就只剩 4 轮）。五段等待里夹着副作用的循环（`go`、`tap(scrolls=0)` 的 3 秒、`start()` 的三处共 16 秒、`wait_unlocked`、`via_app_page` 的翻页）故意不收，理由写在模块 docstring。逐项输出文案与退出码不变。对拍：基线提交的 `tool/` 原样导出，同一份页面时间轴双跑。页面样本取 `tests/` 里 51 份 `<hierarchy>…</hierarchy>` 字面量中可解析的 50 份（1 份是故意造的非良构 XML），每份跑 1080×2340 与 720×1600 两种屏尺寸共 100 组，另加 10 组「页面一直不换」，`settle` 110 组判定全同、28 组早 0.1 秒（旧实现先睡后采）；`wait_page` 11 组（含每次读屏 0 / 0.25 / 0.5 秒三种慢读屏）、`via_app_page` 6 组、`tap_icon` 3 组、`setting` 3 组、`off` 3 组，返回值、读屏次数、点击次数、耗时逐项一致。已知差异只剩两处：`tap_icon` 到期那一轮不再多读一次屏（每个候选 5 次 → 4 次）；`settle` 首次采样提前 0.1 秒 |
| `CLAUDE.md` 里 90 行日期化记录与 `CHANGELOG.md` 同源、每轮都进 agent 上下文；纯重构要求「对拍证据」而仓库里没有材料；静态检查只有 CI 的单元测试一层 | 内部重构 | `CLAUDE.md` 只留会改变 agent 行为的指令（回归命令、CI 范围、审查标准、`row.py` / `wait.py` / `fixtures.py` 导航、发版步骤），逐次处理记录统一指向本文件。新增 `tests/fixtures.py`：`all_pages()` 从 `tests/` 现抽页面样本、假时钟、按时间轴换页的假设备、`fake_phone()`，同类对拍脚本从 250 行缩到 20 行。CI 加 `ruff check --select F,E9 tool tests gui`（`recipes/` 靠注入作用域执行，静态分析全是假阳性，排除），顺手清掉 `tool/fast.py` 与 `gui/shots.py` 各一处未使用导入。不改产品行为，385 项回归全过 |

## 0.2.7 · 2026-10-29

按 0.2.6 发布后收到的 101 份错误日志（当天 33 份、当夜 68 份）和 GitHub 新问题修复；新增软件名、暂停、提示音、新版本提示；合并 8 个社区 PR。

### 10-28：0.2.6 当天的上报

0.2.6 发布后 4 小时收到 33 份 0.2.6 的错误日志，来自 33 台电脑；同期 GitHub 下载约 3150 次。同一时间 0.2.5 又报了 21 份，这些问题 0.2.6 已修，旧版不会自动更新。

| 现象 | 份数 | 原因 | 处理 |
|---|---|---|---|
| 华为（HarmonyOS 4.0 / 4.2、EMUI 10.1，底层是安卓 10 / 12）和旧版荣耀（YOK-AN10、CDY-TN90）每个渠道都「这一行的开关没认出」 | 9 | 0.2.6 能找到渠道名所在的列表项，但列表项里不止一个开关。推断是几个渠道排在同一张卡片里 | 从渠道名往上找第一个含开关的控件，只含一个开关才用；开关自己的无障碍标签也是渠道名时不算重名。还认不出时，日志附上从渠道名往上的控件链（类名、可点、开关数），不含页面文字。没有华为真机，需要反馈者复测 |
| 大部分渠道关了，剩一两个「未确认」，整步算失败 | 9 | 页面加载慢，一次没认出就放弃（OPPO Find X9 关了 67 个剩 1 个，红米 Note 12 Turbo 关了 93 个剩 1 个） | 一批跑完后，没确认的渠道再试一次。这台手机已经关成功过才重试，最多 10 个；一个都没认出的不重试 |
| vivo「点这一行后页面没变；标题顶部」 | 5 | vivo 直达的渠道页按规则不能直接用，要回应用通知页再点进去；两页是同一个页面类型，切回去时读到的还是上一页 | 等上一页换下去再读；认出是 vivo 后不再走直达链接，每个渠道少等十几秒（一台 vivo 27 个渠道用了 13 分钟） |
| vivo OriginOS Ocean（安卓 10）「应用通知页没有打开」 | 1 | 通知页挂在 `com.android.systemui` 下，程序不认识 | 认这个包下的同一个 Activity，读它的页面文字 |
| 用户点了停止，日志记成失败 | 4 | 营销通知刚开始时只显示「正在连接手机读屏服务」，看着像卡住；停止的步骤当成失败，完成页提示上报 | 停止的步骤记为「已停止」，不提示上报；停止后仍跑「收尾」改回插电常亮（以前停止会让手机插电时一直亮着）。连上读屏服务后先打一行「要处理 N 个渠道」 |
| 没执行任何步骤就上报 | 6 | 从「反馈问题」里点了上报，报告只有手机型号 | 没有执行记录时客户端不发送，提示到 GitHub 反馈。旧版客户端仍能发空报告，服务器暂未拦 |
| 手机断开时带着 Python 报错堆栈 | 2 | 读屏库的 `HTTPError: device not found`、`AdbShellError: closed` 不是 RuntimeError，没被认成断开 | 认成「手机断开」，只打印排查说明 |
| 全部成功也上报了 | 2 | 从「反馈问题」里上报 | 不改 |

### 新功能

- **营销通知清单显示软件名**：以前只显示包名，用户认不出是哪个软件。扫描时在手机上运行一个 3 KB 的读名程序（`tool/applabels.dex`，源码 `tool/applabels/Labels.java`），按包名取手机上显示的应用名，跟随系统语言，用完删除；读不到时显示包名。软件名只在界面和清单文件里，不写进日志，上报的错误日志仍不含应用列表。
- **暂停**：执行中要用手机时点「暂停」，手头这个渠道、机型脚本的这一段或这一步做完后停下，提示「已暂停」再拿手机；点「继续」后重新读屏幕再往下走。
- **新版本提示**：启动时查一次官网的版本文件（读不到查 GitHub），有新版在左下角提示，点了打开下载页。请求只带客户端版本号。
- **提示音**：执行结束、暂停生效、手机锁屏要解锁时响一声：两个柔和的音（E5 → A5），不到 1 秒，峰值约 -11 dBFS。音由 `gui/make_chime.py` 合成，Mac 用 `afplay`、Windows 用系统自带的 `winsound` 播放；几件事挤在一起时 3 秒内只响一次。
- **adb 下载换源**（[#273](https://github.com/rddmwmddr/android-ad-cleaner/issues/273)）：以前只从 Google 官网下，下不了就卡住。现在固定版本 platform-tools 37.0.1 先从 Google 官网、再从腾讯云镜像下，下完核对 SHA-256（校验值按 Google 官方清单核过，两处文件一致）；都失败才从官网下最新版。

### 10-29：0.2.6 一夜的上报和 GitHub 新问题

0.2.6 又收到 68 份上报（64 台电脑），大部分是上面已修的几类：vivo「点这一行后页面没变」14 份、华为 / 旧版荣耀 10 份、停止 10 份、空报告 7 份、断开 7 份。新出现的：

| 现象 | 来源 | 处理 |
|---|---|---|
| `tap 隐私` 点中「边下边玩」的说明「不涉及隐私数据」，把功能关了 | [#247](https://github.com/rddmwmddr/android-ad-cleaner/issues/247) | 先找文字完全相同的；包含匹配时跳过开关所在行的文字（那是开关的说明，点了等于拨开关） |
| 三星 9 个渠道「界面状态与渠道实际状态不一致」，渠道页开关显示关、记录仍开 | 上报 3 份；华为 [#241](https://github.com/rddmwmddr/android-ad-cleaner/issues/241) 同样现象 | 推断是这个应用的通知已整体关闭（安卓 13 起是通知权限）。查到权限是关的，记为「应用通知已整体关闭，渠道不会弹出」，不算失败；查不到仍报不一致 |
| 华为 HarmonyOS 4.2、vivo OriginOS Ocean「停在 未知页面」，页面明明在 | 上报 2 份 | 焦点窗口为空时改看 `mFocusedApp` 和多种 resumed 行 |
| 一加 13「福利活动 」找不到 | 上报 1 份 | 渠道名两头的空格去掉再比 |
| 海信 Android 9「读不到通知渠道状态」 | [#258](https://github.com/rddmwmddr/android-ad-cleaner/issues/258) | 安卓 8 / 9 的段名是 `per-package config:`，按 AOSP 9 的输出格式补上。没有安卓 9 真机 |
| 小米打开「USB 调试（安全设置）」后检测仍说点击被拒 | [#217](https://github.com/rddmwmddr/android-ad-cleaner/issues/217) [#245](https://github.com/rddmwmddr/android-ad-cleaner/issues/245) [#251](https://github.com/rddmwmddr/android-ad-cleaner/issues/251) [#257](https://github.com/rddmwmddr/android-ad-cleaner/issues/257) [#266](https://github.com/rddmwmddr/android-ad-cleaner/issues/266) | 提示里加上：打开时等倒计时点「确定」；仍被拒就拔插数据线，再不行重启手机（#217 有人重启后恢复） |
| vivo 阅图锁屏「关不掉」：确认框按钮文字在 content-desc | [#246](https://github.com/rddmwmddr/android-ad-cleaner/issues/246) | 合并 PR #249；同时合并 #239（文字在按钮子节点）、#248（跳过屏幕外的旧按钮）对 `confirm()` 的修改 |

华为 #241 的反馈者在 NAM-AL00 上逐行核对：渠道行里标题和开关的 content-desc 都是渠道名，按所在行去重后能找到唯一的开关。这和本版华为的改法一致，自动流程仍待华为用户复测。

### 社区机型脚本

合并 8 个 PR：荣耀 WKL-AN20 MagicOS 11（#262）、OPPO Find X8s PKT110 ColorOS 17（#248）、小米 17 Ultra 标准版（#243）、一加 13T PKX110（#237）、小米 Pad 7（#232）、小米 13 Ultra（#231），vivo 参考脚本 V2547DA 在 OriginOS 6 真机整段跑通（#239），确认框按钮修复（#249）。脚本由贡献者在自己的手机上录制。#239 合并时改了两处：浏览器菜单按钮最多等 3 秒（别的 vivo 型号借用这份脚本时可能没有这个按钮，原写法要等 20 秒）；去掉商店页的「开启，开关」关键词。

realme GT5 Pro 的实测差异和桌面上滑「看点」的关法记进了 OPPO 清单（#271）。

285 项设备无关回归通过。Android 15 模拟器：读名程序以 shell 身份读出系统和第三方应用的中文名（设置、日历、信息和一个中文名的第三方应用），7 个包不到 1 秒；扫描输出带软件名，读名程序用完已删除；关闭、暂停、继续、还原一个测试渠道，回读一致。华为、旧版荣耀、vivo 的修改没有真机。

## 0.2.6 · 2026-10-28

0.2.5 上线一天收到 122 份用户确认上报的错误日志（Windows 111 份，Mac 11 份）。「关闭营销通知」一步失败 90 份，按原因归类后逐类处理。

| 现象 | 份数 | 原因 | 处理 |
|---|---|---|---|
| 只剩一个「系统锁定（开关是灰的）」的渠道，整步标成失败 | 23 | 灰色开关不能关，仍计入「仍开着」 | 说明是系统锁定，不算失败；识屏「内容提取」、三星「内容已传输」等功能通知不再列入扫描 |
| OPPO、一加、realme 从第一个渠道起全部「停在 NotificationShade」 | 9 | ColorOS 16 / 17 没有 `isKeyguardShowing` 字段，锁屏没被认出 | 焦点在通知栏窗口时按锁屏字段判断，字段都没有就按锁屏处理；只是通知栏被拉下来时自动收起 |
| 开始执行时手机已锁屏，后面每一项都报「手机锁屏了」 | 约 15 | 等待连接、选择时手机自动锁屏 | 点亮屏幕，等机主解锁，最多 90 秒，解锁后自动继续；中途锁屏同样等一次，仍锁着就停下整批，只说一次 |
| 断线后快应用、挂起、收尾每一步各打一遍排查说明，日志里夹着 Python 报错堆栈 | 约 20 | 每一步各自发现断线；引擎没接住读屏服务启动失败 | 手机确实断开时，后面的步骤不再执行，只说一次；读屏服务传不进手机、命令无回应、读屏被占用都给出原因，不打印堆栈；读屏占用先等 20 秒 |
| vivo OriginOS 3 / Android 13 全部「未确认」 | 3 | 焦点行以 `Activity}}` 结尾，取到的 Activity 多了一个 `}` | 修正解析 |
| 华为 HarmonyOS 4 停在应用通知页 | 13 | 渠道行不可点，由列表处理点击；以前一直往上找可点的控件，找不到就放弃 | 找到列表的直接子项为止。没有华为真机，需要反馈者复测 |
| 小米 msa「部分完成：本系统不支持断网接口」标成失败 | 7 | 系统没有这个接口，用户改不了 | 挂起成功就不算失败，说明只做了挂起 |

「未确认渠道页」的日志现在附上卡在哪一环（深链没打开 / 应用页没找到这一行 / 点进去没认出渠道页）和页面结构（标题位置、开关数量），不含页面文字，下次适配用。

**隐私**：一份报告的程序在 `E:\…\Users\<名字>\` 下（用户目录被挪到了别的盘），客户端和服务器的脱敏规则都没盖住。两边规则改为任何盘、任何前缀下的 `Users\名字`、`/home/名字` 都替换；库里那份报告已改写。华为系统版本号 `4.2.0.180(…)` 不再被当成 IP。

没有本型号脚本时用的同品牌参考脚本固定为维护者实测的那一份，社区新增机型不再改变别的手机用的参考脚本。

### 社区机型脚本

合并 10 个 PR，新增 9 个机型脚本和一份差异记录。脚本由贡献者在自己的手机上录制，维护者没有对应真机。

| 机型 | 型号 | 系统 | PR |
|---|---|---|---|
| REDMI K80 至尊版 | 25060RK16C | HyperOS 2 / Android 16 | #204 |
| REDMI K90 Pro Max | 25102RKBEC | HyperOS 4 / Android 17 | #152 |
| Redmi K70 | 23113RKC6C | HyperOS 3 / Android 16 | #107，记录见 [docs/13](../13-红米K70实测.md) |
| Redmi Note 14 Pro | 24090RA29C | HyperOS 3 / Android 16 | #72 |
| Redmi Note 12 Turbo | 23049RAD8C | HyperOS 3 / Android 15 | #27 |
| vivo X300 Ultra | V2547A | OriginOS 7 / Android 17 | #10 |
| iQOO | V2324HA | Android 16 | #198 |
| vivo | V2361A | OriginOS / Android 16（引擎整段未跑） | #100 |
| 一加 Ace 2 | PHK110 | ColorOS 16 | #15 |
| 一加 Ace 5 | PKG110 | ColorOS 16（只有差异记录） | #3 |

V2547A 以前用 V2547DA 的脚本，现在用 #10 的专用脚本。#10 清单里整包关通知（`notif-off` / `pm revoke`）的写法删掉了，原因同 #20：订单、聊天提醒会一起关。

**验证**：204 项设备无关回归通过（本节新增 28 项，#107 另带 6 项）。Android 15 模拟器：滑动锁屏下开始执行，提示解锁、解锁后继续；通知栏拉下时自动收起；系统锁定渠道不算失败；关闭、还原后回读与原值一致。

## 0.2.5 · 2026-10-27

新增错误日志上报：执行失败时，不需要 GitHub 账号也能把日志发给维护者。

- 入口：完成页「有步骤没成功」里的「上报错误日志」，以及「反馈问题」窗口里的按钮。
- 发送前原样展示要发送的全部内容，点「确认上报」才发送；成功后给出报告编号，凭编号可以申请删除。
- 内容与「复制完整诊断」同源：客户端版本、电脑系统、手机型号和系统版本、各步结果、日志末尾，以及一个随机安装编号。客户端和服务器各替换一遍序列号、用户目录、邮箱、手机号、IP；不含应用列表、通知内容、账号信息。
- 服务器端：上报通道使用只能写入的低权限账号；客户端每小时最多 3 次，服务器另按 IP 和安装编号限频；IP 只存哈希；保存 90 天。说明见 [错误日志上报](../12-错误日志上报.md)。
- 0.2.4 的修复全部保留。

**验证**：170 项设备无关回归通过（新增 8 项：脱敏、预览与发送一致、长度上限、本地限频、安装编号、服务器拒绝与超时提示、重复报告）。线上服务完成越权、限流、超大请求、字段校验和真实客户端写入测试，测试记录已删除。

## 0.2.4 · 2026-10-27

10-26 至 10-27 收到 140 多条 Issue。按日志归类，失败集中在下面几类，本版逐类处理。没有对应真机的机型，只按反馈者提供的页面结构修改，需要反馈者更新后复测。

### 营销通知

| 现象 | 原因 | 0.2.4 的处理 |
|---|---|---|
| OPPO、一加、realme（ColorOS 16 / 17）全部「未确认渠道页」（#37 #63 #76 #91 #123 #149 等） | 渠道页由 `com.oplus.notificationmanager` 承载，0.2.3 只认包名里带 settings 的页面 | 按实测 Activity 识别（一加 Ace 2 Pro 实测，#165 Find X9 Ultra / ColorOS 17 社区实测） |
| 荣耀 MagicOS 10 / 11 全部跳过（#80 #86 #99 #106） | 渠道页由 `com.hihonor.systemmanager` 承载 | 采纳 #86 的实测 Activity；华为 EMUI / HarmonyOS 4 与旧版荣耀按同一结构识别，未经实测 |
| 荣耀 Magic6 等渠道平铺在应用通知页（#99） | Android 16 内联布局：每个渠道一行，自带开关 | 只认标题与渠道名完全相同、全页唯一的一行，取这一行唯一的开关；应用总开关不会命中 |
| 三星 One UI 全部跳过（#42 #69 #95） | 渠道名在页眉控件里，位置低于原来的判定线；开关只在 content-desc 上写「允许通知」 | 认 `entity_header_title`；开关按自身标签识别 |
| 「界面状态与渠道实际状态不一致」（#53 #98 #104 #144） | 双开、分身、隐私空间、安全文件夹里同一个 App 的通知状态混进了回读（#95） | 只读机主空间（user 0） |
| 三星部分渠道 ID 显示为 `com.se...`（#95） | 系统输出时缩略了 ID | 扫描不列入，并提示数量 |
| vivo / iQOO 全部报「会影响整个 App」（#41 #43 #45 #48 #83 #159） | vivo 的应用通知总页和单个渠道页是同一个 Activity，0.2.3 整个拒绝 | 总页（顶栏是 App 名，「允许通知」管整个 App）仍不点；从总页点进渠道行，顶栏是渠道名且不同于 App 名时才操作。vivo 的渠道行带 checked，不按行内开关处理。X300 Ultra / OriginOS 6 真机通过 |
| 系统锁定的渠道一直「点击后状态未改变」（#134） | 系统应用固定了通知权限，渠道开关是灰的 | 扫描不列入；遇到灰色开关直接说明，不连点 |
| 「未确认渠道页」看不出停在哪 | 日志只有渠道名 | 附上当前页面的包名 / Activity，不含页面内容 |

小米「“钱包”正在其他应用的上层显示内容」是悬浮窗提示，名字里带「内容」被扫描选中，又因渠道状态读不到而让整步报失败（#115），现在不列入。关闭后的复查列出仍开着的渠道名，以前只有数量。

点击后除了核对目标渠道和应用总开关，也核对同一 App 的其他渠道：清单之外的渠道跟着变了，就在原位置点回去，并停止整批。

### 小米 / Redmi / POCO

大量「没找到」「点击后渠道状态未改变」、中途锁屏（#31 #47 #50 #51 #71 #129 #130 #143 #153 等），日志特征与未开「USB 调试（安全设置）」一致：能读屏，点击和写设置被拒。检测页先发一个空按键试探，被拒就提示打开这一项，暂不进入下一步；引擎点击时遇到 `INJECT_EVENTS` 拒绝也直接说明原因。

锁屏判断原来在 `isKeyguardShowing` 那一行里找任意 `true`，HyperOS 3 这一行有其他字段为 true，全程解锁也被判成锁屏（#115 跟帖）。现在只认 `isKeyguardShowing=true`。

### 连接

- 执行中途 `device not found`（#126 #127 #140 #147 #150 #158）：等手机回来重试一次；仍断开就停在这一步，提示退出手机助手 / 模拟器、换线换口。以前断开后读到空结果，快照目录名变成「-日期」，快应用显示「没有检测到」，收尾也显示成功。
- 营销通知一步改开关前设插电常亮，结束后改回原值（以前只有机型脚本设置，#71）。设不上时提示调长锁屏时间。
- Windows 等不到手机时，只读查询设备管理器，区分「没有调试接口」「调试接口缺驱动」「接口在但 adb 没连上」，并给出荣耀 / 华为「仅充电模式下允许 ADB 调试」、三星 USB 驱动等提示（#57 #58 #65 #118 #125 #135 等）。
- 电脑上只有 1.0.32 等旧版 adb 时不再使用（#25 #75），改为提示下载官方 adb。
- 诊断里增加 adb 设备数量与状态（不含序列号）、其他正在运行的 adb 路径。

### 机型脚本

- 同品牌参考脚本里的 App 本机没装时，说明「本机没有安装」，不报成打开失败（#74 #165）。
- OPPO：ColorOS 17 设置首页叫「隐私与安全」时改走这条路径；浏览器切成简洁首页、没有「我的」和菜单时，在浏览器前台直达设置页（#165）。
- 荣耀：设置搜索框打不开时，按「隐私和安全 → 其他隐私和安全功能 → 广告与隐私」进入（#88 #99）；没有 `com.honor.browser` 的机型改用 `com.hihonor.baidu.browser` 的消息设置和隐私设置，网页形式的「广告设置」提示手动处理（#87）。

### 真机验证中发现并修复

- 找入口时顺手关弹窗，会点到列表卡片上的 ✕（Find X10 Pro Max / ColorOS 17 隐私页「关闭提示」），结果打开「权限建议」用户须知，后面的入口全部找不到。现在只点列表外浮层里的 ✕；拒绝类按钮加上「不同意」，遇到用户须知不替用户同意。
- 荣耀 PNM-AN10（10.0.0.102）设置搜索框换成 `AutoCompleteTextView`，以前只认 `EditText`，判成「设置搜索框没打开」。现在两种都认。
- 安全模式下页面找到了、只是不整页全关时，日志以前写「本页未找到目标开关」，现在写明「安全模式不做整页全关，本页 N 个开关未改动」。
- 快应用组件之前被手动 `disable-user` 停用的，检测结果以前显示「未关闭」，现在算作已关闭。

### 反馈与安装包

- Windows 复制诊断不再乱码（#33 #50 #128）：直接写 Unicode 剪贴板，以前经 PowerShell 按 GBK 解码。
- 诊断较长时，反馈网址里带上手机、系统、各步结果和日志节选，完整内容另放剪贴板。以前网址里只有一句「请粘贴」，很多 Issue 只剩标题。
- Mac Intel 版（#103）：0.2.0–0.2.3 误用按 macOS 26 编译的 Homebrew Python，低于 macOS 26 的 Intel Mac 打不开。改用 uv 自带的 Python（最低 macOS 10.15），Info.plist 写明最低 macOS 11，打包时逐个检查包内文件，有高于 macOS 11 的就停止构建。

**真机验证**（2026-10-27，无线调试，测试后状态与测试前一致）：

| 机型 | 结果 |
|---|---|
| OPPO Find X10 Pro Max（PMX110），ColorOS 17 `PMX110_17.0.0.114(CN01)` | 渠道页确认为 `com.oplus.notificationmanager/.ChannelNotificationSettingsActivity`。Edge「突发新闻」`ON → off → ON`、天气「内容与营销」`off → ON → off` 通过，两个 App 全部渠道与应用总开关的回读与测试前一致，插电常亮恢复为 0。浏览器简洁首页下直达设置页成功；广告跟踪段经「隐私与安全 → 设备标识与广告」进入 `OAIDActivity`，安全模式下未改动开关 |
| vivo X300 Ultra（V2547DA），OriginOS 6 `PD2547D_A_16.0.22.14.W10` | 支付宝「运营消息」`off → ON → off` 通过，回读与测试前一致，插电常亮恢复为 0。调试中发现两处并修复：渠道开着时渠道页会多出静默、振动等开关，不能用开关数量区分总页；直达页未退出时会读到上一页标题，App 名改为在总页列表里找到渠道行的同一次读屏中记录。测试中途有一次把支付宝「运营消息」留在了开启状态，已关回 |
| 荣耀 PNM-AN10，MagicOS 10 `10.0.0.102` | 渠道页确认为 `com.hihonor.systemmanager/com.hihonor.notificationmanager.ui.NotificationSettingsActivity`。夸克「新闻推送」、淘宝「营销通知」（同 App 有两个同名渠道）`off → ON → off` 通过，回读与测试前一致，插电常亮保持原值 7。原机脚本「广告跟踪」「浏览器」两段调整 0 项；设置搜索修复后直接进入「广告与隐私」 |

**验证**：162 项设备无关回归通过，新增 39 项覆盖上述反馈（荣耀 / 三星 / 华为页面身份、内联开关、多用户回读、缩略 ID、系统锁定渠道、点错后点回、小米点击被拒、锁屏误判、列表内 ✕ 与用户须知、AutoCompleteTextView 搜索框、adb 掉线重试与停止、插电常亮、USB 提示、旧版 adb、诊断脱敏）。Android 15 模拟器上，新代码的读屏检查、营销渠道扫描（排除 1 个系统锁定渠道）、`ON → off → ON` 通过，服务渠道和应用总开关不变，插电常亮原值 0 与 7 都能恢复；未连接设备时 15 秒后停止并给出连接提示。

安装包验证：Windows [Actions #40491070922](https://github.com/rddmwmddr/android-ad-cleaner/actions/runs/40491070922)（代码 `4fdc39e`）通过回归、PyInstaller 打包、两层 CLI 与原生 GUI 冒烟、安装程序和免安装包生成，包内脚本与源码一致。Mac Apple 芯片与 Intel 两个包：Developer ID 签名、公证、Gatekeeper 通过，最低系统版本 macOS 11 且包内没有更高要求的文件；原生 GUI 冒烟、模拟器读屏检查通过（Intel 在 Rosetta 下），包内脚本与源码一致。Intel 真机待用户反馈。

**支持边界**：ColorOS 17 与荣耀 MagicOS 10 的渠道页已在上表两台真机验证；荣耀 PTP-AN00 / Magic6 的内联渠道行、三星 SM-S9420 的修改依据是反馈者的实测记录；华为、旧版荣耀、荣耀平板的渠道页识别、荣耀百度浏览器路径没有真机验证。vivo 只在 OriginOS 6 真机验证，OriginOS 3 / 7 待复测；渠道名与 App 名相同时无法区分总页，跳过。小米其他机型的「没找到」在打开安全设置后若仍存在，属于脚本路径差异，需要按型号补脚本。原生鸿蒙（HarmonyOS NEXT）、三星 / 魅族 / 摩托罗拉等品牌的机型脚本尚未提供。

## 0.2.4 收录 · 读屏冲突排查与找机位通知保护

2026-10-26 用户反馈：0.2.3 仍无法读屏，同时关闭 GKD 和自动记账后可以继续；另报小米 18 Pro 系列“找机位通知”被误关。**以下改动随 0.2.4 发布。**

- 修正“无需关闭无障碍服务”的绝对表述。读屏连接失败时只读检查无障碍总开关和服务数量，限时 3 秒，不收集服务名单到诊断；读取失败仍保留原始异常。
- CLI、客户端读屏检查和完成页明确提示逐项排查 GKD、自动记账等自动化 / Shizuku 功能；必要时由用户暂时停用对应服务，保留依赖的辅助服务，结束后按需恢复。程序不会自动关闭无障碍、强停其他工具或重启手机。
- 找机位、机位推荐等功能通知加入保护：扫描、GUI 全选、旧清单执行和点击前复核均覆盖；受保护项目不计入剩余营销渠道。已有关闭状态不会被自动开启，但明确执行的单渠道还原仍可用。
- Mac 与 Windows 均通过 123 项回归，原生 GUI 冒烟增加模拟失败排查卡片的显示检查；Windows [打包验证](https://github.com/rddmwmddr/android-ad-cleaner/actions/runs/40213007991)通过，未上传 Release。真实包名 / 渠道 ID 和反馈设备复测仍待补充，不能将用户同时暂停两个工具后的成功写成某一个工具根因已确定。

排查顺序、实现边界与误关恢复方法见[读屏冲突与功能通知保护](../11-读屏冲突与功能通知保护.md)。

## 0.2.4 收录 · 一加 ColorOS 14 实测与兼容修复

2026-10-25 在一加 Ace 2 Pro（PJA110）、`PJA110_14.0.0.812(CN01)` / Android 14 上完成实机操作与回读。**以下改动随 0.2.4 发布。**

- 修复 ColorOS 14 独立通知设置页识别；仍核对渠道标题、明确开关，禁止操作应用通知总开关。23 个营销渠道关闭并回读通过，混合付款、直播和含糊渠道保留；新增中英文付款渠道排除回归。
- 新增 `recipes/oneplus-PJA110/recipe.py`：下拉搜索、商店个性化、商店推广位、浏览器四段。3 个个性化推荐开关关闭，机主联网后再关闭并跨页回读 6 个商店推广位，其他服务开关保持原样。
- 首屏少量文字不再视为空白广告；冷启动空白最多等待 8 秒，不盲按返回。读取及弹窗处理前后核对前台，系统权限申请只点明确的拒绝按钮。
- 商店沿用先停止再从桌面启动的方式，浏览器使用实测 Activity，避免复用旧子页；以实际前台核对设置入口。脚本缺目标或回读失败时返回非零，已成功改动日志仍保存。
- 经机主明确同意，挂起 OPPO 广告服务、乐划锁屏和两个快应用组件，并核对状态。旧系统会重新拉起部分进程，收尾广告服务仍运行，不能宣称彻底停止。商店、下拉搜索和负一屏未挂起；还原命令已写入实测文档。
- 通知差异如实记录：首次关闭后的 368 个既有渠道中，其余状态及应用总开关不变；最终复查仍有 23 个目标关闭、所有总开关不变，但天气提醒重要级别从 4 变为 3（仍开启，原因未确认），新增渠道共 13 个。
- 系统逐应用广告跟踪、负一屏、主题、视频等仍有未适配入口；不能把上述有限范围写成整机全部去广告成功。

Mac 与 Windows 均通过 112 项设备无关回归，Windows 打包及原生 GUI 冒烟通过；最终真机完整复跑四段，155 秒确认 9 项关闭、调整 0 项、失败 0 项。手机原始备份与日志留在本机，未上传。完整环境、应用版本、保留项、CI 记录及还原方法见[一加旧系统实测](../10-一加旧系统实测.md)。本轮不是 Windows 连接该手机的实测，也不能代替小米 OS4.0.27 的复测。

## 0.2.3 · 2026-10-25

Windows 0.2.2 的完整反馈已确认：小米 18 Pro Max（M154FF）、OS4.0.27.0.XEOCNXM / Android 17 抛出 `AccessibilityServiceAlreadyRegisteredError`，即手机 UiAutomation 已注册，新连接被拒绝。App 广告与营销通知的实际点击都依赖读屏，因此一起失败；不是扫描功能退回旧实现。**具体占用进程尚未确定，不能把它直接归因于 Android 17 或某个 App。**

- 补齐读屏会话生命周期：启动失败、操作异常和正常退出均关闭本次持有的 adb 连接，等本次进程和服务退出，再释放本机设备锁；未由本次启动的服务不主动停止。
- 同一电脑、同一设备的去广告读屏进程互斥。只对“已注册”错误清理本次失败连接后重试一次，处理短暂的注销衔接；持续占用就报失败，不无限等待或按名字批量杀进程。
- 持续冲突时给出可执行的恢复步骤：退出旧版及其他自动化工具；仍失败请机主手动重启手机，解锁后只开一个客户端并运行「检查读屏连接」。不自动重启手机，不自动停用无障碍，不清除应用数据。
- 首次读屏冲突后，跳过本次计划中后续的读屏步骤，保留最初的完整诊断，继续执行收尾。界面与诊断区分「失败」「跳过」；收尾不再写“去广告已经做完”，需要继续排查时提醒先保留 USB 调试。
- 固定 uiautomator2 为已验证的 3.7.1，避免构建时依赖漂移。保留 0.2.2 的 adb 只读扫描、完整诊断及此前修复。

**验证**：91 项回归通过，覆盖真实的跨进程锁竞争和异常退出后释放、注册冲突有限重试、初始化失败清理、不停止复用服务、首个诊断保留和失败收尾。Android 15 模拟器连续三次只读连接成功；外部自动化占用时复现相同 `already registered` 错误，返回失败后外部服务仍正常；释放占用后重连成功。两个去广告读屏任务同时运行时，第二个被拒绝，首个仍可正常读屏。未点击或更改手机广告开关。

安装包验证：Windows [Actions #40198943037](https://github.com/rddmwmddr/android-ad-cleaner/actions/runs/40198943037)（代码 `cb08d5c`）通过 91 项回归、打包后两层 CLI 调用、原生 GUI / 教程图片 / JS API 和安装包生成。Mac Apple 芯片及 Intel / Rosetta 最终包通过原生 GUI、两层 CLI、签名、公证；两种打包程序都通过模拟器实际读屏检查，Apple 芯片连续三次通过。Intel 真机和反馈者 Windows 电脑仍待测。

**支持边界**：尚未在反馈者 Windows 11 / OS4.0.27 手机上重跑。此前遗留或外部占用不保证仅换安装包就消失，必要时需先手动重启手机。没有新增系统权限或自动终止其他工具的功能。排查依据与步骤见[客户端说明](../08-桌面客户端.md#提示-accessibilityservicealreadyregisterederror--already-registered)。

## 0.2.2 · 2026-10-25

针对 Windows 0.2.1 / Xiaomi 18 Pro Max / HyperOS 4.0.27 的后续反馈：通知扫描显示 `QueryController / UiDevice / Main.runServer` 堆栈。截图只有末尾，无法确定手机端 UiAutomation 初始化失败的具体原因。本版修复扫描不必要依赖读屏服务、完整错误丢失的问题；**不把它写成已完成 4.0.27 真机适配**。

- 通知扫描、状态复查改为直接通过 adb 读取；无需启动 UiAutomation。已经达到目标状态的清单也不启动读屏服务、不操作页面。需要实际拨动开关时仍须读屏成功，失败不会算成功。
- 执行前可点「检查读屏连接」，仅检查连接和页面是否可读，不点击开关、不输出页面内容。命令行：`run.py -s <序列号> ui-check`。
- 扫描与执行失败保留完整异常，界面可展开、复制；本地保存在数据目录的 `logs/last-error.txt`。复制诊断附带最近失败的完整原因、HyperOS 版本，替换序列号及错误中的当前用户目录，不再只显示末尾 600 字。
- CLI 捕获异常并返回失败，保留原始原因，避免再附加 PyInstaller 的笼统错误。补充打包程序 `run.py → chan_fast.py` 两层调用测试：不存在的清单应及时失败，不能再打开窗口或接触手机。
- 标签构建只给 Release 草稿补缺少的文件，不覆盖已公开安装包和已有校验值。

**验证**：78 项回归通过，包括“UiAutomation 完全不可用时仍可扫描 / 复查”、实际关闭仍要求读屏、完整原因保留及脱敏。Android 15 模拟器的实际扫描和只读读屏检查通过。本版没有修改机型广告开关路径，没有在反馈者的小米 OS4.0.27 上重跑。

安装包验证：Windows [Actions #40195500808](https://github.com/rddmwmddr/android-ad-cleaner/actions/runs/40195500808)（代码 `9de8e6b`）通过 78 项回归、原生 GUI / 图片 / JS API、两层 CLI 分发与失败退出、安装程序和免安装包生成。Mac Apple 芯片 / Intel 两种最终包均通过签名、公证、Gatekeeper 及原生 GUI / 两层调用测试；Intel 使用 Rosetta，Intel 真机仍待测。Apple 芯片打包程序的模拟器只读通知扫描通过。

**仍需反馈者复测**：安装 0.2.2 后，先确认通知扫描，再点「检查读屏连接」。若失败，点「复制完整诊断」提供首个 `Exception` / `Caused by` 及完整堆栈；不要只截最后几行。原先 0.2.0 执行时再次打开窗口属于已修复的 CLI 分发问题，不能直接当作本次初始化失败的同一原因。

## 0.2.1 · 2026-10-25

这是 0.2.0 之后的修复版本，提供 Mac Apple 芯片、Mac Intel、Windows 安装版和免安装版。[下载 v0.2.1](https://github.com/rddmwmddr/android-ad-cleaner/releases/tag/v0.2.1)。旧版不会自动升级；替换程序即可继续使用原来的备份目录，无需删除备份。

### 修复了什么

| 问题 | 0.2.1 的处理 |
|---|---|
| Windows 打开后显示 127.0.0.1 超时（#18） | 使用明确的 `file://` 地址加载本地页面和图片，不再依赖 Bottle 的本地 HTTP 服务；新增实际 GUI、图片和 JS API 冒烟测试，Windows 构建也执行此项 |
| 小米 10 横屏热榜漏开关、部分设置未遍历（#21） | 读屏时刷新屏幕尺寸，旋转后拒绝使用旧坐标；浏览器优先识别顶部设置图标，避免点击正文「我的」；同页主开关和热榜子页都会处理；补充「天气视频卡片」 |
| 老系统不支持 msa 断网却显示成功（#21） | 先检查接口，再核对包联网规则和防火墙状态；兼容实机 `包名:allow/deny` 回读。不支持或回读失败时明确报告部分完成并返回失败，保留挂起还原记录 |
| 荣耀服务通知被列为营销候选（#24） | 排除实时活动、赛事、护眼及告警；界面默认不选「其他 / 普通通知 / 推送通知」等含糊类别。仍开着的渠道会显示失败，不把尝试次数当成功数 |
| Mac Intel 签名后界面启动卡住 | 发布检查发现 PyObjC / libffi 回调缺少运行权限；仅给 Intel 主程序补充必要权限，保留 hardened runtime 和库签名校验，重新签名、公证并做 Rosetta GUI 冒烟测试 |
| 安装包混入本地调试文件 | Mac / Windows 共用明确的发布资源清单，排除运行日志、缓存、备份和测试机型；公证脚本中的失败会中止构建 |
| 荣耀通知扫描截图越界（#16） | 对照截图的真实尺寸检查取样范围；分辨率不一致或越界时跳过未知状态，不猜成关闭、不抛 `IndexError` |
| HyperOS 渠道深链失败、vivo 误关整应用通知（#7、PR #19 / #20） | 确认设置页身份、渠道标题和明确的通知开关；HyperOS 尝试从应用通知页进入渠道详情；vivo 的 `systemuiplugin` 页面直接拒绝。每次点击后回读渠道状态，应用总开关异常变化时停止整批 |
| 通知清单首行被跳过、还原失败仍成功 | 接受 UTF-8 BOM / CRLF；清单格式错误会报行号。关闭与还原失败均返回失败；扫描失败不覆盖已有清单，客户端显示错误与重试入口 |
| Windows 备份路径跨盘报错 | 程序与备份在不同盘符时显示实际路径，不再因计算相对路径抛异常；该问题由本轮 Windows 云端回归发现 |
| vivo 隐私空间污染备份、快应用无法挂起（PR #20） | 包清单限定机主 `--user 0`；vivo / iQOO 检测到快应用服务开关时保存原值后关闭，回读验证，重复操作不覆盖原值。按设备匹配备份还原，无备份时不擅自打开；其他品牌成功挂起后再强停进程（#9） |
| 小米设置搜索卡住、反复输入 `%` | 小米机型脚本直接走菜单进入广告服务。通用搜索先确认可见且获得焦点的输入框，再限时输入并核对文字；不再保留可能持续输入的后台线程，也不把输入框当搜索结果点击 |
| vivo / iQOO 客户端清单链接打不开 | 按手机品牌打开具体清单文件，并编码中文路径；未知品牌打开清单目录说明。也覆盖小米 / Redmi / POCO、OPPO / 一加 / realme、荣耀 |
| 打包客户端执行时再次打开窗口，任务没有进入引擎 | 子进程统一通过 `--cli` 入口运行 `fast.py`、`chan_fast.py`，保留 Windows 的 UTF-8 输出处理 |
| 小米脚本在多个 App 找不到入口 | 补齐手机管家、全局搜索的直达入口，处理主题启动包跳转、更多菜单、商店个性化服务子页、搜索应用推荐和热榜子页、天气城市管理入口；新增识别天气和日历的「内容推广」 |
| 页面切换后误读旧页面、空页面或其他 App | 启动时核对结果和前台包；等待非空页面稳定；只滑动可滚动区域，滑动离开当前页面时停止该段；不把带开关的设置面板当弹窗关闭 |
| 开关标题或状态识别错误 | 按所在行和无障碍标签识别标题，过滤屏幕外节点、单选按钮和文字轮播控件；「限制广告跟踪」等保护开关设为开启。点击后开关消失时不误报成功、不重复点旧坐标 |
| 失败后仍显示成功，或插电常亮未还原 | 通知渠道、快应用挂起失败会报告失败；机型脚本退出或异常时还原运行前的插电常亮值。每页日志分别记录核对数和调整数 |

### 机型与兼容性

- **小米 HyperOS**：继续兼容 Xiaomi 18 Pro Max 和社区提供的 18 Fold 入口差异。浏览器首页由机主决定；自动更新、常用应用、天气预警等保留项维持原规则。
- **vivo OriginOS**：新增 X300 Ultra（V2547DA）的 OriginOS 6 脚本，并识别 V2547A 型号别名；整段自动执行仍待真机回归。根据 PR #20 的新证据，通知工具不再尝试操作 vivo 的应用级总开关；快应用优先使用可读到的系统服务开关，不扩展到智慧生活等功能包。
- **同品牌参考脚本**：没有本型号脚本时可主动选择参考脚本（命令行加 `--ref`，客户端默认不勾选）。型号或系统版本不一致时使用安全模式，只处理脚本点名的开关，不做整页全关；这不等于完成新机型适配。
- **小米 msa**：经机主同意挂起时，仅在系统提供接口的情况下尝试禁止联网。Android 13 等旧系统可能只完成挂起，不能保证阻断广告；还原时不会关闭其他包共用的防火墙链。断网规则重启后可能失效，见[小米清单](../清单/小米-HyperOS.md)。
- **小米 10 / 荣耀 Magic7 Pro**：基于 #21 / #24 的路径与日志修复共用引擎和默认通知选择；没有新增未经真机验证的专用脚本。
- **华为原生鸿蒙**：#22 / #23 与此前反馈属于同一支持边界；连接首页明确当前仅支持 adb / Android，使用 HDC 的原生鸿蒙暂不支持。此版本没有鸿蒙引擎。

### 验证结果

| 验证范围 | 2026-10-25 的结果 |
|---|---|
| Xiaomi 18 Pro Max（M154FF），HyperOS OS4.0.24，Android 17 | 前轮源码九段完整重跑约 173 秒，核对 28 项目标；日志无未找到或执行错误，重复运行调整 0 项。修复验证期间新增关闭天气、日历的「内容推广」各一项，未新增挂起包。本轮小米 10 兼容改动尚未在此机重跑 |
| 通用设置搜索 | 真机成功输入中文并进入广告服务页；超时、输入失败、输入框与结果区分另有自动回归覆盖，未声称覆盖所有系统输入法 |
| 设备无关回归 | 66 项测试通过：覆盖输入与开关保护、截图和横屏尺寸、渠道身份与实际状态、BOM、扫描失败、服务通知选择、快应用备份还原、msa 支持检测及部分失败、Windows 跨盘路径、桌面启动、发布资源范围。常亮原值 `15` 可正确恢复 |
| 客户端清单 | 四品牌清单与目录说明均返回 HTTP 200；品牌别名及未知品牌的跳转映射校验通过 |
| Mac Apple 芯片 0.2.1 | 包内源码逐文件核对通过；Developer ID 签名、公证、凭证装订、Gatekeeper 检查通过；内置命令行、原生 GUI、五张教程图片、JS API 通过 |
| Mac Intel 0.2.1 | 修复签名权限后，最终 App 与 DMG 重新公证、装订，签名与 Gatekeeper 验证通过；Rosetta 下内置命令行、原生 GUI / 五张图片 / JS API 通过。Intel 真机待测 |
| Windows 0.2.1 | [Actions #40190341584](https://github.com/rddmwmddr/android-ad-cleaner/actions/runs/40190341584) 通过：66 项回归、PyInstaller、内置命令行、原生 GUI / 图片 / JS API、安装程序及便携包生成。代码提交 `310a3f9`；后续 `73239d8` 仅调整 Mac 签名。下载后校验 ZIP 完整性，包内脚本与源码一致（忽略 Windows 换行差异） |
| Android 15 模拟器 | 屏幕从 1344 × 2992 转为 2992 × 1344 后读屏尺寸正确刷新；独立应用营销渠道 `ON → off → ON` 通过，服务渠道和应用总开关不变；旋转与插电常亮原值已恢复 |

测试命令（已安装根目录 `requirements.txt` 的 Python 环境）：

```bash
python -m unittest discover -s tests -v
```

真机结果仅代表上述机型和版本。vivo 整段脚本、小米 10、荣耀 Magic7 Pro、Windows 连接手机及报告者电脑、Intel Mac 真机仍待回归；不能用模拟器或 Rosetta 的结果代替。测试收尾恢复原来的屏幕旋转与插电常亮设置。

### 仍待处理

- Windows #18 的启动修复已通过云端原生 GUI 验证；报告问题的 Windows 11 电脑仍需复测，请升级 0.2.1，0.2.0 不会自动获得修复。
- [PR #10](https://github.com/rddmwmddr/android-ad-cleaner/pull/10)：社区提供的 vivo OriginOS 7 适配尚未合并；当前 OriginOS 6 参考脚本不代表 OriginOS 7 已验证。
- [PR #19](https://github.com/rddmwmddr/android-ad-cleaner/pull/19) / [PR #20](https://github.com/rddmwmddr/android-ad-cleaner/pull/20) 的问题已按当前引擎重新实现修复并补测试；没有整单合并，也没有引入整包关闭通知的命令。HyperOS / vivo / 荣耀对应手机的新版回归仍待完成。
- 所有已拉取 Issue 的处理范围、证据和待验证项见 [社区问题处理记录](../09-社区问题处理.md)，其中原生鸿蒙、缺少诊断的新机型不会标成已适配。

历史安装包与版本说明见 [Releases](https://github.com/rddmwmddr/android-ad-cleaner/releases)。
