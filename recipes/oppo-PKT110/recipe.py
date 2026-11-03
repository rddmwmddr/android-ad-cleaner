# OPPO Find X8s（PKT110），ColorOS 17.0.0.102(CN01) / Android 17。
# 路径与开关来自 2026-10-28 在 PKT110 真机上逐段实测。
# 不覆盖软件商店（ColorOS 17 的设置页里没有「隐私」「服务管理」，商店首页的推广位也关不掉），
# 也不覆盖负一屏（速览）——那边没有「推荐服务」分组。详见 docs/清单/OPPO-ColorOS.md。
BUILD = "PKT110_17.0.0.102(CN01)"
import time

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
VERIFIED_SWITCHES = 0
# 全局搜索的设置页没有导出：adb am start 会被系统拒绝（SecurityException: not exported），
# 只能用它自己的 gs:// scheme 打开。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 搜索首页上那几张卡片：应用建议、精选推荐、推荐卡片、热搜榜单都是推荐位。
# 「便捷服务」是用户常用的快捷入口，不是广告位，保持不动。
HOME_CARDS = ["热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"]
# 「未下载应用推荐」「应用建议小卡」是「应用建议」的子项：父开关一关，这两行就没了。
HOME_CARD_CHILDREN = ["未下载应用推荐", "应用建议小卡"]
HOME_CARD_PARENT = "应用建议"
# 搜索结果里带出来的推荐源。「榜单」「小红书」「购物」这些是内容源不是广告位，保持不动。
SEARCH_SOURCES = ["个性化推荐", "精选资讯", "搜索建议"]


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def step(name):
    def decorate(action):
        if ONLY and name not in ONLY:
            return action
        print(f"\n== {name}", flush=True)
        p.miss = 0
        try:
            require(not p.locked(), "手机锁屏了，请机主解锁后再跑")
            action()
        except Exception as error:
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{error}", flush=True)
        return action
    return decorate


def tap(name, scrolls=4, exact=True):
    if not p.tap(name, exact=exact, scrolls=scrolls):
        raise RuntimeError(f"未找到入口「{name}」；当前页：{p.page_text()}")


def open_settings(expect=("服务管理", "隐私")):
    """进「设置」入口，落地页出现 expect 之一才算成功。
    17.22 的主题商店把这一行读作「设置,有1条新通知」：精确匹配「设置」落空，它又带文字，
    右上角图标的兜底只收无文字节点，同样收不到；游戏中心 14.43.3 反过来是纯齿轮图标。
    按「文字精确 → 文字包含 → 右上角图标」三级走，点错页先退回来再换下一级（#286）。"""
    for exact in (True, False):
        if not p.find("设置", exact=exact):
            continue
        before = p.sig()
        if p.tap("设置", exact=exact, scrolls=0) and any(p.find(w, exact=True) for w in expect):
            return True
        if p.sig() != before:
            p.back()
    return p.tap_icon(list(expect))


def read_switches(max_screens, first=None):
    """读这一页的开关。first 是刚读到的第一屏，复用它，不多读一遍。"""
    current = {}
    items = first if first is not None else p.switches()
    current.update({title: on for title, on, _ in items})
    for _ in range(max_screens - 1):
        if not p.scroll_more():
            break
        current.update({title: on for title, on, _ in p.switches()})
    return current


def wait_switches(timeout=4.0):
    """刚进二级页时开关还没画出来：等一下再读，别把空页面当成「没找到目标开关」。"""
    end = time.time() + timeout
    while True:
        found = p.switches()
        if found:
            return found
        if time.time() >= end:
            return []
        time.sleep(0.2)


def close_named(names, page, max_screens=1, reopen=None, gone=()):
    """关掉点名的开关并回读确认；其他开关的状态不能变。
    reopen：有的页点完开关会弹确认框、确认后退回上一级，回读前用这个回调重新进一次。
    gone：父开关一关就会从页面上消失的那几行，回读时不再要求它们还在。"""
    global VERIFIED_SWITCHES
    p.top(max_screens)
    first = wait_switches()
    require(first, f"{page}：页面里没读到开关，未操作")
    before = read_switches(max_screens, first=first)
    require(all(name in before for name in names), f"{page}：未识别全部目标开关，未操作")
    p.top(max_screens)
    p.off(only=names, page=page, max_screens=max_screens)
    if reopen:
        reopen()
    p.top(max_screens)
    current = read_switches(max_screens)
    require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
    require(all(current.get(name) == state for name, state in before.items()
                if name not in names and name not in gone),
            f"{page}：其他开关状态变化，请核对")
    VERIFIED_SWITCHES += len(names)


def close_group(children, parent, page, max_screens=1):
    """有的开关是父项的子项：父开关一关，子项那两行就从页面上消失了（点不到、也回读不到）。
    父项还开着时先关子项再关父项；父项本来就是关的，子项压根不在页面上，只关父项。"""
    p.top(max_screens)
    first = wait_switches()
    require(first, f"{page}：页面里没读到开关，未操作")
    if read_switches(max_screens, first=first).get(parent):
        close_named(children, page, max_screens=max_screens)
        close_named([parent], page, max_screens=max_screens, gone=children)
    else:
        close_named([parent], page, max_screens=max_screens)


def close_all(page, max_screens):
    """整页关掉所有开关（逐 App 的广告跟踪列表用），关完回读确认。"""
    global VERIFIED_SWITCHES
    p.top(max_screens)
    first = wait_switches()
    require(first, f"{page}：没读到开关，未操作")
    before = read_switches(max_screens, first=first)
    require(before, f"{page}：没读到开关，未操作")
    p.top(max_screens)                   # 读完整页会翻到底，p.off 只往下翻，得先回到顶部
    p.off(page=page, max_screens=max_screens)
    p.top(max_screens)
    current = read_switches(max_screens)
    still = sorted(name for name, on in current.items() if on)
    require(not still, f"{page}：回读未确认关闭（仍有 {len(still)} 项开着）")
    VERIFIED_SWITCHES += len(before)


@step("广告跟踪")
def _():
    """设置 → 隐私与安全 → 设备标识与广告 → 广告跟踪。
    每个 App 一个开关、没有总开关，本机 96 个 App，分五屏。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    p.miss = 0
    # 17 把入口改名叫「隐私与安全」：先试新名字，免得在旧名字上白翻一轮、还打印一行失败（#292）。
    if not p.tap("隐私与安全", exact=True):
        p.miss = 0
        tap("隐私")
    tap("设备标识与广告")
    tap("广告跟踪")
    time.sleep(1)
    close_all("广告跟踪", max_screens=40)


@step("下拉搜索")
def _():
    """全局搜索的设置页（gs://search/setting）：搜索首页上的推荐卡片、搜索结果里的推荐源、
    搜索框提示词、消息通知、隐私里的个性化推荐。
    「便捷服务」和搜索范围里的内容源（榜单、小红书、购物等）不是广告位，不动。"""
    p.d.shell(SEARCH_SETTING); time.sleep(1.5)
    require("com.heytap.quicksearchbox" in p.focus(), "全局搜索设置页没有打开")
    tap("首页卡片管理")
    require("SearchModuleManagerActivity" in p.focus(), "首页卡片管理页没有打开")
    if wait_switches():
        close_group(HOME_CARD_CHILDREN, HOME_CARD_PARENT, "下拉搜索·首页卡片管理", max_screens=3)
        close_named(HOME_CARDS, "下拉搜索·首页卡片管理", max_screens=3)
    else:
        # 推荐卡片全部关掉之后，这一页就不再列出任何卡片（2026-10-28 实测）。
        print("  · 首页卡片管理：这页没有列出卡片，没有可关的开关", flush=True)
    p.back()
    tap("搜索范围")
    close_named(SEARCH_SOURCES, "下拉搜索·搜索范围", max_screens=6)
    p.back()
    tap("功能管理")
    close_named(["搜索框提示词"], "下拉搜索·功能管理", max_screens=2)
    p.back()
    tap("消息管理")
    close_named(["消息通知"], "下拉搜索·消息管理", max_screens=2)
    p.back()
    tap("隐私")
    close_named(["个性化推荐"], "下拉搜索·隐私", max_screens=2)


@step("浏览器")
def _():
    """浏览器 → 隐私：广告管理里的开屏/资讯列表广告、个性化管理里的个性化广告推荐。
    「摇一摇广告」在两个上级开关关掉后仍显示为开且点不动（系统置灰），不单独点。"""
    p.start("com.heytap.browser")
    # 这台机上「我的」点进去是菜单浮层，直接用公开入口进设置页
    p.d.shell("am start -n com.heytap.browser/.settings.component.BrowserPreferencesPage"); time.sleep(1.5)
    require("com.heytap.browser" in p.focus(), "浏览器设置页没有打开")
    tap("隐私")
    if p.tap("广告管理", exact=True, scrolls=0):
        close_named(["开屏广告", "资讯列表广告"], "浏览器·广告管理")
        p.back()
    tap("个性化管理")
    close_named(["个性化广告推荐"], "浏览器·个性化管理")


@step("主题商店")
def _():
    """主题商店 → 我的 → 设置：服务管理 → 消息与广告；隐私 → 个性化推荐设置。
    「个性化推荐设置」点下去先弹确认框，确认后页面退回「设置」，回读前要重新进一次。
    首页的「检测到新版本」弹窗盖住底部标签栏，关弹窗的动画会把紧跟着的点击吞掉，
    所以每一跳都用会确认换页的 p.enter（#286）。
    「我的」页的「设置」在 17.22 上带通知角标（读作「设置,有1条新通知」），别的版本是纯齿轮，
    两种都要能进——见 open_settings()。"""
    def enter_settings():
        require(open_settings(), "没找到「设置」入口：文字与右上角图标都试过")

    def to_privacy():
        p.start("com.heytap.themestore")
        p.enter("我的")
        enter_settings()
        p.enter("隐私")

    p.start("com.heytap.themestore")
    p.enter("我的")
    enter_settings()
    p.enter("服务管理")
    p.enter("消息与广告")
    close_named(["消息通知", "开屏广告"], "主题·消息与广告")
    p.back(2)
    to_privacy()
    close_named(["个性化推荐设置"], "主题·个性化推荐", reopen=to_privacy)


@step("视频")
def _():
    """OPPO 视频 → 我的（底部标签）→ 设置 → 个性化管理。"""
    p.start("com.heytap.yoli")
    p.enter("我的")
    p.enter("设置")
    p.enter("个性化管理", scrolls=6)
    close_named(["个性化广告推荐", "个性化内容推荐"], "视频·个性化管理")


@step("游戏中心")
def _():
    """游戏中心 → 我的 → 设置 → 隐私开关设置 → 个性化推荐管理。
    「设置」在 14.43.3 上是「我的」页右上角的齿轮图标，没有文字（#292）；旧版是「设置,有新通知」文字行。
    「我的」页还带「页面升级」弹窗，先关掉。"""
    p.start("com.nearme.gamecenter")
    # 底栏点下去被开屏动画吞掉时页面不换，p.tap 照样返回成功，接着就整段失败；换页要确认（#286）。
    p.enter("我的")
    time.sleep(1.2)
    # dismiss() 遇到带滚动列表的页面就不点文字按钮，「页面升级」弹窗的「我知道了」只能点名点。
    if p.find("我知道了", exact=True):
        p.tap("我知道了", exact=True, scrolls=0); time.sleep(1.2)
    else:
        p.dismiss()
    require(open_settings(("隐私开关设置", "隐私")), "没找到设置入口：右上角图标都点过")
    tap("隐私开关设置")
    tap("个性化推荐管理")
    close_named(["个性化推荐"], "游戏中心·个性化推荐")


@step("小布建议")
def _():
    """设置 → OPPO AI → 小布建议 → 内容资讯里的「资讯服务」，
    再进「场景服务」里的「视界日报」「小红书资讯」。
    「内容资讯」是分组标题，页面上没有开关；开关在它下面那一行的二级页里。
    快递、航班、日程提醒、商圈服务在同一页，保持不动。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    tap("OPPO AI", scrolls=6)
    tap("小布建议", scrolls=6)
    tap("资讯服务", scrolls=8)
    close_named(["资讯服务"], "小布建议·资讯服务")
    tap("视界日报", scrolls=0)
    close_named(["视界日报"], "小布建议·视界日报")
    p.back()
    tap("小红书资讯", scrolls=0)
    close_named(["小红书资讯"], "小布建议·小红书资讯")


@step("应用建议")
def _():
    """小布建议 → 其他 → 应用建议：搜索首页上那排「应用建议」卡片，
    每个被推荐的应用一个开关（com.oplus.metis），整页关掉。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    tap("OPPO AI", scrolls=6)
    tap("小布建议", scrolls=6)
    tap("应用建议", scrolls=10)
    close_all("应用建议", max_screens=40)


print(f"\n已回读确认 {VERIFIED_SWITCHES} 项；未完成步骤 {len(FAILED_STEPS)} 个", flush=True)
