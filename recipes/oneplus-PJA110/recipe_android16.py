# 一加 Ace 2 Pro（PJA110），ColorOS 16 / Android 16。
# 路径取自同代系统在 Ace 2 与 OPPO 机型上已实测的公开入口，PJA110_16.0.5.1201 上尚未整段验证。
# 仅覆盖下拉搜索、商店、浏览器；广告跟踪、负一屏、主题、视频、游戏中心不在本脚本内。
BUILD = "PJA110_16.0.5.1201"
import time
VERIFIED_SWITCHES = 0
# 录自 ColorOS 14 的商店服务管理，不扩成 PHK110 的 26 项：改名或下架的项跳过，一项都不认识算段失败。
PROMOTIONS = ["首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
              "游戏详情页：游戏活动卡片", "软件专区：福利"]
# 两个 App 都认这条公开设置 Intent：绕开含账号信息的「我的」页，不再连点三下。
SETTINGS_INTENT = "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p {}"
SETTINGS_REFUSED = ("Error", "Exception", "Permission Denial")
# SearchSettingActivity 未导出，只有它自己的 scheme 能直接落地（PLP120 / PLG110 / PMX110 实测）。
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
SEARCH_TITLES = ("搜索范围", "首页卡片管理", "功能管理", "账号与隐私")


def open_settings(package, activity, title):
    """公开设置 Intent 直达 App 设置页，核对前台 Activity 与页标题。"""
    result = p.d.shell(SETTINGS_INTENT.format(package))
    require(not result.exit_code and not any(m in result.output for m in SETTINGS_REFUSED),
            f"{package}：系统不允许直达设置，未操作（{result.output.strip()[-200:]}）")
    require(p.expect_page(title), f"{package}：设置页未打开；{p.page_evidence()}")
    landed = p.focus()
    require(landed.endswith(activity), f"{package}：没落在设置页（停在 {landed}）；{p.page_evidence()}")


def enter_privacy():
    """商店的隐私入口随商店 App 版本叫「隐私」或「隐私授权管理」，两个 COS16 机型各是一种（#907）。"""
    for name in ("隐私", "隐私授权管理"):
        try:
            p.enter(name, scrolls=4)
            return
        except RuntimeError as error:
            if not any(mark in str(error) for mark in ("未找到入口", "页面没有变化")):
                raise
    raise RuntimeError(f"没找到商店的隐私入口；{p.page_evidence()}")


def read_switches(max_screens):
    current = {}
    for index in range(max_screens):
        current.update({title: on for title, on, _ in p.switches()})
        if index + 1 == max_screens or not p.scroll_more():
            break
    return current


def close_named(names, page, max_screens=1, snapshot=None):
    """关掉点名的开关，并核对其他开关未变。`snapshot` 是调用方已经读过的那一页，免得再翻一遍。"""
    global VERIFIED_SWITCHES
    if snapshot is None:
        p.top(max_screens)
        snapshot = read_switches(max_screens)
    require_switches(snapshot, names, page)
    others = set(snapshot) - set(names)
    where = p.focus()
    p.top(max_screens)
    p.off(only=names, page=page, max_screens=max_screens)
    p.top(max_screens)
    after = read_switches(max_screens)
    for name in names:
        if after.get(name) is False:
            continue
        # 关掉后整行从列表里消失也算已关（引擎回读的 VANISHED）：同页还有别的行、且没换页才算；
        # 整页读空或换成新页时读屏失败，不能当成关闭成功。
        require(after.get(name) is None and others & set(after) and p.focus() == where,
                f"{page}：回读未确认关闭「{name}」")
    require(all(after.get(name) == state for name, state in snapshot.items() if name in others),
            f"{page}：其他开关状态变化，请核对")
    VERIFIED_SWITCHES += len(names)


def search_settings_ready(timeout=6):
    """搜索设置页认得出：前台是 quicksearchbox 的设置 Activity，且页面标题是那几组之一。"""
    from wait import until

    def sample():
        return "Setting" in p.focus() and any(t in SEARCH_TITLES for t, _, _ in p.texts())

    return bool(until(sample, timeout=timeout, poll=0.2, same=2, now=time.monotonic, sleep=time.sleep))


@step("下拉搜索")
def _():
    # 桌面下滑手势在 adb 下不稳；scheme 不通时退回搜索首页底部的「设置」，不碰手势。
    p.d.shell(SEARCH_SETTINGS)
    if not search_settings_ready():
        print("  · scheme 没落到搜索设置页，改点搜索首页底部的「设置」", flush=True)
        p.start("com.heytap.quicksearchbox", ".ui.activity.SearchHomeActivity")
        cands = [((l + r) // 2, (tp + b) // 2) for t, (l, tp, r, b), _ in p.texts()
                 if t == "设置" and tp > p.H * 0.8]
        require(cands, f"搜索首页底部没有「设置」；{p.page_evidence()}")
        before = p.sig()
        p.click(*cands[-1])
        p.settle(before, 1.5)
        require(search_settings_ready(), f"没进全局搜索设置页；{p.page_evidence()}")
    p.enter("账号与隐私", scrolls=4)
    p.enter("隐私", scrolls=4)
    close_named(["个性化推荐"], "下拉搜索·隐私")


@step("软件商店")
def _():
    open_settings("com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity", "应用与服务")
    enter_privacy()
    p.enter("个性化推荐", scrolls=4)   # 此版本是二级页，不是隐私页上的开关
    close_named(["个性化推荐"], "商店·个性化推荐")


@step("商店推广位")
def _():
    open_settings("com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity", "应用与服务")
    p.enter("服务管理", scrolls=4)
    page = read_switches(6)
    missing = [name for name in PROMOTIONS if name not in page]
    if missing:
        print(f"  · 商店·推广位：本次未显示 {'、'.join(missing)}，不计为已关闭", flush=True)
    close_named([name for name in PROMOTIONS if name in page], "商店·推广位", max_screens=6, snapshot=page)


@step("浏览器")
def _():
    open_settings("com.heytap.browser",
                  "com.heytap.browser.settings.component.BrowserPreferencesPage", "浏览器")
    p.enter("隐私", scrolls=4)
    p.enter("个性化管理", scrolls=4)
    close_named(["个性化优惠推荐", "个性化广告推荐"], "浏览器·个性化管理")

print(f"\n已回读确认 {VERIFIED_SWITCHES} 项；未完成步骤 {len(FAILED_STEPS)} 个", flush=True)
