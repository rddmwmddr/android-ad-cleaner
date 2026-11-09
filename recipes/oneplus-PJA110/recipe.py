# 一加 Ace 2 Pro，ColorOS 14.0.0.812 / Android 14，路径来自 2026-10-25 实测。
# 仅覆盖下拉搜索、商店、浏览器；本机联网后验证 9 项，失败会回读并返回非零。
# 不代表系统广告跟踪、负一屏、主题、视频等均已适配。
BUILD = "PJA110_14.0.0.812"
import time
VERIFIED_SWITCHES = 0
PROMOTIONS = ["首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
              "游戏详情页：游戏活动卡片", "软件专区：福利"]
# 浏览器使用实机解析出的公开入口；商店沿用先停止、再从桌面启动，避免复用旧子页。
START_ACTIVITIES = {"com.heytap.browser": "com.android.browser.BrowserActivity"}


def tap(name, scrolls=4):
    require(p.tap(name, exact=True, scrolls=scrolls), f"未找到入口「{name}」")


def app_settings(package, activity):
    if p.focus() == f"{package}/{activity}":
        return
    p.start(package, activity=START_ACTIVITIES.get(package))
    require(p.go("我的", "设置"), "未进入包含设置按钮的「我的」页")
    # 旧版应用切换到「我的」后，首下设置点击可能被动画吞掉；按实际前台回读。
    for _ in range(3):
        require(p.focus().split("/", 1)[0] == package, "应用已离开前台，停止本段")
        if p.focus() == f"{package}/{activity}":
            return
        tap("设置", scrolls=0)
        time.sleep(.4)
    require(p.focus() == f"{package}/{activity}", "设置页未打开，停止本段")


def read_switches(max_screens):
    current = {}
    for index in range(max_screens):
        current.update({title: on for title, on, _ in p.switches()})
        if index + 1 == max_screens or not p.scroll_more():
            break
    return current


def close_named(names, page, max_screens=1):
    global VERIFIED_SWITCHES
    p.top(max_screens)
    before = read_switches(max_screens)
    require_switches(before, names, page)
    p.top(max_screens)
    p.off(only=names, page=page, max_screens=max_screens)
    p.top(max_screens)
    current = read_switches(max_screens)
    require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
    require(all(current.get(name) == state for name, state in before.items() if name not in names),
            f"{page}：其他开关状态变化，请核对")
    VERIFIED_SWITCHES += len(names)


@step("下拉搜索")
def _():
    p.d.shell("input keyevent HOME"); time.sleep(.6)
    p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); time.sleep(1)
    p.d.shell("input keyevent BACK"); time.sleep(.4)
    require(p.focus().split("/", 1)[0] == "com.heytap.quicksearchbox", "未进入下拉搜索")
    tap("设置")
    tap("账号与隐私")
    tap("隐私")
    close_named(["个性化推荐"], "下拉搜索·隐私")


@step("软件商店")
def _():
    app_settings("com.heytap.market", "com.heytap.market.mine.ui.SettingActivity")
    tap("隐私")
    tap("个性化推荐")  # 此版本是二级页，不是隐私页上的开关
    close_named(["个性化推荐"], "商店·个性化推荐")


@step("商店推广位")
def _():
    # 紧接隐私段时沿原路返回，避免旧系统连续强停、重启同一个商店导致启动超时。
    if p.focus() == "com.heytap.market/com.heytap.market.mine.PersonalRecommendActivity":
        p.back(2)
    app_settings("com.heytap.market", "com.heytap.market.mine.ui.SettingActivity")
    tap("服务管理")
    close_named(PROMOTIONS, "商店·推广位", max_screens=6)  # 联网后列表变长；只动这六项


@step("浏览器")
def _():
    app_settings("com.heytap.browser", "com.heytap.browser.settings.component.BrowserPreferencesPage")
    tap("隐私")
    close_named(["个性化推荐"], "浏览器·隐私")

print(f"\n已回读确认 {VERIFIED_SWITCHES} 项；未完成步骤 {len(FAILED_STEPS)} 个", flush=True)
