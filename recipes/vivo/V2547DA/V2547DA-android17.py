# V2547DA Android 17 变体的本机例外函数（catalog，#1263）：直达优先（opened(...)）+ 商店兜底是过程段。
# 由 catalog.loader 装进执行作用域（preamble 已注入 opened / settings_home / maybe / gear / off_unnamed / SkipStep / time）。
import adb_link
import time
import recipe_nav as nav
from recipe_runtime import SkipStep


def step_system_ads(p, rt):
    only = ["个性化广告", "个性化推荐", "智能推荐服务"]
    if nav.opened(p, rt, lambda: p.start("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo", expect="智能推荐服务", budget=2)):
        p.off(only=only, page="系统·广告与隐私")
        return
    nav.settings_home(p, rt)
    if nav.maybe(p, rt, "安全") or nav.maybe(p, rt, "安全与隐私"):
        if nav.maybe(p, rt, "更多安全设置") and nav.maybe(p, rt, "广告与隐私"):
            p.off(only=only, page="系统·广告与隐私")


def step_global_search(p, rt):
    if not nav.opened(p, rt, lambda: p.start("com.vivo.globalsearch", ".view.SearchSettingsActivity", expect="首页展示内容", budget=2)):
        nav.settings_home(p, rt)
        if not (nav.maybe(p, rt, "系统管理与升级") and nav.maybe(p, rt, "全局搜索")):
            return
    if nav.maybe(p, rt, "首页展示内容"):
        p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
    # Android 17 上没有「推荐热搜榜单」这个入口（#220）。这一页只有几行，看一眼就够，不滚也不等
    if p.find("推荐热搜榜单", exact=True) and nav.maybe(p, rt, "推荐热搜榜单", scrolls=0):
        p.off(only=["热门搜索"], page="全局搜索·热搜榜单"); p.back()
    if nav.maybe(p, rt, "个性化内容"):
        p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()   # 历史记录、应用建议保留


def step_lock_screen(p, rt):
    only = ["阅图锁屏", "锁屏横滑进入阅图"]
    if nav.opened(p, rt, lambda: p.start("com.vivo.magazine", ".ui.MagazineSettings", expect="锁屏横滑进入阅图", budget=2)):
        p.off(only=only, page="阅图锁屏")
        return
    nav.settings_home(p, rt)
    if nav.maybe(p, rt, "桌面、锁屏与壁纸") and nav.maybe(p, rt, "锁屏设置") and nav.maybe(p, rt, "阅图锁屏"):
        p.off(only=only, page="阅图锁屏")


def step_store(p, rt):
    # 「我的」页没有能读到的齿轮入口，设置页只能按 Activity 直达（#220）。
    try:
        p.start("com.bbk.appstore", ".ui.menu.AppstoreSettingsActivity")
        reached = "AppstoreSettingsActivity" in p.focus()
    except (adb_link.DeviceLost, SkipStep):
        raise                     # DeviceLost 也是 RuntimeError：断线不能当成「这一页打不开」再空跑一次；跳过同样放行（#908）
    except RuntimeError as e:
        print(f"  · 直达商店设置页失败（{e}），改走「我的 → 设置」")
        reached = False
    if not reached:
        p.start("com.bbk.appstore", expect=("我的",))
        if not p.tab("我的"):
            raise RuntimeError("商店底部「我的」标签没找到")
        time.sleep(0.8)
        nav.gear(p, rt)
    if nav.maybe(p, rt, "关于"):
        if nav.maybe(p, rt, "个性化推荐"):
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐")
            p.top()                     # p.off 会往下翻；这一页的开关在上面时别错过
            nav.off_unnamed(p, rt, "商店·个性化推荐")
            p.back(); time.sleep(0.5)
        if nav.maybe(p, rt, "服务管理"):
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back()
        p.back()
    p.back(2)
