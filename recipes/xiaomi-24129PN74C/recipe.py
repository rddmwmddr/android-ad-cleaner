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
#    （MIX Flip 2）在「我的」页里找设置（#833）。
#    「隐私和安全」在设置页最底部，要滚 8 屏才看得到，脚本用 scroll_more 往下翻。
#    实测默认开着的广告项只有「显示猜你想搜模块」（搜索设置）和「运营任务」（功能设置）；
#    「个性化内容推荐」「个性化广告推荐」「小说」「宫格位推送」出厂就是关的。
#  · 下载管理：右上「更多」按钮 → 弹窗里的「设置」→ 信息流设置。
#    实测「资源推荐」「热榜推荐」出厂就是关的。
#  · 手机管家：垃圾清理设置里「推荐内容」出厂就是关的；「个性化推荐」在隐私设置里，实测已关。
#  · 主题：每次联网时通知实测已关；隐私设置「个性化推荐」出厂就是关的。
#
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "BP2A.250605.031"
MODELS = ["24129PN74C"]
import time
from wait import until

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
VERIFIED_SWITCHES = 0


def step(name):
    def deco(f):
        if ONLY and name not in ONLY:
            return f
        print(f"\n== {name}", flush=True)
        p.miss = 0
        t = time.time()
        try:
            if p.locked():
                raise RuntimeError("手机锁屏了，请机主解锁后再跑")
            f()
        except Exception as e:
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{e}", flush=True)
        print(f"  ({time.time()-t:.0f} 秒)", flush=True)
        return f
    return deco


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def maybe(name, scrolls=6):
    """可选入口：有就点，没有不算「走丢」。"""
    return p.entry(name, scrolls=scrolls)


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
            raise RuntimeError(f"浏览器设置页没有打开；停在 {stopped}")
        xy = popup_row("设置")
        if not xy:
            raise RuntimeError(f"浏览器菜单里没有「设置」；停在 {p.focus()}")
        before = p.sig()
        p.click(*xy)
        p.settle(before, 1.5)
        if p.in_settings_page():
            return True
        # 弹窗这一行在屏上才走到这里，所以按返回是收起弹窗或退出面板，不会离开浏览器首页
        # focus 读不出前台时是空串，别让它被当成「还没进过弹窗」
        stopped = p.focus() or "读不出前台"
        p.back()
    raise RuntimeError(f"浏览器设置页没有打开；停在 {stopped}")


def browser_settings():
    """底栏「菜单」→ 弹窗「设置」；底栏没有「菜单」的机型在「我的」页里找设置（#833）。

    借这份脚本的机型底栏布局不同：Xiaomi 15 是 主页/视频/AI搜索/菜单/我的，MIX Flip 2 是
    主页/视频/AI搜索/免费小说/我的。两条入口点完都要认出设置页；「我的」那条没进去时报出
    停在哪一页，不在旧页上继续找「隐私和安全」等子项（#586）。"""
    if menu_settings():
        return
    print("  · 底栏没有「菜单」，改走「我的」→ 设置", flush=True)
    if not p.tab("我的"):
        raise RuntimeError(f"浏览器底部没有「菜单」，也没有「我的」标签；停在 {p.focus()}")
    p.dismiss()                       # 「我的」页可能先弹一键登录框，盖住齿轮
    if not gear():
        raise RuntimeError(f"浏览器设置页没有打开；停在 {p.focus()}")


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
    require(all(any(name in title for title in targets) for name in names),
            f"{page}：未识别全部目标开关，未操作")
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


@step("主题")
def _():
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
        p.off(only=["个性化推荐"], page="主题·隐私")
        p.back()
    p.back(2)


@step("浏览器")
def _():
    # 2026-10-29 实测：底栏是 主页/视频/AI搜索/菜单/我的，入口是底部「菜单」→ 弹窗右上「设置」；
    # 底栏没有「菜单」的机型（MIX Flip 2）在「我的」页里找设置（#833）。
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
