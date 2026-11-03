# Redmi K70 Pro（23117RK66C），HyperOS OS3.0.306.0.WNMCNXM / Android 16。
# 入口与核对范围见 docs/14-红米K70Pro实测.md；包安装状态和联网规则不由机型脚本改动。
BUILD = "OS3.0.306.0.WNMCNXM"
MODELS = ["23117RK66C"]
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


def enter(name, scrolls=6):
    require(p.entry(name, scrolls=scrolls), f"未找到「{name}」")


@step("系统广告")
def _():
    p.start("com.android.settings", ".ad.AdServiceSettings")
    close_named(["个性化广告推荐"], "系统·广告服务")


@step("应用商店")
def _():
    # 首页的「我的」标签文字在本版本点击后不切页，设置 Activity 已在本机验证。
    p.start("com.xiaomi.market", ".ui.MarketPreferenceActivity")
    enter("隐私设置")
    enter("个性化服务")
    close_named(["个性化服务"], "商店·个性化服务")
    # 通知子页不允许外部 Activity 启动，必须从商店设置内进入。
    p.back(2)
    p.top(2)
    enter("通知设置")
    close_named(["新手帮助"], "商店·通知设置")


@step("手机管家")
def _():
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    enter("隐私设置")
    close_named(["个性化推荐"], "管家·隐私")
    p.back()
    enter("垃圾清理")
    close_named(["推荐内容"], "管家·垃圾清理")


@step("下载管理")
def _():
    p.start("com.android.providers.downloads.ui")
    require(gear(), "下载管理设置入口未找到")
    enter("信息流设置")
    close_named(["资源推荐", "热榜推荐"], "下载管理·信息流")


@step("主题")
def _():
    # 从壳包启动会复用上次设置页，显式重建主题首页以支持连续复跑。
    p.start("com.android.thememanager", ".ThemeResourceProxyTabActivity")
    require(p.go("我的", "设置"), "未进入主题「我的」")
    require(gear(), "主题设置入口未找到")
    close_named(["每次联网时通知"], "主题·设置")
    enter("隐私设置")
    close_named(["个性化推荐"], "主题·隐私")


@step("浏览器")
def _():
    p.start("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity")
    close_named(["个性化内容推荐", "个性化广告推荐"], "浏览器·个性化推荐")
    p.start("com.android.browser", ".BrowserSettingsActivity")
    enter("主页设置", scrolls=0)
    close_named(["宫格位推送"], "浏览器·主页设置")
    p.back()
    enter("搜索设置", scrolls=0)
    close_named(["显示猜你想搜模块"], "浏览器·搜索设置")


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("全局搜索")
def _():
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    enter("首页展示模块")
    close_named(["搜索提示词"], "搜索·首页模块")
    enter("应用推荐")
    close_named(["推荐未安装应用"], "搜索·应用推荐")
    p.back()
    enter("热搜榜单")
    # 不把所有版本可能出现的榜单当成必备；每个实际打开的子页必须找到目标并回读。
    subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
    require(subs, "未识别热榜分类")
    for name in subs:
        enter(name, scrolls=0)
        titles = [title for title, _, _ in p.switches() if any(k in title for k in HOT)]
        require(titles, f"热榜「{name}」未识别目标开关")
        close_named(titles, f"搜索·热榜·{name}")
        p.back()


@step("负一屏")
def _():
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    close_named(["推荐卡片", "热门活动"], "负一屏·设置")
    enter("隐私设置")
    close_named(["个性化推荐"], "负一屏·隐私")


@step("天气和日历")
def _():
    p.start("com.miui.weather2")
    enter("更多设置", scrolls=0)
    enter("设置", scrolls=0)
    enter("用户体验计划")
    close_named(["天气视频卡片", "内容推广"], "天气·用户体验计划")
    p.start("com.android.calendar")
    enter("设置", scrolls=0)
    enter("设置", scrolls=0)
    enter("用户体验计划")
    close_named(["内容推广"], "日历·用户体验计划")


print(f"\n逐页回读确认 {VERIFIED_SWITCHES} 项；步骤异常 {len(FAILED_STEPS)} 个", flush=True)
