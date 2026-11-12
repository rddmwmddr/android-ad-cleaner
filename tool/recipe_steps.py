"""机型脚本的段体注入面（#1209）：跨文件代码逐字相同的 `@step` 段体收在这里。

`recipe_kit.preamble()` 写完生命周期与台账之后调用 `install(p, g)`，把段体补进同一个执行作用域。
脚本侧只留一行调用：`@step("下载管理")` 加 `def _(): downloads()`，段体本身搬到这里。

与 `recipe_nav` 同一形状、同一方向：不 import `recipe_kit`，前导名字一律按 `g` 现取；段体依赖的
模块常量同样按名字现取（`g["HOT"]`），既不内联进实现、也不改成数据参数（沿用 #1149 的定案）。同一段文字在
不同脚本里可能挂着不同的取值，逐字相同的代码不等于相同的数据（小米系 `HOT` 有一份多「千问」）。

搬代码不改现有脚本的行为——脚本本地定义后执行，覆盖注入的名字；删掉本地那份之后才开始走注入版。
代价是段体从执行作用域取的那些名字在脚本里仍要留着：`import time` 与 `HOT` / `THEME_DEAD_ENDS`
这类模块常量即使脚本自己不再直接读也不能删，否则闭包现取到的是空。

字段：名字 → 工厂。工厂收 `(p, g)`，只造闭包、不碰手机，返回写进执行作用域的那个函数。
守卫比对脚本里还留着的 `@step` 段体与注入实现，AST 归一（剥注释、docstring、装饰器与折行）后
相同即红，见 `tests/test_recipe_steps.py`。
"""

from collections.abc import Callable
from typing import Any

STEPS: dict[str, Callable[[Any, Any], Callable[..., Any]]] = {}


# ---------- 小米系（xiaomi / redmi，#1210）----------
#
# 同名多簇各用能看出差异的注入名：下载管理分主体 / 探路 / 点击三版，天气和日历分点击 / 探路两版，
# 应用商店分是否带「模式切换」两版。段体里出现的前导名字、导航助手与模块常量一律按 `g` 现取：
# `tap_any` / `gear` 在部分脚本里有本地同名定义，闭包取到的就是脚本那份。

def _xiaomi_negative_screen(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def negative_screen() -> None:
        # 只动卡片推荐；搜索框、出行助手保留；包本身不挂起（AGENTS 硬规则）
        p.start("com.miui.personalassistant", ".settings.PASettingActivity")
        p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框、出行助手保留
        if g["maybe"]("隐私设置"):
            p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
        p.back()

    return negative_screen


def _xiaomi_global_search(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def global_search() -> None:
        p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
        if g["maybe"]("首页展示模块"):
            p.off(only=["搜索提示词"], page="搜索·首页模块")
            if g["maybe"]("应用推荐"):
                p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐")
                p.back()
            if g["maybe"]("热搜榜单"):
                # 同一页既有「推荐」开关又有热搜/生活/话题/娱乐子页，二者都要处理（Issue #21）。
                subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
                if p.switches():
                    p.off(only=g["HOT"], page="搜索·热搜榜单")
                if subs:
                    p.top()
                    for x in subs:
                        if g["maybe"](x):
                            p.off(only=g["HOT"], page=f"搜索·热榜·{x}")
                            p.back()
                p.back()
            p.back()
        p.back(2)

    return global_search


def _xiaomi_security_center(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def security_center() -> None:
        # 探路时 securitymanager 包起不来，照 M154FF 用 securitycenter 直达设置页。
        # 新版手机管家（13.6.5）隐私设置里没有「个性化推荐」、垃圾清理里没有「推荐内容」；有就关，没有跳过。
        p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
        if g["maybe"]("隐私设置"):
            p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
        if g["maybe"]("垃圾清理"):
            p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
        p.back(2)

    return security_center


def _xiaomi_downloads(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def downloads() -> None:
        # p.start 会顺手点掉「以后再说」更新弹窗
        p.start("com.android.providers.downloads.ui")
        if not g["gear"]():
            raise RuntimeError("下载管理设置入口未找到")
        if g["maybe"]("信息流设置"):
            p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
        p.back(3)

    return downloads


def _xiaomi_downloads_probe(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def downloads_probe() -> None:
        if g["opened"](lambda: p.start("com.android.providers.downloads.ui",
                                       ".activity.InfoFlowSettingActivity",
                                       expect="资源推荐", budget=2)):
            p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
            p.back()
            return
        p.start("com.android.providers.downloads.ui")
        if not g["gear"]():
            raise RuntimeError("下载管理设置入口未找到")
        if g["maybe"]("信息流设置"):
            p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
        p.back(3)

    return downloads_probe


def _xiaomi_downloads_tap(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def downloads_tap() -> None:
        # 2026-10-29 实测：设置入口在右上「更多」按钮的弹窗里，页面上没有齿轮。
        p.start("com.android.providers.downloads.ui")
        g["time"].sleep(1.5)
        g["require"](p.tap("更多", exact=True, scrolls=0), "下载管理「更多」按钮没找到")
        g["time"].sleep(1.0)
        g["require"](p.tap("设置", exact=True, scrolls=0), "下载管理弹窗里的「设置」没找到")
        g["time"].sleep(1.2)
        if g["maybe"]("信息流设置"):
            p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
        p.back(3)

    return downloads_tap


def _xiaomi_theme(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def theme() -> None:
        # 直达主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；经主题商店冷启动
        # 要过一道重定向过渡窗，前台校验容易误判，也可能续在上次留下的子页上（#906）。
        # 落点被系统转去商店详情页或桌面时仍按跳过收尾。
        if "package:" not in p.d.shell("pm path com.android.thememanager").output:
            print("  · 本机没有主题管理包，跳过"); return
        g["start_or_skip"]("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                           dead_ends=g["THEME_DEAD_ENDS"], reason="主题页打不开")
        # 导航失败以前与「本页没有目标开关」同形：进「我的」、进设置页、点名开关三步都校验，
        # 0 个开关按失败报并带页面现场（#906）。
        if not p.go("我的", "设置"):
            raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
        if not g["gear"]():
            raise RuntimeError("主题设置入口没找到；" + p.page_evidence())
        p.await_page()                              # 齿轮点完这一页可能还没画完
        before = {}
        for _ in range(2):                          # 行也可能在首屏之下，off() 自己会翻页找
            before.update({title: on for title, on, _ in p.switches()})
            if not p.scroll_more():
                break
        p.top(2)
        g["require_switches"](before, ["每次联网时通知"], "主题·设置", contains=True)
        p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
        if g["maybe"]("隐私设置"):
            p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
        p.back(2)

    return theme


def _xiaomi_weather_calendar_tap(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def weather_calendar_tap() -> None:
        p.start("com.miui.weather2")
        if p.tap("更多设置", exact=True, scrolls=0):
            g["time"].sleep(1.2)
            if p.tap("设置", exact=True, scrolls=0):
                g["time"].sleep(1.2)
                if p.tap("用户体验计划", exact=True, scrolls=6):
                    g["time"].sleep(1.0)
                    p.off(only=["天气视频卡片", "内容推广"], page="天气·用户体验计划")
                    p.back()
                p.back(2)
        p.start("com.android.calendar")
        if p.tap("设置", exact=True, scrolls=0):
            g["time"].sleep(1.0)
            if p.tap("设置", exact=True, scrolls=0):
                g["time"].sleep(1.2)
                if p.tap("用户体验计划", exact=True, scrolls=6):
                    g["time"].sleep(1.0)
                    p.off(only=["内容推广"], page="日历·用户体验计划")
                    p.back()
                p.back(2)

    return weather_calendar_tap


def _xiaomi_weather_calendar_probe(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def weather_calendar_probe() -> None:
        # Issue #1 提供入口线索；2026-10-25 已在 M154FF 验证天气、日历的「内容推广」。
        for pkg in ("com.miui.weather2", "com.android.calendar"):
            if pkg == "com.android.calendar" and g["opened"](
                    lambda: p.start("com.android.calendar", ".settings.UserExperienceActionBarActivity",
                                    expect="内容推广", budget=2)):
                p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"],
                      page=f"{pkg}·用户体验计划"); p.back()
                continue
            p.start(pkg)
            if pkg == "com.miui.weather2" and p.find("城市管理", exact=True, edge_ok="tab"):
                # 新版天气：底部城市管理 → 右上更多设置 → 设置。
                p.tap("城市管理", exact=True, scrolls=0)
            if not g["gear"]():
                print("  · 本版本没有可识别的设置菜单，跳过"); continue
            if g["maybe"]("用户体验计划"):
                p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"],
                      page=f"{pkg}·用户体验计划"); p.back()
            p.back(3)

    return weather_calendar_probe


def _xiaomi_store(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def store() -> None:
        p.start("com.xiaomi.market")
        p.go("我的", "设置")
        g["gear"]()
        if g["tap_any"]("隐私设置", "隐私"):
            # 「个性化服务」可能是子页入口，开关在下一层。
            nested = not any("个性化服务" in t for t, _, _ in p.switches())
            if not nested or g["maybe"]("个性化服务"):
                p.off(only=["个性化服务", "个性化推荐"], page="商店·个性化服务")
                if nested:
                    p.back()
            p.back()
        if g["maybe"]("通知设置"):
            # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连「点赞消息」「评论消息」一起关（Issue #2）
            p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
        p.back(2)

    return store


def _xiaomi_store_mode(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def store_mode() -> None:
        p.start("com.xiaomi.market")
        p.go("我的", "设置")
        g["gear"]()
        if g["tap_any"]("隐私设置", "隐私"):
            # 「个性化服务」可能是子页入口，开关在下一层。
            nested = not any("个性化服务" in t for t, _, _ in p.switches())
            if not nested or g["maybe"]("个性化服务"):
                p.off(only=["个性化服务"], page="商店·个性化服务")
                if nested:
                    p.back()
            p.back()
        if g["maybe"]("模式切换"):                        # 新版商店没有这一项
            p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
        if g["maybe"]("通知设置"):
            # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞/评论消息一起关
            p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
        p.back(2)

    return store_mode


def _xiaomi_system_ads_security(p: Any, g: dict[str, Any]) -> Callable[..., Any]:
    def system_ads_security() -> None:
        # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
        g["time"].sleep(1.2)
        g["require"](p.tap("隐私与安全", exact=True, scrolls=6), "未找到「隐私与安全」")
        g["require"](g["security_tab"](), "未识别「安全」标签")
        g["require"](p.tap("更多安全设置", exact=True, scrolls=6), "未找到「更多安全设置」")
        g["require"](p.tap("广告服务", exact=True, scrolls=6), "未找到「广告服务」")
        g["close_named"](["个性化广告推荐"], "系统·广告服务")

    return system_ads_security


STEPS.update({
    "negative_screen": _xiaomi_negative_screen,
    "global_search": _xiaomi_global_search,
    "security_center": _xiaomi_security_center,
    "downloads": _xiaomi_downloads,
    "downloads_probe": _xiaomi_downloads_probe,
    "downloads_tap": _xiaomi_downloads_tap,
    "theme": _xiaomi_theme,
    "weather_calendar_tap": _xiaomi_weather_calendar_tap,
    "weather_calendar_probe": _xiaomi_weather_calendar_probe,
    "store": _xiaomi_store,
    "store_mode": _xiaomi_store_mode,
    "system_ads_security": _xiaomi_system_ads_security,
})


def install(p: Any, g: dict[str, Any]) -> None:
    """把段体写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in STEPS.items():
        g[name] = factory(p, g)
