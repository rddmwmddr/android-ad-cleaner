"""meizu 家族库（#1269）：只被 meizu 家族用到的实现住在这里。

上半是词汇（原 `recipe_nav`），下半是策略（原 `recipe_strategies` / `recipe_steps`）。
跨家族用到的实现不放在这里，见 `recipe_lib/shared.py`。
"""

from recipe_lib.shared import tap_text, wait_page

__all__ = ('assert_no_other_window', 'safe_switches')

# ---------- 词汇 ----------
def _meizu_wait_page(p, rt, activity, title, timeout=8):
    """等页面认得出，顺手记下落到的包名给同脚本的其它助手用（Flyme 的 `TARGET_PACKAGE` 约定）。

    落到的包名写到 `rt.target`，同脚本的 `tap_id` 从那里读。"""
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
    before_list = safe_switches(p, rt, activity)
    rt.require(all(sum(1 for t, _, _ in before_list if t == name) == 1 for name in names),
                 f"{page}：目标开关未全部唯一识别，未操作")
    baseline = {t: on for t, on, _ in before_list}
    print(f"  准备关闭 {page}：{'、'.join(names)}；已关闭的保持不变", flush=True)
    for name in names:
        rt.require(not p.locked(), "手机锁屏，请机主解锁")
        rt.require(p.focus() == activity, "页面已变化，停止本段")
        switches = [(on, xy) for t, on, xy in safe_switches(p, rt, activity) if t == name]
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
        after_list = safe_switches(p, rt, activity)
        after = {t: on for t, on, _ in after_list}
        rt.require(sum(1 for t, _, _ in after_list if t == name) == 1 and after.get(name) is False,
                     f"{name}：回读未确认关闭")
        rt.require(all(after.get(t) == state for t, state in baseline.items() if t not in names),
                     f"{page}：其他开关状态变化，请手动核对")
        p.changed.append((page, name))
        print(f"  关 {name}（已回读）", flush=True)

def assert_no_other_window(p, rt, root, package):
    """不在小窗混合其他应用或权限页时点击（魅族 21 Pro）。"""
    foreign = {n.get("package") for n in root.iter("node") if p.on_screen(n)
               and n.get("package") and n.get("package") not in (package, "com.android.systemui")}
    rt.require(not foreign, "检测到其他应用窗口或权限页，停止本段")

# ---------- 策略 ----------
def safe_switches(p, rt, activity):
    rt.require(p.focus() == activity, "页面已变化，停止本段")
    root = p.tree()
    assert_no_other_window(p, rt, root, activity.split("/", 1)[0])
    return p.switches(root)
