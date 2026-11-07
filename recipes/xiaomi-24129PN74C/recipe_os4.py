# HyperOS 4 变体（PR #298）：同型号的 HyperOS 3 路径在 recipe.py（PR #312）。系统版本对上 OS4.0 时由 run.recipe_for 选这份。
# 小米 HyperOS 4 机型脚本：Xiaomi 15（24129PN74C）
# 录制：2026-10-29，系统 OS4.0.0.22.XOCCNXM（CP2A.260605.016），九段实测
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
#
# 与 xiaomi-M154FF（18 Pro Max）的差异，来自 Issue #193：
#   1. 系统广告：隐私与安全 → 更多安全设置 里没有广告服务；广告服务是独立 Activity，可直接拉起
#   2. 应用商店：底部标签文案是「我的，有新消息」，精确匹配「我的」找不到，后面的入口全部走空
#   3. 浏览器：工具栏右上角那个「设置」图标打开的是首页编辑面板；真正的设置在底栏「菜单」里
#   4. 主题、手机管家、下载管理、全局搜索、负一屏、天气日历与参考脚本一致
BUILD = "OS4.0"
MODELS = ["24129PN74C"]
import time
from wait import until

from fast import bounds

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


def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
    重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（#305 / #374）。
    点击后要认出设置页：日历的齿轮会打开一个 PopupWindow，不校验就会在弹窗里找入口（#407）。"""
    from fast import bounds, icon_hit

    def open_settings():
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

    before = p.focus()
    if not open_settings():
        return False
    if p.in_settings_page():
        return True
    if p.focus() != before:
        p.back()          # 点开的是弹窗或别的页：关掉，别留给下一段（#331 / #407）
    return False


def tap_any(*names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(n, scrolls) for n in names)


def maybe(name, scrolls=6):
    """可选入口：有就点，没有不报「走丢」。"""
    return p.entry(name, scrolls=scrolls)


def popup_row(text, timeout=3.0):
    """屏幕下半段里文字正好是 text 的那一行：菜单弹窗从底部升起，工具栏上的同名图标在上半屏。"""
    def row():
        for t, (l, top, r, b), _n in p.texts():
            if t == text and top > p.H * 0.3:
                return (l + r) // 2, (top + b) // 2
        return None
    return until(row, timeout=timeout, poll=0.3, now=time.time, sleep=time.sleep)


def menu_settings(tries=2):
    """底栏「菜单」→ 弹窗里的「设置」，点完必须认出设置页（#586）。

    工具栏右上角也有一个叫「设置」的图标，点它打开的是首页编辑面板（页面布局 / 快捷网址 / 全网热榜）。
    只点下半屏那一行；没落进设置页就退回来重开菜单再试，两次都不成就报当前页，不在面板上继续找。"""
    stopped = ""
    for _ in range(tries):
        if not p.tap("菜单", exact=True, scrolls=0):
            raise RuntimeError("浏览器底栏「菜单」未找到")
        xy = popup_row("设置")
        if not xy:
            raise RuntimeError(f"浏览器菜单里没有「设置」；停在 {p.focus()}")
        before = p.sig()
        p.click(*xy)
        p.settle(before, 1.5)
        if p.in_settings_page():
            return
        # 弹窗这一行在屏上才走到这里，所以按返回是收起弹窗或退出面板，不会离开浏览器首页
        stopped = p.focus()
        p.back()
    raise RuntimeError(f"浏览器设置页没有打开；停在 {stopped}")


def gear_top():
    """只认右上角那个文字就是「设置」的齿轮。

    应用商店「我的」页有一条「去功能设置里重新开启」，含「设置」二字且可点，通用 gear() 会先命中它，
    点开的是手机清理的功能页——这就是 #193 里商店四个入口全部找不到的真正原因。
    """
    for n in p.tree().iter("node"):
        t = (n.get("text") or n.get("content-desc") or "").strip()
        if t != "设置" or n.get("clickable") != "true" or not p.on_screen(n):
            continue
        l, top, r, b = bounds(n)
        if b < p.H * 0.25 and (l + r) // 2 > p.W * 0.7:
            p.click((l + r) // 2, (top + b) // 2)
            time.sleep(1)
            return True
    return False


@step("系统广告")
def _():
    # 这台没有「隐私与安全 → 更多安全设置 → 广告服务」这条路：更多安全设置里只有用户体验计划等项目，
    # 广告服务是 com.android.settings 的独立 Activity，直接拉起最稳，也不再受设置首页滚动位置影响。
    p.start("com.android.settings", ".ad.AdServiceSettings")
    p.off(only=["个性化广告推荐"], page="系统·广告服务")
    p.back()


@step("应用商店")
def _():
    # 上次停在应用详情页时 start 会复用旧任务，先停掉
    p.d.shell("am force-stop com.xiaomi.market"); time.sleep(1)
    p.start("com.xiaomi.market")
    # 冷启动首页要几秒才渲染完，底栏还没出来就点会扑空（3 秒窗口实测不够，整段会空跑 65 秒）
    for _ in range(24):
        if p.find("我的，有新消息", exact=True, edge_ok="tab", nav=True):
            break
        time.sleep(0.5)
    # 底部标签的 content-desc 是「我的，有新消息」，精确匹配「我的」找不到（#193 四个入口全空的起点）。
    # 上次退出停在「我的」页、或首页被促销弹窗挡住时，这个标签读不到；先探测再点，免得留下假失败日志。
    p.miss = 0
    if p.find("我的，有新消息", exact=True, edge_ok="tab", nav=True):
        p.tap("我的，有新消息", exact=True, scrolls=0)
    elif p.find("我的", exact=False, edge_ok="tab", nav=True):
        p.tap("我的", exact=False, scrolls=0)
    time.sleep(1.5)
    if not gear_top():
        raise RuntimeError("商店「我的」页右上角齿轮未找到")
    if maybe("隐私设置") or maybe("隐私"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    # 不碰「模式切换 → 极简模式」：那是把商店首页整个换成极简布局，属于机主看得见的外观改动，
    # 不是关广告开关。参考脚本这么做是为了少几个推荐位，但脚本不该替机主改界面。
    if maybe("通知设置"):
        # 只关「新手帮助」。这台的通知设置没有「推送消息」总开关，只有 4 个独立项，别的一律不碰
        p.off(only=["新手帮助"], keep=["应用更新通知", "点赞消息", "评论消息"], page="商店·通知设置"); p.back()
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
    p.start("com.android.providers.downloads.ui")
    if not gear():
        raise RuntimeError("下载管理设置入口未找到")
    if maybe("信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    # 桌面入口在 themestore，打开后转到 thememanager；后者本身没有 LAUNCHER
    if "package:" in p.d.shell("pm path com.miui.themestore").output:
        p.start("com.miui.themestore", foreground="com.android.thememanager")
    else:
        # 没有主题商店时直接起 thememanager：它没有 LAUNCHER activity，monkey 拉不起来（#730）
        if "package:" not in p.d.shell("pm path com.android.thememanager").output:
            print("  · 本机没有主题商店，跳过"); return
        p.start("com.android.thememanager", ".ThemeResourceProxyTabActivity")
    p.go("我的", "设置")
    gear()
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # p.start 是「先 app_stop 再起，5 秒内前台必须是本包」。这台冷启动能起，但 start 内部的弹窗清理
    # 会把它顶掉，报「启动后离开前台」（#193 同一条）。这里直接拉起，前台实测 1 秒就稳定。
    p.d.shell("am force-stop com.android.browser"); time.sleep(1)
    p.d.shell("monkey -p com.android.browser -c android.intent.category.LAUNCHER 1")
    time.sleep(3)
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    # 底栏按钮是 ViewGroup，只认 80 毫秒短按；input tap 点了没反应
    # 工具栏右上角也有一个叫「设置」的图标，点它打开的是首页编辑面板（页面布局/快捷网址/全网热榜）；
    # 菜单里那个在同一行（头像/菜单编辑/分享/设置），menu_settings() 按 y 坐标排除顶部那个。
    menu_settings()
    if maybe("隐私和安全", scrolls=6):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    p.back(2)


@step("全局搜索")
def _():
    HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]
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
        p.start(pkg)
        if pkg == "com.miui.weather2" and p.find("城市管理", exact=True, edge_ok="tab"):
            # 新版天气：底部城市管理 → 右上更多设置 → 设置。
            p.tap("城市管理", exact=True, scrolls=0)
        if not gear():
            print("  · 本版本没有可识别的设置菜单，跳过"); continue
        if maybe("用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page=f"{pkg}·用户体验计划"); p.back()
        p.back(3)
