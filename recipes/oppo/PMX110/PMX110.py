# OPPO Find X10 Pro Max（PMX110，ColorOS 17）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 只剩广告跟踪：要用菜单「全部关闭」整表关并恢复「显示系统应用」偏好，是状态机。其余八段是数据。
from collections import namedtuple

import adb_link
from fast import ScreenLocked, bounds

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, page, require, rt, skip
    from recipe_nav import ad_id_page, app_settings, browser_settings, menu_state, more_menu, read_switches, row
    from recipe_strategies import close_all_listed, close_named_optional

BUILD = "PMX110_17.0.0"
# 浏览器设置页的包名：入口只属于这台机，家族库按这个名字拼拉起命令（#1245）。
BROWSER_PKG = "com.heytap.browser"

MenuState = namedtuple("MenuState", "close_all_disabled system_apps_shown")
# 分段结果由引擎经 rt 记录
SKIPPED_ITEMS = []
# 回读确认数由引擎经 rt 记录

SEARCH = "com.heytap.quicksearchbox"
MARKET = "com.heytap.market"
THEME = "com.heytap.themestore"
VIDEO = "com.heytap.yoli"
GAME = "com.nearme.gamecenter"
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
SEARCH_CARDS = ["未下载应用推荐", "应用建议小卡", "热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"]
# 轮播单选只有这两个选项，「不显示」是我们要的那一档（#280）。
CAROUSEL_LABELS = {"显示轮播推荐", "不显示轮播推荐"}
CAROUSEL_OFF = "不显示轮播推荐"
# 负一屏首页的两条已知文案（PLG110 / PMA110 实测）：头像入口万一改名，两条都在也算到了（#901）
LAUNCHER = "com.android.launcher/"
ASSISTANT_HOME = {"我的服务", "添加卡片"}


def require_installed(package, label):
    """没装的包 `pm path` 输出为空，退出码是 1（adb shell v2 带回）或 0（不带回退出码的通道）：
    那是「没装」，跳过本段，不算读不出（#899）。有报错文字或别的退出码才算读不出。"""
    result = p.d.shell("pm path " + package)
    if "package:" in result.output:
        return
    require(result.exit_code in (0, 1) and not result.output.strip(), f"无法读取{label}安装状态")
    skip(f"本机未安装{label}")


def _labelled(text, name):
    """读屏会把状态后缀并进同一段文字（「全部关闭 - 已停用」），按主语认。"""
    rest = text[len(name):]
    return text.startswith(name) and (not rest or rest[0] in " ,，、-")


def step_ad_tracking(p, rt):
    # 每个应用一个开关。用菜单「全部关闭」整表关，再看它是否置灰来确认（#650）：
    # 以前逐行读整个列表（547 个具名项）两遍，约 27 分钟；现在不用滚动列表，个人应用名单也不必读出来。
    # 版本由引擎判（录制版本对不上会置 safe_mode）；这里只挡「拿这份脚本去跑别的型号」。
    if p.safe_mode or p.d.shell("getprop ro.product.model").output.strip() != "PMX110":
        skip("仅在 PMX110 上批量处理广告跟踪")
    ad_id_page()
    row("广告跟踪", activity="OAIDActivity")
    state = menu_state()
    p.back()
    close_all_listed("系统应用已显示" if state.system_apps_shown else "用户应用")
    if not state.system_apps_shown:
        more_menu()
        require(p.tap("显示系统应用", scrolls=0), "未能显示系统应用")
        p.await_page()
        page("广告跟踪", activity="OAIDActivity")
        try:
            close_all_listed("含系统应用")
        finally:
            more_menu()                       # 显示方式恢复原样，不改机主的列表偏好
            if not p.tap("隐藏系统应用", scrolls=0):
                p.back()
                print("  · 没找到「隐藏系统应用」，列表保持显示系统应用", flush=True)
            p.await_page()


def tail():
    print(f"\n逐项回读确认 {rt.verified} 项；完成 {sum(state == '完成' for _, state in rt.results)} 段，"
          f"跳过 {sum(state == '跳过' for _, state in rt.results)} 段，未显示项 {len(SKIPPED_ITEMS)} 组", flush=True)


# 负一屏 / 主题 / 视频 / 游戏中心的段体按 `g["close_named"]` 取这个钩子，实现住在
# recipe_strategies 的 `close_named_optional`，这里绑回旧名字（#1253）。
close_named = close_named_optional
