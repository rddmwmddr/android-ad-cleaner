# OPPO Find N6（PLP120，ColorOS 16 / 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 search_settings / enter_settings / game_settings_direct / game_settings_via_mine /
# open_switch_page / page / read_on_page 与 require_switches 由装载器注入执行作用域。
# 只剩四段在这里：负一屏（手势循环）、游戏中心（运行期 direct 分支）、小布建议（两次入口
# 状态机），以及下拉搜索要用的 `search_sources` 名单。其余六段已落数据（见 `.toml`）。
import time

import adb_link
from fast import ScreenLocked
import recipe_nav as nav
import recipe_strategies as strategies


BUILD = "PLP120_16.0.9"

GAME = "com.nearme.gamecenter"
SETTINGS = "com.android.settings"


def step_negative_screen(p, rt):
    # 进没进都不中断：这一段后面按页面读到的头像与开关走，不靠这个结果
    nav.assistant_swipe_in(p, rt)
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


def search_sources(p, rt):
    """借给别的机型（安全模式）时只关推荐位：ColorOS 17 上榜单 / 小说 / 购物是内容源，关掉会搜不到东西。"""
    if p.safe_mode:
        return ["个性化推荐", "精选资讯"]
    return ["榜单", "小说", "购物", "个性化推荐", "精选资讯"]



def step_game_center(p, rt):
    direct = nav.game_settings_direct(p, rt)
    if not direct:
        nav.game_settings_via_mine(p, rt)
    p.enter("隐私开关设置", scrolls=6)
    p.enter("个性化推荐管理", scrolls=4)
    rt.require_switches(strategies.read_on_page(p, rt, "个性化推荐管理", GAME), ["个性化推荐"], "个性化推荐管理")
    p.off(only=["个性化推荐"], page="游戏中心·个性化推荐")
    p.back(3 if direct else 4)


def step_assistant_advice(p, rt):
    # ColorOS 17：「内容资讯」是点不动的分组标题，入口是它下面那行「资讯服务」，开关在二级页
    # （PMX110 / #905）。ColorOS 16 仍是点「内容资讯」进列表页、在那页上关。
    # 这一页还有快递、航班、日程提醒与商圈服务，保持不动。
    nav.enter_settings(p, rt, "OPPO AI", "小布建议")
    rt.page("小布建议", SETTINGS)
    switches = nav.open_switch_page(p, rt, "资讯服务", "资讯服务", SETTINGS)
    if switches is not None:
        rt.require_switches(switches, ["资讯服务"], "资讯服务")
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
        return
    # 旧版本这一页的标题没有实测记录，两种叫法都认。
    switches = nav.open_switch_page(p, rt, "内容资讯", ["内容资讯", "资讯服务"], SETTINGS)
    if switches is not None:
        rt.require_switches(switches, ["资讯服务"], "内容资讯")
        p.off(only=["资讯服务"], page="小布建议·内容资讯")
        return
    raise RuntimeError("小布建议：「资讯服务」与「内容资讯」两条入口都没进去")
