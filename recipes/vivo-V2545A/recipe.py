# vivo X Fold6 机型脚本：V2545A（OriginOS 6 Fold，Android 16，PD2545B_A_16.0.16.0.W10）
# 入口沿用同代 OriginOS 6 路径，逐步在真机核对；整段只用 only=[] 点名关闭，找不到就跳过。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]
BUILD = "PD2545B_A_16"
MODELS = ["V2545A"]
import time

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
    """有就点，没有不算走丢。"""
    return p.entry(name, scrolls=scrolls)

def gear():
    """vivo App 设置多是右上角齿轮，没有文字。"""
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("resource-id") or "")
        if any(k in d.lower() for k in ("设置", "setting")) and n.get("clickable") == "true" and p.on_screen(n):
            from fast import bounds
            l, t, r, b = bounds(n); p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    return p.tap("设置", exact=True, scrolls=0)

def settings_home():
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)

def by_desc(kw, wait=1.2):
    """底部 tab、右上齿轮这类入口只有 content-desc，没有文字。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        if kw in (n.get("content-desc") or "") and n.get("clickable") == "true" and p.on_screen(n):
            l, t, r, b = bounds(n)
            p.click((l + r) // 2, (t + b) // 2); time.sleep(wait)
            return True
    return False

def row_switch(title):
    """商店的开关标题在开关行外，只能按同一行的 Switch 节点配对；找不到返回 None。
    整行容器和真开关都会被算进来，取树里最后一个（内层真开关）。"""
    from fast import bounds
    root = p.tree()
    rows = [bounds(n) for n in root.iter("node") if (n.get("text") or "").strip() == title]
    hit = None
    for n in root.iter("node"):
        if "Switch" in (n.get("class") or ""):
            l, t, r, b = bounds(n)
            if any(t <= (t2 + b2) // 2 <= b and t2 >= t and b2 <= b for l2, t2, r2, b2 in rows):
                hit = (n.get("checked") == "true", ((l + r) // 2, (t + b) // 2))
    return hit

def switch_off(title, page, tries=2):
    """p.off() 的开关标题取自同一行，商店这页标题在行外会配错，所以单独回读。
    关掉的项与 p.off() 一样记进 p.changed，并区分「本来就是关」和「这次关掉」。"""
    for _ in range(tries):
        state = row_switch(title)
        if state is None:
            print(f"  ? {title}：没找到")
            return False
        if not state[0]:
            print(f"  · {title}：本来就是关")
            return True
        p.click(*state[1]); time.sleep(0.9); p.confirm(); time.sleep(0.9)
        now = row_switch(title)
        if now is not None and not now[0]:
            p.changed.append((page, title))
            print(f"  关 {title}")
            return True
    print(f"  ✗ 关不掉 {title}")
    return False

def setting_search(keyword, result):
    """设置页层级变了就用搜索兜底。"""
    try:
        return bool(p.setting(keyword, result))
    except Exception as e:
        print(f"  设置搜索「{keyword}」没走通：{e}")
        return False

@step("系统广告")
def _():
    settings_home()
    done = False
    if maybe("安全") or maybe("安全与隐私"):
        if maybe("更多安全设置") and maybe("广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")
            done = True
    if not done and setting_search("广告", "广告与隐私"):
        p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私（搜索）")

@step("全局搜索")
def _():
    settings_home()
    if maybe("系统管理与升级") and maybe("全局搜索"):
        if maybe("个性化内容"):
            p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()

@step("阅图锁屏")
def _():
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置") and maybe("阅图锁屏"):
        p.off(only=["阅图锁屏", "轮播壁纸"], page="锁屏·阅图锁屏")

@step("应用商店")
def _():
    p.start("com.bbk.appstore")
    time.sleep(2)
    by_desc("我的")
    gear()
    if maybe("关于"):
        if maybe("个性化推荐"):
            for t in ("个性化推荐", "个性化广告推荐"):
                switch_off(t, page="商店·个性化推荐")
            p.back()
        if maybe("服务管理"):
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back()
        p.back(2)

@step("浏览器")
def _():
    p.start("com.vivo.browser")
    time.sleep(2)
    by_desc("菜单")
    by_desc("设置", wait=2)
    if maybe("首页设置"):
        maybe("极简首页", scrolls=0)
        p.off(only=["首页上滑展示资讯"], page="浏览器·首页设置")
        p.back(); time.sleep(1)
    if maybe("隐私权限设置"):
        p.off(only=["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], page="浏览器·隐私权限设置")
        p.back(); time.sleep(1)
    if maybe("网页浏览设置"):
        p.off(only=["网页下载相关推荐"], page="浏览器·网页浏览设置")
        p.back(); time.sleep(1)
    if maybe("更多设置"):
        p.off(only=["WiFi连接跳转新闻资讯", "跳转新闻资讯"], page="浏览器·更多设置")
        p.back(); time.sleep(1)
    p.back(2)

@step("i管家")
def _():
    print("  跳过：i管家首次启动强制要求同意用户协议，按规则不代点。")
    print("  手动做：i管家 → 设置 → 关于 → 个性化设置 → 关「应用个性化推荐」")

@step("天气")
def _():
    p.start("com.vivo.weather")
    time.sleep(2)
    by_desc("更多")
    maybe("设置", scrolls=0)
    p.off(only=["天气服务"], page="天气·设置")
    p.back(2)
