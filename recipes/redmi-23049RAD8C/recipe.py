# Redmi Note 12 Turbo（23049RAD8C，HyperOS 1 / OS3.0.5.0）机型脚本
# 适配机型：Redmi Note 12 Turbo（23049RAD8C）
# 路径来源：2026-10-25 实测（OS3.0.5.0.VMRCNXM，Android 15）
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS3.0.5.0"
MODELS = ["23049RAD8C"]
import time
from entries import THEME_DEAD_ENDS


@step("系统广告")
def _():
    # 1. 广告服务直达页
    try:
        p.start("com.android.settings", "com.android.settings.ad.AdServiceSettings")
        p.off(only=["个性化广告推荐"], page="系统·广告服务")
    except Exception:
        pass
    # 2. 系统广告（系统工具广告）
    if not p.setting("系统广告"):
        raise RuntimeError("没搜到「系统广告」")
    p.off(only=["系统工具广告"], page="系统·系统工具广告")


@step("应用商店")
def _():
    # 直达设置页，避免从首页弹窗或“我的”页面图标迷路
    try:
        p.start("com.xiaomi.market", "com.xiaomi.market.ui.MarketPreferenceActivity")
    except SkipStep:
        raise                     # App 本机没装：放行，由段包装记跳过，别退到「我的 → 设置」再空跑（#908）
    except Exception:
        p.start("com.xiaomi.market")
        p.go("我的", "设置")
        gear()
    if tap_any("隐私设置", "隐私"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("模式切换"):
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if maybe("通知设置"):
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


@step("手机管家")
def _():
    security_center()


@step("下载管理")
def _():
    downloads()


@step("主题")
def _():
    theme()


@step("浏览器")
def _():
    # 直达设置页
    p.start("com.android.browser", "com.android.browser.BrowserSettingsActivity")
    if maybe("隐私和安全"):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if maybe(page):
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
    # 1. 天气
    p.start("com.miui.weather2")
    if p.tap("更多设置", exact=True, scrolls=0) or gear():
        if p.tap("设置", exact=True, scrolls=0):
            if maybe("用户体验计划"):
                p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page="天气·用户体验计划"); p.back()
            p.back()
    p.back(2)

    # 2. 日历（直达用户体验计划）
    try:
        p.start("com.android.calendar", ".settings.UserExperienceActionBarActivity")
        p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划")
        p.back(2)
    except SkipStep:
        raise                     # App 本机没装：放行，由段包装记跳过（#908）
    except Exception:
        p.start("com.android.calendar")
        gear()
        if maybe("用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划"); p.back()
        p.back(2)
