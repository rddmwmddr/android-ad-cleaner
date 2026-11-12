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
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    time.sleep(1.2)
    require(p.tap("隐私与安全", exact=True, scrolls=6), "未找到「隐私与安全」")
    require(security_tab(), "未识别「安全」标签")
    require(p.tap("更多安全设置", exact=True, scrolls=6), "未找到「更多安全设置」")
    require(p.tap("广告服务", exact=True, scrolls=6), "未找到「广告服务」")
    close_named(["个性化广告推荐"], "系统·广告服务")


@step("应用商店")
def _():
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    gear()
    if tap_any("隐私设置", "隐私"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务", "个性化推荐"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它会连带关闭点赞/评论等消息。
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置")
        p.back()
    p.back(2)


@step("手机管家")
def _():
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="管家·隐私")
        p.back()
    if maybe("垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理")
        p.back()
    p.back(2)


@step("下载管理")
def _():
    p.start("com.android.providers.downloads.ui")
    if not gear():
        raise RuntimeError("下载管理设置入口未找到")
    if maybe("信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


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
    if not p.go("我的", "设置"):
        raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
    if not gear():
        raise RuntimeError("主题设置入口没找到；" + p.page_evidence())
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
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if maybe("首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if maybe("应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐")
            p.back()
        if maybe("热搜榜单"):
            subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
            if p.switches():
                p.off(only=HOT, page="搜索·热搜榜单")
            if subs:
                p.top()
                for x in subs:
                    if maybe(x):
                        p.off(only=HOT, page=f"搜索·热榜·{x}")
                        p.back()
            p.back()
        p.back()
    p.back(2)


@step("负一屏")
def _():
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私")
        p.back()
    p.back()


@step("天气和日历")
def _():
    p.start("com.miui.weather2")
    if p.tap("更多设置", exact=True, scrolls=0):
        time.sleep(1.2)
        if p.tap("设置", exact=True, scrolls=0):
            time.sleep(1.2)
            if p.tap("用户体验计划", exact=True, scrolls=6):
                time.sleep(1.0)
                p.off(only=["天气视频卡片", "内容推广"], page="天气·用户体验计划")
                p.back()
            p.back(2)
    p.start("com.android.calendar")
    if p.tap("设置", exact=True, scrolls=0):
        time.sleep(1.0)
        if p.tap("设置", exact=True, scrolls=0):
            time.sleep(1.2)
            if p.tap("用户体验计划", exact=True, scrolls=6):
                time.sleep(1.0)
                p.off(only=["内容推广"], page="日历·用户体验计划")
                p.back()
            p.back(2)


print(f"\n系统广告段回读确认 {VERIFIED_SWITCHES} 项；步骤异常 {len(FAILED_STEPS)} 个", flush=True)
