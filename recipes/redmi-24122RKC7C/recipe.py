# Redmi K80 Pro（24122RKC7C，代号 miro），HyperOS OS3.0.304.0.WOMCNXM / Android 16 / Build BP2A.250605.031.A3。
# 2026-10-29 真机实测：USB 有线，1080×2400、密度 450、ROTATION_0。
# 入口来源：先按同品牌 Redmi K70 脚本（OS3.0.307.0）安全模式跑通 9 段、关 20 项，
#   再按本机入口补两处差异，专用脚本复跑 9 段（0 调整、0 步骤异常）。
# 与 K70 的两处差异：
#   ① 主题商店冷启动（com.miui.themestore）会跳到 com.android.thememanager，引擎的前台校验会停段；
#      直达 com.android.thememanager/.ThemeResourceProxyTabActivity 最稳。
#   ② 浏览器「设置」是顶部右侧的齿轮 ImageView（文字就是「设置」），冷启动偶发被过渡窗拦一次；
#      这里先 force-stop 再直达 BrowserActivity，重试一次，齿轮点不动时用 input tap 兜底。
# 浏览器「小说」「最新资讯」按 K70 的结论不动：小说是功能入口不是广告开关，最新资讯在本机是 disabled。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS3.0.304.0"
MODELS = ["24122RKC7C"]
import time
from entries import THEME_DEAD_ENDS
VERIFIED_SWITCHES = 0


def tap_any(*names, scrolls=6):
    return any(maybe(name, scrolls) for name in names)
def gear_tap(pkg, activity):
    """齿轮用引擎短按点不动时的兜底：同一次读屏里找到齿轮，改用 input tap（80 毫秒短按有的 App 会吞）。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        text = (n.get("text") or "").strip()
        desc = (n.get("content-desc") or "").strip()
        if text == "设置" or desc == "设置":
            l, t, r, b = bounds(n)
            if not p.on_screen(n):
                continue
            p.d.shell(f"input tap {(l + r) // 2} {(t + b) // 2}")
            time.sleep(1.2)
            return p.focus().split("/", 1)[0] == pkg and activity in p.focus()
    return False


def browser_start():
    """冷启动偶发被启动过渡窗判断成「离开前台」：先强停再直达 BrowserActivity，重试一次。"""
    for attempt in range(2):
        try:
            p.start("com.android.browser", ".BrowserActivity")
            return True
        except SkipStep:
            raise                 # App 本机没装：放行，不走下面那句按文案判的重试分支（#908）
        except RuntimeError as e:
            if attempt or "离开前台" not in str(e):
                raise
            p.d.shell("am force-stop com.android.browser")
            time.sleep(1.5)
    return False


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("系统广告")
def _():
    system_ads_security()


@step("应用商店")
def _():
    store()


@step("手机管家")
def _():
    security_center()


@step("下载管理")
def _():
    downloads()


@step("主题")
def _():
    # 主题商店冷启动会跳到 thememanager，引擎的前台校验会停段；直达代理标签页最稳。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    # 导航失败不能与「本页没有目标开关」同形：三步都校验，报错带页面现场（#906）。
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("未找到主题「我的」；" + p.page_evidence())
    if not gear():
        raise RuntimeError("主题设置入口没找到；" + p.page_evidence())
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
    require(browser_start(), "浏览器没有启动")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    # 「我的」在本机是顶部标签：主页 / 视频 / AI搜索 / 免费小说 / 我的
    require(p.tap("我的", exact=True, scrolls=0), "未找到浏览器「我的」")
    if not gear(toolbar_only=True):
        require(gear_tap("com.android.browser", "BrowserSettingsActivity"),
                "浏览器设置齿轮没找到")
    else:
        require(p.focus().split("/", 1)[0] == "com.android.browser"
                and "BrowserSettingsActivity" in p.focus(), "浏览器设置页没有打开")
    if maybe("主页设置"):
        p.off(only=["宫格位推送"], page="浏览器·主页设置")
        p.back()
    if maybe("搜索设置"):
        p.off(only=["显示猜你想搜模块"], page="浏览器·搜索设置")
        p.back()
    p.back(2)


@step("全局搜索")
def _():
    global_search()


@step("负一屏")
def _():
    negative_screen()


@step("天气和日历")
def _():
    weather_calendar_tap()


print(f"\n系统广告段回读确认 {VERIFIED_SWITCHES} 项；步骤异常 {len(FAILED_STEPS)} 个", flush=True)
