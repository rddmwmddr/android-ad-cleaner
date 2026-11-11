"""弹窗与推广位：`dismiss()` 的四条退化链，以及点过才发现是推广位的退回（ADR-0033、#1043）。

这一段只决定「点哪个」：权限申请页只点明确的拒绝键，更新弹窗先按标题认，纯图标弹窗按
desc / id 认 ✕，其余按文字认拒绝类按钮；点完前台换成了别的 App 就退回原 App，并把这一处记进
启动会话。怎么点在观测基座的动作原语上（`click` / `back`），这里不碰传输，也不认识门面。

确认框（拨一次开关后要再点一次才生效的那类）不归这里：它的认法在 `Screen.confirm_target()`，
拨动点掉遮罩、导航报出失败原因都用那一份，别在这里再写一份词表。
"""
import re
import time

from row import bounds, is_switch, switches_in

from phone.screen import PERMISSION_CONTROLLERS

DISMISS = ("以后再说", "暂不更新", "暂不", "取消", "我知道了", "跳过", "禁止", "不再提示", "不同意")
# 应用内更新弹窗的标题（沿用 #286：主题商店 17.22.0beta2 是「检测到新版本」）。它通常把更新说明放进可滚动容器，
# 只按标题认，不按按钮认：单个「取消」在正常设置面板里也有。
UPDATE_TITLE = re.compile(r"检测到新版本|发现新版本|版本更新提示")


class Dismisser:
    """弹窗的退化链与推广位退回。

    `screen` 是观测基座（读屏与动作原语都经它），`session` 是启动会话：
    推广位退回读它记的目标 App（`app`）、把点过的这一处写进 `promoted`。
    """

    CLOSE = re.compile(r"close|关闭|跳过|skip|cancel|dismiss|iv_x\b|btn_x\b", re.I)
    # 描述精确读作「返回」的不是弹窗的 ✕，是浮层/页面自己的返回键：点了是导航，会把刚打开的
    # 浮层收起来。vivo 浏览器菜单的 iv_back_cancel 就长这样，id 里的 cancel 本来会命中 CLOSE（沿用 #753）。
    BACK_LABELS = {"返回", "back"}

    def __init__(self, screen, session):
        self.screen = screen
        self.session = session

    def dismiss(self):
        """挡路的更新/推荐/权限弹窗：点拒绝类按钮（不替用户同意任何东西）。
        纯图片的广告弹窗没有文字，只有一个 ✕ 图标：找 desc/id 里带 close 的可点元素。
        返回非空表示这次关掉了东西，返回前已经等过界面过渡（0.4~0.6 秒），调用方不必再等；
        返回 None 表示这次没关掉任何东西（推广位的 ✕ 点过也已退回原 App），
        调用方按自己的节奏等待或重试。轮询处写成 `if not self.dismiss(): time.sleep(x)`：
        刚关掉就立刻重读，什么都没关才按间隔再读。"""
        screen = self.screen
        root = screen.tree()
        # Android 运行时权限页只点明确的拒绝按钮，不替用户授予权限或修改“不再询问”。
        if (any(n.get("package") in PERMISSION_CONTROLLERS for n in root.iter("node"))
                and screen.focus().split("/", 1)[0] in PERMISSION_CONTROLLERS):
            for n in root.iter("node"):
                if (n.get("package") in PERMISSION_CONTROLLERS and "Button" in n.get("class", "")
                        and n.get("text") in ("拒绝", "不允许", "Deny", "Don't allow") and screen.on_screen(n)):
                    l, t, r, b = bounds(n)
                    screen.click((l+r)//2, (t+b)//2); time.sleep(.4)
                    screen.say("  · 已拒绝运行时权限申请，未授予权限")
                    return "拒绝权限"
            return None
        parent = {c: p for p in root.iter() for c in p}

        def in_list(n):
            # 列表里卡片的 ✕（ColorOS 17 隐私页「关闭提示」）点了会打开别的页面；广告弹窗的 ✕ 在列表外的浮层里。
            n = parent.get(n)
            while n is not None:
                if n.get("scrollable") == "true":
                    return True
                n = parent.get(n)
            return False

        # 设置页里含「关闭」的说明行本身可能就是开关，点它等于替用户拨一次（沿用 #378）。
        # 按候选子树判定而不是整屏——ColorOS 17 隐私页的浮层 ✕ 盖在带开关的页面上，仍然要能点。
        def is_switch_row(n):
            return is_switch(n) or bool(switches_in(n, screen.on_screen))

        for n in root.iter("node"):
            if n.get("clickable") != "true" or n.get("package") == "com.android.systemui":
                continue
            desc = (n.get("content-desc") or "").strip()
            key = desc + " " + (n.get("resource-id") or "")
            if (self.CLOSE.search(key) and desc.casefold() not in self.BACK_LABELS
                    and not (n.get("text") or "").strip()
                    and not in_list(n) and not is_switch_row(n)):
                l, t, r, b = bounds(n)
                # 只点屏幕内的图标：屏幕外还留着上一层的节点，点它会抛「点击坐标在屏幕外」把整段打断
                if 0 < r - l < screen.W * 0.3 and 0 < b - t < screen.H * 0.12 and screen.on_screen(n):
                    if self.promoted_click((l + r) // 2, (t + b) // 2, key.strip()):
                        return None         # 没关掉弹窗，调用方按「这次什么也没关」处理
                    screen.say(f"  · 弹窗点了 ✕（{key.strip()[:40]}）")
                    return "✕"
        tx = screen.texts(root)

        def refuse():
            for w in DISMISS:
                for t, (l, tp, r, b), _ in tx:
                    if t == w:
                        screen.click((l + r) // 2, (tp + b) // 2); time.sleep(0.6)
                        screen.say(f"  · 弹窗点了「{w}」")
                        return w
            return None

        # 更新弹窗先认，且不看有没有滚动列表：主题商店把更新说明放在可滚动容器里，下面的守卫会漏掉它（沿用 #286）；
        # 正常设置面板没有「检测到新版本」这类标题，所以仍不会被当成弹窗。
        if any(UPDATE_TITLE.search(t) for t, _, _ in tx):
            hit = refuse()
            if hit:
                return hit
        if len(tx) > 16:
            return None
        # 天气等 App 的正常设置面板也有「取消」。带开关/滚动列表的页面不能仅凭文字当弹窗关掉。
        if any(n.get("checkable") == "true" or n.get("scrollable") == "true" for n in root.iter("node")):
            return None
        return refuse()

    def promoted_click(self, x, y, key):
        """点 ✕ 之后前台换成了别的 App：多半是页面里的推广位（沿用 #420），退回原 App 并记下这一处。
        点前不在目标 App（抢焦点的广告浮层）或点后读不到前台时不算推广位，调用方照旧算关闭。
        返回真表示这次没关掉弹窗。"""
        screen, session = self.screen, self.session
        before = screen.focus().split("/", 1)[0]
        if before and (before, key) in session.promoted:
            return True                     # 这个 App 的这一处点过并跳走了：再点还是跳
        screen.click(x, y); time.sleep(0.6)
        after = screen.focus().split("/", 1)[0]
        if not (before and after and before == session.app and after != before):
            return False
        session.promoted.add((before, key))
        screen.back(); time.sleep(.4)
        where = screen.focus().split("/", 1)[0]
        if where and where != before:        # 一次返回还没退回来，再退一次
            screen.back(); time.sleep(.4)
            where = screen.focus().split("/", 1)[0]
        if where and where != before:
            # 退不回来就停：不能把用户留在别的 App 里，也不能在陌生页面上接着找入口
            raise RuntimeError(f"点 ✕ 后跳到了 {after}，返回两次仍停在 {where}，停止本段以免操作其他 App")
        screen.say(f"  · 点了 ✕ 后跳到 {after}，疑似推广位，已退回（{key[:40]}）")
        return True
