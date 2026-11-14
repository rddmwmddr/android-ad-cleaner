# 一加 Ace 2 Pro（PJA110，ColorOS 16 / Android 16）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 open_settings / read_switches / close_named 与 require 由装载器注入执行作用域。
# 两段留在代码里：下拉搜索要算「首页底部的设置」坐标并带页面现场，推广位要按本页实际读到的开关收窄名单。


# 全局搜索的设置页没有导出，只有它自己的 gs:// scheme 能直接落地（PLP120 / PLG110 / PMX110 实测）。
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
SEARCH_TITLES = ("搜索范围", "首页卡片管理", "功能管理", "账号与隐私")
# 录自 ColorOS 14 的商店服务管理，不扩成 PHK110 的 26 项：改名或下架的项跳过，一项都不认识算段失败。
PROMOTIONS = ["首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
              "游戏详情页：游戏活动卡片", "软件专区：福利"]


import recipe_nav as nav
def step_search(p, rt):
    """桌面下滑手势在 adb 下不稳；scheme 不通时退回搜索首页底部的「设置」，不碰手势。"""
    p.d.shell(SEARCH_SETTINGS)
    if not nav.search_settings_ready(p, rt):
        print("  · scheme 没落到搜索设置页，改点搜索首页底部的「设置」", flush=True)
        p.start("com.heytap.quicksearchbox", ".ui.activity.SearchHomeActivity")
        cands = [((l + r) // 2, (tp + b) // 2) for t, (l, tp, r, b), _ in p.texts()
                 if t == "设置" and tp > p.H * 0.8]
        rt.require(cands, f"搜索首页底部没有「设置」；{p.page_evidence()}")
        before = p.sig()
        p.click(*cands[-1])
        p.settle(before, 1.5)
        rt.require(nav.search_settings_ready(p, rt), f"没进全局搜索设置页；{p.page_evidence()}")
    p.enter("账号与隐私", scrolls=4)
    p.enter("隐私", scrolls=4)
    nav.close_named(p, rt, ["个性化推荐"], "下拉搜索·隐私")


def step_store_promotions(p, rt):
    nav.open_settings(p, rt, "com.heytap.market", "com.heytap.market.mine.cn.setting.ui.SettingActivity", "应用与服务")
    p.enter("服务管理", scrolls=4)
    page = nav.read_switches(p, rt, 6)
    missing = [name for name in PROMOTIONS if name not in page]
    if missing:
        print(f"  · 商店·推广位：本次未显示 {'、'.join(missing)}，不计为已关闭", flush=True)
    nav.close_named(p, rt, [name for name in PROMOTIONS if name in page], "商店·推广位", max_screens=6, snapshot=page)


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)
