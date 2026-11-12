# realme 真我 GT5 Pro（RMX3888，ColorOS 15.0.0.420(CN01) / Android 15）机型脚本。
# 按报告者（#1083）逐段实测的落点写成，本仓库没有这台手机，未在真机复跑，待复测。
# 只关点名的广告与推荐；营销通知、组件挂起与快应用仍走 run.py 的独立确认流程。
#
# 本机实测与同族 OPPO 脚本的差别（别照抄别家脚本的路径）：
#   · 广告跟踪在「隐私 → 更多 → 设备标识与广告 → 广告跟踪」，页内 219 个开关
#     （`com.oplus.settings.feature.notification.oaid.OAIDActivity`）。
#   · 负一屏这一层没有「推荐服务 → 轮播推荐」，也没有「搜索框提示词」；推荐服务与热点资讯默认已关。
#     设置页是 `com.oplus.assistantscreen.setting.AssistantScreenSettingActivity`。
#   · 软件商店的个性化推荐是子页 `com.heytap.market.mine.PersonalRecommendActivity`，不是就地开关；
#     服务管理 46 项。
#   · 浏览器 40.9.14.1 的「隐私」页已没有「广告管理」入口；主页布局默认已经是「简洁」。
#     设置页可以直达 `com.heytap.browser/.settings.component.BrowserPreferencesPage`。
#   · 主题商店的包名是 `com.oplus.themestore`（不是同族的 `com.heytap.themestore`），而且没有
#     启动界面：`resolve-activity` 返回 No activity found，这一段在本机做不了。
#   · `com.heytap.yoli` 只有本地视频播放器（`LocalVideosListActivity`），没有在线内容与「我的」页。
#   · 游戏中心 `com.nearme.gamecenter` 确实未安装。
#   · 设置里的小布建议入口叫「AI」（`com.coloros.sceneservice`），不叫「OPPO AI」；总开关默认已关。
BUILD = "RMX3888_15.0.0.420"
MODELS = ["RMX3888"]

import time

import adb_link
from fast import ScreenLocked

SETTINGS = "com.android.settings"
MARKET = "com.heytap.market"
BROWSER = "com.heytap.browser"
THEME = "com.oplus.themestore"
VIDEO = "com.heytap.yoli"
GAME = "com.nearme.gamecenter"
SEARCH = "com.heytap.quicksearchbox"
# SearchSettingActivity 没导出（`am start -n` 会被系统拒绝），只能走应用自己的 scheme。
# 前提是 com.heytap.quicksearchbox 没被挂起：一挂，这个 scheme 落到系统的「应用已被暂停」页。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 搜索范围：只关推荐位。「榜单」「小红书」「购物」「小说」「视频」是内容源，「本机应用」「设置」
# 这类是数据源，关掉会搜不到东西。
SEARCH_SOURCES = ["个性化推荐", "精选资讯"]
# 商店「服务管理」里只保留功能项，其余推广入口全关（本机 46 项）。
STORE_KEEP = ["帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：存储空间清理",
              "我的专区：我的资产", "我的专区：安全守护", "我的专区：小i客服",
              "应用使用记录", "首页：AI搜索"]


def settings_page(*path):
    """打开系统设置并逐级点进 path 里的每一级。任一级点不到就返回 False。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    time.sleep(1.2)
    for name in path:
        if not p.tap(name, exact=True):
            return False
    return True


def has_row(name, screens=4):
    """这一页（含下面几屏）有没有这行：只找不点。

    存在性探测不能用 `maybe()` / `p.entry`：它们找到就真的点一下，点在开关行上等于把开关拨了。
    """
    for _ in range(screens):
        if p.find(name, exact=True):
            return True
        if not p.scroll_more():
            return False
    return False


def store_privacy():
    """走进商店的隐私页：有的版本设置首页直接有「隐私」，有的挂在「账号与隐私」下面。"""
    if p.tap("隐私", exact=True):
        return True
    if not p.tap("账号与隐私", exact=True):
        return False
    for name in ("隐私", "隐私授权管理"):
        if p.tap(name, exact=True):
            return True
    return False


@step("广告跟踪")
def _():
    # 每个 App 一个 OAID 开关、没有总开关（本机 219 个），新装 App 默认开，整页关掉即可。
    skip_in_safe_mode()
    found = settings_page("隐私", "更多", "设备标识与广告", "广告跟踪")
    if not found:
        p.miss = 0
        found = settings_page("隐私", "设备标识与广告", "广告跟踪")
    if not found:
        raise RuntimeError("设置里没走到「隐私 → 更多 → 设备标识与广告 → 广告跟踪」")
    page("广告跟踪", SETTINGS, "OAIDActivity")
    p.off(page="广告跟踪", max_screens=40)


@step("负一屏")
def _():
    # 本机这一层没有「推荐服务 → 轮播推荐」，也没有「搜索框提示词」：两处默认已关，没有可关的项。
    p.d.shell("input keyevent HOME"); time.sleep(0.6)
    p.d.shell("input keyevent HOME"); time.sleep(0.6)
    entered = False
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
        if "assistantscreen" in p.focus():
            entered = True
            break
    if not entered:
        raise RuntimeError("右滑没进负一屏（速览），本段没做成")
    if not maybe("我的") and not maybe("头像"):
        raise RuntimeError("负一屏里没找到「我的」或头像入口")
    if not p.tap("设置", exact=True, scrolls=0):
        raise RuntimeError("负一屏没有设置入口")
    if not p.in_settings_page():
        raise RuntimeError("负一屏的设置页没有打开")
    has_tips = has_row("搜索框提示词")
    has_service = has_row("推荐服务")
    if not (has_tips or has_service):
        p.back(2)
        skip("本机这一层没有「推荐服务」与「搜索框提示词」，没有可关的推荐位")
    p.top(3)                 # 探测时翻过页；关开关要从页顶往下读
    if has_tips:
        p.off(only=["搜索框提示词"], page="负一屏")
    # 「推荐服务」总开关不能拨：会删掉天气、步数、清理卡片。它在这一族机型上是点开子页的入口行；
    # 万一某版把它做成开关行，就一个字都不动，留给机主手动关轮播。
    if has_service:
        if any(title == "推荐服务" for title, _, _ in p.switches()):
            print("  · 「推荐服务」在本机是开关行，按约定不拨（会删掉天气、步数、清理卡片）；"
                  "轮播推荐需手动关", flush=True)
        elif p.tap("推荐服务", exact=True):
            if p.tap("轮播推荐", exact=True):
                p.tap("不显示", exact=True, scrolls=0)
            else:
                print("  · 「推荐服务」下没有「轮播推荐」", flush=True)
            p.back()
    p.back(2)


@step("下拉搜索")
def _():
    # 搜索设置首页本身 0 个开关，开关都在子页里。「账号与隐私」是分组标题，点它多数情况没反应。
    p.d.shell(SEARCH_SETTING)
    time.sleep(1.8)
    if "SuspendedAppActivity" in p.focus():
        skip(f"{SEARCH} 被挂起了，全局搜索不可用；先 run.py unsuspend {SEARCH} 再跑本段")
    page("搜索范围", SEARCH, "SearchSettingActivity")
    if p.tap("搜索范围", exact=True):
        p.off(only=SEARCH_SOURCES, page="下拉搜索·搜索范围")
        p.back()
    if p.tap("功能管理", exact=True):
        # 语音搜索、扫一扫是功能，搜索历史是用户自己的记录，只关提示词。
        p.off(only=["搜索框提示词"], page="下拉搜索·功能管理")
        p.back()
    p.miss = 0
    if not p.tap("账号与隐私", exact=True):
        p.miss = 0                       # 有的版本里它只是分组标题
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="下拉搜索·隐私")
        p.back(2)
    p.back(2)


@step("软件商店")
def _():
    p.start(MARKET)
    if not p.tab("我的"):
        raise RuntimeError("商店里没找到底部「我的」")
    time.sleep(1.0)
    if not p.tap("设置", exact=True, scrolls=0):
        raise RuntimeError("商店「我的」页没找到「设置」")
    page("设置", MARKET, "SettingActivity")
    if p.tap("服务管理", exact=True):
        p.off(keep=STORE_KEEP, page="商店·服务管理")
        p.back()
    # 个性化推荐是入口行，开关在下一层的 PersonalRecommendActivity，不是就地开关。
    if store_privacy():
        if p.tap("个性化推荐", exact=True):
            page("个性化推荐", MARKET, "PersonalRecommendActivity")
            p.off(only=["个性化推荐"], page="商店·个性化推荐")
            p.back()
        else:
            print("  · 隐私页没有「个性化推荐」入口", flush=True)
        p.back(2)
    else:
        p.note_miss("隐私")
        print("  · 商店里没找到「隐私 / 隐私授权管理」", flush=True)
    p.back(2)


@step("浏览器")
def _():
    # 40.9.14.1 的「隐私」页已没有「广告管理」入口；主页布局默认已是「简洁」。
    # 首页也没有底部「我的」和菜单，只能按页面名直达设置页（带清栈参数会立刻退出）。
    p.start(BROWSER)
    p.d.shell("am start -n com.heytap.browser/com.heytap.browser.settings.component.BrowserPreferencesPage")
    time.sleep(1.5)
    if BROWSER not in p.focus():
        raise RuntimeError("浏览器设置页没有打开")
    if p.tap("主页设置", exact=True):
        if p.tap("页面布局", exact=True):
            p.tap("简洁", exact=True, scrolls=0)
            p.back()
        p.back()
    if p.tap("隐私", exact=True):
        if p.tap("广告管理", exact=True):
            p.off(only=["开屏广告", "资讯列表广告", "摇一摇广告"], page="浏览器·广告管理")
        else:
            print("  · 「隐私」页没有「广告管理」，本段没有可关的项（本机 40.9.14.1）", flush=True)
        p.back()
    p.back(2)


@step("主题")
def _():
    # 包名不是同族的 com.heytap.themestore，而且没有启动界面：resolve-activity 返回
    # No activity found，拉起命令只会报「无法打开」。本机这一段做不了，按跳过收尾。
    try:
        p.start(THEME)
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError as error:
        if "无法打开" not in str(error):
            raise
        skip(f"主题商店（{THEME}）没有启动界面，本机做不了这一段")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("服务管理", exact=True):
        if p.tap("消息与广告", exact=True):
            # 消息通知是服务通知，保留；只关开屏广告。
            p.off(only=["开屏广告"], page="主题·消息与广告")
            p.back()
        p.back()
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="主题·个性化推荐")
        p.back()
    p.back(2)


@step("视频")
def _():
    # 本机 com.heytap.yoli 只有本地视频播放器（LocalVideosListActivity），没有在线内容与「我的」页。
    p.start(VIDEO)
    if not maybe("我的"):
        skip("本机视频 App 只有本地视频播放器，没有在线内容与「我的」页")
    if not p.tap("设置", exact=True, scrolls=0):
        raise RuntimeError("视频「我的」页没找到「设置」")
    if p.tap("个性化内容管理", exact=True):
        p.off(only=["个性化推荐"], page="视频·个性化内容管理")
        p.back()
    p.back(2)


@step("游戏中心")
def _():
    # 本机未安装：p.start 抛 MissingPackage，段包装按跳过记账。装上之后走同族旧版路径。
    p.start(GAME)
    if not p.tab("我的"):
        raise RuntimeError("游戏中心没找到底部「我的」")
    time.sleep(1.0)
    if not p.tap("设置", exact=True, scrolls=0) and not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("游戏中心没找到设置入口")
    if p.tap("隐私开关设置", exact=True) and p.tap("个性化推荐管理", exact=True):
        p.off(only=["个性化推荐"], page="游戏中心·个性化推荐管理")
    p.back(4)


@step("小布建议")
def _():
    # 本机设置里的入口叫「AI」（com.coloros.sceneservice 的设置页），不叫「OPPO AI」；
    # 报告者实测「小布建议」总开关默认已关，没再往下点。开着时才去二级页关「资讯服务」。
    if not settings_page("AI") and not settings_page("OPPO AI"):
        raise RuntimeError("设置里没找到小布建议入口（「AI」/「OPPO AI」）")
    page("小布建议", activity="SettingsActivity")
    if p.tap("资讯服务", exact=True):
        # 关掉主开关，下面的视界日报 / AI 快讯 / 小红书资讯随之失效。
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
    else:
        print("  · 没有「资讯服务」入口（本机小布建议总开关默认已关）", flush=True)
    p.back(2)
