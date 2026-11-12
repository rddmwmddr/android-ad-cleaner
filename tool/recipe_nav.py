"""机型脚本的公共导航助手（#1150）：跨文件代码逐字相同的那些导航过程收在这里。

`recipe_kit.preamble()` 写完生命周期与台账之后调用 `install(p, g)`，把公共导航补进同一个
执行作用域。脚本本地定义的同名名字后执行、覆盖注入版，所以同名多簇的机型差异继续留在各自
脚本里，搬过来的只有代码逐字相同的副本（迁移后脚本侧只删定义、不改调用点）。

实现不 import `recipe_kit`：`skip` / `require` 这类前导名字由工厂从 `g` 取、包进闭包，
两个模块因此没有依赖关系（方向只有 `preamble()` → `install()` 这一条）。

实现体必须与被搬走的脚本副本代码逐字相同：守卫把工厂里返回的函数源码与脚本里还留着的本地定义
都折成 AST（剥注释、docstring、折行）后比对，改一边不改另一边即红（tests/test_recipe_nav.py）。
`g["X"]` 现取与随之消失的 `global X` 是搬动本身带来的改写，比对前由守卫折算掉。

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
# V2547A 有一份代码不同的同名实现，按「同名多簇一律留脚本原样」不搬；V2309A 那份代码与这里
# 相同（当时按文本判成「写法不同」），#1153 起走注入版。

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

        return bool(until(sample, tries=tries, same=2,
                          now=g["time"].monotonic, sleep=g["time"].sleep))
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
# 23113RKC6C / 24122RKC7C / 24129PN74C 那份 `tap_any` 与本实现循环变量名不同，按「同名多簇」
# 留在脚本里覆盖注入版。三兄弟（23113RKC6C / 23117RK66C / 24122RKC7C）与 24094RAD4C 的 `gear`
# 只差排版，按代码逐字判据在 #1153 一并删掉、改走注入版。

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


# ---------- OPPO 两大对：PLZ110 / PMX110 与 PLG110 / PMA110（#1154）----------
#
# 一对里代码逐字相同的导航过程收在这里，两份脚本各删本地定义、调用点一字不改。
# `app_settings` 与 `system_settings` 在两对里各自成簇（同一对里逐字相同、跨对代码不同），
# 一个名字只能放一簇：这里放 PLZ110 / PMX110 那份，PLG110 / PMA110 的同名实现留在脚本里覆盖。
#
# `close_named` 不在这一簇：注入面的这个名字已被小米系（#1151）占用，PLZ110 / PMX110 那份带
# `snapshot` / `optional`、代码不同，按「同名多簇一律留脚本原样」继续留在两份脚本里。
#
# `assistant_settings` 与 `at_assistant` / `assistant_icon` 的常量与下一步由脚本侧给出：
# PLG110 与 PMA110 各有一份同名的本地 `tap_page`，闭包从执行作用域现取。`row` 与
# `carousel_choices` 的 `bounds` 同样按执行作用域取，两份 PLG/PMA 脚本的 `from fast import …`
# 因此要留着（那条 import 唯一的读者是注入版）。

def _plz_open_page(p, g):
    def open_page(command, title, package, activity=None):
        result = p.d.shell(command)
        g["require"](not result.exit_code and not any(word in result.output for word in
                      ("Error", "Exception", "Permission Denial", "unable to resolve")),
                     "系统未允许打开设置页")
        g["page"](title, package, activity)
    return open_page


def _plz_app_settings(p, g):
    def app_settings(package):
        g["open_page"]("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package,
                       "返回" if package == g["THEME"] else "软件商店", package, "SettingActivity")
    return app_settings


def _plz_row(p, g):
    def row(text, title=None, package=None, activity=None, scrolls=8, tries=1):
        """只点具名导航行，避免点隐私页的过度授权横幅；坐标来自当前节点。

        `text` 可以给一组等价文案，按顺序试：软件商店的隐私入口随商店 App 版本叫「隐私」或
        「隐私授权管理」（#907）。认不到时留下停在哪个页面与结构摘要，与 note_miss 同形。
        `tries` 是点击被弹窗淡出动画吞掉时的重试次数（#286）；页面没换才重点，坐标仍然有效。"""
        names = (text,) if isinstance(text, str) else tuple(text)
        p.await_page()
        where = p.focus()
        for index in range(scrolls + 2):
            root = p.tree()
            parents = {child: node for node in root.iter() for child in node}
            for name in names:
                matches = [n for n in root.iter("node")
                           if (n.get("text") or n.get("content-desc") or "").strip() == name
                           and p.on_screen(n)]
                g["require"](len(matches) <= 1, f"「{name}」入口不唯一，未点击")
                if not matches:
                    continue
                node = matches[0]
                target = node
                while target is not None and target.get("clickable") != "true":
                    target = parents.get(target)
                target = target if target is not None else node
                l, t, r, b = g["bounds"](target)
                g["require"](r > l and b > t and p.on_screen(target), "入口坐标无效")
                g["require"](p.focus() == where, "找入口期间页面变了，未点击")
                for _ in range(tries):
                    before = p.sig()
                    p.click((l + r) // 2, (t + b) // 2)
                    if p.settle(before, 2.4):
                        break
                else:
                    raise RuntimeError(f"点击「{name}」后页面没有变化")
                g["page"](title or (name if len(names) == 1 else names), package, activity)
                return
            if index == 0:
                p.top(scrolls)
            elif index == scrolls + 1 or not p.scroll_more():
                break
        p.note_miss(" / ".join(names))
        raise RuntimeError(f"没找到入口「{names[0]}」，未继续本段")
    return row


def _plz_switch_signature(p, g):
    def switch_signature():
        return tuple(p.switches())
    return switch_signature


def _plz_switch_top(p, g):
    def switch_top(max_screens):
        """按开关行判顶部，不让访问时间等动态文字延长整页翻动。"""
        before = g["switch_signature"]()
        for _ in range(max_screens):
            p.top(1)
            current = g["switch_signature"]()
            if current == before:
                return
            before = current
        raise RuntimeError("未确认开关列表顶部，未执行关闭")
    return switch_top


def _plz_system_settings(p, g):
    def system_settings():
        g["open_page"]("am start -f 0x10008000 -a android.settings.SETTINGS", "设置",
                       "com.android.settings")
    return system_settings


def _plz_at_assistant(p, g):
    def at_assistant():
        """当前页是不是负一屏首页：先要求前台是桌面，再看头像入口或首页的两条已知文案。

        负一屏内嵌在桌面进程里，焦点窗口不再是它自己的包名（PLR110 实测）；反过来，
        它自己的包名对应的是负一屏设置页，那页不能当成「已经到了」。别的 App 上的同名
        头像 / 文案同样不算，否则这一段会在错的应用里点下去（#901）。"""
        if not p.focus().startswith(g["LAUNCHER"]):
            return False
        root = p.tree()
        if any(n.get("resource-id", "").endswith("head_icon") for n in root.iter("node")):
            return True
        return g["ASSISTANT_HOME"] <= {t for t, _, _ in p.texts(root)}
    return at_assistant


def _plz_assistant_icon(p, g):
    def assistant_icon():
        """回默认桌面、从左侧内侧右滑进负一屏，返回唯一的头像入口。

        ColorOS 最左一条是返回 / 侧边栏手势区，起点从 W//7 起、滑动 250 ms（同族 PLG110 实测）。
        两次 HOME 回默认桌面：多主页时一次可能停在别的页；HOME 也可能正好落在负一屏，那就不再滑，
        再滑一次会把自己划走（#901）。"""
        if g["at_assistant"]():
            p.await_page()                  # 已到也可能是刚划进来的过渡帧：等这一页画完再取坐标
        else:
            reached = False
            for _ in range(2):
                p.d.shell("input keyevent HOME")
                p.await_page()
                reached = g["at_assistant"]()
                if reached:
                    break
            if not reached:
                for _ in range(4):
                    g["require"](p.focus().startswith(g["LAUNCHER"]), "未停在系统桌面，请勿同时操作手机")
                    p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250")
                    p.await_page()
                    if g["at_assistant"]():
                        break
        icons = [n for n in p.tree().iter("node") if n.get("resource-id", "").endswith("head_icon")
                 and p.on_screen(n)]
        if len(icons) != 1:
            p.note_miss(f"唯一的负一屏头像入口（读到 {len(icons)} 个）")
        g["require"](len(icons) == 1, "未确认负一屏头像入口")
        return icons[0]
    return assistant_icon


def _plg_assistant_settings(p, g):
    def assistant_settings():
        """PMA110 录制时负一屏子页没导出：走桌面入口，不尝试绕过权限，也不截图「我的」页。"""
        p.d.shell("input keyevent HOME")
        g["time"].sleep(.8)
        for _ in range(4):
            texts = {text for text, _, _ in p.texts()}
            if {"我的服务", "添加卡片"} <= texts:
                break
            g["require"](p.focus().startswith("com.android.launcher/"), "未停在系统桌面，请勿同时操作手机")
            p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250")
            g["time"].sleep(.8)
        else:
            raise RuntimeError("未进入负一屏，未继续操作")
        g["require"](p.tap("我的", exact=True, scrolls=0), "未找到负一屏「我的」入口")
        g["tap_page"]("设置", g["ASSISTANT"] + "setting.AssistantScreenSettingActivity", scrolls=0)
    return assistant_settings


def _plg_carousel_choices(p, g):
    def carousel_choices(root):
        """只识别有明确 checked 状态的单选控件；预览图的同名文字不能作为点击目标。"""
        parents = {child: node for node in root.iter() for child in node}
        choices = {}
        labels = {"显示轮播推荐", "不显示轮播推荐"}
        for node in root.iter("node"):
            if node.get("checkable") != "true" or "RadioButton" not in node.get("class", ""):
                continue
            row = node
            for _ in range(5):
                captions = {x.get("text", "") for x in row.iter("node")} | {
                    x.get("content-desc", "") for x in row.iter("node")}
                matched = captions & labels
                if len(matched) == 1:
                    name = matched.pop()
                    g["require"](name not in choices, "轮播单选项不唯一，未点击")
                    g["require"](p.on_screen(node) and node.get("enabled") == "true", "轮播单选项不可操作")
                    g["require"](node.get("checked") in ("true", "false"), "轮播单选状态未知，未点击")
                    choices[name] = (node.get("checked") == "true", g["bounds"](node))
                    break
                row = parents.get(row)
                if row is None or len(matched) > 1:
                    break
        g["require"](set(choices) == labels and sum(on for on, _ in choices.values()) == 1,
                     "无法确认轮播单选状态，未使用固定坐标")
        return choices
    return carousel_choices


NAV.update({
    "app_settings": _plz_app_settings,
    "assistant_icon": _plz_assistant_icon,
    "at_assistant": _plz_at_assistant,
    "open_page": _plz_open_page,
    "row": _plz_row,
    "switch_signature": _plz_switch_signature,
    "switch_top": _plz_switch_top,
    "system_settings": _plz_system_settings,
    "assistant_settings": _plg_assistant_settings,
    "carousel_choices": _plg_carousel_choices,
})
