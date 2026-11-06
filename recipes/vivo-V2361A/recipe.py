# vivo V2361A 机型脚本（OriginOS 16 / Android 16）
# 路径来源：V2361A，OriginOS 16（PD2361B_A_16.2.12.2.W10），2026-10-26 真机逐页实测。
# 说明：本脚本的**页面路径和开关标题已逐页实测确认**；整段由引擎自动执行尚未验证
#       （录制时本机 uiautomator2 读屏服务不稳定，改用原生 dump 逐页走通）。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PD2361B_A_16"
MODELS = ["V2361A"]
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
    """有就点，没有不算「走丢」，后面的步骤照常找。"""
    return p.entry(name, scrolls=scrolls)


def settings_home():
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)


# ── 本机型实测要点 ────────────────────────────────────────────────
# 1. 系统设置页顶部有**悬浮搜索框**（y 约 360-460）。往下翻后，第一行会被它盖住，
#    直接点会误触搜索。脚本里翻页后先确认目标不在顶部再点，必要时补一次小幅下滑。
# 2. 设置类开关每行有**两个 Switch 节点**：外层是整行容器（clickable=true），
#    内层才是真开关。点外层会跳页而不改状态。
# 3. 关闭时多数会弹确认框（确定 / 确认关闭），要点掉。
# 4. 应用商店的「个性化推荐」「服务管理」都藏在 我的 → 设置 → 关于 里面，
#    不在设置一级页（与 V2547DA 一致）。
# ────────────────────────────────────────────────────────────────


@step("系统广告")
def _():
    settings_home()
    if maybe("安全") and maybe("更多安全设置") and maybe("广告与隐私"):
        p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")


@step("全局搜索")
def _():
    settings_home()
    if maybe("系统管理与升级") and maybe("全局搜索"):
        if maybe("首页展示内容"):
            # 本机型这一页有：搜索框推荐词、语音搜索、历史记录、推荐卡片
            p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
        if maybe("个性化内容"):
            # 应用建议个性化、热门推荐个性化、搜索结果个性化、广告个性化
            p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()


@step("阅图锁屏")
def _():
    settings_home()
    if maybe("桌面、锁屏与壁纸") and maybe("锁屏设置") and maybe("阅图锁屏"):
        # 关掉总开关「阅图锁屏」后，「锁屏横滑进入阅图」会跟着关
        p.off(only=["阅图锁屏", "锁屏横滑进入阅图"], page="阅图锁屏")


@step("应用商店")
def _():
    p.start("com.bbk.appstore")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if maybe("关于"):
        if maybe("个性化推荐"):
            p.off(only=["个性化推荐", "个性化广告推荐"], page="商店·个性化推荐"); p.back()
        if maybe("服务管理"):
            p.off(only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                  keep=["管理页-我的服务", "空间清理"], page="商店·服务管理"); p.back()
        p.back()
    p.back(2)


@step("i管家")
def _():
    p.start("com.iqoo.secure")
    p.tap("设置", exact=True, scrolls=0)
    if maybe("关于") and maybe("个性化设置"):
        p.off(only=["应用个性化推荐"], page="i管家·个性化设置")
    p.back(3)


@step("天气")
def _():
    p.start("com.vivo.weather")
    p.tap("更多", exact=True, scrolls=0)
    if maybe("设置"):
        # 只关「天气服务」（天气相关热点资讯通知），预警类全部保留
        p.off(only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")
    p.back(2)


# ── 待补 ─────────────────────────────────────────────────────────
# 浏览器 com.vivo.browser：本机是首次启动，停在「同意 / 不同意」协议页。
#   按规范不代用户同意协议，需用户自己打开一次并同意后再录制。
# 负一屏：桌面左边缘右滑未进入（本机可能未开启或入口不同），待确认。
# ────────────────────────────────────────────────────────────────
