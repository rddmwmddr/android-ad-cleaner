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
一个名字，跨模块分派会把两张注入面绕在一起（沿用 #1245）。带 `p.off(only=…)` / `keep=…` 现场的也收
这里（#1253）：词库（`vocab.py`）除了段体表也扫这一张表，`recipe_source.strategy_sources()` 由
脚本的 import 决定扫哪几份，现场跟着实现走、读数不变。

事实层按脚本的 import 解析到本模块的 `STRATEGIES` 表（`recipe_source.SURFACE`，沿用 #1243）：
脚本写 `from recipe_strategies import close_with_plain_tap`，词库与入口速查才扫得到实现。
注入名在本模块内必须唯一（表是扁平的）；`preamble()` 先装 `recipe_nav`、再装这里，同名会盖掉
nav 那几档，所以 nav 已有的名字（`close_named` / `off_exact` / `read_switches`）在这里一律带后缀。

文内按家族分节，`install()` 落在最后。
"""

from typing import Any

# 名字 → 工厂。工厂收 (p, g)，只造闭包、不碰手机，返回写进执行作用域的那个函数。
# 守卫按这张表取注入面的实现源码，比对脚本里还留着的逐字副本（tests/test_recipe_strategies.py）。
STRATEGIES = {}

# 「跨家族」分节收进来的注入名：这些实现必须被 ≥2 个家族使用（#1247 的守卫，判据按节算）。
# 现在这张表全是家族分节（小米系 / OPPO / vivo / 荣耀 / 魅族），没有跨家族条目，所以这里是空的；
# 往这里加名字时先数家族，只有一个家族在用的放家族分节，别开共享库。
SHARED = frozenset()


def __getattr__(name: str) -> Any:
    """注入名在类型层面可见（#1247）：脚本 `if TYPE_CHECKING:` 块里的 import 落到这里。
    运行时这些名字住在执行作用域，模块上没有对应属性，照旧抛 AttributeError。"""
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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


# ---------- OPPO 家族（oppo / oneplus / realme，沿用 #1245；#1253）----------
#
# 一族里逐字相同的拨动过程收在这里；同一个名字在家族内有几套走法的（`read_switches` /
# `close_named` / `hide_carousel`）各占一档、按脚本常量分派，那几张表跟着名字住在 `recipe_nav`
# ——一张表一个名字，跨模块分派会把两张注入面绕在一起。
#
# 剩下的 14 个带 `p.off(only=…)` / `keep=…` 现场的拨动策略在这里（#1253）：词库现在也扫这一张表
# （`recipe_source.strategy_sources()`），现场跟着实现走、读数不变。注入名不能复用 nav 的
# `close_named` / `off_exact`（`preamble()` 先装 nav、再装这里，同名会把它盖掉），所以几套走法
# 各起一个名字；脚本用别名把库按名字回调的那两个钩子绑回旧名（`off_exact = off_exact_paged`、
# `close_named = close_named_optional`），段体里的 `g["off_exact"]` / `g["close_named"]` 不用改。
# 内层闭包仍叫旧名（`off_exact` / `close_named`）：词库按 `call.function == "close_named"` 认
# 「off 在助手里面」，改名会把那份未解析数从「不算」变成「算」。

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
        读到的标题（沿用 #903），不再「核对 0 项」静默收尾。"""
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
        """当前列表里还有开着的就点「全部关闭」，再开一次菜单确认它变灰（沿用 #650）。"""
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


def _oppo_off_exact_paged(p, g):
    def off_exact(names, page, max_screens=16):
        """逐页传入当前可见的精确标题，不把“福利”之类子串扩展到未知服务。"""
        wanted, seen, failed = set(names), set(), set()
        for _ in range(max_screens):
            root = p.tree()
            visible = {title for title, _, _ in p.switches(root)}
            targets = wanted & visible
            seen.update(targets)
            if targets:
                before = len(p.changed)
                expected_changes = {title for title, on, _ in p.switches(root)
                                    if on and title in targets}
                # fast.off 的 only 是子串匹配；把所有非精确命中的可见标题排除。
                # max_screens=1 仍可能翻一页，所以每轮重新获取实际可见页面。
                p.off(only=list(targets), keep=list(visible - targets), page=page, max_screens=1)
                changed = {title for _, title in p.changed[before:]}
                failed.update(expected_changes - changed)
            elif not p.scroll_more():
                break
            # off 已尝试翻到下一屏；只在全局滚动到底后收尾。
            current = {title for title, _, _ in p.switches()}
            if current == visible:
                break
        if failed or wanted - seen:
            print(f"  ! 未关闭 {sorted(failed)}；未找到 {sorted(wanted - seen)}")
            return False
        return True

    return off_exact


def _oppo_off_exact_paged_optional(p, g):
    def off_exact(names, page, max_screens=16):
        """逐页传入当前可见的精确标题，不把子串扩展到未知服务（用于需要翻多屏的页面）。"""
        wanted, seen, failed = set(names), set(), set()
        for _ in range(max_screens):
            root = p.tree()
            visible = {title for title, _, _ in p.switches(root)}
            targets = wanted & visible
            seen.update(targets)
            if targets:
                before = len(p.changed)
                expected = {title for title, on, _ in p.switches(root) if on and title in targets}
                p.off(only=list(targets), keep=list(visible - targets), page=page, max_screens=1)
                changed = {title for _, title in p.changed[before:]}
                failed.update(expected - changed)
            elif not p.scroll_more():
                break
            current = {title for title, _, _ in p.switches()}
            if current == visible:
                break
        if failed or wanted - seen:
            print(f"  ! 未关闭 {sorted(failed)}；本机型无此项 {sorted(wanted - seen)}")
            return not failed
        return True

    return off_exact


def _oppo_close_named_optional(p, g):
    def close_named(names, title, max_screens=12, dependent=(), reopen=None, snapshot=None, optional=()):
        """关掉点名的开关，并核对目标已关、非目标未变。

        optional 里的名字允许这次页面上没有：记成「未显示」并继续；名单其余项缺一个就整段不动。
        """
        # 回读确认数由引擎经 rt 记录
        before = g["read_switches"](title, max_screens) if snapshot is None else snapshot
        g["require_switches"](before, names, title, optional=optional)
        present = [name for name in names if name in before]
        absent = [name for name in names if name not in before]
        if absent:
            note = f"{title}：本次未显示 {'、'.join(absent)}，未操作、不计为已关闭"
            g["SKIPPED_ITEMS"].append(note)
            print("  · " + note, flush=True)
        if not present:
            return
        if not any(before[name] for name in present):
            g["rt"].confirm(len(present))
            print(f"  · {title}：读取确认 {len(present)} 项原已关闭，未点击", flush=True)
            return
        p.top(max_screens)
        p.off(only=list(present), keep=[name for name in before if name not in names],
              page=title, max_screens=max_screens)
        if reopen:
            reopen()
        after = g["read_switches"](title, max_screens)
        g["require"](all(after.get(name) is False for name in present), f"{title}：回读未确认关闭")
        g["require"](all(after.get(name) == state for name, state in before.items()
                    if name not in names and name not in dependent), f"{title}：其他功能开关状态变化")
        g["rt"].confirm(len(present))
        print(f"  · {title}：回读确认 {len(present)} 项关闭", flush=True)

    return close_named


def _oppo_close_named_expect(p, g):
    def close_named(names, page, activity, title=None, max_screens=8, reopen=None, dependent=()):
        """精确核对标题再调用引擎；回读关闭状态，同时保留其他功能开关。"""
        # 回读确认数由引擎经 rt 记录
        before = g["read_switches"](activity, title, max_screens, expect=names)
        g["require_switches"](before, names, page)
        if any(before[name] for name in names):
            p.top(max_screens)
            p.off(only=list(names), keep=[name for name in before if name not in names],
                  page=page, max_screens=max_screens)
            if reopen:
                reopen()
            current = g["read_switches"](activity, title, max_screens, expect=names)
            g["require"](all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
            g["require"](all(current.get(name) == state for name, state in before.items()
                        if name not in names and name not in dependent), f"{page}：其他开关状态变化，请核对")
        g["rt"].confirm(len(names))
        print(f"  · {page}：回读确认 {len(names)} 项关闭", flush=True)

    return close_named


def _oppo_close_named_plain(p, g):
    def close_named(names, page, activity, title, max_screens=8, reopen=None, dependent=()):
        """精确核对标题再调用引擎；回读关闭状态，同时保留其他功能开关。"""
        # 回读确认数由引擎经 rt 记录
        before = g["read_switches"](activity, title, max_screens)
        g["require_switches"](before, names, page)
        if any(before[name] for name in names):
            p.top(max_screens)
            # off 的 only 为子串匹配，keep 排除所有非精确目标（包括未知的相似标题）。
            p.off(only=list(names), keep=[name for name in before if name not in names],
                  page=page, max_screens=max_screens)
            if reopen:
                reopen()
            current = g["read_switches"](activity, title, max_screens)
            g["require"](all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
            g["require"](all(current.get(name) == state for name, state in before.items()
                        if name not in names and name not in dependent), f"{page}：其他开关状态变化，请核对")
        g["rt"].confirm(len(names))
        print(f"  · {page}：回读确认 {len(names)} 项关闭", flush=True)

    return close_named


def _oppo_close_group(p, g):
    def close_group(children, parent, page, max_screens=1):
        """有的开关是父项的子项：父开关一关，子项那两行就从页面上消失了（点不到、也回读不到）。
        父项还开着时先关子项再关父项；父项本来就是关的，子项压根不在页面上，只关父项。"""
        p.top(max_screens)
        first = g["wait_switches"]()
        g["require"](first, f"{page}：页面里没读到开关，未操作")
        if g["read_switches"](max_screens, first=first).get(parent):
            g["close_named"](children, page, max_screens=max_screens)
            g["close_named"]([parent], page, max_screens=max_screens, gone=children)
        else:
            g["close_named"]([parent], page, max_screens=max_screens)

    return close_group


def _oppo_close_all(p, g):
    def close_all(page, max_screens):
        """整页关掉所有开关（逐 App 的广告跟踪列表用），关完回读确认。"""
        # 回读确认数由引擎经 rt 记录
        p.top(max_screens)
        first = g["wait_switches"]()
        g["require"](first, f"{page}：没读到开关，未操作")
        before = g["read_switches"](max_screens, first=first)
        g["require"](before, f"{page}：没读到开关，未操作")
        p.top(max_screens)                   # 读完整页会翻到底；p.off 自己也回顶，这一下是让前后两段都从页顶读
        p.off(page=page, max_screens=max_screens)
        p.top(max_screens)
        current = g["read_switches"](max_screens)
        still = sorted(name for name, on in current.items() if on)
        g["require"](not still, f"{page}：回读未确认关闭（仍有 {len(still)} 项开着）")
        g["rt"].confirm(len(before))

    return close_all


STRATEGIES.update({
    "off_exact": _oppo_off_exact,
    "off_exact_paged": _oppo_off_exact_paged,
    "off_exact_paged_optional": _oppo_off_exact_paged_optional,
    "close_named_optional": _oppo_close_named_optional,
    "close_named_expect": _oppo_close_named_expect,
    "close_named_plain": _oppo_close_named_plain,
    "close_group": _oppo_close_group,
    "close_all": _oppo_close_all,
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


def _vivo_close_named(p, g):
    def close_named(names, page, max_screens=1):
        p.top(max_screens)
        before = g["read_switches"](max_screens)
        g["require_switches"](before, names, page)
        p.top(max_screens)
        # only 在引擎中是包含匹配；明确保留本页其余开关，回读再核对一次。
        p.off(only=names, keep=[name for name in before if name not in names],
              page=page, max_screens=max_screens)
        p.top(max_screens)
        g["verify"](before, g["read_switches"](max_screens), names, page)

    return close_named


STRATEGIES.update({
    "off_one": _vivo_off_one,
    "close_named_vivo": _vivo_close_named,
    "row_switch": _vivo_row_switch,
    "switch_off": _vivo_switch_off,
    "setting_search": _vivo_setting_search,
    "store_personalization": _vivo_store_personalization,
    "confirm2": _vivo_confirm2,
    "dialog_open": _vivo_dialog_open,
    "rows": _vivo_rows,
    "off": _vivo_off,
})


# ---------- 荣耀（#1253）----------
#
# 这三份里只收「关开关的算法」：WKL-AN20 的 `close_named` 带 `p.off(only=…)` 现场，它的扫描助手
# `scan` 一起搬成 `scan_switches`；PNM-AN10 的 `baidu_browser` 是 `browser_settings` 荣耀档按名字
# 回调的钩子（`g["baidu_browser"]`），实现也搬过来了。荣耀专用的导航助手（`settle_page` /
# `labels` / `radio` / `dismiss`）仍留在脚本：它们读的是这一台的页面，别家不用。

def _honor_baidu_browser(p, g):
    def baidu_browser():
        """新机预装 com.hihonor.baidu.browser（沿用 #87 社区实测 PTP-AN00）：我的 → 右上齿轮 → 消息设置 / 隐私设置。
        「广告设置」是网页，读不到开关；其中「不看程序化广告」「不看个性化广告」要打开，请手动处理。"""
        import re

        from fast import bounds

        p.start("com.hihonor.baidu.browser")
        p.dismiss()
        for text, (l, t, r, b), _ in p.texts():
            if text == "我的" and t >= p.H * 0.8:
                p.click((l + r) // 2, (t + b) // 2); g["time"].sleep(1); break
        else:
            print("  ✗ 没找到底部「我的」"); return False
        icons = [n for n in p.tree().iter("node") if n.get("clickable") == "true" and p.on_screen(n)
                 and bounds(n)[3] < p.H * 0.15 and bounds(n)[0] > p.W * 0.5
                 and re.search(r"设置|setting", (n.get("content-desc") or "") + (n.get("resource-id") or ""), re.I)]
        if len(icons) != 1:
            print("  ✗ 没找到右上角唯一的设置图标"); return False
        l, t, r, b = bounds(icons[0]); p.click((l + r) // 2, (t + b) // 2); g["time"].sleep(1)
        if p.tap("消息设置", exact=True):
            p.off(only=["新闻热点", "兴趣推送"], page="浏览器·消息设置")
            p.back()
        if p.tap("隐私设置", exact=True):
            p.off(only=["搜索个性化推荐", "搜索下一条推荐"], page="浏览器·隐私设置")
            p.back()
        print("  · 「隐私设置 → 偏好设置 → 广告设置」是网页，请手动打开「不看程序化广告」「不看个性化广告」")
        p.back(2)
        return False

    return baidu_browser


def _honor_scan_switches(p, g):
    def scan_switches(max_screens):
        states = {}
        for index in range(max_screens):
            for title, state, _ in p.switches():
                g["require"](bool(title), "出现无标题开关，未操作")
                g["require"](title not in states or states[title] == state, "同名开关状态不一致，未操作")
                states[title] = state
            if not p.scroll_more():
                return states
            g["require"](index + 1 < max_screens, "列表超过扫描上限，未确认完整列表")
        return states

    return scan_switches


def _honor_close_named(p, g):
    def close_named(names, title, package, marker, max_screens=6, drawn=False):
        """精确标题白名单；操作前完整扫描，操作后核对目标及其他开关。"""
        from fast import Phone, want_state

        # 回读确认数由引擎经 rt 记录
        g["settle_page"](package, marker)
        native = p.switches

        def read(root=None):
            root = root if root is not None else p.tree()
            g["require"](p.focus().split("/", 1)[0] == package and marker in g["labels"](root),
                         "已离开目标设置页，停止读取开关")
            # 仅阅读的「广告推荐服务」设置页允许截图识别自绘开关，不写图片文件。
            if drawn:
                g["require"](package == "com.hihonor.dz.reader" and marker == "广告推荐服务",
                             "此页不允许自绘开关截图")
                return Phone.switches(p, root)
            return native(root)

        p.switches = read
        try:
            p.top(max_screens)
            before = g["scan_switches"](max_screens)
            # OAID 的应用名称随安装列表变化，不把机主应用清单写入脚本。
            wanted = set(before) if names is None else set(names)
            g["require_switches"](before, wanted, title)
            p.top(max_screens)
            p.switches = lambda root=None: [item for item in read(root) if item[0] in wanted]
            p.off(only=sorted(wanted), page=title, max_screens=max_screens)
            p.switches = read
            p.top(max_screens)
            after = g["scan_switches"](max_screens)
            g["require"](all(after.get(name) == want_state(name) for name in wanted),
                         title + "：回读未确认目标状态")
            g["require"](all(after.get(name) == state for name, state in before.items() if name not in wanted),
                         title + "：其他开关状态变化，请机主核对")
            g["rt"].confirm(len(wanted))
            print(f"  · {title}：已回读 {len(wanted)} 项", flush=True)
        finally:
            p.switches = native

    return close_named


# ---------- 魅族（#1253）----------
#
# 只有 `safe_switches` 这一档：读开关前先确认没换页、没有别的窗口压在上面。判据里那两件事由脚本的
# `assert_no_other_window` 与 `TARGET_PACKAGE` 约定给出，仍留在脚本，这里按名字从执行作用域取。

def _meizu_safe_switches(p, g):
    def safe_switches(activity):
        g["require"](p.focus() == activity, "页面已变化，停止本段")
        root = p.tree()
        g["assert_no_other_window"](root, activity.split("/", 1)[0])
        return p.switches(root)

    return safe_switches


# ---------- 三星 ----------
#
# `protect` 仍是本机函数：它写的是这一页「点标题而不是点开关、把保护类开关拨回开」，且是沿用 #608 的
# 临时回退，等真机复测通过后才换回 `p.off`。按归属规则（只服务一台机）留在脚本里。


STRATEGIES.update({
    "baidu_browser": _honor_baidu_browser,
    "scan_switches": _honor_scan_switches,
    "close_named_honor": _honor_close_named,
    "safe_switches": _meizu_safe_switches,
})


def install(p, g):
    """把拨动策略写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in STRATEGIES.items():
        g[name] = factory(p, g)
