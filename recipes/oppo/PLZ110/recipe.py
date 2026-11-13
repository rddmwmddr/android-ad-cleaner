# 一加 15T（PLZ110），2026-11-08 真机核对。系统 PLZ110_17.0.0.107(CN01) / Android 17；仅记录本机走通的路径。
from recipe_kit import step
# 浏览器原已停用，跳过且不启用；系统广告跟踪未验证，不纳入本脚本。
# 通知渠道、广告组件及快应用仍由 run.py 独立确认。
# 2026-11-10 负一屏入口改从内侧右滑、已在负一屏不再滑走、认不到入口时留页面现场（#901），未复测。
# 软件商店隐私入口接受「隐私」与「隐私授权管理」两种叫法，按落在商店隐私页判，未复测（#907）。
BUILD = "PLZ110_17.0.0.107(CN01)"
# 家族库按这些常量选走法（#1245），缺省档见 tool/recipe_nav.py。
READ_SWITCHES_STYLE = "title"
HIDE_CAROUSEL_STYLE = "labels"
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
import adb_link
from fast import ScreenLocked, bounds


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
# 轮播单选只有这两个选项，「不显示」是我们要的那一档（沿用 #280 的做法）。
CAROUSEL_LABELS = {"显示轮播推荐", "不显示轮播推荐"}
CAROUSEL_OFF = "不显示轮播推荐"
# 来自本机服务管理页；普通游戏分类、AI 搜索、资产、客服、工具与安全功能不在清单里。
STORE_PROMOS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "应用安全安全内容推荐", "游戏专区：重磅更新卡片", "游戏详情页：游戏活动卡片",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：账号会员徽章", "我的专区：应用时刻", "我的专区：积分商城",
    "我的专区：休闲一刻", "我的专区：安装有礼", "我的专区：福利中心", "我的专区：游戏VIP",
    "我的专区：金豆乐园", "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动",
    "游戏详情页：游戏礼包", "手机管家：应用推荐", "文件管理：应用推荐", "游戏专区：活动集合",
    "详情页：限时活动", "小游戏二楼和专区", "福利专区",
]


def require_installed(package, label):
    """没装的包 `pm path` 输出为空，退出码是 1（adb shell v2 带回）或 0（不带回退出码的通道）：
    那是「没装」，跳过本段，不算读不出（#899）。有报错文字或别的退出码才算读不出。"""
    result = p.d.shell("pm path " + package)
    if "package:" in result.output:
        return
    require(result.exit_code in (0, 1) and not result.output.strip(), f"无法读取{label}安装状态")
    raise SkipStep(f"本机未安装{label}")


@step("软件商店")
def _():
    app_settings(MARKET)
    # 本版商店叫「隐私授权管理」，同族另有叫「隐私」的（#907）。tries 保住原来 p.enter 的
    # 「点击被弹窗动画吞掉就再点」：这一行必须点开，后面的行都指着它（#286）。
    row(("隐私", "隐私授权管理"), package=MARKET, activity="PrivacyActivity", tries=3)
    row("个性化推荐", package=MARKET, activity="PersonalRecommendActivity")
    close_named(["个性化推荐"], "个性化推荐")
    app_settings(MARKET)
    row("服务管理")
    available = read_switches("服务管理")
    names = [name for name in STORE_PROMOS if name in available]
    require(names, "服务管理未识别到已录制推广位")
    close_named(names, "服务管理", snapshot=available)


@step("下拉搜索")
def _():
    search_settings_direct()


# 下面两个名字给注入面的负一屏助手取（at_assistant / assistant_icon 跑在 recipe_nav 里）
LAUNCHER = "com.android.launcher/"
# 负一屏首页的两条已知文案（PLG110 / PMA110 实测）：头像入口万一改名，两条都在也算到了（#901）
ASSISTANT_HOME = {"我的服务", "添加卡片"}


@step("负一屏")
def _():
    assistant_screen()


@step("主题")
def _():
    theme_store_settings()


@step("视频")
def _():
    video_direct()


@step("游戏中心")
def _():
    game_center_direct()


@step("小布建议")
def _():
    assistant_advice_rows()


def tail():
    print(f"\n逐项回读确认 {rt.verified} 项；完成 {sum(state == '完成' for _, state in rt.results)} 段，"
          f"跳过 {sum(state == '跳过' for _, state in rt.results)} 段，未显示项 {len(SKIPPED_ITEMS)} 组", flush=True)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import SkipStep, p, page, require, require_switches, rt
    from recipe_nav import app_settings, hide_carousel, read_switches, row, switch_signature, switch_top
    from recipe_strategies import close_named_optional
    from recipe_steps import assistant_advice_rows, assistant_screen, game_center_direct, search_settings_direct, theme_store_settings, video_direct

# 负一屏 / 主题 / 视频 / 游戏中心的段体按 `g["close_named"]` 取这个钩子，实现住在
# recipe_strategies 的 `close_named_optional`，这里绑回旧名字（#1253）。
close_named = close_named_optional
