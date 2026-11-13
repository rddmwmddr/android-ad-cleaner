# 魅族 21 Pro 的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。共享库的
# wait_page/goto/close_named/tap_text 仍由装载器注入执行作用域，这些函数按模块全局名取用。
# 只有「浏览器」一段的整段是例外（页面文字分支 + 首页样式切换，属本机 UI 流程），走 step_browser。
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import time
    from recipe_kit import p, require, rt
    from recipe_nav import close_named, goto, tap_text, wait_page

BUILD = "Flyme 12.6.0.0A"
MODELS = ["MEIZU 21 Pro"]
TARGET_PACKAGE = ""


def page_summary():
    """失败时的页面结构：只报 Activity 与计数，不带页面文字，也不截屏（账号页不外泄）。"""
    from row import summary
    try:
        root = p.tree()
        bottom = sum(1 for _text, (_l, top, _r, bottom_edge), _node in p.texts(root)
                     if (top + bottom_edge) // 2 >= p.H * .85)
        return f"当前页 {p.focus() or '未知'}；{summary(root, p.W, p.H)}；底栏 {bottom} 条"
    except Exception:
        return "当前页面结构读取失败"


def guard():
    # 安全模式下不因型号拒跑；否则比对机型与版本。
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


def tail():
    print(f"\n已调整 {len(p.changed)} 项；未完成步骤 {len(rt.failed_steps)} 个。", flush=True)
    print("通知渠道、广告包、快应用按标准流程另行处理。", flush=True)


def step_browser(p, rt):
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
