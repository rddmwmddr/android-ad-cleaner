# 小米 / Redmi HyperOS 3 机型脚本：Redmi Note 14 Pro（24090RA29C）
# 路径来源：2026-10-26 真机实测，HyperOS OS3.0.309.0.WOOCNXM（Android 16，BP2A.250605.031.A3）。
# 与 M154FF（OS4.0）的差异：系统广告的「更多安全设置」在「安全」标签页下，不在隐私页首屏；
# 主题、浏览器的设置是无文字齿轮（content-desc=设置），首页「我的」是底部标签。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS3.0.309.0"
MODELS = ["24090RA29C"]
import time
from entries import THEME_DEAD_ENDS


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
    store_mode()


@step("手机管家")
def _():
    security_center()


@step("下载管理")
def _():
    downloads()


@step("主题")
def _():
    # 直接起主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；前台就是它自己，
    # 交给 start() 等落点。经主题商店冷启动的过渡窗会误判，也可能续在上次留下的子页上（#906）。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    time.sleep(3)                               # 首页要几秒才画完，早读会找不到底部标签
    p.dismiss()
    # 底部「我的」标签在 65% 屏高以下，p.tab() 只认最下面那道带，这里按位置找
    xy = next((((l + r) // 2, (t + b) // 2) for text, (l, t, r, b), node in p.texts()
               if text == "我的" and t >= p.H * 0.65), None)
    if xy is None:
        raise RuntimeError("主题「我的」标签没找到；" + p.page_evidence())
    tap_sig = p.sig()
    p.click(*xy)
    p.settle(tap_sig, 1.5)
    p.dismiss()
    # 导航失败以前与「本页没有目标开关」同形：进设置页、点名开关也校验，带页面现场（#906）。
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
    global_search()


@step("负一屏")
def _():
    negative_screen()
