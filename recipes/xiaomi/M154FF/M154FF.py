# Xiaomi 18 Pro Max（M154FF）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 系统广告 / 应用商店 / 浏览器用 `opened()` 的直达探路：拉起函数作为回调传进去，留在这里。
import time
from entries import THEME_DEAD_ENDS


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]

# 注入面的 opened() 从这里取 adb_link.DeviceLost
import adb_link
import recipe_nav as nav
import recipe_steps as steps


def step_system_ads(p, rt):
    if nav.opened(p, rt, lambda: p.start("com.android.settings", ".ad.AdServiceSettings", expect="个性化广告推荐", budget=2)):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")
        return
    # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not nav.maybe(p, rt, "隐私与安全"):
        return
    # 18 Pro Max（OS4.0.24）：隐私与安全 → 更多安全设置；18 Fold：隐私与安全 → 安全 → 更多安全设置
    if not nav.maybe(p, rt, "更多安全设置"):
        if nav.maybe(p, rt, "安全", scrolls=3):
            nav.maybe(p, rt, "更多安全设置")
    if nav.maybe(p, rt, "广告服务"):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")


def step_store(p, rt):
    if not nav.opened(p, rt, lambda: p.start("com.xiaomi.market", ".ui.MarketPreferenceActivity", expect="通知设置", budget=2)):
        p.start("com.xiaomi.market")
        p.go("我的", "设置")
        nav.gear(p, rt)
    if nav.tap_any(p, rt, "隐私设置", "隐私"):
        # 4.129.s.00 的「个性化服务」是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or nav.maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if nav.maybe(p, rt, "模式切换"):                       # 新版商店没有这一项
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连「点赞消息」「评论消息」一起关（Issue #2）
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


def step_browser(p, rt):
    # 首页「默认 / 探索版 / 自定义主页」不改：自定义主页要填网址，按机主喜好
    # 设置页都有导出，直达：后台屏上首页的工具栏和底栏认不出来，走菜单会报「入口未找到」（#667）
    if nav.opened(p, rt, lambda: p.start("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity", expect="个性化内容推荐", budget=2)):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
        # 子项页老版本可能没导出：打不开只跳过下面三项，不让整段报未完成
        nav.opened(p, rt, lambda: p.start("com.android.browser", ".BrowserSettingsActivity"))
    else:
        p.start("com.android.browser")
        if "basicmode" in p.focus().lower():
            # 拒绝浏览器协议后落到基本模式设置页，四个设置入口都不在这条路径上，找下去只会报「入口未找到」（#414）
            print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
            return
        if not nav.browser_settings(p, rt):
            raise RuntimeError("浏览器设置入口未找到；未点击正文中的文字")
        if nav.maybe(p, rt, "隐私和安全"):
            p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if nav.maybe(p, rt, page):                           # 新版浏览器这三项都没有，有就关
            p.off(only=only, page=f"浏览器·{page}"); p.back()
    p.back(2)

