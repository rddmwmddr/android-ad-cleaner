# Xiaomi 15（24129PN74C），HyperOS OS3.0.307.0.WOCCNXM / Android 16，底包 BP2A.250605.031.A3。2026-10-29 无线调试（192.168.2.147:5555）实测：底包与 recipes/xiaomi/25060RK16C 完全一致，
from recipe_kit import step
# 但浏览器和商店的入口结构不同，按本机实测路径写。
#
# 本机实测到的入口（与 M154FF / K80 脚本的差异）：
#  · 系统广告：设置里搜不到「更多安全设置」，「隐私与安全」是权限中心没有那一项。
#    可用路径：设置搜索「广告服务」→ 结果页 → 或深链 com.android.settings/.ad.AdServiceSettings。
#    实测「个性化广告推荐」出厂就是关的（核对 1 项、调整 0 项）。
#  · 应用商店：底部「我的」→ 顶部「设置」→ 滚到底。这版没有「隐私设置/个性化服务」，
#    也没有「秒装」；「其他功能」只是分类标题不是入口。设置页可见的是
#    通知设置、极速下载、模式切换、自动升级、WLAN 加速。
#  · 浏览器 20.29.1031010：底栏是 主页/视频/AI搜索/菜单/我的，入口是
#    底部「菜单」→ 弹窗右上「设置」（不是底栏「我的」）；底栏没有「菜单」的机型
#    （MIX Flip 2）在「我的」页里找设置（#833）。两条入口都对时序敏感，先试直达设置页
#    `com.android.browser/.BrowserSettingsActivity`，通不过才走这两条（#912）。
#    「隐私和安全」在设置页最底部，要滚 8 屏才看得到，脚本用 scroll_more 往下翻。
#    实测默认开着的广告项只有「显示猜你想搜模块」（搜索设置）和「运营任务」（功能设置）；
#    「个性化内容推荐」「个性化广告推荐」「小说」「宫格位推送」出厂就是关的。
#  · 下载管理：右上「更多」按钮 → 弹窗里的「设置」→ 信息流设置。
#    实测「资源推荐」「热榜推荐」出厂就是关的。
#  · 手机管家：垃圾清理设置里「推荐内容」出厂就是关的；「个性化推荐」在隐私设置里，实测已关。
#  · 主题：每次联网时通知实测已关；隐私设置「个性化推荐」出厂就是关的。
#
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
# BUILD 写 ROM 版本、不写底包：底包被多台同代小米机共用，写进 BUILD 会让它们都被选到这份脚本（#942）。
BUILD = "OS3.0.307.0"
MODELS = ["24129PN74C"]
import time
from dataclasses import replace
from entries import ENTRIES, THEME_DEAD_ENDS, reach
# 回读确认数由引擎经 rt 记录

# 本机的齿轮入口点完要认出设置页（日历的齿轮开的是 PopupWindow，沿用 #407）；
# 浏览器入口是底栏「菜单」→ 弹窗「设置」，回退到「我的」+齿轮（沿用 #833）。两处走法由家族库按这两个常量选。
GEAR_STYLE = "checked"
BROWSER_FLOW = "menu"

# 浏览器段的入口页是设置页本身。分组里的另一条直达是「个性化推荐设置」子页：直接落过去时
# 后面几个设置页入口都找不到、整段 0 项空跑，所以回退链只取设置页那一条（#912）。
_BROWSER = ENTRIES["xiaomi"]["浏览器"]
BROWSER_SETTINGS_ENTRY = replace(
    _BROWSER, direct=tuple(d for d in _BROWSER.direct if d.activity == ".BrowserSettingsActivity"))


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("系统广告")
def _():
    # 本机「隐私与安全」是权限中心，没有「更多安全设置」。用设置搜索直达「广告服务」。
    if not p.setting("广告服务"):
        # 搜索不可用时用深链兜底。
        p.d.shell("am start -f 0x10008000 -n com.android.settings/.ad.AdServiceSettings")
        time.sleep(1.5)
    close_named(["个性化广告推荐"], "系统·广告服务")
    p.back()


@step("应用商店")
def _():
    # 2026-10-29 实测：冷启动落「福利推广页」→ 先回首页。
    # 「我的」用 p.tab()：底部带过滤把内容区里同名的文字挡在外面（#386）。
    p.start("com.xiaomi.market")
    time.sleep(2.5)
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0)
        time.sleep(2)
    require(p.tab("我的"), "商店底部「我的」标签没找到")
    time.sleep(2)
    require(p.tap("设置", exact=True, scrolls=4), "商店设置图标没找到")
    time.sleep(1)
    # 本版没有「隐私设置/个性化服务」和「秒装」，有就关，没有就跳过。
    if maybe("隐私设置"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务", "个性化推荐"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞/评论消息一起关。
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置")
        p.back()
    # 模式切换：保持标准模式，不切极简。
    p.back(2)


@step("手机管家")
def _():
    security_center()


@step("下载管理")
def _():
    downloads_tap()


@step("主题")
def _():
    # 直达主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；经主题商店冷启动
    # 要过一道重定向过渡窗，前台校验容易误判，也可能续在上次留下的子页上（#906）。
    # 落点被系统转去商店详情页或桌面时仍按跳过收尾。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    # 导航失败以前与「本页没有目标开关」同形：进「我的」、进设置页、点名开关三步都校验，
    # 0 个开关按失败报并带页面现场（#906）。
    theme_settings()
    p.await_page()                              # 齿轮点完这一页可能还没画完
    before = {}
    for _ in range(2):                          # 行也可能在首屏之下，off() 自己会翻页找
        before.update({title: on for title, on, _ in p.switches()})
        if not p.scroll_more():
            break
    p.top(2)
    require_switches(before, ["每次联网时通知"], "主题·设置", contains=True)
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私")
        p.back()
    p.back(2)


@step("浏览器")
def _():
    # 入口顺序：直达设置页 → 底部「菜单」→ 弹窗「设置」→ 底栏「我的」→ 齿轮（#912；后两档沿用 #833）。
    # 基本模式的机型直达会落到 BasicModeSettingActivity，落点校验判不过，仍走到下面的跳过（#414）。
    if not direct_settings():
        p.start("com.android.browser")
        if "basicmode" in p.focus().lower():
            # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
            print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
            return
        time.sleep(2)
        browser_settings()
    # 「隐私和安全」在设置页最底部（实测要滚 8 屏），往下翻着找。
    if maybe("隐私和安全", scrolls=12):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全")
        p.back()
    if maybe("主页设置"):
        p.off(only=["宫格位推送"], page="浏览器·主页设置")
        p.back()
    if maybe("搜索设置"):
        # 扫一扫、搜索历史、书签、最常访问是功能项，保留。
        p.off(only=["显示猜你想搜模块"], page="浏览器·搜索设置")
        p.back()
    if maybe("功能设置"):
        # 「运营任务」= 做任务得金币挣红包，纯营销；「我的网盘」是用户功能，保留。
        p.off(only=["运营任务", "小说"], keep=["我的网盘"], page="浏览器·功能设置")
        p.back()
    p.back(2)


@step("全局搜索")
def _():
    global_search()


@step("负一屏")
def _():
    negative_screen()


@step("天气和日历")
def _():
    # 2026-10-29 实测：天气有「用户体验计划」，里面「天气视频卡片」默认开着。
    # 日历的齿轮打开的是 PopupWindow（#407 真机焦点），不是设置页，gear() 校验落点后跳过。
    p.start("com.miui.weather2")
    time.sleep(2)
    if not (gear(toolbar_only=True) or gear()):
        print("  · 天气没有可识别的设置入口，跳过")
    else:
        if maybe("用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page="天气·用户体验计划")
            p.back()
        p.back(3)
    p.start("com.android.calendar")
    time.sleep(2)
    if not (gear(toolbar_only=True) or gear()):
        print("  · 日历没有可识别的设置入口，跳过")
    else:
        if maybe("用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划")
            p.back()
        p.back(3)


def tail():
    print(f"\n回读确认 {rt.verified} 项；步骤异常 {len(rt.failed_steps)} 个", flush=True)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import maybe, p, require, require_switches, rt, start_or_skip
    from recipe_nav import browser_settings, close_named, direct_settings, gear, theme_settings
    from recipe_steps import downloads_tap, global_search, negative_screen, security_center
