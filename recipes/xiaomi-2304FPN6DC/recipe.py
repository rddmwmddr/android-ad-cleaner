# 小米 HyperOS 3 机型脚本：Xiaomi 13 Ultra（2304FPN6DC）、Xiaomi 14 Pro（23116PN5BC）
# 路径来源：2026-10-27 实机录制（OS3.0.308.0.WMACNXM / Android 16）。
# 14 Pro 2026-10-29 社区实测（OS3.0.308.0.WNBCNXM / Android 16，Issue #317）：九段跑通、每步回读，
# 只有浏览器「搜索设置」一页没命中目标开关。
# 与 18 系列（OS4）的差异：系统广告的「更多安全设置」在「隐私与安全 → 安全」页里；
# 浏览器个性化推荐是独立 Activity；手机管家没有独立「隐私设置」入口项，需滚到页面底部。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "OS3.0.308"
MODELS = ["2304FPN6DC", "23116PN5BC"]
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
    # 13 Ultra（OS3.0.308）：隐私与安全默认停在「隐私」，要切到顶部的「安全」页
    for _ in range(3):
        if p.find("设备安全") or p.find("人身安全"):
            break
        p.tap("安全", exact=True, scrolls=0)
        time.sleep(0.5)
    if maybe("更多安全设置"):
        if maybe("广告服务"):
            p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    p.start("com.xiaomi.market")
    if not p.tab("我的"):
        raise RuntimeError("应用商店底部「我的」未找到")
    if not maybe("设置", scrolls=10):
        raise RuntimeError("应用商店设置入口未找到")
    if maybe("通知设置"):
        # 只关「新手帮助」。不碰「推送消息」「应用更新通知」（Issue #2）
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    if tap_any("隐私设置", "隐私"):
        # 4.129.s.00 之后「个性化服务」是子页入口，开关在下一层；老版本开关就在本页
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe("个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    p.back(2)


@step("手机管家")
def _():
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    # 12.8.7：垃圾清理页里直接有「内容推荐设置 → 推荐内容」
    if maybe("垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
    # 「隐私设置」在设置页最底部，排在「关于」前面
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
    p.back(2)


@step("下载管理")
def _():
    p.start("com.android.providers.downloads.ui")   # p.start 会顺手点掉「以后再说」更新弹窗
    if not gear():
        raise RuntimeError("下载管理设置入口未找到")
    if maybe("信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    # HyperOS 3 的 13 Ultra 只有 thememanager，没有 themestore
    if "package:" in p.d.shell("pm path com.miui.themestore").output:
        p.start("com.miui.themestore", foreground="com.android.thememanager")
    else:
        p.start("com.android.thememanager")
    if not p.tab("我的"):
        raise RuntimeError("主题底部「我的」未找到")
    gear()
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe("隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # 个性化推荐在独立 Activity，直接拉起最稳；老版本没有这个页面时整段快速跳过
    p.start("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity")
    p.off(only=["个性化内容推荐", "个性化广告推荐"], page="浏览器·个性化推荐")
    p.back(2)
    p.start("com.android.browser", ".BrowserSettingsActivity")
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]), ("功能设置", ["小说"])]:
        if maybe(page):
            p.off(only=only, page=f"浏览器·{page}"); p.back()
    p.back(2)


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选", "千问"]


@step("全局搜索")
def _():
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if maybe("首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if maybe("应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示应用推荐"], page="搜索·应用推荐"); p.back()
        if maybe("热搜榜单"):
            # 「我的热榜」既有「推荐」总开关，又分热搜 / 生活 / 娱乐 / 话题子页
            subs = [x for x in ("热搜", "生活", "娱乐", "话题") if p.find(x, exact=True)]
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
    # 天气 18.x：右上「更多设置 → 设置 → 用户体验计划」；日历 18.x 设置里已没有用户体验计划
    p.start("com.miui.weather2")
    if maybe("更多设置", scrolls=3):
        maybe("设置", scrolls=0)
    if maybe("用户体验计划"):
        p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page="天气·用户体验计划"); p.back()
    p.back(3)
    p.start("com.android.calendar")
    if maybe("设置", scrolls=0):
        maybe("设置", scrolls=0)                  # 右上按钮先弹菜单，再点菜单里的「设置」
    if maybe("用户体验计划"):
        p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划"); p.back()
    p.back(3)
