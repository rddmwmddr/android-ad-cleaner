"""机型脚本的拨动策略注入面（#1244）：把一页开关关掉的算法收在这里。

与 `recipe_nav` / `recipe_steps` 同一形状、同一方向：工厂收 `(p, g)`，只造闭包、不碰手机；
`recipe_kit.preamble()` 写完生命周期、台账与导航助手之后调 `install(p, g)`，把策略补进同一个
执行作用域。脚本侧只留调用点，前导名字（`require` / `require_switches` / `rt` 等）一律按 `g` 现取，
本模块不 import `recipe_kit`。

归属：同一家族 ≥2 机型使用的进家族分节，跨 ≥2 家族使用的进「跨家族」，只是字面量不同的参数化后
共用一份；别把只有该家族用的实现挪进「跨家族」。导航、入口、选择器与等待归 `recipe_nav`，段体归
`recipe_steps`——这里只放「怎么把开关关掉」那一类（精确匹配、逐行重读、整页全关、父子项、
短按被吞、标题在行外、标题随状态变）。同一个注入名在家族里有几套走法、由脚本常量选的
（`read_switches` / `close_named` / `hide_carousel`），分派表跟着名字住在 `recipe_nav`：一张表
一个名字，跨模块分派会把两张注入面绕在一起（#1245）。函数体里带着 `vocab.py` 要列的
`p.off(only=…)` / `keep=…` 现场的，继续留在机型脚本里，别为了收口把那份证据搬走。

事实层按脚本的 import 解析到本模块的 `STRATEGIES` 表（`recipe_source.SURFACE`，沿用 #1243）：
脚本写 `from recipe_strategies import close_with_plain_tap`，词库与入口速查才扫得到实现。

文内按家族分节，`install()` 落在最后。
"""

# 名字 → 工厂。工厂收 (p, g)，只造闭包、不碰手机，返回写进执行作用域的那个函数。
# 守卫按这张表取注入面的实现源码，比对脚本里还留着的逐字副本（tests/test_recipe_strategies.py）。
STRATEGIES = {}


# ---------- 小米系（xiaomi / redmi，#1244）----------

def _xiaomi_close_with_plain_tap(p, g):
    def close_with_plain_tap(names, page):
        """下载管理和浏览器会吞掉短按；普通 tap 后确认，并核对其他开关未变。"""
        before = {title: on for title, on, _ in p.switches()}
        targets = [title for title in before if any(name in title for name in names)]
        g["require_switches"](before, names, page, contains=True)
        for title in targets:
            if not before[title]:
                continue
            xy = next((xy for t, on, xy in p.switches() if t == title and on), None)
            if not xy:
                raise RuntimeError(f"{page}：目标开关位置未识别，停止本页")
            p.d.shell(f"input tap {xy[0]} {xy[1]}")
            g["time"].sleep(0.5)
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

    return close_with_plain_tap


def _xiaomi_gear_tap(p, g):
    def gear_tap(pkg, activity):
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
                g["time"].sleep(1.2)
                return p.focus().split("/", 1)[0] == pkg and activity in p.focus()
        return False

    return gear_tap


STRATEGIES.update({
    "close_with_plain_tap": _xiaomi_close_with_plain_tap,
    "gear_tap": _xiaomi_gear_tap,
})


# ---------- OPPO 家族（oppo / oneplus / realme，#1245）----------
#
# 一族里逐字相同的拨动过程收在这里；同一个名字在家族内有几套走法的（`read_switches` /
# `close_named` / `hide_carousel`）各占一档、按脚本常量分派，那几张表跟着名字住在 `recipe_nav`
# ——一张表一个名字，跨模块分派会把两张注入面绕在一起。
#
# 留在脚本里的策略函数不是漏收：函数体里的 `p.off(only=list(targets), …)` 与 `keep=…` 是
# `vocab.py` 的「未解析」台账现场，`close_all` 的整页关闭也计入那一节的数；#1237 的判据要求
# 这几个数逐字不变，搬走就把证据一起搬没了（沿用 #1148 的口径）。

def _oppo_off_exact(p, g):
    def off_exact(names, activity, title):
        """只处理当前页精确匹配的开关，并在同一页面读回（PHK110 的 Android 15 变体）。"""
        if not g["page"](activity, title):
            return False
        switches = p.switches()
        visible = {name for name, _, _ in switches}
        wanted = set(names)
        if not wanted <= visible:
            print(f"  ! 缺少开关 {sorted(wanted - visible)}，本页不操作")
            return False
        for name in names:
            if not g["page"](activity, title):
                return False
            matches = [(on, xy) for label, on, xy in p.switches() if label == name]
            if len(matches) != 1:
                print(f"  ! 开关「{name}」无法唯一确认，停止")
                return False
            on, xy = matches[0]
            if on:
                p.click(*xy)
                p.confirm()
                if not g["page"](activity, title):
                    return False
                after = [(on, xy) for label, on, xy in p.switches() if label == name]
                if len(after) != 1 or after[0][0]:
                    print(f"  ! 开关「{name}」未确认关闭")
                    return False
                p.changed.append((title, name))
                print(f"  关 {name}")
        states = {name: on for name, on, _ in p.switches() if name in wanted}
        if set(states) != wanted or any(states.values()):
            print("  ! 开关未全部确认关闭")
            return False
        return True

    return off_exact


def _oppo_close_titles(p, g):
    def close_titles(wanted, max_rounds=8):
        """逐页只点标题完全等于 wanted 里某项的开关，点完回读。
        ColorOS 17 有「应用建议」是「应用建议小卡」子串的情况，p.off 的子串匹配会误伤，所以用精确标题。"""
        remaining, failed = list(wanted), []
        for _ in range(max_rounds):
            cur = {t: (c, xy) for t, c, xy in p.switches()}
            hit = [t for t in remaining if t in cur]
            for t in hit:
                cur = {t2: (c, xy) for t2, c, xy in p.switches()}
                was_on = bool(cur.get(t, (False, None))[0])
                for _ in range(3):
                    cur = {t2: (c, xy) for t2, c, xy in p.switches()}
                    if t not in cur:
                        break
                    c, xy = cur[t]
                    if not c:
                        break
                    if not (0 < xy[0] < p.W and 0 < xy[1] < p.H):
                        print(f"  ! 「{t}」坐标越界，跳过不做")
                        break
                    p.click(*xy)
                    g["time"].sleep(0.5)
                    p.confirm()
                    g["time"].sleep(0.5)
                final = {t2: c for t2, c, _ in p.switches()}
                remaining.remove(t)
                if final.get(t) is False:
                    print(f"  {'关' if was_on else '· 已是关闭状态'} {t}")
                elif t in final:
                    print(f"  ✗ 关不掉 {t}")
                    failed.append(t)
            if not remaining:
                break
            if not p.scroll_more():
                break
        if remaining:
            print(f"  ! 未找到 {remaining}")
        return not failed and not remaining

    return close_titles


def _oppo_read_on_page(p, g):
    def read_on_page(titles, package):
        """确认落在目标页并读出这一页的开关：读不到目标时整段不动，报错带上停在哪个页与当次
        读到的标题（#903），不再「核对 0 项」静默收尾。"""
        from wait import until

        g["page"](titles, package)
        until(p.switches, tries=10, poll=0.2, now=g["time"].time, sleep=g["time"].sleep)
        return {text: on for text, on, _ in p.switches()}

    return read_on_page


def _oppo_wait_switches(p, g):
    def wait_switches(timeout=4.0):
        """刚进二级页时开关还没画出来：等一下再读，别把空页面当成「没找到目标开关」。"""
        end = g["time"].time() + timeout
        while True:
            found = p.switches()
            if found:
                return found
            if g["time"].time() >= end:
                return []
            g["time"].sleep(0.2)

    return wait_switches


def _oppo_close_all_listed(p, g):
    def close_all_listed(label):
        """当前列表里还有开着的就点「全部关闭」，再开一次菜单确认它变灰（#650）。"""
        state = g["menu_state"]()
        if state.close_all_disabled:
            p.back()
            print(f"  · 广告跟踪（{label}）：已全部关闭，未点击", flush=True)
            return
        g["require"](p.tap("全部关闭", exact=True, scrolls=0), "未能点「全部关闭」")
        p.confirm()
        p.await_page()
        state = g["menu_state"]()
        p.back()
        g["require"](state.close_all_disabled, f"广告跟踪（{label}）：点了「全部关闭」后仍有开着的应用")
        print(f"  · 广告跟踪（{label}）：已全部关闭，菜单项已置灰确认", flush=True)

    return close_all_listed


def _oppo_close_rows(p, g):
    def close_rows(names, page):
        """逐项关掉列表里的这些开关。

        首页卡片管理这一类页面，关掉一项这一行就从列表里消失、下面的行整体上移，
        拿一批旧坐标连点会点到邻居——2026-11-02 实测就是这样误关了本该保留的「便捷服务」。
        所以每关一项都重新读一次坐标。
        """
        done = []
        for _ in range(len(names) * 3 + 4):
            todo = [(t, xy) for t, on, xy in p.switches() if t in names and on]
            if not todo:
                break
            title, xy = todo[0]
            p.click(*xy)
            g["time"].sleep(0.9)
            done.append(title)
        print(f"  · {page}：关了 {len(done)} 项" + (f"（{'、'.join(done)}）" if done else ""))
        return len(done)

    return close_rows


STRATEGIES.update({
    "off_exact": _oppo_off_exact,
    "close_titles": _oppo_close_titles,
    "read_on_page": _oppo_read_on_page,
    "wait_switches": _oppo_wait_switches,
    "close_all_listed": _oppo_close_all_listed,
    "close_rows": _oppo_close_rows,
})


# ---------- vivo（#1246）----------
#
# vivo 系的关开关过程：商店把标题放在开关行外（`row_switch` / `switch_off`），
# 推荐类开关点完弹「温馨提示」（`confirm2` / `rows` / `off`），vivo 的列表行标题会串到上一行，
# 引擎的 `p.switches()` 在这台上会把同一行点两遍（V2547A 的 `off`）。这些都收在这里。
#
# `read_switches` 的 vivo 档（标题按点号前半段归并）跟名字住在 `recipe_nav`，它读的是开关不是
# 关开关的算法；`close_named` 的 meizu 档同理（一张表一个名字，跨模块分派会把两张注入面绕在一起）。

def _vivo_off_one(p, g):
    def off_one(keyword, page):
        """按开关自身状态关一个开关并回读。返回 None=本来关着，True=关掉，False=没关掉。

        （旧注释说的「标题随状态变化致引擎误报」已由引擎在标题产出处剥掉尾缀修复，沿用 #565；
        本页的独立回读保留——没有真机，不敢顺手改脚本行为。）"""
        hits = [(t, c, xy) for t, c, xy in p.switches() if keyword in t]
        if not hits:
            print(f"  ✗ 没找到「{keyword}」开关"); return False
        if not hits[0][1]:
            print(f"  · {keyword} 本来就是关的")
            return None
        p.click(*hits[0][2]); p.confirm(); g["time"].sleep(0.5)
        for t, c, _ in p.switches():
            if keyword in t and not c:
                print(f"  关 {keyword}")
                p.changed.append((page, keyword))
                return True
        print(f"  ✗ 关不掉 {keyword}")
        return False

    return off_one


def _vivo_row_switch(p, g):
    def row_switch(title):
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

    return row_switch


def _vivo_switch_off(p, g):
    def switch_off(title, page, tries=2):
        """`p.off()` 的开关标题取自同一行，商店这页标题在行外会配错，所以单独回读。

        关掉的项与 `p.off()` 一样记进 `p.changed`，并区分「本来就是关」和「这次关掉」。"""
        for _ in range(tries):
            state = g["row_switch"](title)
            if state is None:
                print(f"  ? {title}：没找到")
                return False
            if not state[0]:
                print(f"  · {title}：本来就是关")
                return True
            p.click(*state[1]); g["time"].sleep(0.9); p.confirm(); g["time"].sleep(0.9)
            now = g["row_switch"](title)
            if now is not None and not now[0]:
                p.changed.append((page, title))
                print(f"  关 {title}")
                return True
        print(f"  ✗ 关不掉 {title}")
        return False

    return switch_off


def _vivo_setting_search(p, g):
    def setting_search(keyword, result):
        """设置页层级变了就用搜索兜底。"""
        try:
            return bool(p.setting(keyword, result))
        except Exception as e:
            print(f"  设置搜索「{keyword}」没走通：{e}")
            return False

    return setting_search


def _vivo_store_personalization(p, g):
    def store_personalization():
        """两行标题会随状态变化；逐行点，处理确认框后用稳定标题回读。"""
        page = "商店·个性化推荐"
        names = ["个性化推荐", "个性化广告推荐"]
        before = g["read_switches"]()
        g["require_switches"](before, names, page)
        for name in names:
            rows = [(state, xy) for title, state, xy in p.switches() if g["title_key"](title) == name]
            g["require"](len(rows) == 1, f"{page}：无法唯一识别「{name}」，未操作")
            if not rows[0][0]:
                continue
            signature = p.sig()
            p.click(*rows[0][1])
            p.settle(signature, 1.5)
            # 本机按钮未被通用 confirm() 识别；只点明确的“确认关闭”，不点状态文字。
            if p.find("确认关闭", exact=True):
                g["tap"]("确认关闭", scrolls=0)
            else:
                p.confirm()
            g["require"](g["read_switches"]().get(name) is False, f"{page}：「{name}」回读未确认关闭")
            p.changed.append((page, name))
            print(f"  关 {name}", flush=True)
        g["verify"](before, g["read_switches"](), names, page)

    return store_personalization


def _vivo_confirm2(p, g):
    def confirm2():
        """关掉推荐开关后，vivo 会弹「温馨提示 → 取消 / 确认关闭」。

        这个框的按钮 text 是空的（android:id/button1=取消、button2=确认关闭），
        标题挂在下层 TextView（resource-id=...vbutton_title）里。引擎的 `p.confirm()` 理论上已覆盖
        这个形状，但没在 V2547A 真机上验过，暂留这份（沿用 #397）。"""
        g["time"].sleep(0.35)
        root = p.tree()
        for n in root.iter("node"):
            if n.get("clickable") != "true" or "Button" not in (n.get("class") or ""):
                continue
            labels = [(x.get("text") or "").strip() for x in n.iter("node")]
            hit = next((w for w in g["CONFIRM"] if w in labels), None)
            if not hit:
                continue
            l, t, r, b = g["bounds_of"](n)
            if r - l <= 0 or b - t <= 0:
                continue
            p.click((l + r) // 2, (t + b) // 2)
            g["time"].sleep(0.35)
            return hit
        return None

    return confirm2


def _vivo_dialog_open(p, g):
    def dialog_open():
        """当前屏是不是挡着一个带「取消」的确认框（用来发现没关掉的弹窗）。"""
        root = p.tree()
        tx = {(n.get("text") or "").strip() for n in root.iter("node")}
        return "取消" in tx and not p.switches(root)

    return dialog_open


def _vivo_rows(p, g):
    def rows():
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
            l, t, r, b = g["bounds_of"](n)
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
            l, t, r, b = g["bounds_of"](n)
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

    return rows


def _vivo_off(p, g):
    def off(only=None, keep=(), page="", max_screens=30):
        """只关匹配的开关，每行点一次。引擎自带的 p.off 在 vivo 上会把同一行点两遍。"""
        done = 0
        tried = {}                                  # 标题 -> 点过几次，防止在同一行上反复空点
        for _ in range(2 if p.miss else 8):          # 页面刚打开还没画完
            if p.switches():
                break
            g["time"].sleep(0.25)
        for _ in range(max_screens):
            todo = []
            for t, c, xy in g["rows"]():
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
                g["time"].sleep(0.3)
                hit = g["confirm2"]()               # 这个弹窗按钮没有 text，见 confirm2() 的说明
                if hit:
                    print(f"  · 二次确认点了「{hit}」")
                g["time"].sleep(0.15)
                if g["dialog_open"]():               # 弹窗还在：不再点了，避免又被遮罩关掉、来回拨
                    print(f"  ✗ {page}：确认框关不掉，停止本页")
                    p.back(1)
                    return done
                tried[t] = tried.get(t, 0) + 1
                if any(tt == t and cc for tt, cc, _ in g["rows"]()):
                    continue                        # 还开着，下一屏再看
                print(f"  关 {t}")
                p.changed.append((page, t))
                done += 1
            if not p.scroll_more():
                break
        left = [t for t, c, _ in g["rows"]() if c and t and t in tried]
        for t in dict.fromkeys(left):
            print(f"  ✗ 关不掉 {t}")
        return done

    return off


STRATEGIES.update({
    "off_one": _vivo_off_one,
    "row_switch": _vivo_row_switch,
    "switch_off": _vivo_switch_off,
    "setting_search": _vivo_setting_search,
    "store_personalization": _vivo_store_personalization,
    "confirm2": _vivo_confirm2,
    "dialog_open": _vivo_dialog_open,
    "rows": _vivo_rows,
    "off": _vivo_off,
})


# ---------- 荣耀 / 魅族 / 三星（#1246）----------
#
# 这三家都不足以为「关开关的算法」开一节：魅族的 `close_named` 是共享名的一档、住 `recipe_nav`
# （一张表一个名字，沿用 #1245）；荣耀三份里只有 WKL-AN20 的 `close_named` / `scan` 带
# `p.off(only=…)` 现场，按同一口径留在脚本；三星的 `protect` 只有一台机用、按归属规则
# 留在脚本里。所以这里没有它们的条目——不是漏收。


def install(p, g):
    """把拨动策略写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in STRATEGIES.items():
        g[name] = factory(p, g)
