# OPPO Find X9 Ultra（PMA110，ColorOS 17）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 app_settings / system_settings / browser_settings / open_page / tap_page / close_named /
# read_switches / hide_carousel 与 require / skip 由装载器注入执行作用域。八段都留在这里：长 Activity
# 前缀、逐个开关页的落点判据、读回名单再整表关、重进一次再回读都是本机知识，数据里写不下。
import time

# bounds 只给注入面的 carousel_choices 取（它按执行作用域解析这个名字）
from fast import ScreenLocked, bounds

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import VERIFIED_SWITCHES, p, require, rt, skip, skip_in_safe_mode
    from recipe_nav import app_settings, assistant_settings, browser_settings, hide_carousel
    from recipe_nav import open_page, read_switches, system_settings, tap_page
    from recipe_strategies import close_named_plain

BUILD = "PMA110_17.0.0.106(CN01)"

# 分段结果由引擎经 rt 记录
# 回读确认数由引擎经 rt 记录

SETTINGS = "com.android.settings/com.oplus.settings.feature.homepage.OplusSettingsHomepageActivity"
OAID = "com.android.settings/com.oplus.settings.feature.notification.oaid.OAIDActivity"
BROWSER = "com.heytap.browser/com.heytap.browser.settings.component."
# 浏览器设置页的短命令：入口只属于这台机，家族库按这个名字拼拉起命令（#1245）。
BROWSER_PREFS = "com.heytap.browser/.settings.component.BrowserPreferencesPage"
SEARCH = "com.heytap.quicksearchbox/com.heytap.quicksearchbox.ui.activity."
MARKET = "com.heytap.market/com.heytap.market.mine.cn.setting.ui."
THEME = "com.heytap.themestore/com.nearme.themespace.activities."
VIDEO = "com.heytap.yoli/com.heytap.yoli.mine.setting."
ADVICE = "com.oplus.pantanal.ums/com.oplus.advice.settings.ui."
ASSISTANT = "com.coloros.assistantscreen/com.oplus.assistantscreen."
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"


def step_ad_tracking(p, rt):
    global VERIFIED_SWITCHES
    skip_in_safe_mode()
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PMA110" or not build.startswith(BUILD):
        skip("参考或版本不同时不批量处理逐应用广告跟踪，需重新核对")
    print("  将关闭逐应用广告跟踪许可；应用清单从本机读取，不写入脚本。", flush=True)
    system_settings()
    tap_page("隐私与安全", "com.oplus.securitypermission/com.oplusos.securitypermission.privacy.PrivacySecuritySettingsDashboardActivity", scrolls=6)
    tap_page("设备标识与广告", "com.android.settings/com.oplus.settings.OplusSettingsActivity$DevicesIdentifySettingsActivity", scrolls=8)
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


def step_theme(p, rt):
    print("  将关闭开屏广告、锁屏左滑精选、个性化推荐；保留消息总开关与锁屏相机。", flush=True)
    app_settings("com.heytap.themestore", THEME + "SettingActivity", "主题商店")
    tap_page("服务管理", THEME + "SettingServiceManagerActivity", scrolls=0)
    activity = THEME + "MessageAndRecommendationSettingActivity"
    tap_page("消息与广告", activity, scrolls=0)
    close_named(["开屏广告"], "主题商店·消息与广告", activity, "消息与广告", 2)
    p.back()
    close_named(["锁屏左滑查看精选内容"], "主题商店·服务管理", THEME + "SettingServiceManagerActivity", "服务管理", 2)

    def privacy():
        app_settings("com.heytap.themestore", THEME + "SettingActivity", "主题商店")
        tap_page("隐私", THEME + "PrivacyActivity", scrolls=2)

    privacy()
    close_named(["个性化推荐设置"], "主题商店·隐私", THEME + "PrivacyActivity", "隐私", 2, reopen=privacy)


def step_assistant_advice(p, rt):
    print("  将关闭资讯服务、视界日报、小红书资讯；保留出行、快递、日程等服务。", flush=True)
    system_settings()
    # OPPO AI 首页 Activity 随版本变化，只在本机实测的小布建议页后开始读开关。
    require(p.tap("OPPO AI", exact=True, scrolls=6), "未找到 OPPO AI")
    tap_page("小布建议", ADVICE + "AdviceSettingActivity", scrolls=5)
    activity = ADVICE + "detail.SceneServiceActivity"
    tap_page("资讯服务", activity, title="服务设置", scrolls=8)
    close_named(["资讯服务"], "小布建议·资讯服务", activity, "服务设置", 2)
    detail = ADVICE + "detail.AdviceDetailActivity"
    tap_page("视界日报", detail, title="服务设置", scrolls=0)
    close_named(["视界日报"], "小布建议·视界日报", detail, "服务设置", 2)
    p.back()
    tap_page("小红书资讯", detail, title="服务设置", scrolls=0)
    close_named(["小红书资讯"], "小布建议·小红书资讯", detail, "服务设置", 2)


def tail():
    print(f"\n已回读确认 {rt.verified} 项；分段结果：{rt.results}", flush=True)
    print("录制时本机未安装游戏中心，未录入；通知渠道与组件挂起仍走 run.py 的独立流程。", flush=True)
    print("乐划须先由机主在应用内关闭锁屏功能，再按本人意愿挂起；本脚本不动乐划。", flush=True)


# 各段的调用点按旧名字写，实现住在 recipe_strategies 的 `close_named_plain`，这里绑回旧名字（#1253）。
close_named = close_named_plain
