"""oppo 家族库（#1269）：只被 oppo 家族用到的实现住在这里。

上半是词汇（原 `recipe_nav`），下半是策略（原 `recipe_strategies` / `recipe_steps`）。
跨家族用到的实现不放在这里，见 `recipe_lib/shared.py`。
"""

from collections import namedtuple
import adb_link
from recipe_runtime import SkipStep
from row import bounds
from recipe_lib.shared import _style, app_settings, close_named, close_named_step, maybe, open_page, page_activity, read_switches, wait_page, wait_switches

__all__ = ('ad_id_page', 'ad_tracking_close_all', 'assistant_advice_rows', 'assistant_advice_search', 'assistant_icon', 'assistant_screen', 'assistant_settings', 'at_assistant', 'browser_ads', 'browser_home', 'browser_personalized', 'browser_settings_direct', 'carousel_choices', 'close_all', 'close_all_listed', 'close_group', 'close_named_expect', 'close_named_optional', 'close_named_plain', 'close_rows', 'close_titles', 'enter_privacy', 'enter_settings', 'game_center_direct', 'game_center_taps', 'game_settings_direct', 'game_settings_entry', 'game_settings_via_mine', 'has_row', 'hide_carousel', 'menu_state', 'more_menu', 'navigate', 'off_exact', 'off_exact_paged', 'off_exact_paged_optional', 'open_app_settings', 'open_search_setting', 'open_search_settings', 'open_search_sub', 'open_switch_page', 'read_on_page', 'row', 'search_settings', 'search_settings_direct', 'search_settings_ready', 'search_settings_swipe', 'settings_page', 'store_privacy', 'store_promotions', 'system_settings', 'tap_by_scroll', 'tap_page', 'theme_shop_settings', 'theme_store_settings', 'video_direct', 'wait_search_settings')

# ---------- 词汇 ----------
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

def navigate(p, rt, label, activity, title):
    """`label` 可以给一组等价入口文案，按顺序试；点到第一个就按落点页面判（沿用 #933）。"""
    labels = (label,) if isinstance(label, str) else tuple(label)
    for name in labels:
        if p.tap(name, exact=True, quiet=len(labels) > 1):
            return page_activity(p, rt, activity, title)
    p.note_miss(" / ".join(labels))
    return False

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
        return read_on_page(p, rt, titles, package)
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
    return MenuState(disabled, system_shown)

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

def _labelled(text, name):
    """读屏会把状态后缀并进同一段文字（「全部关闭 - 已停用」），按主语认（PMX110）。"""
    rest = text[len(name):]
    return text.startswith(name) and (not rest or rest[0] in " ,，、-")

# ---------- 策略 ----------
def off_exact(p, rt, names, activity, title):
    """只处理当前页精确匹配的开关，并在同一页面读回（PHK110 的 Android 15 变体）。"""
    if not page_activity(p, rt, activity, title):
        return False
    switches = p.switches()
    visible = {name for name, _, _ in switches}
    wanted = set(names)
    if not wanted <= visible:
        print(f"  ! 缺少开关 {sorted(wanted - visible)}，本页不操作")
        return False
    for name in names:
        if not page_activity(p, rt, activity, title):
            return False
        matches = [(on, xy) for label, on, xy in p.switches() if label == name]
        if len(matches) != 1:
            print(f"  ! 开关「{name}」无法唯一确认，停止")
            return False
        on, xy = matches[0]
        if on:
            p.click(*xy)
            p.confirm()
            if not page_activity(p, rt, activity, title):
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

def close_titles(p, rt, wanted, max_rounds=8):
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
                rt.clock.sleep(0.5)
                p.confirm()
                rt.clock.sleep(0.5)
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

def read_on_page(p, rt, titles, package):
    """确认落在目标页并读出这一页的开关：读不到目标时整段不动，报错带上停在哪个页与当次
    读到的标题（沿用 #903），不再「核对 0 项」静默收尾。"""
    from wait import until

    rt.page(titles, package)
    until(p.switches, tries=10, poll=0.2, now=rt.clock.time, sleep=rt.clock.sleep)
    return {text: on for text, on, _ in p.switches()}

def close_all_listed(p, rt, label):
    """当前列表里还有开着的就点「全部关闭」，再开一次菜单确认它变灰（沿用 #650）。"""
    state = menu_state(p, rt)
    if state.close_all_disabled:
        p.back()
        print(f"  · 广告跟踪（{label}）：已全部关闭，未点击", flush=True)
        return
    rt.require(p.tap("全部关闭", exact=True, scrolls=0), "未能点「全部关闭」")
    p.confirm()
    p.await_page()
    state = menu_state(p, rt)
    p.back()
    rt.require(state.close_all_disabled, f"广告跟踪（{label}）：点了「全部关闭」后仍有开着的应用")
    print(f"  · 广告跟踪（{label}）：已全部关闭，菜单项已置灰确认", flush=True)

def close_rows(p, rt, names, page):
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
        rt.clock.sleep(0.9)
        done.append(title)
    print(f"  · {page}：关了 {len(done)} 项" + (f"（{'、'.join(done)}）" if done else ""))
    return len(done)

def off_exact_paged(p, rt, names, page, max_screens=16):
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

def off_exact_paged_optional(p, rt, names, page, max_screens=16):
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

def close_named_optional(p, rt, names, title, max_screens=12, dependent=(), reopen=None, snapshot=None, optional=()):
    """关掉点名的开关，并核对目标已关、非目标未变。

    optional 里的名字允许这次页面上没有：记成「未显示」并继续；名单其余项缺一个就整段不动。
    """
    # 回读确认数由引擎经 rt 记录
    before = read_switches(p, rt, title, max_screens) if snapshot is None else snapshot
    rt.require_switches(before, names, title, optional=optional)
    present = [name for name in names if name in before]
    absent = [name for name in names if name not in before]
    if absent:
        note = f"{title}：本次未显示 {'、'.join(absent)}，未操作、不计为已关闭"
        rt.constants['SKIPPED_ITEMS'].append(note)
        print("  · " + note, flush=True)
    if not present:
        return
    if not any(before[name] for name in present):
        rt.confirm(len(present))
        print(f"  · {title}：读取确认 {len(present)} 项原已关闭，未点击", flush=True)
        return
    p.top(max_screens)
    p.off(only=list(present), keep=[name for name in before if name not in names],
          page=title, max_screens=max_screens)
    if reopen:
        reopen()
    after = read_switches(p, rt, title, max_screens)
    rt.require(all(after.get(name) is False for name in present), f"{title}：回读未确认关闭")
    rt.require(all(after.get(name) == state for name, state in before.items()
                if name not in names and name not in dependent), f"{title}：其他功能开关状态变化")
    rt.confirm(len(present))
    print(f"  · {title}：回读确认 {len(present)} 项关闭", flush=True)

def close_named_expect(p, rt, names, page, activity, title=None, max_screens=8, reopen=None, dependent=()):
    """精确核对标题再调用引擎；回读关闭状态，同时保留其他功能开关。"""
    # 回读确认数由引擎经 rt 记录
    before = read_switches(p, rt, activity, title, max_screens, expect=names)
    rt.require_switches(before, names, page)
    if any(before[name] for name in names):
        p.top(max_screens)
        p.off(only=list(names), keep=[name for name in before if name not in names],
              page=page, max_screens=max_screens)
        if reopen:
            reopen()
        current = read_switches(p, rt, activity, title, max_screens, expect=names)
        rt.require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
        rt.require(all(current.get(name) == state for name, state in before.items()
                    if name not in names and name not in dependent), f"{page}：其他开关状态变化，请核对")
    rt.confirm(len(names))
    print(f"  · {page}：回读确认 {len(names)} 项关闭", flush=True)

def close_named_plain(p, rt, names, page, activity, title, max_screens=8, reopen=None, dependent=()):
    """精确核对标题再调用引擎；回读关闭状态，同时保留其他功能开关。"""
    # 回读确认数由引擎经 rt 记录
    before = read_switches(p, rt, activity, title, max_screens)
    rt.require_switches(before, names, page)
    if any(before[name] for name in names):
        p.top(max_screens)
        # off 的 only 为子串匹配，keep 排除所有非精确目标（包括未知的相似标题）。
        p.off(only=list(names), keep=[name for name in before if name not in names],
              page=page, max_screens=max_screens)
        if reopen:
            reopen()
        current = read_switches(p, rt, activity, title, max_screens)
        rt.require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
        rt.require(all(current.get(name) == state for name, state in before.items()
                    if name not in names and name not in dependent), f"{page}：其他开关状态变化，请核对")
    rt.confirm(len(names))
    print(f"  · {page}：回读确认 {len(names)} 项关闭", flush=True)

def close_group(p, rt, children, parent, page, max_screens=1):
    """有的开关是父项的子项：父开关一关，子项那两行就从页面上消失了（点不到、也回读不到）。
    父项还开着时先关子项再关父项；父项本来就是关的，子项压根不在页面上，只关父项。"""
    p.top(max_screens)
    first = wait_switches(p, rt)
    rt.require(first, f"{page}：页面里没读到开关，未操作")
    if read_switches(p, rt, max_screens, first=first).get(parent):
        close_named(p, rt, children, page, max_screens=max_screens)
        close_named(p, rt, [parent], page, max_screens=max_screens, gone=children)
    else:
        close_named(p, rt, [parent], page, max_screens=max_screens)

def close_all(p, rt, page, max_screens):
    """整页关掉所有开关（逐 App 的广告跟踪列表用），关完回读确认。"""
    # 回读确认数由引擎经 rt 记录
    p.top(max_screens)
    first = wait_switches(p, rt)
    rt.require(first, f"{page}：没读到开关，未操作")
    before = read_switches(p, rt, max_screens, first=first)
    rt.require(before, f"{page}：没读到开关，未操作")
    p.top(max_screens)                   # 读完整页会翻到底；p.off 自己也回顶，这一下是让前后两段都从页顶读
    p.off(page=page, max_screens=max_screens)
    p.top(max_screens)
    current = read_switches(p, rt, max_screens)
    still = sorted(name for name, on in current.items() if on)
    rt.require(not still, f"{page}：回读未确认关闭（仍有 {len(still)} 项开着）")
    rt.confirm(len(before))

def browser_home(p, rt):
    if not browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page(p, rt, "主页设置", activity, "主页设置"):
        return False
    if p.find("简洁", exact=True):
        print("  · 首页已为简洁，保持不变")
        return True
    if not tap_page(p, rt, "页面布局", activity, "页面布局"):
        return False
    if not p.tap("简洁", exact=True, scrolls=0):
        return False
    p.back()
    if not wait_page(p, rt, activity, "主页设置") or not p.find("简洁", exact=True):
        return False
    p.changed.append(("浏览器主页", "默认 → 简洁"))
    return True

def off_exact_step(p, rt, names, page, *args, **kwargs):
    """共享段体里的 off_exact 档位：默认 paged，PKH110 用允许缺项的那一档（#1268）。"""
    fn = off_exact_paged_optional if rt.constants.get("OFF_EXACT_OPTIONAL") else off_exact_paged
    return fn(p, rt, names, page, *args, **kwargs)

def store_promotions(p, rt):
    if not open_app_settings(p, rt, "com.heytap.market",
                                 "com.heytap.market.mine.cn.setting.ui.SettingActivity",
                                 "应用与服务"):
        return False
    if not tap_page(p, rt, "服务管理",
                         "com.heytap.market.mine.cn.setting.ui.ServeManagerActivity", "服务管理"):
        return False
    p.top(n=12)
    return off_exact_step(p, rt, rt.constants['STORE_PROMOTIONS'], "商店·推广入口")

def browser_ads(p, rt):
    if not browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page(p, rt, "隐私", activity, "隐私") or not tap_page(p, rt, "广告管理", activity, "广告管理"):
        return False
    completed = off_exact_step(p, rt, ["开屏广告", "资讯列表广告"], "浏览器·广告管理", max_screens=2)
    print("  · 摇一摇广告可能随上级开关灰置；不将 checked=true 的灰置项计作独立关闭")
    return completed

def browser_personalized(p, rt):
    if not browser_settings_direct(p, rt):
        return False
    activity = "com.heytap.browser.settings.component.BrowserPreferenceActivity"
    if not tap_page(p, rt, "隐私", activity, "隐私") or not tap_page(p, rt, "个性化管理", activity, "个性化管理"):
        return False
    return off_exact_step(p, rt, ["个性化优惠推荐", "个性化广告推荐"], "浏览器·个性化管理", max_screens=2)

def assistant_screen(p, rt):
    from fast import ScreenLocked
    l, t, r, b = bounds(assistant_icon(p, rt))
    before = p.sig()
    p.click((l + r) // 2, (t + b) // 2)
    p.settle(before, 2.4)
    row(p, rt, "设置", title="推荐服务")
    row(p, rt, "推荐服务")
    where = p.focus()
    carousel_error = None
    try:
        hide_carousel(p, rt)
    except (adb_link.DeviceLost, ScreenLocked):
        raise
    except RuntimeError as error:
        rt.require(p.focus() == where, "轮播识别失败且已离开原页，停止本段")
        carousel_error = error
        print(f"  ✗ 轮播推荐未确认：{error}；继续核对独立的热点资讯", flush=True)
    # 热点资讯页有导出，直达（沿用 #650 的做法），不用回设置页再滚动找
    hot_news = "am start -f 0x10008000 -n com.coloros.assistantscreen/com.oplus.assistantscreen.card.infoflow.setting.activity.InfoFlowSettingActivity"
    open_page(p, rt, hot_news, "热点资讯", "com.coloros.assistantscreen", "InfoFlowSettingActivity")
    close_named_step(p, rt, ["热点资讯"], "热点资讯")
    if carousel_error:
        raise RuntimeError(f"热点资讯已核对；轮播推荐未完成：{carousel_error}")

def search_settings_direct(p, rt):
    open_page(p, rt, rt.constants['SEARCH_SETTINGS'], "搜索范围", rt.constants['SEARCH'], "SearchSettingActivity")
    row(p, rt, "搜索范围")
    close_named_step(p, rt, ["个性化推荐", "精选资讯"], "搜索范围", dependent=["全部"])
    p.back()
    row(p, rt, "首页卡片管理")
    cards = read_switches(p, rt, "首页卡片管理")
    names = [name for name in rt.constants['SEARCH_CARDS'] if name in cards]
    if names:
        close_named_step(p, rt, names, "首页卡片管理", snapshot=cards)
    missing = len(rt.constants['SEARCH_CARDS']) - len(names)
    if missing:
        note = f"首页卡片管理：本次未显示 {missing} 个录制推广项，未操作、不计为已关闭"
        rt.constants['SKIPPED_ITEMS'].append(note)
        print("  · " + note, flush=True)
    p.back()
    row(p, rt, "功能管理")
    close_named_step(p, rt, ["搜索框提示词"], "功能管理")
    p.back()
    # 「账号与隐私」只是设置页上的分组标题，没有二级页面；直接点它下面的隐私行。
    row(p, rt, "隐私")
    close_named_step(p, rt, ["个性化推荐"], "隐私")

def theme_store_settings(p, rt):
    app_settings(p, rt, rt.constants['THEME'])
    row(p, rt, "服务管理")
    row(p, rt, "消息与广告")
    close_named_step(p, rt, ["开屏广告"], "消息与广告")
    app_settings(p, rt, rt.constants['THEME'])
    row(p, rt, "隐私")

    def reopen() -> None:
        app_settings(p, rt, rt.constants['THEME'])
        row(p, rt, "隐私")

    close_named_step(p, rt, ["个性化推荐设置"], "隐私", reopen=reopen)

def video_direct(p, rt):
    require_installed(p, rt, rt.constants['VIDEO'], "视频")
    # 设置页没导出，用 App 自己的深链直达（沿用 #650 的做法），不经开屏页和「我的」；带 -p 限定到视频，
    # 免得别的 App 也注册了这个 scheme 时弹选择器
    open_page(p, rt, "am start -f 0x10008000 -a android.intent.action.VIEW -p " + rt.constants['VIDEO']
                   + " -d yoli://yoli.com/mine_act_lib_yoli/settings", "设置", rt.constants['VIDEO'], "SettingActivity")
    row(p, rt, "个性化管理")
    close_named_step(p, rt, ["个性化广告推荐", "个性化内容推荐"], "个性化管理")

def game_center_direct(p, rt):
    require_installed(p, rt, rt.constants['GAME'], "游戏中心")
    open_page(p, rt, "am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p " + rt.constants['GAME'],
                   "游戏中心", rt.constants['GAME'], "SettingActivity")
    row(p, rt, "隐私开关设置", scrolls=6)
    row(p, rt, "个性化推荐管理", scrolls=4)
    close_named_step(p, rt, ["个性化推荐"], "个性化推荐管理")
    p.confirm()

def assistant_advice_rows(p, rt):
    system_settings(p, rt)
    row(p, rt, "OPPO AI")
    row(p, rt, "小布建议")
    row(p, rt, "资讯服务")
    close_named_step(p, rt, ["资讯服务"], "资讯服务")

def ad_tracking_close_all(p, rt):
    rt.skip_in_safe_mode()
    found = settings_page(p, rt, "隐私与安全", "设备标识与广告", "广告跟踪")
    if not found:
        p.miss = 0
        found = settings_page(p, rt, "隐私", "设备标识与广告", "广告跟踪")
    if not found:
        return
    # 右上角三个点（更多选项）菜单里有「全部关闭」，一键关完，比逐个点稳
    if p.tap("更多选项", exact=True, scrolls=0):
        if p.tap("全部关闭", exact=True, scrolls=0):
            p.confirm()                       # 有的版本会弹确认框
            rt.clock.sleep(0.5)
            still = [t for t, c, _ in p.switches() if c]
            if not still:
                p.changed.append(("广告跟踪", "全部关闭（更多选项菜单）"))
                return
            p.say(f"  ! 「全部关闭」后这一屏仍有 {len(still)} 个开关开着，退回逐项关")
        else:
            p.back()                          # 菜单开了但没点成：收起后退回逐个关
    p.miss = 0
    p.off(page="广告跟踪", max_screens=40)

def search_settings_swipe(p, rt):
    if not search_settings(p, rt):
        raise RuntimeError("没进全局搜索设置页")
    if p.tap("搜索范围", exact=True):
        # APP内搜索、搜索建议、小程序、AI搜索、便捷服务保留
        p.off(only=["榜单", "小说", "购物", "个性化推荐", "精选资讯"], page="下拉搜索·搜索范围")
        p.back()
    if p.tap("首页卡片管理", exact=True):
        p.off(only=["未下载应用推荐", "应用建议小卡", "热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"], page="下拉搜索·首页卡片管理")
        p.back()
    if p.tap("功能管理", exact=True):
        p.off(only=["搜索框提示词"], page="下拉搜索·功能管理")
        p.back()
    if p.tap("账号与隐私", exact=True) and p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="下拉搜索·隐私")
        p.back(2)
    p.back(2)

def game_center_taps(p, rt):
    p.start("com.nearme.gamecenter")
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("没找到底部「我的」")
    rt.clock.sleep(1.2)
    p.dismiss()
    # 14.43.3：「设置」是「我的」页里带新通知标记的文字行（非右上角齿轮）
    if not p.tap("设置", exact=False, scrolls=0) and not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("没找到设置入口")
    if p.tap("隐私开关设置", exact=True) and p.tap("个性化推荐管理", exact=True):
        p.off(only=["个性化推荐"], page="游戏中心·个性化推荐管理")
    p.back(4)

def theme_shop_settings(p, rt):
    p.start("com.heytap.themestore")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("服务管理", exact=True):
        # 「全部服务/基础服务」保持全部服务；锁屏开关是功能项
        if maybe(p, rt, "消息与广告"):
            p.off(only=["消息通知", "开屏广告"], page="主题·消息与广告")
            p.back()
        p.back()
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="主题·个性化推荐")
        p.back()
    p.back(2)

def assistant_advice_search(p, rt):
    if settings_page(p, rt, "OPPO AI", "小布建议"):
        # 「内容资讯」是分组标题；「资讯服务」是子入口，进去关开关
        if p.tap("资讯服务", exact=True):
            p.off(only=["资讯服务"], page="小布建议·内容资讯")
            p.back()
    p.back(2)

def require_installed(p, rt, package, label):
    """没装的包 `pm path` 输出为空，退出码是 1 或 0：那是「没装」，跳过本段（#899）。"""
    result = p.d.shell("pm path " + package)
    if "package:" in result.output:
        return
    rt.require(result.exit_code in (0, 1) and not result.output.strip(), f"无法读取{label}安装状态")
    rt.skip(f"本机未安装{label}")

MenuState = namedtuple("MenuState", "close_all_disabled system_apps_shown")
