# OPPO Find N5（PKH110，ColorOS 17.0.0.103）机型脚本。
# 路径实测：2026-10-29。只收录已走通的系统广告跟踪、商店、浏览器、主题、下拉搜索。
# 不挂包、不动通知渠道；这些操作仍走 run.py 的独立、需确认流程。
BUILD = "PKH110_17.0.0.103"
MODELS = ["PKH110"]

import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
RESULTS = []

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


def step(name):
    def deco(function):
        if ONLY and name not in ONLY:
            return function
        model = p.d.shell("getprop ro.product.model").output.strip()
        build = p.d.shell("getprop ro.build.display.id").output.strip()
        if model not in MODELS or not build.startswith(BUILD):
            print(f"\n== {name}：型号或系统版本不同，跳过；请重新核对页面")
            RESULTS.append((name, "version_mismatch"))
            return function
        if p.locked():
            print(f"\n== {name}：手机锁屏，跳过，请机主解锁")
            RESULTS.append((name, "locked"))
            return function
        print(f"\n== {name}", flush=True)
        p.miss = 0
        started = time.monotonic()
        try:
            completed = function()
            state = "completed" if completed else "incomplete"
        except Exception as error:
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{error}")
            state = "failed"
        RESULTS.append((name, state))
        print(f"  ({time.monotonic() - started:.0f} 秒，{state})", flush=True)
        return function
    return deco


def wait_page(activity, title, timeout=6):
    """等活动、页标题和可点击区域连续稳定，避免横向动画期间的越界坐标。"""
    deadline, previous = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        if p.locked():
            return False
        if not p.focus().endswith(activity):
            time.sleep(0.2)
            continue
        root = p.tree()
        texts = p.texts(root)
        # 只识别真正的同意按钮，不把设置页里的「隐私政策」链接当作协议弹窗。
        if any(t in ("同意", "同意并继续", "同意并使用", "允许")
               and "Button" in n.get("class", "") for t, _, n in texts):
            print("  ! 出现协议/权限按钮，本段跳过，不代为同意")
            return False
        if not any(t == title for t, _, _ in texts):
            time.sleep(0.2)
            continue
        switches = p.switches(root)
        if any(not (0 < xy[0] < p.W and 0 < xy[1] < p.H) for _, _, xy in switches):
            time.sleep(0.2)
            continue
        signature = tuple(t for t, _, _ in texts), tuple(switches)
        if signature == previous:
            return True
        previous = signature
        time.sleep(0.25)
    print(f"  ✗ 未确认目标页面「{title}」，不操作开关")
    return False


def open_app_settings(package, activity, title):
    """公开设置 Intent 直达，绕开含账号信息的「我的」页。"""
    result = p.d.shell(
        "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package
    ).output
    if "Permission Denial" in result or "SecurityException" in result:
        print("  ! 系统不允许直达设置，跳过，不提升权限")
        return False
    return wait_page(activity, title)


def tap_page(text, activity, title):
    return p.tap(text, exact=True) and wait_page(activity, title)


def close_titles(wanted, max_rounds=8):
    """逐页只点标题完全等于 wanted 里某项的开关，点完回读。
    ColorOS 17 有「应用建议」是「应用建议小卡」子串的情况，p.off 的子串匹配会误伤，所以用精确标题。"""
    remaining, failed = list(wanted), []
    for _ in range(max_rounds):
        cur = {t: (c, xy) for t, c, xy in p.switches()}
        hit = [t for t in remaining if t in cur]
        for t in hit:
            cur = {t2: (c, xy) for t2, c, xy in p.switches()}
            was_on = bool(cur.get(t, (False, None))[0])
            for _ in range(3):
                cur = {t2: (c, xy) for t2, c, xy in p.switches()}
                if t not in cur:
                    break
                c, xy = cur[t]
                if not c:
                    break
                if not (0 < xy[0] < p.W and 0 < xy[1] < p.H):
                    print(f"  ! 「{t}」坐标越界，跳过不做")
                    break
                p.click(*xy)
                time.sleep(0.5)
                p.confirm()
                time.sleep(0.5)
            final = {t2: c for t2, c, _ in p.switches()}
            remaining.remove(t)
            if final.get(t) is False:
                print(f"  {'关' if was_on else '· 已是关闭状态'} {t}")
            elif t in final:
                print(f"  ✗ 关不掉 {t}")
                failed.append(t)
        if not remaining:
            break
        if not p.scroll_more():
            break
    if remaining:
        print(f"  ! 未找到 {remaining}")
    return not failed and not remaining


def off_exact(names, page, max_screens=16):
    """逐页传入当前可见的精确标题，不把子串扩展到未知服务（用于需要翻多屏的页面）。"""
    wanted, seen, failed = set(names), set(), set()
    for _ in range(max_screens):
        root = p.tree()
        visible = {title for title, _, _ in p.switches(root)}
        targets = wanted & visible
        seen.update(targets)
        if targets:
            before = len(p.changed)
            expected = {title for title, on, _ in p.switches(root) if on and title in targets}
            p.off(only=list(targets), keep=list(visible - targets), page=page, max_screens=1)
            changed = {title for _, title in p.changed[before:]}
            failed.update(expected - changed)
        elif not p.scroll_more():
            break
        current = {title for title, _, _ in p.switches()}
        if current == visible:
            break
    if failed or wanted - seen:
        print(f"  ! 未关闭 {sorted(failed)}；本机型无此项 {sorted(wanted - seen)}")
        return not failed
    return True


@step("广告跟踪")
def _():
    # ColorOS 17：「隐私」已并入「隐私与安全」。设置搜索能搜到「设备标识与广告」但点搜索结果不跳转，
    # 因此走面板路径；该页 Activity 为 OplusSettingsActivity$DevicesIdentifySettingsActivity。
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    time.sleep(1.5)
    if not p.tap("隐私与安全", scrolls=3):
        print("  ✗ 没找到「隐私与安全」")
        return False
    time.sleep(1.5)
    if not tap_page("设备标识与广告", "DevicesIdentifySettingsActivity", "设备标识与广告"):
        return False
    if not tap_page("广告跟踪", "OAIDActivity", "广告跟踪"):
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


@step("软件商店")
def _():
    if not open_app_settings("com.heytap.market",
                             "com.heytap.market.mine.cn.setting.ui.SettingActivity", "应用与服务"):
        return False
    if not tap_page("服务管理", "com.heytap.market.mine.cn.setting.ui.ServeManagerActivity", "服务管理"):
        return False
    p.top(n=12)
    return off_exact(STORE_PROMOTIONS, "商店·推广入口")


def browser_settings():
    return open_app_settings("com.heytap.browser",
                             "com.heytap.browser.settings.component.BrowserPreferencesPage", "浏览器")


@step("浏览器首页")
def _():
    if not browser_settings():
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page("主页设置", activity, "主页设置"):
        return False
    if p.find("简洁", exact=True):
        print("  · 首页已为简洁，保持不变")
        return True
    if not tap_page("页面布局", activity, "页面布局"):
        return False
    if not p.tap("简洁", exact=True, scrolls=0):
        return False
    p.back()
    if not wait_page(activity, "主页设置") or not p.find("简洁", exact=True):
        return False
    p.changed.append(("浏览器主页", "默认 → 简洁"))
    return True


@step("浏览器广告")
def _():
    if not browser_settings():
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page("隐私", activity, "隐私") or not tap_page("广告管理", activity, "广告管理"):
        return False
    completed = off_exact(["开屏广告", "资讯列表广告"], "浏览器·广告管理", max_screens=2)
    print("  · 摇一摇广告可能随上级开关灰置；灰置项不计作独立关闭")
    return completed


@step("浏览器个性化")
def _():
    # 该页只有「个性化内容推荐」「个性化广告推荐」两项；两项都开时只读到后者的 Switch。
    if not browser_settings():
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page("隐私", activity, "隐私") or not tap_page("个性化管理", activity, "个性化管理"):
        return False
    return close_titles(["个性化广告推荐"])


@step("主题商店")
def _():
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


def open_search_settings():
    """ColorOS 17 的下拉搜索设置挂在 quicksearchbox 里；桌面下滑手势在 adb 下不稳定，直接拉 Activity。"""
    p.d.shell("am start -f 0x10008000 -n com.heytap.quicksearchbox/.ui.activity.SearchHomeActivity")
    time.sleep(2.2)
    p.d.shell("input keyevent BACK")          # 收键盘
    time.sleep(0.8)
    cands = sorted((tp, l, tp, r, b) for t, (l, tp, r, b), _ in p.texts() if t == "设置")
    if not cands:
        print("  ✗ 搜索页没有「设置」入口")
        return False
    _, l, tp, r, b = cands[-1]                # 底部那个才是搜索设置
    p.click((l + r) // 2, (tp + b) // 2)
    time.sleep(2)
    return p.focus().endswith("SearchSettingActivity")


@step("下拉搜索")
def _():
    if not open_search_settings():
        return False
    # 「搜索范围」页全是数据源（本机应用、相册、网页搜索结果等），关掉会搜不到东西，不动。
    if p.tap("首页卡片管理", exact=True, scrolls=3):
        time.sleep(1.8)
        # 关掉「探索发现」后，它下面的「每日热榜」「推荐卡片」会从列表里一并消失。
        close_titles(["未下载应用推荐", "应用建议小卡", "探索发现", "每日热榜", "推荐卡片"])
        p.back()
        time.sleep(1)
    else:
        print("  ✗ 没找到「首页卡片管理」")
    if not open_search_settings():
        return False
    if p.tap("功能管理", exact=True, scrolls=3):
        time.sleep(1.8)
        close_titles(["搜索框提示词", "搜索框顶部推荐词", "猜你想搜"])
        p.back()
    else:
        print("  ✗ 没找到「功能管理」")
    return True


print("\n本机型脚本不处理：负一屏（设置页受 oppo.permission.OPPO_COMPONENT_SAFE 保护，"
      "adb 边缘手势进不去，需机主手动在负一屏内关「热点资讯」「轮播推荐」）、OPPO 视频、游戏中心。")
print("分段结果：", RESULTS)
