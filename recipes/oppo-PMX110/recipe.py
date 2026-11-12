# OPPO Find X10 Pro Max（PMX110）：2026-11-05 逐页核对，ColorOS 17 / Android 17，实测版本
# PMX110_17.0.0.116(CN01)。BUILD 只写到 17.0.0：同代的 17.0.0.x 共用这份路径，其他 ColorOS 17
# 机型也靠这个前缀把这份脚本当同族参考（#319 / #483）。
# 只关点名的广告与推荐；搜索数据源、服务通知与消息总开关保留，营销由 chan-scan / chan-off
# 在渠道级处理。通知渠道、组件挂起和快应用继续走 run.py 的独立确认流程。
# 2026-11-10 负一屏入口改从内侧右滑、已在负一屏不再滑走、认不到入口时留页面现场（#901），未复测。
# 软件商店隐私入口接受「隐私」与「隐私授权管理」两种叫法，按落在商店隐私页判，未复测（#907）。
BUILD = "PMX110_17.0.0"
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
from collections import namedtuple

import adb_link
from fast import ScreenLocked, bounds

MenuState = namedtuple("MenuState", "close_all_disabled system_apps_shown")
RESULTS = []
SKIPPED_ITEMS = []
VERIFIED_SWITCHES = 0

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


def read_switches(title, max_screens=12):
    page(title)
    where = p.focus()
    switch_top(max_screens)
    states = {}
    previous = None
    for index in range(max_screens):
        require(p.focus() == where, "读取时离开目标页，停止本段")
        if p.locked():
            raise ScreenLocked("读取时手机锁屏")
        signature = switch_signature()
        if signature == previous:
            return states
        for name, on, _ in signature:
            if name:
                require(name not in states or states[name] == on,
                        "同名开关状态不一致，无法可靠核对，未继续操作")
                states[name] = on
        if max_screens > 20 and (index + 1) % 20 == 0:
            print(f"  · {title}：已读取 {len(states)} 个具名项，继续核对列表", flush=True)
        previous = signature
        # scroll_more 的返回值包含全页动态文字，只借其滚动及焦点保护，下一轮按开关行判进展。
        p.scroll_more()
    if switch_signature() == previous:
        return states
    raise RuntimeError("列表超过读取上限，未执行关闭")


def close_named(names, title, max_screens=12, dependent=(), reopen=None, snapshot=None, optional=()):
    """关掉点名的开关，并核对目标已关、非目标未变。

    optional 里的名字允许这次页面上没有：记成「未显示」并继续；名单其余项缺一个就整段不动。
    """
    global VERIFIED_SWITCHES
    before = read_switches(title, max_screens) if snapshot is None else snapshot
    require_switches(before, names, title, optional=optional)
    present = [name for name in names if name in before]
    absent = [name for name in names if name not in before]
    if absent:
        note = f"{title}：本次未显示 {'、'.join(absent)}，未操作、不计为已关闭"
        SKIPPED_ITEMS.append(note)
        print("  · " + note, flush=True)
    if not present:
        return
    if not any(before[name] for name in present):
        VERIFIED_SWITCHES += len(present)
        print(f"  · {title}：读取确认 {len(present)} 项原已关闭，未点击", flush=True)
        return
    p.top(max_screens)
    p.off(only=list(present), keep=[name for name in before if name not in names],
          page=title, max_screens=max_screens)
    if reopen:
        reopen()
    after = read_switches(title, max_screens)
    require(all(after.get(name) is False for name in present), f"{title}：回读未确认关闭")
    require(all(after.get(name) == state for name, state in before.items()
                if name not in names and name not in dependent), f"{title}：其他功能开关状态变化")
    VERIFIED_SWITCHES += len(present)
    print(f"  · {title}：回读确认 {len(present)} 项关闭", flush=True)


def require_installed(package, label):
    """没装的包 `pm path` 输出为空，退出码是 1（adb shell v2 带回）或 0（不带回退出码的通道）：
    那是「没装」，跳过本段，不算读不出（#899）。有报错文字或别的退出码才算读不出。"""
    result = p.d.shell("pm path " + package)
    if "package:" in result.output:
        return
    require(result.exit_code in (0, 1) and not result.output.strip(), f"无法读取{label}安装状态")
    skip(f"本机未安装{label}")


def browser_settings():
    p.start("com.heytap.browser", ".settings.component.BrowserPreferencesPage")
    for _ in range(4):
        p.await_page()
        where = p.focus()
        require(where.startswith("com.heytap.browser/"), "浏览器设置未打开")
        if where.endswith("BrowserPreferencesPage"):
            page("浏览器", "com.heytap.browser")
            return
        require(where.endswith("BrowserPreferenceActivity"), "浏览器进入未知页面，停止本段")
        p.back()
    raise RuntimeError("浏览器未回到设置首页")


def more_menu():
    require(p.tap("更多选项", exact=True, scrolls=0) or p.tap("更多", exact=True, scrolls=0),
            "未找到更多选项")


def ad_id_page():
    """到「设备标识与广告」页：先用设置搜索（ColorOS 能直接打开搜索页，#650，实测 4 秒），
    搜不到再从设置首页一层层找。"""
    if not p.setting("广告跟踪", "限制广告跟踪", path="隐私与安全 > 隐私 > 设备标识与广告"):
        system_settings()
        row("隐私与安全", package="com.oplus.securitypermission")
        row("设备标识与广告")
        return
    page("设备标识与广告")


def _labelled(text, name):
    """读屏会把状态后缀并进同一段文字（「全部关闭 - 已停用」），按主语认。"""
    rest = text[len(name):]
    return text.startswith(name) and (not rest or rest[0] in " ,，、-")


def menu_state():
    """打开右上「更多选项」，读「全部关闭」与「显示系统应用」两项的状态，菜单保持打开。
    列表里没有开着的应用时，系统把「全部关闭」置灰（读屏描述「全部关闭 - 已停用」）。"""
    more_menu()
    p.await_page()
    items = p.texts()                 # 一次快照：三次 dump 之间列表可能已经变化
    require(any(_labelled(t, "全部关闭") for t, _, _ in items), "菜单里没有「全部关闭」")
    disabled = any(_labelled(t, "全部关闭") and "已停用" in t for t, _, _ in items) or any(
        t == "全部关闭" and n.get("enabled") == "false" for t, _, n in items)
    # 显示系统应用后，这一项换成「隐藏系统应用」（PMX110 实测）
    system_shown = any(t.startswith("隐藏系统应用") or (t.startswith("显示系统应用") and "已选中" in t
                                                       and "未选中" not in t) for t, _, _ in items)
    return MenuState(disabled, system_shown)


def close_all_listed(label):
    """当前列表里还有开着的就点「全部关闭」，再开一次菜单确认它变灰（#650）。"""
    state = menu_state()
    if state.close_all_disabled:
        p.back()
        print(f"  · 广告跟踪（{label}）：已全部关闭，未点击", flush=True)
        return
    require(p.tap("全部关闭", exact=True, scrolls=0), "未能点「全部关闭」")
    p.confirm()
    p.await_page()
    state = menu_state()
    p.back()
    require(state.close_all_disabled, f"广告跟踪（{label}）：点了「全部关闭」后仍有开着的应用")
    print(f"  · 广告跟踪（{label}）：已全部关闭，菜单项已置灰确认", flush=True)


@step("广告跟踪")
def _():
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


@step("浏览器")
def _():
    browser_settings()
    row("隐私")
    row("广告管理")
    close_named(["开屏广告", "资讯列表广告", "摇一摇广告"], "广告管理")
    p.back()
    row("个性化管理")
    # 「个性化内容推荐」在部分安装版本上没有这一行：有就关，没有就记未显示。
    close_named(["个性化广告推荐", "个性化内容推荐"], "个性化管理", optional=["个性化内容推荐"])


@step("软件商店")
def _():
    app_settings(MARKET)
    row(("隐私", "隐私授权管理"), package=MARKET, activity="PrivacyActivity")
    row("个性化推荐")
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


def hide_carousel():
    """只认单选控件自己的标签；不合并祖先子树的文字，也不点预览图里的同名文字（#280）。"""
    global VERIFIED_SWITCHES
    before = read_switches("推荐服务")
    require("推荐服务" in before, "未读到推荐服务总开关")

    def choices():
        root = p.tree()
        parents = {child: node for node in root.iter() for child in node}
        found = {}
        for node in root.iter("node"):
            if node.get("checkable") != "true" or "RadioButton" not in node.get("class", ""):
                continue
            container = node
            for _ in range(5):
                labels = ({x.get("text", "") for x in container.iter("node")} |
                          {x.get("content-desc", "") for x in container.iter("node")}) & CAROUSEL_LABELS
                if len(labels) == 1:
                    label = labels.pop()
                    require(label not in found and p.on_screen(node) and node.get("enabled") == "true",
                            "轮播单选项不唯一或不可操作")
                    require(node.get("checked") in ("true", "false"), "轮播单选状态未知，未点击")
                    found[label] = (node.get("checked") == "true", bounds(node))
                    break
                container = parents.get(container)
                if container is None or len(labels) > 1:
                    break
        require(set(found) == CAROUSEL_LABELS and
                sum(on for on, _ in found.values()) == 1, "无法确认轮播单选状态")
        return found

    where = p.focus()
    selected, (l, t, r, b) = choices()[CAROUSEL_OFF]
    if not selected:
        require(p.focus() == where, "读取后轮播页面变化，未点击")
        p.click((l + r) // 2, (t + b) // 2)
        p.await_page()
        require(choices()[CAROUSEL_OFF][0], "轮播推荐回读未选中不显示")
        p.changed.append(("推荐服务", "轮播推荐：不显示"))
    require(read_switches("推荐服务") == before, "推荐服务总开关发生变化")
    VERIFIED_SWITCHES += 1


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


print(f"\n逐项回读确认 {VERIFIED_SWITCHES} 项；完成 {sum(state == '完成' for _, state in RESULTS)} 段，"
      f"跳过 {sum(state == '跳过' for _, state in RESULTS)} 段，未显示项 {len(SKIPPED_ITEMS)} 组", flush=True)
