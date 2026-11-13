# 一加 Ace 2，Android 15；2026-10-29 手动路径实测，自动脚本尚未在真机整段验证。不修改通知、挂起包、快应用、系统广告跟踪或服务类开关。
from recipe_kit import step
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, rt, skip
    from recipe_nav import navigate, open_settings, page_activity, search_settings
    from recipe_nav import tap_page, wait_page
    from recipe_strategies import off_exact
# 2026-11-10 软件商店隐私入口接受「隐私」与「隐私授权管理」两种叫法，未复测（#933）。
BUILD = "PHK110_15.0.0.601(CN01)"

import time
# 分段结果由引擎经 rt 记录

# 家族库按常量选走法（#1245）：设置页走公开 Intent，下拉搜索走 scheme + 落点断言。
OPEN_SETTINGS_STYLE = "intent"
SEARCH_SETTINGS_STYLE = "page"
# 家族库的 `page_activity` 与 recipe_kit 注入的 `page()` 同名不同签名，绑回旧名字给段体用。
page = page_activity


def guard():
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PHK110" or not build.startswith(BUILD):
        skip("型号或系统版本不匹配，跳过")


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
    if not navigate(("隐私", "隐私授权管理"), "PrivacyActivity", ("隐私", "隐私授权管理")):
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


def tail():
    print("\n负一屏、主题、系统广告跟踪：请按本机实测记录手动核对。视频和小游戏未自动处理。")
    print("通知渠道、广告包和快应用按独立流程处理，挂起须机主同意。")
    print("分段结果：", rt.results)

