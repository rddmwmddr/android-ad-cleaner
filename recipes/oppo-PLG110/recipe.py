# OPPO Find X9 Pro（PLG110），ColorOS 16.0.10.501(CN01) / Android 16。2026-11-01 真机逐页记录；仅收录本机已识别的开关，不包含包操作和通知渠道。
from recipe_kit import step
# 软件商店隐私入口接受「隐私」与「隐私授权管理」两种叫法，未复测（#933）。
BUILD = "PLG110_16.0.10"
# 家族库按这些常量选走法（#1245），缺省档见 tool/recipe_nav.py。
WAIT_PAGE_STYLE = "raise"
TAP_PAGE_STYLE = "raise"
READ_SWITCHES_STYLE = "expect"
OPEN_PAGE_STYLE = "shell"
APP_SETTINGS_STYLE = "shell"
SYSTEM_SETTINGS_STYLE = "shell"
MODELS = ["PLG110"]

import re
import time

# bounds 只给注入面的 carousel_choices 取（它按执行作用域解析这个名字）
from fast import ScreenLocked, bounds
# 分段结果由引擎经 rt 记录
# 回读确认数由引擎经 rt 记录

SETTINGS = "com.android.settings/com.oplus.settings.feature.homepage.OplusSettingsHomepageActivity"
OAID = "com.android.settings/com.oplus.settings.feature.notification.oaid.OAIDActivity"
BROWSER = "com.heytap.browser/com.heytap.browser.settings.component."
SEARCH = "com.heytap.quicksearchbox/com.heytap.quicksearchbox.ui.activity."
MARKET = "com.heytap.market/com.heytap.market.mine.cn.setting.ui."
THEME = "com.oplus.themestore"
VIDEO = "com.heytap.yoli/com.heytap.yoli.mine.setting."
ADVICE = "com.oplus.pantanal.ums/com.oplus.advice.settings.ui."
ASSISTANT = "com.coloros.assistantscreen/com.oplus.assistantscreen."
GAMECENTER = "com.nearme.gamecenter/com.nearme.gamecenter.me.ui."
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"

# 软件商店服务管理中明确的推广入口
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "应用安全安全内容推荐",
    "游戏专区：找游戏-休闲", "游戏专区：找游戏-小游戏", "游戏专区：找游戏-种草",
    "游戏专区：找游戏", "游戏专区：重磅更新卡片", "游戏专区：活动集合",
    "游戏详情页：游戏活动卡片", "游戏详情页：游戏礼包",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "我的专区：账号会员徽章", "我的专区：主题商店", "我的专区：应用时刻", "我的专区：游戏VIP",
    "小游戏二楼和专区", "AI智能体",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "详情页：限时活动",
    "手机管家：应用推荐", "文件管理：应用推荐", "福利专区",
]


def close_named(names, page, activity, title=None, max_screens=8, reopen=None, dependent=()):
    """精确核对标题再调用引擎；回读关闭状态，同时保留其他功能开关。"""
    # 回读确认数由引擎经 rt 记录
    before = read_switches(activity, title, max_screens, expect=names)
    require_switches(before, names, page)
    if any(before[name] for name in names):
        p.top(max_screens)
        p.off(only=list(names), keep=[name for name in before if name not in names],
              page=page, max_screens=max_screens)
        if reopen:
            reopen()
        current = read_switches(activity, title, max_screens, expect=names)
        require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
        require(all(current.get(name) == state for name, state in before.items()
                    if name not in names and name not in dependent), f"{page}：其他开关状态变化，请核对")
    rt.confirm(len(names))
    print(f"  · {page}：回读确认 {len(names)} 项关闭", flush=True)


# ==================== 各段具体实现 ====================

@step("广告跟踪")
def _():
    global VERIFIED_SWITCHES
    skip_in_safe_mode()
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PLG110" or not build.startswith(BUILD):
        skip("参考或版本不同时不批量处理逐应用广告跟踪，需重新核对")
    print("  将关闭逐应用 OAID 广告跟踪许可；不重置设备标识符。", flush=True)
    system_settings()
    require(p.setting("设备标识与广告", "设备标识与广告"), "未找到设备标识与广告入口")
    tap_page("广告跟踪", OAID, scrolls=0)
    before = read_switches(OAID, "广告跟踪", max_screens=60)
    require(before, "未读到广告跟踪列表，未操作")
    if any(before.values()):
        p.top(60)
        p.off(only=list(before), page="广告跟踪", max_screens=60)
        current = read_switches(OAID, "广告跟踪", max_screens=60)
        require(set(before) <= set(current) and not any(current.values()), "广告跟踪回读未确认全部关闭")
    VERIFIED_SWITCHES += len(before)
    print(f"  · 广告跟踪：回读确认 {len(before)} 个应用关闭", flush=True)


@step("软件商店")
def _():
    global VERIFIED_SWITCHES
    print("  将关闭个性化推荐与推广服务；保留下载更新与应用安全。", flush=True)
    app_settings("com.heytap.market", MARKET + "SettingActivity", "软件商店")
    tap_page(("隐私", "隐私授权管理"), MARKET + "PrivacyActivity", scrolls=8)
    activity = MARKET + "PersonalRecommendActivity"
    tap_page("个性化推荐", activity, scrolls=0)
    close_named(["个性化推荐"], "软件商店·个性化推荐", activity, "个性化推荐", 4)
    # 推广入口管理
    app_settings("com.heytap.market", MARKET + "SettingActivity", "软件商店")
    tap_page("服务管理", MARKET + "ServeManagerActivity", scrolls=6)
    activity_serve = MARKET + "ServeManagerActivity"
    before = read_switches(activity_serve, "服务管理", 8)
    to_close = [k for k in before if k in STORE_PROMOTIONS]
    if to_close:
        p.top(8)
        p.off(only=to_close, keep=[k for k in before if k not in to_close],
              page="软件商店·服务管理", max_screens=8)
        current = read_switches(activity_serve, "服务管理", 8)
        require(all(current.get(name) is False for name in to_close), "服务管理回读未确认关闭")
        VERIFIED_SWITCHES += len(to_close)
    print(f"  · 软件商店·服务管理：处理完成，核心服务已保留", flush=True)


@step("浏览器")
def _():
    print("  将关闭开屏广告、资讯列表广告、个性化搜索与广告推荐；不改默认引擎与主页布局。", flush=True)
    app_settings("com.heytap.browser", BROWSER + "BrowserPreferencesPage", "浏览器")
    activity = BROWSER + "BrowserPreferenceActivity"
    tap_page("隐私", activity, scrolls=4)
    # 广告管理
    tap_page("广告管理", activity, scrolls=2)
    close_named(["开屏广告", "资讯列表广告"], "浏览器·广告管理", activity, "广告管理", 2)
    p.back()
    wait_page(activity, "隐私")
    # 个性化管理
    tap_page("个性化管理", activity, scrolls=2)
    close_named(["个性化搜索推荐", "个性化广告推荐"], "浏览器·个性化管理", activity, "个性化管理", 2)


@step("下拉搜索")
def _():
    print("  将关闭搜索范围中的商业推荐、搜索框提示词、隐私中的个性化推荐。", flush=True)
    open_page(SEARCH_SETTINGS, SEARCH + "SearchSettingActivity", "搜索设置")
    activity_source = SEARCH + "SearchSourceActivity"
    tap_page("搜索范围", activity_source, scrolls=0)
    close_named(["榜单", "小说", "购物", "个性化推荐", "精选资讯"], "下拉搜索·搜索范围",
                activity_source, "搜索范围", 6, dependent=["全部"])
    p.back()
    activity_func = SEARCH + "SearchFunctionManagerActivity"
    tap_page("功能管理", activity_func, scrolls=2)
    close_named(["搜索框提示词"], "下拉搜索·功能管理", activity_func, "功能管理", 2)
    p.back()
    activity_priv = SEARCH + "PrivacySettingsActivity"
    tap_page("隐私", activity_priv, scrolls=4)
    close_named(["个性化推荐"], "下拉搜索·隐私", activity_priv, "隐私", 2)


@step("负一屏")
def _():
    print("  将关闭热点资讯、搜索框提示词，轮播改为不显示；保留功能卡片和推荐服务总开关。", flush=True)
    assistant_settings()
    activity = ASSISTANT + "setting.AssistantScreenSettingActivity"
    close_named(["搜索框提示词"], "负一屏·搜索框提示词", activity, "设置", 2)
    # 轮播推荐单选项
    tap_page("推荐服务", ASSISTANT + "setting.recommendservice.RecommendServiceSettingActivity", scrolls=0)
    hide_carousel()
    p.back()
    wait_page(activity, "设置")
    # 隐私中的热点资讯
    tap_page("隐私", ASSISTANT + "setting.activity.PrivacyActivity", scrolls=4)
    activity_priv = ASSISTANT + "setting.activity.PersonalRecommendManageActivity"
    tap_page("个性化推荐", activity_priv, scrolls=0)
    close_named(["热点资讯"], "负一屏·个性化推荐", activity_priv, "个性化推荐", 2)


@step("视频")
def _():
    print("  将关闭 OPPO 视频个性化推荐与广告推荐；保留在线播放和下载设置。", flush=True)
    p.start("com.heytap.yoli")
    p.go("我的", "设置")
    tap_page("设置", VIDEO + "SettingActivity", scrolls=0, exact=False)
    activity = VIDEO + "PersonalizedContentManageActivity"
    tap_page("个性化管理", activity, scrolls=3)
    close_named(["个性化广告推荐", "个性化内容推荐"], "OPPO视频·个性化管理", activity, "个性化管理", 2)


@step("游戏中心")
def _():
    print("  将关闭游戏中心个性化推荐；保留游戏助手与时长同步。", flush=True)
    p.start("com.nearme.gamecenter")
    time.sleep(1.2)
    p.dismiss()
    # 弹窗压在带开关/滚动列表的页面上：p.dismiss() 只认 ✕ 图标、不点名文字按钮（见 fast.dismiss 的守卫），
    # 所以开屏与引导弹窗按页面实见的按钮逐个点名。
    for _ in range(4):
        for dismiss_btn in ("取消", "我知道了", "不再提醒", "忽略", "跳过"):
            if p.find(dismiss_btn, exact=True):
                p.tap(dismiss_btn, exact=True, scrolls=0)
                time.sleep(0.4)
    if not p.tap("我的", exact=False, scrolls=0):
        raise RuntimeError("未找到底部「我的」入口")
    time.sleep(0.8)
    for dismiss_btn in ("我知道了", "取消", "不再提醒", "忽略"):
        if p.find(dismiss_btn, exact=True):
            p.tap(dismiss_btn, exact=True, scrolls=0)
            time.sleep(0.4)
    tap_page("设置", GAMECENTER + "SettingActivity", scrolls=0, exact=False)
    tap_page("隐私开关设置", GAMECENTER + "PrivacySettingActivity", scrolls=2)
    activity = GAMECENTER + "PersonalRecommendActivity"
    tap_page("个性化推荐管理", activity, scrolls=0)
    close_named(["个性化推荐"], "游戏中心·个性化", activity, "个性化推荐管理", 2)


@step("小布建议")
def _():
    print("  核对并关闭小布建议内容资讯服务；保留出行、生活等实用卡片。", flush=True)
    system_settings()
    require(p.tap("OPPO AI", exact=True, scrolls=6), "未找到 OPPO AI")
    tap_page("小布建议", ADVICE + "AdviceSettingActivity", scrolls=5)
    for _ in range(8):
        if p.find("资讯服务", exact=True):
            break
        if not p.scroll_more():
            break
    texts = [t for t, _, _ in p.texts()]
    if any("资讯服务" in t and "未开启" in x for t, x in zip(texts, texts[1:])):
        print("  · 资讯服务已是「未开启」，保持不变", flush=True)
        return
    if p.tap("资讯服务", exact=True, scrolls=0):
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
        p.back()


@step("主题商店")
def _():
    print("  检查主题商店服务模式；基础服务模式无广告，不代为同意完整模式协议。", flush=True)
    result = p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.oplus.themestore").output
    time.sleep(1)
    if "BasicEntranceActivity" in p.focus():
        print("  · 主题商店处于「基础服务」模式，本身不含广告，保持不变", flush=True)
        return
    print("  · 当前未处于基础服务模式，跳过自动处理以避免误点协议", flush=True)


def tail():
    print(f"\n已回读确认 {rt.verified} 项；分段结果：{rt.results}", flush=True)
    print("通知渠道与组件挂起仍走 run.py 的独立流程。", flush=True)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, require, require_switches, rt, skip, skip_in_safe_mode
    from recipe_nav import app_settings, assistant_settings, hide_carousel, open_page, read_switches, system_settings, tap_page, wait_page
