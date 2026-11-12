# 一加 15T（PLZ110），2026-11-08 真机核对。
# 系统 PLZ110_17.0.0.107(CN01) / Android 17；仅记录本机走通的路径。
# 浏览器原已停用，跳过且不启用；系统广告跟踪未验证，不纳入本脚本。
# 通知渠道、广告组件及快应用仍由 run.py 独立确认。
# 2026-11-10 负一屏入口改从内侧右滑、已在负一屏不再滑走、认不到入口时留页面现场（#901），未复测。
# 软件商店隐私入口接受「隐私」与「隐私授权管理」两种叫法，按落在商店隐私页判，未复测（#907）。
BUILD = "PLZ110_17.0.0.107(CN01)"
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
import adb_link
from fast import ScreenLocked, bounds


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
# 轮播单选只有这两个选项，「不显示」是我们要的那一档（沿用 #280 的做法）。
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
    raise SkipStep(f"本机未安装{label}")


@step("软件商店")
def _():
    app_settings(MARKET)
    # 本版商店叫「隐私授权管理」，同族另有叫「隐私」的（#907）。tries 保住原来 p.enter 的
    # 「点击被弹窗动画吞掉就再点」：这一行必须点开，后面的行都指着它（#286）。
    row(("隐私", "隐私授权管理"), package=MARKET, activity="PrivacyActivity", tries=3)
    row("个性化推荐", package=MARKET, activity="PersonalRecommendActivity")
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
    """只认单选控件自己的标签；不合并祖先子树的文字，也不点预览图里的同名文字（沿用 #280 的做法）。"""
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
    l, t, r, b = bounds(assistant_icon())
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
    # 热点资讯页有导出，直达（沿用 #650 的做法），不用回设置页再滚动找
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
    # 设置页没导出，用 App 自己的深链直达（沿用 #650 的做法），不经开屏页和「我的」；带 -p 限定到视频，
    # 免得别的 App 也注册了这个 scheme 时弹选择器
    open_page("am start -f 0x10008000 -a android.intent.action.VIEW -p " + VIDEO
              + " -d yoli://yoli.com/mine_act_lib_yoli/settings", "设置", VIDEO, "SettingActivity")
    row("个性化管理")
    close_named(["个性化广告推荐", "个性化内容推荐"], "个性化管理")


@step("游戏中心")
def _():
    # 设置页认 APP_SETTINGS 动作，直达（沿用 #650 的做法），不用关首进引导、找「我的」和齿轮。
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


print(f"\n逐项回读确认 {VERIFIED_SWITCHES} 项；完成 {sum(state == '完成' for _, state in RESULTS)} 段，"
      f"跳过 {sum(state == '跳过' for _, state in RESULTS)} 段，未显示项 {len(SKIPPED_ITEMS)} 组", flush=True)
