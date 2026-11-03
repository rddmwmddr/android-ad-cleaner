# 小米 / Redmi HyperOS 3 机型脚本：Redmi Note 14 Pro（24090RA29C）
# 路径来源：2026-10-26 真机实测，HyperOS OS3.0.309.0.WOOCNXM（Android 16，BP2A.250605.031.A3）。
# 与 M154FF（OS4.0）的差异：系统广告的「更多安全设置」在「安全」标签页下，不在隐私页首屏；
# 主题、浏览器的设置是无文字齿轮（content-desc=设置），首页「我的」是底部标签。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS3.0.309.0"
MODELS = ["24090RA29C"]
import time

ONLY = globals().get("ONLY") or []


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
                print(f"  ✗ 出错：{e}")
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
    # 下载管理、天气和日历的齿轮藏在右上「更多」菜单里。
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


def browser_settings():
    """先看工具栏，再点底部「我的」；不把资讯正文里的「我的」当导航标签。"""
    before = p.focus()
    if gear(toolbar_only=True):
        if p.in_settings_page():          # 点完要认出设置页，点击被吞时别在旧页上找入口（#331）
            return True
        if p.focus() != before:
            p.back()
    for text, (l, t, r, b), node in p.texts():
        if text == "我的" and t >= p.H * 0.65:
            before = p.sig()
            p.click((l + r) // 2, (t + b) // 2)
            p.settle(before, 1.5)
            p.dismiss()                    # 「我的」页可能先弹一键登录框，关掉再找齿轮
            return gear()
    return False


def tap_tab(name):
    """点顶部标签页（隐私/安全）：标签是可点容器，内层文字节点不可点。"""
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


def tap_any(*names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(n, scrolls) for n in names)


def maybe(name, scrolls=6):
    """可选入口：有就点，没有不报「走丢」。"""
    return p.entry(name, scrolls=scrolls)


@step("系统广告")
def _():
    # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not maybe("隐私与安全"):
        return
    # OS3.0：隐私页首屏没有「更多安全设置」，它在「安全」标签页下
    if not maybe("更多安全设置"):
        tap_tab("安全")
        maybe("更多安全设置")
    if maybe("广告服务"):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    gear()
    if tap_any("隐私设置", "隐私"):
        # 「个性化服务」可能是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("模式切换"):                       # 新版商店没有这一项
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞/评论消息一起关
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


@step("手机管家")
def _():
    # 新版手机管家可能没有这两项；有就关，没有跳过
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
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    # 桌面入口在 themestore，内部会跳到 thememanager，前台包两种都会出现；start() 的前台断言
    # 会误判，这里直接 am 拉起并等待，不做前台包校验。
    if "package:" in p.d.shell("pm path com.miui.themestore").output:
        p.d.shell("am start -n com.miui.themestore/com.miui.thememanagerstore.ThemeResourceTabActivity")
    else:
        p.d.shell("monkey -p com.android.thememanager -c android.intent.category.LAUNCHER 1")
    time.sleep(3)
    p.dismiss()
    # 底部「我的」标签 → 右上齿轮（desc=设置，无文字）
    for text, (l, t, r, b), node in p.texts():
        if text == "我的" and t >= p.H * 0.65:
            before = p.sig()
            p.click((l + r) // 2, (t + b) // 2)
            p.settle(before, 1.5)
            break
    p.dismiss()
    gear()
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # 首页「默认 / 探索版 / 自定义主页」不改：按机主喜好。
    # 底栏「我的」标签在部分启动状态下点不动，直达设置页 Activity，绕开首页导航。
    p.d.shell("am start -n com.android.browser/.BrowserSettingsActivity")
    time.sleep(2)
    p.dismiss()
    if maybe("隐私和安全"):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if maybe(page):                           # 新版浏览器这三项都没有，有就关
            p.off(only=only, page=f"浏览器·{page}"); p.back()
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
