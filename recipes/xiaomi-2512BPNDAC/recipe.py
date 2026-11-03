# 小米 HyperOS 4 机型脚本：Xiaomi 17 Ultra（2512BPNDAC，标准版，非徕卡版）
# 2026-10-28 真机实测：HyperOS OS4.0.5.0.XPACNXM / Android 17（SDK 37）/ 系统底包 CP2A.260605.016
# 与 Xiaomi 18 Pro Max、18 Fold 同一个系统底包，但这台的入口有四处不同，都写在本脚本里：
#   ① 系统广告：「广告服务」页只有「个性化广告推荐」；「系统工具广告」是另一个独立页面，
#      只能靠设置搜索命中「系统广告」进去。两条都用 p.setting 直达。
#   ② 应用商店 / 主题：底部「我的」标签的文字能被找到，但点进去后没有「设置」两个字（齿轮是纯图标），
#      所以不能写 p.go("我的", "设置")，要按底部位置点标签再找齿轮。
#      商店设置页会记住上次滚动位置，找「隐私设置」前先滑回页顶。
#   ③ 浏览器：工具栏最右的「设置」按钮点进去是「页面布局」子页，不是设置；
#      正确路径是 底部「菜单」→ 弹窗右上角「设置」。「隐私和安全」在主设置页最底部，要滚动。
#   ④ 日历：右上「更多」对 uiautomator 的点击不响应，只能走 adb input tap；
#      「用户体验计划」在设置页倒数第二项，得先滚到底再点。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS4.0.5.0"
MODELS = ["2512BPNDAC"]
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


def maybe(name, scrolls=6):
    """可选入口：有就点，没有不报「走丢」。"""
    return p.entry(name, scrolls=scrolls)


def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
    重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（#305 / #374）。"""
    from fast import bounds, icon_hit

    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        if icon_hit(n) and (n.get("clickable") == "true" or "ImageView" in n.get("class", "")) and p.on_screen(n) and (not toolbar_only or b < p.H * 0.23):
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    # 兜底：正文正好是「设置」两个字的一行（有些 App 是文字入口），只在屏幕上半部分找，
    # 免得点到正文中间的「…设置…」长句。
    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        if (n.get("text") or "").strip() == "设置" and n.get("clickable") == "true" and b < p.H * 0.45 and p.on_screen(n):
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    # 下载管理、天气的齿轮藏在右上「更多」菜单里。
    for n in p.tree().iter("node"):
        key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
        l, t, r, b = bounds(n)
        if any(k in key.lower() for k in ("更多", "more", "menu")) and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22:
            p.click((l + r) // 2, (t + b) // 2); time.sleep(0.5)
            if p.tap("设置", exact=True, scrolls=0):
                return True
            break
    return False


def by_id(rid, wait=1.5):
    """按 resource-id 点控件：这台浏览器工具栏和弹窗里各有一个叫「设置」的图标，按文字会点错。"""
    from fast import bounds
    t0 = time.time()
    while time.time() - t0 < wait:
        for n in p.tree().iter("node"):
            if n.get("resource-id") == rid:
                l, t, r, b = bounds(n)
                p.click((l + r) // 2, (t + b) // 2)
                return True
        time.sleep(0.2)
    return False


def bottom_tab(name="我的"):
    """点底部标签。这些 App 的标签文字能找到，但点进去后没有带文字的「设置」，
    所以不能写 p.go("我的", "设置")。"""
    for t, (l, top, r, b), n in p.texts():
        if t.strip() == name and top > p.H * 0.85:
            p.click((l + r) // 2, (top + b) // 2); time.sleep(2.5)
            return True
    return False


def tap_low(name, tries=3):
    """页底最后那一项（商店的「隐私设置」）：读屏读得到，但坐标超过引擎的点击安全线，
    要轻滑一小段再点。别用 tap(scrolls=N)：它翻页会直接翻过这一项，翻进「功能设置」子页。"""
    for _ in range(tries):
        if p.tap(name, exact=True, scrolls=0):
            return True
        p.d.shell("input swipe 600 2000 600 1700 150"); time.sleep(0.7)
    return False


@step("系统广告")
def _():
    # 两条设置搜索直达。不走「隐私与安全 → 安全 → 更多安全设置」：这台的「隐私与安全」是安全中心
    # PrivacySafetyActivity，默认停在「隐私」分栏，「安全」标签用读屏点经常点不动。
    if p.setting("广告服务"):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")
    if p.setting("系统广告"):
        # 「在系统工具应用中会出现少量广告推荐」——天气、日历、音乐等系统工具里广告的总闸。
        p.off(only=["系统工具广告"], page="系统·系统广告")


@step("应用商店")
def _():
    p.start("com.xiaomi.market")
    if not bottom_tab("我的"):
        p.go("我的", "设置")
    gear()
    if tap_low("隐私设置") or tap_low("隐私"):
        # 4.129.s.00 的「个性化服务」是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    # 「模式切换 → 极简模式」这版商店有，但切换后商店只剩搜索、安装、更新，界面变化明显，
    # 不属于「关广告开关」，脚本不自动切。需要的话手动切。
    if p.find("模式切换", exact=True):
        print("  · 有「模式切换 → 极简模式」，界面变化明显，未自动切换")
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞、评论消息一起关。
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
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    # HyperOS 4 桌面入口在 themestore，打开后转到 thememanager；后者本身没有 LAUNCHER。
    if "package:" in p.d.shell("pm path com.miui.themestore").output:
        p.start("com.miui.themestore", foreground="com.android.thememanager")
    else:
        p.start("com.android.thememanager")
    if not bottom_tab("我的"):
        p.go("我的", "设置")
    gear()
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    p.start("com.android.browser")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    # 工具栏最右那个「设置」按钮点进去是「页面布局」子页（这版特有）。
    # 正确路径：底部「菜单」→ 弹窗右上角「设置」，用 resource-id 定位。
    if not by_id("com.android.browser:id/action_more"):
        raise RuntimeError("浏览器底部「菜单」未找到")
    time.sleep(1)
    if not by_id("com.android.browser:id/action_menu_setting"):
        raise RuntimeError("菜单弹窗里的「设置」未找到")
    time.sleep(2)
    # 「隐私和安全」在主设置页最底部（第 13 项之后），必须滚动
    if maybe("隐私和安全", scrolls=8):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if maybe(page):
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


@step("天气和日历")
def _():
    # 天气：底部城市管理 → 右上更多 → 设置 → 用户体验计划。「天气预警提醒」「异常天气提醒」是安全功能，不动。
    p.start("com.miui.weather2")
    if p.find("城市管理", exact=True, edge_ok="tab"):
        p.tap("城市管理", exact=True, scrolls=0)
    if gear():
        if maybe("用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page="天气·用户体验计划"); p.back()
        p.back(3)

    # 日历：右上「更多」→ 设置 → 滚到底 → 倒数第二项「用户体验计划」。
    # 这版日历的「更多」和「设置」对 uiautomator 的点击不响应，只能走 adb input tap；
    # 列表项反而能正常按文字点，所以进到设置页之后就交回 p.tap。
    p.start("com.android.calendar", ".AllInOneActivity"); time.sleep(2)
    p.d.shell("input tap 1098 240"); time.sleep(1.5)      # 右上「更多」
    p.d.shell("input tap 769 647"); time.sleep(2)         # 菜单里的「设置」
    for _ in range(3):                                    # 「用户体验计划」在页底，先滚下去
        p.d.shell("input swipe 600 2200 600 500 250"); time.sleep(0.8)
    if maybe("用户体验计划", scrolls=2):
        p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划")
    p.back(3)
