# vivo（iQOO）V2324HA 机型脚本
# 路径来源：V2324HA，OriginOS / Android 16（PD2324J_A_16.2.13.1.W10），2026-10-27 手动实测。
# 这台没有「推荐热搜榜单」「应用商店服务管理」两个入口，脚本里保留为「有就点、没有跳过」。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2324J_A_16"
MODELS = ["V2324HA"]
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
    """有就点，没有不算「走丢」，后面的步骤照常找。"""
    return p.entry(name, scrolls=scrolls)


def gear():
    """vivo App 的设置多是右上角齿轮图标，没有文字。"""
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("resource-id") or "")
        if any(k in d.lower() for k in ("设置", "setting")) and n.get("clickable") == "true" and p.on_screen(n):
            from fast import bounds
            l, t, r, b = bounds(n); p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    return p.tap("设置", exact=True, scrolls=0)


def settings_home():
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)


@step("系统广告")
def _():
    settings_home()
    if maybe("安全") or maybe("安全与隐私"):
        if maybe("更多安全设置") and maybe("广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")


@step("全局搜索")
def _():
    settings_home()
    if maybe("系统管理与升级") and maybe("全局搜索"):
        # 本机系统设置里全局搜索页没有「推荐热搜榜单」这一项，只有下面两个子页。
        if maybe("首页展示内容"):
            p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
        if maybe("推荐热搜榜单"):   # 旧版 / 新版本机上有，留着备用
            p.off(only=["热门搜索"], page="全局搜索·热搜榜单"); p.back()
        if maybe("个性化内容"):
            p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()   # 历史记录、应用建议保留


@step("阅图锁屏")
def _():
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置") and maybe("阅图锁屏"):
        p.off(only=["阅图锁屏", "锁屏横滑进入阅图"], page="阅图锁屏")


@step("应用商店")
def _():
    # 本机「服务管理」「个性化推荐」两个入口藏在「关于」页里（不是设置页第一层），要滑下去才看得到。
    # 「消息通知设置」是标题行点不动，要直接点它下面的「应用商店提醒类型」。
    p.start("com.bbk.appstore")
    p.go("我的", "设置")
    gear()
    if maybe("关于"):
        if maybe("个性化推荐"):   # SettingUserRecommendActivity
            # 已知限制：这页两个开关（个性化推荐 / 个性化广告推荐）在读屏里没有标题，
            # 只有「关闭，开关」这种状态字。引擎会把它当「关闭××」类保护开关而不猜方向，因此这里
            # 通常读不到可操作项（核对 0 项）。这是引擎刻意的安全策略，不绕过；开关本身是关的就没事，
            # 若哪天系统把标题改出来，下面这行会自动生效。
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐"); p.back()
        if maybe("服务管理"):     # FunctionManagerActivity
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["管理页-我的服务", "空间清理"], page="商店·服务管理"); p.back()
        p.back()
    if maybe("应用商店提醒类型"):   # NotificationSettingsActivity
        # 只关营销类；应用更新、安装完成等提醒不动。
        p.off(only=["资讯活动提醒", "积分过期提醒", "应用管理提醒"], page="商店·提醒类型"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # 本机浏览器首页没有底部「我的」，设置入口是右上角「菜单」→「设置」。
    # 「隐私权限设置」是页内子页（同一个 SettingActivity），不是独立页面。
    p.start("com.vivo.browser")
    if maybe("菜单", scrolls=0):
        maybe("设置", scrolls=0)
    if maybe("首页设置"):
        maybe("极简首页", scrolls=0)
        p.off(only=["首页上滑展示资讯"], page="浏览器·首页设置"); p.back()
    if maybe("隐私权限设置"):
        # 个性化内容、第三方应用来源个性化推荐、个性化广告推荐
        p.off(only=["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], page="浏览器·隐私"); p.back()
    if maybe("网页浏览设置"):
        p.off(only=["网页下载相关推荐"], page="浏览器·网页浏览"); p.back()
    if maybe("更多设置"):
        p.off(only=["WiFi 连接跳转新闻资讯", "跳转新闻资讯"], page="浏览器·更多设置"); p.back()
    p.back(2)


@step("i管家")
def _():
    p.start("com.iqoo.secure")
    gear()
    if maybe("关于") and maybe("个性化设置"):
        p.off(only=["应用个性化推荐"], page="i管家·个性化设置")
    p.back(3)


@step("天气")
def _():
    # 本机天气首页没有「设置」文字，齿轮()找不到；直接拉 WeatherSettings 最稳。
    p.start("com.vivo.weather", ".WeatherSettings")
    p.off(only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")   # 只关「天气相关热点资讯通知」
    p.back(2)
