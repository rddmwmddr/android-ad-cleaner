"""机型脚本的公共导航助手（#1150）：跨文件逐字相同的那些导航过程收在这里。

`recipe_kit.preamble()` 写完生命周期与台账之后调用 `install(p, g)`，把公共导航补进同一个
执行作用域。脚本本地定义的同名名字后执行、覆盖注入版，所以同名多簇的机型差异继续留在各自
脚本里，搬过来的只有逐字相同的副本（迁移后脚本侧只删定义、不改调用点）。

实现不 import `recipe_kit`：`skip` / `require` 这类前导名字由工厂从 `g` 取、包进闭包，
两个模块因此没有依赖关系（方向只有 `preamble()` → `install()` 这一条）。

实现体必须与被搬走的脚本副本逐字相同：守卫把工厂里返回的函数源码与脚本里还留着的本地定义
按行比对，改一边不改另一边即红（tests/test_recipe_nav.py）。`g["X"]` 现取与随之消失的
`global X` 是搬动本身带来的改写，比对前由守卫折算掉。

闭包对名字一律按 `g` 现取（包括 `g["time"]`）：脚本原来是在自己的全局里解析这些名字，换到
这个模块后仍取当次执行作用域里的那一个，测试装的假时钟才照旧生效。
"""

import time

from wait import until

# 名字 → 工厂。工厂收 (p, g)，只造闭包、不碰手机，返回写进执行作用域的那个函数。
# 守卫按这张表取注入面的实现源码，比对脚本里还留着的逐字副本（tests/test_recipe_nav.py）。
NAV = {}


# ---------- vivo ----------
#
# `browser_settings` 收的是「不含拉起 App」那一簇：vivo 浏览器没有底部「我的」，入口在右上菜单。
# 含 `p.start` 的另一簇不在范围里：`entries.used_by` 从脚本源码扫 `p.start` / `start_or_skip` /
# `am start -n` / `p.setting` 四类入口，搬走后入口速查会静默漏机型（沿用 #1148 定案 3）。
# V2309A 与 V2547A 各有一份写法不同的同名实现，按「同名多簇一律留脚本原样」不搬。

def _vivo_settings_home(p, g):
    def settings_home():
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    return settings_home


def _vivo_browser_settings(p, g):
    def browser_settings(tries=2):
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
    return browser_settings


NAV["settings_home"] = _vivo_settings_home
NAV["browser_settings"] = _vivo_browser_settings


# ---------- OPPO 家族 ----------
#
# ColorOS 脚本共用的导航过程。`SEARCH_TITLES` 与 `wait_page` 是脚本侧的东西：PLP120 的
# 搜索页标题名单比一加两台长，PHK110 / PKX110 / PKH110 的 `wait_page` 各有本地实现
# （代码同形、注释与折行不同），闭包从执行作用域现取、注入版不替它们判断。
# `browser_settings` 上文已被 vivo 的菜单版占用，OPPO 这一版是公开 Intent 直达，
# 另起名字 `browser_settings_direct`，三份脚本的调用点跟着改名（#1153）。

def _oppo_wait_search_settings(p, g):
    def wait_search_settings(tries=30):
        from wait import until

        def sample():
            focus = p.focus()
            if "com.heytap.quicksearchbox" not in focus or "Setting" not in focus:
                return False
            return bool(g["SEARCH_TITLES"] & {text for text, _, _ in p.texts()})

        clock = g["time"]
        return bool(until(sample, tries=tries, same=2, now=clock.monotonic, sleep=clock.sleep))
    return wait_search_settings


def _oppo_settings_page(p, g):
    def settings_page(*path):
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
        g["time"].sleep(1.2)
        for t in path:
            if not p.tap(t, exact=True):
                return False
        return True
    return settings_page


def _oppo_tap_page(p, g):
    def tap_page(text, activity, title):
        return p.tap(text, exact=True) and g["wait_page"](activity, title)
    return tap_page


def _oppo_open_app_settings(p, g):
    def open_app_settings(package, activity, title):
        # 两个 App 均实测支持此公开设置 Intent，绕开含账号信息的“我的”页。
        result = p.d.shell(
            "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package
        ).output
        if "Permission Denial" in result or "SecurityException" in result:
            print("  ! 系统不允许直达设置，跳过，不提升权限")
            return False
        return g["wait_page"](activity, title)
    return open_app_settings


def _oppo_browser_settings_direct(p, g):
    def browser_settings_direct():
        return g["open_app_settings"]("com.heytap.browser",
                                      "com.heytap.browser.settings.component.BrowserPreferencesPage",
                                      "浏览器")
    return browser_settings_direct


NAV["wait_search_settings"] = _oppo_wait_search_settings
NAV["settings_page"] = _oppo_settings_page
NAV["tap_page"] = _oppo_tap_page
NAV["open_app_settings"] = _oppo_open_app_settings
NAV["browser_settings_direct"] = _oppo_browser_settings_direct


# ---------- 跨家族 ----------
#
# `tap`：按名字点入口、找不到就 `require` 报错。一加 PJA110 与 vivo V2417A 各一份逐字相同。
# 另外两份同名的（honor-WKL-AN20 的 `scrolls=6`、oppo-PKT110 的 `exact=`）签名不同，留本地覆盖。

def _plain_tap(p, g):
    def tap(name, scrolls=4):
        g["require"](p.tap(name, exact=True, scrolls=scrolls), f"未找到入口「{name}」")
    return tap


NAV["tap"] = _plain_tap


def install(p, g):
    """把公共导航助手写进执行作用域 `g`（原地写，调用方不需要返回值）。"""
    for name, factory in NAV.items():
        g[name] = factory(p, g)


# ---------- 小米系（xiaomi / redmi，#1151）----------
#
# 三兄弟（23113RKC6C / 23117RK66C / 24122RKC7C）的 `gear`，与 23113RKC6C / 24122RKC7C /
# 24129PN74C 那份不带 docstring 的 `tap_any`，与这里的实现不是逐字相同（排版、循环变量名有别），
# 按本票判据不收，留在脚本里覆盖注入版。

def _xiaomi_tap_any(p, g):
    def tap_any(*names, scrolls=6):
        """依次试几个入口名，点中一个就返回 True。"""
        return any(g["maybe"](n, scrolls) for n in names)

    return tap_any


def _xiaomi_gear(p, g):
    def gear(toolbar_only=False):
        """很多小米 App 的设置是右上角齿轮图标，没有文字。
        匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
        重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（#305 / #374）。"""
        from fast import bounds, icon_hit

        for n in p.tree().iter("node"):
            l, t, r, b = bounds(n)
            icon = "ImageView" in n.get("class", "") and r-l < p.W * 0.25 and b-t < p.H * 0.15
            if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n) and (not toolbar_only or b < p.H * 0.23):
                p.click((l + r) // 2, (t + b) // 2); g["time"].sleep(1)
                return True
        if not toolbar_only and p.find("设置", exact=True, edge_ok="tab"):
            return p.tap("设置", exact=True, scrolls=0)
        # 下载管理、天气和日历的齿轮藏在右上「更多」菜单里。
        for n in p.tree().iter("node"):
            key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
            from fast import bounds
            l, t, r, b = bounds(n)
            if any(k in key.lower() for k in ("更多", "more", "menu")) and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22:
                p.click((l + r) // 2, (t + b) // 2); g["time"].sleep(0.5)
                if p.tap("设置", exact=True, scrolls=0):
                    return True
                break
        return False

    return gear


def _xiaomi_read_switches(p, g):
    def read_switches(max_screens):
        current = {}
        for index in range(max_screens):
            current.update({title: on for title, on, _ in p.switches()})
            if index + 1 == max_screens or not p.scroll_more():
                break
        return current

    return read_switches


def _xiaomi_close_named(p, g):
    def close_named(names, page, max_screens=2):
        """只关闭点名的开关；操作前确认目标存在，操作后回读，并检查其他开关未被改动。
        开关标题可能附带整段说明，所以按关键词匹配，不做完整标题相等判断。"""
        p.top(max_screens)
        before = g["read_switches"](max_screens)
        targets = [title for title in before if any(name in title for name in names)]
        g["require_switches"](before, names, page, contains=True)
        p.top(max_screens)
        p.off(only=names, page=page, max_screens=max_screens)
        p.top(max_screens)
        current = g["read_switches"](max_screens)
        g["require"](all(current.get(title) is False for title in targets), f"{page}：回读未确认关闭")
        g["require"](all(current.get(title) == state for title, state in before.items() if title not in targets),
                     f"{page}：其他开关状态变化，请核对")
        g["VERIFIED_SWITCHES"] += len(targets)

    return close_named


def _xiaomi_security_tab(p, g):
    def security_tab():
        """HyperOS 3 的「安全」是隐私页上方的标签，不是设置行。
        按文字点会命中不可点击的标签文字；这里只点横跨半屏、位于顶部的可点击容器。"""
        for text, (l, t, r, b), node in p.texts():
            if (text == "安全" and node.get("clickable") == "true"
                    and r - l > p.W * 0.3 and t < p.H * 0.25):
                p.click((l + r) // 2, (t + b) // 2)
                g["time"].sleep(0.8)
                return True
        return False

    return security_tab


NAV.update({
    "tap_any": _xiaomi_tap_any,
    "gear": _xiaomi_gear,
    "read_switches": _xiaomi_read_switches,
    "close_named": _xiaomi_close_named,
    "security_tab": _xiaomi_security_tab,
})
