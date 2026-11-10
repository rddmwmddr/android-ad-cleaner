# 小米 HyperOS / Android 16 机型脚本：Xiaomi MIX Flip 2（2505APX7BC）
# 路径来源：2026-11-05 社区实测，HyperOS / Android 16，底包 BP2A.250605.031.A3，全程合盖用外屏（1224×2912）。
# 同底包的 xiaomi-24129PN74C 在这台上跑通了六个段（系统广告、应用商店、手机管家、下载管理、
# 全局搜索、负一屏），主题 / 浏览器 / 天气 / 日历的入口不同，本脚本按这台实测重写：
#  · 主题：「设置」在「我的」页是文字按钮，不是图标；入口是 ThemePreferenceActivity。
#  · 浏览器：底栏是 主页/视频/AI搜索/免费小说/我的，没有「菜单」；设置入口在「我的」页。
#  · 天气：「更多设置」弹出 PopupWindow（前台读成 PopupWindow:<id>，不能按包名判断），
#    菜单里点「设置」进 ActivitySet。这一版没有「用户体验计划」页。
#  · 日历：设置是无文字图标，直达 CalendarActionbarSettingsActivity。
# 这台机的底栏标签在第 5 个位置（y≈94% 屏高），用 p.tab() 点；p.tap() 会先命中内容区同名文字。
# 本仓库没有这台机器，未在真机上复跑。
#
# BUILD 置空：只录到 Android 16 的底包，没记到 ROM 版本号。底包跨机型共享、不能进 BUILD（#942）；
# 没标录制版本的脚本不参与同版本挑选，选脚本只按型号，不受此影响。
#
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = ""
MODELS = ["2505APX7BC"]
import time
from entries import THEME_DEAD_ENDS
from wait import until


def gear(toolbar_only=False):
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
    重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（#305 / #374）。
    点击后要认出设置页：点开的是弹窗或别的页就退回来（#331 / #407）。"""
    from fast import bounds, icon_hit

    def open_settings():
        for n in p.tree().iter("node"):
            l, t, r, b = bounds(n)
            icon = "ImageView" in n.get("class", "") and r - l < p.W * 0.25 and b - t < p.H * 0.15
            if (icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n)
                    and (not toolbar_only or b < p.H * 0.23)):
                p.click((l + r) // 2, (t + b) // 2)
                time.sleep(1)
                return True
        # 主题商店的「设置」是「我的」页上的文字按钮，不在这条图标分支里
        if not toolbar_only and p.find("设置", exact=True, edge_ok="tab"):
            return p.tap("设置", exact=True, scrolls=0)
        # 有的版本把齿轮藏在右上「更多」菜单里
        for n in p.tree().iter("node"):
            key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
            l, t, r, b = bounds(n)
            if (any(k in key.lower() for k in ("更多", "more", "menu"))
                    and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22):
                p.click((l + r) // 2, (t + b) // 2)
                time.sleep(0.5)
                if p.tap("设置", exact=True, scrolls=0):
                    return True
                break
        return False

    before = p.focus()
    if not open_settings():
        return False
    if p.in_settings_page():
        return True
    if p.focus() != before:
        p.back()          # 点开的是弹窗或别的页：关掉，别留给下一段
    return False


def popup_row(text, timeout=3.0, below=0.0):
    """浮层里文字正好是 text 的那一行；below 是它必须落在屏高多少比例以下。
    天气的「更多设置」浮层从右上锚点往下展开，位置不固定在屏底，所以默认不设下限。
    刚打开的浮层里等入口不要用 scrolls=0 的 p.tap()（它等待期间会 dismiss 掉浮层，docs/04）。"""
    def row():
        for t, (l, top, r, b), _n in p.texts():
            if t == text and top > p.H * below:
                return (l + r) // 2, (top + b) // 2
        return None
    return until(row, timeout=timeout, poll=0.3, now=time.time, sleep=time.sleep)


def browser_settings():
    """底部「我的」→ 设置。底栏没有「我的」、或那一页认不出设置页时返回 False。"""
    if not p.tab("我的"):
        return False
    time.sleep(1)
    return gear()


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("系统广告")
def _():
    # 同底包的 24129PN74C 走设置搜索「广告服务」，这台实测可用；搜不到时用深链兜底。
    if not p.setting("广告服务"):
        p.d.shell("am start -f 0x10008000 -n com.android.settings/.ad.AdServiceSettings")
        time.sleep(1.5)
    # 两条路都收敛到同一个判据：页面上要有这个开关，否则本段 0 项却算成功
    require(p.expect_page("个性化广告推荐", timeout=3),
            f"广告服务页没有打开；停在 {p.focus()}")
    p.off(only=["个性化广告推荐"], page="系统·广告服务")
    p.back()


@step("应用商店")
def _():
    # 冷启动可能落「福利推广页」→ 先回首页。「我的」用 p.tab()：底部带过滤把内容区同名文字挡在外面（#386）。
    p.start("com.xiaomi.market")
    time.sleep(2.5)
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0)
        time.sleep(2)
    require(p.tab("我的"), "商店底部「我的」标签没找到")
    time.sleep(1.5)
    require(p.tap("设置", exact=True, scrolls=4), "商店设置图标没找到")
    time.sleep(1)
    if maybe("隐私设置"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务", "个性化推荐"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞/评论消息一起关。
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置")
        p.back()
    p.back(2)


@step("手机管家")
def _():
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="管家·隐私")
        p.back()
    if maybe("垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理")
        p.back()
    p.back(2)


@step("下载管理")
def _():
    p.start("com.android.providers.downloads.ui")
    time.sleep(1.5)
    require(p.tap("更多", exact=True, scrolls=0), "下载管理「更多」按钮没找到")
    time.sleep(1.0)
    require(p.tap("设置", exact=True, scrolls=0), "下载管理弹窗里的「设置」没找到")
    time.sleep(1.2)
    if maybe("信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    # 直达主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；经主题商店冷启动
    # 还要过一道重定向过渡窗，前台校验容易误判（#906）。落点被系统转走时仍按跳过收尾。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    time.sleep(2)
    if not p.tab("我的"):
        raise RuntimeError("主题底部「我的」标签没找到；" + p.page_evidence())
    time.sleep(1)
    # 「设置」在这台是「我的」页上的文字按钮（精确匹配不会命中「设置壁纸」），图标形态也认
    if not p.tap("设置", exact=True, scrolls=0):
        raise RuntimeError("主题「我的」页没有「设置」；" + p.page_evidence())
    # 落点判据用页面上的项：比只看 Activity 名更严，这一页没画出这些项就不算进去
    if not (p.expect_page("每次联网时通知", timeout=3) or p.expect_page("自动更新", timeout=1)):
        raise RuntimeError("主题设置页没有打开；" + p.page_evidence())
    p.await_page()                              # 齿轮点完这一页可能还没画完
    before = {}
    for _ in range(2):                          # 行也可能在首屏之下，off() 自己会翻页找
        before.update({title: on for title, on, _ in p.switches()})
        if not p.scroll_more():
            break
    p.top(2)
    require_switches(before, ["每次联网时通知"], "主题·设置", contains=True)
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私")
        p.back()
    p.back(2)


@step("浏览器")
def _():
    # 底栏没有「菜单」：入口是底部「我的」→ 设置（BrowserSettingsActivity）。首页布局按机主喜好，不改。
    p.start("com.android.browser")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    time.sleep(2)
    require(browser_settings(), f"浏览器设置入口没找到；停在 {p.focus()}")
    # 票面路径是两层：「隐私」→「隐私和安全」；有版本把这一页平铺在设置页首层。
    if maybe("隐私", scrolls=12):
        if maybe("隐私和安全"):
            p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全")
            p.back()          # 回到「隐私」页
        p.back()              # 回到设置页，后面三个入口在这一层
    elif maybe("隐私和安全", scrolls=2):
        p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·隐私和安全")
        p.back()
    if maybe("主页设置"):
        p.off(only=["宫格位推送"], page="浏览器·主页设置")
        p.back()
    if maybe("搜索设置"):
        # 扫一扫、AI搜索、搜索历史、搜索引擎切换栏是搜索功能项，保留
        p.off(only=["显示猜你想搜模块"], keep=["扫一扫", "AI搜索", "搜索历史", "搜索引擎切换栏"],
              page="浏览器·搜索设置")
        p.back()
    if maybe("功能设置"):
        p.off(only=["小说"], keep=["我的网盘"], page="浏览器·功能设置")
        p.back()
    p.back(2)


@step("全局搜索")
def _():
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if maybe("首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if maybe("应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐")
            p.back()
        if maybe("热搜榜单"):
            subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
            if p.switches():
                p.off(only=HOT, page="搜索·热搜榜单")
            if subs:
                p.top()
                for x in subs:
                    if maybe(x):
                        p.off(only=HOT, page=f"搜索·热榜·{x}")
                        p.back()
            p.back()
        p.back()
    p.back(2)


@step("负一屏")
def _():
    # 只动卡片推荐；搜索框、出行助手保留；包本身不挂起（AGENTS 硬规则）。
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私")
        p.back()
    p.back()


@step("天气和日历")
def _():
    # 天气：设置藏在「更多设置」弹出的菜单里；这版页面只有提醒与单位类开关，没有「用户体验计划」。
    p.start("com.miui.weather2")
    time.sleep(2)
    require(p.tap("更多设置", exact=True, scrolls=2), "天气「更多设置」没找到")
    xy = popup_row("设置")
    require(xy, f"天气「更多设置」菜单里没有「设置」；停在 {p.focus()}")
    before = p.sig()
    p.click(*xy)
    # 落点核对：没进设置页就报失败，否则会把「没点开」说成「本版没有这类开关」
    require(p.settle(before, 1.5)
            and ("ActivitySet" in p.focus() or p.find("温度单位", exact=True)
                 or p.find("早晚天气提醒", exact=True)),
            f"天气设置页没有打开；停在 {p.focus()}")
    if maybe("用户体验计划"):
        p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page="天气·用户体验计划")
        p.back()
    else:
        print("  · 天气：本版无此类开关（只有提醒与单位设置），跳过")
    p.back(2)
    # 日历：设置是无文字图标，直达 Activity；这版 7 项全是功能开关。
    p.d.shell("am start -f 0x10008000 -n com.android.calendar/.settings.CalendarActionbarSettingsActivity")
    time.sleep(1.5)
    require("CalendarActionbarSettingsActivity" in p.focus(), f"日历设置页没有打开；停在 {p.focus()}")
    if maybe("用户体验计划"):
        p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划")
        p.back()
    else:
        print("  · 日历：本版无此类开关（7 项全是功能开关），跳过")
    p.back()
