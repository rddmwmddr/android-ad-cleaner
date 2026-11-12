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
    except SkipStep:
        raise                     # App 本机没装：放行，由段包装记跳过（#908）
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


@step("浏览器")
def _():
    browser_recommendations()


@step("i管家")
def _():
    i_manager_ads()


@step("天气")
def _():
    weather_service()
