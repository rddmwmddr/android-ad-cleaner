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
from captures import root_from_env as _captures_root_from_env
from phone.screen import CONFIRM as CONFIRM
from phone.screen import PERMISSION_CONTROLLERS as PERMISSION_CONTROLLERS
from phone.screen import Captures as Captures
from phone.screen import Screen
from phone.session import ChannelSession, LaunchSession, LostNote
import adb_link
import backups
import events
import recipe_kit
import wait
from reader import Reader
from row import bounds as bounds
from row import switch_row as switch_row
# 弹窗搬走后本文件不再用它们，但改前这两个名字就在模块命名空间里（ADR-0033 的出口承诺）：
# 照 bounds / icon_hit 的写法显式 re-export，站外脚本的 `from fast import switches_in` 不会断。
from row import is_switch as is_switch, switches_in as switches_in
# 显式 re-export：机型脚本从 fast 取这个判据（与 bounds 同一处引用）。
from row import icon_hit as icon_hit
# 极性词表定义在 polarity.py（文档生成器也要同一份，见 #693），这里显式 re-export，
# `from fast import want_state` 的调用点一行都不用改。
from polarity import AD_WORDS as AD_WORDS, NEG_PREFIX as NEG_PREFIX, TRACK_WORDS as TRACK_WORDS
from polarity import want_state as want_state

# 导航已搬进 tool/phone/navigator.py（#1044），这里显式 re-export：`fast.SETTINGS_MARKS` 是
# 模块级名字，门面上的 `in_settings_page()` 只是转发。设置页的焦点签名与导航判据只有那一份。
from phone.navigator import SETTINGS_MARKS as SETTINGS_MARKS
from phone.navigator import Navigator


# 设置搜索框的识别式与直达动作随 `setting()` 搬进 tool/phone/settings_search.py（#1042），
# 这里显式 re-export：`fast.EDIT` 是模块级名字，门面上的 `BOX` / `SEARCH_ACTION` 仍是类常量。
from phone.settings_search import BOX as BOX, EDIT as EDIT, SEARCH_ACTION as SEARCH_ACTION
from phone.settings_search import SettingsSearch


# 弹窗与推广位已搬进 tool/phone/dismisser.py（#1043），这里显式 re-export：`fast.DISMISS` /
# `fast.UPDATE_TITLE` 是模块级名字；`CLOSE` / `BACK_LABELS` 仍是门面的类常量。
from phone.dismisser import DISMISS as DISMISS, UPDATE_TITLE as UPDATE_TITLE
from phone.dismisser import Dismisser


class ScreenLocked(RuntimeError):
    """手机锁屏了：调用方等机主解锁，或停下整批，不逐项报同一个原因。"""


# 启动与落点已随 `start()` 搬进 tool/phone/launcher.py（#1041），这里显式 re-export：
# `fast.unknown_focus` / `LAUNCH_WAIT` 这些模块级名字与 `tests/` 一行都不用改。
from phone.launcher import EXPECT_TAIL as EXPECT_TAIL
from phone.launcher import FOREIGN_STREAK as FOREIGN_STREAK
from phone.launcher import LAUNCH_HARD_STOP as LAUNCH_HARD_STOP, LAUNCH_WAIT as LAUNCH_WAIT
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

    两个基座与五个阶段已全部搬进 `tool/phone/`：`Connection`（连接与生命周期）、
    `Screen`（观测、视口几何、动作原语）、`Toggler`（整页拨动）、`Launcher`（启动与落点）、
    `SettingsSearch`（设置搜索）、`Dismisser`（弹窗与推广位）与 `Navigator`（导航）。
    """

    # 设置搜索框的识别式与直达动作归 `SettingsSearch`，弹窗的 ✕ 判据归 `Dismisser`；
    # 门面保留同名类常量（公开面不改）。
    BOX = BOX
    SEARCH_ACTION = SEARCH_ACTION
    CLOSE = Dismisser.CLOSE
    BACK_LABELS = Dismisser.BACK_LABELS

    def __init__(self, serial, log=True, reader: Reader | None = None):
        self.conn = Connection(serial, log=log, reader=reader)
        # 失败现场的根只在入口读一次环境变量，观测基座不认识客户端（同 `backups`：#1126）
        self.screen = Screen(self.conn, Captures(_captures_root_from_env()))
        # 三个跨阶段会话各有对象；门面只转发，写者与读者写在对象接口上（#1039）
        self.lost_note = LostNote()
        self.launch_session = LaunchSession()
        self.channel_session = ChannelSession()
        self.toggler = Toggler(self.screen, self.lost_note)
        self.search = SettingsSearch(self.screen, self.lost_note)
        # 弹窗读启动会话（推广位退回），启动阶段拿到关弹窗的窄接口：两边的边都经注入，不互相 import。
        self.dismisser = Dismisser(self.screen, self.launch_session)
        self.launcher = Launcher(self.screen, self.lost_note, self.launch_session, self.dismisser.dismiss)
        # 导航拿到弹窗阶段的窄接口（挡路的先点掉）：导航调它，它不回调导航，调用图无环（#1044）。
        self.navigator = Navigator(self.screen, self.lost_note, self.dismisser.dismiss)
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
        return self.screen.find(text, exact=exact, root=root, edge_ok=edge_ok, nav=nav)

    def scroll(self, frac=0.45, up=False):
        """按下-移动-停 0.12 秒-松开：没有惯性，翻多少是多少，约 0.45 秒。"""
        self.screen.scroll(frac, up)

    # ---------- 弹窗与推广位（Dismisser） ----------
    # 四条退化链（权限拒绝 / 更新标题 / ✕ 图标 / 推广位退回）与词表都在弹窗阶段；门面只转发。
    def dismiss(self):
        """挡路的更新/推荐/权限弹窗：点拒绝类按钮，不替用户同意任何东西（退化链见 `Dismisser`）。

        返回非空表示这次关掉了东西、返回前已经等过界面过渡，调用方不必再等；返回 None 表示这次
        什么也没关（推广位的 ✕ 点过也已退回原 App），调用方按自己的节奏等待或重试（沿用 #999）。"""
        return self.dismisser.dismiss()

    def _promoted_click(self, x, y, key):
        return self.dismisser.promoted_click(x, y, key)

    # ---------- 导航（Navigator） ----------
    # 按文字点、换页校验、等页、底栏、图标入口与回顶都在导航阶段；失败语义各方法不同（有的抛、
    # 有的只返回假），门面只转发。挡路的弹窗由阶段经注入的窄接口调 `Dismisser`，不回调门面。
    def tap(self, text, exact=False, scrolls=6, wait=0.6, quiet=False, seen=None):
        return self.navigator.tap(text, exact, scrolls, wait, quiet, seen)

    def in_settings_page(self):
        return self.navigator.in_settings_page()

    def await_page(self, budget=2.4, poll=0.2, stable=0.15, changed_from=wait.UNSET):
        return self.navigator.await_page(budget, poll, stable, changed_from)

    def entry(self, text, scrolls=6, budget=2.4, poll=0.2, tries=2):
        return self.navigator.entry(text, scrolls, budget, poll, tries)

    def tap_icon(self, expect, area=(0.72, 0.0, 1.0, 0.16), tries=3):
        return self.navigator.tap_icon(expect, area, tries)

    def enter(self, text, scrolls=0, tries=3):
        return self.navigator.enter(text, scrolls, tries)

    def go(self, text, expect, tries=3, exact=True):
        return self.navigator.go(text, expect, tries, exact)

    def tab(self, name, maxwait=6.0):
        return self.navigator.tab(name, maxwait)

    def top(self, n=None):
        self.navigator.top(n)

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

    # ---------- 设置搜索（SettingsSearch） ----------
    # 进搜索页、打字的多级退化链与退场都归设置搜索会话；失败只返回假、不抛异常（沿用 #776 的判据）。
    def focused_text(self):
        return self.search.focused_text()

    def type_text(self, kw, timeout=4.0):
        return self.search.type_text(kw, timeout)

    def edit_ready(self):
        return self.search.edit_ready()

    def setting(self, kw, entry=None, box=None, path=None):
        return self.search.setting(kw, entry, box, path)

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
    # 失败现场的归档名：run 在客户端是「关闭各 App 里的广告开关」这一步（`Task.kind` = recipe）
    p.screen.captures.task = "recipe" if cmd == "run" else cmd
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
