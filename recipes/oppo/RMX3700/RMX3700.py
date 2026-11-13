# realme GT Neo5 SE（RMX3700，ColorOS 16）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 settings_page / tap_by_scroll / wait_page / open_search_setting / open_search_sub / close_rows
# 与 skip / skip_in_safe_mode / p.note_miss 由装载器注入执行作用域。六段都留在这里：每段都按
# wait_page 的落点逐跳判、失败即 return False，本机路径与别家不同。
import time

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, rt, skip, skip_in_safe_mode
    from recipe_nav import open_search_setting, open_search_sub, settings_page, tap_by_scroll, wait_page
    from recipe_strategies import close_rows

BUILD = "RMX3700_16.0.5.1300"
# 家族库按这些常量选走法（#1245），缺省档见 tool/recipe_nav.py。
WAIT_PAGE_TIMEOUT = 8

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


def step_ad_tracking(p, rt):
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


def step_store(p, rt):
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


def step_browser(p, rt):
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


def step_search(p, rt):
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


def step_assistant_advice(p, rt):
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


def step_app_suggestions(p, rt):
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
