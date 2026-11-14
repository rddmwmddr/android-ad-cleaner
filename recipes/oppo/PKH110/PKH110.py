# OPPO Find N5（PKH110，ColorOS 17.0.0.103）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 tap_page / close_titles / off_exact_paged_optional 与 require / skip 由装载器注入执行作用域。
# 段体的条件分支、逐项精确标题与等待循环留下，逐字保留原实现；线性的两段已转成数据。
import time
import recipe_nav as nav
import recipe_strategies as strategies


BUILD = "PKH110_17.0.0.103"
MODELS = ["PKH110"]

# 仅关闭明确列名的推广入口。没有列出的入口（包括未来新增项）不主动处理。
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "游戏专区：找游戏-种草", "游戏专区：重磅更新卡片", "游戏详情页：游戏活动卡片",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "游戏详情页：游戏礼包",
    "手机管家：应用推荐", "文件管理：应用推荐", "游戏专区：活动集合", "详情页：限时活动", "福利专区",
]

# 段体（store_promotions）按 `g["off_exact"]` 取这个钩子，实现住在 recipe_strategies 的
# `off_exact_paged_optional`（本机「未找到」不算失败），这里绑回旧名字（#1253）。


def guard(p, rt):
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model not in MODELS or not build.startswith(BUILD):
        rt.skip("型号或系统版本不同，跳过；请重新核对页面")


def step_ad_tracking(p, rt):
    # ColorOS 17：「隐私」已并入「隐私与安全」。设置搜索能搜到「设备标识与广告」但点搜索结果不跳转，
    # 因此走面板路径；该页 Activity 为 OplusSettingsActivity$DevicesIdentifySettingsActivity。
    rt.skip_in_safe_mode()
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    time.sleep(1.5)
    if not p.tap("隐私与安全", scrolls=3):
        print("  ✗ 没找到「隐私与安全」")
        return False
    time.sleep(1.5)
    if not nav.tap_page(p, rt, "设备标识与广告", "DevicesIdentifySettingsActivity", "设备标识与广告"):
        return False
    if not nav.tap_page(p, rt, "广告跟踪", "OAIDActivity", "广告跟踪"):
        return False
    # 等应用列表真正加载，不能把只有标题的空白加载页视为完成。
    for _ in range(30):
        if p.switches():
            break
        time.sleep(0.2)
    if not p.switches():
        print("  ✗ 广告跟踪列表未加载")
        return False
    p.top(n=16)
    p.off(page="广告跟踪", max_screens=40)
    return True


def step_browser_ads(p, rt):
    if not nav.browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not nav.tap_page(p, rt, "隐私", activity, "隐私") or not nav.tap_page(p, rt, "广告管理", activity, "广告管理"):
        return False
    completed = strategies.off_exact_paged_optional(p, rt, ["开屏广告", "资讯列表广告"], "浏览器·广告管理", max_screens=2)
    print("  · 摇一摇广告可能随上级开关灰置；灰置项不计作独立关闭")
    return completed


def step_browser_personalized(p, rt):
    # 该页只有「个性化内容推荐」「个性化广告推荐」两项；两项都开时只读到后者的 Switch。
    if not nav.browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not nav.tap_page(p, rt, "隐私", activity, "隐私") or not nav.tap_page(p, rt, "个性化管理", activity, "个性化管理"):
        return False
    return strategies.close_titles(p, rt, ["个性化广告推荐"])


def step_theme(p, rt):
    # 主题商店的 APP_SETTINGS 页没有固定标题（ColorOS 17 直接落在 SettingActivity 列表），
    # 因此这里只确认前台包名，不等页标题。
    p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.themestore")
    time.sleep(2.5)
    if not p.focus().startswith("com.heytap.themestore"):
        print("  ✗ 主题商店设置页没有打开")
        return False
    if p.tap("服务管理", exact=True, scrolls=3):
        if p.tap("消息与广告", exact=True, scrolls=2):
            time.sleep(1.2)
            p.off(only=["消息通知", "开屏广告"], page="主题·消息与广告", max_screens=2)
            p.back()
        p.back()
    # 「个性化推荐设置」是二级页，打不开就跳过，不做整页全关。
    return True


def step_search(p, rt):
    if not nav.open_search_settings(p, rt):
        return False
    # 「搜索范围」页全是数据源（本机应用、相册、网页搜索结果等），关掉会搜不到东西，不动。
    if p.tap("首页卡片管理", exact=True, scrolls=3):
        time.sleep(1.8)
        # 关掉「探索发现」后，它下面的「每日热榜」「推荐卡片」会从列表里一并消失。
        strategies.close_titles(p, rt, ["未下载应用推荐", "应用建议小卡", "探索发现", "每日热榜", "推荐卡片"])
        p.back()
        time.sleep(1)
    else:
        print("  ✗ 没找到「首页卡片管理」")
    if not nav.open_search_settings(p, rt):
        return False
    if p.tap("功能管理", exact=True, scrolls=3):
        time.sleep(1.8)
        strategies.close_titles(p, rt, ["搜索框提示词", "搜索框顶部推荐词", "猜你想搜"])
        p.back()
    else:
        print("  ✗ 没找到「功能管理」")
    return True


def tail(p, rt):
    print("\n本机型脚本不处理：负一屏（设置页受 oppo.permission.OPPO_COMPONENT_SAFE 保护，"
          "adb 边缘手势进不去，需机主手动在负一屏内关「热点资讯」「轮播推荐」）、OPPO 视频、游戏中心。")
    print("分段结果：", rt.results)
