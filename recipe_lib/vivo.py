"""vivo 家族库（#1269）：只被 vivo 家族用到的实现住在这里。

上半是词汇（原 `recipe_nav`），下半是策略（原 `recipe_strategies` / `recipe_steps`）。
跨家族用到的实现不放在这里，见 `recipe_lib/shared.py`。
"""

import time
from wait import until
from recipe_lib.shared import _style, browser_settings, maybe, read_switches, tap

__all__ = ('browser_recommendations', 'browser_settings_vivo', 'by_desc', 'close_named_vivo', 'confirm2', 'dialog_open', 'global_search_ads', 'hiboard_panel_v2547a', 'hiboard_panel', 'i_manager_ads', 'lock_screen_magazine', 'off', 'off_one', 'off_unnamed', 'result_xy', 'row_switch', 'rows', 'search_setting', 'setting_search', 'settings_home', 'store_personalization', 'switch_off', 'system_ads_branch', 'system_ads_chain', 'tap_row', 'weather_service')

# ---------- 词汇 ----------
def settings_home(p, rt):
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)

def browser_settings_vivo(p, rt, tries=2):
    """右上「菜单 → 设置」，点完要认出设置页（沿用 #753 的做法）。

    冷启动首页没有底部「我的」，入口是右上菜单。菜单浮层右上角有一个 desc 读作「返回」的 ✕
    （id 里带 cancel），等入口时按弹窗去关会把它点掉，刚打开的菜单就收起来了，「设置」再也找不到。
    所以这里只等那一行画出来、直接点，不在等待里关弹窗；点完没进设置页就退回、重开菜单再试一次。
    别的 vivo 型号可能没有这个按钮，最多等 3 秒就放弃本段。"""
    def landed():
        if p.in_settings_page():
            return True
        at = p.find("设置", exact=True)         # Activity 名不含 Setting 的 App：只认顶上那处「设置」标题
        return bool(at) and at[1] < p.H * 0.25

    for _ in range(tries):
        if not p.d(resourceId="com.vivo.browser:id/menu_btn").click_exists(timeout=3):
            return False                        # 本机没有这个按钮：交给调用方跳过本段
        p.await_page(1.6)                       # 菜单是弹层，画出来的那一帧才有「设置」
        xy = until(lambda: p.find("设置", exact=True, edge_ok="tab"), timeout=3.0, poll=0.3,
                   now=time.time, sleep=time.sleep)
        if xy:
            before = p.sig()
            p.click(*xy)
            if p.settle(before, 1.5):
                p.await_page(1.5)               # Activity 换了、内容可能还在画：等这一页画完再认落点
                if landed():
                    return True
        p.back()                                # 收起浮层 / 退出点错的页，下一轮重开菜单
    raise RuntimeError(f"浏览器设置页没有打开；停在 {p.focus()}")

def off_unnamed(p, rt, page):
    """这一页上没有标题的开关：按位置一个个关，点一次回读一次。
    商店「个性化推荐」页的两个开关 content-desc 只有「开启，开关」（沿用 #220 的做法）：p.off() 按标题匹配，
    空标题的行整行跳过——既关不到，也不会报「关不掉」，所以只有这一页自己点。
    灰的行不点（沿用 #333 的做法）；点完读不到开关（被确认框挡住）不算关掉（沿用 #486 的教训：读空不等于成功）。
    安全模式下不点：无标题的行不在脚本点名的范围内（沿用 #909 的做法）。"""
    from row import disabled_at
    if p.safe_mode:
        print(f"  · {page}：安全模式不做整页全关，无标题开关未改动", flush=True)
        return 0
    root = p.tree()
    targets = [xy for title, on, xy in p.switches(root) if not title and on]
    if not targets:
        print(f"  · {page}：没有开着且无标题的开关")
        return 0
    done = 0
    for i, xy in enumerate(targets, 1):
        if disabled_at(root, xy):
            print(f"  · 被上级开关禁用（开关是灰的），未改动 无标题开关 {i}")
            continue
        was = sum(1 for title, on, _ in p.switches() if not title and on)
        p.click(*xy)
        p.confirm()
        rt.clock.sleep(0.3)
        rows = p.switches()
        if not rows or sum(1 for title, on, _ in rows if not title and on) >= was:
            print(f"  ✗ 关不掉 无标题开关 {i}")
            continue
        print(f"  关 无标题开关 {i}")
        p.changed.append((page, f"无标题开关 {i}"))
        done += 1
    print(f"  · {page}：核对 {len(targets)} 项，调整 {done} 项")
    return done

def _vivo_gear(p, rt):
    from fast import bounds, icon_hit
    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        icon = "ImageView" in n.get("class", "") and r - l < p.W * 0.25 and b - t < p.H * 0.15
        if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n):
            p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1)
            return True
    return p.tap("设置", exact=True, scrolls=0)

def _vivo_gear_desc(p, rt):
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("resource-id") or "")
        if any(k in d.lower() for k in ("设置", "setting")) and n.get("clickable") == "true" and p.on_screen(n):
            from fast import bounds
            l, t, r, b = bounds(n); p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1)
            return True
    return p.tap("设置", exact=True, scrolls=0)

def _vivo_gear_landing(p, rt):
    from fast import bounds, icon_hit

    def landed(focus0):
        if p.focus() == focus0:
            return False                    # 点击被吞：页面没换，不能当成进了设置页
        if p.in_settings_page():
            return True
        # Activity 名不含 Setting 的 App：只认顶上标题带那一处「设置」——齿轮自己也读作「设置」
        at = p.find("设置", exact=True)
        return bool(at) and at[1] < p.H * 0.25

    for n in p.tree().iter("node"):
        l, t, r, b = bounds(n)
        icon = "ImageView" in n.get("class", "") and r - l < p.W * 0.25 and b - t < p.H * 0.15
        if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n):
            focus0 = p.focus()
            p.click((l + r) // 2, (t + b) // 2); p.await_page(1.5)
            if landed(focus0):
                return True
            if p.focus() != focus0:         # 点进了别的页：退回来，别用旧树的坐标在新页上接着点
                p.back(); rt.clock.sleep(0.6)
    focus0 = p.focus()
    return p.tap("设置", exact=True, scrolls=0) and landed(focus0)

def _vivo_gear_top_style(p, rt):
    """V2309A 的「我的」页右上角齿轮：无文字 Button，只有 content-desc="设置"。

    判据用引擎的 icon_hit（沿用 #530 / ADR-0013）：它只认正好是「设置」的描述 / 正文，同页那条
    「去功能设置里重新开启」的说明行不会被点到，所以不用再按位置收一次。齿轮名字不是恰好
    「设置」（比如「更多设置」）的机型会在这里漏掉。
    """
    from fast import bounds, icon_hit
    for n in p.tree().iter("node"):
        if n.get("clickable") != "true" or not p.on_screen(n):
            continue
        if not icon_hit(n):
            continue
        l, t, r, b = bounds(n)
        if r > l and b > t:
            p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1.0)
            return True
    return False

def tap_row(p, rt, *args, **kwargs):
    def subtitle_style(subtitle):
        """点「副标题」所在那一行的中间：本机有些行点左侧标题文字不跳转（V1986A）。"""
        for t, (_l, tp, _r, b), _n in p.texts():
            if t.startswith(subtitle):
                p.click(int(p.W * 0.4), (tp + b) // 2); rt.clock.sleep(1.0)
                return True
        return False
    def row_span_style(title, scrolls=4):
        """点标题所在的可点行，落点在行宽 40% 处。

        商店设置页点左侧标题文字不跳转（V1986A 同此），要点行中间（沿用 #530）。
        """
        from fast import bounds
        for _ in range(scrolls + 1):
            root = p.tree()
            parent = {c: par for par in root.iter("node") for c in par}
            for n in root.iter("node"):
                if (n.get("text") or "").strip() != title or not p.on_screen(n):
                    continue
                row = n
                for _ in range(4):
                    up = parent.get(row)
                    if up is None or up.get("clickable") != "true":
                        break
                    row = up
                l, t, r, b = bounds(row)
                if r <= l or b <= t:
                    l, t, r, b = bounds(n)
                p.click(int(l + (r - l) * 0.4), (t + b) // 2); rt.clock.sleep(1.0)
                return True
            if not p.scroll_more():
                break
        return False
    def centre_style(w, scrolls=0, wait=1.3):
        """点列表项：先找到文字，再点整行水平中间（V2547A）。

        有的 vivo 页面左侧文字节点不转发点击（应用商店「关于」页的「服务管理」就是这样，
        点文字没反应，点行中间才进得去）。
        进页后立刻找会对着还没画完的页面报「没找到」，先等这一页站稳（沿用 #331）。"""
        p.await_page()
        xy = p.find(w, exact=True)
        for _ in range(scrolls):
            if xy:
                break
            if not p.scroll_more():
                break
            xy = p.find(w, exact=True)
        if not xy:
            return False
        b = p.sig()
        p.click(p.W // 2, xy[1])
        p.settle(b, wait + 0.4)
        rt.clock.sleep(wait)
        return True
    style = _style(rt, "TAP_ROW_STYLE", ("subtitle", "row_span", "centre"), "centre")
    if style == "subtitle":
        return subtitle_style(*args, **kwargs)
    if style == "row_span":
        return row_span_style(*args, **kwargs)
    return centre_style(*args, **kwargs)

def by_desc(p, rt, kw, wait=1.2):
    """底部 tab、右上齿轮这类入口只有 content-desc，没有文字。"""
    from fast import bounds
    for n in p.tree().iter("node"):
        if kw in (n.get("content-desc") or "") and n.get("clickable") == "true" and p.on_screen(n):
            l, t, r, b = bounds(n)
            p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(wait)
            return True
    return False

def result_xy(p, rt, kw, root=None):
    """搜索结果里挑真正那一条。

    搜索框本身是个 EditText，里面也有刚输入的关键词（y 在页面顶部），
    p.find(keyword) 按文档顺序会先命中它 —— 点上去等于又点了一次输入框，页面根本不跳，
    而且不会报错，整段就这么静默空跑。所以这里排除 EditText，并跳过顶部搜索栏那块。"""
    root = root if root is not None else p.tree()
    for t, (l, tp, r, b), n in p.texts(root):
        if t != kw or "EditText" in (n.get("class") or ""):
            continue
        cy = (tp + b) // 2
        if b <= tp or cy < p.H * 0.13:
            continue
        return ((l + r) // 2, cy)
    return None

def search_setting(p, rt, kw, pick=True):
    """在系统设置里搜 kw 并点进第一条结果。

    引擎的 p.setting 依赖 focused 输入框，在 vivo 上时而等不到（会抛异常），这里直接按 resourceId
    取输入框。点完还要确认焦点窗口真的变了，否则返回 False —— 宁可报错，也不要装作进去了。"""
    p.miss = 0
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
    for _ in range(24):
        if p.find("搜索设置项"):
            break
        rt.clock.sleep(0.25)
    if not p.tap("搜索设置项", scrolls=0, wait=0.6):
        print("  ✗ 设置首页没找到搜索框"); return False
    try:
        p.d(resourceId="com.android.settings:id/vigour_search_edit").set_text(kw)
    except Exception as e:
        print(f"  ✗ 搜索框输入失败：{e}"); return False
    xy = None
    for _ in range(12):
        xy = result_xy(p, rt, kw)
        if xy:
            break
        rt.clock.sleep(0.25)
    if not xy:
        print(f"  ✗ 没搜到「{kw}」"); return False
    if not pick:
        return True
    before = p.focus()
    p.click(p.W // 2, xy[1])
    for _ in range(15):
        if p.focus() != before:
            rt.clock.sleep(0.7)
            return True
        rt.clock.sleep(0.2)
    print(f"  ✗ 点「{kw}」的搜索结果没有跳转")
    return False

def hiboard_panel(p, rt):
    """回到负一屏的设置面板（V2417A 的路径）。"""
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
        rt.require(home.startswith("com.bbk.launcher2/"), "未回到系统桌面，停止负一屏段")
        signature = p.sig()
        p.d.shell(f"input swipe {p.W // 10} {p.H // 2} {p.W * 9 // 10} {p.H // 2} 300")
        p.settle(signature, 1.5)
    rt.require(p.focus() == "HiBoard" and p.find("添加组件", exact=True),
                 "未进入负一屏（可能未启用），停止本段")
    rt.require(p.go("设置", "更多设置"), "未进入负一屏设置")
    rt.require("com.vivo.hiboard.settings.AppletSettingActivity" in p.focus(), "负一屏设置页面不符")

def hiboard_panel_v2547a(p, rt):
    """回到负一屏的设置面板（V2547A 的路径）。

    子页来来回回地 back 很容易多退一层回到负一屏主页，后面的项就全找不到了 ——
    所以每进一个子页之前都用 Activity 确认一次，不在面板上就重新滑进来。
    不能用「屏上有『热点资讯』」来判断：负一屏主页上本来就有资讯卡片，会误判成面板。"""
    if "AppletSettingActivity" in p.focus():
        return True
    p.d.shell("input keyevent HOME"); rt.clock.sleep(1.0)
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//10} {p.H//2} {p.W*9//10} {p.H//2} 250")
        rt.clock.sleep(1.5)
        if p.find("添加组件") or p.find("小V建议"):
            break
    p.tap("设置", exact=True, scrolls=0, wait=1.3)
    return "AppletSettingActivity" in p.focus()

def _vivo_read_switches_style(p, rt, max_screens=1):
    """读这一页的开关，标题按脚本的 `title_key()` 归并（V2417A：vivo 把说明拼在点号后）。"""
    result = {}
    for screen in range(max_screens):
        items = until(p.switches, timeout=3, poll=0.2)
        rt.require(items, "页面里没有读到开关，停止本段")
        current = {}
        for title, state, _ in items:
            key = title_key(title)
            rt.require(key not in current, f"开关标题不唯一：{key}")
            current[key] = state
        result.update(current)
        if screen + 1 < max_screens and not p.scroll_more():
            break
    return result

def _vivo_my_tab(p, rt):
    """应用商店底部「我的」标签：在 y>92% 处，find() 默认不点，直接按坐标点最后一个标签（V1986A）。"""
    xy = p.find("我的", edge_ok="tab")
    if xy:
        p.click(*xy)
    else:
        p.click(int(p.W * 0.9), int(p.H * 0.96))
    rt.clock.sleep(1.2)

def _vivo_tap_text_style(p, rt, w, scrolls=0, wait=1.3):
    ok = p.tap(w, exact=True, scrolls=scrolls)
    rt.clock.sleep(wait)
    return ok

def _vivo_goto_style(p, rt, name, scrolls=0):
    """点进一个列表项，并把结果打出来。

    不打印就没法区分「这页确实没开关可关」和「压根没进到这页」，跑完看到 0 个也敢信。"""
    ok = tap_row(p, rt, name, scrolls=scrolls)
    print(f"  · {name}" if ok else f"  ✗ 没找到「{name}」")
    return ok

def title_key(title):
    """vivo 把说明拼在点号后；状态尾缀已由引擎剥掉（#565）。"""
    return title.split(".", 1)[0].strip()

# ---------- 策略 ----------
def off_one(p, rt, keyword, page):
    """按开关自身状态关一个开关并回读。返回 None=本来关着，True=关掉，False=没关掉。

    （旧注释说的「标题随状态变化致引擎误报」已由引擎在标题产出处剥掉尾缀修复，沿用 #565；
    本页的独立回读保留——没有真机，不敢顺手改脚本行为。）"""
    hits = [(t, c, xy) for t, c, xy in p.switches() if keyword in t]
    if not hits:
        print(f"  ✗ 没找到「{keyword}」开关"); return False
    if not hits[0][1]:
        print(f"  · {keyword} 本来就是关的")
        return None
    p.click(*hits[0][2]); p.confirm(); rt.clock.sleep(0.5)
    for t, c, _ in p.switches():
        if keyword in t and not c:
            print(f"  关 {keyword}")
            p.changed.append((page, keyword))
            return True
    print(f"  ✗ 关不掉 {keyword}")
    return False

def row_switch(p, rt, title):
    """商店的开关标题在开关行外，只能按同一行的 Switch 节点配对；找不到返回 None。

    整行容器和真开关都会被算进来，取树里最后一个（内层真开关）。"""
    from fast import bounds
    root = p.tree()
    rows = [bounds(n) for n in root.iter("node") if (n.get("text") or "").strip() == title]
    hit = None
    for n in root.iter("node"):
        if "Switch" in (n.get("class") or ""):
            l, t, r, b = bounds(n)
            if any(t <= (t2 + b2) // 2 <= b and t2 >= t and b2 <= b for l2, t2, r2, b2 in rows):
                hit = (n.get("checked") == "true", ((l + r) // 2, (t + b) // 2))
    return hit

def switch_off(p, rt, title, page, tries=2):
    """`p.off()` 的开关标题取自同一行，商店这页标题在行外会配错，所以单独回读。

    关掉的项与 `p.off()` 一样记进 `p.changed`，并区分「本来就是关」和「这次关掉」。"""
    for _ in range(tries):
        state = row_switch(p, rt, title)
        if state is None:
            print(f"  ? {title}：没找到")
            return False
        if not state[0]:
            print(f"  · {title}：本来就是关")
            return True
        p.click(*state[1]); rt.clock.sleep(0.9); p.confirm(); rt.clock.sleep(0.9)
        now = row_switch(p, rt, title)
        if now is not None and not now[0]:
            p.changed.append((page, title))
            print(f"  关 {title}")
            return True
    print(f"  ✗ 关不掉 {title}")
    return False

def setting_search(p, rt, keyword, result):
    """设置页层级变了就用搜索兜底。"""
    try:
        return bool(p.setting(keyword, result))
    except Exception as e:
        print(f"  设置搜索「{keyword}」没走通：{e}")
        return False

def store_personalization(p, rt):
    """两行标题会随状态变化；逐行点，处理确认框后用稳定标题回读。"""
    page = "商店·个性化推荐"
    names = ["个性化推荐", "个性化广告推荐"]
    before = read_switches(p, rt)
    rt.require_switches(before, names, page)
    for name in names:
        rows = [(state, xy) for title, state, xy in p.switches() if title_key(title) == name]
        rt.require(len(rows) == 1, f"{page}：无法唯一识别「{name}」，未操作")
        if not rows[0][0]:
            continue
        signature = p.sig()
        p.click(*rows[0][1])
        p.settle(signature, 1.5)
        # 本机按钮未被通用 confirm() 识别；只点明确的“确认关闭”，不点状态文字。
        if p.find("确认关闭", exact=True):
            tap(p, rt, "确认关闭", scrolls=0)
        else:
            p.confirm()
        rt.require(read_switches(p, rt).get(name) is False, f"{page}：「{name}」回读未确认关闭")
        p.changed.append((page, name))
        print(f"  关 {name}", flush=True)
    verify(p, rt, before, read_switches(p, rt), names, page)

def confirm2(p, rt):
    """关掉推荐开关后，vivo 会弹「温馨提示 → 取消 / 确认关闭」。

    这个框的按钮 text 是空的（android:id/button1=取消、button2=确认关闭），
    标题挂在下层 TextView（resource-id=...vbutton_title）里。引擎的 `p.confirm()` 理论上已覆盖
    这个形状，但没在 V2547A 真机上验过，暂留这份（沿用 #397）。"""
    rt.clock.sleep(0.35)
    root = p.tree()
    for n in root.iter("node"):
        if n.get("clickable") != "true" or "Button" not in (n.get("class") or ""):
            continue
        labels = [(x.get("text") or "").strip() for x in n.iter("node")]
        hit = next((w for w in rt.constants['CONFIRM'] if w in labels), None)
        if not hit:
            continue
        l, t, r, b = rt.constants['bounds_of'](n)
        if r - l <= 0 or b - t <= 0:
            continue
        p.click((l + r) // 2, (t + b) // 2)
        rt.clock.sleep(0.35)
        return hit
    return None

def dialog_open(p, rt):
    """当前屏是不是挡着一个带「取消」的确认框（用来发现没关掉的弹窗）。"""
    root = p.tree()
    tx = {(n.get("text") or "").strip() for n in root.iter("node")}
    return "取消" in tx and not p.switches(root)

def rows(p, rt):
    """当前屏的开关行：[(真实标题, 是否开着, (x, y))]，一行一条。

    引擎自带的 p.switches() 有两个坑，在 V2547A 上都会踩到：
    1) 标题是「往上找父节点里的第一段文字」，遇到分组容器会串成页标题 ——
       负一屏「热点资讯」页 8 行全都叫「热点资讯」、阅图锁屏页的「锁屏底部壁纸功能」会被叫成「阅图锁屏」，
       照着标题关就会关错东西。这里改成按行还原：取同一行、开关左侧、最靠上的那段文字
       （vivo 的列表行都是「标题在上、说明在下」，按纵向最近取会把长说明当标题 ——
       全局搜索·个性化内容 的「广告个性化」就因此永远匹配不上）。
    2) 单选组（热点资讯页的悬浮/经典/卡片形态）也是 checkable+clickable，会被当成开关一起「关掉」。
       单选钮一律排除。
    """
    root = p.tree()
    p.switches(root)                        # 先让引擎把自绘开关标成 SelfDrawnSwitch，再自己扫
    texts = []
    for n in root.iter("node"):
        s = (n.get("text") or n.get("content-desc") or "").strip()
        if not s:
            continue
        l, t, r, b = rt.constants['bounds_of'](n)
        if r - l <= 0 or b - t <= 0:
            continue
        texts.append((s, l, t, r, b, (t + b) // 2))

    found = []                              # [左, 右, 中线y, 上, 下, 是否开, 原始文案, 宽]
    for n in root.iter("node"):
        cls = n.get("class") or ""
        if n.get("checkable") != "true" or "Radio" in cls:
            continue
        if not any(k in cls for k in ("Switch", "CheckBox", "ToggleButton", "SelfDrawnSwitch")):
            continue
        l, t, r, b = rt.constants['bounds_of'](n)
        if r - l <= 0 or b - t <= 0:
            continue
        raw = (n.get("text") or n.get("content-desc") or "").strip()
        found.append([l, r, (t + b) // 2, t, b, n.get("checked") == "true", raw, r - l])

    # 同一行的「整行节点」和「开关节点」合成一条：点在真开关上、行范围取两者的并集
    merged = []
    for f in sorted(found, key=lambda f: f[2]):
        for m in merged:
            if abs(m[2] - f[2]) <= 40:
                m[3] = min(m[3], f[3])
                m[4] = max(m[4], f[4])
                if f[7] > m[7]:             # 整行节点的文案更完整，留作兜底
                    m[6], m[7] = f[6], f[7]
                if (f[0] + f[1]) > (m[0] + m[1]):
                    m[0], m[1], m[2], m[5] = f[0], f[1], f[2], f[5]
                break
        else:
            merged.append(list(f))

    out = []
    for l, r, cy, top, bot, ck, raw, _w in merged:
        best = None
        for s, tl, tt, tr, _tb, tc in texts:
            if tr > l:                      # 只要开关左边的文字
                continue
            if not (top - 25 <= tc <= bot + 25):
                continue
            if best is None or (tt, tl) < (best[0], best[1]):
                best = (tt, tl, s)
        title = best[2] if best else (raw.split(".")[0].strip() if raw else "")
        out.append((title, ck, ((l + r) // 2, cy)))
    return out

def off(p, rt, only=None, keep=(), page='', max_screens=30):
    """只关匹配的开关，每行点一次。引擎自带的 p.off 在 vivo 上会把同一行点两遍。"""
    done = 0
    tried = {}                                  # 标题 -> 点过几次，防止在同一行上反复空点
    for _ in range(2 if p.miss else 8):          # 页面刚打开还没画完
        if p.switches():
            break
        rt.clock.sleep(0.25)
    for _ in range(max_screens):
        todo = []
        for t, c, xy in rows(p, rt):
            if not c or not t:
                continue
            if any(k in t for k in keep):
                continue
            if only is not None and not any(k in t for k in only):
                continue
            if tried.get(t, 0) >= 2:            # 点两次还是开着：多半被弹窗挡着，交给下面的检查
                continue
            if not (0 < xy[0] < p.W and p.H * 0.08 < xy[1] < p.H * 0.985):
                print(f"  ! {t} 坐标异常 {xy}，跳过不乱点")
                continue
            todo.append((t, xy))
        for t, xy in todo:
            p.click(*xy)
            rt.clock.sleep(0.3)
            hit = confirm2(p, rt)               # 这个弹窗按钮没有 text，见 confirm2() 的说明
            if hit:
                print(f"  · 二次确认点了「{hit}」")
            rt.clock.sleep(0.15)
            if dialog_open(p, rt):               # 弹窗还在：不再点了，避免又被遮罩关掉、来回拨
                print(f"  ✗ {page}：确认框关不掉，停止本页")
                p.back(1)
                return done
            tried[t] = tried.get(t, 0) + 1
            if any(tt == t and cc for tt, cc, _ in rows(p, rt)):
                continue                        # 还开着，下一屏再看
            print(f"  关 {t}")
            p.changed.append((page, t))
            done += 1
        if not p.scroll_more():
            break
    left = [t for t, c, _ in rows(p, rt) if c and t and t in tried]
    for t in dict.fromkeys(left):
        print(f"  ✗ 关不掉 {t}")
    return done

def close_named_vivo(p, rt, names, page, max_screens=1):
    p.top(max_screens)
    before = read_switches(p, rt, max_screens)
    rt.require_switches(before, names, page)
    p.top(max_screens)
    # only 在引擎中是包含匹配；明确保留本页其余开关，回读再核对一次。
    p.off(only=names, keep=[name for name in before if name not in names],
          page=page, max_screens=max_screens)
    p.top(max_screens)
    verify(p, rt, before, read_switches(p, rt, max_screens), names, page)

def verify(p, rt, before, current, names, page):
    """vivo 的整表回读：目标都关掉、其他开关未变，并记回读确认数（V2417A）。"""
    rt.require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
    rt.require(all(current.get(name) == state for name, state in before.items() if name not in names),
               f"{page}：其他开关状态变化，请核对")
    rt.confirm(len(names))
    print(f"  ✓ {page}：回读确认 {len(names)} 项关闭，其他开关未变", flush=True)

def browser_recommendations(p, rt):
    """浏览器设置页几处推荐开关。没有右上菜单按钮的机型整段跳过。"""
    p.start("com.vivo.browser")
    if not browser_settings(p, rt):
        print("  ✗ 本机浏览器没有右上菜单按钮，跳过本段"); return
    print(f"  · 浏览器设置页 {p.focus()}")
    if maybe(p, rt, "首页设置"):
        maybe(p, rt, "极简首页", scrolls=0)
        p.off(only=["首页上滑展示资讯"], page="浏览器·首页设置"); p.back()
    p.top()
    if maybe(p, rt, "网页浏览设置"):
        p.off(only=["网页下载相关推荐"], page="浏览器·网页浏览"); p.back()
    p.top()
    if maybe(p, rt, "更多设置"):
        p.off(only=["WiFi连接跳转新闻资讯", "WiFi 连接跳转新闻资讯", "跳转新闻资讯",
                    "下载管理页展示热门应用", "下载管理页展示下载热榜"], page="浏览器·更多设置"); p.back()
    p.top()
    if maybe(p, rt, "隐私权限设置"):
        p.off(only=["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], page="浏览器·隐私"); p.back()
    p.back(2)

def i_manager_ads(p, rt):
    """i管家「关于 → 个性化设置」，直达 MainSettings 页。"""
    p.d.shell("am start -f 0x10008000 -n com.iqoo.secure/.MainSettings")
    rt.clock.sleep(1.0)
    if maybe(p, rt, "关于") and maybe(p, rt, "个性化设置"):
        p.off(only=["应用个性化推荐", "清理个性化推荐"], page="i管家·个性化设置")
    p.back(3)

def lock_screen_magazine(p, rt):
    """桌面、锁屏与壁纸 → 锁屏设置 → 阅图锁屏。"""
    settings_home(p, rt)
    if maybe(p, rt, "桌面、锁屏与壁纸") and maybe(p, rt, "锁屏设置") and maybe(p, rt, "阅图锁屏"):
        p.off(only=["阅图锁屏", "锁屏横滑进入阅图"], page="阅图锁屏")

def system_ads_branch(p, rt):
    """系统设置里的「广告与隐私」：首屏入口读作「安全」或「安全与隐私」两种都认。"""
    settings_home(p, rt)
    if maybe(p, rt, "安全") or maybe(p, rt, "安全与隐私"):
        if maybe(p, rt, "更多安全设置") and maybe(p, rt, "广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")

def system_ads_chain(p, rt):
    """系统设置里的「广告与隐私」：一路串联认「安全 → 更多安全设置 → 广告与隐私」。"""
    settings_home(p, rt)
    if maybe(p, rt, "安全") and maybe(p, rt, "更多安全设置") and maybe(p, rt, "广告与隐私"):
        p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")

def global_search_ads(p, rt):
    """系统管理与升级 → 全局搜索 的三个子页；历史记录与应用建议保留。"""
    settings_home(p, rt)
    if maybe(p, rt, "系统管理与升级") and maybe(p, rt, "全局搜索"):
        if maybe(p, rt, "首页展示内容"):
            p.off(only=["搜索框推荐词", "推荐卡片"], page="全局搜索·首页展示内容"); p.back()
        if maybe(p, rt, "推荐热搜榜单", scrolls=2):
            p.off(only=["热门搜索"], page="全局搜索·热搜榜单"); p.back()
        if maybe(p, rt, "个性化内容"):
            p.off(only=["广告个性化"], page="全局搜索·个性化内容"); p.back()

def weather_service(p, rt):
    """天气设置页只关「天气服务」（天气相关热点资讯通知），预警类三个开关同页保留。"""
    p.d.shell("am start -f 0x10008000 -n com.vivo.weather/.WeatherSettings")
    rt.clock.sleep(1.0)
    p.off(only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")
    p.back(1)

_VIVO_GEAR_FACTORIES = {"vivo": _vivo_gear, "vivo_desc": _vivo_gear_desc,
                        "vivo_landing": _vivo_gear_landing}
