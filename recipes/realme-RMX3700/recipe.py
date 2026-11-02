# realme GT Neo5 SE（RMX3700，ColorOS 16.0.5.1300(CN01)）机型脚本。
# 路径实测：2026-10-30。只收录已走通的：广告跟踪、软件商店、浏览器、小布建议、应用建议。
# 不挂包、不动通知渠道；这些操作仍走 run.py 的独立、需确认流程。
#
# 本机实测与其它机型的差异（务必保留在注释里，别照抄别家机型）：
#   · ColorOS 16 的广告跟踪入口在「隐私 → 设备标识与广告 → 广告跟踪」，不是 17 的「隐私与安全」。
#   · 软件商店有「服务管理」（OPPO GT5 Pro 那台没有），共 46 项；
#     隐私相关不在「隐私」页，而在「账号与隐私 → 隐私授权管理 → 个性化推荐」。
#   · 浏览器主页是「简洁」模式，没有底部「我的」和菜单；必须用 BrowserPreferencesPage 直达。
#   · 小布建议叫「NEXT AI」（不是「OPPO AI」）。
#   · 下拉搜索全局搜索页的 Activity 不可导出、拉不起设置页；桌面下滑手势是「通知与控制中心」。
#   · 负一屏（桌面首屏右滑）没有设置入口，页面上也没有齿轮。
#   · 本机没有独立视频 App（com.coloros.video 有包但没有 LAUNCHER 入口，com.heytap.yoli 未安装）→ 视频段跳过。
#   · 主题商店的包名是 com.oplus.themestore（/product/priv-app/KeKeOplusThemeStore-CN/），
#     不是 com.heytap.themestore —— 本机没有后者。它没有 LAUNCHER 入口，oaps://theme 落到
#     .entrance.BasicEntranceActivity。enabled=0 是 COMPONENT_ENABLED_STATE_DEFAULT（正常状态），
#     不是「被禁用」；显式禁用是 enabled=2。录制时它 suspended=true（被别人冻结了），
#     所以主题段跳过，原因记在这里：不是出厂禁用。
BUILD = "RMX3700_16.0.5.1300"

import time

ONLY = globals().get("ONLY") or []
RESULTS = []

# 商店「服务管理」是「关掉后隐藏对应服务入口」的开关。服务类入口要留，推广入口才关。
STORE_KEEP = [
    "帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：存储空间清理",
    "我的专区：我的资产", "我的专区：安全守护", "我的专区：小i客服",
    "应用使用记录", "首页：AI搜索",
]


def step(name):
    def deco(function):
        if ONLY and name not in ONLY:
            return function
        model = p.d.shell("getprop ro.product.model").output.strip()
        build = p.d.shell("getprop ro.build.display.id").output.strip()
        if model != "RMX3700" or not build.startswith(BUILD):
            print(f"\n== {name}：型号或系统版本不同，跳过；请重新核对页面")
            RESULTS.append((name, "version_mismatch"))
            return function
        if p.locked():
            print(f"\n== {name}：手机锁屏，跳过，请机主解锁")
            RESULTS.append((name, "locked"))
            return function
        print(f"\n== {name}", flush=True)
        p.miss = 0
        started = time.monotonic()
        try:
            completed = function()
            state = "completed" if completed else "incomplete"
        except Exception as error:
            print(f"  ✗ 本段停止：{error}")
            state = "failed"
        RESULTS.append((name, state))
        print(f"  ({time.monotonic() - started:.0f} 秒，{state})", flush=True)
        return function
    return deco


def wait_page(activity, title, timeout=8):
    """等到活动、页标题以及可点击区域连续稳定，避免横向动画期间的越界坐标。"""
    deadline, previous = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        if p.locked():
            return False
        if not p.focus().endswith(activity):
            time.sleep(0.2)
            continue
        root = p.tree()
        texts = p.texts(root)
        # 只识别真正的同意按钮，不把设置页里的「隐私政策」链接当作协议弹窗。
        if any(t in ("同意", "同意并继续", "同意并使用", "允许")
               and "Button" in n.get("class", "") for t, _, n in texts):
            print("  ! 出现协议/权限按钮，本段跳过，不代为同意")
            return False
        if not any(t == title for t, _, _ in texts):
            time.sleep(0.2)
            continue
        switches = p.switches(root)
        if any(not (0 < xy[0] < p.W and 0 < xy[1] < p.H)
               for _, _, xy in switches):
            time.sleep(0.2)
            continue
        signature = tuple(t for t, _, _ in texts), tuple(switches)
        if signature == previous:
            return True
        previous = signature
        time.sleep(0.25)
    print(f"  ✗ 未确认目标页面「{title}」，不操作开关")
    return False


def tap_by_scroll(text, max_scrolls=12):
    """在长列表里自己往下翻着找并点击。

    p.tap 内部会先回到页顶；小布建议页（小布建议 Activity）回顶时会判定「离开了当前页」并抛错，
    所以那一类页面必须用这个手动翻找的写法。
    """
    for _ in range(max_scrolls):
        if p.find(text, exact=True):
            return p.tap(text, exact=True, scrolls=0)
        if not p.scroll_more():
            break
    return False


def settings_page(*path):
    """打开设置并逐级点进 path 里的每一级。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    time.sleep(1.5)
    for text in path:
        if not tap_by_scroll(text):
            print(f"  ! 设置里没找到「{text}」")
            return False
        time.sleep(1.2)
    return True


@step("广告跟踪")
def _():
    # 每个 App 一个 OAID 开关、没有总开关，新装 App 默认开。
    if not settings_page("隐私"):
        return False
    if not wait_page("com.oplusos.securitypermission.privacy.PrivacySettingsDashboardActivity", "隐私"):
        return False
    if not tap_by_scroll("设备标识与广告"):
        print("  ! 没找到「设备标识与广告」")
        return False
    if not wait_page("com.oplus.settings.OplusSettingsActivity$DevicesIdentifySettingsActivity",
                     "设备标识与广告"):
        return False
    if not tap_by_scroll("广告跟踪"):
        print("  ! 没找到「广告跟踪」")
        return False
    if not wait_page("com.oplus.settings.feature.notification.oaid.OAIDActivity", "广告跟踪"):
        return False
    # 页面上全是 App 名，没有服务类开关，整页关掉即可。
    p.off(page="广告跟踪")
    return True


@step("软件商店")
def _():
    p.start("com.heytap.market")
    p.tap("我的", exact=True, scrolls=0)
    time.sleep(1.2)
    if not p.tap("设置", exact=True, scrolls=0):
        print("  ! 商店里没找到「设置」")
        return False
    time.sleep(1.5)
    if not wait_page("com.heytap.market.mine.cn.setting.ui.SettingActivity", "设置"):
        return False

    # 服务管理：46 项推广/服务入口，只保留 STORE_KEEP 里的服务类。
    if tap_by_scroll("服务管理"):
        if wait_page("com.heytap.market.mine.cn.setting.ui.ServeManagerActivity", "服务管理"):
            p.off(keep=STORE_KEEP, page="商店·服务管理")
        else:
            print("  ! 没到「服务管理」页")
        p.back()
        time.sleep(1.2)

    # 个性化推荐不在「隐私」页，在「账号与隐私 → 隐私授权管理 → 个性化推荐」。
    tap_by_scroll("账号与隐私")
    if tap_by_scroll("隐私授权管理"):
        if wait_page("com.heytap.market.mine.cn.setting.ui.PrivacyActivity", "隐私授权管理"):
            if tap_by_scroll("个性化推荐"):
                if wait_page("com.heytap.market.mine.cn.setting.ui.PersonalRecommendActivity",
                             "个性化推荐"):
                    p.off(only=["个性化推荐"], page="商店·个性化推荐")
                else:
                    print("  ! 没到「个性化推荐」页")
            else:
                print("  ! 没找到「个性化推荐」")
        else:
            print("  ! 没到「隐私授权管理」页")
        p.back()
        time.sleep(1.0)
    else:
        print("  ! 没找到「隐私授权管理」")
    return True


@step("浏览器")
def _():
    # 主页是「简洁」模式：没有底部「我的」，也没有菜单。设置页只能按公开 Activity 直达。
    p.d.shell("am start -n com.heytap.browser/com.heytap.browser.settings.component.BrowserPreferencesPage")
    time.sleep(1.5)
    if not wait_page("com.heytap.browser.settings.component.BrowserPreferencesPage", "浏览器"):
        return False
    if not tap_by_scroll("隐私"):
        print("  ! 没找到「隐私」")
        return False
    if not wait_page("com.heytap.browser.settings.component.BrowserPreferenceActivity", "隐私"):
        return False
    if not tap_by_scroll("广告管理"):
        print("  ! 没找到「广告管理」")
        return False
    p.off(only=["开屏广告", "资讯列表广告", "摇一摇广告"], page="浏览器·广告管理")
    return True


@step("小布建议")
def _():
    # realme 上叫「NEXT AI」，不是「OPPO AI」。
    if not settings_page("NEXT AI", "小布建议"):
        return False
    if not wait_page("com.oplus.advice.settings.ui.AdviceSettingActivity", "小布建议"):
        return False
    if not tap_by_scroll("资讯服务"):
        print("  ! 没找到「资讯服务」")
        return False
    if not wait_page("com.oplus.advice.settings.ui.detail.SceneServiceActivity", "资讯服务"):
        return False
    # 关掉主开关，下面的视界日报 / AI快讯 / 小红书资讯随之失效。
    p.off(only=["资讯服务"], page="小布建议·资讯服务")
    return True


@step("应用建议")
def _():
    # 负一屏/助手里的「应用建议」：每个已装 App 一个开关，关掉即不再出现在推荐里。
    if not settings_page("NEXT AI", "小布建议"):
        return False
    if not wait_page("com.oplus.advice.settings.ui.AdviceSettingActivity", "小布建议"):
        return False
    if not tap_by_scroll("应用建议"):
        print("  ! 没找到「应用建议」")
        return False
    if not wait_page("com.oplus.metis.v2.ui.settings.SettingActivity", "应用建议"):
        return False
    p.off(page="应用建议")
    return True


print("\n== 结果", flush=True)
for name, state in RESULTS:
    print(f"  {name}: {state}")
