# vivo X300 Ultra 机型脚本：V2547DA（卫星通信版）。V2547A（OriginOS 7）另有社区实测脚本 recipes/vivo/V2547A/；路径来源：V2547DA，OriginOS 6 / Android 16（PD2547D_A_16.0.21.21.W10），2026-10-28 真机整段跑通验证。
from recipe_kit import step
# 2026-11-03 商店段改用 Phone.tab()、gear() 改用引擎 icon_hit（#530），这两处未复测。
# 2026-11-07 gear() 补落地校验：点不动的齿轮继续找、最后回退按文字点（#575），未复测。
# 别的系统版本会用安全模式跑：只关点名的开关，找不到入口就跳过。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2547D_A_16"
MODELS = ["V2547DA"]
# 家族库按这个常量选走法（#1246），缺省档与实现见 tool/recipe_nav.py。
GEAR_STYLE = "vivo_landing"
import time


@step("系统广告")
def _():
    system_ads_branch()


@step("全局搜索")
def _():
    global_search_ads()


@step("阅图锁屏")
def _():
    lock_screen_magazine()


@step("应用商店")
def _():
    # 开屏推荐页会挡住底部标签栏（#420）：先确认「我的」在，不在就退一次重进，仍不在就跳过本段
    p.start("com.bbk.appstore", expect=("我的",))
    # 底栏标签读作「我的, 2个应用待更新,第5个, 共5个」，精确匹配读不到（#530）
    if not p.tab("我的"):
        raise RuntimeError("商店底部「我的」标签没找到")
    time.sleep(0.8)
    gear()
    if maybe("关于"):
        if maybe("个性化推荐"):
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐")
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
    from recipe_kit import maybe, p
    from recipe_nav import gear
    from recipe_steps import browser_recommendations, global_search_ads, i_manager_ads, lock_screen_magazine, system_ads_branch, weather_service
