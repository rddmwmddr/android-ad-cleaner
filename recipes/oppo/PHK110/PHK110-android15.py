# 一加 Ace 2（PHK110），Android 15 的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 navigate / open_settings 与 require / skip 由装载器注入执行作用域。
# 浏览器首页要读回主页布局并写改动台账（p.changed），数据表达不了，逐字保留原实现。


import recipe_nav as nav
BUILD = "PHK110_15.0.0.601(CN01)"

# 家族库的 `page_activity` 与 recipe_kit 注入的 `page()` 同名不同签名，绑回旧名字给段体用。


def guard(p, rt):
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PHK110" or not build.startswith(BUILD):
        rt.skip("型号或系统版本不匹配，跳过")


def browser(p, rt):
    return nav.open_settings(p, rt, "com.heytap.browser", "BrowserPreferencesPage", "浏览器")


def step_browser_home(p, rt):
    if not browser(p, rt) or not nav.navigate(p, rt, "主页设置", "BrowserPreferenceActivity", "主页设置"):
        return False
    if p.find("简洁", exact=True):
        return True
    if not nav.navigate(p, rt, "页面布局", "BrowserPreferenceActivity", "页面布局"):
        return False
    if not p.tap("简洁", exact=True, scrolls=0):
        return False
    p.back()
    if not nav.page_activity(p, rt, "BrowserPreferenceActivity", "主页设置") or not p.find("简洁", exact=True):
        return False
    p.changed.append(("浏览器主页", "默认 → 简洁"))
    return True


def tail(p, rt):
    print("\n负一屏、主题、系统广告跟踪：请按本机实测记录手动核对。视频和小游戏未自动处理。")
    print("通知渠道、广告包和快应用按独立流程处理，挂起须机主同意。")
    print("分段结果：", rt.results)
