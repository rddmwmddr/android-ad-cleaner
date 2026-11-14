# OPPO Find X8s（PKT110，ColorOS 17）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 tap / close_named / close_all / close_group / open_settings 与 require / skip 由装载器注入。
# 四段留在代码里：广告跟踪与游戏中心要清页面状态并逐个点名弹窗按钮，下拉搜索按读到的开关分岔，
# 主题商店的「重进一次再回读」要传回调。
import time
import recipe_nav as nav
import recipe_strategies as strategies


BUILD = "PKT110_17.0.0.102(CN01)"

# 全局搜索的设置页没有导出：adb am start 会被系统拒绝（SecurityException: not exported），
# 只能用它自己的 gs:// scheme 打开。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 搜索首页上那几张卡片：应用建议、精选推荐、推荐卡片、热搜榜单都是推荐位。
# 「便捷服务」是用户常用的快捷入口，不是广告位，保持不动。
HOME_CARDS = ["热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"]
# 「未下载应用推荐」「应用建议小卡」是「应用建议」的子项：父开关一关，这两行就没了。
HOME_CARD_CHILDREN = ["未下载应用推荐", "应用建议小卡"]
HOME_CARD_PARENT = "应用建议"
# 搜索结果里带出来的推荐源。「榜单」「小红书」「购物」这些是内容源不是广告位，保持不动。
SEARCH_SOURCES = ["个性化推荐", "精选资讯", "搜索建议"]


def step_ad_tracking(p, rt):
    """设置 → 隐私与安全 → 设备标识与广告 → 广告跟踪。
    每个 App 一个开关、没有总开关，本机 96 个 App，分五屏。"""
    rt.skip_in_safe_mode()
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    p.miss = 0
    # 17 把入口改名叫「隐私与安全」：先试新名字，免得在旧名字上白翻一轮、还打印一行失败（#292）。
    if not p.tap("隐私与安全", exact=True):
        p.miss = 0
        nav.tap(p, rt, "隐私")
    nav.tap(p, rt, "设备标识与广告")
    nav.tap(p, rt, "广告跟踪")
    time.sleep(1)
    strategies.close_all(p, rt, "广告跟踪", max_screens=40)


def step_search(p, rt):
    """全局搜索的设置页（gs://search/setting）：搜索首页上的推荐卡片、搜索结果里的推荐源、
    搜索框提示词、消息通知、隐私里的个性化推荐。
    「便捷服务」和搜索范围里的内容源（榜单、小红书、购物等）不是广告位，不动。"""
    p.d.shell(SEARCH_SETTING); time.sleep(1.5)
    rt.require("com.heytap.quicksearchbox" in p.focus(), "全局搜索设置页没有打开")
    nav.tap(p, rt, "首页卡片管理")
    rt.require("SearchModuleManagerActivity" in p.focus(), "首页卡片管理页没有打开")
    if strategies.wait_switches(p, rt):
        strategies.close_group(p, rt, HOME_CARD_CHILDREN, HOME_CARD_PARENT, "下拉搜索·首页卡片管理", max_screens=3)
        nav.close_named(p, rt, HOME_CARDS, "下拉搜索·首页卡片管理", max_screens=3)
    else:
        # 推荐卡片全部关掉之后，这一页就不再列出任何卡片（2026-10-28 实测）。
        print("  · 首页卡片管理：这页没有列出卡片，没有可关的开关", flush=True)
    p.back()
    nav.tap(p, rt, "搜索范围")
    nav.close_named(p, rt, SEARCH_SOURCES, "下拉搜索·搜索范围", max_screens=6)
    p.back()
    nav.tap(p, rt, "功能管理")
    nav.close_named(p, rt, ["搜索框提示词"], "下拉搜索·功能管理", max_screens=2)
    p.back()
    nav.tap(p, rt, "消息管理")
    nav.close_named(p, rt, ["消息通知"], "下拉搜索·消息管理", max_screens=2)
    p.back()
    nav.tap(p, rt, "隐私")
    nav.close_named(p, rt, ["个性化推荐"], "下拉搜索·隐私", max_screens=2)


def step_theme(p, rt):
    """主题商店 → 我的 → 设置：服务管理 → 消息与广告；隐私 → 个性化推荐设置。
    「个性化推荐设置」点下去先弹确认框，确认后页面退回「设置」，回读前要重新进一次。
    首页的「检测到新版本」弹窗盖住底部标签栏，关弹窗的动画会把紧跟着的点击吞掉，
    所以每一跳都用会确认换页的 p.enter（#286）。
    「我的」页的「设置」在 17.22 上带通知角标（读作「设置,有1条新通知」），别的版本是纯齿轮，
    两种都要能进——见 open_settings()。"""
    def enter_settings():
        rt.require(nav.open_settings(p, rt), "没找到「设置」入口：文字与右上角图标都试过")

    def to_privacy():
        p.start("com.heytap.themestore")
        p.enter("我的")
        enter_settings()
        p.enter("隐私")

    p.start("com.heytap.themestore")
    p.enter("我的")
    enter_settings()
    p.enter("服务管理")
    p.enter("消息与广告")
    nav.close_named(p, rt, ["消息通知", "开屏广告"], "主题·消息与广告")
    p.back(2)
    to_privacy()
    nav.close_named(p, rt, ["个性化推荐设置"], "主题·个性化推荐", reopen=to_privacy)


def step_game_center(p, rt):
    """游戏中心 → 我的 → 设置 → 隐私开关设置 → 个性化推荐管理。
    「设置」在 14.43.3 上是「我的」页右上角的齿轮图标，没有文字（#292）；旧版是「设置,有新通知」文字行。
    「我的」页还带「页面升级」弹窗，先关掉。"""
    p.start("com.nearme.gamecenter")
    # 底栏点下去被开屏动画吞掉时页面不换，p.tap 照样返回成功，接着就整段失败；换页要确认（#286）。
    p.enter("我的")
    time.sleep(1.2)
    # dismiss() 遇到带滚动列表的页面就不点文字按钮，「页面升级」弹窗的「我知道了」只能点名点。
    if p.find("我知道了", exact=True):
        p.tap("我知道了", exact=True, scrolls=0); time.sleep(1.2)
    else:
        p.dismiss()
    rt.require(nav.open_settings(p, rt, ("隐私开关设置", "隐私")), "没找到设置入口：右上角图标都点过")
    nav.tap(p, rt, "隐私开关设置")
    nav.tap(p, rt, "个性化推荐管理")
    nav.close_named(p, rt, ["个性化推荐"], "游戏中心·个性化推荐")


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)
