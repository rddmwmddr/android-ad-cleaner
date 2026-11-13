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


def install(p, g):
    """把拨动策略写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in STRATEGIES.items():
        g[name] = factory(p, g)
