# vivo X Fold6 机型脚本：V2545A（OriginOS 6 Fold，Android 16，PD2545B_A_16.0.16.0.W10）；入口沿用同代 OriginOS 6 路径，逐步在真机核对；整段只用 only=[] 点名关闭，找不到就跳过。
from recipe_kit import step
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]
BUILD = "PD2545B_A_16"
MODELS = ["V2545A"]
# 家族库按这个常量选走法（#1246），缺省档与实现见 tool/recipe_nav.py。
GEAR_STYLE = "vivo_desc"
import time

@step("系统广告")
def _():
    settings_home()
    done = False
    if maybe("安全") or maybe("安全与隐私"):
        if maybe("更多安全设置") and maybe("广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")
            done = True
    if not done and setting_search("广告", "广告与隐私"):
        p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私（搜索）")

@step("全局搜索")
def _():
    settings_home()
    if maybe("系统管理与升级") and maybe("全局搜索"):
        if maybe("个性化内容"):
            p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()

@step("阅图锁屏")
def _():
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置") and maybe("阅图锁屏"):
        p.off(only=["阅图锁屏", "轮播壁纸"], page="锁屏·阅图锁屏")

@step("应用商店")
def _():
    p.start("com.bbk.appstore")
    time.sleep(2)
    by_desc("我的")
    gear()
    if maybe("关于"):
        if maybe("个性化推荐"):
            for t in ("个性化推荐", "个性化广告推荐"):
                switch_off(t, page="商店·个性化推荐")
            p.back()
        if maybe("服务管理"):
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back()
        p.back(2)

@step("浏览器")
def _():
    p.start("com.vivo.browser")
    time.sleep(2)
    by_desc("菜单")
    by_desc("设置", wait=2)
    if maybe("首页设置"):
        maybe("极简首页", scrolls=0)
        p.off(only=["首页上滑展示资讯"], page="浏览器·首页设置")
        p.back(); time.sleep(1)
    if maybe("隐私权限设置"):
        p.off(only=["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], page="浏览器·隐私权限设置")
        p.back(); time.sleep(1)
    if maybe("网页浏览设置"):
        p.off(only=["网页下载相关推荐"], page="浏览器·网页浏览设置")
        p.back(); time.sleep(1)
    if maybe("更多设置"):
        p.off(only=["WiFi连接跳转新闻资讯", "跳转新闻资讯"], page="浏览器·更多设置")
        p.back(); time.sleep(1)
    p.back(2)

@step("i管家")
def _():
    print("  跳过：i管家首次启动强制要求同意用户协议，按规则不代点。")
    print("  手动做：i管家 → 设置 → 关于 → 个性化设置 → 关「应用个性化推荐」")

@step("天气")
def _():
    p.start("com.vivo.weather")
    time.sleep(2)
    by_desc("更多")
    maybe("设置", scrolls=0)
    p.off(only=["天气服务"], page="天气·设置")
    p.back(2)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import maybe, p
    from recipe_nav import by_desc, gear, settings_home
    from recipe_strategies import row_switch, setting_search, switch_off
