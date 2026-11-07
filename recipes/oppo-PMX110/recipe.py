# OPPO Find X10 Pro Max（PMX110）：2026-11-05 逐页核对，ColorOS 17 / Android 17，实测版本
# PMX110_17.0.0.116(CN01)。BUILD 只写到 17.0.0：同代的 17.0.0.x 共用这份路径，其他 ColorOS 17
# 机型也靠这个前缀把这份脚本当同族参考（#319 / #483）。
# 只关点名的广告与推荐；搜索数据源、服务通知与消息总开关保留，营销由 chan-scan / chan-off
# 在渠道级处理。通知渠道、组件挂起和快应用继续走 run.py 的独立确认流程。
BUILD = "PMX110_17.0.0"
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
import time
from collections import namedtuple

import adb_link
from fast import ScreenLocked, bounds

MenuState = namedtuple("MenuState", "close_all_disabled system_apps_shown")

ONLY = globals().get("ONLY") or []
FAILED_STEPS = globals().get("FAILED_STEPS") or []
RESULTS = []
SKIPPED_ITEMS = []
VERIFIED_SWITCHES = 0
HALTED = False

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


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


class SkipStep(RuntimeError):
    pass


def step(name):
    def decorate(action):
        global HALTED
        if ONLY and name not in ONLY:
            return action
        print(f"\n== {name}", flush=True)
        started = time.monotonic()
        p.miss = 0
        try:
            if HALTED or p.locked():
                raise ScreenLocked("手机锁屏或前段已停止，请机主解锁后重试")
            action()
            RESULTS.append((name, "completed"))
        except adb_link.DeviceLost:
            raise
        except SkipStep as reason:
            RESULTS.append((name, "skipped"))
            print(f"  · 跳过：{reason}", flush=True)
        except Exception as error:
            if isinstance(error, ScreenLocked):
                HALTED = True
            FAILED_STEPS.append(name)
            RESULTS.append((name, "incomplete"))
            print(f"  ✗ 未完成：{error}", flush=True)
        print(f"  ({time.monotonic() - started:.0f} 秒)", flush=True)
        return action
    return decorate


def page(title, package=None, activity=None):
    # 等待由引擎负责；旧页面即使已稳定，也必须通过下面的落点与标题检查。
    p.await_page(budget=6)
    where = p.focus()
    require(not package or where.split("/", 1)[0] == package, "未进入目标应用，未操作开关")
    require(not activity or activity in where.split("/", 1)[-1], "未进入目标设置页，未操作开关")
    require(p.find(title, exact=True), f"未确认页面「{title}」，未操作开关")
    if any(text in {"同意", "同意并继续", "同意并使用", "允许", "仅在使用中允许"}
           and "Button" in node.get("class", "") for text, _, node in p.texts()):
        p.dismiss()
        raise SkipStep("出现协议或权限申请，不代为同意")
    if p.locked():
        raise ScreenLocked("手机锁屏，请机主解锁")


def open_page(command, title, package, activity=None):
    result = p.d.shell(command)
    require(not result.exit_code and not any(word in result.output for word in
            ("Error", "Exception", "Permission Denial", "unable to resolve")), "系统未允许打开设置页")
    page(title, package, activity)


def app_settings(package):
    open_page("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package,
              "返回" if package == THEME else "软件商店", package, "SettingActivity")


def row(text, title=None, package=None, activity=None, scrolls=8):
    """只点具名导航行，避免点隐私页的过度授权横幅；坐标来自当前节点。"""
    p.await_page()
    where = p.focus()
    for index in range(scrolls + 2):
        root = p.tree()
        parents = {child: node for node in root.iter() for child in node}
        matches = [n for n in root.iter("node")
                   if (n.get("text") or n.get("content-desc") or "").strip() == text and p.on_screen(n)]
        require(len(matches) <= 1, f"「{text}」入口不唯一，未点击")
        if matches:
            node = matches[0]
            target = node
            while target is not None and target.get("clickable") != "true":
                target = parents.get(target)
            target = target if target is not None else node
            l, t, r, b = bounds(target)
            require(r > l and b > t and p.on_screen(target), "入口坐标无效")
            require(p.focus() == where, "找入口期间页面变了，未点击")
            before = p.sig()
            p.click((l + r) // 2, (t + b) // 2)
            require(p.settle(before, 2.4), f"点击「{text}」后页面没有变化")
            page(title or text, package, activity)
            return
        if index == 0:
            p.top(scrolls)
        elif index == scrolls + 1 or not p.scroll_more():
            break
    raise RuntimeError(f"没找到入口「{text}」，未继续本段")


def switch_signature():
    return tuple(p.switches())


def switch_top(max_screens):
    """按开关行判顶部，不让访问时间等动态文字延长整页翻动。"""
    before = switch_signature()
    for _ in range(max_screens):
        p.top(1)
        current = switch_signature()
        if current == before:
            return
        before = current
    raise RuntimeError("未确认开关列表顶部，未执行关闭")


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
    missing = [name for name in names if name not in before and name not in optional]
    require(not missing, f"{title}：未识别全部目标开关，未操作")
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
    result = p.d.shell("pm path " + package)
    require(not result.exit_code, f"无法读取{label}安装状态")
    if "package:" not in result.output:
        raise SkipStep(f"本机未安装{label}")


def system_settings():
    open_page("am start -f 0x10008000 -a android.settings.SETTINGS", "设置", "com.android.settings")


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
        raise SkipStep("仅在 PMX110 上批量处理广告跟踪")
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
    row("隐私")
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
    # 设置页 SearchSettingActivity 没导出，am start -n 会被拒绝；走应用自己的 scheme。
    # 榜单 / 小说 / 购物是搜索数据源，消息管理是服务通知，两类都不动。
    open_page(SEARCH_SETTINGS, "搜索范围", SEARCH, "SearchSettingActivity")
    row("搜索范围")
    close_named(["个性化推荐", "精选资讯"], "搜索范围", dependent=["全部"])
    p.back()
    row("首页卡片管理")
    cards = read_switches("首页卡片管理")
    names = [name for name in SEARCH_CARDS if name in cards]
    if names:
        close_named(names, "首页卡片管理", snapshot=cards)
    missing = len(SEARCH_CARDS) - len(names)
    if missing:
        note = f"首页卡片管理：本次未显示 {missing} 个录制推广项，未操作、不计为已关闭"
        SKIPPED_ITEMS.append(note)
        print("  · " + note, flush=True)
    p.back()
    row("功能管理")
    close_named(["搜索框提示词"], "功能管理")
    p.back()
    # 「账号与隐私」只是设置页上的分组标题，没有二级页面；直接点它下面的隐私行。
    row("隐私")
    close_named(["个性化推荐"], "隐私")


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


@step("负一屏")
def _():
    p.d.shell("input keyevent HOME")
    time.sleep(.6)
    p.d.shell("input keyevent HOME")
    for _ in range(3):
        p.d.shell(f"input swipe 8 {p.H//2} {p.W*3//4} {p.H//2} 700")
        p.await_page()
        if any("head_icon" in n.get("resource-id", "") for n in p.tree().iter("node")):
            break
    icons = [n for n in p.tree().iter("node") if n.get("resource-id", "").endswith("head_icon")
             and p.on_screen(n)]
    require(len(icons) == 1, "未确认负一屏头像入口")
    l, t, r, b = bounds(icons[0])
    before = p.sig()
    p.click((l + r) // 2, (t + b) // 2)
    p.settle(before, 2.4)
    row("设置", title="推荐服务")
    row("推荐服务")
    where = p.focus()
    carousel_error = None
    try:
        hide_carousel()
    except (adb_link.DeviceLost, ScreenLocked):
        raise
    except RuntimeError as error:
        require(p.focus() == where, "轮播识别失败且已离开原页，停止本段")
        carousel_error = error
        print(f"  ✗ 轮播推荐未确认：{error}；继续核对独立的热点资讯", flush=True)
    # 热点资讯页有导出，直达（#650），不用回设置页再滚动找
    hot_news = "am start -f 0x10008000 -n com.coloros.assistantscreen/com.oplus.assistantscreen.card.infoflow.setting.activity.InfoFlowSettingActivity"
    open_page(hot_news, "热点资讯", "com.coloros.assistantscreen", "InfoFlowSettingActivity")
    close_named(["热点资讯"], "热点资讯")
    if carousel_error:
        raise RuntimeError(f"热点资讯已核对；轮播推荐未完成：{carousel_error}")


@step("主题")
def _():
    # 消息与广告只关开屏广告：消息通知是服务通知，保留。
    app_settings(THEME)
    row("服务管理")
    row("消息与广告")
    close_named(["开屏广告"], "消息与广告")
    app_settings(THEME)
    row("隐私")

    def reopen():
        app_settings(THEME)
        row("隐私")

    close_named(["个性化推荐设置"], "隐私", reopen=reopen)


@step("视频")
def _():
    require_installed(VIDEO, "视频")
    # 设置页没导出，用 App 自己的深链直达（#650），不经开屏页和「我的」；带 -p 限定到视频，
    # 免得别的 App 也注册了这个 scheme 时弹选择器
    open_page("am start -f 0x10008000 -a android.intent.action.VIEW -p " + VIDEO
              + " -d yoli://yoli.com/mine_act_lib_yoli/settings", "设置", VIDEO, "SettingActivity")
    row("个性化管理")
    close_named(["个性化广告推荐", "个性化内容推荐"], "个性化管理")


@step("游戏中心")
def _():
    # 设置页认 APP_SETTINGS 动作，直达（#650），不用关首进引导、找「我的」和齿轮。
    # 设置页上的「隐私」只是分组标题、点不动；入口是它下面的「隐私开关设置」（PMX110 11-06 实测）。
    require_installed(GAME, "游戏中心")
    open_page("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + GAME, "游戏中心", GAME, "SettingActivity")
    row("隐私开关设置", scrolls=6)
    row("个性化推荐管理", scrolls=4)
    close_named(["个性化推荐"], "个性化推荐管理")
    p.confirm()


@step("小布建议")
def _():
    system_settings()
    row("OPPO AI")
    row("小布建议")
    row("资讯服务")
    close_named(["资讯服务"], "资讯服务")


print(f"\n逐项回读确认 {VERIFIED_SWITCHES} 项；完成 {sum(state == 'completed' for _, state in RESULTS)} 段，"
      f"跳过 {sum(state == 'skipped' for _, state in RESULTS)} 段，未显示项 {len(SKIPPED_ITEMS)} 组", flush=True)
