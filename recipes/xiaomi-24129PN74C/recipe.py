# Xiaomi 15（24129PN74C），HyperOS OS3.0.307.0.WOCCNXM / Android 16，底包 BP2A.250605.031.A3。
# 2026-10-29 无线调试（192.168.2.147:5555）实测：底包与 recipes/redmi-25060RK16C 完全一致，
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
from wait import until
VERIFIED_SWITCHES = 0

# 浏览器段的入口页是设置页本身。分组里的另一条直达是「个性化推荐设置」子页：直接落过去时
# 后面几个设置页入口都找不到、整段 0 项空跑，所以回退链只取设置页那一条（#912）。
_BROWSER = ENTRIES["xiaomi"]["浏览器"]
BROWSER_SETTINGS_ENTRY = replace(
    _BROWSER, direct=tuple(d for d in _BROWSER.direct if d.activity == ".BrowserSettingsActivity"))


def tap_any(*names, scrolls=6):
    return any(maybe(name, scrolls) for name in names)


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

    工具栏右上角也有一个叫「设置」的图标，弹窗还没画出来时按文字点会落到它上面、进首页编辑面板，
    后面几页入口全部找不到，整段 0 项又不报错。所以只点下半屏那一行，且没落进设置页就退回来
    重开菜单再试；两次都不成就报当前页，不在工具栏面板上继续找。
    底栏没有「菜单」的机型（MIX Flip 2）返回 False，交给 browser_settings() 的「我的」入口（#833）。"""
    stopped = None
    for _ in range(tries):
        if not p.tap("菜单", exact=True, scrolls=0, quiet=True):
            if stopped is None:
                return False
            raise RuntimeError("浏览器设置页没有打开；" + p.page_evidence())
        xy = popup_row("设置")
        if not xy:
            raise RuntimeError("浏览器菜单里没有「设置」；" + p.page_evidence())
        before = p.sig()
        p.click(*xy)
        p.settle(before, 1.5)
        if p.in_settings_page():
            return True
        # 弹窗这一行在屏上才走到这里，所以按返回是收起弹窗或退出面板，不会离开浏览器首页
        # focus 读不出前台时是空串，别让它被当成「还没进过弹窗」
        stopped = p.focus()
        p.back()
    raise RuntimeError("浏览器设置页没有打开；" + p.page_evidence())


def browser_settings():
    """底栏「菜单」→ 弹窗「设置」；底栏没有「菜单」的机型在「我的」页里找设置（#833）。

    借这份脚本的机型底栏布局不同：Xiaomi 15 是 主页/视频/AI搜索/菜单/我的，MIX Flip 2 是
    主页/视频/AI搜索/免费小说/我的。两条入口点完都要认出设置页；「我的」那条没进去时报出
    停在哪一页，不在旧页上继续找「隐私和安全」等子项（#586）。"""
    if menu_settings():
        return
    print("  · 底栏没有「菜单」，改走「我的」→ 设置", flush=True)
    if not p.tab("我的"):
        raise RuntimeError("浏览器底部没有「菜单」，也没有「我的」标签；" + p.page_evidence())
    p.dismiss()                       # 「我的」页可能先弹一键登录框，盖住齿轮
    if not gear():
        raise RuntimeError("浏览器设置页没有打开；" + p.page_evidence())


def direct_settings():
    """浏览器设置页能直达就直达（#912）。

    直达档取自 entries 的浏览器分组，只试直达不试设置搜索：设置搜索会离开浏览器、落到
    系统设置里，拿到的不是这一页。直达不通返回 False，由调用方按「菜单」→「我的」回退。
    报告者实测那两条回退对时序敏感：点完底栏「我的」立刻点「设置」会点空，隔 0.2 秒才稳。"""
    if reach(p, BROWSER_SETTINGS_ENTRY, allow_search=False) != "direct":
        return False
    print("  · 直达浏览器设置页", flush=True)
    return True


def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
    重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（#305 / #374）。
    点击后要认出设置页：日历的齿轮会打开一个 PopupWindow，不校验就会在弹窗里找入口（#407）。"""
    from fast import bounds, icon_hit

    def open_settings():
        for n in p.tree().iter("node"):
            l, t, r, b = bounds(n)
            icon = "ImageView" in n.get("class", "") and r - l < p.W * 0.25 and b - t < p.H * 0.15
            if (icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n)
                    and (not toolbar_only or b < p.H * 0.23)):
                p.click((l + r) // 2, (t + b) // 2)
                time.sleep(1)
                return True
        if not toolbar_only and p.find("设置", exact=True, edge_ok="tab"):
            return p.tap("设置", exact=True, scrolls=0)
        for n in p.tree().iter("node"):
            key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
            l, t, r, b = bounds(n)
            if (any(k in key.lower() for k in ("更多", "more", "menu"))
                    and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22):
                p.click((l + r) // 2, (t + b) // 2)
                time.sleep(0.5)
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


def read_switches(max_screens):
    current = {}
    for index in range(max_screens):
        current.update({title: on for title, on, _ in p.switches()})
        if index + 1 == max_screens or not p.scroll_more():
            break
    return current


def close_named(names, page, max_screens=2):
    """只关闭点名的开关；操作前确认目标存在，操作后回读，并检查其他开关未被改动。
    开关标题可能附带整段说明，所以按关键词匹配，不做完整标题相等判断。
    目标本来就已经是关的，算核对通过，不算调整。"""
    global VERIFIED_SWITCHES
    p.top(max_screens)
    before = read_switches(max_screens)
    targets = [title for title in before if any(name in title for name in names)]
    require_switches(before, names, page, contains=True)
    p.top(max_screens)
    p.off(only=names, page=page, max_screens=max_screens)
    p.top(max_screens)
    current = read_switches(max_screens)
    require(all(current.get(title) is False for title in targets), f"{page}：回读未确认关闭")
    require(all(current.get(title) == state for title, state in before.items() if title not in targets),
            f"{page}：其他开关状态变化，请核对")
    VERIFIED_SWITCHES += len(targets)


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
    # 2026-10-29 实测：设置入口在右上「更多」按钮的弹窗里，页面上没有齿轮。
    p.start("com.android.providers.downloads.ui")
    time.sleep(1.5)
    require(p.tap("更多", exact=True, scrolls=0), "下载管理「更多」按钮没找到")
    time.sleep(1.0)
    require(p.tap("设置", exact=True, scrolls=0), "下载管理弹窗里的「设置」没找到")
    time.sleep(1.2)
    if maybe("信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


def settings_icon_visible():
    """「设置」入口进了界面树且可见：只等它出现，点不点得中由 gear() 再判。

    判据是 icon_hit()（与 gear() 同一份），但不管可点性与位置——这两条留给 gear()。"""
    from fast import icon_hit
    return any(icon_hit(n) and p.on_screen(n) for n in p.tree().iter("node"))


def theme_settings(tries=2):
    """主题「我的」→ 顶部「设置」图标，两次都不成才报错（#912）。

    底栏「我的」只有 content-desc（读作「未选中,我的」），内容区另有「我的点赞 / 我的收藏 /
    我的订单」——`go("我的")` 走包含匹配，会先点内容区那一行；`tab()` 只认屏底带，命中的是底栏。
    点进「我的」后图标要晚一帧才进树，gear() 只读一次树，所以先等图标出现再交给它。"""
    for _ in range(tries):
        if not p.tab("我的"):
            raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
        p.dismiss()                   # 「我的」页可能先弹登录 / 引导弹窗，盖住图标
        until(settings_icon_visible, timeout=3, poll=0.3, now=time.time, sleep=time.sleep)
        if gear():
            return
    raise RuntimeError("主题设置入口没找到；" + p.page_evidence())


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
    # 只动卡片推荐；搜索框、出行助手保留；包本身不挂起（AGENTS 硬规则）。
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私")
        p.back()
    p.back()


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


print(f"\n回读确认 {VERIFIED_SWITCHES} 项；步骤异常 {len(FAILED_STEPS)} 个", flush=True)
