# 荣耀 WKL-AN20，MagicOS 11 / Android 17。路径逐项实测：2026-10-28。
# 新脚本整轮待真机复测；音乐须先由机主打开「更多设置」，再单段运行。
# 由 tool/fast.py 注入 p 和 ONLY；不包含通知渠道、挂包或 Scene 激活操作。
BUILD = "WKL-AN20 11.0.0.111(SP7C00E110R101P7)"
MODELS = ["WKL-AN20"]

import copy
from contextlib import contextmanager
import time

import adb_link
from fast import CONFIRM, Phone, bounds, want_state

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []
RESULTS = []
VERIFIED_SWITCHES = 0
HALTED = False
CHANGES = {
    "广告跟踪": "应用的 OAID 读取权限",
    "智能推荐服务": "智能推荐服务",
    "系统管家": "应用推荐",
    "应用市场": "营销服务推荐、个性化服务推荐、营销消息、活动福利、游戏动态、热门推荐管理",
    "浏览器首页": "模式选择 → 简洁首页",
    "浏览器推荐": "精彩推荐、每日推送、新闻热点、兴趣推送、个性化内容、个性化广告、摇一摇广告",
    "视频": "个性化内容、个性化广告、允许视频采集OAID推荐广告",
    "搜索": "热搜榜、热搜词推荐",
    "负一屏": "智能推荐、个性化广告、个性化消息、资讯精选",
    "阅读": "广告推荐服务 → 个性化广告",
    "主题": "个性化内容、个性化广告；内容推荐和活动的消息通知、短信、邮件",
    "魔法画报": "锁屏壁纸轮播、锁屏进入魔法画报、数据流量自动更新",
    "音乐": "朋友页显示推荐动态、展示“摇一摇”类开屏广告、个性化广告推荐",
}


class SkipStep(Exception):
    """本段按约定跳过，不算失败：型号或版本不符，或前面已因锁屏中止。"""


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def labels(root=None):
    return {text for text, _, _ in p.texts(root)}


def page(package, *markers, timeout=5):
    """包名、可见标题和节点位置连续稳定后才使用坐标；不输出账号内容。"""
    deadline, previous = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        require(not p.locked(), "手机锁屏，请机主解锁后重跑")
        root = p.tree()
        texts = p.texts(root)
        if any(text in ("同意", "同意并继续", "同意并使用", "允许")
               and "Button" in node.get("class", "")
               for text, _, node in texts):
            p.dismiss()
            raise RuntimeError("遇到协议或权限申请，未代为同意，本段停止")
        signature = (p.focus(), tuple((text, box) for text, box, _ in texts))
        if signature[0].split("/", 1)[0] == package and set(markers) <= labels(root):
            if texts and signature == previous:
                return root
        previous = signature
        time.sleep(.25)
    raise RuntimeError("未确认目标设置页：" + "、".join(markers))


def tap(text, scrolls=6):
    require(p.tap(text, exact=True, scrolls=scrolls), "未找到入口「" + text + "」")


@contextmanager
def safe_ui():
    """只在本段内使用 u2 手势、原生开关及屏内确认按钮，结束后还原引擎。"""
    original = {name: getattr(p, name) for name in ("click", "scroll", "confirm", "switches")}

    def click(x, y):
        require(not p.locked(), "手机锁屏，未点击")
        require(tuple(p.d.window_size()) == (p.W, p.H), "屏幕尺寸变化，未使用旧坐标")
        require(0 <= x < p.W and 0 <= y < p.H, "按钮在屏外，未点击")
        p.d.click(x, y)

    def scroll(frac=.45, up=False):
        p.tree()
        require(not p.locked(), "手机锁屏，未滑动")
        y1, y2 = int(p.H * .8), int(p.H * (.8 - min(frac, .58)))
        if up:
            y1, y2 = y2, y1
        p.d.swipe(p.W // 2, y1, p.W // 2, y2, duration=.45)
        time.sleep(.25)

    def switches(root=None):
        # 引擎会为自绘 switch 自动截图。默认屏蔽它，导航账号页时也不会截图。
        root = copy.deepcopy(root if root is not None else p.tree())
        for node in root.iter("node"):
            if node.get("checkable") != "true" and "switch" in node.get("resource-id", "").lower():
                node.set("clickable", "false")
        return original["switches"](root)

    def confirm():
        time.sleep(.2)
        root = p.tree()
        visible = labels(root)
        music_dialog = {"关闭个性化广告推荐", "取消"} <= visible
        for text in CONFIRM:
            for node in root.iter("node"):
                if ((node.get("text") or "").strip() != text
                        or node.get("enabled") == "false" or not p.on_screen(node)):
                    continue
                # 音乐的实测确认框里「确定」不一定是 Button；仅在该明确对话框中接受。
                if "Button" not in node.get("class", "") and not (music_dialog and text == "确定"):
                    continue
                left, top, right, bottom = bounds(node)
                p.click((left + right) // 2, (top + bottom) // 2)
                time.sleep(.3)
                return text
        return None

    p.click, p.scroll, p.confirm, p.switches = click, scroll, confirm, switches
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(p, name, value)


def step(name):
    def decorate(action):
        global HALTED
        if ONLY and name not in ONLY:
            return action
        print("\n== " + name + "：将核对并调整「" + CHANGES[name] + "」", flush=True)
        started = time.monotonic()
        status = "未完成"
        try:
            if HALTED:
                raise SkipStep("前面检测到锁屏，后续段已停止")
            model = p.d.shell("getprop ro.product.model").output.strip()
            build = p.d.shell("getprop ro.build.display.id").output.strip()
            if model not in MODELS:
                raise SkipStep("型号不匹配，跳过；不使用其他型号的路径")
            if not build.startswith(BUILD):
                raise SkipStep("系统版本不匹配，跳过；请重新核对页面")
            if p.locked():
                HALTED = True
                raise RuntimeError("手机锁屏，请机主解锁后重跑")
            p.miss = 0
            with safe_ui():
                action()
            status = "已回读"
        except adb_link.DeviceLost:
            raise  # 交还引擎，整轮停止；不继续操作其他应用。
        except SkipStep as error:
            status = "跳过"
            print("  · " + str(error), flush=True)
        except Exception as error:
            FAILED_STEPS.append(name)
            print("  ✗ 未完成：" + str(error), flush=True)
            if p.locked():
                HALTED = True
        RESULTS.append((name, status))
        print(f"  {status}，{time.monotonic() - started:.0f} 秒", flush=True)
        return action
    return decorate


def scan(max_screens):
    states = {}
    for index in range(max_screens):
        for title, state, _ in p.switches():
            require(bool(title), "出现无标题开关，未操作")
            require(title not in states or states[title] == state, "同名开关状态不一致，未操作")
            states[title] = state
        if not p.scroll_more():
            return states
        require(index + 1 < max_screens, "列表超过扫描上限，未确认完整列表")
    return states


def close_named(names, title, package, marker, max_screens=6, drawn=False):
    """精确标题白名单；操作前完整扫描，操作后核对目标及其他开关。"""
    global VERIFIED_SWITCHES
    page(package, marker)
    native = p.switches

    def read(root=None):
        root = root if root is not None else p.tree()
        require(p.focus().split("/", 1)[0] == package and marker in labels(root),
                "已离开目标设置页，停止读取开关")
        # 仅阅读的「广告推荐服务」设置页允许截图识别自绘开关，不写图片文件。
        if drawn:
            require(package == "com.hihonor.dz.reader" and marker == "广告推荐服务",
                    "此页不允许自绘开关截图")
            return Phone.switches(p, root)
        return native(root)

    p.switches = read
    try:
        p.top(max_screens)
        before = scan(max_screens)
        # OAID 的应用名称随安装列表变化，不把机主应用清单写入脚本。
        wanted = set(before) if names is None else set(names)
        require(bool(wanted) and wanted <= before.keys(), title + "：未识别全部目标开关，未操作")
        p.top(max_screens)
        p.switches = lambda root=None: [item for item in read(root) if item[0] in wanted]
        p.off(only=sorted(wanted), page=title, max_screens=max_screens)
        p.switches = read
        p.top(max_screens)
        after = scan(max_screens)
        require(all(after.get(name) == want_state(name) for name in wanted),
                title + "：回读未确认目标状态")
        require(all(after.get(name) == state for name, state in before.items() if name not in wanted),
                title + "：其他开关状态变化，请机主核对")
        VERIFIED_SWITCHES += len(wanted)
        print(f"  · {title}：已回读 {len(wanted)} 项", flush=True)
    finally:
        p.switches = native


def app_settings(package, *markers):
    p.start(package)
    require(p.go("我的", "设置"), "未找到应用设置入口")
    tap("设置", scrolls=0)
    page(package, *markers)


def browser_settings():
    package = "com.honor.browser"
    if p.focus().split("/", 1)[0] == package and {"模式选择", "隐私管理"} <= labels():
        return package
    p.start(package)
    # 本机已验证「更多 → 设置」；经典首页的未知图标位置不猜。
    tap("更多", scrolls=0)
    tap("设置", scrolls=0)
    page(package, "模式选择", "隐私管理")
    return package


def radio(root, text):
    parents = {child: parent for parent in root.iter() for child in parent}
    candidates = []
    for label, label_box, node in p.texts(root):
        if label != text:
            continue
        for _ in range(6):
            choices = [n for n in node.iter("node") if "RadioButton" in n.get("class", "")
                       and n.get("checkable") == "true" and p.on_screen(n)]
            left, top, right, bottom = bounds(node)
            if len(choices) == 1 and right > left and 0 < bottom - top <= p.H * .35:
                _, rt, _, rb = bounds(choices[0])
                require(abs((rt + rb) - (label_box[1] + label_box[3])) <= p.H * .24,
                        "单选按钮与文字不在同一选项区域")
                candidates.append(choices[0])
                break
            node = parents.get(node)
            if node is None:
                break
    unique = {id(node): node for node in candidates}
    require(len(unique) == 1, "未识别「" + text + "」对应的唯一单选按钮")
    return next(iter(unique.values()))


@step("广告跟踪")
def _():
    require(p.setting("广告", "广告与隐私"), "未进入广告与隐私")
    page("com.hihonor.id", "广告与隐私")
    tap("更多选项", scrolls=0)
    if p.find("显示系统程序", exact=True):
        tap("显示系统程序", scrolls=0)
    elif not p.find("隐藏系统程序", exact=True):
        raise RuntimeError("未确认显示系统程序的菜单状态")
    if p.find("隐藏系统程序", exact=True) or p.find("全部关闭", exact=True):
        p.back()  # 菜单仍开着时只收起菜单。
    close_named(None, "广告与隐私·OAID读取权限", "com.hihonor.id", "广告与隐私", max_screens=40)


@step("智能推荐服务")
def _():
    p.start("com.hihonor.id", ".oaid.ui.IntelligentRecommendActivity")
    close_named(["智能推荐服务"], "广告与隐私·智能推荐服务", "com.hihonor.id", "智能推荐服务")


@step("系统管家")
def _():
    package = "com.hihonor.systemmanager"
    p.start(package, ".mainscreen.SettingActivity")
    close_named(["应用推荐"], "系统管家·设置", package, "设置")


@step("应用市场")
def _():
    package = "com.hihonor.appmarket"
    app_settings(package, "内容推荐服务", "消息通知管理")
    tap("内容推荐服务")
    close_named(["营销服务推荐", "个性化服务推荐"], "市场·内容推荐服务", package, "内容推荐服务")
    p.back()
    tap("消息通知管理")
    close_named(["消息通知"], "市场·消息通知管理", package, "消息通知管理")
    p.back()
    tap("消息中心提醒")
    close_named(["活动福利", "游戏动态"], "市场·消息中心提醒", package, "消息中心提醒")
    p.back()
    tap("热门推荐管理")
    close_named(["热门推荐管理"], "市场·热门推荐管理", package, "热门推荐管理")
    # 不切基本服务模式；保留应用更新、安装、下载和服务模式的当前设置。


@step("浏览器首页")
def _():
    package = browser_settings()
    tap("模式选择")
    root = page(package, "模式选择", "简洁首页")
    choice = radio(root, "简洁首页")
    if choice.get("checked") != "true":
        require(choice.get("enabled") != "false", "简洁首页选项不可用")
        left, top, right, bottom = bounds(choice)
        p.click((left + right) // 2, (top + bottom) // 2)
        time.sleep(.5)
        require(radio(page(package, "简洁首页"), "简洁首页").get("checked") == "true",
                "回读未确认简洁首页")
        p.changed.append(("浏览器·模式选择", "简洁首页"))


@step("浏览器推荐")
def _():
    package = browser_settings()
    tap("消息通知")
    close_named(["精彩推荐", "每日推送", "新闻热点", "兴趣推送"], "浏览器·消息通知", package, "消息通知")
    p.back()
    tap("隐私管理")
    tap("个性化推荐", scrolls=0)
    close_named(["个性化内容"], "浏览器·个性化推荐", package, "个性化推荐")
    p.back()
    tap("互动广告管理", scrolls=0)
    close_named(["个性化广告", "允许摇一摇进入广告"], "浏览器·互动广告", package, "互动广告管理")


@step("视频")
def _():
    package = "com.hihonor.youku.video"
    p.start(package, "com.youku.android.youkusetting.activity.SettingsActivity")
    tap("其他设置")
    close_named(["个性化内容", "个性化广告", "允许视频采集OAID推荐广告"], "视频·其他设置", package, "其他设置")


@step("搜索")
def _():
    p.d.press("home")
    time.sleep(.5)
    p.d.press("home")
    p.tree()
    p.d.swipe(p.W // 2, p.H * 3 // 10, p.W // 2, p.H * 7 // 10, duration=.3)
    time.sleep(1)
    p.d.press("back")  # 仅收起搜索键盘，不改搜索功能。
    page("com.hihonor.search", "更多")
    tap("更多", scrolls=0)
    tap("设置", scrolls=0)
    tap("首页显示")
    close_named(["热搜榜", "热搜词推荐"], "搜索·首页显示", "com.hihonor.search", "首页显示")


@step("负一屏")
def _():
    package = "com.hihonor.hiboard"
    p.d.press("home")
    time.sleep(.5)
    for _ in range(3):
        if p.focus().split("/", 1)[0] == package and p.find("头像", exact=True):
            break
        p.tree()
        p.d.swipe(p.W // 7, p.H // 2, p.W * 6 // 7, p.H // 2, duration=.3)
        time.sleep(.7)
    page(package, "头像")
    tap("头像", scrolls=0)
    tap("设置", scrolls=0)
    close_named(["智能推荐", "个性化广告", "个性化消息"], "负一屏·设置", package, "设置")
    p.back()
    tap("资讯服务", scrolls=0)
    close_named(["资讯精选"], "负一屏·资讯服务", package, "资讯服务")


@step("阅读")
def _():
    package = "com.hihonor.dz.reader"
    p.start(package)
    require(p.go("我的", "更多设置"), "未找到阅读设置入口")
    tap("更多设置")
    page(package, "广告推荐服务")
    tap("广告推荐服务", scrolls=0)
    close_named(["个性化广告"], "阅读·广告推荐服务", package, "广告推荐服务", drawn=True)
    # 不操作「接收新通知」，不把通知总开关作为营销渠道的替代方案。


@step("主题")
def _():
    package = "com.hihonor.android.thememanager"
    app_settings(package, "个性化服务", "通知")  # SettingsAC 不允许 shell 直达，走正常界面。
    tap("个性化服务", scrolls=0)
    close_named(["个性化内容", "个性化广告"], "主题·个性化服务", package, "个性化服务")
    p.back()
    tap("通知", scrolls=0)
    close_named(["消息通知", "短信", "邮件"], "主题·内容推荐和活动通知", package, "通知")


@step("魔法画报")
def _():
    require(p.setting("画报", "魔法画报"), "未搜到魔法画报")
    if p.focus().split("/", 1)[0] != "com.hihonor.magazine":
        tap("魔法画报", scrolls=0)
    close_named(["锁屏壁纸轮播", "锁屏进入魔法画报", "数据流量自动更新"],
                "魔法画报", "com.hihonor.magazine", "魔法画报")


@step("音乐")
def _():
    # 此机之前由机主手动打开，未验证从首页可靠自动进入；不复制其他机型的图标位置。
    # 全跑时跳过此段；手动进入「更多设置」后用 recipe 音乐 单独执行。
    if ONLY != ["音乐"]:
        raise SkipStep("请手动打开荣耀音乐 → 我的 → 设置 → 更多设置，再单段运行「音乐」")
    package = "com.hihonor.cloudmusic"
    page(package, "消息和隐私设置")
    tap("消息和隐私设置")
    close_named(["朋友页显示推荐动态", "展示“摇一摇”类开屏广告"], "音乐·消息和隐私设置", package, "消息和隐私设置")
    tap("广告推荐设置")
    close_named(["个性化广告推荐"], "音乐·广告推荐设置", package, "广告推荐设置")
    # 个性化服务保留；第三方推送含评论提醒，不整项关闭。


print(f"\n已回读 {VERIFIED_SWITCHES} 项；分段结果：{RESULTS}", flush=True)
print("YOYO 新闻资讯、旧版文件夹管理入口未适配；通知渠道、快应用请走 run.py 独立流程。", flush=True)
