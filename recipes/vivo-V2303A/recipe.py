# vivo V2303A（Android 17 / OriginOS 7，build CP2A.260605.016）机型脚本。
# 由同品牌参考脚本 recipes/vivo-V2547DA/recipe_android17.py 改写而来，针对本机实测调整：
#   - BUILD / MODELS 改为本机；
#   - 「系统广告 / 全局搜索 / 阅图锁屏」三段改用 p.setting("关键词") 在设置内搜关键词直达，
#     避开逐层翻页找入口时滑出设置页的问题（Android 17 上原 maybe() 链式导航在本机不稳）。
# 实测设备：vivo V2303A，CP2A.260605.016 release-keys，2026-11-04。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "CP2A.260605.016"
MODELS = ["V2303A"]
import time
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
    其它入口（商店的 securitySettingSwitchLayout 之类）会被当成齿轮先点掉（#530）。"""
    from fast import bounds, icon_hit
    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        icon = "ImageView" in n.get("class", "") and r - l < p.W * 0.25 and b - t < p.H * 0.15
        if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n):
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
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


@step("系统广告")
def _():
    # Android 17 上用设置内搜关键词直达，避开逐层翻页滑出设置页。
    if not p.setting("广告与隐私"):
        raise RuntimeError("没搜到「广告与隐私」")
    p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")


@step("全局搜索")
def _():
    # 每个子页都先重新 p.setting("全局搜索") 回到主页再钻，保证每段起点干净，
    # 避免上一段触发「离开设置页」保护后界面污染、导致后续子页找不到。
    # 本机（V2303A / Android 17）首页展示内容下无「搜索框推荐词 / 推荐卡片」，
    # 只有「语音搜索 / 应用建议」，应用建议属常用建议不关；only= 找不到即跳过。
    for name, switches in (
        ("首页展示内容", ["搜索框推荐词", "推荐卡片"]),
        ("推荐热搜榜单", ["热门搜索"]),        # Android 17 上无此入口（#220），找不到即跳过
        ("个性化内容", ["广告个性化"]),          # 历史记录、应用建议保留
    ):
        # 放在 try 外面：搜不到要记成整段未完成，不能被下面「单页跳过」的 except 吞掉（#819）
        if not p.setting("全局搜索"):
            raise RuntimeError("没搜到「全局搜索」")
        try:
            if maybe(name, scrolls=2):
                p.off(only=switches, page=f"全局搜索·{name}"); p.back()
        except Exception as e:
            print(f"  · {name} 跳过：{e}")


@step("阅图锁屏")
def _():
    if not p.setting("锁屏设置"):
        raise RuntimeError("没搜到「锁屏设置」")
    if maybe("阅图锁屏"):
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
