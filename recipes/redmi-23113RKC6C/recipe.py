# Redmi K70（23113RKC6C），HyperOS OS3.0.307.0.WNKCNXM / Android 16。
# 2026-10-26 无线调试实测：系统广告段临时开启后关闭，39 秒、调整 1 项、回读确认。
# 其余 8 段已按 K70 实际入口补入；浏览器 2 项、天气 2 项、日历 1 项已实际关闭。
# 浏览器「小说」是功能入口，验证后已从本脚本移除；「最新资讯」为 disabled，无法操作。
# 参考脚本 9 段安全模式实测调整 14 项；最终脚本在有线原生 1440×3200 上复跑 230 秒、0 调整、0 步骤异常（移除小说前的无线复跑为 307 秒）。
# 不能把这份脚本当成整机适配完成。
BUILD = "OS3.0.307.0"
MODELS = ["23113RKC6C"]
import time
from entries import THEME_DEAD_ENDS
VERIFIED_SWITCHES = 0


def tap_any(*names, scrolls=6):
    return any(maybe(name, scrolls) for name in names)
def mine_settings(tries=2):
    """底栏「我的」→ 「设置」，点完必须认出设置页（#586）。

    不校验的话，点击被吞、或点在了别的面板上，都会当成已经进了设置页：后面几页入口全部
    找不到，整段 0 项又不报错。没落进设置页就退回来重开「我的」再点一次，两次都不成就报当前页。"""
    stopped = ""
    for _ in range(tries):
        if not p.tap("我的", exact=True, scrolls=0):
            raise RuntimeError("未找到浏览器「我的」")
        if not p.tap("设置", exact=True, scrolls=0):
            raise RuntimeError("未找到浏览器「设置」")
        if p.in_settings_page():
            return
        stopped = p.focus()
        p.back()
    raise RuntimeError(f"浏览器设置页没有打开；停在 {stopped}")


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("系统广告")
def _():
    system_ads_security()


@step("应用商店")
def _():
    store()


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
    p.start("com.android.browser")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    mine_settings()
    if maybe("主页设置"):
        p.off(only=["宫格位推送"], page="浏览器·主页设置")
        p.back()
    if maybe("搜索设置"):
        p.off(only=["显示猜你想搜模块"], page="浏览器·搜索设置")
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
    weather_calendar_tap()


print(f"\n系统广告段回读确认 {VERIFIED_SWITCHES} 项；步骤异常 {len(FAILED_STEPS)} 个", flush=True)
