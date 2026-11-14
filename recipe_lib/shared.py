"""跨家族共享的词汇与策略（#1269）：被 ≥2 个家族用到的实现住在这里。

归属判据：家族取自 `entries.FAMILY`；一个实现只在 ≥2 个家族的机型里被调用才进本文件。
只服务一个家族的实现放 `recipe_lib/<家族>.py`（`dev.recipes.shared-sections` 守着）。
分派器（`browser_settings` 等）按机型常量选家族实现，那些实现住在各自的家族文件里。
"""

import functools
import re
from collections.abc import Callable
from typing import Any
from wait import GiveUp
from wait import until
import adb_link
from recipe_runtime import SkipStep

__all__ = ('app_settings', 'browser_settings', 'close_named', 'enter', 'gear', 'gear_top', 'goto', 'my_tab', 'open_page', 'open_settings', 'opened', 'page_activity', 'read_switches', 'switch_signature', 'switch_top', 'tap', 'tap_text', 'wait_page', 'wait_switches')

# ---------- 词汇 ----------
def _style(rt, constant, choices, default):
    """脚本的模块级常量选了哪一档走法：缺省 `default`，认不出当场报错。

    静默回退会点错入口，比报错更难查（沿用 #819 的口径）。常量是脚本自己的页面知识，
    库按它选实现，不按型号猜。
    """
    value = rt.constants.get(constant, default)
    if value not in choices:
        raise RuntimeError(f"脚本常量 {constant} = {value!r} 认不出；可用的：{'、'.join(choices)}")
    return value

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
    flows: dict[str, Callable[..., Any]] = {"text": text_style, "vivo": vivo_style}
    return flows[style]()

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
    flows: dict[str, Callable[..., Any]] = {"plain": plain_style, "title": title_style,
                                            "first": first_style, "expect": expect_style, "vivo": vivo_style}
    return flows[style](*args, **kwargs)

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
        first = wait_switches(p, rt)
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
    flows: dict[str, Callable[..., Any]] = {"plain": plain_style, "basic": basic_style,
                                            "vanish": vanish_style, "reopen": reopen_style, "meizu": meizu_style}
    return flows[style](*args, **kwargs)

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

def my_tab(p, rt, *args, **kwargs):
    honor_style = functools.partial(_honor_my_tab, p, rt)
    style = _style(rt, "MY_TAB_STYLE", ("vivo", "honor"), "vivo")
    if style == "honor":
        return honor_style(*args, **kwargs)
    return _vivo_my_tab(p, rt, *args, **kwargs)

def tap_text(p, rt, *args, **kwargs):
    meizu_style = functools.partial(_meizu_tap_text, p, rt)
    vivo_style = functools.partial(_vivo_tap_text_style, p, rt)
    style = _style(rt, "TAP_TEXT_STYLE", ("vivo", "meizu"), "vivo")
    if style == "meizu":
        return meizu_style(*args, **kwargs)
    return vivo_style(*args, **kwargs)

def goto(p, rt, *args, **kwargs):
    meizu_style = functools.partial(_meizu_goto, p, rt)
    vivo_style = functools.partial(_vivo_goto_style, p, rt)
    style = _style(rt, "GOTO_STYLE", ("vivo", "meizu"), "vivo")
    if style == "meizu":
        return meizu_style(*args, **kwargs)
    return vivo_style(*args, **kwargs)

def browser_settings(p, rt):
    def prefs_shell_flow():
        """直达设置页后只认已识别的子页，不从旧子页或数据页继续（PMA110）。

        直达入口可能复用旧子页；只从已识别的浏览器设置子页返回，不清数据或历史。
        命令串按 `rt.constants['BROWSER_PREFS']` 拼：这一档的入口只属于这台机，事实层按调用方的常量
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

        包名从 `rt.constants['BROWSER_PKG']` 取（PMX110），理由与上一档相同。"""
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

def maybe(p, rt, name, scrolls=6):
    """入口可选：`p.entry` 的薄封装，返回成没成。"""
    return p.entry(name, scrolls=scrolls)

# ---------- 策略 ----------
def wait_switches(p, rt, timeout=4.0):
    """刚进二级页时开关还没画出来：等一下再读，别把空页面当成「没找到目标开关」。"""
    end = rt.clock.time() + timeout
    while True:
        found = p.switches()
        if found:
            return found
        if rt.clock.time() >= end:
            return []
        rt.clock.sleep(0.2)

def close_named_step(p, rt, names, title, *args, **kwargs):
    """共享段体里的 close_named 档位：默认小米那一档，PMX110 / PLZ110 用 optional（#1268）。

    名字带 `close_named` 前缀：事实层按前缀认「这一页点名关了哪些开关」，改包装不丢词条。"""
    fn = close_named_optional if rt.constants.get("CLOSE_NAMED_OPTIONAL") else close_named
    return fn(p, rt, names, title, *args, **kwargs)

# 分派器按机型常量选家族实现：家族文件加载完后再绑进本模块全局名（放文件末尾，避免 import 环）。
from recipe_lib.honor import _honor_app_settings, _honor_browser_settings_mounted, _honor_browser_settings_plain, _honor_my_tab
from recipe_lib.meizu import _meizu_close_named, _meizu_goto, _meizu_tap_text, _meizu_wait_page
from recipe_lib.oppo import close_named_optional
from recipe_lib.vivo import _VIVO_GEAR_FACTORIES, _vivo_gear_top_style, _vivo_goto_style, _vivo_my_tab, _vivo_read_switches_style, _vivo_tap_text_style, browser_settings_vivo
from recipe_lib.xiaomi import _xiaomi_close_named, _xiaomi_read_switches, browser_settings_xiaomi
