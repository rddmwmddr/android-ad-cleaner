# OPPO Find N6（PLP120，ColorOS 16 / 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 search_settings / open_switch_page / page / read_on_page 与 require_switches 由装载器
# 注入执行作用域。只剩负一屏（坐标算法）在这里，外加下拉搜索要用的 `search_sources` 名单；
# 其余八段已落数据（见 `.toml`）。
import time

import adb_link
from fast import ScreenLocked
import recipe_nav as nav


BUILD = "PLP120_16.0.9"

# 游戏中心与系统设置两个包名：家族库经 `rt.constants` 取它们（`game_settings_direct` 等），
# 数据段里则写成字面量。
GAME = "com.nearme.gamecenter"
SETTINGS = "com.android.settings"


def step_negative_screen(p, rt):
    # 进没进都不中断：这一段后面按页面读到的头像与开关走，不靠这个结果。
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

