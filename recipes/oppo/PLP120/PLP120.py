# OPPO Find N6（PLP120，ColorOS 16 / 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 search_settings / open_switch_page / page / read_on_page 与 require_switches 由装载器
# 注入执行作用域。只剩三段在这里：负一屏（手势循环）、下拉搜索（运行期名单）、浏览器（多分支
# 状态机）。其余六段已落数据（见 `.toml`）。
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


def search_sources(p, rt):
    """借给别的机型（安全模式）时只关推荐位：ColorOS 17 上榜单 / 小说 / 购物是内容源，关掉会搜不到东西。"""
    if p.safe_mode:
        return ["个性化推荐", "精选资讯"]
    return ["榜单", "小说", "购物", "个性化推荐", "精选资讯"]


def step_search(p, rt):
    if not nav.search_settings(p, rt):
        print("  · 跳过：没有认出全局搜索设置页（入口不可用或被系统限制）", flush=True)
        return
    if p.tap("搜索范围", exact=True):
        p.off(only=search_sources(p, rt), page="下拉搜索·搜索范围")
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
