"""机型脚本的公共导航助手（沿用 #1150、#1244）：入口、选择器、等待与落点确认收在这里。

`recipe_kit.preamble()` 写完生命周期与台账之后调用 `install(p, g)`，把公共导航补进同一个
执行作用域；拨动策略另住 `recipe_strategies`，段体另住 `recipe_steps`。三张表都按名字写进
同一个作用域，脚本侧只留调用点。

实现不 import `recipe_kit`：`skip` / `require` 这类前导名字由工厂从 `g` 取、包进闭包，
两个模块因此没有依赖关系（方向只有 `preamble()` → `install()` 这一条）。

同一个名字在一个家族里有几套结构不同的实测走法时，各占一档（如 `gear` 的 icon / checked / text），
由脚本的模块常量选（`_style()`）；缺省一档是多数机型那一套。只有字面量不同的参数化后共用一份。
未迁移的家族仍是老规矩：脚本本地同名定义后执行、覆盖注入版，同名但代码不同的是机型知识。
实现体与被搬走的脚本副本代码逐字相同：守卫把工厂里返回的函数源码与脚本里还留着的本地定义
都折成 AST（剥注释、docstring、折行）后比对，改一边不改另一边即红（tests/test_recipe_nav.py）。
`g["X"]` 现取与随之消失的 `global X` 是搬动本身带来的改写，比对前由守卫折算掉。

闭包对名字一律按 `g` 现取（包括 `g["time"]`）：脚本原来是在自己的全局里解析这些名字，换到
这个模块后仍取当次执行作用域里的那一个，测试装的假时钟才照旧生效。

文件内按家族分节：小米系 / vivo / OPPO（导航与词汇、两大对、策略分派各一节）/ 荣耀 / 魅族 /
其余·跨家族，名字被两个家族占用的那一处（`browser_settings`）另有一节分派，`install()` 落在最后。
荣耀与魅族只有三份与一份脚本（#1246）：这两节只收「注入名已经住在共享库、别家也在用」的实现，
各占一档；只服务一台机的辅助留在脚本里。OPPO 那一族的走法常量最多（`WAIT_PAGE_STYLE` /
`TAP_PAGE_STYLE` / `TAP_STYLE` / `OPEN_SETTINGS_STYLE` / `SEARCH_SETTINGS_STYLE` /
`OPEN_PAGE_STYLE` / `APP_SETTINGS_STYLE` / `SYSTEM_SETTINGS_STYLE` / `SETTINGS_PAGE_STYLE` /
`READ_SWITCHES_STYLE` / `CLOSE_NAMED_STYLE` / `HIDE_CAROUSEL_STYLE`），`read_switches` /
`close_named` 两档也住这一节：一张表一个名字，跨模块分派会把两张注入面绕在一起。
"""

import functools
import re
import time
from collections import namedtuple
from typing import Any

from wait import GiveUp, until

import adb_link
import recipe_strategies as strategies
from entries import reach
from recipe_runtime import SkipStep
from row import bounds

# 数据可调用的公开实现：`tool/catalog/interpreter.py` 按这些名字建分派表。
__all__ = ("ad_id_page", "app_settings", "assert_no_other_window", "assistant_icon", "assistant_settings", "at_assistant", "bottom_tab", "browser_settings", "browser_settings_direct", "browser_settings_vivo", "browser_settings_xiaomi", "browser_start", "by_desc", "by_id", "carousel_choices", "close_named", "direct_settings", "enter", "enter_privacy", "enter_settings", "game_settings_direct", "game_settings_entry", "game_settings_via_mine", "gear", "gear_top", "goto", "has_row", "hiboar_panel", "hiboard_panel", "hide_carousel", "menu_settings", "menu_state", "mine_settings", "more_menu", "my_tab", "navigate", "no_agreement", "off_unnamed", "open_app_settings", "open_page", "open_search_setting", "open_search_settings", "open_search_sub", "open_settings", "open_switch_page", "opened", "page_activity", "popup_row", "read_switches", "result_xy", "row", "search_setting", "search_settings", "search_settings_ready", "security_tab", "settings_home", "settings_icon_visible", "settings_page", "store_privacy", "switch_signature", "switch_top", "system_settings", "tab", "tab_bot", "tap", "tap_any", "tap_bottom_tab", "tap_by_scroll", "tap_low", "tap_page", "tap_row", "tap_tab", "tap_text", "theme_settings", "wait_bottom_tab", "wait_page", "wait_search_settings")

# 「跨家族」分节收进来的注入名：这些实现必须被 ≥2 个家族使用（#1247 的守卫，判据按节算）。
# 家族分节（小米系 / vivo / OPPO / 荣耀 / 魅族）不受这条限制——那是新机型并入的入口，
# 允许单脚本变体。往这里加名字之前先数家族：只有一个家族在用的，放家族分节。
SHARED = frozenset({"tap", "opened", "my_tab", "tap_text", "goto", "browser_settings"})


def __getattr__(name: str) -> Any:
    """注入名在类型层面可见（#1247）：脚本 `if TYPE_CHECKING:` 块里的 import 落到这里。
    运行时这些名字住在执行作用域，模块上没有对应属性，照旧抛 AttributeError。"""
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------- 小米系（xiaomi / redmi，沿用 #1151、#1244）----------
#
# 同一个注入名在家族内有几套结构不同的实测走法时，各占一档、脚本用模块常量选（`_style()`）：
# 走法属于这台机的知识，库不按型号猜。缺省一档是多数机型那一套，常量只在偏离缺省时才写。
# 23113RKC6C / 24122RKC7C / 24129PN74C 那份 `tap_any` 是死代码（定义后没人调），#1244 删掉。

def _style(rt, constant, choices, default):
    """脚本的模块级常量选了哪一档走法：缺省 `default`，认不出当场报错。

    静默回退会点错入口，比报错更难查（沿用 #819 的口径）。常量是脚本自己的页面知识，
    库按它选实现，不按型号猜。
    """
    value = rt.constants.get(constant, default)
    if value not in choices:
        raise RuntimeError(f"脚本常量 {constant} = {value!r} 认不出；可用的：{'、'.join(choices)}")
    return value


def tap_any(p, rt, *names, scrolls=6):
    """依次试几个入口名，点中一个就返回 True。"""
    return any(maybe(p, rt, n, scrolls) for n in names)


def gear(p, rt, toolbar_only=False):
    vivo_styles = {name: functools.partial(fn, p, rt) for name, fn in _VIVO_GEAR_FACTORIES.items()}
    def icon_style(toolbar_only):
        from fast import bounds, icon_hit

        for n in p.tree().iter("node"):
            l, t, r, b = bounds(n)
            icon = "ImageView" in n.get("class", "") and r-l < p.W * 0.25 and b-t < p.H * 0.15
            if icon_hit(n) and (n.get("clickable") == "true" or icon) and p.on_screen(n) and (not toolbar_only or b < p.H * 0.23):
                p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1)
                return True
        if not toolbar_only and p.find("设置", exact=True, edge_ok="tab"):
            return p.tap("设置", exact=True, scrolls=0)
        # 下载管理、天气和日历的齿轮藏在右上「更多」菜单里。
        for n in p.tree().iter("node"):
            key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
            from fast import bounds
            l, t, r, b = bounds(n)
            if any(k in key.lower() for k in ("更多", "more", "menu")) and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22:
                p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(0.5)
                if p.tap("设置", exact=True, scrolls=0):
                    return True
                break
        return False
    def text_style(toolbar_only):
        from fast import bounds, icon_hit

        for n in p.tree().iter("node"):
            l, t, r, b = bounds(n)
            if icon_hit(n) and (n.get("clickable") == "true" or "ImageView" in n.get("class", "")) and p.on_screen(n) and (not toolbar_only or b < p.H * 0.23):
                p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1)
                return True
        # 兜底：正文正好是「设置」两个字的一行（有些 App 是文字入口），只在屏幕上半部分找，
        # 免得点到正文中间的「…设置…」长句。
        for n in p.tree().iter("node"):
            l, t, r, b = bounds(n)
            if (n.get("text") or "").strip() == "设置" and n.get("clickable") == "true" and b < p.H * 0.45 and p.on_screen(n):
                p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(1)
                return True
        # 下载管理、天气的齿轮藏在右上「更多」菜单里。
        for n in p.tree().iter("node"):
            key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
            l, t, r, b = bounds(n)
            if any(k in key.lower() for k in ("更多", "more", "menu")) and n.get("clickable") == "true" and p.on_screen(n) and b < p.H * 0.22:
                p.click((l + r) // 2, (t + b) // 2); rt.clock.sleep(0.5)
                if p.tap("设置", exact=True, scrolls=0):
                    return True
                break
        return False
    """很多小米 App 的设置是右上角齿轮图标，没有文字。
    匹配只认正好是「设置」的描述、正文或 setting 类 id：商店「我的」页有一行正文「去功能设置里
    重新开启」，主题商店有「设置壁纸」，按包含匹配会先命中它们、点进别的子页，整段跑空（沿用 #305 / #374）。
    点完要不要认出设置页按机型：日历的齿轮打开的是 PopupWindow，不校验就会在弹窗里找入口（沿用 #407）。"""
    style = _style(rt, "GEAR_STYLE", ("icon", "checked", "text") + tuple(vivo_styles), "icon")
    if style in vivo_styles:
        return vivo_styles[style]()
    if style == "text":
        return text_style(toolbar_only)
    if style == "icon":
        return icon_style(toolbar_only)
    before = p.focus()
    if not icon_style(toolbar_only):
        return False
    if p.in_settings_page():
        return True
    if p.focus() != before:
        p.back()          # 点开的是弹窗或别的页：关掉，别留给下一段（沿用 #331 / #407）
    return False



def gear_top(p, rt):
    vivo_style = functools.partial(_vivo_gear_top_style, p, rt)
    def text_style():
        """只认右上角那个文字就是「设置」的齿轮。

        应用商店「我的」页有一条「去功能设置里重新开启」，含「设置」二字且可点，通用 gear() 会先命中它，
        点开的是手机清理的功能页——这就是沿用 #193 那组记录里商店四个入口全部找不到的真正原因。
        """
        from fast import bounds
        for n in p.tree().iter("node"):
            t = (n.get("text") or n.get("content-desc") or "").strip()
            if t != "设置" or n.get("clickable") != "true" or not p.on_screen(n):
                continue
            l, top, r, b = bounds(n)
            if b < p.H * 0.25 and (l + r) // 2 > p.W * 0.7:
                p.click((l + r) // 2, (top + b) // 2)
                rt.clock.sleep(1)
                return True
        return False
    style = _style(rt, "GEAR_TOP_STYLE", ("text", "vivo"), "text")
    return {"text": text_style, "vivo": vivo_style}[style]()



def enter(p, rt, name, scrolls=None):
    def require_style(name, scrolls=6):
        rt.require(p.entry(name, scrolls=scrolls), f"未找到「{name}」")
    def honor_style(name, scrolls=4):
        """必需入口：没有就是这一段没跑成，不能报成功。"""
        if not p.entry(name, scrolls=scrolls):
            raise RuntimeError(f"入口「{name}」没找到")
    style = _style(rt, "ENTER_STYLE", ("require", "honor"), "require")
    if style == "honor":
        return honor_style(name, 4 if scrolls is None else scrolls)
    return require_style(name, 6 if scrolls is None else scrolls)



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







# ---------- vivo ----------
#
# `browser_settings` 收的是「不含拉起 App」那一簇：vivo 浏览器没有底部「我的」，入口在右上菜单。
# 含 `p.start` 的另一簇当时按 #1148 定案 3 留脚本，理由是入口速查只扫脚本源码、搬走会漏机型；
# #1153 起 `entries.used_by()` 连脚本调用的注入实现一起扫，这条理由不再成立（#1211 搬走带
# `p.start` 的浏览器段体后「用过的机型」逐条不变）。
# V2547A 有一份代码不同的同名实现，按「同名多簇一律留脚本原样」不搬；V2309A 那份代码与这里
# 相同（当时按文本判成「写法不同」），#1153 起走注入版。

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


_VIVO_GEAR_FACTORIES = {"vivo": _vivo_gear, "vivo_desc": _vivo_gear_desc,
                        "vivo_landing": _vivo_gear_landing}


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


def hiboar_panel(p, rt):
    """回到负一屏的设置面板（V2547A 的路径，名字按脚本原样保留）。

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





# `browser_settings` 这个名字小米系也在用：两个家族的实现由文件末尾的分派器按脚本常量选
# （`_browser_settings()`），这里不注册、免得被后来的那一行静默覆盖。




# ---------- OPPO 家族：导航与词汇（沿用 #1153、#1154、#1245）----------
#
# ColorOS 脚本共用的导航过程。`SEARCH_TITLES` 仍是脚本侧的东西：PLP120 的搜索页标题名单比
# 一加两台长，闭包从执行作用域现取、注入版不替它判断。
#
# 同一个注入名在这个家族里有几套结构不同的实测走法时，各占一档、脚本用模块常量选（`_style()`，
# 与小米系同一份）：`WAIT_PAGE_STYLE` / `TAP_PAGE_STYLE` / `TAP_STYLE` / `OPEN_SETTINGS_STYLE` /
# `SEARCH_SETTINGS_STYLE` / `OPEN_PAGE_STYLE` / `APP_SETTINGS_STYLE` / `SYSTEM_SETTINGS_STYLE` /
# `SETTINGS_PAGE_STYLE` / `HIDE_CAROUSEL_STYLE`；从不传 timeout 的那些页面用 `WAIT_PAGE_TIMEOUT`
# 这一档参数（RMX3700 的等待预算比别家长）。缺省一档保留未声明常量时的旧行为，认不出的值在
# 调用那一刻报错。
#
# `browser_settings` 上文已被 vivo 的菜单版占用，OPPO 这一版是公开 Intent 直达，
# 另起名字 `browser_settings_direct`，三份脚本的调用点跟着改名（沿用 #1153）。PMA110 / PMX110 各自
# 走设置页的方式结构不同，按跨家族分派表的新 flow 注册（`BROWSER_FLOW`，见文件末尾）。
#
# PHK110 / PKX110 / PKH110 的 `off_exact` 与 PLZ110 / PMX110 / PLG110 / PMA110 的 `close_named`
# 在 #1253 搬进了 `recipe_strategies`：词库现在也扫策略库那一张表，那几个「未解析 / keep=」的
# 现场跟着实现走、读数不变。`close_named` / `read_switches` 的注入名两边都占——小米系那两份
# 住在这一节，OPPO 各档紧挨着放同一张表，一张表一个名字，跨模块分派会把两张注入面绕在一起；
# 策略库那几套走法因此各用带后缀的注入名，脚本把注入实现绑回旧名字。

def wait_search_settings(p, rt, tries=30):
    from wait import until

    def sample():
        focus = p.focus()
        if "com.heytap.quicksearchbox" not in focus or "Setting" not in focus:
            return False
        return bool(rt.constants['SEARCH_TITLES'] & {text for text, _, _ in p.texts()})

    return bool(until(sample, tries=tries, same=2,
                      now=rt.clock.monotonic, sleep=rt.clock.sleep))


def settings_page(p, rt, *path):
    def tap_style(*path):
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
        rt.clock.sleep(1.2)
        for t in path:
            if not p.tap(t, exact=True):
                return False
        return True
    def scroll_style(*path):
        """设置并逐级点进 path 里的每一级；长列表靠 `tap_by_scroll` 自己往下翻（RMX3700）。"""
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
        rt.clock.sleep(1.5)
        for text in path:
            if not tap_by_scroll(p, rt, text):
                print(f"  ! 设置里没找到「{text}」")
                return False
            rt.clock.sleep(1.2)
        return True
    style = _style(rt, "SETTINGS_PAGE_STYLE", ("tap", "scroll"), "tap")
    return {"tap": tap_style, "scroll": scroll_style}[style](*path)



def tap_page(p, rt, text, activity, title=None, scrolls=4, exact=True):
    def plain_style(text, activity, title=None, scrolls=4, exact=True):
        return p.tap(text, exact=True) and wait_page(p, rt, activity, title)
    def tuple_style(text, activity, title=None, scrolls=4, exact=True):
        """`text` 可以给一组等价文案，按顺序试；点到第一个就按落点页面判，不退回改写另一支。"""
        names = (text,) if isinstance(text, str) else tuple(text)
        for name in names:
            if p.tap(name, exact=True, quiet=len(names) > 1):
                return wait_page(p, rt, activity, title)
        p.note_miss(" / ".join(names))
        return False
    def raise_style(text, activity, title=None, scrolls=4, exact=True):
        """`text` 可以给一组等价文案，按顺序试，先命中的点进去；认不到时留下现场再抛。

        软件商店的隐私入口随商店 App 版本叫「隐私」或「隐私授权管理」（沿用 #933），单写一支就一定有一段
        0 项。认不到时留下停在哪个页面与结构摘要，与 note_miss 同形。"""
        names = (text,) if isinstance(text, str) else tuple(text)
        for name in names:
            if p.tap(name, exact=exact, scrolls=scrolls, quiet=len(names) > 1):
                wait_page(p, rt, activity, title or name)
                return True
        p.note_miss(" / ".join(names))
        raise RuntimeError(f"未找到入口「{names[0]}」")
    style = _style(rt, "TAP_PAGE_STYLE", ("plain", "tuple", "raise"), "plain")
    return {"plain": plain_style, "tuple": tuple_style,
            "raise": raise_style}[style](text, activity, title, scrolls, exact)



def open_app_settings(p, rt, package, activity, title):
    result = p.d.shell(
        "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package
    ).output
    if "Permission Denial" in result or "SecurityException" in result:
        print("  ! 系统不允许直达设置，跳过，不提升权限")
        return False
    return wait_page(p, rt, activity, title)


def browser_settings_direct(p, rt):
    return open_app_settings(p, rt, "com.heytap.browser",
                                  "com.heytap.browser.settings.component.BrowserPreferencesPage",
                                  "浏览器")


def wait_page(p, rt, activity, title=None, timeout=None):
    meizu_style = functools.partial(_meizu_wait_page, p, rt)
    def bool_style(activity, title, timeout=None):
        """等到活动、页标题以及可点击区域连续稳定，避免横向动画期间的越界坐标。

        `title` 可以给一组等价标题：软件商店的隐私页随商店 App 版本叫「隐私」或「隐私授权管理」（沿用 #933）。
        没传 timeout 时取脚本常量 `WAIT_PAGE_TIMEOUT`（RMX3700 的录制预算比别家长）。"""
        if timeout is None:
            timeout = rt.constants.get("WAIT_PAGE_TIMEOUT", 6)
        titles = (title,) if isinstance(title, str) else tuple(title)
        deadline, previous = rt.clock.monotonic() + timeout, None
        while rt.clock.monotonic() < deadline:
            if p.locked():
                return False
            if not p.focus().endswith(activity):
                rt.clock.sleep(0.2)
                continue
            root = p.tree()
            texts = p.texts(root)
            # 只识别真正的同意按钮，不把设置页里的「隐私政策」链接当作协议弹窗。
            if any(t in ("同意", "同意并继续", "同意并使用", "允许")
                   and "Button" in n.get("class", "") for t, _, n in texts):
                print("  ! 出现协议/权限按钮，本段跳过，不代为同意")
                return False
            if not any(t in titles for t, _, _ in texts):
                rt.clock.sleep(0.2)
                continue
            switches = p.switches(root)
            if any(not (0 < xy[0] < p.W and 0 < xy[1] < p.H) for _, _, xy in switches):
                rt.clock.sleep(0.2)
                continue
            signature = tuple(t for t, _, _ in texts), tuple(switches)
            if signature == previous:
                return True
            previous = signature
            rt.clock.sleep(0.25)
        print(f"  ✗ 未确认目标页面「{'、'.join(titles)}」，不操作开关")
        return False
    def raise_style(activity, title=None, timeout=None):
        """只在实际 Activity、标题及可见文字稳定后继续；不在账号页读开关或截图。"""
        from fast import ScreenLocked

        timeout = 6 if timeout is None else timeout
        end, previous = rt.clock.monotonic() + timeout, None
        while rt.clock.monotonic() < end:
            if p.locked():
                raise ScreenLocked("手机锁屏，请机主解锁")
            if p.focus() == activity:
                root = p.tree()
                texts = p.texts(root)
                consent = {"同意", "同意并继续", "同意并使用", "允许"}
                rt.require(not any(t in consent and "Button" in n.get("class", "")
                                     for t, _, n in texts), "出现协议或权限申请，本段停止，不代为同意")
                signature = tuple((t, xy) for t, xy, _ in texts)
                if (not title or any(t == title for t, _, _ in texts)) and signature == previous:
                    return
                previous = signature
            rt.clock.sleep(.15)
        target = f"「{title}」" if title else ""
        raise RuntimeError(f"未确认页面{target}（当前：{p.focus()}），不操作开关")
    def strict_style(activity, title, timeout=None):
        """与 raise 同形，标题必给、失败句不带当前前台（PMA110 的录制口径）。"""
        from fast import ScreenLocked

        timeout = 6 if timeout is None else timeout
        end, previous = rt.clock.monotonic() + timeout, None
        while rt.clock.monotonic() < end:
            if p.locked():
                raise ScreenLocked("手机锁屏，请机主解锁")
            if p.focus() == activity:
                root = p.tree()
                texts = p.texts(root)
                consent = {"同意", "同意并继续", "同意并使用", "允许"}
                rt.require(not any(t in consent and "Button" in n.get("class", "")
                                     for t, _, n in texts), "出现协议或权限申请，本段停止，不代为同意")
                signature = tuple((t, xy) for t, xy, _ in texts)
                if any(t == title for t, _, _ in texts) and signature == previous:
                    return
                previous = signature
            rt.clock.sleep(.15)
        raise RuntimeError(f"未确认页面「{title}」，不操作开关")
    style = _style(rt, "WAIT_PAGE_STYLE", ("bool", "raise", "strict", "meizu"), "bool")
    if style == "raise":
        return raise_style(activity, title, timeout)
    if style == "strict":
        return strict_style(activity, title, timeout)
    if style == "meizu":
        return meizu_style(activity, title, 8 if timeout is None else timeout)
    return bool_style(activity, title, timeout)



# ---- OPPO 家族：设置页入口与页面骨架（#1245）----

def page_activity(p, rt, activity, title, timeout=6):
    titles = (title,) if isinstance(title, str) else tuple(title)

    def sample():
        if p.locked():
            raise GiveUp()
        if not p.focus().endswith(activity):
            return None
        root = p.tree()
        texts = p.texts(root)
        if any(t in ("同意", "同意并继续", "同意并使用", "允许", "开始使用")
               and "Button" in n.get("class", "") for t, _, n in texts):
            print("  ! 出现协议或权限提示，跳过")
            raise GiveUp()
        switches = p.switches(root)
        if (not any(t in titles for t, _, _ in texts)
                or any(not (0 < xy[0] < p.W and 0 < xy[1] < p.H)
                       for _, _, xy in switches)):
            return None
        return tuple(t for t, _, _ in texts), tuple(switches)

    found = until(sample, timeout=timeout, poll=.2, same=2,
                  now=rt.clock.monotonic, sleep=rt.clock.sleep)
    if not found:
        print(f"  ✗ 未确认页面「{'、'.join(titles)}」，跳过")
    return bool(found)


def navigate(p, rt, label, activity, title):
    """`label` 可以给一组等价入口文案，按顺序试；点到第一个就按落点页面判（沿用 #933）。"""
    labels = (label,) if isinstance(label, str) else tuple(label)
    for name in labels:
        if p.tap(name, exact=True, quiet=len(labels) > 1):
            return page_activity(p, rt, activity, title)
    p.note_miss(" / ".join(labels))
    return False


def open_settings(p, rt, *args, **kwargs):
    def text_style(expect=("服务管理", "隐私")):
        """进「设置」入口，落地页出现 expect 之一才算成功。

        17.22 的主题商店把这一行读作「设置,有1条新通知」：精确匹配「设置」落空，它又带文字，
        右上角图标的兜底只收无文字节点，同样收不到；游戏中心 14.43.3 反过来是纯齿轮图标。
        按「文字精确 → 文字包含 → 右上角图标」三级走，点错页先退回来再换下一级（沿用 #286）。"""
        for exact in (True, False):
            if not p.find("设置", exact=exact):
                continue
            before = p.sig()
            if p.tap("设置", exact=exact, scrolls=0) and any(p.find(w, exact=True) for w in expect):
                return True
            if p.sig() != before:
                p.back()
        return p.tap_icon(list(expect))
    def intent_style(package, activity, title):
        """公开设置 Intent 直达，落点交给同名助手 `page()` 判（脚本把它绑到 page_activity）。"""
        out = p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package)
        if out.exit_code or any(x in out.output for x in ("Error", "Exception", "Permission Denial")):
            return False
        return page_activity(p, rt, activity, title)
    def shell_style(package, activity, title):
        """公开设置 Intent 直达 App 设置页，核对前台 Activity 与页标题。"""
        result = p.d.shell(rt.constants['SETTINGS_INTENT'].format(package))
        rt.require(not result.exit_code and not any(m in result.output for m in rt.constants['SETTINGS_REFUSED']),
                     f"{package}：系统不允许直达设置，未操作（{result.output.strip()[-200:]}）")
        rt.require(p.expect_page(title), f"{package}：设置页未打开；{p.page_evidence()}")
        landed = p.focus()
        rt.require(landed.endswith(activity), f"{package}：没落在设置页（停在 {landed}）；{p.page_evidence()}")
    style = _style(rt, "OPEN_SETTINGS_STYLE", ("text", "intent", "shell", "honor"), "text")
    if style == "intent":
        return intent_style(*args, **kwargs)
    if style == "shell":
        return shell_style(*args, **kwargs)
    if style == "honor" and not args and "expect" not in kwargs:
        kwargs["expect"] = ("个性化服务", "通知")
    return text_style(*args, **kwargs)



def search_settings(p, rt):
    def page_style():
        out = p.d.shell("am start -a android.intent.action.VIEW -d gs://search/setting")
        if out.exit_code or "Error" in out.output:
            return False
        return page_activity(p, rt, "com.heytap.quicksearchbox.ui.activity.SearchSettingActivity", "搜索设置")
    def wait_style():
        """先走 scheme，打不开再退回桌面下滑进搜索页、点底部「设置」的旧入口（沿用 #165）。"""
        p.d.shell(rt.constants['SEARCH_SETTING'])
        if wait_search_settings(p, rt):
            return True
        # ColorOS 16 及更早版本：桌面下滑进搜索页，底部「设置」。别往下拉，会退出。
        p.d.shell("input keyevent HOME"); rt.clock.sleep(0.6)
        p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); rt.clock.sleep(1.5)
        p.d.shell("input keyevent BACK"); rt.clock.sleep(0.4)      # 收键盘
        return p.tap("设置", exact=True) and wait_search_settings(p, rt)
    def swipe_style():
        """先用全局搜索自己的 scheme 落地（同族 PLP120 / PMX110 实测，沿用 #796）；打不开再退回桌面下拉。
        SearchSettingActivity 未导出，按组件名 `am start -n` 会被系统拒绝。"""
        p.d.shell(rt.constants['SEARCH_SETTING'])
        if wait_search_settings(p, rt):
            return True
        p.d.shell("input keyevent HOME"); rt.clock.sleep(0.6)
        # HOME 可能停在速览页（左一屏）：先左滑回主桌面，否则下拉手势被速览吃掉
        p.d.shell(f"input swipe {p.W*6//7} {p.H//2} {p.W//7} {p.H//2} 250"); rt.clock.sleep(1.0)
        p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); rt.clock.sleep(1.5)
        if "quicksearchbox" not in p.focus():
            print("  ✗ 下拉没进全局搜索")
            return False
        # 收键盘要点键盘上的「收起键盘」箭头；按返回会整页退出
        p.tap("收起键盘", exact=True, scrolls=0)
        rt.clock.sleep(0.8)
        # 页面底部出现「设置」按钮；应用建议里也有「设置」图标，点最靠下的那个
        cands = [((l + r) // 2, (tp + b) // 2) for t, (l, tp, r, b), _ in p.texts()
                 if t == "设置" and tp > p.H * 0.8]
        if not cands:
            print("  ✗ 底部没有「设置」")
            p.back()
            return False
        before = p.sig()
        p.click(*cands[-1])
        p.settle(before, 1.5)
        if "SearchSetting" not in p.focus():
            print("  ✗ 没进搜索设置")
            return False
        return True
    def swipe_strict_style():
        """与 swipe 同形，失败句换成抛出（PYB110 的录制口径）。"""
        p.d.shell(rt.constants['SEARCH_SETTING'])
        if wait_search_settings(p, rt):
            return True
        p.d.shell("input keyevent HOME"); rt.clock.sleep(0.6)
        p.d.shell(f"input swipe {p.W*6//7} {p.H//2} {p.W//7} {p.H//2} 250"); rt.clock.sleep(1.0)
        p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); rt.clock.sleep(1.5)
        if "quicksearchbox" not in p.focus():
            raise RuntimeError("下拉没进全局搜索")
        p.tap("收起键盘", exact=True, scrolls=0)
        rt.clock.sleep(0.8)
        cands = [((l + r) // 2, (tp + b) // 2) for t, (l, tp, r, b), _ in p.texts()
                 if t == "设置" and tp > p.H * 0.8]
        if not cands:
            raise RuntimeError("搜索页底部没有「设置」")
        before = p.sig()
        p.click(*cands[-1])
        p.settle(before, 1.5)
        if "SearchSetting" not in p.focus():
            raise RuntimeError("没进搜索设置")
        return True
    style = _style(rt, "SEARCH_SETTINGS_STYLE", ("page", "wait", "swipe", "swipe_strict"), "wait")
    return {"page": page_style, "wait": wait_style, "swipe": swipe_style,
            "swipe_strict": swipe_strict_style}[style]()



def enter_settings(p, rt, *path):
    """设置 → path 逐跳点开，每一跳都要真的换页：点击被弹窗淡出动画吞掉时重试（沿用 #286）。"""
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); rt.clock.sleep(1.2)
    for name in path:
        p.enter(name, scrolls=6)


def enter_privacy(p, rt):
    """商店的隐私入口随商店 App 版本叫「隐私」或「隐私授权管理」，两个 COS16 机型各是一种（沿用 #907）。"""
    for name in ("隐私", "隐私授权管理"):
        try:
            p.enter(name, scrolls=4)
            return
        except RuntimeError as error:
            if not any(mark in str(error) for mark in ("未找到入口", "页面没有变化")):
                raise
    raise RuntimeError(f"没找到商店的隐私入口；{p.page_evidence()}")


def search_settings_ready(p, rt, timeout=6):
    """搜索设置页认得出：前台是 quicksearchbox 的设置 Activity，且页面标题是那几组之一。"""
    from wait import until

    def sample():
        return "Setting" in p.focus() and any(t in rt.constants['SEARCH_TITLES'] for t, _, _ in p.texts())

    return bool(until(sample, timeout=timeout, poll=0.2, same=2,
                      now=rt.clock.monotonic, sleep=rt.clock.sleep))


def open_search_settings(p, rt):
    """ColorOS 17 的下拉搜索设置挂在 quicksearchbox 里；桌面下滑手势在 adb 下不稳定，直接拉 Activity。"""
    p.d.shell("am start -f 0x10008000 -n com.heytap.quicksearchbox/.ui.activity.SearchHomeActivity")
    rt.clock.sleep(2.2)
    p.d.shell("input keyevent BACK")          # 收键盘
    rt.clock.sleep(0.8)
    cands = sorted((tp, l, tp, r, b) for t, (l, tp, r, b), _ in p.texts() if t == "设置")
    if not cands:
        print("  ✗ 搜索页没有「设置」入口")
        return False
    _, l, tp, r, b = cands[-1]                # 底部那个才是搜索设置
    p.click((l + r) // 2, (tp + b) // 2)
    rt.clock.sleep(2)
    return p.focus().endswith("SearchSettingActivity")


def game_settings_direct(p, rt):
    from fast import ScreenLocked
    """ColorOS 17 的游戏中心设置页认 APP_SETTINGS 动作，直达（PMX110，沿用 #650）。
    旧版本不认这个动作时落不到设置页，返回假交给「我的 → 设置」兜底。"""
    result = p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + rt.constants['GAME'])
    if result.exit_code or any(word in result.output for word in
                               ("Error", "Exception", "Permission Denial", "unable to resolve")):
        return False
    try:
        rt.page("游戏中心", rt.constants['GAME'], "SettingActivity")
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError:
        print("  · 直达没落在设置页，转「我的 → 设置」", flush=True)
        return False
    return True


def game_settings_entry(p, rt):
    from fast import ScreenLocked
    """「我的」页的「设置」：旧版是文字行（可能读作「设置,有1条新通知」），新版是右上角没有
    文字的齿轮（沿用 #292）。文字行点进了别的页就退回来改用齿轮，不把落点押在包含匹配上。"""
    where = p.focus()
    try:
        p.enter("设置", scrolls=0)
        rt.page("隐私开关设置", rt.constants['GAME'])
        return
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError:
        if p.focus() != where:
            p.back()
            rt.clock.sleep(0.6)
    if not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("没找到设置入口：文字与右上角图标都试过")


def game_settings_via_mine(p, rt):
    """我的 → 设置；首次进入的「页面升级」弹窗盖住这一页，先关掉。"""
    p.start(rt.constants['GAME'])
    p.enter("我的")
    rt.clock.sleep(1.2)
    # 「页面升级」弹窗里带滚动列表，dismiss() 不点文字按钮，只能点名点（PKT110）。
    if p.find("我知道了", exact=True):
        p.tap("我知道了", exact=True, scrolls=0); rt.clock.sleep(1.2)
    else:
        p.dismiss()
    game_settings_entry(p, rt)


def open_page(p, rt, *args, **kwargs):
    def fields_style(command, title, package, activity=None):
        result = p.d.shell(command)
        rt.require(not result.exit_code and not any(word in result.output for word in
                      ("Error", "Exception", "Permission Denial", "unable to resolve")),
                     "系统未允许打开设置页")
        rt.page(title, package, activity)
    def shell_style(command, activity, title=None):
        result = p.d.shell(command)
        rt.require(not result.exit_code and not re.search(
            r"Error|Exception|Permission Denial|unable to resolve", result.output, re.I),
            f"系统未允许打开「{title or activity}」，未继续操作")
        wait_page(p, rt, activity, title)
    style = _style(rt, "OPEN_PAGE_STYLE", ("fields", "shell"), "fields")
    return shell_style(*args, **kwargs) if style == "shell" else fields_style(*args, **kwargs)



def app_settings(p, rt, *args, **kwargs):
    def direct_style(package):
        open_page(p, rt, "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package,
                       "返回" if package == rt.constants['THEME'] else "软件商店", package, "SettingActivity")
    def launch_style(package, activity):
        if p.focus() == f"{package}/{activity}":
            return
        p.start(package, activity=rt.constants['START_ACTIVITIES'].get(package))
        rt.require(p.go("我的", "设置"), "未进入包含设置按钮的「我的」页")
        # 旧版应用切换到「我的」后，首下设置点击可能被动画吞掉；按实际前台回读。
        for _ in range(3):
            rt.require(p.focus().split("/", 1)[0] == package, "应用已离开前台，停止本段")
            if p.focus() == f"{package}/{activity}":
                return
            tap(p, rt, "设置", scrolls=0)
            rt.clock.sleep(.4)
        rt.require(p.focus() == f"{package}/{activity}", "设置页未打开，停止本段")
    def shell_style(package, activity, title=None):
        open_page(p, rt, "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + package,
                       activity, title)
    style = _style(rt, "APP_SETTINGS_STYLE", ("direct", "launch", "shell", "honor"), "direct")
    if style == "launch":
        return launch_style(*args, **kwargs)
    if style == "shell":
        return shell_style(*args, **kwargs)
    if style == "honor":
        return _honor_app_settings(p, rt, *args, **kwargs)
    return direct_style(*args, **kwargs)



def system_settings(p, rt):
    def fields_style():
        open_page(p, rt, "am start -f 0x10008000 -a android.settings.SETTINGS", "设置",
                       "com.android.settings")
    def shell_style():
        open_page(p, rt, "am start -f 0x10008000 -a android.settings.SETTINGS", rt.constants['SETTINGS'], "设置")
    style = _style(rt, "SYSTEM_SETTINGS_STYLE", ("fields", "shell"), "fields")
    return {"fields": fields_style, "shell": shell_style}[style]()



def open_switch_page(p, rt, name, titles, package):
    """点开入口 → 确认落在目标页 → 读出开关；任一步不通就退回原页并返回空，把兜底留给调用方。
    `p.enter` 只认「页面变了」，点进别的页也算换页，所以落点必须再校验一次（沿用 #286）。
    断线、锁屏与按约定跳过照常上抛，交给段包装收场。"""
    from fast import ScreenLocked
    where = p.focus()
    try:
        p.enter(name, scrolls=8)
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError as error:
        print(f"  · 入口「{name}」没进去：{error}", flush=True)
        p.note_miss(name)
        return None
    try:
        return strategies.read_on_page(p, rt, titles, package)
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError as error:
        print(f"  · 落点不对：{error}", flush=True)
        if p.focus() != where:
            p.back()
            rt.clock.sleep(0.6)
        return None


def more_menu(p, rt):
    rt.require(p.tap("更多选项", exact=True, scrolls=0) or p.tap("更多", exact=True, scrolls=0),
                 "未找到更多选项")


def menu_state(p, rt):
    """打开右上「更多选项」，读「全部关闭」与「显示系统应用」两项的状态，菜单保持打开。
    列表里没有开着的应用时，系统把「全部关闭」置灰（读屏描述「全部关闭 - 已停用」）。"""
    more_menu(p, rt)
    p.await_page()
    items = p.texts()                 # 一次快照：三次 dump 之间列表可能已经变化
    rt.require(any(_labelled(t, "全部关闭") for t, _, _ in items), "菜单里没有「全部关闭」")
    disabled = any(_labelled(t, "全部关闭") and "已停用" in t for t, _, _ in items) or any(
        t == "全部关闭" and n.get("enabled") == "false" for t, _, n in items)
    # 显示系统应用后，这一项换成「隐藏系统应用」（PMX110 实测）
    system_shown = any(t.startswith("隐藏系统应用") or (t.startswith("显示系统应用") and "已选中" in t
                                                       and "未选中" not in t) for t, _, _ in items)
    return rt.constants['MenuState'](disabled, system_shown)


def ad_id_page(p, rt):
    """到「设备标识与广告」页：先用设置搜索（ColorOS 能直接打开搜索页，沿用 #650，实测 4 秒），
    搜不到再从设置首页一层层找。"""
    if not p.setting("广告跟踪", "限制广告跟踪", path="隐私与安全 > 隐私 > 设备标识与广告"):
        system_settings(p, rt)
        row(p, rt, "隐私与安全", package="com.oplus.securitypermission")
        row(p, rt, "设备标识与广告")
        return
    rt.page("设备标识与广告")


def tap_by_scroll(p, rt, text, max_scrolls=12):
    """在长列表里自己往下翻着找并点击。

    p.tap 内部会先回到页顶；小布建议页（小布建议 Activity）回顶时会判定「离开了当前页」并抛错，
    所以那一类页面必须用这个手动翻找的写法。`text` 可以给一组等价文案，按顺序试（沿用 #933）。
    """
    names = (text,) if isinstance(text, str) else tuple(text)
    for _ in range(max_scrolls):
        for name in names:
            if p.find(name, exact=True):
                return p.tap(name, exact=True, scrolls=0)
        if not p.scroll_more():
            break
    return False


def open_search_setting(p, rt):
    """打开全局搜索的设置首页。包被挂起时拉起的是系统「应用已被暂停」页，要区分出来。"""
    p.d.shell(rt.constants['SEARCH_SETTING'])
    rt.clock.sleep(1.8)
    if "SuspendedAppActivity" in p.focus():
        print("  ! com.heytap.quicksearchbox 被挂起了，全局搜索整个不可用；"
              "先 run.py unsuspend com.heytap.quicksearchbox 再跑本段")
        return False
    return wait_page(p, rt, "com.heytap.quicksearchbox.ui.activity.SearchSettingActivity", "搜索设置")


def open_search_sub(p, rt, name, activity):
    """从搜索设置首页进一个子页。每页都重新打开首页，不靠 back 一层层退。"""
    if not open_search_setting(p, rt):
        return False
    if not tap_by_scroll(p, rt, name):
        print(f"  ! 没找到「{name}」")
        return False
    if not wait_page(p, rt, activity, name):
        print(f"  ! 没到「{name}」页")
        return False
    return True


def read_switches(p, rt, *args, **kwargs):
    plain_style = functools.partial(_xiaomi_read_switches, p, rt)
    vivo_style = functools.partial(_vivo_read_switches_style, p, rt)
    def title_style(title, max_screens=12):
        from fast import ScreenLocked

        rt.page(title)
        where = p.focus()
        switch_top(p, rt, max_screens)
        states = {}
        previous = None
        for index in range(max_screens):
            rt.require(p.focus() == where, "读取时离开目标页，停止本段")
            if p.locked():
                raise ScreenLocked("读取时手机锁屏")
            signature = switch_signature(p, rt)
            if signature == previous:
                return states
            for name, on, _ in signature:
                if name:
                    rt.require(name not in states or states[name] == on,
                                 "同名开关状态不一致，无法可靠核对，未继续操作")
                    states[name] = on
            if max_screens > 20 and (index + 1) % 20 == 0:
                print(f"  · {title}：已读取 {len(states)} 个具名项，继续核对列表", flush=True)
            previous = signature
            # scroll_more 的返回值包含全页动态文字，只借其滚动及焦点保护，下一轮按开关行判进展。
            p.scroll_more()
        if switch_signature(p, rt) == previous:
            return states
        raise RuntimeError("列表超过读取上限，未执行关闭")
    def first_style(max_screens, first=None):
        """读这一页的开关。first 是刚读到的第一屏，复用它，不多读一遍。"""
        current = {}
        items = first if first is not None else p.switches()
        current.update({title: on for title, on, _ in items})
        for _ in range(max_screens - 1):
            if not p.scroll_more():
                break
            current.update({title: on for title, on, _ in p.switches()})
        return current
    def expect_style(activity, title=None, max_screens=8, expect=None):
        """完整读取有界列表；未读完不改，空标题不作为可操作目标。

        `expect` 给定时读到目标就提前收手，没读到算「列表超过读取上限」（PLG110 的录制口径）。"""
        wait_page(p, rt, activity, title)
        p.top(max_screens)
        states = {}
        for _ in range(max_screens):
            rt.require(p.focus() == activity, "读取时离开目标页面，停止本段")
            states.update({name: on for name, on, _ in p.switches() if name})
            if expect and all(name in states for name in expect):
                return states
            if not p.scroll_more():
                return states
        if expect and all(name in states for name in expect):
            return states
        raise RuntimeError("列表超过读取上限，未执行关闭")
    style = _style(rt, "READ_SWITCHES_STYLE", ("plain", "title", "first", "expect", "vivo"), "plain")
    return {"plain": plain_style, "title": title_style, "first": first_style,
            "expect": expect_style, "vivo": vivo_style}[style](*args, **kwargs)



def close_named(p, rt, *args, **kwargs):
    plain_style = functools.partial(_xiaomi_close_named, p, rt)
    meizu_style = functools.partial(_meizu_close_named, p, rt)
    def basic_style(names, page, max_screens=1):
        # 回读确认数由引擎经 rt 记录
        p.top(max_screens)
        before = read_switches(p, rt, max_screens)
        rt.require_switches(before, names, page)
        p.top(max_screens)
        p.off(only=names, page=page, max_screens=max_screens)
        p.top(max_screens)
        current = read_switches(p, rt, max_screens)
        rt.require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
        rt.require(all(current.get(name) == state for name, state in before.items() if name not in names),
                     f"{page}：其他开关状态变化，请核对")
        rt.confirm(len(names))
    def vanish_style(names, page, max_screens=1, snapshot=None):
        """关掉点名的开关，并核对其他开关未变。`snapshot` 是调用方已经读过的那一页，免得再翻一遍。"""
        # 回读确认数由引擎经 rt 记录
        if snapshot is None:
            p.top(max_screens)
            snapshot = read_switches(p, rt, max_screens)
        rt.require_switches(snapshot, names, page)
        others = set(snapshot) - set(names)
        where = p.focus()
        p.top(max_screens)
        p.off(only=names, page=page, max_screens=max_screens)
        p.top(max_screens)
        after = read_switches(p, rt, max_screens)
        for name in names:
            if after.get(name) is False:
                continue
            # 关掉后整行从列表里消失也算已关（引擎回读的 VANISHED）：同页还有别的行、且没换页才算；
            # 整页读空或换成新页时读屏失败，不能当成关闭成功。
            rt.require(after.get(name) is None and others & set(after) and p.focus() == where,
                         f"{page}：回读未确认关闭「{name}」")
        rt.require(all(after.get(name) == state for name, state in snapshot.items() if name in others),
                     f"{page}：其他开关状态变化，请核对")
        rt.confirm(len(names))
    def reopen_style(names, page, max_screens=1, reopen=None, gone=()):
        """关掉点名的开关并回读确认；其他开关的状态不能变。
        reopen：有的页点完开关会弹确认框、确认后退回上一级，回读前用这个回调重新进一次。
        gone：父开关一关就会从页面上消失的那几行，回读时不再要求它们还在。"""
        # 回读确认数由引擎经 rt 记录
        p.top(max_screens)
        first = strategies.wait_switches(p, rt)
        rt.require(first, f"{page}：页面里没读到开关，未操作")
        before = read_switches(p, rt, max_screens, first=first)
        rt.require_switches(before, names, page)
        p.top(max_screens)
        p.off(only=names, page=page, max_screens=max_screens)
        if reopen:
            reopen()
        p.top(max_screens)
        current = read_switches(p, rt, max_screens)
        rt.require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
        rt.require(all(current.get(name) == state for name, state in before.items()
                    if name not in names and name not in gone),
                     f"{page}：其他开关状态变化，请核对")
        rt.confirm(len(names))
    style = _style(rt, "CLOSE_NAMED_STYLE", ("plain", "basic", "vanish", "reopen", "meizu"), "plain")
    return {"plain": plain_style, "basic": basic_style, "vanish": vanish_style,
            "reopen": reopen_style, "meizu": meizu_style}[style](*args, **kwargs)



def has_row(p, rt, name, screens=4):
    """这一页（含下面几屏）有没有这行：只找不点。

    存在性探测不能用 `maybe()` / `p.entry`：它们找到就真的点一下，点在开关行上等于把开关拨了。
    """
    for _ in range(screens):
        if p.find(name, exact=True):
            return True
        if not p.scroll_more():
            return False
    return False


def store_privacy(p, rt):
    """走进商店的隐私页：有的版本设置首页直接有「隐私」，有的挂在「账号与隐私」下面。"""
    if p.tap("隐私", exact=True):
        return True
    if not p.tap("账号与隐私", exact=True):
        return False
    for name in ("隐私", "隐私授权管理"):
        if p.tap(name, exact=True):
            return True
    return False












# ---------- OPPO 两大对：PLZ110 / PMX110 与 PLG110 / PMA110（#1154）----------
#
# 一对里代码逐字相同的导航过程收在这里，两份脚本各删本地定义、调用点一字不改。
# `app_settings` / `system_settings` / `open_page` 的同族差别按模块常量分派，实现在上面那一节
# （`APP_SETTINGS_STYLE` / `SYSTEM_SETTINGS_STYLE` / `OPEN_PAGE_STYLE`），这里不再各留一份。
#
# `close_named` 不在这一簇：注入面的这个名字已被小米系（#1151）占用，PLZ110 / PMX110 那份带
# `snapshot` / `optional`、代码不同，按「同名多簇一律留脚本原样」继续留在两份脚本里（也是词库
# 「未解析」的现场）。`hide_carousel` 这一簇是 PLG110 / PMA110 的单选读法；PLZ110 / PMX110 那份
# 在单个函数体内自带 `choices()`，另占一档（`HIDE_CAROUSEL_STYLE` 的 labels）。
#
# `assistant_settings` 与 `at_assistant` / `assistant_icon` 的常量与下一步由脚本侧给出：
# 两份脚本各有一份同名的本地 `tap_page`（#1245 起走 `TAP_PAGE_STYLE` 的 raise 档）。`row` 与
# `carousel_choices` 的 `bounds` 同样按执行作用域取，两份 PLG/PMA 脚本的 `from fast import …`
# 因此要留着（`bounds` 唯一的读者是注入版）。

def row(p, rt, text, title=None, package=None, activity=None, scrolls=8, tries=1):
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
            rt.require(len(matches) <= 1, f"「{name}」入口不唯一，未点击")
            if not matches:
                continue
            node = matches[0]
            target = node
            while target is not None and target.get("clickable") != "true":
                target = parents.get(target)
            target = target if target is not None else node
            l, t, r, b = bounds(target)
            rt.require(r > l and b > t and p.on_screen(target), "入口坐标无效")
            rt.require(p.focus() == where, "找入口期间页面变了，未点击")
            for _ in range(tries):
                before = p.sig()
                p.click((l + r) // 2, (t + b) // 2)
                if p.settle(before, 2.4):
                    break
            else:
                raise RuntimeError(f"点击「{name}」后页面没有变化")
            rt.page(title or (name if len(names) == 1 else names), package, activity)
            return
        if index == 0:
            p.top(scrolls)
        elif index == scrolls + 1 or not p.scroll_more():
            break
    p.note_miss(" / ".join(names))
    raise RuntimeError(f"没找到入口「{names[0]}」，未继续本段")


def switch_signature(p, rt):
    return tuple(p.switches())


def switch_top(p, rt, max_screens):
    """按开关行判顶部，不让访问时间等动态文字延长整页翻动。"""
    before = switch_signature(p, rt)
    for _ in range(max_screens):
        p.top(1)
        current = switch_signature(p, rt)
        if current == before:
            return
        before = current
    raise RuntimeError("未确认开关列表顶部，未执行关闭")


def _plz_system_settings(p, rt):
    open_page(p, rt, "am start -f 0x10008000 -a android.settings.SETTINGS", "设置",
                   "com.android.settings")


def at_assistant(p, rt):
    """当前页是不是负一屏首页：先要求前台是桌面，再看头像入口或首页的两条已知文案。

    负一屏内嵌在桌面进程里，焦点窗口不再是它自己的包名（PLR110 实测）；反过来，
    它自己的包名对应的是负一屏设置页，那页不能当成「已经到了」。别的 App 上的同名
    头像 / 文案同样不算，否则这一段会在错的应用里点下去（#901）。"""
    if not p.focus().startswith(rt.constants['LAUNCHER']):
        return False
    root = p.tree()
    if any(n.get("resource-id", "").endswith("head_icon") for n in root.iter("node")):
        return True
    return rt.constants['ASSISTANT_HOME'] <= {t for t, _, _ in p.texts(root)}


def assistant_icon(p, rt):
    """回默认桌面、从左侧内侧右滑进负一屏，返回唯一的头像入口。

    ColorOS 最左一条是返回 / 侧边栏手势区，起点从 W//7 起、滑动 250 ms（同族 PLG110 实测）。
    两次 HOME 回默认桌面：多主页时一次可能停在别的页；HOME 也可能正好落在负一屏，那就不再滑，
    再滑一次会把自己划走（#901）。"""
    if at_assistant(p, rt):
        p.await_page()                  # 已到也可能是刚划进来的过渡帧：等这一页画完再取坐标
    else:
        reached = False
        for _ in range(2):
            p.d.shell("input keyevent HOME")
            p.await_page()
            reached = at_assistant(p, rt)
            if reached:
                break
        if not reached:
            for _ in range(4):
                rt.require(p.focus().startswith(rt.constants['LAUNCHER']), "未停在系统桌面，请勿同时操作手机")
                p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250")
                p.await_page()
                if at_assistant(p, rt):
                    break
    icons = [n for n in p.tree().iter("node") if n.get("resource-id", "").endswith("head_icon")
             and p.on_screen(n)]
    if len(icons) != 1:
        p.note_miss(f"唯一的负一屏头像入口（读到 {len(icons)} 个）")
    rt.require(len(icons) == 1, "未确认负一屏头像入口")
    return icons[0]


def assistant_settings(p, rt):
    """PMA110 录制时负一屏子页没导出：走桌面入口，不尝试绕过权限，也不截图「我的」页。"""
    p.d.shell("input keyevent HOME")
    rt.clock.sleep(.8)
    for _ in range(4):
        texts = {text for text, _, _ in p.texts()}
        if {"我的服务", "添加卡片"} <= texts:
            break
        rt.require(p.focus().startswith("com.android.launcher/"), "未停在系统桌面，请勿同时操作手机")
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250")
        rt.clock.sleep(.8)
    else:
        raise RuntimeError("未进入负一屏，未继续操作")
    rt.require(p.tap("我的", exact=True, scrolls=0), "未找到负一屏「我的」入口")
    tap_page(p, rt, "设置", rt.constants['ASSISTANT'] + "setting.AssistantScreenSettingActivity", scrolls=0)


def hide_carousel(p, rt):
    def plg_style():
        activity = rt.constants['ASSISTANT'] + "setting.recommendservice.RecommendServiceSettingActivity"
        wait_page(p, rt, activity, "推荐服务")
        before = read_switches(p, rt, activity, "推荐服务", max_screens=1)
        rt.require("推荐服务" in before, "未读到推荐服务总开关，未操作")
        choices = carousel_choices(p, rt, p.tree())
        if not choices["不显示轮播推荐"][0]:
            l, t, r, b = choices["不显示轮播推荐"][1]
            rt.require(p.focus() == activity, "点击前页面变化，未操作")
            p.click((l + r) // 2, (t + b) // 2)
            rt.clock.sleep(.4)
            current = carousel_choices(p, rt, p.tree())
            rt.require(current["不显示轮播推荐"][0], "轮播推荐回读未确认不显示")
            p.changed.append(("负一屏·推荐服务", "轮播推荐：不显示"))
        rt.require(read_switches(p, rt, activity, "推荐服务", 1) == before, "推荐服务总开关变化，请核对")
        rt.confirm(1)
        print("  · 轮播推荐：已确认不显示，推荐服务总开关保持原值", flush=True)
    def labels_style():
        """只认单选控件自己的标签；不合并祖先子树的文字，也不点预览图里的同名文字（沿用 #280 的做法）。"""
        before = read_switches(p, rt, "推荐服务")
        rt.require("推荐服务" in before, "未读到推荐服务总开关")

        def choices():
            root = p.tree()
            parents = {child: node for node in root.iter() for child in node}
            found = {}
            for node in root.iter("node"):
                if node.get("checkable") != "true" or "RadioButton" not in node.get("class", ""):
                    continue
                container = node
                for _ in range(5):
                    labels = ({x.get("text", "") for x in container.iter("node")} |
                              {x.get("content-desc", "") for x in container.iter("node")}) & rt.constants['CAROUSEL_LABELS']
                    if len(labels) == 1:
                        label = labels.pop()
                        rt.require(label not in found and p.on_screen(node) and node.get("enabled") == "true",
                                     "轮播单选项不唯一或不可操作")
                        rt.require(node.get("checked") in ("true", "false"), "轮播单选状态未知，未点击")
                        found[label] = (node.get("checked") == "true", bounds(node))
                        break
                    container = parents.get(container)
                    if container is None or len(labels) > 1:
                        break
            rt.require(set(found) == rt.constants['CAROUSEL_LABELS'] and
                         sum(on for on, _ in found.values()) == 1, "无法确认轮播单选状态")
            return found

        where = p.focus()
        selected, (l, t, r, b) = choices()[rt.constants['CAROUSEL_OFF']]
        if not selected:
            rt.require(p.focus() == where, "读取后轮播页面变化，未点击")
            p.click((l + r) // 2, (t + b) // 2)
            p.await_page()
            rt.require(choices()[rt.constants['CAROUSEL_OFF']][0], "轮播推荐回读未选中不显示")
            p.changed.append(("推荐服务", "轮播推荐：不显示"))
        rt.require(read_switches(p, rt, "推荐服务") == before, "推荐服务总开关发生变化")
        rt.confirm(1)
    style = _style(rt, "HIDE_CAROUSEL_STYLE", ("plg", "labels"), "plg")
    return {"plg": plg_style, "labels": labels_style}[style]()



def carousel_choices(p, rt, root):
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
                rt.require(name not in choices, "轮播单选项不唯一，未点击")
                rt.require(p.on_screen(node) and node.get("enabled") == "true", "轮播单选项不可操作")
                rt.require(node.get("checked") in ("true", "false"), "轮播单选状态未知，未点击")
                choices[name] = (node.get("checked") == "true", bounds(node))
                break
            row = parents.get(row)
            if row is None or len(matched) > 1:
                break
    rt.require(set(choices) == labels and sum(on for on, _ in choices.values()) == 1,
                 "无法确认轮播单选状态，未使用固定坐标")
    return choices





# ---------- 荣耀（#1246）----------
#
# 这家只有三份脚本，家族分节只收「注入名已经住在共享库、别家也在用」的那几档：`app_settings`
# 与 `browser_settings`（PNM-AN10 / WKL-AN20 都走这个注入名）的荣耀走法写在下面，`enter` /
# `tap` / `open_settings` 的荣耀档在各自主分派里（`ENTER_STYLE` / `TAP_STYLE` /
# `OPEN_SETTINGS_STYLE`），`my_tab` 在跨家族分节（`MY_TAB_STYLE`）。只在这一家出现、代码也只
# 服务这一台机的辅助（`settle_page` / `radio` / `labels` / `dismiss` 等）留在脚本里。
#
# 走法各按脚本常量选：`ENTER_STYLE` / `TAP_STYLE` / `APP_SETTINGS_STYLE` / `OPEN_SETTINGS_STYLE` /
# `BROWSER_FLOW` / `MY_TAB_STYLE`，缺省档都是别的家族原有的走法，不声明常量时行为不变。

def _honor_my_tab(p, rt, app):
    """底栏可能被晚到的弹窗盖住（阅读开屏广告之后才弹「发现新版本」）：关掉再找。

    协议框不关，只跳过（CLE-AN00）。"""
    for _ in range(4):
        no_agreement(p, rt, app)
        if p.find("我的", edge_ok="tab"):
            break
        p.dismiss()
        rt.clock.sleep(1.5)
    if not p.tab("我的"):
        raise RuntimeError(f"{app}底部「我的」没找到")
    rt.clock.sleep(1)


def _honor_browser_settings_mounted(p, rt):
    if "package:" not in p.d.shell("pm path com.honor.browser").output:
        return strategies.baidu_browser(p, rt)
    p.start("com.honor.browser")
    p.dismiss()
    if p.find("我的", exact=True):                       # 经典首页：我的 → 右上第三个图标
        p.tap("我的", exact=True, scrolls=0)
        p.d(resourceId="com.honor.browser:id/top_local_icon")[2].click()
        rt.clock.sleep(1)
    else:                                                # 简洁首页：更多 → 设置
        p.tap("更多", exact=True, scrolls=0)
        p.tap("设置", exact=True, scrolls=0)


def _honor_browser_settings_plain(p, rt):
    package = "com.honor.browser"
    if p.focus().split("/", 1)[0] == package and {"模式选择", "隐私管理"} <= labels(p):
        return package
    p.start(package)
    # 本机已验证「更多 → 设置」；经典首页的未知图标位置不猜。
    tap(p, rt, "更多", scrolls=0)
    tap(p, rt, "设置", scrolls=0)
    settle_page(p, rt, package, "模式选择", "隐私管理")
    return package


def _honor_app_settings(p, rt, package, *markers):
    p.start(package)
    rt.require(p.go("我的", "设置"), "未找到应用设置入口")
    tap(p, rt, "设置", scrolls=0)
    settle_page(p, rt, package, *markers)


# ---------- 魅族（#1246）----------
#
# 只有一份脚本，家族分节不成立：只收注入名已经住在共享库、别家也在用的那几个
# （`wait_page` / `tap_text` / `goto` / `close_named`），各占一档。其余本机助手
# （`page_summary` / `tap_id` / `open_app` / `assert_no_other_window`）
# 服务的是这台机的页面与 `TARGET_PACKAGE` 约定，留在脚本里；`safe_switches` 在 #1253 搬进了
# `recipe_strategies`，它按 `g["assert_no_other_window"]` 取这里留下的那个助手。

def _meizu_wait_page(p, rt, activity, title, timeout=8):
    """等页面认得出，顺手记下目标包名给同脚本的其它助手用（Flyme 的 `TARGET_PACKAGE` 约定）。

    `TARGET_PACKAGE` 是脚本的模块常量，所以写回执行作用域，脚本里按裸名字读的助手照旧看得到。"""
    deadline = rt.clock.monotonic() + timeout
    while rt.clock.monotonic() < deadline:
        rt.require(not p.locked(), "手机锁屏，请机主解锁")
        if p.focus() == activity:
            texts = p.texts(p.tree())
            rt.require(not any(t in ("同意", "同意并继续", "同意并使用", "允许")
                                 and "Button" in (n.get("class") or "") for t, _, n in texts),
                         "出现协议或权限申请，未同意，停止本段")
            if any(t == title and n.get("package") == activity.split("/", 1)[0] for t, _, n in texts):
                rt.target = activity.split("/", 1)[0]
                return
        rt.clock.sleep(.2)
    raise RuntimeError(f"未确认目标页「{title}」：{activity}")


def _meizu_tap_text(p, rt, text, scrolls=0):
    """只点击可见的准确文字；找不到时只滚动当前页面，不自动处理弹窗。"""
    initial = p.focus()
    for index in range(scrolls + 1):
        rt.require(not p.locked(), "手机锁屏，请机主解锁")
        rt.require(p.focus() == initial, "页面已变化，停止点击")
        root = p.tree()
        assert_no_other_window(p, rt, root, rt.target)
        hits = [(b, n) for t, b, n in p.texts(root)
                if t == text and n.get("package") == rt.target]
        # 同一按钮可同时有容器和子文字；不同区域的同名项不猜。
        centers = {((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for b, _ in hits}
        if centers:
            if len(centers) > 1:
                # 父子节点的中心可有微小偏移，但不能指向不同位置。
                xs, ys = zip(*centers, strict=True)     # centers 都是 (x, y) 两元组
                rt.require(max(xs) - min(xs) < p.W * .15 and max(ys) - min(ys) < p.H * .08,
                             f"「{text}」有多个位置，未点击")
            x, y = min(centers, key=lambda xy: xy[1])
            rt.require(0 <= x < p.W and 0 <= y < p.H, "坐标不在屏幕内")
            # 底部可能被系统导航区域覆盖，即使文字节点中心仍在屏幕内。
            if y >= p.H * .95:
                if index < scrolls and p.scroll_more():
                    continue
                raise RuntimeError(f"「{text}」位于屏幕底部导航区域附近，未点击")
            p.click(x, y)
            rt.clock.sleep(.7)
            return
        if index == scrolls or not p.scroll_more():
            break
    raise RuntimeError(f"未找到「{text}」")


def _meizu_goto(p, rt, text, activity, title, scrolls=0):
    tap_text(p, rt, text, scrolls)
    wait_page(p, rt, activity, title)


def _meizu_close_named(p, rt, names, page, activity):
    """精确标题、逐项点击、识别关闭确认框并回读；有变化或不确定立即停止。"""
    rt.require(p.focus() == activity, f"{page}：页面不符")
    before_list = strategies.safe_switches(p, rt, activity)
    rt.require(all(sum(1 for t, _, _ in before_list if t == name) == 1 for name in names),
                 f"{page}：目标开关未全部唯一识别，未操作")
    baseline = {t: on for t, on, _ in before_list}
    print(f"  准备关闭 {page}：{'、'.join(names)}；已关闭的保持不变", flush=True)
    for name in names:
        rt.require(not p.locked(), "手机锁屏，请机主解锁")
        rt.require(p.focus() == activity, "页面已变化，停止本段")
        switches = [(on, xy) for t, on, xy in strategies.safe_switches(p, rt, activity) if t == name]
        rt.require(len(switches) == 1, f"{name}：开关不唯一")
        on, (x, y) = switches[0]
        if not on:
            print(f"  · {name} 已关闭", flush=True)
            continue
        rt.require(not any(n.get("checkable") == "true" and n.get("enabled") == "false"
                             and p.on_screen(n) and (lambda b: b[0] <= x <= b[2] and b[1] <= y <= b[3])
                             (__import__("fast").bounds(n)) for n in p.tree().iter("node")),
                     f"{name}：开关不可操作")
        p.click(x, y)
        rt.clock.sleep(.8)
        rt.require(not p.locked(), "手机锁屏，请机主解锁")
        rt.require(p.focus() == activity, "点击后页面变化，停止本段")
        root = p.tree()
        assert_no_other_window(p, rt, root, activity.split("/", 1)[0])
        texts = p.texts(root)
        titles = [t for t, _, _ in texts if "确定关闭" in t and name in t]
        confirmations = [(b, n) for t, b, n in texts if t == "确定" and "Button" in (n.get("class") or "")]
        if titles:
            rt.require(len(confirmations) == 1, f"{name}：关闭确认框无法识别")
            b, _ = confirmations[0]
            rt.require(0 <= (b[0] + b[2]) // 2 < p.W and 0 <= (b[1] + b[3]) // 2 < p.H,
                         "确认按钮不在屏幕内，停止")
            p.click((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
            rt.clock.sleep(.8)
        else:
            rt.require(not confirmations, "出现无法识别的确认框，停止")
        rt.require(p.focus() == activity, "确认后页面变化，停止")
        after_list = strategies.safe_switches(p, rt, activity)
        after = {t: on for t, on, _ in after_list}
        rt.require(sum(1 for t, _, _ in after_list if t == name) == 1 and after.get(name) is False,
                     f"{name}：回读未确认关闭")
        rt.require(all(after.get(t) == state for t, state in baseline.items() if t not in names),
                     f"{page}：其他开关状态变化，请手动核对")
        p.changed.append((page, name))
        print(f"  关 {name}（已回读）", flush=True)


# ---------- 跨家族 ----------
#
# `tap`：按名字点入口、找不到就 `require` 报错。一加 PJA110 与 vivo V2417A 各一份逐字相同。
# OPPO PKT110 那份带 `exact=`、失败句里多一句当前页文字，按 `TAP_STYLE` 另占一档（#1245）；
# honor-WKL-AN20 的 `scrolls=6` 签名仍不同，留本地覆盖。
#
# `opened`：试一条直达页面、不通就走菜单。vivo V2547DA 的 Android 17 变体与小米 M154FF /
# M332BF 三份逐字相同，意图也一致，所以共用一个注入名。脚本侧的 `import adb_link` 要留着：
# 闭包从执行作用域取它，删掉这行 import 就是 AttributeError。

def tap(p, rt, name, scrolls=None):
    def require_style(name, scrolls=4):
        rt.require(p.tap(name, exact=True, scrolls=scrolls), f"未找到入口「{name}」")
    def exact_style(name, scrolls=4, exact=True):
        """带入口的点击：失败句里带上当前页文字（PKT110 的录制口径）。"""
        if not p.tap(name, exact=exact, scrolls=scrolls):
            raise RuntimeError(f"未找到入口「{name}」；当前页：{p.page_text()}")
    style = _style(rt, "TAP_STYLE", ("require", "exact", "honor"), "require")
    if scrolls is None:
        # honor 那一档只是默认翻页预算不同（WKL-AN20 录的是 6 屏），句子与 require 逐字相同。
        scrolls = 6 if style == "honor" else 4
    if style == "exact":
        return exact_style(name, scrolls)
    return require_style(name, scrolls)



def opened(p, rt, start):
    """试一条直达页面：到了返回真。别的系统版本可能没有这一页，返回假走菜单；
    断线照常上抛——跑到一半掉线时 Phone 只置 lost、抛的是普通 RuntimeError（沿用 #293 的做法）。"""
    try:
        start()
        return True
    except (adb_link.DeviceLost, SkipStep):
        # 跳过（App 本机没装 / 按约定不跑）不是「这条路不通」：放行，由段包装记跳过（沿用 #908 的做法）
        raise
    except RuntimeError as e:
        if p.lost:
            raise
        print(f"  · 直达不通（{e}），走菜单")
        return False


def _vivo_my_tab(p, rt):
    """应用商店底部「我的」标签：在 y>92% 处，find() 默认不点，直接按坐标点最后一个标签（V1986A）。"""
    xy = p.find("我的", edge_ok="tab")
    if xy:
        p.click(*xy)
    else:
        p.click(int(p.W * 0.9), int(p.H * 0.96))
    rt.clock.sleep(1.2)


def my_tab(p, rt, *args, **kwargs):
    honor_style = functools.partial(_honor_my_tab, p, rt)
    style = _style(rt, "MY_TAB_STYLE", ("vivo", "honor"), "vivo")
    if style == "honor":
        return honor_style(*args, **kwargs)
    return _vivo_my_tab(p, rt, *args, **kwargs)



def _vivo_tap_text_style(p, rt, w, scrolls=0, wait=1.3):
    ok = p.tap(w, exact=True, scrolls=scrolls)
    rt.clock.sleep(wait)
    return ok


def tap_text(p, rt, *args, **kwargs):
    meizu_style = functools.partial(_meizu_tap_text, p, rt)
    vivo_style = functools.partial(_vivo_tap_text_style, p, rt)
    style = _style(rt, "TAP_TEXT_STYLE", ("vivo", "meizu"), "vivo")
    if style == "meizu":
        return meizu_style(*args, **kwargs)
    return vivo_style(*args, **kwargs)



def _vivo_goto_style(p, rt, name, scrolls=0):
    """点进一个列表项，并把结果打出来。

    不打印就没法区分「这页确实没开关可关」和「压根没进到这页」，跑完看到 0 个也敢信。"""
    ok = tap_row(p, rt, name, scrolls=scrolls)
    print(f"  · {name}" if ok else f"  ✗ 没找到「{name}」")
    return ok


def goto(p, rt, *args, **kwargs):
    meizu_style = functools.partial(_meizu_goto, p, rt)
    vivo_style = functools.partial(_vivo_goto_style, p, rt)
    style = _style(rt, "GOTO_STYLE", ("vivo", "meizu"), "vivo")
    if style == "meizu":
        return meizu_style(*args, **kwargs)
    return vivo_style(*args, **kwargs)






# ---------- 名字被两个家族占用：`browser_settings` ----------
#
# 注入面一个名字只能放一份实现，而 vivo 的「右上菜单 → 设置」与小米系的三种走法各自都有脚本
# 在段体里按 `browser_settings()` 点名调用（段体不能改），所以这个共用名按脚本常量 `BROWSER_FLOW`
# 分派：缺省（没写常量）走 vivo 那一套——未迁移的家族行为不变；小米系三类机型各自声明
# toolbar / menu / mine（#1244）；OPPO 的 PMA110 / PMX110 各声明 prefs_shell / prefs_start（#1245）。
#
# 两条实现在各自的家族分节里；这里只做分派，不复制实现。

def browser_settings(p, rt):
    def prefs_shell_flow():
        """直达设置页后只认已识别的子页，不从旧子页或数据页继续（PMA110）。

        直达入口可能复用旧子页；只从已识别的浏览器设置子页返回，不清数据或历史。
        命令串按执行作用域的 `BROWSER` 拼：这一档的入口只属于这台机，事实层按调用方的常量
        还原，别的家族导入同一个 `browser_settings` 时读不出这条入口（#1245）。"""
        result = p.d.shell("am start -n " + rt.constants['BROWSER_PREFS'])
        rt.require(not result.exit_code and "Error" not in result.output, "浏览器设置未打开")
        rt.clock.sleep(.5)
        for _ in range(4):
            current = p.focus()
            if current == rt.constants['BROWSER'] + "BrowserPreferencesPage":
                wait_page(p, rt, current, "浏览器")
                return
            rt.require(current == rt.constants['BROWSER'] + "BrowserPreferenceActivity",
                         "浏览器进入了未知页面，停止本段")
            p.back()
        raise RuntimeError("浏览器未回到设置首页")
    def prefs_start_flow():
        """用 `p.start` 拉设置页后逐帧核对前台，落在子页就退回（PMX110）。

        包名同样从执行作用域取（PMX110 的 `BROWSER_PKG`），理由与上一档相同。"""
        p.start(rt.constants['BROWSER_PKG'], ".settings.component.BrowserPreferencesPage")
        for _ in range(4):
            p.await_page()
            where = p.focus()
            rt.require(where.startswith("com.heytap.browser/"), "浏览器设置未打开")
            if where.endswith("BrowserPreferencesPage"):
                rt.page("浏览器", "com.heytap.browser")
                return
            rt.require(where.endswith("BrowserPreferenceActivity"), "浏览器进入未知页面，停止本段")
            p.back()
        raise RuntimeError("浏览器未回到设置首页")
    def vivo_menu_flow():
        """首选右上「菜单 → 设置」，进不去退回底部「我的」（V2547A）。

        实测冷启动会直接停在首页，底部只有菜单/窗口，没有「我的」，走「我的」会整段跑空。"""
        try:
            p.d(resourceId="com.vivo.browser:id/menu_btn").click()
            rt.clock.sleep(1.4)
            if p.tap("设置", exact=True, scrolls=0, wait=1.3) and "SettingActivity" in p.focus():
                return True
        except Exception:
            pass
        p.d.shell("input keyevent BACK")
        rt.clock.sleep(0.8)
        if p.tap("我的", exact=True, scrolls=4, wait=1.2):     # 兜底：「我的」页顶部也有设置入口
            p.top()
            if p.tap("设置", exact=True, scrolls=0, wait=1.3) and "SettingActivity" in p.focus():
                return True
        return False
    flow = _style(rt, "BROWSER_FLOW", ("vivo", "toolbar", "menu", "mine", "prefs_shell",
                                      "prefs_start", "vivo_menu", "honor_mounted", "honor_plain"), "vivo")
    if flow == "vivo":
        return browser_settings_vivo(p, rt)
    if flow in ("toolbar", "menu", "mine"):
        return browser_settings_xiaomi(p, rt)
    if flow == "honor_mounted":
        return _honor_browser_settings_mounted(p, rt)
    if flow == "honor_plain":
        return _honor_browser_settings_plain(p, rt)
    return {"prefs_shell": prefs_shell_flow, "prefs_start": prefs_start_flow,
            "vivo_menu": vivo_menu_flow}[flow]()


# ---------- 本机助手（原先由例外 `.py` 经执行作用域提供，注入面拆除后收进库里）----------

def maybe(p, rt, name, scrolls=6):
    """入口可选：`p.entry` 的薄封装，返回成没成。"""
    return p.entry(name, scrolls=scrolls)


def labels(p, root=None):
    """这一页读到的全部文字（WKL-AN20 的落点判据）。"""
    return {text for text, _, _ in p.texts(root)}


def no_agreement(p, rt, app):
    """App 还弹着用户协议就停（CLE-AN00）。"""
    if p.find("同意", exact=True, edge_ok="tab") or p.find("同意并继续", exact=True, edge_ok="tab"):
        rt.skip(f"{app}还没同意用户协议，不代为同意。需要的话打开{app}同意后，单独跑这一段")


def settle_page(p, rt, package, *markers, timeout=5):
    """包名、可见标题和节点位置连续稳定后才使用坐标；不输出账号内容（WKL-AN20）。"""
    deadline, previous = rt.clock.monotonic() + timeout, None
    while rt.clock.monotonic() < deadline:
        rt.require(not p.locked(), "手机锁屏，请机主解锁后重跑")
        root = p.tree()
        texts = p.texts(root)
        if any(text in ("同意", "同意并继续", "同意并使用", "允许")
               and "Button" in node.get("class", "")
               for text, _, node in texts):
            p.dismiss()
            raise RuntimeError("遇到协议或权限申请，未代为同意，本段停止")
        signature = (p.focus(), tuple((text, box) for text, box, _ in texts))
        if signature[0].split("/", 1)[0] == package and set(markers) <= labels(p, root):
            if texts and signature == previous:
                return root
        previous = signature
        rt.clock.sleep(.25)
    raise RuntimeError("未确认目标设置页：" + "、".join(markers))


def assert_no_other_window(p, rt, root, package):
    """不在小窗混合其他应用或权限页时点击（魅族 21 Pro）。"""
    foreign = {n.get("package") for n in root.iter("node") if p.on_screen(n)
               and n.get("package") and n.get("package") not in (package, "com.android.systemui")}
    rt.require(not foreign, "检测到其他应用窗口或权限页，停止本段")


def title_key(title):
    """vivo 把说明拼在点号后；状态尾缀已由引擎剥掉（#565）。"""
    return title.split(".", 1)[0].strip()


def _labelled(text, name):
    """读屏会把状态后缀并进同一段文字（「全部关闭 - 已停用」），按主语认（PMX110）。"""
    rest = text[len(name):]
    return text.startswith(name) and (not rest or rest[0] in " ,，、-")


MenuState = namedtuple("MenuState", "close_all_disabled system_apps_shown")
