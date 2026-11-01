# Redmi K70（23113RKC6C），HyperOS OS3.0.307.0.WNKCNXM / Android 16。
# 2026-10-26 无线调试实测：系统广告段临时开启后关闭，39 秒、调整 1 项、回读确认。
# 其余 8 段已按 K70 实际入口补入；浏览器 2 项、天气 2 项、日历 1 项已实际关闭。
# 浏览器「小说」是功能入口，验证后已从本脚本移除；「最新资讯」为 disabled，无法操作。
# 参考脚本 9 段安全模式实测调整 14 项；最终脚本在有线原生 1440×3200 上复跑 230 秒、0 调整、0 步骤异常（移除小说前的无线复跑为 307 秒）。
# 不能把这份脚本当成整机适配完成。
BUILD = "OS3.0.307.0"
MODELS = ["23113RKC6C"]
import time

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


def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
    重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（#305 / #374）。"""
    from fast import bounds

    def icon_hit(n):
        desc = (n.get("content-desc") or "").strip().lower()
        text = (n.get("text") or "").strip().lower()
        if desc in ("设置", "settings", "setting") or text in ("设置", "settings", "setting"):
            return True
        # id 只认最后一段里以 setting 开头的词：商店「我的」页的 securitySettingSwitchLayout
        # 也含 setting，但 setting 前面粘着 security，不该算成设置入口。
        rid = (n.get("resource-id") or "").lower().rsplit("/", 1)[-1]
        return rid.startswith("setting") or "_setting" in rid

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
        from fast import bounds
        l, t, r, b = bounds(n)
        if (any(k in key.lower() for k in ("更多", "more", "menu"))
                and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22):
            p.click((l + r) // 2, (t + b) // 2)
            time.sleep(0.5)
            if p.tap("设置", exact=True, scrolls=0):
                return True
            break
    return False


def security_tab():
    """HyperOS 3 的「安全」是隐私页上方的标签，不是设置行。
    按文字点会命中不可点击的标签文字；这里只点横跨半屏、位于顶部的可点击容器。"""
    for text, (l, t, r, b), node in p.texts():
        if (text == "安全" and node.get("clickable") == "true"
                and r - l > p.W * 0.3 and t < p.H * 0.25):
            p.click((l + r) // 2, (t + b) // 2)
            time.sleep(0.8)
            return True
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
    开关标题可能附带整段说明，所以按关键词匹配，不做完整标题相等判断。"""
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
    if "package:" in p.d.shell("pm path com.miui.themestore").output:
        p.start("com.miui.themestore", foreground="com.android.thememanager")
    else:
        p.start("com.android.thememanager")
    p.go("我的", "设置")
    gear()
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
    require(p.tap("我的", exact=True, scrolls=0), "未找到浏览器「我的」")
    require(p.tap("设置", exact=True, scrolls=0), "未找到浏览器「设置」")
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
