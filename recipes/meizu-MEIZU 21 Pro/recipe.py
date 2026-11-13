# 魅族 21 Pro（MEIZU 21 Pro，Flyme 12.6.0.0A / Android 16）。2026-10-30 真机分段验证：除下列两段外，其余目标已读到关闭；手机管家入口修复后单独复测通过。
from recipe_kit import step
# 浏览器、应用商店两段的启动落点与中间跳转在 #523 改过，尚未真机复测。
# 不处理通知渠道、快应用或广告包；不修改服务类通知和负一屏卡片。
BUILD = "Flyme 12.6.0.0A"
MODELS = ["MEIZU 21 Pro"]

import time
TARGET_PACKAGE = ""
# 共享库按这些常量选走法（#1246），缺省档与实现见 tool/recipe_nav.py。
WAIT_PAGE_STYLE = "meizu"
TAP_TEXT_STYLE = "meizu"
GOTO_STYLE = "meizu"
CLOSE_NAMED_STYLE = "meizu"


def page_summary():
    """失败时的页面结构：只报 Activity 与计数，不带页面文字，也不截屏（账号页不外泄）。

    计数交给 row.summary()：它按 #331 的判据只看节点，自绘开关不取色；
    `p.switches()` 会为自绘开关截图，而这两段正经过账号页。
    底栏带与 Phone.tab() 同为 85%，两处各说一个数会让复测对不上。
    """
    from row import summary
    try:
        root = p.tree()
        bottom = sum(1 for _text, (_l, top, _r, bottom_edge), _node in p.texts(root)
                     if (top + bottom_edge) // 2 >= p.H * .85)
        return f"当前页 {p.focus() or '未知'}；{summary(root, p.W, p.H)}；底栏 {bottom} 条"
    except Exception:
        return "当前页面结构读取失败"


detail = page_summary


def guard():
    # 安全模式（别的魅族机型借这份脚本、或本机版本不符）下不因型号拒跑：
    # 每段照常找入口、找不到就跳过，与其它族的参考脚本一致（#379）。
    if p.safe_mode:
        return
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    require(model in MODELS and build == BUILD, "型号或系统版本不符，未操作；请逐页核对")


def tap_id(resource_id):
    from fast import bounds
    require(not p.locked(), "手机锁屏，请机主解锁")
    require(p.focus().split("/", 1)[0] == TARGET_PACKAGE, "目标应用不在前台")
    root = p.tree()
    assert_no_other_window(root, TARGET_PACKAGE)
    nodes = [n for n in root.iter("node") if n.get("resource-id") == resource_id
             and n.get("clickable") == "true" and p.on_screen(n)]
    require(len(nodes) == 1, f"入口 {resource_id} 不唯一或不可见")
    l, t, r, b = bounds(nodes[0])
    p.click((l + r) // 2, (t + b) // 2)
    time.sleep(.7)


def open_intent(action, package):
    # 只使用本机已手动验证的公开 intent；不依赖跨版本参考脚本。
    result = p.d.shell(f"am start --windowingMode 1 -f 0x10008000 -a {action} -p {package}")
    require(not result.exit_code and not any(x in result.output for x in
            ("Error", "Exception", "Permission Denial")), "设置入口启动失败")


def open_app(package, expect):
    """expect 是目标 App 首屏的锚点：落在开屏 / 推广页时由 Phone.start 退一次再重新拉起（#523）。"""
    p.start(package, expect=expect)
    require(p.focus().split("/", 1)[0] == package, "目标应用不在前台")


def assert_no_other_window(root, package):
    """不在小窗混合其他应用或权限页时点击。"""
    foreign = {n.get("package") for n in root.iter("node") if p.on_screen(n)
               and n.get("package") and n.get("package") not in (package, "com.android.systemui")}
    require(not foreign, "检测到其他应用窗口或权限页，停止本段")


def safe_switches(activity):
    require(p.focus() == activity, "页面已变化，停止本段")
    root = p.tree()
    assert_no_other_window(root, activity.split("/", 1)[0])
    return p.switches(root)


@step("系统跟踪")
def _():
    p.d.shell("am start --windowingMode 1 -f 0x10008000 -a android.settings.SETTINGS")
    wait_page("com.android.settings/com.android.settings.homepage.SettingsHomepageActivity", "我的手机")
    goto("权限和隐私", "com.meizu.safe/com.meizu.safe.ui.permission.PermissionMainActivity", "权限和隐私", 8)
    goto("应用跟踪控制", "com.flyme.secureservice/com.flyme.secureservice.openid.ui.OAIDSettingsActivity", "应用跟踪控制", 6)
    close_named(["允许应用跟踪"], "系统·应用跟踪", p.focus())


@step("全局搜索")
def _():
    pkg = "com.meizu.net.search"
    home = pkg + "/com.meizu.net.search.ui.module.activities.SearchPreferenceActivity"
    open_intent("com.meizu.net.search.setting", pkg)
    wait_page(home, "全局搜索")
    close_named(["插件显示热词", "精选内容推送"], "全局搜索", home)
    goto("搜索项设置", pkg + "/com.meizu.net.search.ui.module.activities.SubPreferenceActivity", "搜索项设置")
    close_named(["精选内容"], "全局搜索·搜索项", p.focus())
    p.back(); wait_page(home, "全局搜索")
    goto("个性化推荐", pkg + "/com.meizu.net.search.ui.module.activities.PersonalRecommendPreferenceActivity", "个性化推荐")
    close_named(["个性化内容推荐", "个性化广告推荐"], "全局搜索·推荐", p.focus())


@step("浏览器")
def _():
    pkg = "com.android.browser"
    main = pkg + "/com.android.browser.BrowserActivity"
    settings = pkg + "/com.android.browser.activity.BrowserPreferencesPage"
    recommend = pkg + "/com.android.browser.activity.PersonalizedActivity"
    open_app(pkg, "工具"); wait_page(main, "工具")
    require(not p.locked(), "手机锁屏，请机主解锁")
    assert_no_other_window(p.tree(), pkg)
    require(p.go("工具", "设置"), "浏览器没有「设置」入口")
    require(p.go("设置", "主页展示"), "浏览器没有进入设置页")
    wait_page(settings, "主页展示")
    texts = [t for t, _, _ in p.texts(p.tree())]
    if "极简版" not in texts:
        require("标准版" in texts, "浏览器主页样式不明，未更改")
        print("  准备将浏览器主页展示从标准版改为极简版", flush=True)
        tap_text("主页展示")
        texts = [t for t, _, _ in p.texts(p.tree())]
        require("极简版" in texts and "标准版" in texts, "主页样式选择页不明确")
        tap_text("极简版")
        wait_page(settings, "主页展示")
        require(any(t == "极简版" for t, _, _ in p.texts(p.tree())), "极简版回读未确认")
        p.changed.append(("浏览器主页", "标准版 → 极简版"))
        print("  主页展示：标准版 → 极简版（已回读）", flush=True)
    goto("个性化推荐", recommend, "个性化推荐", 4)
    close_named(["个性化内容推荐", "个性化广告推荐"], "浏览器·推荐", recommend)


@step("应用商店")
def _():
    pkg = "com.meizu.mstore"
    main = pkg + "/com.meizu.flyme.appcenter.activitys.AppMainActivity"
    settings = pkg + "/com.meizu.flyme.appcenter.activitys.AppSettingsPreferenceActivity"
    recommend = pkg + "/com.meizu.cloud.app.settings.PersonalizedPreferenceActivity"
    open_app(pkg, "我的"); wait_page(main, "我的")
    require(not p.locked(), "手机锁屏，请机主解锁")
    assert_no_other_window(p.tree(), pkg)
    # 「我的」在底栏：交给 Phone.tab()，它只在底部带里找、等遮挡弹窗散开，找不到就响亮失败（#523）
    require(p.tab("我的"), "应用商店底部没有「我的」标签")
    wait_page(main, "设置")  # 不读开关、不截图账号页
    goto("设置", settings, "应用更新通知")
    goto("个性化推荐", recommend, "个性化推荐")
    close_named(["个性化内容推荐", "个性化广告推荐"], "应用商店·推荐", recommend)


@step("主题美化")
def _():
    pkg = "com.meizu.customizecenter"
    main = pkg + "/com.meizu.customizecenter.frame.activity.CustomizeCenterActivity"
    account = pkg + "/com.meizu.customizecenter.frame.modules.myAccount.view.AccountActivity"
    settings = pkg + "/com.meizu.customizecenter.frame.modules.settingactivity.view.SettingActivity"
    recommend = pkg + "/com.meizu.customizecenter.frame.modules.privacysettingactivity.PersonalizedRecommendationActivity"
    open_app(pkg, "主题"); wait_page(main, "主题")
    tap_id(pkg + ":id/account_avatar"); wait_page(account, "设置")  # 不截图账号页
    goto("设置", settings, "主题字体动态壁纸更新通知")
    goto("个性化推荐", recommend, "个性化推荐")
    close_named(["个性化广告推荐"], "主题美化·推荐", recommend)


@step("天气")
def _():
    pkg = "com.meizu.flyme.weather"
    main = pkg + "/com.hy.weather.mz.modules.home.WeatherMainActivity"
    settings = pkg + "/com.hy.weather.mz.WeatherSettingActivity"
    content = pkg + "/com.hy.weather.mz.WeatherPersonalizationSettingActivity"
    recommend = pkg + "/com.hy.weather.mz.RecommendSettingActivity"
    open_app(pkg, "更多选项"); wait_page(main, "更多选项")
    tap_text("更多选项"); tap_text("设置"); wait_page(settings, "预警管理")
    goto("内容推荐", content, "内容推荐")
    close_named(["本地资讯", "精选内容推送", "允许展示开屏推荐"], "天气·内容", content)
    p.back(); wait_page(settings, "预警管理")
    goto("个性化推荐", recommend, "个性化推荐")
    close_named(["个性化内容推荐", "个性化广告推荐"], "天气·推荐", recommend)


@step("手机管家")
def _():
    p.d.shell("am start --windowingMode 1 -f 0x10008000 -a android.settings.SETTINGS")
    wait_page("com.android.settings/com.android.settings.homepage.SettingsHomepageActivity", "我的手机")
    main = "com.meizu.safe/com.meizu.safe.SecurityMainActivity"
    settings = "com.meizu.safe/com.meizu.safe.MainSettingsActivity"
    recommend = "com.meizu.safe/com.meizu.safe.PersonalizedSettingsActivity"
    goto("手机管家", main, "设置", 8)
    goto("设置", settings, "应用下载推荐")
    close_named(["允许展示开屏推荐", "应用下载推荐"], "手机管家·内容", settings)
    goto("个性化推荐", recommend, "个性化推荐", 4)
    close_named(["个性化广告推荐"], "手机管家·推荐", recommend)


@step("锁屏画报")
def _():
    pkg = "com.meizu.net.nativelockscreen"
    home = pkg + "/com.meizu.net.lockscreenlibrary.view.LockScreenPosterSettingActivity"
    settings = pkg + "/com.meizu.net.lockscreenlibrary.view.settings.SettingsActivity"
    recommend = pkg + "/com.meizu.net.lockscreenlibrary.view.settings.PersonalizedRecommendationsActivity"
    open_intent("com.meizu.net.nativelockscreen.locksettingpage", pkg)
    wait_page(home, "锁屏画报")
    goto("设置", settings, "个性化推荐")
    goto("个性化推荐", recommend, "个性化推荐")
    close_named(["个性化内容推荐", "个性化广告推荐"], "锁屏画报·推荐", recommend)


def tail():
    print(f"\n已调整 {len(p.changed)} 项；未完成步骤 {len(rt.failed_steps)} 个。", flush=True)
    print("通知渠道、广告包、快应用按标准流程另行处理。", flush=True)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, require, rt
    from recipe_nav import close_named, goto, tap_text, wait_page
