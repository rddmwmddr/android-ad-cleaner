# realme 真我 GT5 Pro（RMX3888，ColorOS 15）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 只剩负一屏一段在这里（读完入口行之后的收窄，两个读数要留到后面用）。其余八段已落数据：
# 七段在 #1368，主题段在 #1372——「直达不通」的判据（只认「无法打开」）写进数据的 `dead_ends`。
import recipe_nav as nav


BUILD = "RMX3888_15.0.0.420"
MODELS = ["RMX3888"]

SETTINGS = "com.android.settings"
BROWSER = "com.heytap.browser"
VIDEO = "com.heytap.yoli"
SEARCH = "com.heytap.quicksearchbox"
# SearchSettingActivity 没导出（`am start -n` 会被系统拒绝），只能走应用自己的 scheme。
# 前提是 com.heytap.quicksearchbox 没被挂起：一挂，这个 scheme 落到系统的「应用已被暂停」页。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 搜索范围：只关推荐位。「榜单」「小红书」「购物」「小说」「视频」是内容源，「本机应用」「设置」
# 这类是数据源，关掉会搜不到东西。
SEARCH_SOURCES = ["个性化推荐", "精选资讯"]


def step_negative_screen_tail(p, rt):
    # 本机这一层没有「推荐服务 → 轮播推荐」，也没有「搜索框提示词」：两处默认已关，没有可关的项。
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
