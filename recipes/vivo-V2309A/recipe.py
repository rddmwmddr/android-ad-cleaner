# vivo V2309A，OriginOS 6 / Android 16，PD2309E_A_16.2.15.0.W10。
# 路径来自 2026-11-02 真机逐段操作：七段整轮 149 秒，每段回读确认（#530）。
# 2026-11-03 从开启状态复跑：26 个点名开关逐个关闭、每页回读核对，213 秒；复跑轮 165 秒。
# 底子是同品牌参考脚本 vivo-V2547DA；本机差异集中在「应用商店」一段，见该段注释。
# 别的系统版本会用安全模式跑：只关点名的开关，找不到入口就跳过。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2309E_A_16"
MODELS = ["V2309A"]
import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


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


def settings_home():
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)


def gear_top():
    """「我的」页右上角齿轮。

    这台是无文字 Button，只有 content-desc="设置"。判据用引擎的 icon_hit（#530 / ADR-0013）：
    它只认正好是「设置」的描述 / 正文，同页那条「去功能设置里重新开启」的说明行不会被点到，
    所以不用再按位置收一次。齿轮名字不是恰好「设置」（比如「更多设置」）的机型会在这里漏掉。
    """
    from fast import bounds, icon_hit
    for n in p.tree().iter("node"):
        if n.get("clickable") != "true" or not p.on_screen(n):
            continue
        if not icon_hit(n):
            continue
        l, t, r, b = bounds(n)
        if r > l and b > t:
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1.0)
            return True
    return False


def tap_row(title, scrolls=4):
    """点标题所在的可点行，落点在行宽 40% 处。

    商店设置页点左侧标题文字不跳转（V1986A 同此），要点行中间（#530）。
    """
    from fast import bounds
    for _ in range(scrolls + 1):
        root = p.tree()
        parent = {c: par for par in root.iter("node") for c in par}
        for n in root.iter("node"):
            if (n.get("text") or "").strip() != title or not p.on_screen(n):
                continue
            row = n
            for _ in range(4):
                up = parent.get(row)
                if up is None or up.get("clickable") != "true":
                    break
                row = up
            l, t, r, b = bounds(row)
            if r <= l or b <= t:
                l, t, r, b = bounds(n)
            p.click(int(l + (r - l) * 0.4), (t + b) // 2); time.sleep(1.0)
            return True
        if not p.scroll_more():
            break
    return False


@step("系统广告")
def _():
    settings_home()
    # 本机「安全」页首屏没有「更多安全设置」，它在下面，靠 entry 的翻页找（6 屏够）
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
    # 本机三处入口差异（参考脚本照 V2547DA 的写法在这台上空转 216 秒，全段「没找到」）：
    #   1. 底部「我的」读作「我的, 2个应用待更新,第5个, 共5个」，带角标与序号后缀，
    #      精确匹配永远落空 → 用引擎的 p.tab()，它在底带内按三层递进找（ADR-0012）
    #   2. 右上齿轮是无文字 Button，content-desc="设置" → gear_top() 走引擎 icon_hit 的精确判据
    #   3. 「关于」点左侧标题文字不跳转 → tap_row() 点行中间
    # 冷启动偶尔先出开屏/推荐页挡住标签栏（#420）：p.tab() 自己在 6 秒里边等边关弹窗
    p.start("com.bbk.appstore", expect=("我的",))
    require(p.tab("我的"), "底部没有「我的」标签，商店可能停在开屏或推荐页")
    require(gear_top(), "「我的」页没找到右上角齿轮")
    require(tap_row("关于"), "商店设置页没找到「关于」")
    if maybe("个性化推荐"):
        p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐")
        p.back(); time.sleep(0.5)
    if maybe("服务管理"):
        # 本机这一项叫「悬浮球」，不是 V2547DA 记的「悬浮窗」；两名并存见 docs/清单
        p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮球", "限时推广"],
              keep=["我的服务", "空间清理"], page="商店·服务管理")
        p.back()
    p.back()
    if tap_row("消息提醒"):
        # 9 个提醒里只有「资讯活动提醒」是营销；应用更新 / 安装完成 / 预约安装类一律保留
        p.off(only=["资讯活动提醒"], page="商店·消息提醒")
        p.back()
    p.back(2)


@step("浏览器")
def _():
    p.start("com.vivo.browser")
    # 冷启动首页没有底部「我的」：走右上菜单 → 设置
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
