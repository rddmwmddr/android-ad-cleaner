#!/usr/bin/env python3
"""「开关所属的那一行」的唯一定义。

行的两副面孔，取决于布局：
  结构（line / own）—— 从起点往上，到可点 / 可勾选的控件，或到滚动列表的直接子项为止；
      容器里不止一个开关时，收窄到最内层含开关的那个（卡片里排着几个渠道）。
  几何（title_of）—— 平铺列表里标题和开关是兄弟节点，结构给不出容器，标题只能按竖直距离挑：
      容器矮取最上方的文字，容器高取离开关最近的文字。

两个投影共享 bounds() 与 switches_in()，但不互相调用：标题规则一旦去问结构行，
「开关在卡片内小行、卡片本身可点」这类布局会改判，那是另一类行为变化。

术语：行 = 开关所属的那一条；卡片 = 一个容器里排着好几行的控件；内联布局 = 渠道行自带开关。
"""
import re

BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
LISTS = re.compile(r"ListView|RecyclerView|ScrollView", re.I)
SWITCH_ROW_DEPTH = 6
PATH_DEPTH = 8
SKELETON_ANCHORS = 8       # 同名节点最多取这么多：华为把分组名写进列表时会满屏同名（#287）
SKELETON_ROW = 40          # 单个锚点保留的行子树节点数
SKELETON_NODES = 80        # 一份骨架的节点上限：一屏朴素全量 18–30KB，会顶爆上报日志的 2 万字预算
SKELETON_BYTES = 4096      # 单份字符上限，与节点上限双保险
STATE_WORDS = ("开", "关", "已开启", "已关闭", "开启", "关闭", "ON", "OFF",
               "开启，开关", "关闭，开关", "已开启，开关", "已关闭，开关", "开启，按钮", "关闭，按钮")


def bounds(node):
    m = BOUNDS.match(node.get("bounds", ""))
    return tuple(map(int, m.groups())) if m else (0, 0, 0, 0)


def line(node, parents, max_depth=None):
    """文字所在的行。ListView 的行常常不可点（点击由列表处理），到列表的直接子项为止。
    max_depth 是往上检查的节点数上限（含起点）；None 表示一直找到根节点。"""
    seen = 0
    while node is not None and (max_depth is None or seen < max_depth):
        if node.get("clickable") == "true" or node.get("checkable") == "true":
            return node
        parent = parents.get(node)
        if parent is not None and (parent.get("scrollable") == "true"
                                   or LISTS.search(parent.get("class") or "")):
            return node
        node = parent
        seen += 1
    return None


def switches_in(node, on_screen):
    """node 子树里的开关。RadioButton 是互斥选项、不是开关，拨它等于替用户改选另一项；
    node 自己不算——问的是「一行里有几个开关」。"""
    return [x for x in node.iter()
            if x is not node and x.get("checkable") == "true"
            and "RadioButton" not in (x.get("class") or "") and on_screen(x)]


def own(node, parents, on_screen, max_depth=None):
    """node 所在的行和行里的开关。行里不止一个开关时（几个渠道排在同一张卡片里），
    从 node 往上找第一个含开关的控件；它只含一个开关才算这一行。
    行里仍然不止一个开关时照样返回，由调用方决定是放弃还是按别的方式挑。"""
    container = line(node, parents, max_depth)
    if container is None:
        return None, []
    boxes = switches_in(container, on_screen) or (
        [container] if container.get("checkable") == "true" else [])
    inner = node
    while len(boxes) > 1 and inner is not None and inner is not container:
        found = switches_in(inner, on_screen)
        if found:
            return inner, found
        inner = parents.get(inner)
    return container, boxes


def title_of(switch, parents, on_screen, screen_h, max_depth=SWITCH_ROW_DEPTH):
    """开关所在那一行的标题：往上找到第一个带文字的祖先。容器矮（就是一行）时分不清标题和说明，
    取最上面那段；容器高（是一整张列表）时取竖直方向离开关最近的文字。
    行里没有别的文字时，退回开关自己的无障碍标签。"""
    _, t, _, b = bounds(switch)
    cy = (t + b) // 2
    label = (switch.get("text") or switch.get("content-desc") or "").strip().split("\n", 1)[0]
    label = label if label not in STATE_WORDS else ""
    title, node = "", switch
    for _ in range(max_depth):
        # 有自己的可访问标签时，不从包含多个开关的公共列表借用相邻行标题。
        # 这里数的是控件类名里的 Switch（含各家 HwSwitch），问的是「这是不是一张公共列表」；
        # 与 switches_in 判「这是不是一个能拨的开关」是两个问题，不要合并。
        if label and node is not switch and sum(
                1 for x in node.iter("node") if "Switch" in (x.get("class") or "")
                and "Switcher" not in (x.get("class") or "") and on_screen(x)) > 1:
            title = label
            break
        cand = []
        for x in node.iter("node"):
            tx = (x.get("text") or x.get("content-desc") or "").strip().split("\n", 1)[0]
            if x is switch or not tx or tx in STATE_WORDS:
                continue
            xl, xt, xr, xb = bounds(x)
            if xb <= xt or not on_screen(x):
                continue
            cand.append((xt, xl, xb, tx))
        if cand:
            pl, pt, pr, pb = bounds(node)
            if pb - pt <= max(screen_h * 0.18, (b - t) * 3):
                title = min(cand)[3]
            else:
                near = sorted((0 if xt <= cy <= xb else min(abs(xt - cy), abs(xb - cy)), xt, tx)
                              for xt, xl, xb, tx in cand)
                if near[0][0] <= max(60, b - t):
                    title = near[0][2]
            break
        node = parents.get(node)
        if node is None:
            break
    return title or label


def path(node, parents, depth=PATH_DEPTH):
    """从 node 往上的控件链数据：(类名, 'cs' 标志, 子树里的开关数)。到滚动容器为止，不含页面文字。"""
    out = []
    while node is not None and len(out) < depth:
        flags = ("c" if node.get("clickable") == "true" else "") + (
            "s" if node.get("scrollable") == "true" else "")
        out.append((node.get("class") or "node", flags,
                    sum(x.get("checkable") == "true" for x in node.iter())))
        if node.get("scrollable") == "true" or LISTS.search(node.get("class") or ""):
            break
        node = parents.get(node)
    return out


def link(node, parents, depth=PATH_DEPTH):
    """控件链的显示形式：类名、可点 c / 可滚动 s、子树里的开关数。不含页面文字，适配新系统靠它。"""
    return "结构 " + " < ".join(
        f"{(cls or 'node').rsplit('.', 1)[-1]}{':' + flags if flags else ''}#{count}"
        for cls, flags, count in path(node, parents, depth))


def summary(root, screen_w, screen_h):
    """页面结构摘要（不含页面文字）：顶部标题数、开关数、一条控件链。
    入口没找到时用它区分「页面还没画完」和「入口确实没了」（#331）。
    与 Phone.texts() / switches() 同一套过滤：状态栏文字、折叠屏合上后的内屏残留、互斥单选都不算。"""
    nodes = list(root.iter("node"))
    parents = {c: n for n in nodes for c in n}

    def shown(n):
        l, t, r, b = bounds(n)
        cx, cy = (l + r) // 2, (t + b) // 2
        return (r > l and b > t and 0 <= cx < screen_w and 0 <= cy < screen_h
                and n.get("package") != "com.android.systemui")

    def in_list(n):
        cur = parents.get(n)
        while cur is not None:
            if cur.get("scrollable") == "true" or LISTS.search(cur.get("class") or ""):
                return True
            cur = parents.get(cur)
        return False

    def is_switch(n):
        return n.get("checkable") == "true" and "RadioButton" not in (n.get("class") or "")

    titles = sum(1 for n in nodes if shown(n) and not in_list(n)
                 and (n.get("text") or n.get("content-desc") or "").strip()
                 and bounds(n)[1] < screen_h * 0.22)
    switches = sum(1 for n in nodes if shown(n) and is_switch(n))
    anchor = next((n for n in nodes if shown(n) and is_switch(n)), None)
    if anchor is None:
        anchor = next((n for n in nodes if shown(n)
                       and (n.get("text") or n.get("content-desc") or "").strip()), None)
    out = f"标题 {titles} 个，开关 {switches} 个"
    return out + ("；" + link(anchor, parents) if anchor is not None else "")


def skeleton(root, name, screen_w, screen_h, focus=""):
    """脱敏页面骨架（#428）：只含结构，不含页面文字。

    回答的是「这一行为什么没认出来」，不是「整页长什么样」：以文字 / content-desc 命中渠道名的
    节点为锚，带它的祖先链与所在行的子树；一个锚都没有时退回带开关的行，再退回屏内前 40 个节点。
    bounds 用屏宽高的百分比，不同分辨率之间才能比较；N / M / P 三个字面就是「名字挂在哪」的答案。"""
    name = re.sub(r"\s+", " ", (name or "").strip())
    focus = re.sub(r"\s+", " ", (focus or "").strip())
    nodes = list(root.iter("node"))
    if not nodes or screen_w <= 0 or screen_h <= 0:
        return ""
    parents = {c: n for n in nodes for c in n}

    def depth_of(n):
        found = 0
        while parents.get(n) is not None:
            n = parents[n]
            found += 1
        return found

    depth = {n: depth_of(n) for n in nodes}
    host = focus.partition("/")[0]
    # vivo 的渠道页本身挂在 systemui 下：只有焦点页是别的应用时，systemui 的节点才是状态栏
    hide_systemui = bool(host) and host != "com.android.systemui"

    def shown(n):
        if n.get("visible-to-user") == "false":
            return False
        if hide_systemui and n.get("package") == "com.android.systemui":
            return False
        l, t, r, b = bounds(n)
        cx, cy = (l + r) // 2, (t + b) // 2
        return r > l and b > t and 0 <= cx < screen_w and 0 <= cy < screen_h

    def sides(n):
        return (n.get("text") or "").strip(), (n.get("content-desc") or "").strip()

    visible = [n for n in nodes if shown(n)]
    exact = [n for n in visible if name and name in sides(n)]
    partial = [n for n in visible if name and any(name in s for s in sides(n))]
    anchors = (exact or partial)[:SKELETON_ANCHORS]

    picked = set()

    def take(node, subtree=0):
        chain, cur = [], node
        while cur is not None:
            chain.append(cur)
            cur = parents.get(cur)
        picked.update(id(x) for x in chain)
        if subtree:
            picked.update(id(x) for x in list(node.iter("node"))[:subtree])

    if anchors:
        how = f"名{len(anchors)}" if exact else f"含{len(anchors)}"
        for n in anchors:
            container, _ = own(n, parents, shown)
            take(container if container is not None else n, SKELETON_ROW)
    else:
        rows, seen = [], set()
        for n in visible:
            if n.get("checkable") != "true" or "RadioButton" in (n.get("class") or ""):
                continue                     # 互斥选项不是开关（与 switches_in / Phone.switches 同一判据）
            container, _ = own(n, parents, shown)
            container = container if container is not None else n
            if id(container) not in seen:
                seen.add(id(container))
                rows.append(container)
        if rows:
            rows = rows[:3]
            how = f"回退列表{len(rows)}"
            for container in rows:
                take(container, SKELETON_ROW)
        else:
            how = f"回退前{min(40, len(visible))}"
            picked.update(id(x) for x in visible[:40])

    chosen = [n for n in nodes if id(n) in picked][:SKELETON_NODES]
    pruned = max(0, len(picked) - len(chosen))
    if not chosen:
        return ""

    def pct(value, total):
        return str(max(0, min(100, int(value * 100 / total))))

    def short_id(n):
        value = (n.get("resource-id") or "").strip()
        if ":id/" not in value:
            return ""        # 没有 :id/ 的非标准值不保：可能带任意文字，违反「骨架不含页面文字」
        value = value.rsplit(":id/", 1)[-1].strip()
        return value[:40] + "…" if len(value) > 40 else value

    def flags(n):
        text, desc = sides(n)
        out = ""
        for letter, on in (
                ("c", n.get("clickable") == "true"),
                ("k", n.get("checkable") == "true"),
                ("v", n.get("checked") == "true"),
                ("s", n.get("scrollable") == "true"),
                ("e", n.get("enabled") == "false"),
                ("T", bool(text)),
                ("D", bool(desc)),
                ("N", bool(name) and text == name),
                ("M", bool(name) and desc == name),
                # P 只标「包含但不相等」：精确命中已有 N / M，混在一起会把 #427 的诊断读反
                ("P", bool(name) and ((name in text and text != name) or (name in desc and desc != name)))):
            out += letter if on else ""
        return out

    def node_line(n):
        l, t, r, b = bounds(n)
        cls = (n.get("class") or "").rsplit(".", 1)[-1] or "node"
        parts = [str(depth[n]), cls,
                 ",".join((pct(l, screen_w), pct(t, screen_h), pct(r, screen_w), pct(b, screen_h)))]
        mark = flags(n)
        if mark:
            parts.append(mark)
        rid = short_id(n)
        if rid:
            parts.append("id=" + rid)
        return " ".join(parts)

    def header(count, cut):
        return (f"骨架 v1 页={focus or '未知页面'} 目标={name or '无'} 锚={how}"
                f" 节点={count} 剪枝={cut} 屏={screen_w}x{screen_h}")

    body = [node_line(n) for n in chosen]
    while body:
        text = "\n".join([header(len(body), pruned)] + body)
        if len(text) <= SKELETON_BYTES:
            return text
        body.pop()
        pruned += 1
    return ""
