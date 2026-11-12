# 小米 HyperOS 4 机型脚本：REDMI K90 Ultra（M332BF）
# 路径来源：社区报告者 @Sin1ery 2026-10-31 实测（HyperOS OS4.0.4.0.XHPCNXM，Android 17，Issue #374）。
# 脚本按那份报告里的四处差异重写，本仓库尚未在这台机器上复跑，合并后等报告者复测。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS4.0.4"
MODELS = ["M332BF"]
import time
from entries import THEME_DEAD_ENDS

# 注入面的 opened() 从这里取 adb_link.DeviceLost
import adb_link


def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：主题商店的「设置壁纸」也含「设置」，
    按包含匹配会先命中它、点进壁纸页，整段跑空（沿用 #305 的做法）。"""
    from fast import bounds, icon_hit

    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        icon = "ImageView" in n.get("class", "") and r-l < p.W * 0.25 and b-t < p.H * 0.15
        if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n) and (not toolbar_only or b < p.H * 0.23):
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    if not toolbar_only and p.find("设置", exact=True, edge_ok="tab"):
        return p.tap("设置", exact=True, scrolls=0)
    # 下载管理、天气和日历的齿轮藏在右上「更多」菜单里。
    for n in p.tree().iter("node"):
        key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
        l, t, r, b = bounds(n)
        if any(k in key.lower() for k in ("更多", "more", "menu")) and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22:
            p.click((l + r) // 2, (t + b) // 2); time.sleep(0.5)
            if p.tap("设置", exact=True, scrolls=0):
                return True
            break
    return False


@step("系统广告")
def _():
    # 广告服务在「安全」分栏 →「更多安全设置」页底，直达 AdServiceSettings 从 50 秒降到 2 秒（#374）。
    # 不走 p.start()：这一页的开关说明行是「关闭后，广告数量不会因此减少……」，
    # 启动后的 dismiss() 会把整行 content-desc 当成弹窗 ✕ 点一下，等于替用户拨了一次开关。
    p.d.shell("am start -f 0x10008000 -n com.android.settings/.ad.AdServiceSettings")
    if not p.expect_page("个性化广告推荐", 3):
        raise RuntimeError("广告服务页没有打开")
    p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    if not opened(lambda: p.start("com.xiaomi.market", ".ui.MarketPreferenceActivity", expect="通知设置", budget=2)):
        p.start("com.xiaomi.market")
        # 底栏用 p.tab：内容区有叫「我的」的游戏，p.go 会先命中它（沿用 #386 的做法）
        before = p.sig()
        if not p.tab("我的"):
            raise RuntimeError("商店底部「我的」标签没找到")
        p.settle(before, 2)
        gear()
    if tap_any("隐私设置", "隐私"):
        # 「个性化服务」是子页入口，开关在下一层（#374）。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连「点赞消息」「评论消息」一起关（Issue #2）
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


@step("手机管家")
def _():
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
    if maybe("垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
    p.back(2)


@step("下载管理")
def _():
    if opened(lambda: p.start("com.android.providers.downloads.ui", ".activity.InfoFlowSettingActivity", expect="资源推荐", budget=2)):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
        p.back()
        return
    p.start("com.android.providers.downloads.ui")
    if not gear():
        raise RuntimeError("下载管理设置入口未找到")
    if maybe("信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    # 直达主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；经主题商店冷启动
    # 还要过一道重定向过渡窗，前台校验容易误判（#906）。落点被系统转走时仍按跳过收尾。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    tap_sig = p.sig()
    if not p.tab("我的"):
        raise RuntimeError("主题底部「我的」标签没找到；" + p.page_evidence())
    p.settle(tap_sig, 2)
    # 导航失败以前与「本页没有目标开关」同形：三步都校验，报错带页面现场（#906）。
    if not gear():                              # 精确认「设置」，不点「设置壁纸」（沿用 #305 的做法）
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
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # 工具栏齿轮点进去是首页编辑面板（页面布局 / 快捷网址 / 全网热榜），主设置页是
    # com.android.browser/.BrowserSettingsActivity（#374）。关「个性化内容推荐 / 个性化广告推荐」
    # 各弹一次「关闭提醒」，必须点「确认关闭」，点「以后再说」等于没关；确认框由 p.off() 处理。
    p.start("com.android.browser", ".BrowserSettingsActivity", expect="设置", budget=2)
    if maybe("隐私和安全"):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if maybe(page):                           # 新版浏览器这三项不一定都在，有就关
            p.off(only=only, page=f"浏览器·{page}"); p.back()
    p.back(2)


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("全局搜索")
def _():
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if maybe("首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if maybe("应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐"); p.back()
        if maybe("热搜榜单"):
            subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
            if p.switches():
                p.off(only=HOT, page="搜索·热搜榜单")
            if subs:
                p.top()
                for x in subs:
                    if maybe(x):
                        p.off(only=HOT, page=f"搜索·热榜·{x}"); p.back()
            p.back()
        p.back()
    p.back(2)


@step("负一屏")
def _():
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框、出行助手保留
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
    p.back()


@step("天气和日历")
def _():
    for pkg in ("com.miui.weather2", "com.android.calendar"):
        if pkg == "com.android.calendar" and opened(lambda: p.start("com.android.calendar", ".settings.UserExperienceActionBarActivity", expect="内容推广", budget=2)):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page=f"{pkg}·用户体验计划"); p.back()
            continue
        p.start(pkg)
        if pkg == "com.miui.weather2" and p.find("城市管理", exact=True, edge_ok="tab"):
            # 新版天气：底部城市管理 → 右上更多设置 → 设置。
            p.tap("城市管理", exact=True, scrolls=0)
        if not gear():
            print("  · 本版本没有可识别的设置菜单，跳过"); continue
        if maybe("用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page=f"{pkg}·用户体验计划"); p.back()
        p.back(3)
