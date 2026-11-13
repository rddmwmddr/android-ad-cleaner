# 小米 HyperOS 4 机型脚本：Xiaomi 17 Ultra（2512BPNDAC，标准版，非徕卡版）；2026-10-28 真机实测：HyperOS OS4.0.5.0.XPACNXM / Android 17（SDK 37）/ 系统底包 CP2A.260605.016
from recipe_kit import step
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
from entries import THEME_DEAD_ENDS

# 这台的齿轮是纯图标，另有正文「设置」兜底；浏览器两个按钮都按 resource-id 点。
GEAR_STYLE = "text"
MENU_STYLE = "ids"


@step("系统广告")
def _():
    # 两条设置搜索直达。不走「隐私与安全 → 安全 → 更多安全设置」：这台的「隐私与安全」是安全中心
    # PrivacySafetyActivity，默认停在「隐私」分栏，「安全」标签用读屏点经常点不动。
    # 两个总闸在两页上，互不依赖：一条搜不到不能连带把另一条也放弃，收尾再一起报失败。
    missed = []
    if p.setting("广告服务"):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")
    else:
        missed.append("广告服务")
    if p.setting("系统广告"):
        # 「在系统工具应用中会出现少量广告推荐」——天气、日历、音乐等系统工具里广告的总闸。
        p.off(only=["系统工具广告"], page="系统·系统广告")
    else:
        missed.append("系统广告")
    if missed:
        raise RuntimeError("没搜到" + "、".join(f"「{name}」" for name in missed))


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
    security_center()


@step("下载管理")
def _():
    downloads()


@step("主题")
def _():
    # 直达主题管理包的代理页（沿用 #730 的做法：它没有 LAUNCHER，monkey 拉不起来）；经主题商店冷启动
    # 还要过一道重定向过渡窗，前台校验容易误判（#906）。落点被系统转走时仍按跳过收尾。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    # 导航失败以前与「本页没有目标开关」同形：进「我的」、进设置页、点名开关三步都校验，
    # 0 个开关按失败报并带页面现场（#906）。
    if not (bottom_tab("我的") or p.go("我的", "设置")):
        raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
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
    p.start("com.android.browser")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    # 工具栏最右那个「设置」按钮点进去是「页面布局」子页（这版特有）。
    # 正确路径：底部「菜单」→ 弹窗右上角「设置」，用 resource-id 定位。
    menu_settings()
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
    global_search()


@step("负一屏")
def _():
    negative_screen()


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

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import maybe, p, require_switches, start_or_skip
    from recipe_nav import bottom_tab, gear, menu_settings, tap_low
    from recipe_steps import downloads, global_search, negative_screen, security_center
