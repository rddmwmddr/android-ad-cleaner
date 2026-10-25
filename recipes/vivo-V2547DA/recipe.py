# vivo X300 Ultra 机型脚本：V2547DA（卫星通信版）、V2547A
# 路径来源：V2547DA，OriginOS 6 / Android 16（PD2547D_A_16.0.22.8），2026-10-22 手动实测。机型脚本整段跑待验证。
# 别的系统版本会用安全模式跑：只关点名的开关，找不到入口就跳过。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2547D_A_16"
MODELS = ["V2547DA", "V2547A"]
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
    p.miss = 0
    ok = p.tap(name, exact=True, scrolls=scrolls)
    p.miss = 0
    return ok


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
        if maybe("推荐热搜榜单"):
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
    p.start("com.bbk.appstore")
    p.go("我的", "设置")
    gear()
    if maybe("关于"):
        p.off(only=["个性化推荐"], page="商店·关于"); p.back()
    if maybe("服务管理"):
        p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
              keep=["我的服务", "空间清理"], page="商店·服务管理"); p.back()
    p.back(2)


@step("浏览器")
def _():
    p.start("com.vivo.browser")
    p.go("我的", "设置")
    gear()
    if maybe("首页设置"):
        maybe("极简首页", scrolls=0)
        p.off(only=["首页上滑展示资讯"], page="浏览器·首页设置"); p.back()
    if maybe("隐私权限设置"):
        p.off(only=["个性化内容", "第三方应用来源个性化推荐"], page="浏览器·隐私"); p.back()
    if maybe("网页浏览设置"):
        p.off(only=["网页下载相关推荐"], page="浏览器·网页浏览"); p.back()
    if maybe("更多设置"):
        p.off(only=["WiFi 连接跳转新闻资讯", "跳转新闻资讯"], page="浏览器·更多设置"); p.back()
    p.back(2)


@step("i管家")
def _():
    p.start("com.iqoo.secure")
    gear()
    if maybe("关于") and maybe("个性化设置"):
        p.off(only=["应用个性化推荐"], page="i管家·个性化设置")
    p.back(3)


@step("天气")
def _():
    p.start("com.vivo.weather")
    gear()
    p.off(only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")   # 只关「天气相关热点资讯通知」
    p.back(2)
