# vivo X300 Ultra（V2547DA，卫星通信版）Android 17 变体：同型号的 OriginOS 6 路径在 recipe.py，；系统版本对上 17.1.10.2 时由 run.recipe_for 选这份。
from recipe_kit import step
# 路径来源：Issue #220 报告者真机实测（V2547DA，PD2547D_A_17.1.10.2.W10，商店 V10.5.20.0，2026-10-28）。
# 2026-11-03 商店段改用 Phone.tab()、gear() 改用引擎 icon_hit（#530）。
# 2026-11-07 整段在 V2547DA 真机复测；系统广告、全局搜索、阅图锁屏改为直达，打不开再走菜单（#667）。
# 2026-11-07 gear() 补落地校验：点不动的齿轮继续找、最后回退按文字点（#575），未复测。
# 与 recipe.py 的差别只在应用商店——Android 17 的「我的」页没有能读到的齿轮入口，
# 且「个性化推荐」页两个开关的 content-desc 只有「开启，开关」，读不出标题。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2547D_A_17.1.10.2"
MODELS = ["V2547DA"]
# 家族库按这个常量选走法（#1246），缺省档与实现见 tool/recipe_nav.py。
GEAR_STYLE = "vivo_landing"
import time

import adb_link


@step("系统广告")
def _():
    only = ["个性化广告", "个性化推荐", "智能推荐服务"]
    if opened(lambda: p.start("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo", expect="智能推荐服务", budget=2)):
        p.off(only=only, page="系统·广告与隐私")
        return
    settings_home()
    if maybe("安全") or maybe("安全与隐私"):
        if maybe("更多安全设置") and maybe("广告与隐私"):
            p.off(only=only, page="系统·广告与隐私")


@step("全局搜索")
def _():
    if not opened(lambda: p.start("com.vivo.globalsearch", ".view.SearchSettingsActivity", expect="首页展示内容", budget=2)):
        settings_home()
        if not (maybe("系统管理与升级") and maybe("全局搜索")):
            return
    if maybe("首页展示内容"):
        p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
    # Android 17 上没有「推荐热搜榜单」这个入口（#220）。这一页只有几行，看一眼就够，不滚也不等
    if p.find("推荐热搜榜单", exact=True) and maybe("推荐热搜榜单", scrolls=0):
        p.off(only=["热门搜索"], page="全局搜索·热搜榜单"); p.back()
    if maybe("个性化内容"):
        p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()   # 历史记录、应用建议保留


@step("阅图锁屏")
def _():
    only = ["阅图锁屏", "锁屏横滑进入阅图"]
    if opened(lambda: p.start("com.vivo.magazine", ".ui.MagazineSettings", expect="锁屏横滑进入阅图", budget=2)):
        p.off(only=only, page="阅图锁屏")
        return
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置") and maybe("阅图锁屏"):
        p.off(only=only, page="阅图锁屏")


@step("应用商店")
def _():
    # 「我的」页没有能读到的齿轮入口，设置页只能按 Activity 直达（#220）。
    # Activity 不存在时 Phone.start 会直接抛出来，接住再退回「我的 → 设置」，别整段空跑。
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
        # 底栏标签读作「我的, 2个应用待更新,第5个, 共5个」，精确匹配读不到（#530）
        if not p.tab("我的"):
            raise RuntimeError("商店底部「我的」标签没找到")
        time.sleep(0.8)
        gear()
    if maybe("关于"):
        if maybe("个性化推荐"):
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐")
            p.top()                     # p.off 会往下翻；这一页的开关在上面时别错过
            off_unnamed("商店·个性化推荐")
            p.back(); time.sleep(0.5)
        if maybe("服务管理"):
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back()
        p.back()
    p.back(2)


@step("浏览器")
def _():
    browser_recommendations()


@step("i管家")
def _():
    i_manager_ads()


@step("天气")
def _():
    weather_service()

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import SkipStep, maybe, p
    from recipe_nav import gear, off_unnamed, opened, settings_home
    from recipe_steps import browser_recommendations, i_manager_ads, weather_service
