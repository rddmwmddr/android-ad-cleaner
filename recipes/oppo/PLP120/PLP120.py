# OPPO Find N6（PLP120，ColorOS 16 / 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 settings_page / search_settings / enter_settings / game_settings_direct / game_settings_via_mine /
# open_switch_page / page / read_on_page 与 require_switches / skip_in_safe_mode 由装载器注入执行作用域。
# 九段都留在这里：小布建议改成点「资讯服务」进二级页再关（旧「内容资讯」列表页兜底），游戏中心先试
# APP_SETTINGS 直达设置页（「我的 → 设置」兜底）。两条路径都取自同族真机实测（PMX110 / PKT110）。
import time

import adb_link
from fast import ScreenLocked

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import SkipStep, p, page, require_switches, skip_in_safe_mode
    from recipe_nav import enter_settings, game_settings_direct, game_settings_entry, game_settings_via_mine
    from recipe_nav import open_switch_page, search_settings, settings_page, wait_search_settings
    from recipe_strategies import read_on_page

BUILD = "PLP120_16.0.9"

GAME = "com.nearme.gamecenter"
SETTINGS = "com.android.settings"


def step_ad_tracking(p, rt):
    # 每个 App 一个开关、没有总开关；新装的 App 默认开。ColorOS 17 首页改叫「隐私与安全」（#165 社区实测）
    skip_in_safe_mode()
    found = settings_page("隐私", "设备标识与广告", "广告跟踪")
    if not found:
        p.miss = 0
        found = settings_page("隐私与安全", "设备标识与广告", "广告跟踪")
    if found:
        p.off(page="广告跟踪")


def step_negative_screen(p, rt):
    p.d.shell("input keyevent HOME"); time.sleep(0.6); p.d.shell("input keyevent HOME"); time.sleep(0.6)
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
        if "assistantscreen" in p.focus():
            break
    # 左上头像 → 设置
    av = [n for n in p.tree().iter("node") if "头像" in (n.get("content-desc") or "") + (n.get("text") or "")]
    if av:
        from fast import bounds
        l, t, r, b = bounds(av[0]); p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
    p.tap("设置", exact=True, scrolls=0)
    p.off(only=["搜索框提示词"], page="负一屏")
    # ⚠ 「推荐服务」总开关不要关：会删掉天气/步数/清理卡片
    if p.tap("推荐服务", exact=True):
        if p.tap("轮播推荐", exact=True):
            p.tap("不显示", exact=True, scrolls=0)
            p.back()
        p.back()
    p.back(2)


SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 设置页上的标题；搜索首页也有「搜索范围」这类文字，所以还要看前台 Activity（SearchSettingActivity）。
SEARCH_TITLES = {"搜索范围", "功能管理", "搜索引擎", "消息管理", "账号与隐私"}


def search_sources():
    """借给别的机型（安全模式）时只关推荐位：ColorOS 17 上榜单 / 小说 / 购物是内容源，关掉会搜不到东西。"""
    if p.safe_mode:
        return ["个性化推荐", "精选资讯"]
    return ["榜单", "小说", "购物", "个性化推荐", "精选资讯"]


def step_search(p, rt):
    if not search_settings():
        print("  · 跳过：没有认出全局搜索设置页（入口不可用或被系统限制）", flush=True)
        return
    if p.tap("搜索范围", exact=True):
        p.off(only=search_sources(), page="下拉搜索·搜索范围")
        p.back()
    if p.tap("功能管理", exact=True):
        p.off(only=["搜索框提示词"], page="下拉搜索·功能管理")
        p.back()
    p.miss = 0
    if not p.tap("账号与隐私", exact=True):
        p.miss = 0                     # ColorOS 17：「账号与隐私」只是分组标题，直接找「隐私」
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="下拉搜索·隐私")
        p.back(2)
    p.back(2)


STORE_KEEP = ["帮助与客服", "应用安全", "应用工具", "存储空间清理", "我的资产", "安全守护",
              "小i客服", "应用使用记录", "首页 AI 搜索", "自动检测风险应用"]


def step_store(p, rt):
    p.start("com.heytap.market")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="商店·隐私")
        p.back()
    if p.tap("服务管理", exact=True):
        p.off(keep=STORE_KEEP, page="商店·服务管理")
        p.back()
    p.back(2)


def step_browser(p, rt):
    p.start("com.heytap.browser")
    if p.find("我的", exact=True, edge_ok="tab"):          # X9 Ultra：底部「我的」→ 设置
        p.go("我的", "设置"); p.tap("设置", exact=True, scrolls=0)
    elif p.find("菜单") or p.find("更多"):                 # Find N6：底部 ☰ → 齿轮
        p.tap("菜单", scrolls=0) or p.tap("更多", scrolls=0)
        p.tap("设置", scrolls=0)
    else:
        # 首页切成「简洁」后没有「我的」和菜单（ColorOS 17，#165）：浏览器在前台时直达设置页；带清栈参数会立刻退出
        p.d.shell("am start -n com.heytap.browser/.settings.component.BrowserPreferencesPage"); time.sleep(1.2)
        if "com.heytap.browser" not in p.focus():
            print("  ✗ 浏览器设置页没有打开"); return
    if p.tap("主页设置", exact=True):
        if p.tap("页面布局", exact=True):
            p.tap("简洁", exact=True, scrolls=0); p.back()
        p.back()
    if p.tap("隐私", exact=True) and p.tap("广告管理", exact=True):
        p.off(only=["开屏广告", "资讯列表广告", "摇一摇"], page="浏览器·广告管理")
        p.back(2)
    p.back(2)


def step_theme(p, rt):
    p.start("com.heytap.themestore")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("服务管理", exact=True) and p.tap("消息与广告", exact=True):
        p.off(only=["消息通知", "开屏广告"], page="主题·消息与广告")
        p.back(2)
    if p.tap("隐私", exact=True) and p.tap("个性化推荐设置", exact=True):
        p.off(only=["个性化推荐"], page="主题·个性化推荐")
        p.back(2)
    p.back(2)


def step_video(p, rt):
    p.start("com.heytap.yoli")
    p.go("我的", "设置")
    p.tap("设置", exact=True)
    if p.tap("个性化内容管理", exact=True):
        p.off(only=["个性化推荐"], page="视频·个性化")
    p.back(3)


def step_game_center(p, rt):
    direct = game_settings_direct()
    if not direct:
        game_settings_via_mine()
    p.enter("隐私开关设置", scrolls=6)
    p.enter("个性化推荐管理", scrolls=4)
    require_switches(read_on_page("个性化推荐管理", GAME), ["个性化推荐"], "个性化推荐管理")
    p.off(only=["个性化推荐"], page="游戏中心·个性化推荐")
    p.back(3 if direct else 4)


def step_assistant_advice(p, rt):
    # ColorOS 17：「内容资讯」是点不动的分组标题，入口是它下面那行「资讯服务」，开关在二级页
    # （PMX110 / #905）。ColorOS 16 仍是点「内容资讯」进列表页、在那页上关。
    # 这一页还有快递、航班、日程提醒与商圈服务，保持不动。
    enter_settings("OPPO AI", "小布建议")
    page("小布建议", SETTINGS)
    switches = open_switch_page("资讯服务", "资讯服务", SETTINGS)
    if switches is not None:
        require_switches(switches, ["资讯服务"], "资讯服务")
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
        return
    # 旧版本这一页的标题没有实测记录，两种叫法都认。
    switches = open_switch_page("内容资讯", ["内容资讯", "资讯服务"], SETTINGS)
    if switches is not None:
        require_switches(switches, ["资讯服务"], "内容资讯")
        p.off(only=["资讯服务"], page="小布建议·内容资讯")
        return
    raise RuntimeError("小布建议：「资讯服务」与「内容资讯」两条入口都没进去")
