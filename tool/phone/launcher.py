"""启动与落点：拉起 App、确认前台归属、判落点（ADR-0033、#1041）。

这一段对外可观察的东西最难替代：启动后到底算不算还在目标 App、落点不对时报什么，都是报告者
能看见的。所以判据与现场一起搬：`unknown_focus()` 判「读不出 ≠ 离开」，连续 `FOREIGN_STREAK`
帧外占才停段，启动等待按 `LAUNCH_WAIT` 计、顺延不超过 `LAUNCH_HARD_STOP`；落点不对时
`_landing_note()` / `_launch_evidence()` 仍带「停在哪 / 标题 / 结构」。

观测只经 `Screen`，传输经它背后的 `Connection`；`dismiss` 是注入的窄接口（弹窗与推广位归
`Dismisser`，启动只顺手关一下）。启动会话（`app` / `promoted`）的对象由门面建：`app` 在这里写，
`promoted` 在这里换 App 时清空、另由弹窗侧读写——`promoted_click()` 在 `Dismisser` 里。
"""
import re
import shlex
import time
import xml.etree.ElementTree as ET

import adb_link
import recipe_kit
import wait

from phone.screen import PERMISSION_CONTROLLERS

# 拉起后等目标 App 到前台：只有「确知不是它」的时间计入预算，空焦点是窗口还没画出来，不计（#581）。
LAUNCH_WAIT = 5
# 冷启动过渡能把启动等待顺延到的挂钟上限：与下面「启动后 8 秒仍读不到页面」同一个界，空焦点不能无限等。
LAUNCH_HARD_STOP = 8
# 连续读到别的 App 几次才算离开前台：主题商店 → 主题管理器这类跳包过渡帧只占一两帧（#581）。
FOREIGN_STREAK = 3


def unknown_focus(current):
    """读不出前台（空串）= 窗口还没画出来，不是别的 App 抢了前台（#581）。
    启动等待与权限弹窗两条分支共用这一条口径。"""
    return not current


# 判据词后面只能是结尾或分隔符：底栏读作「我的，有新消息」算命中，「我的应用」不算
EXPECT_TAIL = re.compile(r"[，,、/·\s（(：:]")


def expect_match(word, text):
    """这段文字是不是判据词本身：开头相同，且后面停在分隔符上。"""
    if text == word:
        return True
    return text.startswith(word) and bool(EXPECT_TAIL.match(text[len(word):]))


class Launcher:
    """启动会话：拉起、前台归属与落点判据。

    `session` 是启动会话对象（`app` / `promoted`），`dismiss` 是注入的窄接口：
    关弹窗的退化链归 `Dismisser`，这里只要「顺手关一下」。
    """

    def __init__(self, screen, lost_note, session, dismiss):
        self.screen = screen
        self.conn = screen.conn
        self.lost_note = lost_note
        self.session = session
        self.dismiss = dismiss

    # ---------- 落点：拉起、等页面、给现场 ----------
    def start(self, pkg, activity=None, settle=1.2, foreground=None, expect=None, budget=6.0):
        """拉起 App；之后 settle 秒内冒出来的更新/推荐弹窗顺手点掉。

        expect：预期页面的判据——给一段文字就要看见它，给一组时全部出现才算落在页面上。
        budget：等判据的秒数，恢复前后各给一次。
        有开屏 / 推广页的 App 用它：落在别处时退一次，返回把 App 退到后台就重新拉起一次；
        仍不对就结束本段（#420）。判据由调用方给（如该 App 的底部标签栏文字）。
        空白页不等于推广页，不按返回：慢机型上首屏可能只是还没画完。"""
        self.session.promoted.clear()
        self.session.app = foreground or pkg
        self._launch(pkg, activity, settle, foreground)
        if expect is None or self.expect_page(expect, budget):
            return
        self.screen.say(self._landing_note(expect))
        where = self.screen.focus().split("/", 1)[0]
        if where and where != self.session.app:
            self._launch(pkg, activity, settle, foreground)     # 已经不在目标 App：重新拉起一次
        elif where == self.session.app and self.has_text():
            self.screen.back()                                   # 在目标 App 里却是别的页（开屏 / 推广页）
            time.sleep(0.8)
            gone = self.screen.focus().split("/", 1)[0]
            if gone and gone != self.session.app:
                self._launch(pkg, activity, settle, foreground)
        if self.expect_page(expect, budget):
            self.screen.say(f"  · 退出非预期页面重进后，已落在 {pkg} 的预期页面")
            return
        self.screen.say(self._landing_note(expect))
        raise RuntimeError(f"{pkg} 启动后停在非预期页面，跳过本段")

    def has_text(self):
        """这一屏读得到文字。半截 dump 解析失败时当作空白：空白不等于推广页。"""
        try:
            return bool(self.screen.texts())
        except ET.ParseError:
            return False

    def expect_hits(self, expect):
        """这一屏命中了哪些判据词。给一段文字时按它自己算，不按字符拆。
        允许底栏「我的，有新消息」命中「我的」，不让标题「我的应用」命中（见 expect_match）。"""
        words = [expect] if isinstance(expect, str) else list(expect)
        items = [t for t, _, _ in self.screen.texts()]
        return [w for w in words if any(expect_match(w, t) for t in items)]

    def expect_page(self, expect, timeout=4.0, poll=0.2):
        """等 expect 里的字全部出现在页面上；超时返回假。
        断线照常上抛（blocked 只把「已确认断线」带出来），不当成「页面没认出来」。
        半截 dump 解析失败按「还没画完」处理，下一轮再看。"""
        words = [expect] if isinstance(expect, str) else list(expect)

        def hit():
            try:
                found = self.expect_hits(words)
            except ET.ParseError:
                return None
            return found if len(found) == len(words) else None

        return bool(wait.until(hit, timeout=timeout, poll=poll,
                               now=time.time, sleep=time.sleep, blocked=self.conn.check_alive))

    def _landing_note(self, expect):
        """落点不对时的一条诊断：停在哪个前台、期望看到什么、实际命中了哪些判据，再给页面结构摘要。
        不打印页面文字，与 note_miss 同一风格。"""
        where, detail = self.screen._page_diagnosis()
        words = [expect] if isinstance(expect, str) else list(expect)
        try:
            hits = self.expect_hits(words)
        except ET.ParseError:
            hits = []
        missed = [w for w in words if w not in hits]
        note = f"  · 启动后没落在预期页面：停在 {where}；期望看到「{'、'.join(words)}」"
        if missed:
            note += f"，没看到「{'、'.join(missed)}」"
        return f"{note}；{detail}"

    def _launch_evidence(self, seizer="", frames=0):
        """启动两条短路的现场：当前落点 + 页面结构摘要，能确知抢夺者时与落点分开写（#940）。

        抛错那一刻前台可能已经被抢回目标包，轮询里记下的那一帧才是抢夺者。门槛与停段同档
        （同一个包连续 FOREIGN_STREAK 帧）：一两帧过渡、空焦点交替都不算确知，不写也不伪造。"""
        where, detail = self.screen._page_diagnosis()
        if seizer and frames >= FOREIGN_STREAK and seizer.split("/", 1)[0] != where.split("/", 1)[0]:
            return f"（被 {seizer} 抢了前台，连续 {frames} 帧；当前停在 {where}；{detail}）"
        return f"（停在 {where}；{detail}）"

    def _launch(self, pkg, activity, settle, foreground):
        """发启动命令、等前台回到目标 App、顺手关掉可识别的弹窗。落点对不对由 start() 判。"""
        self.conn.check_alive()
        self.lost_note.miss = 0
        if activity:
            # 页面名可能带 $（vivo `.Settings$AdAndPrivacyActivityForOsTwo`）：交给 shell 前整串引用一次。
            # 脚本与 entries.Direct 保持字面量，used_by() 才认得出来源（#667）
            result = self.conn.reader.shell(f"am start -f 0x10008000 -n {shlex.quote(pkg + '/' + activity)}")
        else:
            self.conn._u2(self.conn.reader.app_stop, pkg)
            result = self.conn.reader.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        if result.exit_code or re.search(r"Error|Exception|No activities found|monkey aborted", result.output, re.I):
            # 同品牌参考脚本里的 App 本机可能没装或换了包名（#87 #165），说清楚，别报成打开失败。
            pm = self.conn.reader.shell(f"pm path {pkg}").output
            if "package:" not in pm:
                # adb 断开时 pm path 也一样没有输出：先确认手机还在不在，
                # 别把断连报成「本机没有安装」，后面的段也据此快速跳过（#293）。
                if adb_link.client_gone(result.output + pm) or adb_link.lib_gone(result.output + pm) \
                        or adb_link.detached(self.conn.serial):
                    self.conn.lost = True
                    raise adb_link.lost((result.output or pm).strip())
                # 包确实不在：这一页在这台机上本来就没有，按跳过收尾，别记成未完成（#908）。
                raise recipe_kit.MissingPackage(f"本机没有安装 {pkg}")
            raise RuntimeError(f"无法打开 {pkg}：{result.output.strip()[-250:]}")
        expected = foreground or pkg
        started = time.monotonic()
        last = started
        waited = 0.0                       # 只有确知「不是目标 App」的时间才计入启动等待
        # 最后读到的那一帧外来前台与它同一个包连读的帧数：抛错时前台可能已被抢回目标包（#940）。
        # 读空只打断 seizer_run（这个包当前的连读），不抹掉 seizer / seizer_frames：
        # 空焦点只是「读不出」，之前确知过的那一段仍是唯一的线索。
        seizer, seizer_frames, seizer_run = "", 0, 0
        while self.screen.focus().split("/", 1)[0] != expected:
            focus = self.screen.focus()
            current = focus.split("/", 1)[0]
            now = time.monotonic()
            if not unknown_focus(current):
                waited += now - last       # 空焦点是窗口还没画出来，顺延到 LAUNCH_HARD_STOP 为止
            last = now
            if current in PERMISSION_CONTROLLERS:
                self.dismiss()
            if unknown_focus(current) or current in PERMISSION_CONTROLLERS or current == expected:
                seizer_run = 0
            else:
                seizer_run = seizer_run + 1 if focus == seizer else 1
                seizer, seizer_frames = focus, seizer_run
            if waited >= LAUNCH_WAIT or now >= started + LAUNCH_HARD_STOP:
                # 带上落点（谁抢了前台、页面长什么样）：没有包名就分不清该加白名单还是改判据（#547）。
                raise RuntimeError(f"{pkg} 没有进入前台，跳过本段{self._launch_evidence(seizer, seizer_frames)}")
            time.sleep(0.2)

        def leave_foreground(seizer="", frames=0):
            # 同 #547：这条报错命中 79 份上报、51 个型号，缺的从来都是「是谁盖住了」。
            raise RuntimeError(f"{pkg} 启动后离开前台，停止本段以免操作其他 App"
                               f"{self._launch_evidence(seizer, frames)}")

        streak = 0                          # 连续读到别的 App 的帧数，读到目标包或读空就清零
        seizer, seizer_frames, seizer_run = "", 0, 0    # 「被谁抢了前台」的记录，从这一阶段重新起算
        def check_foreground():
            """确认前台：落在目标 App 返回真（这一屏可以读、可以关弹窗），读不出或别的 App 返回假。"""
            nonlocal streak, seizer, seizer_frames, seizer_run
            focus = self.screen.focus()
            current = focus.split("/", 1)[0]
            # 权限申请可能在首页已出现后才弹出，也只能拒绝；不在其他 App 上找关闭按钮。
            if current in PERMISSION_CONTROLLERS:
                give_up_at = time.monotonic() + 3
                while current in PERMISSION_CONTROLLERS or unknown_focus(current):
                    if time.monotonic() >= give_up_at:
                        break
                    if current and not self.dismiss():
                        break
                    time.sleep(.2)
                    focus = self.screen.focus()
                    current = focus.split("/", 1)[0]
                if current in PERMISSION_CONTROLLERS:      # 等满 3 秒仍在：确知被它占住
                    leave_foreground()
            if unknown_focus(current):
                streak = 0
                seizer_run = 0
                return False
            if current == expected:
                streak = 0
                seizer_run = 0
                return True
            streak += 1
            seizer_run = seizer_run + 1 if focus == seizer else 1
            seizer, seizer_frames = focus, seizer_run
            if streak >= FOREIGN_STREAK:
                leave_foreground(seizer, seizer_frames)
            return False

        # 旧版商店冷启动可能暂时没有可读文字；空白不等于广告，不能盲按返回退出 App。
        t = time.time()
        while time.time() - t < LAUNCH_HARD_STOP:
            if check_foreground():         # 不在别的 App 上读页面、关弹窗
                if self.screen.texts():    # 一两个标签也可能是正常首页
                    break
                self.dismiss()             # 仅尝试可识别的关闭 / 拒绝按钮
            time.sleep(.2)
        else:
            raise RuntimeError(f"{pkg} 启动后 {LAUNCH_HARD_STOP} 秒仍读不到页面，停止本段；请确认首页已加载后重试")

        t = time.time()                    # 首屏加载较慢时，也要给引导/更新弹窗留下处理时间
        while time.time() - t < settle:
            if check_foreground():
                self.dismiss()
            time.sleep(0.4)
        # 收尾至少再读一次：最后一拍被别的 App 抢了前台也当启动成功的话，后面的段会对着它操作。
        # 那一帧不判，读到别的 App 就把它攒够才停；读空或回到目标包就结束（跳包过渡会自己清零）。
        while True:
            if check_foreground() or not streak:
                break
            time.sleep(.2)
