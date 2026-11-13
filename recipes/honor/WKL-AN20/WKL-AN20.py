# 荣耀 WKL-AN20 的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 tap / app_settings / browser_settings / close_named / require / skip 由装载器注入执行作用域。
# 线性段已转成 `.toml` 数据；这里只留过程化的段（safe_ui 坐标手势、settle_page+radio 单选组、
# 条件分支）与模块级钩子，逐字保留原实现。
import copy
from contextlib import contextmanager
import time

from fast import CONFIRM, bounds

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, require, rt, skip, skip_in_safe_mode
    from recipe_nav import browser_settings, tap
    from recipe_strategies import close_named_honor

BUILD = "WKL-AN20 11.0.0.111(SP7C00E110R101P7)"
MODELS = ["WKL-AN20"]

# 各分组这一版改了什么（词库「字典常量里的说明文字」的出处；运行时不用，仅承载说明）。
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

# close_named 的实现按名字注入为 close_named_honor；数据段与 code 段都按旧名 close_named 用。
close_named = close_named_honor


def labels(root=None):
    return {text for text, _, _ in p.texts(root)}


def settle_page(package, *markers, timeout=5):
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


def guard():
    if p.d.shell("getprop ro.product.model").output.strip() not in MODELS:
        skip("型号不匹配，跳过；不使用其他型号的路径")
    if not p.d.shell("getprop ro.build.display.id").output.strip().startswith(BUILD):
        skip("系统版本不匹配，跳过；请重新核对页面")


wrap = safe_ui


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


def tail():
    print(f"\n已回读 {rt.verified} 项；分段结果：{rt.results}", flush=True)
    print("YOYO 新闻资讯、旧版文件夹管理入口未适配；通知渠道、快应用请走 run.py 独立流程。", flush=True)


def step_ad_tracking(p, rt):
    skip_in_safe_mode()
    require(p.setting("广告", "广告与隐私"), "未进入广告与隐私")
    settle_page("com.hihonor.id", "广告与隐私")
    tap("更多选项", scrolls=0)
    if p.find("显示系统程序", exact=True):
        tap("显示系统程序", scrolls=0)
    elif not p.find("隐藏系统程序", exact=True):
        raise RuntimeError("未确认显示系统程序的菜单状态")
    if p.find("隐藏系统程序", exact=True) or p.find("全部关闭", exact=True):
        p.back()
    close_named(None, "广告与隐私·OAID读取权限", "com.hihonor.id", "广告与隐私", max_screens=40)


def step_browser_home(p, rt):
    package = browser_settings()
    tap("模式选择")
    root = settle_page(package, "模式选择", "简洁首页")
    choice = radio(root, "简洁首页")
    if choice.get("checked") != "true":
        require(choice.get("enabled") != "false", "简洁首页选项不可用")
        left, top, right, bottom = bounds(choice)
        p.click((left + right) // 2, (top + bottom) // 2)
        time.sleep(.5)
        require(radio(settle_page(package, "简洁首页"), "简洁首页").get("checked") == "true",
                "回读未确认简洁首页")
        p.changed.append(("浏览器·模式选择", "简洁首页"))


def step_browser_recs(p, rt):
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


def step_search(p, rt):
    p.d.press("home")
    time.sleep(.5)
    p.d.press("home")
    p.tree()
    p.d.swipe(p.W // 2, p.H * 3 // 10, p.W // 2, p.H * 7 // 10, duration=.3)
    time.sleep(1)
    p.d.press("back")
    settle_page("com.hihonor.search", "更多")
    tap("更多", scrolls=0)
    tap("设置", scrolls=0)
    tap("首页显示")
    close_named(["热搜榜", "热搜词推荐"], "搜索·首页显示", "com.hihonor.search", "首页显示")


def step_negative(p, rt):
    package = "com.hihonor.hiboard"
    p.d.press("home")
    time.sleep(.5)
    for _ in range(3):
        if p.focus().split("/", 1)[0] == package and p.find("头像", exact=True):
            break
        p.tree()
        p.d.swipe(p.W // 7, p.H // 2, p.W * 6 // 7, p.H // 2, duration=.3)
        time.sleep(.7)
    settle_page(package, "头像")
    tap("头像", scrolls=0)
    tap("设置", scrolls=0)
    close_named(["智能推荐", "个性化广告", "个性化消息"], "负一屏·设置", package, "设置")
    p.back()
    tap("资讯服务", scrolls=0)
    close_named(["资讯精选"], "负一屏·资讯服务", package, "资讯服务")


def step_reader(p, rt):
    package = "com.hihonor.dz.reader"
    p.start(package)
    require(p.go("我的", "更多设置"), "未找到阅读设置入口")
    tap("更多设置")
    settle_page(package, "广告推荐服务")
    tap("广告推荐服务", scrolls=0)
    close_named(["个性化广告"], "阅读·广告推荐服务", package, "广告推荐服务", drawn=True)


def step_magazine(p, rt):
    require(p.setting("画报", "魔法画报"), "未搜到魔法画报")
    if p.focus().split("/", 1)[0] != "com.hihonor.magazine":
        tap("魔法画报", scrolls=0)
    close_named(["锁屏壁纸轮播", "锁屏进入魔法画报", "数据流量自动更新"],
                "魔法画报", "com.hihonor.magazine", "魔法画报")


def step_music(p, rt):
    if rt.only != ["音乐"]:
        skip("请手动打开荣耀音乐 → 我的 → 设置 → 更多设置，再单段运行「音乐」")
    package = "com.hihonor.cloudmusic"
    settle_page(package, "消息和隐私设置")
    tap("消息和隐私设置")
    close_named(["朋友页显示推荐动态", "展示“摇一摇”类开屏广告"], "音乐·消息和隐私设置", package, "消息和隐私设置")
    tap("广告推荐设置")
    close_named(["个性化广告推荐"], "音乐·广告推荐设置", package, "广告推荐设置")
