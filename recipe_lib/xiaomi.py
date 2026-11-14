"""xiaomi 家族库（#1269）：只被 xiaomi 家族用到的实现住在这里。

上半是词汇（原 `recipe_nav`），下半是策略（原 `recipe_strategies` / `recipe_steps`）。
跨家族用到的实现不放在这里，见 `recipe_lib/shared.py`。
"""

from wait import until
from entries import reach
from recipe_runtime import SkipStep
from recipe_lib.shared import _style, close_named_step, gear, maybe, opened, read_switches

__all__ = ('bottom_tab', 'browser_settings_xiaomi', 'browser_start', 'by_id', 'close_with_plain_tap', 'direct_settings', 'downloads', 'downloads_probe', 'downloads_tap', 'gear_tap', 'global_search', 'menu_settings', 'mine_settings', 'negative_screen', 'popup_row', 'security_center', 'security_tab', 'settings_icon_visible', 'store', 'store_mode', 'system_ads_security', 'tab', 'tab_bot', 'tap_any', 'tap_bottom_tab', 'tap_low', 'tap_tab', 'theme', 'theme_settings', 'wait_bottom_tab', 'weather_calendar_probe', 'weather_calendar_tap')

# ---------- 词汇 ----------
def tap_any(p, rt, *names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(p, rt, n, scrolls) for n in names)

def mine_settings(p, rt, tries=2):
    """底栏「我的」→ 「设置」，点完必须认出设置页（沿用 #586）。

    不校验的话，点击被吞、或点在了别的面板上，都会当成已经进了设置页：后面几页入口全部
    找不到，整段 0 项又不报错。没落进设置页就退回来重开「我的」再点一次，两次都不成就报当前页。"""
    stopped = ""
    for _ in range(tries):
        if not p.tap("我的", exact=True, scrolls=0):
            raise RuntimeError("未找到浏览器「我的」")
        if not p.tap("设置", exact=True, scrolls=0):
            raise RuntimeError("未找到浏览器「设置」")
        if p.in_settings_page():
            return
        stopped = p.focus()
        p.back()
    raise RuntimeError(f"浏览器设置页没有打开；停在 {stopped}")

def menu_settings(p, rt, tries=2):
    def tap_style(tries, evidence):
        stopped = None
        for _ in range(tries):
            if not p.tap("菜单", exact=True, scrolls=0, quiet=True):
                if stopped is None:
                    return False
                raise RuntimeError("浏览器设置页没有打开；"
                                   + (p.page_evidence() if evidence else f"停在 {stopped}"))
            xy = popup_row(p, rt, "设置", below=0.3)
            if not xy:
                raise RuntimeError("浏览器菜单里没有「设置」；"
                                   + (p.page_evidence() if evidence else f"停在 {p.focus()}"))
            before = p.sig()
            p.click(*xy)
            p.settle(before, 1.5)
            if p.in_settings_page():
                return True
            # 弹窗这一行在屏上才走到这里，所以按返回是收起弹窗或退出面板，不会离开浏览器首页
            # focus 读不出前台时是空串，别让它被当成「还没进过弹窗」
            current = p.focus()
            stopped = current if evidence else (current or "读不出前台")
            p.back()
        raise RuntimeError("浏览器设置页没有打开；"
                           + (p.page_evidence() if evidence else f"停在 {stopped}"))
    def ids_style(tries):
        stopped = ""
        for _ in range(tries):
            if not by_id(p, rt, "com.android.browser:id/action_more"):
                raise RuntimeError("浏览器底部「菜单」未找到")
            if not by_id(p, rt, "com.android.browser:id/action_menu_setting"):
                raise RuntimeError("菜单弹窗里的「设置」未找到")
            rt.clock.sleep(2)
            if p.in_settings_page():
                return
            stopped = p.focus()
            p.back()
        raise RuntimeError(f"浏览器设置页没有打开；停在 {stopped}")
    """底栏「菜单」→ 弹窗里的「设置」，点完必须认出设置页（沿用 #586）。

    工具栏右上角也有一个叫「设置」的图标，弹窗还没画出来时按文字点会落到它上面、进首页编辑面板，
    后面几页入口全部找不到，整段 0 项又不报错。所以只点下半屏那一行，且没落进设置页就退回来
    重开菜单再试；两次都不成就报当前页，不在工具栏面板上继续找。
    底栏没有「菜单」的机型（MIX Flip 2）返回 False，交给 browser_settings() 的「我的」入口（沿用 #833）。
    `evidence` 用整页现场报错（沿用 #939），`focus` 只写停在哪；`ids` 按 resource-id 点两个按钮。"""
    style = _style(rt, "MENU_STYLE", ("evidence", "focus", "ids"), "evidence")
    if style == "ids":
        return ids_style(tries)
    return tap_style(tries, style == "evidence")

def browser_settings_xiaomi(p, rt):
    def toolbar_flow():
        """先看工具栏，再点底部「我的」；不把资讯正文里的「我的」当导航标签。"""
        before = p.focus()
        if gear(p, rt, toolbar_only=True):
            if p.in_settings_page():          # 点完要认出设置页，点击被吞时别在旧页上找入口（沿用 #331）
                return True
            if p.focus() != before:
                p.back()
        for text, (l, t, r, b), _node in p.texts():
            if text == "我的" and t >= p.H * 0.65:
                before = p.sig()
                p.click((l + r) // 2, (t + b) // 2)
                p.settle(before, 1.5)
                return gear(p, rt)
        return False
    def menu_flow():
        """底栏「菜单」→ 弹窗「设置」；底栏没有「菜单」的机型在「我的」页里找设置（沿用 #833）。

        借这份脚本的机型底栏布局不同：Xiaomi 15 是 主页/视频/AI搜索/菜单/我的，MIX Flip 2 是
        主页/视频/AI搜索/免费小说/我的。两条入口点完都要认出设置页；「我的」那条没进去时报出
        停在哪一页，不在旧页上继续找「隐私和安全」等子项（沿用 #586）。"""
        if menu_settings(p, rt):
            return
        print("  · 底栏没有「菜单」，改走「我的」→ 设置", flush=True)
        evidence = _style(rt, "MENU_STYLE", ("evidence", "focus", "ids"), "evidence") == "evidence"
        if not p.tab("我的"):
            raise RuntimeError("浏览器底部没有「菜单」，也没有「我的」标签；"
                               + (p.page_evidence() if evidence else f"停在 {p.focus()}"))
        p.dismiss()                       # 「我的」页可能先弹一键登录框，盖住齿轮
        if not gear(p, rt):
            raise RuntimeError("浏览器设置页没有打开；"
                               + (p.page_evidence() if evidence else f"停在 {p.focus()}"))
    def mine_flow():
        """底部「我的」→ 设置。底栏没有「我的」、或那一页认不出设置页时返回 False。"""
        if not p.tab("我的"):
            return False
        rt.clock.sleep(1)
        return gear(p, rt)
    flow = _style(rt, "BROWSER_FLOW", ("toolbar", "menu", "mine"), "toolbar")
    return {"toolbar": toolbar_flow, "menu": menu_flow, "mine": mine_flow}[flow]()

def browser_start(p, rt):
    """冷启动偶发被启动过渡窗判断成「离开前台」：先强停再直达 BrowserActivity，重试一次。"""
    for attempt in range(2):
        try:
            p.start("com.android.browser", ".BrowserActivity")
            return True
        except SkipStep:
            raise                 # App 本机没装：放行，不走下面那句按文案判的重试分支（沿用 #908）
        except RuntimeError as e:
            if attempt or "离开前台" not in str(e):
                raise
            p.d.shell("am force-stop com.android.browser")
            rt.clock.sleep(1.5)
    return False

def tab(p, rt, name):
    """点顶部分栏标签（隐私 / 安全）。
    页面里同名文字常有两个（分栏标签 + 下面分组标题），取屏幕最上面那个。"""
    cand = []
    for text, (l, t, r, b), _node in p.texts():
        if text == name and t < p.H * 0.40:
            cand.append((t, (l + r) // 2, (t + b) // 2))
    if not cand:
        return False
    cand.sort()
    p.click(cand[0][1], cand[0][2]); rt.clock.sleep(1.2)
    return True

def tab_bot(p, rt, name):
    """按屏幕底部 1/10 区域找标签（主题商店无障碍名带「未选中,」前缀，exact 文本够不着）。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("text") or "")
        if (d == name or d.endswith("," + name) or d.endswith("，" + name)) and p.on_screen(n):
            l, t, r, b = bounds(n)
            if b > p.H * 0.85:
                p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1.5)
                return True
    return False

def tap_bottom_tab(p, rt, name):
    """按屏幕底部标签栏找入口，避开内容区里同名的普通文字。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("text") or "")
        if not d or name not in d:
            continue
        l, t, r, b = bounds(n)
        if b > p.H * 0.85 and p.on_screen(n):
            p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1.5)
            return True
    return False

def wait_bottom_tab(p, rt, name, tries=5):
    """主题商店冷启动先出开屏或更新层，底部栏可能晚几秒才稳定。"""
    for _ in range(tries):
        p.dismiss()
        if tap_bottom_tab(p, rt, name):
            return True
        rt.clock.sleep(0.8)
    return False

def bottom_tab(p, rt, name='我的'):
    """点底部标签。这些 App 的标签文字能找到，但点进去后没有带文字的「设置」，
    所以不能写 p.go("我的", "设置")。"""
    for t, (l, top, r, b), _n in p.texts():
        if t.strip() == name and top > p.H * 0.85:
            p.click((l + r) // 2, (top + b) // 2); rt.clock.sleep(2.5)
            return True
    return False

def by_id(p, rt, rid, wait=1.5):
    """按 resource-id 点控件：这台浏览器工具栏和弹窗里各有一个叫「设置」的图标，按文字会点错。"""
    from fast import bounds
    t0 = rt.clock.time()
    while rt.clock.time() - t0 < wait:
        for n in p.tree().iter("node"):
            if n.get("resource-id") == rid:
                l, t, r, b = bounds(n)
                p.click((l + r) // 2, (t + b) // 2)
                return True
        rt.clock.sleep(0.2)
    return False

def tap_low(p, rt, name, tries=3):
    """页底最后那一项（商店的「隐私设置」）：读屏读得到，但坐标超过引擎的点击安全线，
    要轻滑一小段再点。别用 tap(scrolls=N)：它翻页会直接翻过这一项，翻进「功能设置」子页。"""
    for _ in range(tries):
        if p.tap(name, exact=True, scrolls=0):
            return True
        p.d.shell("input swipe 600 2000 600 1700 150"); rt.clock.sleep(0.7)
    return False

def settings_icon_visible(p, rt):
    """「设置」入口进了界面树且可见：只等它出现，点不点得中由 gear() 再判。

    判据是 icon_hit()（与 gear() 同一份），但不管可点性与位置——这两条留给 gear()。"""
    from fast import icon_hit
    return any(icon_hit(n) and p.on_screen(n) for n in p.tree().iter("node"))

def theme_settings(p, rt, tries=2):
    """主题「我的」→ 顶部「设置」图标，两次都不成才报错（沿用 #912）。

    底栏「我的」只有 content-desc（读作「未选中,我的」），内容区另有「我的点赞 / 我的收藏 /
    我的订单」——`go("我的")` 走包含匹配，会先点内容区那一行；`tab()` 只认屏底带，命中的是底栏。
    点进「我的」后图标要晚一帧才进树，gear() 只读一次树，所以先等图标出现再交给它。"""
    for _ in range(tries):
        if not p.tab("我的"):
            raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
        p.dismiss()                   # 「我的」页可能先弹登录 / 引导弹窗，盖住图标
        until(lambda: settings_icon_visible(p, rt), timeout=3, poll=0.3, now=rt.clock.time, sleep=rt.clock.sleep)
        if gear(p, rt):
            return
    raise RuntimeError("主题设置入口没找到；" + p.page_evidence())

def direct_settings(p, rt):
    """浏览器设置页能直达就直达（沿用 #912）。

    直达档取自 entries 的浏览器分组，只试直达不试设置搜索：设置搜索会离开浏览器、落到
    系统设置里，拿到的不是这一页。直达不通返回 False，由调用方按「菜单」→「我的」回退。
    报告者实测那两条回退对时序敏感：点完底栏「我的」立刻点「设置」会点空，隔 0.2 秒才稳。"""
    if reach(p, rt.constants['BROWSER_SETTINGS_ENTRY'], allow_search=False) != "direct":
        return False
    print("  · 直达浏览器设置页", flush=True)
    return True

def _xiaomi_read_switches(p, rt, max_screens):
    current = {}
    for index in range(max_screens):
        current.update({title: on for title, on, _ in p.switches()})
        if index + 1 == max_screens or not p.scroll_more():
            break
    return current

def _xiaomi_close_named(p, rt, names, page, max_screens=2):
    """只关闭点名的开关；操作前确认目标存在，操作后回读，并检查其他开关未被改动。
    开关标题可能附带整段说明，所以按关键词匹配，不做完整标题相等判断。"""
    p.top(max_screens)
    before = read_switches(p, rt, max_screens)
    targets = [title for title in before if any(name in title for name in names)]
    rt.require_switches(before, names, page, contains=True)
    p.top(max_screens)
    p.off(only=names, page=page, max_screens=max_screens)
    p.top(max_screens)
    current = read_switches(p, rt, max_screens)
    rt.require(all(current.get(title) is False for title in targets), f"{page}：回读未确认关闭")
    rt.require(all(current.get(title) == state for title, state in before.items() if title not in targets),
                 f"{page}：其他开关状态变化，请核对")
    rt.confirm(len(targets))

def security_tab(p, rt):
    """HyperOS 3 的「安全」是隐私页上方的标签，不是设置行。
    按文字点会命中不可点击的标签文字；这里只点横跨半屏、位于顶部的可点击容器。"""
    for text, (l, t, r, b), node in p.texts():
        if (text == "安全" and node.get("clickable") == "true"
                and r - l > p.W * 0.3 and t < p.H * 0.25):
            p.click((l + r) // 2, (t + b) // 2)
            rt.clock.sleep(0.8)
            return True
    return False

def popup_row(p, rt, text, timeout=3.0, below=0.0):
    """浮层里文字正好是 text 的那一行；below 是它必须落在屏高多少比例以下。

    底栏菜单弹窗从底部升起，工具栏上的同名图标在上半屏，那种场景传 below=0.3 把上半屏排掉；
    天气的「更多设置」浮层从右上锚点往下展开，位置不固定在屏底，所以默认不设下限。
    刚打开的浮层里等入口不要用 scrolls=0 的 p.tap()（它等待期间会 dismiss 掉浮层，docs/04）。"""
    def row():
        for t, (l, top, r, b), _n in p.texts():
            if t == text and top > p.H * below:
                return (l + r) // 2, (top + b) // 2
        return None
    return until(row, timeout=timeout, poll=0.3, now=rt.clock.time, sleep=rt.clock.sleep)

def tap_tab(p, rt, name):
    """点顶部标签页：内层文字节点不可点，点外层的可点容器。"""
    for n in p.tree().iter("node"):
        if n.get("clickable") != "true":
            continue
        label = (n.get("text") or "") + (n.get("content-desc") or "")
        from fast import bounds
        l, t, r, b = bounds(n)
        if name in label and t < p.H * 0.3 and p.on_screen(n):
            p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1)
            return True
    return p.tap(name, exact=True, scrolls=0)

# ---------- 策略 ----------
def close_with_plain_tap(p, rt, names, page):
    """下载管理和浏览器会吞掉短按；普通 tap 后确认，并核对其他开关未变。"""
    before = {title: on for title, on, _ in p.switches()}
    targets = [title for title in before if any(name in title for name in names)]
    rt.require_switches(before, names, page, contains=True)
    for title in targets:
        if not before[title]:
            continue
        xy = next((xy for t, on, xy in p.switches() if t == title and on), None)
        if not xy:
            raise RuntimeError(f"{page}：目标开关位置未识别，停止本页")
        p.d.shell(f"input tap {xy[0]} {xy[1]}")
        rt.clock.sleep(0.5)
        p.confirm()
    after = {title: on for title, on, _ in p.switches()}
    if any(after.get(title) is not False for title in targets):
        raise RuntimeError(f"{page}：回读未确认关闭")
    if any(after.get(title) != state for title, state in before.items() if title not in targets):
        raise RuntimeError(f"{page}：其他开关状态变化，请核对")
    turned = [title for title in targets if before[title] and after.get(title) is False]
    for title in turned:
        print(f"  关 {title}")
        p.changed.append((page, title))
    print(f"  · {page}：核对 {len(targets)} 项，调整 {len(turned)} 项")

def gear_tap(p, rt, pkg, activity):
    """齿轮用引擎短按点不动时的兜底：同一次读屏里找到齿轮，改用 input tap（80 毫秒短按有的 App 会吞）。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        text = (n.get("text") or "").strip()
        desc = (n.get("content-desc") or "").strip()
        if text == "设置" or desc == "设置":
            l, t, r, b = bounds(n)
            if not p.on_screen(n):
                continue
            p.d.shell(f"input tap {(l + r) // 2} {(t + b) // 2}")
            rt.clock.sleep(1.2)
            return p.focus().split("/", 1)[0] == pkg and activity in p.focus()
    return False

def negative_screen(p, rt):
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框、出行助手保留
    if maybe(p, rt, "隐私设置"):
        p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
    p.back()

def global_search(p, rt):
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if maybe(p, rt, "首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if maybe(p, rt, "应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐")
            p.back()
        if maybe(p, rt, "热搜榜单"):
            # 同一页既有「推荐」开关又有热搜/生活/话题/娱乐子页，二者都要处理（Issue #21）。
            subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
            if p.switches():
                p.off(only=rt.constants['HOT'], page="搜索·热搜榜单")
            if subs:
                p.top()
                for x in subs:
                    if maybe(p, rt, x):
                        p.off(only=rt.constants['HOT'], page=f"搜索·热榜·{x}")
                        p.back()
            p.back()
        p.back()
    p.back(2)

def security_center(p, rt):
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    if maybe(p, rt, "隐私设置"):
        p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
    if maybe(p, rt, "垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
    p.back(2)

def downloads(p, rt):
    p.start("com.android.providers.downloads.ui")
    if not gear(p, rt):
        raise RuntimeError("下载管理设置入口未找到")
    if maybe(p, rt, "信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)

def downloads_probe(p, rt):
    if opened(p, rt, lambda: p.start("com.android.providers.downloads.ui",
                                   ".activity.InfoFlowSettingActivity",
                                   expect="资源推荐", budget=2)):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
        p.back()
        return
    p.start("com.android.providers.downloads.ui")
    if not gear(p, rt):
        raise RuntimeError("下载管理设置入口未找到")
    if maybe(p, rt, "信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)

def downloads_tap(p, rt):
    p.start("com.android.providers.downloads.ui")
    rt.clock.sleep(1.5)
    rt.require(p.tap("更多", exact=True, scrolls=0), "下载管理「更多」按钮没找到")
    rt.clock.sleep(1.0)
    rt.require(p.tap("设置", exact=True, scrolls=0), "下载管理弹窗里的「设置」没找到")
    rt.clock.sleep(1.2)
    if maybe(p, rt, "信息流设置"):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)

def theme(p, rt):
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    rt.start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                       dead_ends=rt.constants['THEME_DEAD_ENDS'], reason="主题页打不开")
    # 导航失败以前与「本页没有目标开关」同形：进「我的」、进设置页、点名开关三步都校验，
    # 0 个开关按失败报并带页面现场（#906）。
    if not p.go("我的", "设置"):
        raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
    if not gear(p, rt):
        raise RuntimeError("主题设置入口没找到；" + p.page_evidence())
    p.await_page()                              # 齿轮点完这一页可能还没画完
    before = {}
    for _ in range(2):                          # 行也可能在首屏之下，off() 自己会翻页找
        before.update({title: on for title, on, _ in p.switches()})
        if not p.scroll_more():
            break
    p.top(2)
    rt.require_switches(before, ["每次联网时通知"], "主题·设置", contains=True)
    p.off(only=["每次联网时通知"], keep=["自动更新"], page="主题·设置")
    if maybe(p, rt, "隐私设置"):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)

def weather_calendar_tap(p, rt):
    p.start("com.miui.weather2")
    if p.tap("更多设置", exact=True, scrolls=0):
        rt.clock.sleep(1.2)
        if p.tap("设置", exact=True, scrolls=0):
            rt.clock.sleep(1.2)
            if p.tap("用户体验计划", exact=True, scrolls=6):
                rt.clock.sleep(1.0)
                p.off(only=["天气视频卡片", "内容推广"], page="天气·用户体验计划")
                p.back()
            p.back(2)
    p.start("com.android.calendar")
    if p.tap("设置", exact=True, scrolls=0):
        rt.clock.sleep(1.0)
        if p.tap("设置", exact=True, scrolls=0):
            rt.clock.sleep(1.2)
            if p.tap("用户体验计划", exact=True, scrolls=6):
                rt.clock.sleep(1.0)
                p.off(only=["内容推广"], page="日历·用户体验计划")
                p.back()
            p.back(2)

def weather_calendar_probe(p, rt):
    for pkg in ("com.miui.weather2", "com.android.calendar"):
        if pkg == "com.android.calendar" and opened(p, rt, 
                lambda: p.start("com.android.calendar", ".settings.UserExperienceActionBarActivity",
                                expect="内容推广", budget=2)):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"],
                  page=f"{pkg}·用户体验计划"); p.back()
            continue
        p.start(pkg)
        if pkg == "com.miui.weather2" and p.find("城市管理", exact=True, edge_ok="tab"):
            # 新版天气：底部城市管理 → 右上更多设置 → 设置。
            p.tap("城市管理", exact=True, scrolls=0)
        if not gear(p, rt):
            print("  · 本版本没有可识别的设置菜单，跳过"); continue
        if maybe(p, rt, "用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"],
                  page=f"{pkg}·用户体验计划"); p.back()
        p.back(3)

def store(p, rt):
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    gear(p, rt)
    if tap_any(p, rt, "隐私设置", "隐私"):
        # 「个性化服务」可能是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务", "个性化推荐"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连「点赞消息」「评论消息」一起关（Issue #2）
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)

def store_mode(p, rt):
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    gear(p, rt)
    if tap_any(p, rt, "隐私设置", "隐私"):
        # 「个性化服务」可能是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if maybe(p, rt, "模式切换"):                        # 新版商店没有这一项
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞/评论消息一起关
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)

def system_ads_security(p, rt):
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    rt.clock.sleep(1.2)
    rt.require(p.tap("隐私与安全", exact=True, scrolls=6), "未找到「隐私与安全」")
    rt.require(security_tab(p, rt), "未识别「安全」标签")
    rt.require(p.tap("更多安全设置", exact=True, scrolls=6), "未找到「更多安全设置」")
    rt.require(p.tap("广告服务", exact=True, scrolls=6), "未找到「广告服务」")
    close_named_step(p, rt, ["个性化广告推荐"], "系统·广告服务")
