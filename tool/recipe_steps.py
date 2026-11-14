"""机型脚本的段体注入面（#1209）：跨文件代码逐字相同的 `@step` 段体收在这里。

`recipe_kit.preamble()` 写完生命周期与台账之后调用 `install(p, g)`，把段体补进同一个执行作用域。
脚本侧只留一行调用：`@step("下载管理")` 加 `def _(): downloads()`，段体本身搬到这里。

与 `recipe_nav` 同一形状、同一方向：不 import `recipe_kit`，前导名字一律按 `g` 现取；段体依赖的
模块常量同样按名字现取（`g["HOT"]`），既不内联进实现、也不改成数据参数（沿用 #1149 的定案）。同一段文字在
不同脚本里可能挂着不同的取值，逐字相同的代码不等于相同的数据（小米系 `HOT` 有一份多「千问」）。

搬代码不改现有脚本的行为——脚本本地定义后执行，覆盖注入的名字；删掉本地那份之后才开始走注入版。
代价是段体从执行作用域取的那些名字在脚本里仍要留着：`import time` 与 `HOT` / `THEME_DEAD_ENDS`
这类模块常量即使脚本自己不再直接读也不能删——`g` 是执行作用域那个字典，缺名字时闭包取的是 KeyError。

字段：名字 → 工厂。工厂收 `(p, g)`，只造闭包、不碰手机，返回写进执行作用域的那个函数。
守卫比对脚本里还留着的 `@step` 段体与注入实现，AST 归一（剥注释、docstring、装饰器与折行）后
相同即红，见 `tests/test_recipe_steps.py`。

文件内按家族分节，`install()` 落在最后。
"""

import adb_link
import recipe_nav as nav
import recipe_strategies as strategies
from row import bounds

from typing import Any

# 数据可调用的公开实现：`tool/catalog/interpreter.py` 按这些名字建分派表。
__all__ = ("ad_tracking_close_all", "assistant_advice_rows", "assistant_advice_search", "assistant_screen", "browser_ads", "browser_home", "browser_personalized", "browser_recommendations", "downloads", "downloads_probe", "downloads_tap", "game_center_direct", "game_center_taps", "global_search", "global_search_ads", "i_manager_ads", "lock_screen_magazine", "negative_screen", "search_settings_direct", "search_settings_swipe", "security_center", "store", "store_mode", "store_promotions", "system_ads_branch", "system_ads_chain", "system_ads_security", "theme", "theme_shop_settings", "theme_store_settings", "video_direct", "weather_calendar_probe", "weather_calendar_tap", "weather_service")


def __getattr__(name: str) -> Any:
    """注入名在类型层面可见（#1247）：脚本 `if TYPE_CHECKING:` 块里的 import 落到这里。
    运行时这些名字住在执行作用域，模块上没有对应属性，照旧抛 AttributeError。"""
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------- 小米系（xiaomi / redmi，#1210）----------
#
# 同名多簇各用能看出差异的注入名：下载管理分主体 / 探路 / 点击三版，天气和日历分点击 / 探路两版，
# 应用商店分是否带「模式切换」两版。段体里出现的前导名字、导航助手与模块常量一律按 `g` 现取：
# `tap_any` / `gear` 在部分脚本里有本地同名定义，闭包取到的就是脚本那份。

def negative_screen(p, rt):
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框、出行助手保留
    if nav.maybe(p, rt, "隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
    p.back()


def global_search(p, rt):
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if nav.maybe(p, rt, "首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if nav.maybe(p, rt, "应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐")
            p.back()
        if nav.maybe(p, rt, "热搜榜单"):
            # 同一页既有「推荐」开关又有热搜/生活/话题/娱乐子页，二者都要处理（Issue #21）。
            subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
            if p.switches():
                p.off(only=rt.constants['HOT'], page="搜索·热搜榜单")
            if subs:
                p.top()
                for x in subs:
                    if nav.maybe(p, rt, x):
                        p.off(only=rt.constants['HOT'], page=f"搜索·热榜·{x}")
                        p.back()
            p.back()
        p.back()
    p.back(2)


def security_center(p, rt):
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    if nav.maybe(p, rt, "隐私设置"):
        p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
    if nav.maybe(p, rt, "垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
    p.back(2)


def downloads(p, rt):
    p.start("com.android.providers.downloads.ui")
    if not nav.gear(p, rt):
        raise RuntimeError("下载管理设置入口未找到")
    if nav.maybe(p, rt, "信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


def downloads_probe(p, rt):
    if nav.opened(p, rt, lambda: p.start("com.android.providers.downloads.ui",
                                   ".activity.InfoFlowSettingActivity",
                                   expect="资源推荐", budget=2)):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
        p.back()
        return
    p.start("com.android.providers.downloads.ui")
    if not nav.gear(p, rt):
        raise RuntimeError("下载管理设置入口未找到")
    if nav.maybe(p, rt, "信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


def downloads_tap(p, rt):
    p.start("com.android.providers.downloads.ui")
    rt.clock.sleep(1.5)
    rt.require(p.tap("更多", exact=True, scrolls=0), "下载管理「更多」按钮没找到")
    rt.clock.sleep(1.0)
    rt.require(p.tap("设置", exact=True, scrolls=0), "下载管理弹窗里的「设置」没找到")
    rt.clock.sleep(1.2)
    if nav.maybe(p, rt, "信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


def theme(p, rt):
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    rt.start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                       dead_ends=rt.constants['THEME_DEAD_ENDS'], reason="主题页打不开")
    # 导航失败以前与「本页没有目标开关」同形：进「我的」、进设置页、点名开关三步都校验，
    # 0 个开关按失败报并带页面现场（#906）。
    if not p.go("我的", "设置"):
        raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
    if not nav.gear(p, rt):
        raise RuntimeError("主题设置入口没找到；" + p.page_evidence())
    p.await_page()                              # 齿轮点完这一页可能还没画完
    before = {}
    for _ in range(2):                          # 行也可能在首屏之下，off() 自己会翻页找
        before.update({title: on for title, on, _ in p.switches()})
        if not p.scroll_more():
            break
    p.top(2)
    rt.require_switches(before, ["每次联网时通知"], "主题·设置", contains=True)
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if nav.maybe(p, rt, "隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


def weather_calendar_tap(p, rt):
    p.start("com.miui.weather2")
    if p.tap("更多设置", exact=True, scrolls=0):
        rt.clock.sleep(1.2)
        if p.tap("设置", exact=True, scrolls=0):
            rt.clock.sleep(1.2)
            if p.tap("用户体验计划", exact=True, scrolls=6):
                rt.clock.sleep(1.0)
                p.off(only=["天气视频卡片", "内容推广"], page="天气·用户体验计划")
                p.back()
            p.back(2)
    p.start("com.android.calendar")
    if p.tap("设置", exact=True, scrolls=0):
        rt.clock.sleep(1.0)
        if p.tap("设置", exact=True, scrolls=0):
            rt.clock.sleep(1.2)
            if p.tap("用户体验计划", exact=True, scrolls=6):
                rt.clock.sleep(1.0)
                p.off(only=["内容推广"], page="日历·用户体验计划")
                p.back()
            p.back(2)


def weather_calendar_probe(p, rt):
    for pkg in ("com.miui.weather2", "com.android.calendar"):
        if pkg == "com.android.calendar" and nav.opened(p, rt, 
                lambda: p.start("com.android.calendar", ".settings.UserExperienceActionBarActivity",
                                expect="内容推广", budget=2)):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"],
                  page=f"{pkg}·用户体验计划"); p.back()
            continue
        p.start(pkg)
        if pkg == "com.miui.weather2" and p.find("城市管理", exact=True, edge_ok="tab"):
            # 新版天气：底部城市管理 → 右上更多设置 → 设置。
            p.tap("城市管理", exact=True, scrolls=0)
        if not nav.gear(p, rt):
            print("  · 本版本没有可识别的设置菜单，跳过"); continue
        if nav.maybe(p, rt, "用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"],
                  page=f"{pkg}·用户体验计划"); p.back()
        p.back(3)


def store(p, rt):
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    nav.gear(p, rt)
    if nav.tap_any(p, rt, "隐私设置", "隐私"):
        # 「个性化服务」可能是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or nav.maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务", "个性化推荐"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连「点赞消息」「评论消息」一起关（Issue #2）
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


def store_mode(p, rt):
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    nav.gear(p, rt)
    if nav.tap_any(p, rt, "隐私设置", "隐私"):
        # 「个性化服务」可能是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or nav.maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if nav.maybe(p, rt, "模式切换"):                        # 新版商店没有这一项
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞/评论消息一起关
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


def system_ads_security(p, rt):
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    rt.clock.sleep(1.2)
    rt.require(p.tap("隐私与安全", exact=True, scrolls=6), "未找到「隐私与安全」")
    rt.require(nav.security_tab(p, rt), "未识别「安全」标签")
    rt.require(p.tap("更多安全设置", exact=True, scrolls=6), "未找到「更多安全设置」")
    rt.require(p.tap("广告服务", exact=True, scrolls=6), "未找到「广告服务」")
    _close_named_fn(rt)(p, rt, ["个性化广告推荐"], "系统·广告服务")





# ---------- OPPO 家族：oneplus-PHK110 / PKX110、oppo-PKH110（#1212）----------
#
# 三台的浏览器首页与商店段逐字相同，浏览器的广告 / 个性化两段只有一加两台相同（PKH110 的
# 广告段换了一句打印、个性化段改走 `close_titles`，按机型差异留在脚本里）。
#
# 这三段的 `g["off_exact"]` 钩子在 #1253 搬进了 `recipe_strategies`（一加两台一档、PKH110 一档，
# 后者的打印与返回判据不同）；词库现在也扫策略库，未解析现场跟着实现走、读数不变。脚本把注入
# 实现绑回旧名字，段体不必改。`STORE_PROMOTIONS` 在 PHK110 / PKH110 是 26 条、PKX110 是 36 条，
# 一律按名字现取。

def browser_home(p, rt):
    if not nav.browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not nav.tap_page(p, rt, "主页设置", activity, "主页设置"):
        return False
    if p.find("简洁", exact=True):
        print("  · 首页已为简洁，保持不变")
        return True
    if not nav.tap_page(p, rt, "页面布局", activity, "页面布局"):
        return False
    if not p.tap("简洁", exact=True, scrolls=0):
        return False
    p.back()
    if not nav.wait_page(p, rt, activity, "主页设置") or not p.find("简洁", exact=True):
        return False
    p.changed.append(("浏览器主页", "默认 → 简洁"))
    return True




def _close_named_fn(rt):
    """共享段体里的 close_named 档位：默认小米那一档，PMX110 / PLZ110 用 optional（#1268）。"""
    if rt.constants.get("CLOSE_NAMED_OPTIONAL"):
        return strategies.close_named_optional
    return nav.close_named


def _off_exact_fn(rt):
    """共享段体里的 off_exact 档位：默认 paged，PKH110 用允许缺项的那一档（#1268）。"""
    if rt.constants.get("OFF_EXACT_OPTIONAL"):
        return strategies.off_exact_paged_optional
    return strategies.off_exact_paged

def store_promotions(p, rt):
    if not nav.open_app_settings(p, rt, "com.heytap.market",
                                 "com.heytap.market.mine.cn.setting.ui.SettingActivity",
                                 "应用与服务"):
        return False
    if not nav.tap_page(p, rt, "服务管理",
                         "com.heytap.market.mine.cn.setting.ui.ServeManagerActivity", "服务管理"):
        return False
    p.top(n=12)
    return _off_exact_fn(rt)(p, rt, rt.constants['STORE_PROMOTIONS'], "商店·推广入口")


def browser_ads(p, rt):
    if not nav.browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not nav.tap_page(p, rt, "隐私", activity, "隐私") or not nav.tap_page(p, rt, "广告管理", activity, "广告管理"):
        return False
    completed = _off_exact_fn(rt)(p, rt, ["开屏广告", "资讯列表广告"], "浏览器·广告管理", max_screens=2)
    print("  · 摇一摇广告可能随上级开关灰置；不将 checked=true 的灰置项计作独立关闭")
    return completed


def browser_personalized(p, rt):
    if not nav.browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not nav.tap_page(p, rt, "隐私", activity, "隐私") or not nav.tap_page(p, rt, "个性化管理", activity, "个性化管理"):
        return False
    return _off_exact_fn(rt)(p, rt, ["个性化优惠推荐", "个性化广告推荐"], "浏览器·个性化管理", max_screens=2)





# ---------- OPPO 两大对：PLZ110 / PMX110（#1213）----------
#
# 这一对走 ColorOS 17 的直达档：设置页有公开 Intent，`open_page` 落地后按具名行往下点，
# 不经过「我的」与齿轮。段体里的 `read_switches` / `close_named` / `require_installed` /
# `hide_carousel` 都是这两份脚本自己的 helper，按执行作用域现取。

def assistant_screen(p, rt):
    from fast import ScreenLocked
    l, t, r, b = bounds(nav.assistant_icon(p, rt))
    before = p.sig()
    p.click((l + r) // 2, (t + b) // 2)
    p.settle(before, 2.4)
    nav.row(p, rt, "设置", title="推荐服务")
    nav.row(p, rt, "推荐服务")
    where = p.focus()
    carousel_error = None
    try:
        nav.hide_carousel(p, rt)
    except (adb_link.DeviceLost, ScreenLocked):
        raise
    except RuntimeError as error:
        rt.require(p.focus() == where, "轮播识别失败且已离开原页，停止本段")
        carousel_error = error
        print(f"  ✗ 轮播推荐未确认：{error}；继续核对独立的热点资讯", flush=True)
    # 热点资讯页有导出，直达（沿用 #650 的做法），不用回设置页再滚动找
    hot_news = "am start -f 0x10008000 -n com.coloros.assistantscreen/com.oplus.assistantscreen.card.infoflow.setting.activity.InfoFlowSettingActivity"
    nav.open_page(p, rt, hot_news, "热点资讯", "com.coloros.assistantscreen", "InfoFlowSettingActivity")
    _close_named_fn(rt)(p, rt, ["热点资讯"], "热点资讯")
    if carousel_error:
        raise RuntimeError(f"热点资讯已核对；轮播推荐未完成：{carousel_error}")


def search_settings_direct(p, rt):
    nav.open_page(p, rt, rt.constants['SEARCH_SETTINGS'], "搜索范围", rt.constants['SEARCH'], "SearchSettingActivity")
    nav.row(p, rt, "搜索范围")
    _close_named_fn(rt)(p, rt, ["个性化推荐", "精选资讯"], "搜索范围", dependent=["全部"])
    p.back()
    nav.row(p, rt, "首页卡片管理")
    cards = nav.read_switches(p, rt, "首页卡片管理")
    names = [name for name in rt.constants['SEARCH_CARDS'] if name in cards]
    if names:
        _close_named_fn(rt)(p, rt, names, "首页卡片管理", snapshot=cards)
    missing = len(rt.constants['SEARCH_CARDS']) - len(names)
    if missing:
        note = f"首页卡片管理：本次未显示 {missing} 个录制推广项，未操作、不计为已关闭"
        rt.constants['SKIPPED_ITEMS'].append(note)
        print("  · " + note, flush=True)
    p.back()
    nav.row(p, rt, "功能管理")
    _close_named_fn(rt)(p, rt, ["搜索框提示词"], "功能管理")
    p.back()
    # 「账号与隐私」只是设置页上的分组标题，没有二级页面；直接点它下面的隐私行。
    nav.row(p, rt, "隐私")
    _close_named_fn(rt)(p, rt, ["个性化推荐"], "隐私")


def theme_store_settings(p, rt):
    nav.app_settings(p, rt, rt.constants['THEME'])
    nav.row(p, rt, "服务管理")
    nav.row(p, rt, "消息与广告")
    _close_named_fn(rt)(p, rt, ["开屏广告"], "消息与广告")
    nav.app_settings(p, rt, rt.constants['THEME'])
    nav.row(p, rt, "隐私")

    def reopen() -> None:
        nav.app_settings(p, rt, rt.constants['THEME'])
        nav.row(p, rt, "隐私")

    _close_named_fn(rt)(p, rt, ["个性化推荐设置"], "隐私", reopen=reopen)


def video_direct(p, rt):
    require_installed(p, rt, rt.constants['VIDEO'], "视频")
    # 设置页没导出，用 App 自己的深链直达（沿用 #650 的做法），不经开屏页和「我的」；带 -p 限定到视频，
    # 免得别的 App 也注册了这个 scheme 时弹选择器
    nav.open_page(p, rt, "am start -f 0x10008000 -a android.intent.action.VIEW -p " + rt.constants['VIDEO']
                   + " -d yoli://yoli.com/mine_act_lib_yoli/settings", "设置", rt.constants['VIDEO'], "SettingActivity")
    nav.row(p, rt, "个性化管理")
    _close_named_fn(rt)(p, rt, ["个性化广告推荐", "个性化内容推荐"], "个性化管理")


def game_center_direct(p, rt):
    require_installed(p, rt, rt.constants['GAME'], "游戏中心")
    nav.open_page(p, rt, "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + rt.constants['GAME'],
                   "游戏中心", rt.constants['GAME'], "SettingActivity")
    nav.row(p, rt, "隐私开关设置", scrolls=6)
    nav.row(p, rt, "个性化推荐管理", scrolls=4)
    _close_named_fn(rt)(p, rt, ["个性化推荐"], "个性化推荐管理")
    p.confirm()


def assistant_advice_rows(p, rt):
    nav.system_settings(p, rt)
    nav.row(p, rt, "OPPO AI")
    nav.row(p, rt, "小布建议")
    nav.row(p, rt, "资讯服务")
    _close_named_fn(rt)(p, rt, ["资讯服务"], "资讯服务")


# ---------- OPPO 两大对：PLR110 / PYB110（#1213）----------
#
# 这一对走手势与点击档：设置页没有可用的直达入口，靠下拉手势、底部标签与文字行找过去。
# 下拉搜索的 `search_settings` 是各自的本地 helper（PYB110 失败时抛错、PLR110 返回 False），
# 段体只按名字现取，两份实现继续留在脚本里。

def ad_tracking_close_all(p, rt):
    rt.skip_in_safe_mode()
    found = nav.settings_page(p, rt, "隐私与安全", "设备标识与广告", "广告跟踪")
    if not found:
        p.miss = 0
        found = nav.settings_page(p, rt, "隐私", "设备标识与广告", "广告跟踪")
    if not found:
        return
    # 右上角三个点（更多选项）菜单里有「全部关闭」，一键关完，比逐个点稳
    if p.tap("更多选项", exact=True, scrolls=0):
        if p.tap("全部关闭", exact=True, scrolls=0):
            p.confirm()                       # 有的版本会弹确认框
            rt.clock.sleep(0.5)
            still = [t for t, c, _ in p.switches() if c]
            if not still:
                p.changed.append(("广告跟踪", "全部关闭（更多选项菜单）"))
                return
            p.say(f"  ! 「全部关闭」后这一屏仍有 {len(still)} 个开关开着，退回逐项关")
        else:
            p.back()                          # 菜单开了但没点成：收起后退回逐个关
    p.miss = 0
    p.off(page="广告跟踪", max_screens=40)


def search_settings_swipe(p, rt):
    if not nav.search_settings(p, rt):
        raise RuntimeError("没进全局搜索设置页")
    if p.tap("搜索范围", exact=True):
        # APP内搜索、搜索建议、小程序、AI搜索、便捷服务保留
        p.off(only=["榜单", "小说", "购物", "个性化推荐", "精选资讯"], page="下拉搜索·搜索范围")
        p.back()
    if p.tap("首页卡片管理", exact=True):
        p.off(only=["未下载应用推荐", "应用建议小卡", "热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"], page="下拉搜索·首页卡片管理")
        p.back()
    if p.tap("功能管理", exact=True):
        p.off(only=["搜索框提示词"], page="下拉搜索·功能管理")
        p.back()
    if p.tap("账号与隐私", exact=True) and p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="下拉搜索·隐私")
        p.back(2)
    p.back(2)


def game_center_taps(p, rt):
    p.start("com.nearme.gamecenter")
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("没找到底部「我的」")
    rt.clock.sleep(1.2)
    p.dismiss()
    # 14.43.3：「设置」是「我的」页里带新通知标记的文字行（非右上角齿轮）
    if not p.tap("设置", exact=False, scrolls=0) and not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("没找到设置入口")
    if p.tap("隐私开关设置", exact=True) and p.tap("个性化推荐管理", exact=True):
        p.off(only=["个性化推荐"], page="游戏中心·个性化推荐管理")
    p.back(4)


def theme_shop_settings(p, rt):
    p.start("com.heytap.themestore")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("服务管理", exact=True):
        # 「全部服务/基础服务」保持全部服务；锁屏开关是功能项
        if nav.maybe(p, rt, "消息与广告"):
            p.off(only=["消息通知", "开屏广告"], page="主题·消息与广告")
            p.back()
        p.back()
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="主题·个性化推荐")
        p.back()
    p.back(2)


def assistant_advice_search(p, rt):
    if nav.settings_page(p, rt, "OPPO AI", "小布建议"):
        # 「内容资讯」是分组标题；「资讯服务」是子入口，进去关开关
        if p.tap("资讯服务", exact=True):
            p.off(only=["资讯服务"], page="小布建议·内容资讯")
            p.back()
    p.back(2)





# ---------- vivo（#1211）----------
#
# `settings_home` / `browser_settings` / `maybe` 都住在执行作用域里，按 `g` 现取；`time` 同理——
# 测试装载时它是假钟，内联 `import time` 会让等待变回真实睡眠。段体无形参，机型差异只能是
# 另一份实现：「系统广告」两簇一个用 `or` 认「安全 / 安全与隐私」两种叫法、一个直接串联，各占一个名字。

def browser_recommendations(p, rt):
    """浏览器设置页几处推荐开关。没有右上菜单按钮的机型整段跳过。"""
    p.start("com.vivo.browser")
    if not nav.browser_settings(p, rt):
        print("  ✗ 本机浏览器没有右上菜单按钮，跳过本段"); return
    print(f"  · 浏览器设置页 {p.focus()}")
    if nav.maybe(p, rt, "首页设置"):
        nav.maybe(p, rt, "极简首页", scrolls=0)
        p.off(only=["首页上滑展示资讯"], page="浏览器·首页设置"); p.back()
    p.top()
    if nav.maybe(p, rt, "网页浏览设置"):
        p.off(only=["网页下载相关推荐"], page="浏览器·网页浏览"); p.back()
    p.top()
    if nav.maybe(p, rt, "更多设置"):
        p.off(only=["WiFi连接跳转新闻资讯", "WiFi 连接跳转新闻资讯", "跳转新闻资讯",
                    "下载管理页展示热门应用", "下载管理页展示下载热榜"], page="浏览器·更多设置"); p.back()
    p.top()
    if nav.maybe(p, rt, "隐私权限设置"):
        p.off(only=["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], page="浏览器·隐私"); p.back()
    p.back(2)


def i_manager_ads(p, rt):
    """i管家「关于 → 个性化设置」，直达 MainSettings 页。"""
    p.d.shell("am start -f 0x10008000 -n com.iqoo.secure/.MainSettings")
    rt.clock.sleep(1.0)
    if nav.maybe(p, rt, "关于") and nav.maybe(p, rt, "个性化设置"):
        p.off(only=["应用个性化推荐", "清理个性化推荐"], page="i管家·个性化设置")
    p.back(3)


def lock_screen_magazine(p, rt):
    """桌面、锁屏与壁纸 → 锁屏设置 → 阅图锁屏。"""
    nav.settings_home(p, rt)
    if nav.maybe(p, rt, "桌面、锁屏与壁纸") and nav.maybe(p, rt, "锁屏设置") and nav.maybe(p, rt, "阅图锁屏"):
        p.off(only=["阅图锁屏", "锁屏横滑进入阅图"], page="阅图锁屏")


def system_ads_branch(p, rt):
    """系统设置里的「广告与隐私」：首屏入口读作「安全」或「安全与隐私」两种都认。"""
    nav.settings_home(p, rt)
    if nav.maybe(p, rt, "安全") or nav.maybe(p, rt, "安全与隐私"):
        if nav.maybe(p, rt, "更多安全设置") and nav.maybe(p, rt, "广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")


def system_ads_chain(p, rt):
    """系统设置里的「广告与隐私」：一路串联认「安全 → 更多安全设置 → 广告与隐私」。"""
    nav.settings_home(p, rt)
    if nav.maybe(p, rt, "安全") and nav.maybe(p, rt, "更多安全设置") and nav.maybe(p, rt, "广告与隐私"):
        p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")


def global_search_ads(p, rt):
    """系统管理与升级 → 全局搜索 的三个子页；历史记录与应用建议保留。"""
    nav.settings_home(p, rt)
    if nav.maybe(p, rt, "系统管理与升级") and nav.maybe(p, rt, "全局搜索"):
        if nav.maybe(p, rt, "首页展示内容"):
            p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
        if nav.maybe(p, rt, "推荐热搜榜单", scrolls=2):
            p.off(only=["热门搜索"], page="全局搜索·热搜榜单"); p.back()
        if nav.maybe(p, rt, "个性化内容"):
            p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()


def weather_service(p, rt):
    """天气设置页只关「天气服务」（天气相关热点资讯通知），预警类三个开关同页保留。"""
    p.d.shell("am start -f 0x10008000 -n com.vivo.weather/.WeatherSettings")
    rt.clock.sleep(1.0)
    p.off(only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")
    p.back(1)


def require_installed(p, rt, package, label):
    """没装的包 `pm path` 输出为空，退出码是 1 或 0：那是「没装」，跳过本段（#899）。"""
    result = p.d.shell("pm path " + package)
    if "package:" in result.output:
        return
    rt.require(result.exit_code in (0, 1) and not result.output.strip(), f"无法读取{label}安装状态")
    rt.skip(f"本机未安装{label}")
