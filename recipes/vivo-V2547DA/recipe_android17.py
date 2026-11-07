# vivo X300 Ultra（V2547DA，卫星通信版）Android 17 变体：同型号的 OriginOS 6 路径在 recipe.py，
# 系统版本对上 17.1.10.2 时由 run.recipe_for 选这份。
# 路径来源：Issue #220 报告者真机实测（V2547DA，PD2547D_A_17.1.10.2.W10，商店 V10.5.20.0，2026-10-28）。
# 2026-11-03 商店段改用 Phone.tab()、gear() 改用引擎 icon_hit（#530）。
# 2026-11-07 整段在 V2547DA 真机复测；系统广告、全局搜索、阅图锁屏改为直达，打不开再走菜单（#667）。
# 2026-11-07 gear() 补落地校验：点不动的齿轮继续找、最后回退按文字点（#575），未复测。
# 与 recipe.py 的差别只在应用商店——Android 17 的「我的」页没有能读到的齿轮入口，
# 且「个性化推荐」页两个开关的 content-desc 只有「开启，开关」，读不出标题。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2547D_A_17.1.10.2"
MODELS = ["V2547DA"]
import time

import adb_link
from wait import until

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


def maybe(name, scrolls=6):
    """有就点，没有不算「走丢」，后面的步骤照常找。"""
    return p.entry(name, scrolls=scrolls)


def gear():
    """vivo App 的设置多是右上角齿轮图标，没有文字。

    判据用引擎的 icon_hit：旧实现按 content-desc / resource-id 子串匹配，id 里带 setting 的
    其它入口（商店的 securitySettingSwitchLayout 之类）会被当成齿轮先点掉（#530）。
    点完要认出设置页才算命中：点不动的图标页面没换，接着试下一个候选；点进了别的页先退回来
    再试；都点不进去时回退到按文字点，回退也没进设置页才算失败（#575）。"""
    from fast import bounds, icon_hit

    def landed(focus0):
        if p.focus() == focus0:
            return False                    # 点击被吞：页面没换，不能当成进了设置页
        if p.in_settings_page():
            return True
        # Activity 名不含 Setting 的 App：只认顶上标题带那一处「设置」——齿轮自己也读作「设置」
        at = p.find("设置", exact=True)
        return bool(at) and at[1] < p.H * 0.25

    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        icon = "ImageView" in n.get("class", "") and r - l < p.W * 0.25 and b - t < p.H * 0.15
        if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n):
            focus0 = p.focus()
            p.click((l + r) // 2, (t + b) // 2); p.await_page(1.5)
            if landed(focus0):
                return True
            if p.focus() != focus0:         # 点进了别的页：退回来，别用旧树的坐标在新页上接着点
                p.back(); time.sleep(0.6)
    focus0 = p.focus()
    return p.tap("设置", exact=True, scrolls=0) and landed(focus0)


def off_unnamed(page):
    """这一页上没有标题的开关：按位置一个个关，点一次回读一次。
    商店「个性化推荐」页的两个开关 content-desc 只有「开启，开关」（#220）：p.off() 按标题匹配，
    空标题的行整行跳过——既关不到，也不会报「关不掉」，所以只有这一页自己点。
    灰的行不点（#333）；点完读不到开关（被确认框挡住）不算关掉（#486 的教训：读空不等于成功）。"""
    from row import disabled_at
    root = p.tree()
    targets = [xy for title, on, xy in p.switches(root) if not title and on]
    if not targets:
        print(f"  · {page}：没有开着且无标题的开关")
        return 0
    done = 0
    for i, xy in enumerate(targets, 1):
        if disabled_at(root, xy):
            print(f"  · 被上级开关禁用（开关是灰的），未改动 无标题开关 {i}")
            continue
        was = sum(1 for title, on, _ in p.switches() if not title and on)
        p.click(*xy)
        p.confirm()
        time.sleep(0.3)
        rows = p.switches()
        if not rows or sum(1 for title, on, _ in rows if not title and on) >= was:
            print(f"  ✗ 关不掉 无标题开关 {i}")
            continue
        print(f"  关 无标题开关 {i}")
        p.changed.append((page, f"无标题开关 {i}"))
        done += 1
    print(f"  · {page}：核对 {len(targets)} 项，调整 {done} 项")
    return done


def opened(start):
    """试一条直达页面：到了返回真。别的系统版本可能没有这一页，返回假走菜单；
    断线照常上抛——跑到一半掉线时 Phone 只置 lost、抛的是普通 RuntimeError（#293）。"""
    try:
        start()
        return True
    except adb_link.DeviceLost:
        raise
    except RuntimeError as e:
        if p.lost:
            raise
        print(f"  · 直达不通（{e}），走菜单")
        return False


def settings_home():
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)


@step("系统广告")
def _():
    only = ["个性化广告", "个性化推荐", "智能推荐服务"]
    if opened(lambda: p.start("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo", expect="智能推荐服务", budget=2)):
        p.off(only=only, page="系统·广告与隐私")
        return
    settings_home()
    if maybe("安全") or maybe("安全与隐私"):
        if maybe("更多安全设置") and maybe("广告与隐私"):
            p.off(only=only, page="系统·广告与隐私")


@step("全局搜索")
def _():
    if not opened(lambda: p.start("com.vivo.globalsearch", ".view.SearchSettingsActivity", expect="首页展示内容", budget=2)):
        settings_home()
        if not (maybe("系统管理与升级") and maybe("全局搜索")):
            return
    if maybe("首页展示内容"):
        p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
    # Android 17 上没有「推荐热搜榜单」这个入口（#220）。这一页只有几行，看一眼就够，不滚也不等
    if p.find("推荐热搜榜单", exact=True) and maybe("推荐热搜榜单", scrolls=0):
        p.off(only=["热门搜索"], page="全局搜索·热搜榜单"); p.back()
    if maybe("个性化内容"):
        p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()   # 历史记录、应用建议保留


@step("阅图锁屏")
def _():
    only = ["阅图锁屏", "锁屏横滑进入阅图"]
    if opened(lambda: p.start("com.vivo.magazine", ".ui.MagazineSettings", expect="锁屏横滑进入阅图", budget=2)):
        p.off(only=only, page="阅图锁屏")
        return
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置") and maybe("阅图锁屏"):
        p.off(only=only, page="阅图锁屏")


@step("应用商店")
def _():
    # 「我的」页没有能读到的齿轮入口，设置页只能按 Activity 直达（#220）。
    # Activity 不存在时 Phone.start 会直接抛出来，接住再退回「我的 → 设置」，别整段空跑。
    try:
        p.start("com.bbk.appstore", ".ui.menu.AppstoreSettingsActivity")
        reached = "AppstoreSettingsActivity" in p.focus()
    except adb_link.DeviceLost:
        raise                     # DeviceLost 也是 RuntimeError：断线不能当成「这一页打不开」再空跑一次
    except RuntimeError as e:
        print(f"  · 直达商店设置页失败（{e}），改走「我的 → 设置」")
        reached = False
    if not reached:
        p.start("com.bbk.appstore", expect=("我的",))
        # 底栏标签读作「我的, 2个应用待更新,第5个, 共5个」，精确匹配读不到（#530）
        if not p.tab("我的"):
            raise RuntimeError("商店底部「我的」标签没找到")
        time.sleep(0.8)
        gear()
    if maybe("关于"):
        if maybe("个性化推荐"):
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐")
            p.top()                     # p.off 会往下翻；这一页的开关在上面时别错过
            off_unnamed("商店·个性化推荐")
            p.back(); time.sleep(0.5)
        if maybe("服务管理"):
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back()
        p.back()
    p.back(2)


def browser_settings(tries=2):
    """右上「菜单 → 设置」，点完要认出设置页（#753）。

    冷启动首页没有底部「我的」，入口是右上菜单。菜单浮层右上角有一个 desc 读作「返回」的 ✕
    （id 里带 cancel），等入口时按弹窗去关会把它点掉，刚打开的菜单就收起来了，「设置」再也找不到。
    所以这里只等那一行画出来、直接点，不在等待里关弹窗；点完没进设置页就退回、重开菜单再试一次。
    别的 vivo 型号可能没有这个按钮，最多等 3 秒就放弃本段。"""
    def landed():
        if p.in_settings_page():
            return True
        at = p.find("设置", exact=True)         # Activity 名不含 Setting 的 App：只认顶上那处「设置」标题
        return bool(at) and at[1] < p.H * 0.25

    for _ in range(tries):
        if not p.d(resourceId="com.vivo.browser:id/menu_btn").click_exists(timeout=3):
            return False                        # 本机没有这个按钮：交给调用方跳过本段
        p.await_page(1.6)                       # 菜单是弹层，画出来的那一帧才有「设置」
        xy = until(lambda: p.find("设置", exact=True, edge_ok="tab"), timeout=3.0, poll=0.3,
                   now=time.time, sleep=time.sleep)
        if xy:
            before = p.sig()
            p.click(*xy)
            if p.settle(before, 1.5):
                p.await_page(1.5)               # Activity 换了、内容可能还在画：等这一页画完再认落点
                if landed():
                    return True
        p.back()                                # 收起浮层 / 退出点错的页，下一轮重开菜单
    raise RuntimeError(f"浏览器设置页没有打开；停在 {p.focus()}")


@step("浏览器")
def _():
    p.start("com.vivo.browser")
    if not browser_settings():
        print("  ✗ 本机浏览器没有右上菜单按钮，跳过本段"); return
    print(f"  · 浏览器设置页 {p.focus()}")
    if maybe("首页设置"):
        maybe("极简首页", scrolls=0)
        p.off(only=["首页上滑展示资讯"], page="浏览器·首页设置"); p.back()
    p.top()
    if maybe("网页浏览设置"):
        p.off(only=["网页下载相关推荐"], page="浏览器·网页浏览"); p.back()
    p.top()
    if maybe("更多设置"):
        p.off(only=["WiFi连接跳转新闻资讯", "WiFi 连接跳转新闻资讯", "跳转新闻资讯",
                    "下载管理页展示热门应用", "下载管理页展示下载热榜"], page="浏览器·更多设置"); p.back()
    p.top()
    if maybe("隐私权限设置"):
        p.off(only=["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], page="浏览器·隐私"); p.back()
    p.back(2)


@step("i管家")
def _():
    p.d.shell("am start -f 0x10008000 -n com.iqoo.secure/.MainSettings")
    time.sleep(1.0)
    if maybe("关于") and maybe("个性化设置"):
        p.off(only=["应用个性化推荐", "清理个性化推荐"], page="i管家·个性化设置")
    p.back(3)


@step("天气")
def _():
    p.d.shell("am start -f 0x10008000 -n com.vivo.weather/.WeatherSettings")
    time.sleep(1.0)
    p.off(only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")   # 只关「天气相关热点资讯通知」
    p.back(1)
