# vivo X300 Ultra（V2547DA，卫星通信版）Android 17 变体：同型号的 OriginOS 6 路径在 recipe.py，
# 系统版本对上 17.1.10.2 时由 run.recipe_for 选这份。
# 路径来源：Issue #220 报告者真机实测（V2547DA，PD2547D_A_17.1.10.2.W10，商店 V10.5.20.0，2026-10-28）。
# 本仓库没有这台机器：入口按报告者给出的 Activity 与读屏描述写，未整段复测。
# 与 recipe.py 的差别只在应用商店——Android 17 的「我的」页没有能读到的齿轮入口，
# 且「个性化推荐」页两个开关的 content-desc 只有「开启，开关」，读不出标题。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2547D_A_17.1.10.2"
MODELS = ["V2547DA"]
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
    """有就点，没有不算「走丢」，后面的步骤照常找。"""
    return p.entry(name, scrolls=scrolls)


def gear():
    """vivo App 的设置多是右上角齿轮图标，没有文字。"""
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("resource-id") or "")
        if any(k in d.lower() for k in ("设置", "setting")) and n.get("clickable") == "true" and p.on_screen(n):
            from fast import bounds
            l, t, r, b = bounds(n); p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    return p.tap("设置", exact=True, scrolls=0)


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


def settings_home():
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)


@step("系统广告")
def _():
    settings_home()
    if maybe("安全") or maybe("安全与隐私"):
        if maybe("更多安全设置") and maybe("广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")


@step("全局搜索")
def _():
    settings_home()
    if maybe("系统管理与升级") and maybe("全局搜索"):
        if maybe("首页展示内容"):
            p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
        # Android 17 上没有「推荐热搜榜单」这个入口（#220），找不到就跳过
        if maybe("推荐热搜榜单", scrolls=2):
            p.off(only=["热门搜索"], page="全局搜索·热搜榜单"); p.back()
        if maybe("个性化内容"):
            p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()   # 历史记录、应用建议保留


@step("阅图锁屏")
def _():
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置") and maybe("阅图锁屏"):
        p.off(only=["阅图锁屏", "锁屏横滑进入阅图"], page="阅图锁屏")


@step("应用商店")
def _():
    # 「我的」页没有能读到的齿轮入口，设置页只能按 Activity 直达（#220）。
    # Activity 不存在时 Phone.start 会直接抛出来，接住再退回「我的 → 设置」，别整段空跑。
    try:
        p.start("com.bbk.appstore", ".ui.menu.AppstoreSettingsActivity")
        reached = "AppstoreSettingsActivity" in p.focus()
    except RuntimeError as e:
        print(f"  · 直达商店设置页失败（{e}），改走「我的 → 设置」")
        reached = False
    if not reached:
        p.start("com.bbk.appstore", expect=("我的",))
        p.tap("我的", exact=True, scrolls=0)
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


@step("浏览器")
def _():
    p.start("com.vivo.browser")
    # 冷启动首页没有底部「我的」：走右上菜单 → 设置。别的 vivo 型号用它当参考脚本时可能没有这个按钮，最多等 3 秒
    if p.d(resourceId="com.vivo.browser:id/menu_btn").click_exists(timeout=3):
        time.sleep(1.0)
        p.tap("设置", exact=True, scrolls=0)
    if "SettingActivity" in p.focus() or maybe("设置"):
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
