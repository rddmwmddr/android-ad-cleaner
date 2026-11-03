# Redmi K80 Pro（24122RKC7C，代号 miro），HyperOS OS3.0.304.0.WOMCNXM / Android 16 / Build BP2A.250605.031.A3。
# 2026-10-29 真机实测：USB 有线，1080×2400、密度 450、ROTATION_0。
# 入口来源：先按同品牌 Redmi K70 脚本（OS3.0.307.0）安全模式跑通 9 段、关 20 项，
#   再按本机入口补两处差异，专用脚本复跑 9 段（0 调整、0 步骤异常）。
# 与 K70 的两处差异：
#   ① 主题商店冷启动（com.miui.themestore）会跳到 com.android.thememanager，引擎的前台校验会停段；
#      直达 com.android.thememanager/.ThemeResourceProxyTabActivity 最稳。
#   ② 浏览器「设置」是顶部右侧的齿轮 ImageView（文字就是「设置」），冷启动偶发被过渡窗拦一次；
#      这里先 force-stop 再直达 BrowserActivity，重试一次，齿轮点不动时用 input tap 兜底。
# 浏览器「小说」「最新资讯」按 K70 的结论不动：小说是功能入口不是广告开关，最新资讯在本机是 disabled。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS3.0.304.0"
MODELS = ["24122RKC7C"]
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
    from fast import bounds, icon_hit

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


def gear_tap(pkg, activity):
    """齿轮用引擎短按点不动时的兜底：同一次读屏里找到齿轮，改用 input tap（80 毫秒短按有的 App 会吞）。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        text = (n.get("text") or "").strip()
        desc = (n.get("content-desc") or "").strip()
        if text == "设置" or desc == "设置":
            l, t, r, b = bounds(n)
            if not p.on_screen(n):
                continue
            p.d.shell(f"input tap {(l + r) // 2} {(t + b) // 2}")
            time.sleep(1.2)
            return p.focus().split("/", 1)[0] == pkg and activity in p.focus()
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


def browser_start():
    """冷启动偶发被启动过渡窗判断成「离开前台」：先强停再直达 BrowserActivity，重试一次。"""
    for attempt in range(2):
        try:
            p.start("com.android.browser", ".BrowserActivity")
            return True
        except RuntimeError as e:
            if attempt or "离开前台" not in str(e):
                raise
            p.d.shell("am force-stop com.android.browser")
            time.sleep(1.5)
    return False


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("系统广告")
def _():
    # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
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
    # 主题商店冷启动会跳到 thememanager，引擎的前台校验会停段；直达代理标签页最稳。
    if "package:" in p.d.shell("pm path com.android.thememanager").output:
        p.start("com.android.thememanager", ".ThemeResourceProxyTabActivity")
    else:
        p.start("com.miui.themestore", foreground="com.android.thememanager")
    require(p.tap("我的", exact=True, scrolls=0), "未找到主题「我的」")
    require(gear(), "主题设置齿轮未找到")
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私")
        p.back()
    p.back(2)


@step("浏览器")
def _():
    require(browser_start(), "浏览器没有启动")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    # 「我的」在本机是顶部标签：主页 / 视频 / AI搜索 / 免费小说 / 我的
    require(p.tap("我的", exact=True, scrolls=0), "未找到浏览器「我的」")
    if not gear(toolbar_only=True):
        require(gear_tap("com.android.browser", "BrowserSettingsActivity"),
                "浏览器设置齿轮没找到")
    else:
        require(p.focus().split("/", 1)[0] == "com.android.browser"
                and "BrowserSettingsActivity" in p.focus(), "浏览器设置页没有打开")
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
            # 同一页既有「推荐」开关又有热搜/生活/话题/娱乐子页，二者都要处理（Issue #21）。
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
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框、出行助手保留
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
