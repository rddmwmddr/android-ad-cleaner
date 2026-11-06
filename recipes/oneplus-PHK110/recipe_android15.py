# 一加 Ace 2，Android 15；2026-10-29 手动路径实测，自动脚本尚未在真机整段验证。
# 不修改通知、挂起包、快应用、系统广告跟踪或服务类开关。
BUILD = "PHK110_15.0.0.601(CN01)"

import time
from wait import GiveUp, until

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
RESULTS = []


def step(name):
    def decorator(function):
        if ONLY and name not in ONLY:
            return function
        if (p.d.shell("getprop ro.product.model").output.strip() != "PHK110"
                or p.d.shell("getprop ro.build.display.id").output.strip() != BUILD):
            print(f"\n== {name}：型号或系统版本不匹配，跳过")
            RESULTS.append((name, "version_mismatch"))
            return function
        if p.locked():
            print(f"\n== {name}：手机锁屏，跳过")
            RESULTS.append((name, "locked"))
            return function
        print(f"\n== {name}", flush=True)
        p.miss = 0
        try:
            state = "completed" if function() else "incomplete"
        except Exception as error:
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{error}")
            state = "failed"
        RESULTS.append((name, state))
        print(f"  {state}", flush=True)
        return function
    return decorator


def page(activity, title, timeout=6):
    """确认前台 Activity、标题和开关坐标稳定；出现协议时不操作。"""
    def sample():
        if p.locked():
            raise GiveUp()
        if not p.focus().endswith(activity):
            return None
        root = p.tree()
        texts = p.texts(root)
        if any(t in ("同意", "同意并继续", "同意并使用", "允许", "开始使用")
               and "Button" in n.get("class", "") for t, _, n in texts):
            print("  ! 出现协议或权限提示，跳过")
            raise GiveUp()
        switches = p.switches(root)
        if (not any(t == title for t, _, _ in texts)
                or any(not (0 < xy[0] < p.W and 0 < xy[1] < p.H)
                       for _, _, xy in switches)):
            return None
        return tuple(t for t, _, _ in texts), tuple(switches)

    found = until(sample, timeout=timeout, poll=.2, same=2, now=time.monotonic, sleep=time.sleep)
    if not found:
        print(f"  ✗ 未确认页面「{title}」，跳过")
    return bool(found)


def navigate(label, activity, title):
    return p.tap(label, exact=True) and page(activity, title)


def off_exact(names, activity, title):
    """只处理当前页精确匹配的开关，并在同一页面读回。"""
    if not page(activity, title):
        return False
    switches = p.switches()
    visible = {name for name, _, _ in switches}
    wanted = set(names)
    if not wanted <= visible:
        print(f"  ! 缺少开关 {sorted(wanted - visible)}，本页不操作")
        return False
    for name in names:
        if not page(activity, title):
            return False
        matches = [(on, xy) for label, on, xy in p.switches() if label == name]
        if len(matches) != 1:
            print(f"  ! 开关「{name}」无法唯一确认，停止")
            return False
        on, xy = matches[0]
        if on:
            p.click(*xy)
            p.confirm()
            if not page(activity, title):
                return False
            after = [(on, xy) for label, on, xy in p.switches() if label == name]
            if len(after) != 1 or after[0][0]:
                print(f"  ! 开关「{name}」未确认关闭")
                return False
            p.changed.append((title, name))
            print(f"  关 {name}")
    states = {name: on for name, on, _ in p.switches() if name in wanted}
    if set(states) != wanted or any(states.values()):
        print("  ! 开关未全部确认关闭")
        return False
    return True


def open_settings(package, activity, title):
    out = p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package)
    if out.exit_code or any(x in out.output for x in ("Error", "Exception", "Permission Denial")):
        return False
    return page(activity, title)


def search_settings():
    out = p.d.shell("am start -a android.intent.action.VIEW -d gs://search/setting")
    if out.exit_code or "Error" in out.output:
        return False
    return page("com.heytap.quicksearchbox.ui.activity.SearchSettingActivity", "搜索设置")


@step("搜索卡片")
def _():
    if not search_settings() or not navigate("首页卡片管理", "SearchModuleManagerActivity", "首页卡片管理"):
        return False
    return off_exact(["未下载应用推荐", "应用建议小卡", "热搜应用", "精选推荐",
                      "热搜榜单", "活动皮肤", "推荐卡片"], "SearchModuleManagerActivity", "首页卡片管理")


@step("搜索提示词")
def _():
    if not search_settings() or not navigate("功能管理", "SearchFunctionManagerActivity", "功能管理"):
        return False
    return off_exact(["搜索框提示词"], "SearchFunctionManagerActivity", "功能管理")


@step("搜索个性化")
def _():
    if not search_settings() or not navigate("隐私", "PrivacySettingsActivity", "隐私"):
        return False
    return off_exact(["个性化推荐"], "PrivacySettingsActivity", "隐私")


@step("软件商店个性化")
def _():
    if not open_settings("com.heytap.market", "SettingActivity", "软件商店"):
        return False
    if not navigate("隐私授权管理", "PrivacyActivity", "隐私授权管理"):
        return False
    if not navigate("个性化推荐", "PersonalRecommendActivity", "个性化推荐"):
        return False
    return off_exact(["个性化推荐"], "PersonalRecommendActivity", "个性化推荐")


def browser():
    return open_settings("com.heytap.browser", "BrowserPreferencesPage", "浏览器")


@step("浏览器广告")
def _():
    if not browser() or not navigate("隐私", "BrowserPreferenceActivity", "隐私"):
        return False
    if not navigate("广告管理", "BrowserPreferenceActivity", "广告管理"):
        return False
    return off_exact(["开屏广告", "资讯列表广告"], "BrowserPreferenceActivity", "广告管理")


@step("浏览器个性化")
def _():
    if not browser() or not navigate("隐私", "BrowserPreferenceActivity", "隐私"):
        return False
    if not navigate("个性化管理", "BrowserPreferenceActivity", "个性化管理"):
        return False
    return off_exact(["个性化搜索推荐", "个性化优惠推荐", "个性化广告推荐"],
                     "BrowserPreferenceActivity", "个性化管理")


@step("浏览器首页")
def _():
    if not browser() or not navigate("主页设置", "BrowserPreferenceActivity", "主页设置"):
        return False
    if p.find("简洁", exact=True):
        return True
    if not navigate("页面布局", "BrowserPreferenceActivity", "页面布局"):
        return False
    if not p.tap("简洁", exact=True, scrolls=0):
        return False
    p.back()
    if not page("BrowserPreferenceActivity", "主页设置") or not p.find("简洁", exact=True):
        return False
    p.changed.append(("浏览器主页", "默认 → 简洁"))
    return True


print("\n负一屏、主题、系统广告跟踪：请按本机实测记录手动核对。视频和小游戏未自动处理。")
print("通知渠道、广告包和快应用按独立流程处理，挂起须机主同意。")
print("分段结果：", RESULTS)
