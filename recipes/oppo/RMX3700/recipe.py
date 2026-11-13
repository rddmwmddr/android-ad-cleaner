# realme GT Neo5 SE（RMX3700，ColorOS 16.0.5.1300(CN01)）机型脚本。路径实测：2026-10-30，下拉搜索 2026-11-02 补测。软件商店隐私入口接受「隐私」与
from recipe_kit import step
# 「隐私授权管理」两种叫法（#933，未复测）。只收录已走通的：
# 广告跟踪、软件商店、浏览器、下拉搜索、小布建议、应用建议。
# 不挂包、不动通知渠道；这些操作仍走 run.py 的独立、需确认流程。
#
# 本机实测与其它机型的差异（务必保留在注释里，别照抄别家机型）：
#   · ColorOS 16 的广告跟踪入口在「隐私 → 设备标识与广告 → 广告跟踪」，不是 17 的「隐私与安全」。
#   · 软件商店有「服务管理」（OPPO GT5 Pro 那台没有），共 46 项；
#     隐私相关不在「隐私」页，而在「账号与隐私 → 隐私授权管理 → 个性化推荐」。
#   · 浏览器主页是「简洁」模式，没有底部「我的」和菜单；必须用 BrowserPreferencesPage 直达。
#   · 小布建议叫「NEXT AI」（不是「OPPO AI」）。
#   · 下拉搜索的设置页 SearchSettingActivity 没导出，用 `-n` 组件名会被系统拒绝；
#     走应用自己的 gs://search/setting。前提是 com.heytap.quicksearchbox 没被挂起——
#     它一挂，这个 scheme 落到系统的 SuspendedAppActivity「应用已被暂停」页。
#   · 负一屏的设置页 com.heytap.iflow.main.setting.SettingsActivity 存在，但 am start 要
#     oppo.permission.OPPO_COMPONENT_SAFE（OPPO 私有权限，只有系统应用持有），adb 起不来；
#     速览界面上也没有头像或齿轮 → 负一屏段做不了。
#   · 本机没有独立视频 App：com.coloros.video 是本地播放器（只列手机里的文件，没有在线资讯流），
#     com.heytap.yoli 未安装 → 视频段没有可关的广告位。
#   · 主题商店 com.oplus.themestore 在 /product/priv-app/KeKeOplusThemeStore-CN/，是个入口壳：
#     oaps://theme 进 .entrance.BasicEntranceActivity，点「打开主题商店」弹
#     「使用个性化服务需要安装“主题商店”」——主商店没预装、要联网下载 → 主题段没法自动做。
#     注意包名不是 com.heytap.themestore（本机没有这个包），enabled=0 是 DEFAULT 不是禁用。
BUILD = "RMX3700_16.0.5.1300"
# 家族库按这些常量选走法（#1245），缺省档见 tool/recipe_nav.py。
WAIT_PAGE_TIMEOUT = 8
SETTINGS_PAGE_STYLE = "scroll"

import time
# 分段结果由引擎经 rt 记录

# 商店「服务管理」是「关掉后隐藏对应服务入口」的开关。服务类入口要留，推广入口才关。
STORE_KEEP = [
    "帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：存储空间清理",
    "我的专区：我的资产", "我的专区：安全守护", "我的专区：小i客服",
    "应用使用记录", "首页：AI搜索",
]

# 全局搜索的设置页 SearchSettingActivity 没有导出：am start -n 直接被系统拒绝
# （SecurityException: not exported，和 ColorOS 17 的 PKT110 一样），只能用它自己的 scheme 打开。
# 前置条件：com.heytap.quicksearchbox 不能被挂起——它一挂，这个 scheme 落到系统的
# SuspendedAppActivity「应用已被暂停」页，全局搜索整个不可用，本段也做不了。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 搜索范围：只关推荐位。「榜单」「小红书」「购物」「小说」「视频」「小程序」「便捷服务」
# 是内容源，用户主动去点才用得到，保持不动；「本机应用」「设置」「相册」等是数据源，更不能关。
SEARCH_SOURCES = ["个性化推荐", "精选资讯", "搜索建议"]
# 首页卡片管理的推荐位，全是推荐，没有要留的。
SEARCH_CARDS = ["应用建议", "热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"]
# 这两个是「应用建议」的子项：父开关一关，这两行直接从页面上消失，所以要先关它们。
SEARCH_CARD_CHILDREN = ["未下载应用推荐", "应用建议小卡"]


def guard():
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "RMX3700" or not build.startswith(BUILD):
        skip("型号或系统版本不同，跳过；请重新核对页面")


@step("广告跟踪")
def _():
    # 每个 App 一个 OAID 开关、没有总开关，新装 App 默认开。
    skip_in_safe_mode()
    if not settings_page("隐私"):
        return False
    if not wait_page("com.oplusos.securitypermission.privacy.PrivacySettingsDashboardActivity", "隐私"):
        return False
    if not tap_by_scroll("设备标识与广告"):
        print("  ! 没找到「设备标识与广告」")
        return False
    if not wait_page("com.oplus.settings.OplusSettingsActivity$DevicesIdentifySettingsActivity",
                     "设备标识与广告"):
        return False
    if not tap_by_scroll("广告跟踪"):
        print("  ! 没找到「广告跟踪」")
        return False
    if not wait_page("com.oplus.settings.feature.notification.oaid.OAIDActivity", "广告跟踪"):
        return False
    # 页面上全是 App 名，没有服务类开关，整页关掉即可。
    p.off(page="广告跟踪")
    return True


@step("软件商店")
def _():
    p.start("com.heytap.market")
    p.tap("我的", exact=True, scrolls=0)
    time.sleep(1.2)
    if not p.tap("设置", exact=True, scrolls=0):
        print("  ! 商店里没找到「设置」")
        return False
    time.sleep(1.5)
    if not wait_page("com.heytap.market.mine.cn.setting.ui.SettingActivity", "设置"):
        return False

    # 服务管理：46 项推广/服务入口，只保留 STORE_KEEP 里的服务类。
    if tap_by_scroll("服务管理"):
        if wait_page("com.heytap.market.mine.cn.setting.ui.ServeManagerActivity", "服务管理"):
            p.off(keep=STORE_KEEP, page="商店·服务管理")
        else:
            print("  ! 没到「服务管理」页")
        p.back()
        time.sleep(1.2)

    # 个性化推荐不在「隐私」页，在「账号与隐私 → 隐私授权管理 → 个性化推荐」。
    # 商店 App 自己升级，这一行在有的版本里叫「隐私」（#933）；两页都可以当落点判。
    tap_by_scroll("账号与隐私")
    privacy = ("隐私", "隐私授权管理")
    if tap_by_scroll(privacy):
        if wait_page("com.heytap.market.mine.cn.setting.ui.PrivacyActivity", privacy):
            if tap_by_scroll("个性化推荐"):
                if wait_page("com.heytap.market.mine.cn.setting.ui.PersonalRecommendActivity",
                             "个性化推荐"):
                    p.off(only=["个性化推荐"], page="商店·个性化推荐")
                else:
                    print("  ! 没到「个性化推荐」页")
            else:
                print("  ! 没找到「个性化推荐」")
        else:
            print("  ! 没到「隐私授权管理」页")
        p.back()
        time.sleep(1.0)
    else:
        p.note_miss(" / ".join(privacy))
        print("  ! 没找到「隐私授权管理」")
    return True


@step("浏览器")
def _():
    # 主页是「简洁」模式：没有底部「我的」，也没有菜单。设置页只能按公开 Activity 直达。
    p.d.shell("am start -n com.heytap.browser/com.heytap.browser.settings.component.BrowserPreferencesPage")
    time.sleep(1.5)
    if not wait_page("com.heytap.browser.settings.component.BrowserPreferencesPage", "浏览器"):
        return False
    if not tap_by_scroll("隐私"):
        print("  ! 没找到「隐私」")
        return False
    if not wait_page("com.heytap.browser.settings.component.BrowserPreferenceActivity", "隐私"):
        return False
    if not tap_by_scroll("广告管理"):
        print("  ! 没找到「广告管理」")
        return False
    p.off(only=["开屏广告", "资讯列表广告", "摇一摇广告"], page="浏览器·广告管理")
    return True


@step("下拉搜索")
def _():
    # 搜索设置首页本身 0 个开关，全部开关都在子页里。「账号与隐私」是分组标题，点它没反应。
    if not open_search_setting():
        return False
    # 搜索范围 24 个开关：只有 3 个推荐位要关，其余是内容源和数据源。
    if open_search_sub("搜索范围", "com.heytap.quicksearchbox.ui.activity.SearchSourceActivity"):
        p.off(only=SEARCH_SOURCES, page="搜索范围")
    # 功能管理：只关「搜索框提示词」。语音搜索、扫一扫是功能，搜索历史是用户自己的记录。
    if open_search_sub("功能管理", "com.heytap.quicksearchbox.ui.activity.SearchFunctionManagerActivity"):
        p.off(only=["搜索框提示词"], page="功能管理")
    # 首页卡片管理：先关「应用建议」的两个子项，否则父项一关它们就从页面上消失，关不掉。
    if open_search_sub("首页卡片管理", "com.heytap.quicksearchbox.ui.activity.SearchModuleManagerActivity"):
        close_rows(SEARCH_CARD_CHILDREN, "首页卡片·子项")
        close_rows(SEARCH_CARDS, "首页卡片")
    # 消息管理：本机录制时「消息通知」已经是关的，这里只做回读兜底。
    if open_search_sub("消息管理", "com.heytap.quicksearchbox.ui.activity.SearchPushManagerActivity"):
        p.off(only=["消息通知"], page="消息管理")
    return True


@step("小布建议")
def _():
    # realme 上叫「NEXT AI」，不是「OPPO AI」。
    if not settings_page("NEXT AI", "小布建议"):
        return False
    if not wait_page("com.oplus.advice.settings.ui.AdviceSettingActivity", "小布建议"):
        return False
    if not tap_by_scroll("资讯服务"):
        print("  ! 没找到「资讯服务」")
        return False
    if not wait_page("com.oplus.advice.settings.ui.detail.SceneServiceActivity", "资讯服务"):
        return False
    # 关掉主开关，下面的视界日报 / AI快讯 / 小红书资讯随之失效。
    p.off(only=["资讯服务"], page="小布建议·资讯服务")
    return True


@step("应用建议")
def _():
    # 负一屏/助手里的「应用建议」：每个已装 App 一个开关，关掉即不再出现在推荐里。
    skip_in_safe_mode()
    if not settings_page("NEXT AI", "小布建议"):
        return False
    if not wait_page("com.oplus.advice.settings.ui.AdviceSettingActivity", "小布建议"):
        return False
    if not tap_by_scroll("应用建议"):
        print("  ! 没找到「应用建议」")
        return False
    if not wait_page("com.oplus.metis.v2.ui.settings.SettingActivity", "应用建议"):
        return False
    p.off(page="应用建议")
    return True


def tail():
    print("\n== 结果", flush=True)
    for name, state in rt.results:
        print(f"  {name}: {state}")

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, rt, skip, skip_in_safe_mode
    from recipe_nav import open_search_setting, open_search_sub, settings_page, tap_by_scroll, wait_page
    from recipe_strategies import close_rows
