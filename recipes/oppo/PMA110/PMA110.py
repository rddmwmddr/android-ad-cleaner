# OPPO Find X9 Ultra（PMA110，ColorOS 17）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 剩三段在这里：广告跟踪（读回名单再整表关 + 回读核对）、主题商店（`reopen=` 回调重进）、
# 小布建议（`require(p.tap(...))` 的报错出口）。其余五段（长 Activity 前缀的串联调用）已落数据。
import time

# bounds 只给注入面的 carousel_choices 取（它按执行作用域解析这个名字）
from fast import ScreenLocked, bounds
import recipe_nav as nav
import recipe_strategies as strategies


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

    rt.skip_in_safe_mode()
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PMA110" or not build.startswith(BUILD):
        rt.skip("参考或版本不同时不批量处理逐应用广告跟踪，需重新核对")
    print("  将关闭逐应用广告跟踪许可；应用清单从本机读取，不写入脚本。", flush=True)
    nav.system_settings(p, rt)
    nav.tap_page(p, rt, "隐私与安全", "com.oplus.securitypermission/com.oplusos.securitypermission.privacy.PrivacySecuritySettingsDashboardActivity", scrolls=6)
    nav.tap_page(p, rt, "设备标识与广告", "com.android.settings/com.oplus.settings.OplusSettingsActivity$DevicesIdentifySettingsActivity", scrolls=8)
    nav.tap_page(p, rt, "广告跟踪", OAID, scrolls=0)
    before = nav.read_switches(p, rt, OAID, "广告跟踪", max_screens=60)
    rt.require(before, "未读到广告跟踪列表，未操作")
    if any(before.values()):
        p.top(60)
        p.off(only=list(before), page="广告跟踪", max_screens=60)
        current = nav.read_switches(p, rt, OAID, "广告跟踪", max_screens=60)
        rt.require(set(before) <= set(current) and not any(current.values()), "广告跟踪回读未确认全部关闭")
    rt.confirm(len(before))
    print(f"  · 广告跟踪：回读确认 {len(before)} 个应用关闭", flush=True)


def step_theme(p, rt):
    print("  将关闭开屏广告、锁屏左滑精选、个性化推荐；保留消息总开关与锁屏相机。", flush=True)
    nav.app_settings(p, rt, "com.heytap.themestore", THEME + "SettingActivity", "主题商店")
    nav.tap_page(p, rt, "服务管理", THEME + "SettingServiceManagerActivity", scrolls=0)
    activity = THEME + "MessageAndRecommendationSettingActivity"
    nav.tap_page(p, rt, "消息与广告", activity, scrolls=0)
    strategies.close_named_plain(p, rt, ["开屏广告"], "主题商店·消息与广告", activity, "消息与广告", 2)
    p.back()
    strategies.close_named_plain(p, rt, ["锁屏左滑查看精选内容"], "主题商店·服务管理", THEME + "SettingServiceManagerActivity", "服务管理", 2)

    def privacy():
        nav.app_settings(p, rt, "com.heytap.themestore", THEME + "SettingActivity", "主题商店")
        nav.tap_page(p, rt, "隐私", THEME + "PrivacyActivity", scrolls=2)

    privacy()
    strategies.close_named_plain(p, rt, ["个性化推荐设置"], "主题商店·隐私", THEME + "PrivacyActivity", "隐私", 2, reopen=privacy)


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；分段结果：{rt.results}", flush=True)
    print("录制时本机未安装游戏中心，未录入；通知渠道与组件挂起仍走 run.py 的独立流程。", flush=True)
    print("乐划须先由机主在应用内关闭锁屏功能，再按本人意愿挂起；本脚本不动乐划。", flush=True)


# 各段的调用点按旧名字写，实现住在 recipe_strategies 的 `close_named_plain`，这里绑回旧名字（#1253）。

