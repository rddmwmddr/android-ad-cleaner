# Redmi Note 14 5G（24094RAD4C，代号 beryl），HyperOS OS3.0.306.0.WOQCNXM / Android 16。
# 2026-10-30 真机逐段核对：入口与 Redmi Note 14 Pro 的 OS3 脚本基本一致。
# 本脚本只处理点名的广告/推荐开关；应用商店保持标准模式，自动更新和删除安装包保留，
# 浏览器「小说」「我的网盘」等功能项保留，天气预警等安全通知也不在范围内。
# 用法：python tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS3.0.306.0"
MODELS = ["24094RAD4C"]
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


def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
    重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（#305 / #374）。"""
    from fast import bounds, icon_hit

    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        icon = "ImageView" in n.get("class", "") and r-l < p.W * 0.25 and b-t < p.H * 0.15
        if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n) and (not toolbar_only or b < p.H * 0.23):
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    if not toolbar_only and p.find("设置", exact=True, edge_ok="tab"):
        return p.tap("设置", exact=True, scrolls=0)
    for n in p.tree().iter("node"):
        key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
        from fast import bounds
        l, t, r, b = bounds(n)
        if any(k in key.lower() for k in ("更多", "more", "menu")) and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22:
            p.click((l + r) // 2, (t + b) // 2); time.sleep(0.5)
            if p.tap("设置", exact=True, scrolls=0):
                return True
            break
    return False


def tap_tab(name):
    """点顶部标签页；内层文字节点不可点，点外层的可点容器。"""
    for n in p.tree().iter("node"):
        if n.get("clickable") != "true":
            continue
        label = (n.get("text") or "") + (n.get("content-desc") or "")
        from fast import bounds
        l, t, r, b = bounds(n)
        if name in label and t < p.H * 0.3 and p.on_screen(n):
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    return p.tap(name, exact=True, scrolls=0)


def tap_bottom_tab(name):
    """按屏幕底部标签栏找入口，避开内容区里同名的普通文字。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("text") or "")
        if not d or name not in d:
            continue
        l, t, r, b = bounds(n)
        if b > p.H * 0.85 and p.on_screen(n):
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1.5)
            return True
    return False


def wait_bottom_tab(name, tries=5):
    """主题商店冷启动先出开屏或更新层，底部栏可能晚几秒才稳定。"""
    for _ in range(tries):
        p.dismiss()
        if tap_bottom_tab(name):
            return True
        time.sleep(0.8)
    return False


def maybe(name, scrolls=6):
    """可选入口：有就点，没有不报「走丢」。"""
    return p.entry(name, scrolls=scrolls)


def tap_any(*names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(n, scrolls) for n in names)


def close_with_plain_tap(names, page):
    """下载管理和浏览器会吞掉短按；普通 tap 后确认，并核对其他开关未变。"""
    before = {title: on for title, on, _ in p.switches()}
    targets = [title for title in before if any(name in title for name in names)]
    if not all(any(name in title for title in targets) for name in names):
        raise RuntimeError(f"{page}：未识别全部目标开关，未操作")
    for title in targets:
        if not before[title]:
            continue
        xy = next((xy for t, on, xy in p.switches() if t == title and on), None)
        if not xy:
            raise RuntimeError(f"{page}：目标开关位置未识别，停止本页")
        p.d.shell(f"input tap {xy[0]} {xy[1]}")
        time.sleep(0.5)
        p.confirm()
    after = {title: on for title, on, _ in p.switches()}
    if any(after.get(title) is not False for title in targets):
        raise RuntimeError(f"{page}：回读未确认关闭")
    if any(after.get(title) != state for title, state in before.items() if title not in targets):
        raise RuntimeError(f"{page}：其他开关状态变化，请核对")
    turned = [title for title in targets if before[title] and after.get(title) is False]
    for title in turned:
        print(f"  关 {title}")
        p.changed.append((page, title))
    print(f"  · {page}：核对 {len(targets)} 项，调整 {len(turned)} 项")


@step("系统广告")
def _():
    # HyperOS 3：隐私页首屏没有「更多安全设置」，它在「安全」标签页下。
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not maybe("隐私与安全"):
        return
    tap_tab("安全")
    if not maybe("更多安全设置"):
        return
    if maybe("广告服务"):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    p.start("com.xiaomi.market")
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0)
    if not tap_bottom_tab("我的"):
        raise RuntimeError("商店底部「我的」标签没有找到")
    if not gear():
        raise RuntimeError("商店设置入口没有找到")
    if tap_any("隐私设置", "隐私"):
        # 「个性化服务」是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰父开关「推送消息」，应用更新也保留。
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


@step("手机管家")
def _():
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
    if maybe("垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
    p.back(2)


@step("下载管理")
def _():
    p.start("com.android.providers.downloads.ui")
    if not gear():
        raise RuntimeError("下载管理设置入口未找到")
    if maybe("信息流设置"):
        close_with_plain_tap(["资源推荐", "热榜推荐"], "下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    # 桌面入口在 themestore，内部会跳到 thememanager。冷启动偶有可跳过的开屏广告。
    if "package:" in p.d.shell("pm path com.miui.themestore").output:
        p.d.shell("am start -f 0x10008000 -n com.miui.themestore/com.miui.thememanagerstore.ThemeResourceTabActivity")
    else:
        # 没有主题商店时直接起 thememanager：它没有 LAUNCHER activity，monkey 拉不起来（#730）
        if "package:" not in p.d.shell("pm path com.android.thememanager").output:
            print("  · 本机没有主题商店，跳过"); return
        p.start("com.android.thememanager", ".ThemeResourceProxyTabActivity")
    time.sleep(3)
    if p.find("跳过广告"):
        p.tap("跳过广告", scrolls=0)
    if not wait_bottom_tab("我的"):
        raise RuntimeError("主题商店底部「我的」标签没有找到")
    p.dismiss()
    if not gear():
        raise RuntimeError("主题商店设置入口没有找到")
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # 直达设置页，绕开首页导航；主页布局和功能入口按机主当前选择保留。
    p.d.shell("am start -f 0x10008000 -n com.android.browser/.BrowserSettingsActivity")
    time.sleep(2)
    p.dismiss()
    if maybe("隐私和安全"):
        close_with_plain_tap(["个性化内容推荐", "个性化广告推荐"], "浏览器·隐私和安全")
        p.back()
        time.sleep(1)
        p.top(8)
    if maybe("主页设置"):
        p.off(only=["宫格位推送"], page="浏览器·主页设置"); p.back()
    if maybe("搜索设置"):
        p.off(only=["猜你想搜"], page="浏览器·搜索设置"); p.back()
    p.back(2)


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("全局搜索")
def _():
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if maybe("首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if maybe("应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐"); p.back()
        if maybe("热搜榜单"):
            subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
            if p.switches():
                p.off(only=HOT, page="搜索·热搜榜单")
            if subs:
                p.top()
                for x in subs:
                    if maybe(x):
                        p.off(only=HOT, page=f"搜索·热榜·{x}"); p.back()
            p.back()
        p.back()
    p.back(2)


@step("负一屏")
def _():
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框、出行助手保留
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
    p.back()
