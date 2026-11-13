"""机型脚本的拨动策略注入面（#1244）：把一页开关关掉的算法收在这里。

与 `recipe_nav` / `recipe_steps` 同一形状、同一方向：工厂收 `(p, g)`，只造闭包、不碰手机；
`recipe_kit.preamble()` 写完生命周期、台账与导航助手之后调 `install(p, g)`，把策略补进同一个
执行作用域。脚本侧只留调用点，前导名字（`require` / `require_switches` / `rt` 等）一律按 `g` 现取，
本模块不 import `recipe_kit`。

归属：同一家族 ≥2 机型使用的进家族分节，跨 ≥2 家族使用的进「跨家族」，只是字面量不同的参数化后
共用一份；别把只有该家族用的实现挪进「跨家族」。导航、入口、选择器与等待归 `recipe_nav`，段体归
`recipe_steps`——这里只放「怎么把开关关掉」那一类（精确匹配、逐行重读、整页全关、父子项、
短按被吞、标题在行外、标题随状态变）。

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


def install(p, g):
    """把拨动策略写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in STRATEGIES.items():
        g[name] = factory(p, g)
