# 一加 13T（PKX110，ColorOS 16.0.10.500 / Android 16）机型脚本。
# 路径实测：2026-10-28 现场探路（应用与服务、服务管理两页与 PHK110 同 Activity）。
# 骨架取自 oneplus-PHK110（ColorOS 16）；入口差异参考 docs/清单/OPPO-ColorOS.md 的一加 Ace 5（PKG110）记录。
# 不挂包、不动通知渠道；这些操作仍走 run.py 的独立、需确认流程。
BUILD = "PKX110_16.0.10"
MODELS = ["PKX110"]

import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
RESULTS = []

# 服务管理里明确的推广入口（PHK110 清单 + 本机实测新增项）。未列出的入口不主动处理。
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "应用安全安全内容推荐",
    "游戏专区：找游戏-休闲", "游戏专区：找游戏-小游戏", "游戏专区：找游戏-种草",
    "游戏专区：找游戏-VIP", "游戏专区：重磅更新卡片", "游戏专区：活动集合",
    "游戏详情页：游戏活动卡片", "游戏详情页：游戏礼包",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "我的专区：账号会员徽章", "我的专区：主题商店", "我的专区：应用时刻", "我的专区：游戏VIP",
    "小游戏二楼和专区", "AI智能体",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "详情页：限时活动",
    "手机管家：应用推荐", "文件管理：应用推荐", "福利专区",
]


def step(name):
    def deco(function):
        if ONLY and name not in ONLY:
            return function
        model = p.d.shell("getprop ro.product.model").output.strip()
        build = p.d.shell("getprop ro.build.display.id").output.strip()
        if model != "PKX110" or not build.startswith(BUILD):
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
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{error}")
            state = "failed"
        RESULTS.append((name, state))
        print(f"  ({time.monotonic() - started:.0f} 秒，{state})", flush=True)
        return function
    return deco


def wait_page(activity, title, timeout=6):
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
        # 只识别真正的同意按钮，不把设置页里的“隐私政策”链接当作协议弹窗。
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


def open_app_settings(package, activity, title):
    # 两个 App 均支持此公开设置 Intent，绕开含账号信息的“我的”页。
    result = p.d.shell(
        "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package
    ).output
    if "Permission Denial" in result or "SecurityException" in result:
        print("  ! 系统不允许直达设置，跳过，不提升权限")
        return False
    return wait_page(activity, title)


def tap_page(text, activity, title):
    return p.tap(text, exact=True) and wait_page(activity, title)


def off_exact(names, page, max_screens=16):
    """逐页传入当前可见的精确标题，不把“福利”之类子串扩展到未知服务。"""
    wanted, seen, failed = set(names), set(), set()
    for _ in range(max_screens):
        root = p.tree()
        visible = {title for title, _, _ in p.switches(root)}
        targets = wanted & visible
        seen.update(targets)
        if targets:
            before = len(p.changed)
            expected_changes = {title for title, on, _ in p.switches(root)
                                if on and title in targets}
            # fast.off 的 only 是子串匹配；把所有非精确命中的可见标题排除。
            p.off(only=list(targets), keep=list(visible - targets), page=page, max_screens=1)
            changed = {title for _, title in p.changed[before:]}
            failed.update(expected_changes - changed)
        elif not p.scroll_more():
            break
        # off 已尝试翻到下一屏；只在全局滚动到底后收尾。
        current = {title for title, _, _ in p.switches()}
        if current == visible:
            break
    if failed or wanted - seen:
        print(f"  ! 未关闭 {sorted(failed)}；未找到 {sorted(wanted - seen)}")
        return False
    return True


@step("广告跟踪")
def _():
    # 2026-10-28 实测：隐私页在 com.oplus.securitypermission，设备标识与广告在 OplusSettingsActivity$DevicesIdentifySettingsActivity。
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not tap_page("隐私", "com.oplusos.securitypermission.privacy.PrivacySettingsDashboardActivity", "隐私"):
        return False
    if not tap_page("设备标识与广告", "OplusSettingsActivity$DevicesIdentifySettingsActivity", "设备标识与广告"):
        return False
    if not p.find("重置设备标识符", exact=True):
        return False
    if not tap_page("广告跟踪", "com.oplus.settings.feature.notification.oaid.OAIDActivity", "广告跟踪"):
        return False
    # 等应用列表真正加载，不能把只有标题的空白加载页视为完成。
    for _ in range(30):
        if p.switches():
            break
        time.sleep(0.2)
    if not p.switches():
        print("  ✗ 广告跟踪列表未加载")
        return False
    p.top(n=16)
    p.off(page="广告跟踪", max_screens=40)
    return True


@step("软件商店·服务管理")
def _():
    if not open_app_settings("com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity", "应用与服务"):
        return False
    if not tap_page("服务管理", "com.heytap.market.mine.cn.setting.ui.ServeManagerActivity", "服务管理"):
        return False
    p.top(n=12)
    return off_exact(STORE_PROMOTIONS, "商店·推广入口")


@step("软件商店·个性化")
def _():
    if not open_app_settings("com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity", "应用与服务"):
        return False
    # 「隐私」在设置页底部「账号与隐私」分组下；必须 exact，说明文字里有“…隐私数据”会误中。
    if not tap_page("隐私", "com.heytap.market.mine.cn.setting.ui.PrivacyActivity", "隐私"):
        print("  · 没找到商店「隐私」入口，跳过")
        return False
    # 开关在二级页「个性化推荐」里（与 PKG110 记录一致），入口行不是开关。
    if not tap_page("个性化推荐", "com.heytap.market.mine.cn.setting.ui.PersonalRecommendActivity", "个性化推荐"):
        print("  · 没找到「个性化推荐」子页，跳过")
        return False
    return off_exact(["个性化推荐"], "商店·个性化推荐", max_screens=2)


def browser_settings():
    return open_app_settings("com.heytap.browser", "com.heytap.browser.settings.component.BrowserPreferencesPage", "浏览器")


@step("浏览器首页")
def _():
    if not browser_settings():
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page("主页设置", activity, "主页设置"):
        return False
    if p.find("简洁", exact=True):
        print("  · 首页已为简洁，保持不变")
        return True
    if not tap_page("页面布局", activity, "页面布局"):
        return False
    if not p.tap("简洁", exact=True, scrolls=0):
        return False
    p.back()
    if not wait_page(activity, "主页设置") or not p.find("简洁", exact=True):
        return False
    p.changed.append(("浏览器主页", "默认 → 简洁"))
    return True


@step("浏览器广告")
def _():
    if not browser_settings():
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page("隐私", activity, "隐私") or not tap_page("广告管理", activity, "广告管理"):
        return False
    completed = off_exact(["开屏广告", "资讯列表广告"], "浏览器·广告管理", max_screens=2)
    print("  · 摇一摇广告可能随上级开关灰置；不将 checked=true 的灰置项计作独立关闭")
    return completed


@step("浏览器个性化")
def _():
    if not browser_settings():
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page("隐私", activity, "隐私") or not tap_page("个性化管理", activity, "个性化管理"):
        return False
    return off_exact(["个性化优惠推荐", "个性化广告推荐"], "浏览器·个性化管理", max_screens=2)


@step("小布建议")
def _():
    # 2026-10-28 实测：设置首页 → OPPO AI（com.oplus.pantanal.ums/com.ums.aisetting.AISettingActivity）
    # → 小布建议（AdviceSettingActivity）。资讯服务是行状态（已卸载/已开启），不是本页开关，
    # 要关就点进「内容资讯 → 资讯服务」二级页（PKG110 同）。本机全部服务已是「已卸载」，无开关。
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not tap_page("OPPO AI", "com.ums.aisetting.AISettingActivity", "OPPO AI"):
        return False
    if not tap_page("小布建议", "com.oplus.advice.settings.ui.AdviceSettingActivity", "小布建议"):
        return False
    texts = [t for t, _, _ in p.texts()]
    if any("资讯服务" in t and "已卸载" in x for t, x in zip(texts, texts[1:])):
        print("  · 资讯服务已是「已卸载」，无需处理")
        return True
    for _ in range(8):
        if p.find("资讯服务", exact=True):
            break
        if not p.scroll_more():
            break
    if p.tap("资讯服务", exact=True, scrolls=0):
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
        p.back()
        return True
    print("  · 没找到「资讯服务」行，跳过")
    return False


print("\n本机型脚本说明：浏览器段按「入口检测不到就跳过」处理（com.heytap.browser 预装但无桌面入口、")
print("设置组件不存在时）；下拉搜索、负一屏属于原厂桌面，换用第三方桌面后不在使用面，未收录。")
print("广告包、乐划锁屏、快应用和通知渠道请按 run.py 标准流程另行确认。")
print("分段结果：", RESULTS)
