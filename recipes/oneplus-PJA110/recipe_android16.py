# 一加 Ace 2 Pro（PJA110），ColorOS 16 / Android 16。路径取自同代系统在 Ace 2 与 OPPO 机型上已实测的公开入口，PJA110_16.0.5.1201 上尚未整段验证。
from recipe_kit import step
# 仅覆盖下拉搜索、商店、浏览器；广告跟踪、负一屏、主题、视频、游戏中心不在本脚本内。
BUILD = "PJA110_16.0.5.1201"
# 家族库按这些常量选走法（#1245），缺省档见 tool/recipe_nav.py。
OPEN_SETTINGS_STYLE = "shell"
CLOSE_NAMED_STYLE = "vanish"
import time
# 回读确认数由引擎经 rt 记录
# 录自 ColorOS 14 的商店服务管理，不扩成 PHK110 的 26 项：改名或下架的项跳过，一项都不认识算段失败。
PROMOTIONS = ["首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
              "游戏详情页：游戏活动卡片", "软件专区：福利"]
# 两个 App 都认这条公开设置 Intent：绕开含账号信息的「我的」页，不再连点三下。
SETTINGS_INTENT = "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p {}"
SETTINGS_REFUSED = ("Error", "Exception", "Permission Denial")
# SearchSettingActivity 未导出，只有它自己的 scheme 能直接落地（PLP120 / PLG110 / PMX110 实测）。
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
SEARCH_TITLES = ("搜索范围", "首页卡片管理", "功能管理", "账号与隐私")


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

def tail():
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, require, require_switches, rt
    from recipe_nav import close_named, enter_privacy, open_settings, read_switches, search_settings_ready
