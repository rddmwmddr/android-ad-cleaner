"""导航：按文字点、换页校验、等页、底栏、图标入口、回顶（ADR-0033、#1044）。

这一段只编排「按什么字点什么」，观测与动作原语全在 `Screen`：找文字是 `find()`，翻页是
`scroll_more()`，点击与返回是 `click()` / `back()`。挡路的弹窗不归它认，注入的 `dismiss`
是弹窗阶段的窄接口——导航调它，它不回调导航。

失败语义逐处不同，搬的时候一处不改：`tap()` / `entry()` / `go()` / `tab()` 找不到只返回假，
`enter()` 抛（调用方没兜底时会空跑一整段，见 #776）；`entry()` 失败留现场但不丢断线。
"""
import re
import time

import wait

# 设置页的焦点窗口签名：同一批小米 / OPPO App 里两种命名并存，只认 Setting 会把
# ThemePreferenceActivity、BrowserPreferencesPage 这类判成「没进去」（#960）。
SETTINGS_MARKS = ("Setting", "Preference")


class Navigator:
    """按文字导航：找得到就点，找不到按各方法的失败语义收尾。

    `screen` 是观测基座（读屏与动作原语都经它），`lost_note` 是丢失记录（`miss` 被这里写、
    被拨动读），`dismiss` 是弹窗阶段的窄接口：挡路的东西先点掉再找。
    """

    def __init__(self, screen, lost_note, dismiss):
        self.screen = screen
        self.lost_note = lost_note
        self.dismiss = dismiss

    def tap(self, text, exact=False, scrolls=6, wait=0.6, quiet=False, seen=None):
        """找到就点。往下翻着找；翻到底没有，就回顶部再找一遍。
        scrolls=0（点底栏/按钮）：不翻页，但 6 秒内边等边关弹窗——应用内更新弹窗要等版本检查
        回来才冒出来，3 秒够不着（#286）。
        quiet=True 时不打印「没找到」：入口探测会自己重试并给出诊断，中间的失败不该各报一行。
        seen：传一个 list，点击前把当时的页面签名放进去。翻页找入口时翻页本身就会改变页面，
        调用方要拿「点击那一刻」的页面当基准，才分得清是翻到了还是换页了（#286）。"""
        screen = self.screen
        if scrolls == 0:
            t0 = time.time()
            while time.time() - t0 < 6.0:
                xy = screen.find(text, exact, edge_ok="tab", nav=True)
                if xy:
                    b = screen.sig(); screen.click(*xy); screen.settle(b, wait + 0.4)
                    if seen is not None:
                        seen.append(b)
                    return True
                if not self.dismiss():
                    time.sleep(0.2)
            if not quiet:
                screen.say(f"  ✗ 没找到「{text}」" + screen.residual_note())
            return False
        if self.lost_note.miss:                         # 本段已经走丢：只看当前这一屏
            xy = screen.find(text, exact, nav=True)
            if xy:
                b = screen.sig(); screen.click(*xy); screen.settle(b, wait + 0.4)
                if seen is not None:
                    seen.append(b)
                self.lost_note.miss = 0
                return True
            self.lost_note.miss += 1
            if not quiet:
                screen.say(f"  ✗ 没找到「{text}」（快速放弃）" + screen.residual_note())
            return False
        for rnd in range(2 if scrolls else 1):
            for i in range(scrolls + 1):
                edge = "tab" if scrolls == 0 else False
                xy = screen.find(text, exact, edge_ok=edge, nav=True)
                if not xy and self.dismiss():
                    xy = screen.find(text, exact, edge_ok=edge, nav=True)
                if xy:
                    b = screen.sig(); screen.click(*xy); screen.settle(b, wait + 0.4)
                    if seen is not None:
                        seen.append(b)
                    return True
                if i < scrolls and not screen.scroll_more():
                    xy = screen.find(text, exact, edge_ok=True, nav=True)
                    if xy:
                        b = screen.sig()
                        if seen is not None:
                            seen.append(b)
                        screen.click(*xy); time.sleep(wait)
                        return True
                    break
            if rnd == 0 and scrolls:
                self.top(scrolls + 2)
        self.lost_note.miss += 1
        if not quiet:
            screen.say(f"  ✗ 没找到「{text}」" + screen.residual_note())
        return False

    def in_settings_page(self):
        """当前页是某个 App 的设置页（焦点类名含 SETTINGS_MARKS 里的任一签名）。点完齿轮用它
        确认真的进去了：点击被吞时页面没换，接着在旧页上找入口会整段失败（#331）。"""
        return any(mark in self.screen.focus() for mark in SETTINGS_MARKS)

    def await_page(self, budget=2.4, poll=0.2, stable=0.15, changed_from=wait.UNSET):
        """等当前页面站稳：读不到文字、或文字还在变时继续等；预算耗尽就照常往下判定。
        Android 17 上设置页渲染更慢，点完齿轮 Activity 已换、内容还是空白（#331）。
        给了 changed_from 就额外要求「换成了别的页」——重试时用它等页面再画一版；
        不给时只等「这一页画完」，点击被吞、旧页仍在会立刻返回，那种情况要在导航处校验 Activity。"""
        return wait.until(self.screen.sig, timeout=budget, poll=poll, stable=stable,
                          changed_from=changed_from, now=time.time, sleep=time.sleep)

    def entry(self, text, scrolls=6, budget=2.4, poll=0.2, tries=2):
        """可选入口：先等页面站稳再找；找不到返回假，让可选入口不中断整段，并留下
        Activity 与结构摘要，区分「没加载完」和「入口确实没了」（#331）。
        一轮没命中不算结论：等页预算摊到几轮，后一轮等「与上一轮不同」的页面，
        页面在预算内又画完一版就还能找回来；预算耗尽才判失败。
        真正该中断的错误照常抛：断线、翻页离开了当前设置页。"""
        seen = wait.UNSET
        for _ in range(tries):
            self.lost_note.miss = 0
            self.await_page(budget / tries, poll, changed_from=seen)
            if self.tap(text, exact=True, scrolls=scrolls, quiet=True):
                self.lost_note.miss = 0
                return True
            self.lost_note.miss = 0
            seen = self.screen.sig()
        self.screen.note_miss(text)
        return False

    def tap_icon(self, expect, area=(0.72, 0.0, 1.0, 0.16), tries=3):
        """点一个没有文字的图标入口，点完要求 expect 里任一文字精确出现在新页面上；
        点开的不是目标页就退回来换下一个（#292）。游戏中心 14.43.3 把「设置」做成「我的」页右上角的齿轮，
        没有文字，按文字找永远找不到。
        用精确匹配：页面上本来就有「隐私政策」之类的文字时，包含匹配会把第一次点击当成成功、不再回退。"""
        screen = self.screen
        expects = (expect,) if isinstance(expect, str) else tuple(expect)
        for x, y in screen.icon_candidates(area)[:tries]:
            focus, sig = screen.focus(), screen.sig()
            screen.click(x, y)
            # 页面慢时多等几轮，别把还没画出来的页面 back() 掉
            if wait.until(lambda: any(screen.find(e, exact=True) for e in expects),
                          timeout=2.4, poll=0.6, now=time.monotonic, sleep=time.sleep):
                screen.say(f"  · 点开了右上角图标（出现「{expects[0]}」）")
                return True
            # 换了页面或弹出浮层：都要回到原页，不能留在别处接着点下一个候选。
            # 退回来也要等页面站稳，否则下一个候选的坐标可能落在跳页动画上。
            if screen.focus() != focus or screen.sig() != sig:
                screen.back()
                time.sleep(0.6)
        screen.say("  · 当前页文字：" + screen.page_text())
        return False

    def enter(self, text, scrolls=0, tries=3):
        """点开一个会换页的入口，并确认页面真的换了：点击常被弹窗淡出动画吞掉，页面没换就再点（#286）。
        基准取「点击那一刻」的页面：入口要翻页才找得到时，翻页本身会改页面，不能当成换页。
        只给会换页的入口用——没换页会再点一次，所以别用在开关行上。
        精确匹配找不到时退回包含匹配（底栏常读作「我的，有新消息」）；换没换页仍由页面变化判定。"""
        screen = self.screen
        exact = True
        if not screen.find(text, exact=True, edge_ok="tab", nav=True):
            exact = False
        for _ in range(tries):
            seen = []
            if not self.tap(text, exact=exact, scrolls=scrolls, seen=seen):
                raise RuntimeError(f"未找到入口「{text}」{screen.residual_note('；')}；当前页：{screen.page_text()}")
            if screen.settle(seen[0], 2.0):
                return
        raise RuntimeError(f"点「{text}」后页面没有变化{screen.residual_note('；')}；当前页：{screen.page_text()}")

    def go(self, text, expect, tries=3, exact=True):
        """点 text，直到 expect 出现在屏幕上（被弹窗吞掉就再点）。
        精确匹配找不到时退回包含匹配：底部标签常读作「我的，有新消息」，精确匹配「我的」返回空（#305）。
        已知边界：落点只核对 expect 此刻在不在屏上，不与点击前的页面比较——expect 本来就在屏上时，
        点击被吞或入口没找到也返回 True。底栏标签改用 tab()，它按屏底带定位。"""
        screen = self.screen
        if exact and not screen.find(text, exact=True, edge_ok="tab", nav=True):
            exact = False
        for _ in range(tries):
            self.tap(text, exact=exact, scrolls=0)
            for _ in range(5):
                if screen.find(expect) or screen.find(expect, edge_ok="tab"):
                    return True
                if not self.dismiss():
                    time.sleep(0.3)
        screen.say(f"  ✗ 点「{text}」后没出现「{expect}」" + screen.residual_note())
        return False

    def tab(self, name, maxwait=6.0):
        """点屏幕底部的标签。
        只在底部带（节点上沿 `top` 超过屏高 85%）里找：标签常读作「未选中,我的」或「我的，有新消息」，
        精确匹配「我的」找不到；退回包含匹配又会先命中内容区里同名的文字（商店有游戏叫
        「我的奇妙小镇」，#305 / #386）。带内按「精确 → 逗号末段等于 → 包含」递进，越靠前越优先。
        6 秒内边等边关弹窗——应用内更新弹窗晚到时会盖住底栏（#286）；点完等页面换掉再返回。
        找不到返回 False，不回退 tap() / go()：失败要响亮，不能静默点到内容区的同名文字。"""
        screen = self.screen
        deadline = time.time() + maxwait
        while True:
            xy = self._tab_xy(name)
            if xy:
                before = screen.sig()
                screen.click(*xy)
                screen.settle(before, 1.0)
                return True
            if time.time() >= deadline:
                screen.say(f"  ✗ 底部没有「{name}」标签")
                return False
            if not self.dismiss():
                time.sleep(0.2)

    def _tab_xy(self, name):
        """底部带内按三层递进找标签，返回点击坐标或 None。"""
        screen = self.screen
        items = screen.texts()
        for hit in (lambda t: t == name,
                    lambda t: re.split(r"[,，]", t)[-1].strip() == name,
                    lambda t: name in t):
            for text, (l, top, r, b), _ in items:
                if top > screen.H * 0.85 and hit(text):
                    return (l + r) // 2, (top + b) // 2
        return None

    def top(self, n=None):
        """回到页顶（翻页回路在 `Screen.scroll_top()`：拨动也要从页顶开始，见 #1094）。
        `n` 是次数上限，不给就一直翻到没有新文字为止。"""
        self.screen.scroll_top(n)
