# 小米 HyperOS 2 平板机型脚本：Xiaomi Pad 7（2410CRP4CC）
# 路径来源：2026-10-28 实机录制（OS2.0.208.0.VOZCNXM / Android 15，3200×2136 横屏）。
# 平板设置是左右分栏，左侧菜单要单独滚动；脚本改用直达 Activity，避免滚错栏位。
# 本版本已实测没有可关项的入口：手机管家、下载管理、主题、全局搜索、天气。
# 日历首次启动要求本人同意隐私协议，脚本不代为同意，因此未纳入。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS2.0.208"
MODELS = ["2410CRP4CC"]
import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []


def step(name):
    def deco(f):
        if (not ONLY or name in ONLY) and p.locked():
            print(f"\n== {name}：手机锁屏了，后面的都不跑"); return f
        if not ONLY or name in ONLY:
            print(f"\n== {name}"); p.miss = 0
            t = time.time()
            try:
                f()
            except Exception as e:
                FAILED_STEPS.append(name)
                print(f"  ✗ 未完成：{e}")
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


def maybe(name, scrolls=6):
    """可选入口：有就点，没有不报「走丢」。"""
    return p.entry(name, scrolls=scrolls)


def tap_any(*names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(n, scrolls) for n in names)


@step("系统广告")
def _():
    # 平板设置首页是左右分栏，左侧菜单需要单独滚动；直达广告服务页最稳
    p.start("com.android.settings", ".ad.AdServiceSettings")
    p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    # 平板商店从 MarketTabActivity 直接进，避开冷启动时的 FloatWebActivity 空白页
    p.start("com.xiaomi.market", ".ui.MarketTabActivity")
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("应用商店顶部「我的」未找到")
    if not maybe("设置", scrolls=8):
        raise RuntimeError("应用商店设置入口未找到")
    if maybe("通知设置"):
        # 只关「新手帮助」；「推送消息」是父开关，关了会连带点赞 / 评论消息
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    if tap_any("隐私设置", "隐私"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    p.back(2)


@step("浏览器")
def _():
    # 个性化推荐设置是独立 Activity，平板和手机都在这个页面
    p.start("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity")
    p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
    p.back(2)
    p.start("com.android.browser", ".BrowserSettingsActivity")
    if maybe("主页设置"):
        p.off(only=["宫格位推送"], page="浏览器·主页设置"); p.back()
    # 平板版没有「猜你想搜」「小说」，保留这两段兼容以后版本
    for page, only in [("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if maybe(page):
            p.off(only=only, page=f"浏览器·{page}"); p.back()
    p.back(2)


@step("负一屏")
def _():
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框保留
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
    p.back()
