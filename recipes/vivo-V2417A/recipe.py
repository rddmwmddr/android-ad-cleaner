# vivo V2417A，Android 16，PD2417D_A_16.2.14.1.W10。
# 路径来自 2026-10-30 真机逐页操作；验证范围及复跑记录见同目录 README.md。
BUILD = "PD2417D_A_16.2.14.1.W10"
MODELS = ["V2417A"]
import shlex
import time

import adb_link
from wait import until

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
VERIFIED_SWITCHES = 0


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def step(name):
    def decorate(action):
        if ONLY and name not in ONLY:
            return action
        print(f"\n== {name}", flush=True)
        p.miss = 0
        started = time.monotonic()
        try:
            require(not p.locked(), "手机锁屏了，请机主解锁后重试")
            action()
        except adb_link.DeviceLost:
            raise
        except Exception as error:
            FAILED_STEPS.append(name)
            print(f"  ✗ 未完成：{error}", flush=True)
        print(f"  ({time.monotonic() - started:.0f} 秒)", flush=True)
        return action
    return decorate


def tap(name, scrolls=4):
    require(p.tap(name, exact=True, scrolls=scrolls), f"未找到入口「{name}」")


def title_key(title):
    # vivo 将说明拼在点号后；商店将“开启/关闭”拼在中文逗号后。
    return title.split(".", 1)[0].split("，", 1)[0].strip()


def read_switches(max_screens=1):
    result = {}
    for screen in range(max_screens):
        items = until(p.switches, timeout=3, poll=0.2)
        require(items, "页面里没有读到开关，停止本段")
        current = {}
        for title, state, _ in items:
            key = title_key(title)
            require(key not in current, f"开关标题不唯一：{key}")
            current[key] = state
        result.update(current)
        if screen + 1 < max_screens and not p.scroll_more():
            break
    return result


def verify(before, current, names, page):
    global VERIFIED_SWITCHES
    require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
    require(all(current.get(name) == state for name, state in before.items() if name not in names),
            f"{page}：其他开关状态变化，请核对")
    VERIFIED_SWITCHES += len(names)
    print(f"  ✓ {page}：回读确认 {len(names)} 项关闭，其他开关未变", flush=True)


def close_named(names, page, max_screens=1):
    p.top(max_screens)
    before = read_switches(max_screens)
    require(all(name in before for name in names), f"{page}：未识别全部目标开关，未操作")
    p.top(max_screens)
    # only 在引擎中是包含匹配；明确保留本页其余开关，回读再核对一次。
    p.off(only=names, keep=[name for name in before if name not in names],
          page=page, max_screens=max_screens)
    p.top(max_screens)
    verify(before, read_switches(max_screens), names, page)


def store_personalization():
    """两行标题会随状态变化；逐行点，处理确认框后用稳定标题回读。"""
    page = "商店·个性化推荐"
    names = ["个性化推荐", "个性化广告推荐"]
    before = read_switches()
    require(all(name in before for name in names), f"{page}：未识别全部目标开关，未操作")
    for name in names:
        rows = [(state, xy) for title, state, xy in p.switches() if title_key(title) == name]
        require(len(rows) == 1, f"{page}：无法唯一识别「{name}」，未操作")
        if not rows[0][0]:
            continue
        signature = p.sig()
        p.click(*rows[0][1])
        p.settle(signature, 1.5)
        # 本机按钮未被通用 confirm() 识别；只点明确的“确认关闭”，不点状态文字。
        if p.find("确认关闭", exact=True):
            tap("确认关闭", scrolls=0)
        else:
            p.confirm()
        require(read_switches().get(name) is False, f"{page}：「{name}」回读未确认关闭")
        p.changed.append((page, name))
        print(f"  关 {name}", flush=True)
    verify(before, read_switches(), names, page)


def hiboard_panel():
    if "com.vivo.hiboard.settings.AppletSettingActivity" in p.focus():
        return
    # 此页面未导出，不能 am start；两次 HOME 回默认桌面，再按真机路径滑入。
    for _ in range(2):
        signature = p.sig()
        p.d.shell("input keyevent HOME")
        p.settle(signature, 1.0)
    # HOME 会恢复上次停留的负一屏；已在 HiBoard 时不必再当普通桌面横滑。
    home = p.focus()
    if home != "HiBoard":
        require(home.startswith("com.bbk.launcher2/"), "未回到系统桌面，停止负一屏段")
        signature = p.sig()
        p.d.shell(f"input swipe {p.W // 10} {p.H // 2} {p.W * 9 // 10} {p.H // 2} 300")
        p.settle(signature, 1.5)
    require(p.focus() == "HiBoard" and p.find("添加组件", exact=True),
            "未进入负一屏（可能未启用），停止本段")
    require(p.go("设置", "更多设置"), "未进入负一屏设置")
    require("com.vivo.hiboard.settings.AppletSettingActivity" in p.focus(), "负一屏设置页面不符")


@step("系统广告")
def _():
    # $ 必须交给 Android shell 前引用，否则会被当作变量展开。
    # 这是设置页，不是 App 首页；说明里的“关闭后”会被通用消弹窗误认为关闭按钮。
    p.start("com.android.settings", shlex.quote(".Settings$AdAndPrivacyActivityForOsTwo"), settle=0)
    require("AdAndPrivacyActivityForOsTwo" in p.focus(), "未进入广告与隐私页")
    close_named(["个性化广告", "个性化推荐", "智能推荐服务"], "系统·广告与隐私")


@step("全局搜索")
def _():
    p.start("com.vivo.globalsearch", ".view.SearchSettingsActivity")
    tap("首页展示内容", scrolls=0)
    close_named(["搜索框推荐词", "推荐卡片"], "全局搜索·首页展示内容")
    tap("推荐热搜榜单", scrolls=0)
    close_named(["热门搜索"], "全局搜索·热搜榜单")
    p.back(2)
    tap("个性化内容", scrolls=0)
    close_named(["广告个性化"], "全局搜索·个性化内容")
    # 全局搜索总开关、历史记录、语音搜索、应用建议及搜索结果个性化保持原值。


@step("阅图锁屏")
def _():
    p.start("com.vivo.magazine", ".ui.MagazineSettings")
    close_named(["阅图锁屏", "锁屏横滑进入阅图"], "阅图锁屏", max_screens=2)


@step("应用商店")
def _():
    p.start("com.bbk.appstore")
    # 冷启动的“月度精品”推荐页只进入首页，不点安装。
    if p.find("进入首页", exact=True):
        tap("进入首页", scrolls=0)
    require(p.go("我的", "设置"), "未进入商店·我的页")
    require(p.go("设置", "关于"), "未进入商店设置")
    require("AppstoreSettingsActivity" in p.focus(), "商店设置页面不符")
    tap("关于")
    tap("个性化推荐")
    store_personalization()
    p.back()
    tap("服务管理")
    close_named(["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮球", "限时推广"],
                "商店·服务管理", max_screens=2)
    # “我的页-我的服务”“空间清理”、下载更新设置不修改。


@step("浏览器")
def browser():
    p.start("com.vivo.browser", settle=2.0)
    # 入口随浏览器版本变：31.1.3.1 是底部「菜单」→「设置」；31.3.0.0 起底部标签栏改成
    # 首页/视频/AI/影视小说/我的，没有「菜单」，「设置」挂在「我的」页右上角，文字只在
    # content-desc 里（texts() 取 text 或 content-desc，按「设置」能找到，不用 tap_icon——
    # 它只挑文字与 desc 都为空的节点）。SettingActivity 未导出，am start 直达抛
    # SecurityException: not exported from uid，只能从界面走。
    if not p.entry("菜单", scrolls=0):
        require(p.go("我的", "设置"), "未打开浏览器设置入口（「菜单」与「我的」都试过；权限申请只拒绝）")
    require(p.go("设置", "首页设置"), "未进入浏览器设置")
    require("SettingActivity" in p.focus(), "浏览器设置页面不符")
    tap("首页设置")
    tap("极简首页", scrolls=0)
    require(p.find("首页上滑展示资讯", exact=True), "未切换到极简首页")
    close_named(["首页上滑展示资讯"], "浏览器·首页设置")
    p.back()
    tap("网页浏览设置")
    close_named(["网页下载相关推荐"], "浏览器·网页浏览")
    p.back()
    tap("更多设置")
    close_named(["WiFi连接跳转新闻资讯", "下载管理页展示热门应用", "下载管理页展示下载热榜"],
                "浏览器·更多设置", max_screens=2)
    p.back()
    tap("隐私权限设置")
    close_named(["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], "浏览器·隐私")


@step("i管家")
def _():
    p.start("com.iqoo.secure", ".MainSettings")
    tap("关于")
    tap("个性化设置")
    close_named(["应用个性化推荐"], "手机管家·个性化设置")


@step("天气")
def _():
    p.start("com.vivo.weather", ".WeatherSettings")
    # 此页“天气服务”的说明是“接收天气相关热点资讯通知”。
    close_named(["天气服务"], "天气·热点资讯通知")
    # 气象预警、异常天气、地震预警不修改。


@step("负一屏")
def _():
    hiboard_panel()
    tap("更多设置", scrolls=0)
    tap("个性化推荐", scrolls=0)
    close_named(["服务推荐", "资讯推荐"], "负一屏·个性化推荐")
    p.back(2)
    for name in ("内容精选", "热点资讯"):
        hiboard_panel()
        tap(name, scrolls=0)
        close_named([name], f"负一屏·{name}")
        p.back()
    # 便捷生活里的“推荐服务”、小V建议和常驻服务卡片全部保留。


print(f"\n回读确认 {VERIFIED_SWITCHES} 项关闭；未完成 {len(FAILED_STEPS)} 段", flush=True)
