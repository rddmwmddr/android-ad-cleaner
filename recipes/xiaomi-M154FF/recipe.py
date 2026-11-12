# 小米 HyperOS 4 机型脚本：Xiaomi 18 Pro Max（M154FF）、Xiaomi 18 Fold（2608BPX34C）、REDMI K90（2510DRK44C）
# 路径来源：18 Pro Max 2026-10-22 实测（OS4.0.24）；18 Fold 2026-10-24 社区实测（Issue #2，CP2A.260605.016）。
# 三台系统底包相同（CP2A.260605.016），App 版本不同时页面不同：每一步都兼容新旧两种入口，找不到就跳过。
# K90（OS4.0.5.0.XPKCNXM）按 2026-11-10 社区实测登记（Issue #929）：借这份脚本跑通九段中的八段，
# 主题段要先挂起 com.miui.systemAdSolution；本仓库未在该机复跑。
# 登记的含义是这台机先按本型号直选（recipe_for），不再转去按版本挑同族脚本——#969 修完也一样。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS4.0"
MODELS = ["M154FF", "2608BPX34C", "2510DRK44C"]
import time
from entries import THEME_DEAD_ENDS

# 注入面的 opened() 从这里取 adb_link.DeviceLost
import adb_link


def browser_settings():
    """先看工具栏，再点底部「我的」；不把资讯正文里的「我的」当导航标签。"""
    before = p.focus()
    if gear(toolbar_only=True):
        if p.in_settings_page():          # 点完要认出设置页，点击被吞时别在旧页上找入口（#331）
            return True
        if p.focus() != before:
            p.back()
    for text, (l, t, r, b), node in p.texts():
        if text == "我的" and t >= p.H * 0.65:
            before = p.sig()
            p.click((l + r) // 2, (t + b) // 2)
            p.settle(before, 1.5)
            return gear()
    return False


@step("系统广告")
def _():
    if opened(lambda: p.start("com.android.settings", ".ad.AdServiceSettings", expect="个性化广告推荐", budget=2)):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")
        return
    # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not maybe("隐私与安全"):
        return
    # 18 Pro Max（OS4.0.24）：隐私与安全 → 更多安全设置；18 Fold：隐私与安全 → 安全 → 更多安全设置
    if not maybe("更多安全设置"):
        if maybe("安全", scrolls=3):
            maybe("更多安全设置")
    if maybe("广告服务"):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    if not opened(lambda: p.start("com.xiaomi.market", ".ui.MarketPreferenceActivity", expect="通知设置", budget=2)):
        p.start("com.xiaomi.market")
        p.go("我的", "设置")
        gear()
    if tap_any("隐私设置", "隐私"):
        # 4.129.s.00 的「个性化服务」是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("模式切换"):                       # 新版商店没有这一项
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连「点赞消息」「评论消息」一起关（Issue #2）
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


@step("手机管家")
def _():
    security_center()


@step("下载管理")
def _():
    downloads_probe()


@step("主题")
def _():
    theme()


@step("浏览器")
def _():
    # 首页「默认 / 探索版 / 自定义主页」不改：自定义主页要填网址，按机主喜好
    # 设置页都有导出，直达：后台屏上首页的工具栏和底栏认不出来，走菜单会报「入口未找到」（#667）
    if opened(lambda: p.start("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity", expect="个性化内容推荐", budget=2)):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
        # 子项页老版本可能没导出：打不开只跳过下面三项，不让整段报未完成
        opened(lambda: p.start("com.android.browser", ".BrowserSettingsActivity"))
    else:
        p.start("com.android.browser")
        if "basicmode" in p.focus().lower():
            # 拒绝浏览器协议后落到基本模式设置页，四个设置入口都不在这条路径上，找下去只会报「入口未找到」（#414）
            print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
            return
        if not browser_settings():
            raise RuntimeError("浏览器设置入口未找到；未点击正文中的文字")
        if maybe("隐私和安全"):
            p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if maybe(page):                           # 新版浏览器这三项都没有，有就关
            p.off(only=only, page=f"浏览器·{page}"); p.back()
    p.back(2)


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("全局搜索")
def _():
    global_search()


@step("负一屏")
def _():
    negative_screen()


@step("天气和日历")
def _():
    weather_calendar_probe()
