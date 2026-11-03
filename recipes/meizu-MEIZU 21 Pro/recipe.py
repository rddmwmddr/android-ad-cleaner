# 魅族 21 Pro（MEIZU 21 Pro，Flyme 12.6.0.0A / Android 16）。
# 2026-10-30 真机分段验证：除下列两段外，其余目标已读到关闭；手机管家入口修复后单独复测通过。
# 浏览器、应用商店两段的启动落点与中间跳转在 #523 改过，尚未真机复测。
# 不处理通知渠道、快应用或广告包；不修改服务类通知和负一屏卡片。
BUILD = "Flyme 12.6.0.0A"
MODELS = ["MEIZU 21 Pro"]

import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
TARGET_PACKAGE = ""


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def step(name):
    def decorate(action):
        if ONLY and name not in ONLY:
            return action
        print(f"\n== {name}", flush=True)
        try:
            # 安全模式（别的魅族机型借这份脚本、或本机版本不符）下不因型号拒跑：
            # 每段照常找入口、找不到就跳过，与其它族的参考脚本一致（#379）。
            if not p.safe_mode:
                model = p.d.shell("getprop ro.product.model").output.strip()
                build = p.d.shell("getprop ro.build.display.id").output.strip()
                require(model in MODELS and build == BUILD,
                        "型号或系统版本不符，未操作；请逐页核对")
            require(not p.locked(), "手机锁屏，请机主解锁")
            p.miss = 0
            action()
        except Exception as error:
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{error}", flush=True)
            print(f"  · {page_summary()}", flush=True)
        return action
    return decorate


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


def wait_page(activity, title, timeout=8):
    global TARGET_PACKAGE
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        require(not p.locked(), "手机锁屏，请机主解锁")
        if p.focus() == activity:
            texts = p.texts(p.tree())
            require(not any(t in ("同意", "同意并继续", "同意并使用", "允许")
                            and "Button" in (n.get("class") or "") for t, _, n in texts),
                    "出现协议或权限申请，未同意，停止本段")
            if any(t == title and n.get("package") == activity.split("/", 1)[0] for t, _, n in texts):
                TARGET_PACKAGE = activity.split("/", 1)[0]
                return
        time.sleep(.2)
    raise RuntimeError(f"未确认目标页「{title}」：{activity}")


def tap_text(text, scrolls=0):
    """只点击可见的准确文字；找不到时只滚动当前页面，不自动处理弹窗。"""
    initial = p.focus()
    for index in range(scrolls + 1):
        require(not p.locked(), "手机锁屏，请机主解锁")
        require(p.focus() == initial, "页面已变化，停止点击")
        root = p.tree()
        assert_no_other_window(root, TARGET_PACKAGE)
        hits = [(b, n) for t, b, n in p.texts(root)
                if t == text and n.get("package") == TARGET_PACKAGE]
        # 同一按钮可同时有容器和子文字；不同区域的同名项不猜。
        centers = {((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for b, _ in hits}
        if centers:
            if len(centers) > 1:
                # 父子节点的中心可有微小偏移，但不能指向不同位置。
                xs, ys = zip(*centers)
                require(max(xs) - min(xs) < p.W * .15 and max(ys) - min(ys) < p.H * .08,
                        f"「{text}」有多个位置，未点击")
            x, y = min(centers, key=lambda xy: xy[1])
            require(0 <= x < p.W and 0 <= y < p.H, "坐标不在屏幕内")
            # 底部可能被系统导航区域覆盖，即使文字节点中心仍在屏幕内。
            if y >= p.H * .95:
                if index < scrolls and p.scroll_more():
                    continue
                raise RuntimeError(f"「{text}」位于屏幕底部导航区域附近，未点击")
            p.click(x, y)
            time.sleep(.7)
            return
        if index == scrolls or not p.scroll_more():
            break
    raise RuntimeError(f"未找到「{text}」")


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


def goto(text, activity, title, scrolls=0):
    tap_text(text, scrolls)
    wait_page(activity, title)


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


def close_named(names, page, activity):
    """精确标题、逐项点击、识别关闭确认框并回读；有变化或不确定立即停止。"""
    global p
    require(p.focus() == activity, f"{page}：页面不符")
    before_list = safe_switches(activity)
    require(all(sum(1 for t, _, _ in before_list if t == name) == 1 for name in names),
            f"{page}：目标开关未全部唯一识别，未操作")
    baseline = {t: on for t, on, _ in before_list}
    print(f"  准备关闭 {page}：{'、'.join(names)}；已关闭的保持不变", flush=True)
    for name in names:
        require(not p.locked(), "手机锁屏，请机主解锁")
        require(p.focus() == activity, "页面已变化，停止本段")
        switches = [(on, xy) for t, on, xy in safe_switches(activity) if t == name]
        require(len(switches) == 1, f"{name}：开关不唯一")
        on, (x, y) = switches[0]
        if not on:
            print(f"  · {name} 已关闭", flush=True)
            continue
        require(not any(n.get("checkable") == "true" and n.get("enabled") == "false"
                        and p.on_screen(n) and (lambda b: b[0] <= x <= b[2] and b[1] <= y <= b[3])
                        (__import__("fast").bounds(n)) for n in p.tree().iter("node")),
                f"{name}：开关不可操作")
        p.click(x, y)
        time.sleep(.8)
        require(not p.locked(), "手机锁屏，请机主解锁")
        require(p.focus() == activity, "点击后页面变化，停止本段")
        root = p.tree()
        assert_no_other_window(root, activity.split("/", 1)[0])
        texts = p.texts(root)
        titles = [t for t, _, _ in texts if "确定关闭" in t and name in t]
        confirmations = [(b, n) for t, b, n in texts if t == "确定" and "Button" in (n.get("class") or "")]
        if titles:
            require(len(confirmations) == 1, f"{name}：关闭确认框无法识别")
            b, _ = confirmations[0]
            require(0 <= (b[0] + b[2]) // 2 < p.W and 0 <= (b[1] + b[3]) // 2 < p.H,
                    "确认按钮不在屏幕内，停止")
            p.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
            time.sleep(.8)
        else:
            require(not confirmations, "出现无法识别的确认框，停止")
        require(p.focus() == activity, "确认后页面变化，停止")
        after_list = safe_switches(activity)
        after = {t: on for t, on, _ in after_list}
        require(sum(1 for t, _, _ in after_list if t == name) == 1 and after.get(name) is False,
                f"{name}：回读未确认关闭")
        require(all(after.get(t) == state for t, state in baseline.items() if t not in names),
                f"{page}：其他开关状态变化，请手动核对")
        p.changed.append((page, name))
        print(f"  关 {name}（已回读）", flush=True)


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


print(f"\n已调整 {len(p.changed)} 项；未完成步骤 {len(FAILED_STEPS)} 个。", flush=True)
print("通知渠道、广告包、快应用按标准流程另行处理。", flush=True)
