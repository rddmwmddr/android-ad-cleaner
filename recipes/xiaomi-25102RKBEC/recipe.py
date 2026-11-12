# 小米 HyperOS 4 机型脚本：REDMI K90 Pro Max（25102RKBEC / myron）
# 路径来源：2026-10-27 实机实测（OS4.0.2.0.XPMCNXM / Android 17）。
#
# 与 xiaomi-M154FF 的关键差异（照 M154FF 跑会跳过「系统广告」这一步）：
#   1. 设置首页要往下滑一段才看得到「隐私与安全」；
#   2. 点「隐私与安全」打开的是安全中心的 PrivacySafetyActivity，不是系统设置的子页。
#      它只有「隐私 / 安全」两个分栏，默认停在「隐私」——那页全是权限记录，没有安全设置；
#   3. 切到「安全」分栏后内容很长，「更多安全设置」在整页最末尾，要滚到底。
#   4. 「主题」这段要求先挂起 com.miui.systemAdSolution：这台打开主题商店的瞬间，
#      广告组件会弹出开屏窗抢走焦点，脚本按约定判定「离开前台」整段跳过。
#      挂起命令（可还原）：python3 tool/run.py -s 序列号 suspend com.miui.systemAdSolution
#
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS4.0"
MODELS = ["25102RKBEC"]
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
            return gear()
    return False


def tab(name):
    """点顶部分栏标签（隐私 / 安全）。
    页面里同名文字常有两个（分栏标签 + 下面分组标题），取屏幕最上面那个。"""
    cand = []
    for text, (l, t, r, b), node in p.texts():
        if text == name and t < p.H * 0.40:
            cand.append((t, (l + r) // 2, (t + b) // 2))
    if not cand:
        return False
    cand.sort()
    p.click(cand[0][1], cand[0][2]); time.sleep(1.2)
    return True


@step("系统广告")
def _():
    # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    # 这台设置首页一屏放不下，「隐私与安全」在第二屏
    if not maybe("隐私与安全", scrolls=8):
        return
    # 打开的是安全中心「隐私与安全」页（PrivacySafetyActivity），默认停在「隐私」分栏
    if p.find("隐私与安全") and not p.find("更多安全设置"):
        tab("安全")
    # 「安全」分栏很长，「更多安全设置」在整页最末尾
    if not maybe("更多安全设置", scrolls=10):
        return
    if maybe("广告服务", scrolls=4):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    gear()
    if tap_any("隐私设置", "隐私"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe("模式切换"):
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连「点赞消息」「评论消息」一起关（Issue #2）
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)


@step("手机管家")
def _():
    # 这台（13.x）的设置页有「隐私设置」，但它在整页最末尾（各功能模块设置之下）。
    # 直接 tap 翻页找不到（贴底的行会被 find 的 0.92H 判据滤掉），先手动往下翻再点。
    # 里面的「个性化推荐」默认是开的——这是 M154FF 那份脚本在这台上漏掉的一项。
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    p.top()
    for _ in range(8):
        if p.find("隐私设置", exact=True, edge_ok=True):
            break
        p.scroll(0.5)
    if p.tap("隐私设置", exact=True, scrolls=0):
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
    # 这台：直接起 thememanager 的 ThemeResourceProxyTabActivity（沿用 #730 的做法）。
    # 若系统广告组件未挂起，开屏窗会抢焦点导致本段被跳过（见文件头说明）。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    # 导航失败以前与「本页没有目标开关」同形：进「我的」、进设置页、点名开关三步都校验，
    # 0 个开关按失败报并带页面现场（#906）。
    if not p.go("我的", "设置"):
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
    # 首页「默认 / 探索版 / 自定义主页」不改：自定义主页要填网址，按机主喜好
    # 紧跟「主题」段连跑时会失败：退出主题商店的那一下会跟浏览器的冷启动抢焦点，
    # 脚本判定「离开前台」整段停（单独跑这段从来不出问题）。先回桌面、等稳了再拉。
    p.d.shell("input keyevent KEYCODE_HOME"); time.sleep(2)
    p.start("com.android.browser")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    if not browser_settings():
        raise RuntimeError("浏览器设置入口未找到；未点击正文中的文字")
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


@step("天气和日历")
def _():
    for pkg in ("com.miui.weather2", "com.android.calendar"):
        p.start(pkg)
        if pkg == "com.miui.weather2" and p.find("城市管理", exact=True, edge_ok="tab"):
            p.tap("城市管理", exact=True, scrolls=0)
        if not gear():
            print("  · 本版本没有可识别的设置菜单，跳过"); continue
        if maybe("用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page=f"{pkg}·用户体验计划"); p.back()
        p.back(3)
