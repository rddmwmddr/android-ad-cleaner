# OPPO Find X10 Pro Max（PMX110，ColorOS 17.0.0）机型脚本。路径 2026-10-26 实机走通
BUILD = "PMX110_17.0.0"
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
import time
import xml.etree.ElementTree as ET

ONLY = globals().get("ONLY") or []
FAILED_STEPS = globals().get("FAILED_STEPS") or []

SEARCH_PKG = "com.heytap.quicksearchbox"
# 设置页 SearchSettingActivity 没导出，am start -n 会被系统拒绝；这是应用自己的入口
SEARCH_SETTINGS = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
SEARCH_TITLES = {"搜索范围", "功能管理", "首页卡片管理", "消息管理", "账号与隐私"}
CAROUSEL_LABELS = {"显示轮播推荐", "不显示轮播推荐"}


def step(name):
    def deco(f):
        if (not ONLY or name in ONLY) and p.locked():
            print(f"\n== {name}：手机锁屏了，后面的都不跑"); return f
        if not ONLY or name in ONLY:
            print(f"\n== {name}"); p.miss = 0
            t = time.time()
            try:
                f()
            except Exception as e:
                print(f"  ✗ 出错：{e}"); FAILED_STEPS.append(name)
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


def find_tap(text, scrolls=10, exact=True):
    """只找不点、逐屏往下翻，找到了才点。
    这一页顶部有「有 N 个应用存在过度授权」横幅，用 p.tap 翻页会误点进去（那页有「一键优化」，不能碰）。"""
    for i in range(scrolls + 1):
        xy = p.find(text, exact=exact)
        if xy:
            p.click(*xy); time.sleep(1.6)
            return True
        if i < scrolls and not p.scroll_more():
            break
    p.say(f"  ✗ 没找到「{text}」")
    return False


def tap_row(text, scrolls=6):
    """ColorOS 17 的设置列表里，标题文字自己不可点，要点它所在的那一行。"""
    from fast import bounds
    time.sleep(0.8)                      # 刚进的页面还没画完，上来就找会白跑一趟
    try:
        p.top(6)                         # 从二级页回来时列表停在中间，不回顶会漏掉上面的项
    except Exception:                    # 回顶时页面变了就当没回成，继续找
        pass
    for i in range(scrolls + 1):
        root = p.tree()
        parent = {c: pp for pp in root.iter() for c in pp}
        for n in root.iter("node"):
            if (n.get("text") or "").strip() != text:
                continue
            m = n
            while m is not None and m.get("clickable") != "true":
                m = parent.get(m)
            m = n if m is None else m       # 没有可点的那一行：点文字本身
            l, t, r, b = bounds(m)
            if b > t and t < p.H * 0.95:
                p.click((l + r) // 2, (t + b) // 2); time.sleep(1.5)
                return True
        if i < scrolls and not p.scroll_more():
            break
    p.say(f"  ✗ 没找到「{text}」")
    return False


def wait_search_settings(timeout=6):
    """认「全局搜索的设置页」：前台是本包的 Setting 页，且页面上认得出设置项标题。
    同包的搜索首页也有「搜索范围」这类文字，只看文字会把首页当成设置页。"""
    from wait import until

    def sample():
        where = p.focus()
        if SEARCH_PKG not in where or "Setting" not in where.split("/", 1)[-1]:
            return False
        try:
            return bool(SEARCH_TITLES & {t.strip() for t, _, _ in p.texts()})
        except ET.ParseError:          # 半截 dump：还没画完，下一轮再看
            return False

    return bool(until(sample, timeout=timeout, poll=0.4, now=time.monotonic, sleep=time.sleep))


def dismiss_guide(timeout=4):
    """首次进游戏中心会弹引导浮层，不点掉会盖住「我的」和齿轮。没有浮层时直接放行。"""
    from wait import until
    if not p.find("跳过", exact=True):
        return True
    if not p.tap("跳过", exact=True, scrolls=0):
        return False
    return bool(until(lambda: not p.find("跳过", exact=True), timeout=timeout, poll=0.3,
                      now=time.monotonic, sleep=time.sleep))


def tap_gear():
    """右上齿轮：没有文字标题，只有「设置」这两个字的无障碍名或 setting 资源名。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        cd = (n.get("content-desc") or ""); rid = (n.get("resource-id") or "").lower()
        key = cd + " " + (n.get("text") or "") + " " + rid
        if ("设置" in key or "setting" in key) and n.get("clickable") == "true":
            if bounds(n)[1] > p.H * 0.25:
                continue
            l, t, r, b = bounds(n)
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1.5)
            return True
    return False


def menu(word):
    """右上「更多选项」菜单。菜单项的文字在 content-desc 里，还带「已停用」这类状态后缀。"""
    opened = p.tap("更多选项", exact=True, scrolls=0) or p.tap("更多", exact=True, scrolls=0)
    if not opened:
        p.say("  ✗ 没找到菜单入口"); return False
    ok = p.tap(word, scrolls=0)
    time.sleep(1.2)
    if not ok:
        p.back()                      # 菜单还开着就收掉，别挡着列表
    return ok


def carousel_choices():
    """轮播单选：只认按钮自己那一行的标签，不合并祖先子树的文字。
    这一页的父容器会把「显示轮播推荐 / 不显示轮播推荐」并成一段，按子串匹配会让「显示」那一项
    也命中「不显示」，点下去等于把轮播又打开（#280）。预览图里的同名文字不是可点目标。"""
    from fast import bounds
    root = p.tree()
    parents = {c: n for n in root.iter() for c in n}
    choices = {}
    for node in root.iter("node"):
        if node.get("checkable") != "true" or "RadioButton" not in (node.get("class") or ""):
            continue
        row = node
        for _ in range(5):
            captions = {x.get("text") or "" for x in row.iter("node")} | {
                x.get("content-desc") or "" for x in row.iter("node")}
            matched = captions & CAROUSEL_LABELS
            if len(matched) == 1:
                name = matched.pop()
                if name in choices:
                    raise RuntimeError("轮播单选项不唯一，未点击")
                if not p.on_screen(node) or node.get("enabled") != "true":
                    raise RuntimeError("轮播单选项不可操作")
                if node.get("checked") not in ("true", "false"):
                    raise RuntimeError("轮播单选状态未知，未点击")
                choices[name] = (node.get("checked") == "true", bounds(node))
                break
            row = parents.get(row)
            if row is None or len(matched) > 1:
                break
    if set(choices) != CAROUSEL_LABELS or sum(on for on, _ in choices.values()) != 1:
        raise RuntimeError("无法确认轮播单选状态，未点击")
    return choices


def pick_radio(target):
    """把轮播推荐改到 target（「不显示轮播推荐」/「显示轮播推荐」）；回读没改过来就报失败。"""
    where = p.focus()
    on, (l, t, r, b) = carousel_choices()[target]
    if on:
        print(f"  · 轮播推荐已经是「{target}」，不动")
        return True
    if p.focus() != where:                    # 读到坐标之后页面换了，坐标就作废
        raise RuntimeError("单选页在读取与点击之间变化，未点击")
    p.click((l + r) // 2, (t + b) // 2); time.sleep(1.2)
    if not carousel_choices()[target][0]:
        raise RuntimeError(f"「{target}」回读未选中，不当作已关闭")
    print(f"  · 轮播推荐：已改为「{target}」")
    return True


@step("广告跟踪")
def _():
    # 每个 App 一个开关、没有总开关；默认不显示系统应用，菜单里的「全部关闭」一次只关当前可见的那些
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.5)
    if not p.tap("隐私与安全", exact=True, scrolls=2):
        FAILED_STEPS.append("广告跟踪"); return
    # 进到「隐私与安全」页默认就在「隐私」标签上，不用再点标签
    if find_tap("设备标识与广告", scrolls=10) and p.tap("广告跟踪", exact=True, scrolls=0):
        menu("全部关闭")                 # 第一轮：关掉用户应用
        if menu("显示系统应用"):          # 找不到说明菜单已写作「隐藏系统应用」，即正在显示
            time.sleep(1.5)
            menu("全部关闭")             # 第二轮：把系统应用也关掉
        p.top(); time.sleep(1)
        still = [k for k, c, _ in p.switches() if c]
        print(f"  · 复查：这一屏仍开着 {len(still)} 个")
        p.back(3)
    else:
        FAILED_STEPS.append("广告跟踪")


@step("负一屏")
def _():
    p.d.shell("input keyevent HOME"); time.sleep(0.6); p.d.shell("input keyevent HOME"); time.sleep(0.6)
    for _ in range(3):
        p.d.shell(f"input swipe 8 {p.H//2} {int(p.W*0.75)} {p.H//2} 700"); time.sleep(1.5)
        if any(t in " ".join(x[0] for x in p.texts()) for t in ("一键清理", "应用建议", "热点资讯")):
            break
    # 左上头像（资源名 head_icon）→ 设置
    from fast import bounds
    av = [n for n in p.tree().iter("node") if (n.get("resource-id") or "").endswith("head_icon")]
    if av:
        l, t, r, b = bounds(av[0]); p.click((l + r) // 2, (t + b) // 2); time.sleep(1.5)
    if p.tap("设置", exact=True, scrolls=0):
        p.off(only=["搜索框提示词"], page="负一屏")
        # ⚠ 「推荐服务」总开关不要关：会删掉天气/步数/清理卡片
        if tap_row("推荐服务", scrolls=6):
            try:
                pick_radio("不显示轮播推荐")
            except RuntimeError as e:            # 轮播没改不影响同段的热点资讯，但要如实记失败
                print(f"  ✗ 轮播推荐没改成：{e}")
                FAILED_STEPS.append("负一屏")
            p.back()
        if tap_row("热点资讯", scrolls=6):   # 二级页，里面才是总开关
            p.off(only=["热点资讯"], page="负一屏·热点资讯")
            p.back()
    else:
        FAILED_STEPS.append("负一屏")
    p.back(3)


def search_sources():
    """借给别的机型（安全模式）时只关推荐位：ColorOS 17 上榜单 / 小说 / 购物是内容源，关掉会搜不到东西。"""
    if p.safe_mode:
        return ["个性化推荐", "精选资讯"]
    return ["榜单", "小说", "购物", "个性化推荐", "精选资讯"]


@step("下拉搜索")
def _():
    # 设置页 SearchSettingActivity 没有导出，am start -n 会被系统拒绝；走应用自己的 scheme 直达。
    # ⚠ 不要退回桌面下滑找搜索页底部入口：这台机器上滑会被输入法当成输入、或直接退出搜索页
    p.d.shell(SEARCH_SETTINGS); time.sleep(1.5)
    if not wait_search_settings():
        print(f"  ✗ 没落到全局搜索设置页（当前前台：{p.focus()}），本段跳过")
        FAILED_STEPS.append("下拉搜索")
        return
    if tap_row("搜索范围", scrolls=3):
        p.off(only=search_sources(), page="下拉搜索·搜索范围")
        p.back()
    if tap_row("首页卡片管理", scrolls=4):
        p.off(only=["未下载应用推荐", "应用建议小卡", "探索发现", "活动皮肤", "每日热榜", "推荐卡片"],
              page="下拉搜索·首页卡片管理")
        p.back()
    if tap_row("功能管理", scrolls=4):
        p.off(only=["搜索框提示词"], page="下拉搜索·功能管理")
        p.back()
    if tap_row("消息管理", scrolls=4):
        p.off(only=["消息通知"], page="下拉搜索·消息管理")
        p.back()
    if tap_row("账号与隐私", scrolls=4) and p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="下拉搜索·隐私")
        p.back(2)
    p.back(2)


STORE_KEEP = ["帮助与客服", "应用安全", "应用工具", "存储空间清理", "我的资产", "安全守护",
              "小i客服", "应用使用记录", "首页 AI 搜索", "自动检测风险应用"]


@step("软件商店")
def _():
    p.start("com.heytap.market")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    # 用 tap_row 而不是 p.tap：这一页长，p.tap 翻页后会回顶，会被当成「离开了设置页」而中断
    if tap_row("隐私", scrolls=8):
        p.tap("个性化推荐", exact=True)          # 二级页，开关在里面
        p.off(only=["个性化推荐"], page="商店·个性化推荐")
        p.back()
    # 「服务管理」在设置页，从个性化推荐回来只退到了隐私页：找不到就再退一级
    if not tap_row("服务管理", scrolls=8):
        p.back(); time.sleep(1.2)
        if not tap_row("服务管理", scrolls=8):
            FAILED_STEPS.append("软件商店")
            p.back(2); return
    p.off(keep=STORE_KEEP, page="商店·服务管理")
    p.off(only=["安全内容推荐"], page="商店·服务管理")
    p.back(2)


@step("浏览器")
def _():
    p.start("com.heytap.browser", ".settings.component.BrowserPreferencesPage")
    if p.tap("隐私", exact=True):
        if p.tap("广告管理", exact=True):
            p.off(only=["开屏广告", "资讯列表广告", "摇一摇"], page="浏览器·广告管理")
            p.back()
        if p.tap("个性化管理", exact=True):
            p.off(only=["个性化广告推荐", "个性化内容推荐"], page="浏览器·个性化管理")
            p.confirm()                          # 「要关闭个性化广告推荐吗？」→ 继续关闭
            p.back()
        p.back()
    p.back()


@step("主题")
def _():
    p.start("com.heytap.themestore")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if tap_row("服务管理", scrolls=6) and p.tap("消息与广告", exact=True):
        p.off(only=["消息通知", "开屏广告"], page="主题·消息与广告")
        p.back(2)
    if tap_row("隐私", scrolls=6):
        p.off(only=["个性化推荐设置"], page="主题·隐私")   # 这一项本身就是开关，不进二级页
        p.confirm()
        p.back()
    p.back(2)


@step("视频")
def _():
    p.start("com.heytap.yoli")
    p.go("我的", "设置")
    p.tap("设置", exact=True)
    if tap_row("个性化管理", scrolls=6):
        p.off(only=["个性化广告推荐", "个性化内容推荐"], page="视频·个性化")
        p.confirm()
    p.back(3)


@step("游戏中心")
def _():
    p.start("com.nearme.gamecenter")
    dismissed = dismiss_guide()                   # 首进引导浮层：首页可能弹一次、切「我的」也可能再弹
    p.tap("我的", exact=True, scrolls=0)          # 底部标签
    dismissed = dismiss_guide() and dismissed
    if not dismissed:
        print("  ✗ 首进引导浮层没关掉，齿轮被挡住，本段跳过")
        FAILED_STEPS.append("游戏中心")
        p.back(2); return
    if tap_gear():                                # 右上齿轮，无障碍名是「设置,有新通知」
        time.sleep(1.2)
        if tap_row("隐私", scrolls=6) and tap_row("隐私开关设置", scrolls=4):
            if tap_row("个性化推荐管理", scrolls=4):
                p.off(only=["个性化推荐"], page="游戏中心·个性化")
                p.confirm()                       # 「继续关闭」
            p.back(2)
        else:
            FAILED_STEPS.append("游戏中心")
        p.back(2)
    else:
        FAILED_STEPS.append("游戏中心")


@step("小布建议")
def _():
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.5)
    if p.tap("OPPO AI", exact=True, scrolls=6) and p.tap("小布建议", exact=True, scrolls=3):
        if p.tap("资讯服务", exact=True):         # 在「内容资讯」分组里
            p.off(only=["资讯服务"], page="小布建议·资讯服务")   # 商圈服务保留
            p.back(2)
            return
    FAILED_STEPS.append("小布建议")
