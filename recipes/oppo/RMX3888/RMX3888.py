# realme 真我 GT5 Pro（RMX3888，ColorOS 15）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 剩五段在这里：负一屏（滑动状态机）、软件商店（多层嵌套 + 无 `require_tap`）、主题（try/except 只认
# 「无法打开」）、视频（`require(p.tap)` 的报错出口）、游戏中心（`tap_icon` + 复合条件）。其余四段已落数据。
import time

import adb_link
from fast import ScreenLocked
import recipe_nav as nav
from recipe_runtime import SkipStep


BUILD = "RMX3888_15.0.0.420"
MODELS = ["RMX3888"]

SETTINGS = "com.android.settings"
MARKET = "com.heytap.market"
BROWSER = "com.heytap.browser"
THEME = "com.oplus.themestore"
VIDEO = "com.heytap.yoli"
GAME = "com.nearme.gamecenter"
SEARCH = "com.heytap.quicksearchbox"
# SearchSettingActivity 没导出（`am start -n` 会被系统拒绝），只能走应用自己的 scheme。
# 前提是 com.heytap.quicksearchbox 没被挂起：一挂，这个 scheme 落到系统的「应用已被暂停」页。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 搜索范围：只关推荐位。「榜单」「小红书」「购物」「小说」「视频」是内容源，「本机应用」「设置」
# 这类是数据源，关掉会搜不到东西。
SEARCH_SOURCES = ["个性化推荐", "精选资讯"]
# 商店「服务管理」里只保留功能项，其余推广入口全关（本机 46 项）。
STORE_KEEP = ["帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：存储空间清理",
              "我的专区：我的资产", "我的专区：安全守护", "我的专区：小i客服",
              "应用使用记录", "首页：AI搜索"]


def step_negative_screen(p, rt):
    # 本机这一层没有「推荐服务 → 轮播推荐」，也没有「搜索框提示词」：两处默认已关，没有可关的项。
    p.d.shell("input keyevent HOME"); time.sleep(0.6)
    p.d.shell("input keyevent HOME"); time.sleep(0.6)
    entered = False
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
        if "assistantscreen" in p.focus():
            entered = True
            break
    if not entered:
        raise RuntimeError("右滑没进负一屏（速览），本段没做成")
    if not nav.maybe(p, rt, "我的") and not nav.maybe(p, rt, "头像"):
        raise RuntimeError("负一屏里没找到「我的」或头像入口")
    if not p.tap("设置", exact=True, scrolls=0):
        raise RuntimeError("负一屏没有设置入口")
    if not p.in_settings_page():
        raise RuntimeError("负一屏的设置页没有打开")
    has_tips = nav.has_row(p, rt, "搜索框提示词")
    has_service = nav.has_row(p, rt, "推荐服务")
    if not (has_tips or has_service):
        p.back(2)
        rt.skip("本机这一层没有「推荐服务」与「搜索框提示词」，没有可关的推荐位")
    p.top(3)                 # 探测时翻过页；关开关要从页顶往下读
    if has_tips:
        p.off(only=["搜索框提示词"], page="负一屏")
    # 「推荐服务」总开关不能拨：会删掉天气、步数、清理卡片。它在这一族机型上是点开子页的入口行；
    # 万一某版把它做成开关行，就一个字都不动，留给机主手动关轮播。
    if has_service:
        if any(title == "推荐服务" for title, _, _ in p.switches()):
            print("  · 「推荐服务」在本机是开关行，按约定不拨（会删掉天气、步数、清理卡片）；"
                  "轮播推荐需手动关", flush=True)
        elif p.tap("推荐服务", exact=True):
            if p.tap("轮播推荐", exact=True):
                p.tap("不显示", exact=True, scrolls=0)
            else:
                print("  · 「推荐服务」下没有「轮播推荐」", flush=True)
            p.back()
    p.back(2)


def step_store(p, rt):
    p.start(MARKET)
    if not p.tab("我的"):
        raise RuntimeError("商店里没找到底部「我的」")
    time.sleep(1.0)
    if not p.tap("设置", exact=True, scrolls=0):
        raise RuntimeError("商店「我的」页没找到「设置」")
    rt.page("设置", MARKET, "SettingActivity")
    if p.tap("服务管理", exact=True):
        p.off(keep=STORE_KEEP, page="商店·服务管理")
        p.back()
    # 个性化推荐是入口行，开关在下一层的 PersonalRecommendActivity，不是就地开关。
    if nav.store_privacy(p, rt):
        if p.tap("个性化推荐", exact=True):
            rt.page("个性化推荐", MARKET, "PersonalRecommendActivity")
            p.off(only=["个性化推荐"], page="商店·个性化推荐")
            p.back()
        else:
            print("  · 隐私页没有「个性化推荐」入口", flush=True)
        p.back(2)
    else:
        p.note_miss("隐私")
        print("  · 商店里没找到「隐私 / 隐私授权管理」", flush=True)
    p.back(2)


def step_theme(p, rt):
    # 包名不是同族的 com.heytap.themestore，而且没有启动界面：resolve-activity 返回
    # No activity found，拉起命令只会报「无法打开」。本机这一段做不了，按跳过收尾。
    try:
        p.start(THEME)
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError as error:
        if "无法打开" not in str(error):
            raise
        rt.skip(f"主题商店（{THEME}）没有启动界面，本机做不了这一段")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("服务管理", exact=True):
        if p.tap("消息与广告", exact=True):
            # 消息通知是服务通知，保留；只关开屏广告。
            p.off(only=["开屏广告"], page="主题·消息与广告")
            p.back()
        p.back()
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="主题·个性化推荐")
        p.back()
    p.back(2)


def step_game_center(p, rt):
    # 本机未安装：p.start 抛 MissingPackage，段包装按跳过记账。装上之后走同族旧版路径。
    p.start(GAME)
    if not p.tab("我的"):
        raise RuntimeError("游戏中心没找到底部「我的」")
    time.sleep(1.0)
    if not p.tap("设置", exact=True, scrolls=0) and not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("游戏中心没找到设置入口")
    if p.tap("隐私开关设置", exact=True) and p.tap("个性化推荐管理", exact=True):
        p.off(only=["个性化推荐"], page="游戏中心·个性化推荐管理")
    p.back(4)
