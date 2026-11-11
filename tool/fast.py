#!/usr/bin/env python3
"""去广告快速引擎（uiautomator2，读屏 ~0.03 秒）。

命令行：
  fast.py -s SERIAL ls                 列当前屏：文字 + 开关状态
  fast.py -s SERIAL check              检查读屏服务，不点击、不输出页面内容
  fast.py -s SERIAL tap 文字 [文字…]    依次点（找不到会往下翻着找）
  fast.py -s SERIAL off [保留词,…]      当前列表里开着的开关全关（保留词命中的不动），一路翻到底
  fast.py -s SERIAL scan                 只读：翻到底列出所有开关
  fast.py -s SERIAL only 词,词…         只关标题含这些词的开关
  fast.py -s SERIAL run 机型脚本.py         跑一个品牌机型脚本
在脚本里：from fast import Phone
"""
import os, re, sys, time
# 显式 re-export：测试与机型脚本用 `fast.ET.fromstring` 解析 dump（模块级名字原地不动）。
from xml.etree import ElementTree as ET  # noqa: F401 - 显式 re-export：`fast.ET` 是模块级名字
from stdio import use_utf8_console

use_utf8_console()
# 两个基座已搬进 tool/phone/（ADR-0033）。读屏库与 adb 库继续从这里显式 re-export：
# 测试与机型脚本拿它们取异常类型（`fast.u2.exceptions.X`），与 `Phone` 是同一个出口。
from phone.connection import Connection
from phone.connection import adbutils as adbutils
from phone.connection import pause_point as pause_point
from phone.connection import reader_failure as reader_failure
from phone.connection import u2 as u2
from phone.connection import _shell_transport as _shell_transport
from phone.screen import CONFIRM as CONFIRM
from phone.screen import Screen
from phone.session import ChannelSession, LaunchSession, LostNote
import adb_link
import backups
import events
import recipe_kit
import wait
from reader import Reader
from row import bounds, is_switch, switches_in
from row import switch_row as switch_row
# 显式 re-export：机型脚本从 fast 取这个判据（与 bounds 同一处引用）。
from row import icon_hit as icon_hit
# 极性词表定义在 polarity.py（文档生成器也要同一份，见 #693），这里显式 re-export，
# `from fast import want_state` 的调用点一行都不用改。
from polarity import AD_WORDS as AD_WORDS, NEG_PREFIX as NEG_PREFIX, TRACK_WORDS as TRACK_WORDS
from polarity import want_state as want_state

DISMISS = ("以后再说", "暂不更新", "暂不", "取消", "我知道了", "跳过", "禁止", "不再提示", "不同意")
# 应用内更新弹窗的标题（主题商店 17.22.0beta2 是「检测到新版本」，#286）。它通常把更新说明放进可滚动容器，
# 只按标题认，不按按钮认：单个「取消」在正常设置面板里也有。
UPDATE_TITLE = re.compile(r"检测到新版本|发现新版本|版本更新提示")
# 设置页的焦点窗口签名：同一批小米 / OPPO App 里两种命名并存，只认 Setting 会把
# ThemePreferenceActivity、BrowserPreferencesPage 这类判成「没进去」（#960）。
SETTINGS_MARKS = ("Setting", "Preference")


# 输入框：荣耀 MagicOS 10（PNM-AN10 10.0.0.102）设置搜索框是 AutoCompleteTextView，类名里没有 EditText
EDIT = re.compile(r"EditText|AutoCompleteTextView")


class ScreenLocked(RuntimeError):
    """手机锁屏了：调用方等机主解锁，或停下整批，不逐项报同一个原因。"""


# 启动与落点已随 `start()` 搬进 tool/phone/launcher.py（#1041），这里显式 re-export：
# `fast.unknown_focus` / `LAUNCH_WAIT` 这些模块级名字与 `tests/` 一行都不用改。
from phone.launcher import EXPECT_TAIL as EXPECT_TAIL
from phone.launcher import FOREIGN_STREAK as FOREIGN_STREAK
from phone.launcher import LAUNCH_HARD_STOP as LAUNCH_HARD_STOP, LAUNCH_WAIT as LAUNCH_WAIT
from phone.launcher import PERMISSION_CONTROLLERS as PERMISSION_CONTROLLERS
from phone.launcher import Launcher
from phone.launcher import expect_match as expect_match, unknown_focus as unknown_focus


from phone.toggler import CONFIRM_WAIT as CONFIRM_WAIT, CONFIRM_SETTLE as CONFIRM_SETTLE
from phone.toggler import GREYED as GREYED, MISSED as MISSED, REACHED as REACHED, VANISHED as VANISHED
from phone.toggler import SwitchPlan as SwitchPlan, in_band as in_band
from phone.toggler import match_key as match_key, match_rank as match_rank
from phone.toggler import greyed_titles as greyed_titles, plan_switches as plan_switches
from phone.toggler import pick_retry_rows as pick_retry_rows, pick_title_rows as pick_title_rows
from phone.toggler import readback as readback, still_greyed as still_greyed, still_open as still_open
from phone.toggler import Toggler
# 拨动的常量与纯函数已随 `off()` 搬进 tool/phone/toggler.py（#1040），这里显式 re-export：
# `from fast import plan_switches`、`fast.SwitchPlan` 与 `tests/test_switch_plan.py` 一行都不用改。


class Phone:
    """门面：只做转发与组合，公开名字一个不改（ADR-0033）。

    两个基座与拨动会话已搬进 `tool/phone/`：`Connection`（连接与生命周期）、`Screen`（观测、
    视口几何、动作原语）与 `Toggler`（整页拨动）。其余四个阶段仍在本文件，按 #1041–#1044
    逐步搬走。
    """

    def __init__(self, serial, log=True, reader: Reader | None = None):
        self.conn = Connection(serial, log=log, reader=reader)
        self.screen = Screen(self.conn)
        # 三个跨阶段会话各有对象；门面只转发，写者与读者写在对象接口上（#1039）
        self.lost_note = LostNote()
        self.launch_session = LaunchSession()
        self.channel_session = ChannelSession()
        self.toggler = Toggler(self.screen, self.lost_note)
        # 启动阶段注入弹窗侧的窄接口：`dismiss()` 还没搬（#1043 才走），这里先交门面的那一份。
        self.launcher = Launcher(self.screen, self.lost_note, self.launch_session, self.dismiss)
        self.conn.check_input()

    # ---------- 转发：连接（Connection）与观测（Screen） ----------
    # 显式属性 + 赋值器，不用 `__getattr__` 兜底：搬漏的方法必须当场 AttributeError（ADR-0033）。
    @property
    def reader(self):
        """读屏 adapter：引擎看手机的唯一接口（ADR-0001），实体归 `Connection`。"""
        return self.conn.reader

    @reader.setter
    def reader(self, value):
        self.conn.reader = value

    @property
    def d(self):
        """读屏 adapter 的历史名字：recipes（`p.d.shell`）与测试用它，实体是同一个 `reader`。"""
        return self.reader

    @d.setter
    def d(self, value):
        self.reader = value

    @property
    def link(self):
        """adb 连接与断线判定，状态归 `Connection`，这里只是读写它的一个别名。"""
        return self.conn.link

    @link.setter
    def link(self, value):
        self.conn.link = value

    @property
    def serial(self):
        """串号归 Connection：每条命令都要带 -s，不存在「手机对象认一台、命令发给另一台」。"""
        return self.conn.serial

    @serial.setter
    def serial(self, value):
        self.conn.serial = value

    @property
    def lost(self):
        """本轮是否已确认断线；状态归 Connection，这里只是读写它的一个别名。"""
        return self.conn.lost

    @lost.setter
    def lost(self, value):
        self.conn.lost = value

    @property
    def log(self):
        return self.conn.log

    @log.setter
    def log(self, value):
        self.conn.log = value

    @property
    def pause_at_lock_check(self):
        return self.conn.pause_at_lock_check

    @pause_at_lock_check.setter
    def pause_at_lock_check(self, value):
        self.conn.pause_at_lock_check = value

    @property
    def W(self):
        return self.screen.W

    @W.setter
    def W(self, value):
        self.screen.W = value

    @property
    def H(self):
        return self.screen.H

    @H.setter
    def H(self, value):
        self.screen.H = value

    @property
    def systemui_text(self):
        """读屏时是否算上 com.android.systemui 的文字：归观测基座，`texts()` 在读它。"""
        return self.screen.systemui_text

    @systemui_text.setter
    def systemui_text(self, value):
        self.screen.systemui_text = value

    # ---------- 转发：三个跨阶段会话（LostNote / LaunchSession / ChannelSession） ----------
    # 谁在什么时候写它们，写在 `tool/phone/session.py` 的类 docstring 上，这里只给归属。
    @property
    def miss(self):
        """本段已经没找到几次。归 `LostNote`。"""
        return self.lost_note.miss

    @miss.setter
    def miss(self, value):
        self.lost_note.miss = value

    @property
    def missed(self):
        """本次没拨到目标态的 (页面, 标题)。归 `LostNote`。"""
        return self.lost_note.missed

    @missed.setter
    def missed(self, value):
        self.lost_note.missed = value

    @property
    def app(self):
        """最近一次 start 拉起的目标 App。归 `LaunchSession`。"""
        return self.launch_session.app

    @app.setter
    def app(self, value):
        self.launch_session.app = value

    @property
    def promoted(self):
        """点过才发现是推广位的 ✕。归 `LaunchSession`。"""
        return self.launch_session.promoted

    @promoted.setter
    def promoted(self, value):
        self.launch_session.promoted = value

    @property
    def vivo_seen(self):
        """见过 vivo 的通知页。归 `ChannelSession`。"""
        return self.channel_session.vivo_seen

    @vivo_seen.setter
    def vivo_seen(self, value):
        self.channel_session.vivo_seen = value

    @property
    def skeleton_sigs(self):
        """本次运行已上报的骨架布局。归 `ChannelSession`。"""
        return self.channel_session.skeleton_sigs

    @skeleton_sigs.setter
    def skeleton_sigs(self, value):
        self.channel_session.skeleton_sigs = value

    @property
    def skeleton_count(self):
        """本次运行已上报的骨架份数。归 `ChannelSession`。"""
        return self.channel_session.skeleton_count

    @skeleton_count.setter
    def skeleton_count(self, value):
        self.channel_session.skeleton_count = value

    @property
    def mismatch_probes(self):
        """本次运行已补的 MISMATCH 判据读数。归 `ChannelSession`。"""
        return self.channel_session.mismatch_probes

    @mismatch_probes.setter
    def mismatch_probes(self, value):
        self.channel_session.mismatch_probes = value

    def _resilient_shell(self, *args, **kwargs):
        return self.conn._resilient_shell(*args, **kwargs)

    def _u2(self, fn, *a, **k):
        return self.conn._u2(fn, *a, **k)

    def check_alive(self):
        self.conn.check_alive()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def say(self, *a):
        self.conn.say(*a)

    def locked(self):
        return self.conn.locked()

    def wait_unlocked(self, timeout=wait.UNLOCK_TIMEOUT):
        return self.conn.wait_unlocked(timeout)

    # ---------- 采样：读屏、页面状态与签名 ----------
    # 区内的 scroll_more 会动屏幕（翻页），不是纯读。
    def tree(self):
        return self.screen.tree()

    def focus(self):
        return self.screen.focus()

    def texts(self, root=None):
        return self.screen.texts(root)

    def page_text(self):
        return self.screen.page_text()

    def on_screen(self, n):
        return self.screen.on_screen(n)

    def switches(self, root=None):
        return self.screen.switches(root)

    def switch_rows(self, root=None):
        return self.screen.switch_rows(root)

    def sig(self):
        return self.screen.sig()

    def scroll_more(self):
        """翻一页；翻完没出现新文字（到底、回弹）返回 False。"""
        return self.screen.scroll_more()

    def ls(self):
        self.screen.ls()

    # ---------- 页面诊断 ----------
    def _page_diagnosis(self):
        return self.screen._page_diagnosis()

    def note_miss(self, text):
        self.screen.note_miss(text)

    def page_evidence(self, titles=()):
        return self.screen.page_evidence(titles)

    def icon_candidates(self, area=(0.72, 0.0, 1.0, 0.16)):
        return self.screen.icon_candidates(area)

    # ---------- 四个动作原语：后续阶段一律经它们动作 ----------
    def click(self, x, y):
        self.screen.click(x, y)

    def back(self, n=1):
        self.screen.back(n)

    def settle(self, before, maxwait=0.8):
        return self.screen.settle(before, maxwait)

    def find(self, text, exact=False, root=None, edge_ok=False, nav=False):
        return self.screen.find(text, exact, root, edge_ok, nav)

    def scroll(self, frac=0.45, up=False):
        """按下-移动-停 0.12 秒-松开：没有惯性，翻多少是多少，约 0.45 秒。"""
        self.screen.scroll(frac, up)

    def top(self, n=4):
        for _ in range(n):
            if not any(x.get("scrollable") == "true" and self.on_screen(x) for x in self.tree().iter("node")):
                break
            focus = self.focus()
            before = {t for t, _, _ in self.texts()}
            self.scroll(0.58, up=True)
            if self.focus() != focus:
                raise RuntimeError("回到页顶时离开了当前设置页，停止本段")
            if {t for t, _, _ in self.texts()} <= before:
                break

    CLOSE = re.compile(r"close|关闭|跳过|skip|cancel|dismiss|iv_x\b|btn_x\b", re.I)
    # 描述精确读作「返回」的不是弹窗的 ✕，是浮层/页面自己的返回键：点了是导航，会把刚打开的
    # 浮层收起来。vivo 浏览器菜单的 iv_back_cancel 就长这样，id 里的 cancel 本来会命中 CLOSE（#753）。
    BACK_LABELS = {"返回", "back"}

    def dismiss(self):
        """挡路的更新/推荐/权限弹窗：点拒绝类按钮（不替用户同意任何东西）。
        纯图片的广告弹窗没有文字，只有一个 ✕ 图标：找 desc/id 里带 close 的可点元素。
        返回非空表示这次关掉了东西，返回前已经等过界面过渡（0.4~0.6 秒），调用方不必再等；
        返回 None 表示这次没关掉任何东西（推广位的 ✕ 点过也已退回原 App），
        调用方按自己的节奏等待或重试。轮询处写成 `if not self.dismiss(): time.sleep(x)`：
        刚关掉就立刻重读，什么都没关才按间隔再读。"""
        root = self.tree()
        # Android 运行时权限页只点明确的拒绝按钮，不替用户授予权限或修改“不再询问”。
        if (any(n.get("package") in PERMISSION_CONTROLLERS for n in root.iter("node"))
                and self.focus().split("/", 1)[0] in PERMISSION_CONTROLLERS):
            for n in root.iter("node"):
                if (n.get("package") in PERMISSION_CONTROLLERS and "Button" in n.get("class", "")
                        and n.get("text") in ("拒绝", "不允许", "Deny", "Don't allow") and self.on_screen(n)):
                    l, t, r, b = bounds(n)
                    self.click((l+r)//2, (t+b)//2); time.sleep(.4)
                    self.say("  · 已拒绝运行时权限申请，未授予权限")
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

        # 设置页里含「关闭」的说明行本身可能就是开关，点它等于替用户拨一次（#378）。
        # 按候选子树判定而不是整屏——ColorOS 17 隐私页的浮层 ✕ 盖在带开关的页面上，仍然要能点。
        def is_switch_row(n):
            return is_switch(n) or bool(switches_in(n, self.on_screen))

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
                if 0 < r - l < self.W * 0.3 and 0 < b - t < self.H * 0.12 and self.on_screen(n):
                    if self._promoted_click((l + r) // 2, (t + b) // 2, key.strip()):
                        return None         # 没关掉弹窗，调用方按「这次什么也没关」处理
                    self.say(f"  · 弹窗点了 ✕（{key.strip()[:40]}）")
                    return "✕"
        tx = self.texts(root)

        def refuse():
            for w in DISMISS:
                for t, (l, tp, r, b), _ in tx:
                    if t == w:
                        self.click((l + r) // 2, (tp + b) // 2); time.sleep(0.6)
                        self.say(f"  · 弹窗点了「{w}」")
                        return w
            return None

        # 更新弹窗先认，且不看有没有滚动列表：主题商店把更新说明放在可滚动容器里，下面的守卫会漏掉它（#286）；
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

    def _promoted_click(self, x, y, key):
        return self.launcher.promoted_click(x, y, key)

    def tap(self, text, exact=False, scrolls=6, wait=0.6, quiet=False, seen=None):
        """找到就点。往下翻着找；翻到底没有，就回顶部再找一遍。
        scrolls=0（点底栏/按钮）：不翻页，但 6 秒内边等边关弹窗——应用内更新弹窗要等版本检查
        回来才冒出来，3 秒够不着（#286）。
        quiet=True 时不打印「没找到」：入口探测会自己重试并给出诊断，中间的失败不该各报一行。
        seen：传一个 list，点击前把当时的页面签名放进去。翻页找入口时翻页本身就会改变页面，
        调用方要拿「点击那一刻」的页面当基准，才分得清是翻到了还是换页了（#286）。"""
        if scrolls == 0:
            t0 = time.time()
            while time.time() - t0 < 6.0:
                xy = self.find(text, exact, edge_ok="tab", nav=True)
                if xy:
                    b = self.sig(); self.click(*xy); self.settle(b, wait + 0.4)
                    if seen is not None:
                        seen.append(b)
                    return True
                if not self.dismiss():
                    time.sleep(0.2)
            if not quiet:
                self.say(f"  ✗ 没找到「{text}」" + self.residual_note())
            return False
        if self.miss:                                   # 本段已经走丢：只看当前这一屏
            xy = self.find(text, exact, nav=True)
            if xy:
                b = self.sig(); self.click(*xy); self.settle(b, wait + 0.4)
                if seen is not None:
                    seen.append(b)
                self.miss = 0
                return True
            self.miss += 1
            if not quiet:
                self.say(f"  ✗ 没找到「{text}」（快速放弃）" + self.residual_note())
            return False
        for rnd in range(2 if scrolls else 1):
            for i in range(scrolls + 1):
                edge = "tab" if scrolls == 0 else False
                xy = self.find(text, exact, edge_ok=edge, nav=True)
                if not xy and self.dismiss():
                    xy = self.find(text, exact, edge_ok=edge, nav=True)
                if xy:
                    b = self.sig(); self.click(*xy); self.settle(b, wait + 0.4)
                    if seen is not None:
                        seen.append(b)
                    return True
                if i < scrolls and not self.scroll_more():
                    xy = self.find(text, exact, edge_ok=True, nav=True)
                    if xy:
                        b = self.sig()
                        if seen is not None:
                            seen.append(b)
                        self.click(*xy); time.sleep(wait)
                        return True
                    break
            if rnd == 0 and scrolls:
                self.top(scrolls + 2)
        self.miss += 1
        if not quiet:
            self.say(f"  ✗ 没找到「{text}」" + self.residual_note())
        return False

    def in_settings_page(self):
        """当前页是某个 App 的设置页（焦点类名含 SETTINGS_MARKS 里的任一签名）。点完齿轮用它
        确认真的进去了：点击被吞时页面没换，接着在旧页上找入口会整段失败（#331）。"""
        return any(mark in self.focus() for mark in SETTINGS_MARKS)

    def await_page(self, budget=2.4, poll=0.2, stable=0.15, changed_from=wait.UNSET):
        """等当前页面站稳：读不到文字、或文字还在变时继续等；预算耗尽就照常往下判定。
        Android 17 上设置页渲染更慢，点完齿轮 Activity 已换、内容还是空白（#331）。
        给了 changed_from 就额外要求「换成了别的页」——重试时用它等页面再画一版；
        不给时只等「这一页画完」，点击被吞、旧页仍在会立刻返回，那种情况要在导航处校验 Activity。"""
        return wait.until(self.sig, timeout=budget, poll=poll, stable=stable,
                          changed_from=changed_from, now=time.time, sleep=time.sleep)

    def entry(self, text, scrolls=6, budget=2.4, poll=0.2, tries=2):
        """可选入口：先等页面站稳再找；找不到返回假，让可选入口不中断整段，并留下
        Activity 与结构摘要，区分「没加载完」和「入口确实没了」（#331）。
        一轮没命中不算结论：等页预算摊到几轮，后一轮等「与上一轮不同」的页面，
        页面在预算内又画完一版就还能找回来；预算耗尽才判失败。
        真正该中断的错误照常抛：断线、翻页离开了当前设置页。"""
        seen = wait.UNSET
        for _ in range(tries):
            self.miss = 0
            self.await_page(budget / tries, poll, changed_from=seen)
            if self.tap(text, exact=True, scrolls=scrolls, quiet=True):
                self.miss = 0
                return True
            self.miss = 0
            seen = self.sig()
        self.note_miss(text)
        return False

    def tap_icon(self, expect, area=(0.72, 0.0, 1.0, 0.16), tries=3):
        """点一个没有文字的图标入口，点完要求 expect 里任一文字精确出现在新页面上；
        点开的不是目标页就退回来换下一个（#292）。游戏中心 14.43.3 把「设置」做成「我的」页右上角的齿轮，
        没有文字，按文字找永远找不到。
        用精确匹配：页面上本来就有「隐私政策」之类的文字时，包含匹配会把第一次点击当成成功、不再回退。"""
        expects = (expect,) if isinstance(expect, str) else tuple(expect)
        for x, y in self.icon_candidates(area)[:tries]:
            focus, sig = self.focus(), self.sig()
            self.click(x, y)
            # 页面慢时多等几轮，别把还没画出来的页面 back() 掉
            if wait.until(lambda: any(self.find(e, exact=True) for e in expects),
                          timeout=2.4, poll=0.6, now=time.monotonic, sleep=time.sleep):
                self.say(f"  · 点开了右上角图标（出现「{expects[0]}」）")
                return True
            # 换了页面或弹出浮层：都要回到原页，不能留在别处接着点下一个候选。
            # 退回来也要等页面站稳，否则下一个候选的坐标可能落在跳页动画上。
            if self.focus() != focus or self.sig() != sig:
                self.back()
                time.sleep(0.6)
        self.say("  · 当前页文字：" + self.page_text())
        return False

    def enter(self, text, scrolls=0, tries=3):
        """点开一个会换页的入口，并确认页面真的换了：点击常被弹窗淡出动画吞掉，页面没换就再点（#286）。
        基准取「点击那一刻」的页面：入口要翻页才找得到时，翻页本身会改页面，不能当成换页。
        只给会换页的入口用——没换页会再点一次，所以别用在开关行上。
        精确匹配找不到时退回包含匹配（底栏常读作「我的，有新消息」）；换没换页仍由页面变化判定。"""
        exact = True
        if not self.find(text, exact=True, edge_ok="tab", nav=True):
            exact = False
        for _ in range(tries):
            seen = []
            if not self.tap(text, exact=exact, scrolls=scrolls, seen=seen):
                raise RuntimeError(f"未找到入口「{text}」{self.residual_note('；')}；当前页：{self.page_text()}")
            if self.settle(seen[0], 2.0):
                return
        raise RuntimeError(f"点「{text}」后页面没有变化{self.residual_note('；')}；当前页：{self.page_text()}")

    def go(self, text, expect, tries=3, exact=True):
        """点 text，直到 expect 出现在屏幕上（被弹窗吞掉就再点）。
        精确匹配找不到时退回包含匹配：底部标签常读作「我的，有新消息」，精确匹配「我的」返回空（#305）。
        已知边界：落点只核对 expect 此刻在不在屏上，不与点击前的页面比较——expect 本来就在屏上时，
        点击被吞或入口没找到也返回 True。底栏标签改用 tab()，它按屏底带定位。"""
        if exact and not self.find(text, exact=True, edge_ok="tab", nav=True):
            exact = False
        for _ in range(tries):
            self.tap(text, exact=exact, scrolls=0)
            for _ in range(5):
                if self.find(expect) or self.find(expect, edge_ok="tab"):
                    return True
                if not self.dismiss():
                    time.sleep(0.3)
        self.say(f"  ✗ 点「{text}」后没出现「{expect}」" + self.residual_note())
        return False

    def tab(self, name, maxwait=6.0):
        """点屏幕底部的标签。
        只在底部带（节点上沿 `top` 超过屏高 85%）里找：标签常读作「未选中,我的」或「我的，有新消息」，
        精确匹配「我的」找不到；退回包含匹配又会先命中内容区里同名的文字（商店有游戏叫
        「我的奇妙小镇」，#305 / #386）。带内按「精确 → 逗号末段等于 → 包含」递进，越靠前越优先。
        6 秒内边等边关弹窗——应用内更新弹窗晚到时会盖住底栏（#286）；点完等页面换掉再返回。
        找不到返回 False，不回退 tap() / go()：失败要响亮，不能静默点到内容区的同名文字。"""
        deadline = time.time() + maxwait
        while True:
            xy = self._tab_xy(name)
            if xy:
                before = self.sig()
                self.click(*xy)
                self.settle(before, 1.0)
                return True
            if time.time() >= deadline:
                self.say(f"  ✗ 底部没有「{name}」标签")
                return False
            if not self.dismiss():
                time.sleep(0.2)

    def _tab_xy(self, name):
        """底部带内按三层递进找标签，返回点击坐标或 None。"""
        items = self.texts()
        for hit in (lambda t: t == name,
                    lambda t: re.split(r"[,，]", t)[-1].strip() == name,
                    lambda t: name in t):
            for text, (l, top, r, b), _ in items:
                if top > self.H * 0.85 and hit(text):
                    return (l + r) // 2, (top + b) // 2
        return None

    # ---------- 拨动（Toggler） ----------
    # 整页拨动与确认框都归拨动会话；确认框的认法与残留确认在观测基座（`Screen.confirm_target`），
    # 导航侧失败时那句残留提示直接问基座，不经过拨动（ADR-0033）。
    @property
    def safe_mode(self):
        """安全模式（参考脚本 / 录制版本不符）：只关点名的开关，不做整页全关。归拨动会话。"""
        return self.toggler.safe_mode

    @safe_mode.setter
    def safe_mode(self, value):
        self.toggler.safe_mode = value

    @property
    def changed(self):
        """本次关掉的 (页面, 标题)。转发本体：`p.changed.append(...)` 直接改它。"""
        return self.toggler.changed

    @changed.setter
    def changed(self, value):
        self.toggler.changed = value

    def confirm(self):
        """开关后弹确认框就点确认类按钮，认出即返回按钮文字；没有弹窗返回 None。"""
        return self.toggler.confirm()

    def residual_confirm(self, root=None):
        """屏上还挂着没被点掉的确认框时返回确认按钮的文字，没有返回 None。只读不点（#557）。"""
        return self.screen.residual_confirm(root)

    def residual_note(self, sep="——", root=None):
        """查找失败时挂在说明后面的那句「屏上还挂着没点掉的确认框「X」」；没有确认框时是空串。"""
        return self.screen.residual_note(sep, root)

    def off(self, keep=(), only=None, page="", max_screens=40):
        """当前列表：关掉开着的开关（判定与补点见 `Toggler.off()`）。"""
        return self.toggler.off(keep, only, page, max_screens)

    # ---------- 设置搜索：输入框、打字、按关键词进页 ----------
    def focused_text(self):
        for n in self.tree().iter("node"):
            if n.get("focused") == "true" and EDIT.search(n.get("class") or "") and self.on_screen(n):
                return n.get("text") or ""
        return None

    def type_text(self, kw, timeout=4.0):
        """往当前输入框打字。部分机型（小米 HyperOS 设置搜索）用 setText 会卡住、一直打「%」：
        加超时，打完核对；不对就清掉、改用剪贴板粘贴；还不对就返回 False，不卡住。
        失败时不退场：离开搜索页只由调用方的 `_leave_search()` 做（#639）。"""
        if not self.edit_ready():
            return False

        def attempt(fn):
            try:
                fn()
            except Exception:
                return False
            time.sleep(0.4)
            return (self.focused_text() or "").strip() == kw

        def clear():
            if not self.edit_ready():
                return
            try:
                self.reader.jsonrpc.clearTextField(selector, http_timeout=timeout)
            except Exception:
                pass

        # 直接对已确认的输入框发有超时的 RPC，不启动无法取消的后台线程。
        # 旧线程超时后仍会等控件出现，可能在下一页补打文字；也不能退回任意 focused 节点（键盘也有）。
        selector = self.reader(classNameMatches=r".*(EditText|AutoCompleteTextView)$", focused=True).selector
        def set_text():
            self.reader.jsonrpc.setText(selector, kw, http_timeout=timeout)
        if attempt(set_text):
            return True
        if not self.edit_ready():
            return False
        clear()
        def paste():
            self.reader.jsonrpc.setClipboard(None, kw, http_timeout=timeout)
            self.reader.shell("input keyevent KEYCODE_PASTE", timeout=timeout)
        if attempt(paste):
            return True
        clear()
        return False

    BOX = re.compile(r"^搜索.{0,6}设置|^Search settings", re.I)

    def edit_ready(self):
        """搜索页打开了：屏幕上有获得焦点的输入框。"""
        for n in self.tree().iter("node"):
            if EDIT.search(n.get("class") or "") and n.get("focused") == "true" and self.on_screen(n):
                return True
        return False

    # 直接打开系统设置搜索页的动作（#650）：打得开就省掉「设置首页 → 找框 → 点框 → 等输入框」。
    # 没有这个动作的系统 am start 当场报解析不到（退出码非零），回到老路，不额外等。
    SEARCH_ACTION = "oplus.intent.action.settings.MAIN_SEARCH"        # ColorOS（OPPO / 一加 / 真我）

    def _search_page(self):
        res = self.reader.shell(f"am start -f 0x10008000 -a {self.SEARCH_ACTION}")
        out = str(getattr(res, "output", "") or "")
        if getattr(res, "exit_code", 0) or "Error" in out or "unable to resolve" in out.lower():
            return False
        return bool(wait.until(self.edit_ready, timeout=2.5, poll=0.15, now=time.time, sleep=time.sleep))

    def _leave_search(self):
        """离开设置搜索页并回到设置首页（#639）：按 BACK 收起键盘、退出搜索页，
        再拉起设置首页——直达搜索页时它是新任务根，BACK 会落到桌面而不是设置首页。
        搜索失败的各条路径共用这一处退场。"""
        if not self.edit_ready():
            return True
        for _ in range(3):
            self.back()
            if not self.edit_ready():
                break
        else:
            return False
        self.reader.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
        time.sleep(0.5)
        return True

    def setting(self, kw, entry=None, box=None, path=None):
        """系统设置里搜 kw，点结果 entry（默认就是 kw）。
        box：搜索框文字，不给就自动认（小米「搜索系统设置项」、OPPO「搜索设置项」等）。
        path：结果下一行的位置文字（如「隐私与安全 > 隐私 > 设备标识与广告」）。同名结果有好几条时按它挑。
        先试直达搜索页的动作（ColorOS），没有就回设置首页点搜索框。
        设置首页刚打开时点搜索框会被忽略（小米 18 Pro Max 实测）：点完要看到输入框才往下走，没打开就再点。"""
        self.miss = 0

        def box_at():
            for t, (l, tp, r, b), _ in self.texts():
                if (box and box in t) or (not box and self.BOX.search(t)):
                    return ((l + r) // 2, (tp + b) // 2)
            return None

        def result_at():
            # 输入框里也有同一段文字；只认非输入框的结果，不能点回搜索框后假报成功。
            items = self.texts()
            for i, (t, (l, tp, r, b), n) in enumerate(items):
                if t != (entry or kw) or EDIT.search(n.get("class", "")):
                    continue
                if path and not (i + 1 < len(items) and items[i + 1][0] == path):
                    continue
                return ((l + r) // 2, (tp + b) // 2)
            return None

        def give_up(msg):
            # 失败前把页面退回设置首页：留在搜索页上，调用方后续的滚屏会全落在输入法上（#639）
            self.say(msg)
            if not self._leave_search():
                self.say(f"  · 设置搜索页退不出去，当前停在 {self.focus()}")
            return False

        opened = self._search_page()
        if not opened:
            self.reader.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
            for _ in range(4):
                xy = wait.until(box_at, timeout=3, poll=0.15, now=time.time, sleep=time.sleep)
                if not xy:
                    break
                time.sleep(0.4)                      # 首页还在加载时点击会被吞
                self.click(*xy)
                opened = bool(wait.until(self.edit_ready, timeout=2, poll=0.15,
                                         now=time.time, sleep=time.sleep))
                if opened:
                    break
        if not opened:
            return give_up(f"  ✗ 设置搜索框没打开，跳过「{kw}」")
        if not self.type_text(kw):
            return give_up(f"  ✗ 设置搜索框输入「{kw}」失败，跳过")
        xy = wait.until(result_at, timeout=3, poll=0.15, now=time.time, sleep=time.sleep)
        if not xy:
            return give_up(f"  ✗ 没搜到「{entry or kw}」，跳过")
        before = self.focus()
        self.click(*xy)

        def left_search():
            return self.focus() != before or not self.edit_ready()

        if not wait.until(left_search, timeout=3, poll=0.15, now=time.time, sleep=time.sleep):
            return give_up(f"  ✗ 搜索结果「{entry or kw}」没有打开，跳过")
        time.sleep(0.3)                      # 结果页起来了，给它的内容留一拍
        return True

    # ---------- 生命周期：拉起 App 与落点确认（Launcher） ----------
    def start(self, pkg, activity=None, settle=1.2, foreground=None, expect=None, budget=6.0):
        self.launcher.start(pkg, activity, settle, foreground, expect, budget)

    def has_text(self):
        return self.launcher.has_text()

    def expect_hits(self, expect):
        return self.launcher.expect_hits(expect)

    def expect_page(self, expect, timeout=4.0, poll=0.2):
        return self.launcher.expect_page(expect, timeout, poll)

    def _landing_note(self, expect):
        return self.launcher._landing_note(expect)

    def _launch_evidence(self, seizer="", frames=0):
        return self.launcher._launch_evidence(seizer, frames)

    def _launch(self, pkg, activity, settle, foreground):
        self.launcher._launch(pkg, activity, settle, foreground)


MISSED_SHOWN = 8    # 收尾那行最多列几个没拨动的开关，其余折成「等 N 个」


def missed_line(missed, limit=MISSED_SHOWN):
    """没拨动的开关拼成一行：`页面 · 标题`，多的折成「等 N 个」。页名缺省时只写标题。"""
    names = "、".join(f"{pg} · {t}" if pg else t for pg, t in missed[:limit])
    more = len(missed) - limit
    return f"没拨动的开关：{len(missed)} 个（{names}{f' 等 {more} 个' if more > 0 else ''}）"


def report_run(g, p):
    """机型脚本跑完的收尾：先报没做成的段，再报没拨动的开关；任一非空就返回 1（#788）。

    `g` 是 `exec` 的脚本作用域，`p` 是这一轮的 Phone。
    段名同时发 `failed_steps` 事件（客户端按它只重跑那几段，#638）；没拨动的开关只有人读的这一行，
    客户端按退出码把整个任务标「失败」。#758 的摘要要把它算进「K 段未完成」，得先有页→段映射。
    中止过的段落另起一行「因中止未执行：…」；第一行与 `failed_steps` 事件仍列全部段名（#838）。
    """
    if g.get("FAILED_STEPS"):
        failed = list(g["FAILED_STEPS"])
        halted = [name for name in failed if name in (g.get("HALTED_STEPS") or [])]
        events.emit("failed_steps", steps=failed)
        print("未完成步骤：" + "、".join(failed), flush=True)
        if halted:
            print("因中止未执行：" + "、".join(halted), flush=True)
    if p.missed:
        print(missed_line(p.missed), flush=True)
    return 1 if g.get("FAILED_STEPS") or p.missed else 0


def main():
    a = sys.argv[1:]
    if a in ([], ["--help"], ["-h"]):
        print(__doc__); return
    if len(a) < 3 or a[0] != "-s":
        print(__doc__); sys.exit(1)
    try:
        with Phone(a[1]) as p:
            execute(p, a[2], a[3:])
    except RuntimeError as e:
        # 断线、读屏服务被占用、启动失败：给出原因，不打印 Python 报错堆栈（错误日志 10-27）
        print(f"✗ {e}", flush=True)
        sys.exit(1)
    except Exception as e:
        # 断线 / 读屏慢一次：给一句人话，不打印 Python 报错堆栈（#731）
        message = adb_link.failure_message(e, a[1])
        if message is None:
            raise
        print(f"✗ {message}", flush=True)
        sys.exit(1)


def execute(p, cmd, rest):
    if cmd == "check":
        if p.locked():
            sys.exit("手机锁屏了，请机主解锁后重试")
        if not list(p.tree().iter("node")):
            sys.exit("读屏服务已连接，但没有读到页面节点，请解锁并停在设置首页后重试")
        print(f"读屏检查通过：{p.W} × {p.H}；未点击或修改任何开关")
    elif cmd == "ls":
        p.ls()
    elif cmd == "tap":
        for t in rest:
            p.tap(t)
        p.ls()
    elif cmd == "off":
        keep = rest[0].split(",") if rest and rest[0] else ()
        t = time.time(); n = p.off(keep=keep)
        print(f"关了 {n} 个，{time.time()-t:.1f} 秒")
    elif cmd == "scan":
        t = time.time(); seen = {}
        for _ in range(60):
            for k, c, _ in p.switches():
                seen.setdefault(k, c)
            if not p.scroll_more():
                break
        for k, c in seen.items():
            print(f"  [{'开' if c else '关'}] {k}")
        if not seen:
            p.top(); p.ls()
        print(f"{len(seen)} 个开关，开着 {sum(seen.values())} 个，{time.time()-t:.1f} 秒")
    elif cmd == "only":
        t = time.time(); n = p.off(only=rest[0].split(","))
        print(f"关了 {n} 个，{time.time()-t:.1f} 秒")
    elif cmd == "run":
        p.safe_mode = p.safe_mode or "--ref" in rest    # 参考脚本：off() 不做整页全关，由 run.py 传下来
        rest = [x for x in rest if x != "--ref"]
        if not p.wait_unlocked():
            print("✗ 手机一直锁屏，本步骤没有执行。请解锁手机、保持亮屏后重试"); sys.exit(2)
        g = {"p": p, "__name__": "__recipe__", "ONLY": rest[1:]}
        recipe_kit.preamble(p, g)
        with open(rest[0], encoding="utf-8") as f:
            src = f.read()
        build = p.d.shell("getprop ro.build.display.id").output.strip()
        osv = p.d.shell("getprop ro.mi.os.version.incremental").output.strip()     # 小米：HyperOS 版本号
        m = re.search(r'^BUILD\s*=\s*"([^"]+)"', src, re.M)
        if m and not (build.startswith(m.group(1)) or osv.startswith(m.group(1))):
            p.safe_mode = True
            print(f"⚠ 机型脚本是按 {m.group(1)} 录的，这台是 {osv or build}：用安全模式跑（只关点名的开关），没找到的段会快速跳过")
        t = time.time()
        try:
            exec(src, g)
        except adb_link.DeviceLost as e:
            print(f"\n✗ {e}\n已停止：关了 {len(p.changed)} 个，{time.time()-t:.0f} 秒", flush=True)
            sys.exit(1)
        print(f"\n机型脚本跑完：关了 {len(p.changed)} 个，{time.time()-t:.0f} 秒")
        import datetime
        logdir = backups.root_from_env() or os.path.dirname(os.path.abspath(rest[0]))
        try:
            os.makedirs(logdir, exist_ok=True)
            with open(os.path.join(logdir, "run-log.txt"), "a", encoding="utf-8") as f:
                f.write(f"\n# {datetime.datetime.now():%Y-%m-%d %H:%M} {' '.join(rest[1:]) or '全跑'}  {time.time()-t:.0f}s\n")
                for pg, tt in p.changed:
                    f.write(f"{pg}\t{tt}\n")
        except OSError:
            pass
        if report_run(g, p):
            sys.exit(1)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
