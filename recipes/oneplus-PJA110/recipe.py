# 一加 Ace 2 Pro，ColorOS 14.0.0.812 / Android 14，路径来自 2026-10-25 实测。仅覆盖下拉搜索、商店、浏览器；本机联网后验证 9 项，失败会回读并返回非零。
from recipe_kit import step
# 不代表系统广告跟踪、负一屏、主题、视频等均已适配。
BUILD = "PJA110_14.0.0.812"
# 家族库按这些常量选走法（#1245），缺省档见 tool/recipe_nav.py。
CLOSE_NAMED_STYLE = "basic"
# 旧版应用切到「我的」后首下设置点击会被动画吞掉：走「我的 → 设置」并按前台回读（沿用 #286）。
APP_SETTINGS_STYLE = "launch"
import time
# 回读确认数由引擎经 rt 记录
PROMOTIONS = ["首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
              "游戏详情页：游戏活动卡片", "软件专区：福利"]
# 浏览器使用实机解析出的公开入口；商店沿用先停止、再从桌面启动，避免复用旧子页。
START_ACTIVITIES = {"com.heytap.browser": "com.android.browser.BrowserActivity"}


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

def tail():
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, require, require_switches, rt
    from recipe_nav import app_settings, close_named, read_switches, tap
