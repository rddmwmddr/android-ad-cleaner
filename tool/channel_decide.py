"""渠道页的认页决策：一份屏幕快照进来，认出哪一行、为什么没认出（#1434）。

认页（这一屏是不是这个渠道的页）、页眉、组底、屏外名与可拨名单只在这里判定。纯函数：
不读屏、不点击，也不认识 `fast` / `phone.*` / `chan_fast`——`tests/test_rules_guards.py` 的
`ChannelDecideGuards` 守着。`chan_fast.ChannelPage` 只负责取一次快照、执行点击与翻页，
把结果搬回它自己的诊断字段。

快照的 `tree` 是节点级判定的来源（页眉 resource-id、祖先链上的 `visible-to-user`、行容器）；
JSON 往返后的快照要先 `ScreenSnapshot.with_tree()` 装回树再送进来。
"""
from dataclasses import dataclass

from geometry import HEADER_BAND, INLINE_ROW_MAX, TOP_BAND, TOP_TITLE_BAND, TOP_TITLE_WIDTH
from row import SAME_LINE, bounds, link, named_nodes, own
from screen_snapshot import on_screen, text_hits

ALLOW = {"允许通知", "显示通知", "允許通知", "顯示通知", "Allow notifications", "Show notifications"}

# 三星 One UI 渠道名在页眉控件里，位置低于 TOP_BAND（#95）
HEADER_IDS = ("entity_header_title", "header_title")

CHANNEL_GROUP = ("类别", "類別", "Categories")   # vivo 旧系统把渠道行收在「类别」分组下面（#336）；繁体界面是「類別」（#498）

# vivo 通知设置页：OriginOS 4 起在 com.vivo.systemuiplugin；OriginOS Ocean（安卓 10）还在 com.android.systemui（错误日志 10-28）
VIVO_HOSTS = ("com.vivo.systemuiplugin", "com.android.systemui")
VIVO_ACTIVITY = ".notification.settings.channels.NotificationSettingsActivity"


def vivo_page(focus):
    return bool(focus) and focus.partition("/")[0] in VIVO_HOSTS and focus.endswith(VIVO_ACTIVITY)


@dataclass(frozen=True)
class Recognition:
    """一次认页的结果：认出的开关（标题、checked、落点）；没认出时 `why` 说明卡在哪。"""
    switch: tuple | None = None
    why: str = ""


@dataclass(frozen=True)
class Candidate:
    """应用通知页上一个可能属于这个渠道的行：名字的落点、所在行容器与行里的开关。"""
    bounds: tuple
    row: object
    boxes: tuple


def _root(snapshot):
    """认页要节点级判定；JSON 往返后的快照没有树，宁可直接说清楚也不静默判空。"""
    if snapshot.tree is None:
        raise ValueError("认页要页面树：先用 ScreenSnapshot.with_tree() 把 tree 装回")
    return snapshot.tree


def _hits(snapshot, systemui_text):
    return text_hits(_root(snapshot), snapshot.width, snapshot.height, systemui_text)


def titled(snapshot, name):
    """页面顶部的标题就是这个渠道名：还停在渠道页。"""
    return any(hit.text == name and hit.bounds[1] < snapshot.height * TOP_BAND
               for hit in snapshot.texts)


def top_title(snapshot, systemui_text=False):
    """顶栏标题控件的文字（vivo：originui_vtoolbar_normal_title）。"""
    hits = _hits(snapshot, systemui_text)
    for t, b, n in hits:
        rid = (n.get("resource-id") or "").lower()
        if "toolbar" in rid and "title" in rid and b[1] < snapshot.height * TOP_BAND:
            return t
    # Funtouch 13 的渠道页顶栏没有 resource-id（#336）：顶部 TOP_TITLE_BAND 里几乎横跨整屏的那段文字。
    # 半屏宽的多半是行内标签（「允许通知」那一行），拿它当标题就会把总开关当成渠道开关。
    wide = [(b[1], b[0] - b[2], t) for t, b, _ in hits
            if b[1] < snapshot.height * TOP_TITLE_BAND and b[2] - b[0] >= snapshot.width * TOP_TITLE_WIDTH]
    return min(wide)[2] if wide else None


def group_floor(snapshot):
    """「类别」/「類別」分组标题的上沿。分组以上只有应用名和「允许通知」总开关，同名文字在那里不是渠道行。"""
    return group_floor_of((hit.text, hit.bounds) for hit in snapshot.texts)


def group_floor_of(texts):
    """`Screen.texts()` 形状的 (文字, bounds, …) 上的分组上沿；`group_floor()` 的同一份判定。"""
    return min((b[1] for t, b, *_ in texts if t in CHANNEL_GROUP), default=None)


def off_screen_name(snapshot, name):
    """同名行已经读进 dump、坐标却落在屏幕下沿之外：列表读到了后面的行，只差翻一页。
    标了不可见的节点（折叠屏合上时留下的另一块屏幕）不算：翻页看不到它，「在屏外」不说明还有下一页。"""
    root = _root(snapshot)
    parents = {c: n for n in root.iter() for c in n}
    for n in root.iter("node"):
        if (n.get("text") or n.get("content-desc") or "").strip() != name or bounds(n)[1] < snapshot.height:
            continue
        node = n
        while node is not None and node.get("visible-to-user") != "false":
            node = parents.get(node)
        if node is None:
            return True
    return False


def allow_switches(snapshot, systemui_text=False):
    """页面上的「允许通知」开关。标题可能来自所在行，也可能只在开关自己的 content-desc 上（三星）。"""
    found = [(row.title, row.checked,
              ((row.bounds[0] + row.bounds[2]) // 2, (row.bounds[1] + row.bounds[3]) // 2))
             for row in snapshot.rows if row.title in ALLOW]
    for n in _root(snapshot).iter("node"):
        label = (n.get("text") or n.get("content-desc") or "").strip()
        if (n.get("checkable") != "true" or label not in ALLOW
                or not on_screen(n, snapshot.width, snapshot.height) or "RadioButton" in n.get("class", "")):
            continue
        l, t, r, b = bounds(n)
        xy = ((l + r) // 2, (t + b) // 2)
        if not any(abs(s[2][1] - xy[1]) < SAME_LINE for s in found):
            found.append((label, n.get("checked") == "true", xy))
    return found


def candidates(snapshot, name, systemui_text=False, floor=None):
    """应用通知页上「可能是这个渠道」的行，按页面顺序：名字相等、不在「类别」分组以上、`own()` 收窄过。"""
    root = _root(snapshot)
    parents = {c: n for n in root.iter() for c in n}
    shown = lambda node: on_screen(node, snapshot.width, snapshot.height)
    out = []
    for _text, b, n in named_nodes(root, parents, shown, name, snapshot.height,
                                   systemui_text=systemui_text):
        if floor is not None and b[1] < floor:
            continue
        row, boxes = own(n, parents, shown)
        if row is None:
            continue
        out.append(Candidate(bounds=b, row=row, boxes=tuple(boxes)))
    return tuple(out)


def recognised_page(snapshot, name, focus, vivo_app=None, systemui_text=False):
    """认页：标题在页面顶部（三星 One UI 在页眉带里），页面身份也还是这个渠道的页。"""
    if not focus or "AppNotification" in focus or not name:
        return False
    if not any(t == name and (b[1] < snapshot.height * TOP_BAND or (
            b[1] < snapshot.height * HEADER_BAND and (n.get("resource-id") or "").endswith(HEADER_IDS)))
            for t, b, n in _hits(snapshot, systemui_text)):
        return False
    if vivo_page(focus):
        # vivo 应用总页的「允许通知」会关掉整个 App，订单、聊天提醒也没了。只认从总页点进来的渠道页：
        # 顶栏是渠道名，且不同于刚才总页的 App 名；两者同名就无法区分，跳过。
        if not vivo_app or top_title(snapshot, systemui_text) != name or name == vivo_app:
            return False
    return True


def recognise(snapshot, name, focus, vivo_app=None, systemui_text=False):
    """同时确认渠道标题、设置页身份和明确的通知开关；绝不取页面第一个开关。"""
    if not recognised_page(snapshot, name, focus, vivo_app, systemui_text):
        return Recognition()
    switches = allow_switches(snapshot, systemui_text)
    return Recognition(switch=switches[0] if len(switches) == 1 else None)


def recognise_inline(snapshot, name, focus="", systemui_text=False):
    """应用通知页里渠道行自带开关（荣耀 MagicOS 10 / Android 16，#99）。
    只认标题与渠道名完全相同、全页唯一合格的一行：行里恰有一个开关、行高合理、行内没有应用总开关。
    同名文字可能不止一处（华为 HarmonyOS 4 的应用通知页把分组名写在列表里，和渠道名相同，#287）：
    没有开关或开关对不上的那些行不算，只有剩下一行时才用。剩下的行仍不止一条时再分一次：
    渠道行的标题和它自己的开关在同一水平带上，分组名借来的开关通常错开一整个行高（错误日志 10-30）。"""
    if not name or name in ALLOW or not focus or vivo_page(focus):
        return Recognition()
    root = _root(snapshot)
    parents = {c: n for n in root.iter() for c in n}
    shown = lambda node: on_screen(node, snapshot.width, snapshot.height)
    # 整行的标签可能也是渠道名：同一行只算一次
    rows, missing, notes = set(), False, []
    good = []
    for _text, b, n in named_nodes(root, parents, shown, name, snapshot.height,
                                   systemui_text=systemui_text):
        row, boxes = own(n, parents, shown)
        if row is None:
            missing = True
            notes.append("没找到所在行；" + link(n, parents))
            continue
        if id(row) in rows:
            continue
        rows.add(id(row))
        l, tp, r, btm = bounds(row)
        labels = {(x.get("text") or x.get("content-desc") or "").strip() for x in row.iter()}
        gap = tol = 0
        if boxes:
            sl, st, sr, sb = bounds(boxes[0])
            gap = abs((b[1] + b[3]) // 2 - (st + sb) // 2)
            tol = max(b[3] - b[1], sb - st)
        ok = len(boxes) == 1 and btm - tp <= snapshot.height * INLINE_ROW_MAX and not labels & ALLOW
        notes.append(f"行内开关 {len(boxes)} 个，行高 {round((btm - tp) * 100 / snapshot.height)}%"
                     + (f"，文字与开关错开 {gap}px" if ok else "")
                     + ("，行内有应用总开关" if labels & ALLOW else "") + "；" + link(n, parents))
        if ok:
            good.append((boxes, gap, tol))
    if len(good) > 1:
        same = [g for g in good if g[1] <= g[2]]
        if len(same) == 1:
            good = same
    if len(good) != 1:
        count = len(rows) + (1 if missing else 0)
        return Recognition(why=(notes[0] if count == 1 and notes
                                else f"同名 {count} 行" + (f"：{' | '.join(notes[:3])}" if notes else "")))
    boxes = good[0][0]
    bl, bt, br, bb = bounds(boxes[0])
    return Recognition(switch=(name, boxes[0].get("checked") == "true", ((bl + br) // 2, (bt + bb) // 2)))


def page_switch(snapshot, name, focus="", vivo_app=None, systemui_text=False):
    """渠道页的开关优先按「渠道页」认，认不出再按「应用通知页的内联行」认。"""
    got = recognise(snapshot, name, focus, vivo_app, systemui_text)
    return got if got.switch is not None else recognise_inline(snapshot, name, focus, systemui_text)


def page_hint(snapshot, name, systemui_text=False, total=None):
    """失败时的人话摘要：标题在顶部 / 列表 / 没有，允许通知开关几个，开关几个（不含页面文字）。

    `total` 是调用方另外独立读到的开关总数（`p.switches()`）：自绘开关的页面两次读取各截一张图，
    与旧实现同形；不传时才退回快照里的行数。
    """
    at = [hit.bounds[1] < snapshot.height * TOP_BAND for hit in snapshot.texts if hit.text == name]
    title = "顶部" if any(at) else ("列表" if at else "无")
    total = len(snapshot.rows) if total is None else total
    return (f"标题{title}，允许通知开关 {len(allow_switches(snapshot, systemui_text))} 个，"
            f"开关 {total} 个")
