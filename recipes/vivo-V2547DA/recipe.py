# vivo X300 Ultra 机型脚本：V2547DA（卫星通信版）。V2547A（OriginOS 7）另有社区实测脚本 recipes/vivo-V2547A/
# 路径来源：V2547DA，OriginOS 6 / Android 16（PD2547D_A_16.0.21.21.W10），2026-10-28 真机整段跑通验证。
# 别的系统版本会用安全模式跑：只关点名的开关，找不到入口就跳过。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2547D_A_16"
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
    # 开屏推荐页会挡住底部标签栏（#420）：先确认「我的」在，不在就退一次重进，仍不在就跳过本段
    p.start("com.bbk.appstore", expect=("我的",))
    p.tap("我的", exact=True, scrolls=0)
    time.sleep(0.8)
    gear()
    if maybe("关于"):
        if maybe("个性化推荐"):
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐")
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
