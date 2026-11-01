# 红米 HyperOS 机型脚本：REDMI K80 Ultra（25060RK16C，BP2A.250605.031.A3 / Android 16）
# 路径来源：2026-10-27 本机 explore.py 探路（探路-25060RK16C.tsv，17 个 App / 121 个开关）+ 同品牌 xiaomi-M154FF 适配。
# 机主拍板（2026-10-27）：关「宫格位推送 / 猜你想搜 / 我的视频 / 小说 / 我的网盘 / 自动开启畅读 / 新手帮助 / 秒装」；
#   保留「扫一扫、搜索历史、快捷功能模块、翻译提示、密码保存、自动填充、删除安装包、计算器语音播报」；商店保持标准模式（不切极简）。
# 浏览器「隐私防护」页的广告过滤 / 防跟踪 / 下载防护是保护类（开着才对），本脚本不碰。
# 用法：python tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "BP2A"
MODELS = ["25060RK16C"]
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
    from fast import bounds

    def icon_hit(n):
        desc = (n.get("content-desc") or "").strip().lower()
        text = (n.get("text") or "").strip().lower()
        if desc in ("设置", "settings", "setting") or text in ("设置", "settings", "setting"):
            return True
        # id 只认最后一段里以 setting 开头的词：商店「我的」页的 securitySettingSwitchLayout
        # 也含 setting，但 setting 前面粘着 security，不该算成设置入口。
        rid = (n.get("resource-id") or "").lower().rsplit("/", 1)[-1]
        return rid.startswith("setting") or "_setting" in rid

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
            return gear()
    return False


def tap_any(*names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(n, scrolls) for n in names)


def maybe(name, scrolls=6):
    """可选入口：有就点，没有不报「走丢」。"""
    return p.entry(name, scrolls=scrolls)


def tab_bot(name):
    """按屏幕底部 1/10 区域找标签（主题商店无障碍名带「未选中,」前缀，exact 文本够不着）。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("text") or "")
        if (d == name or d.endswith("," + name) or d.endswith("，" + name)) and p.on_screen(n):
            l, t, r, b = bounds(n)
            if b > p.H * 0.85:
                p.click((l + r) // 2, (t + b) // 2); time.sleep(1.5)
                return True
    return False


@step("系统广告")
def _():
    # 实测：HyperOS 2 的「隐私与安全」页是权限中心，没有「更多安全设置」；改走引擎设置搜索（0.2.4 已修小米搜索框卡顿）
    if p.setting("广告服务"):
        # 「广告跟踪」以限制/防止开头 = 保护类，off() 会把它拨到开（AGENTS 硬规则10）
        p.off(only=["个性化广告推荐", "广告跟踪"], page="系统·广告服务")
        p.back()
        return
    # 搜索不可用时退回菜单路径（全程 maybe 守卫）
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if maybe("隐私与安全") or maybe("隐私保护"):
        if not maybe("更多安全设置"):
            if maybe("安全", scrolls=3) or maybe("保护与隐私", scrolls=3):
                maybe("更多安全设置")
        if maybe("广告服务"):
            p.off(only=["个性化广告推荐", "广告跟踪"], page="系统·广告服务")
            p.back()


@step("应用商店")
def _():
    # 2026-10-27 K80 实测：冷启动常落「福利推广页」→先回首页；「我的」=底部标签，必须 exact（页里有游戏叫「我的奇妙小镇」）；设置是我的页顶部图标
    p.start("com.xiaomi.market")
    time.sleep(2.5)
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0); time.sleep(2)
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("商店底部「我的」标签没找到")
    time.sleep(2)
    if not (gear(toolbar_only=True) or gear() or p.tap("设置", exact=True, scrolls=4)):
        raise RuntimeError("商店设置图标没找到")
    time.sleep(1)
    p.off(only=["秒装"], page="商店·设置")          # 机主同意关秒装（2026-10-27）；删除安装包等功能保留
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关（M154FF Issue #2）；应用更新保留
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新", "删除安装包", "秒装"], page="商店·通知设置"); p.back()
    if maybe("其他功能"):
        if maybe("隐私设置"):
            nested = not any("个性化服务" in t for t, _, _ in p.switches())
            if not nested or maybe("个性化服务"):
                p.off(only=["个性化服务"], page="商店·个性化服务")
                if nested:
                    p.back()
            p.back()
        p.back()
    # 模式切换：机主拍板保持标准模式，本脚本不切极简
    p.back(2)


@step("手机管家")
def _():
    # 探路时 securitymanager 包起不来；照 M154FF 用 securitycenter 直达设置页
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
    # 实测 resolve-activity：K80 的 themestore 直达自己的 ThemeResourceTabActivity，不再走 18 的 thememanager 中转（那会离开前台）
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题商店，跳过"); return
    # 实测：themestore 冷启动重定向到 thememanager 的过渡窗会把引擎前台校验搞崩；直接拉最终页最稳
    p.start("com.android.thememanager", ".ThemeResourceProxyTabActivity")
    if not (tab_bot("我的") or p.tap("我的", exact=True, scrolls=0)):
        print("  · 主题商店没有「我的」标签，跳过"); p.back(3); return
    if not (gear(toolbar_only=True) or gear()):
        print("  · 主题商店设置入口没找到，跳过"); p.back(3); return
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # 只关机主点名的（见文件头注释）；「隐私防护」页的保护类开关不碰
    p.start("com.android.browser")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    if not browser_settings():
        raise RuntimeError("浏览器设置入口未找到；未点击正文中的文字")
    if maybe("隐私和安全"):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全"); p.back()
    for page, only in [("主页设置", ["宫格位推送"]),
                       ("搜索设置", ["猜你想搜"]),                       # 扫一扫/搜索历史/快捷功能保留（机主）
                       ("功能设置", ["我的视频", "小说", "我的网盘"]),
                       ("网页浏览设置", ["畅读"])]:                      # 翻译提示/密码保存/自动填充保留（机主）
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
    # 只动卡片推荐；搜索框、出行助手保留；包本身不挂起（AGENTS 硬规则）
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
    p.back()


@step("天气和日历")
def _():
    # 2026-10-27 K80 实测：这两个 App 的本系统界面没有可见的「用户体验计划/内容推广」；找不到就安静跳过，不算失败
    for pkg in ("com.miui.weather2", "com.android.calendar"):
        p.start(pkg)
        if pkg == "com.miui.weather2" and p.find("城市管理", exact=True, edge_ok="tab"):
            p.tap("城市管理", exact=True, scrolls=0)
        if not (gear(toolbar_only=True) or gear()):
            print(f"  · {pkg} 本版本没有可识别的设置入口，跳过"); p.back(2); continue
        if p.find("用户体验计划", exact=True) and p.tap("用户体验计划", exact=True, scrolls=6):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page=f"{pkg}·用户体验计划"); p.back()
        else:
            print(f"  · {pkg} 没有用户体验计划，跳过")
        p.back(3)
