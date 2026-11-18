#!/usr/bin/env python3
"""营销通知渠道（通用版，走 fast 引擎）。
  chan_fast.py -s SERIAL scan [--reset]   只读：列出开着的、名字像营销或属于厂商营销分类（vivo VPushChannel_0/4/6）
                                          的渠道（候选，人工挑）；第四列是应用名
                                          （读应用名时在 /data/local/tmp 临时放一个 3 KB 的文件，用完删掉）
                                          --reset：清空「本机 UI 未暴露」名单后照常重扫
  chan_fast.py -s SERIAL verify 清单.tsv   只读：清单里还开着几个
  chan_fast.py -s SERIAL off 清单.tsv      逐个打开渠道页关掉
  chan_fast.py -s SERIAL on  清单.tsv      还原
清单.tsv：包名<TAB>渠道id<TAB>说明[<TAB>应用名]，一行一个；# 开头是注释。
"""
import hashlib, re, shlex, sys, time, os
from dataclasses import dataclass
from stdio import use_utf8_console

use_utf8_console()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fast import Phone, pause_point
from phone.errors import ScreenLocked
from row import PATH_DEPTH, SAME_LINE, link, skeleton
from channel_decide import VIVO_ACTIVITY, VIVO_HOSTS, vivo_page
from channel_arrive import truncated as truncated
from channel_policy import classify, protected_channel
from screen_snapshot import Intent, IntentKind, Progress, parse_notification_dump
from troubleshooting import ON_PHONE, XIAOMI_INPUT
from backups import root_from_env
from ui_hidden import UiHidden
import adb_link
import channel_arrive as arrive
import channel_decide as decide
import channel_toggle as toggle_decide
import events
import wait

# 一项的结局、记账表与批处理策略住在 `channel_batch`（纯值类型与纯函数），这里显式 re-export：
# 用例与渲染照旧取 `chan_fast.Outcome` / `chan_fast.DONE`，改名字要两边一起动。
import channel_batch as batch
from channel_batch import (APP_DENIED as APP_DENIED, APP_OFF as APP_OFF,
                           APP_STATE_UNKNOWN as APP_STATE_UNKNOWN, ALREADY as ALREADY,
                           CONFIRMED_LATER as CONFIRMED_LATER, DELETED as DELETED,
                           DONE as DONE, ERROR as ERROR, GREYED as GREYED, KINDS as KINDS,
                           MISMATCH as MISMATCH, NOT_CONFIRMED as NOT_CONFIRMED,
                           NO_CHANNEL as NO_CHANNEL, Outcome as Outcome,
                           OutcomeKind as OutcomeKind, PROTECTED as PROTECTED, RULES as RULES,
                           UI_HIDDEN as UI_HIDDEN, UNCHANGED as UNCHANGED,
                           account as account, channel_list_of as channel_list_of,
                           exempt_from_recheck as exempt_from_recheck, failed as failed,
                           kind_of_state as kind_of_state, pick_retry as pick_retry,
                           plan_queue as plan_queue, recheck_row as recheck_row,
                           retryable as retryable, second_pass as second_pass,
                           toggled as toggled)

# 「本机 UI 未暴露」名单落在备份目录同一个 root 下（ui_hidden.py），不另开一处。
BACKUPS = root_from_env() or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")


class ShellPhone(adb_link.Connection):
    """扫描和复查只读 adb，不启动手机端 UiAutomation。"""
    def __init__(self, serial):
        super().__init__(serial, sticky=False)          # 一个 reader 跑一整批：一次掉线不该毒掉后面的读取

    def shell(self, command, timeout=60):
        result = super().shell(command, timeout=timeout)
        if result.returncode:
            raise RuntimeError("adb 读取失败：" + (result.stderr or result.stdout).strip())
        return result

    def push(self, local, remote, timeout=30):
        result = super().push(local, remote, timeout=timeout)
        if result.returncode:
            raise RuntimeError("adb 传文件失败：" + (result.stderr or result.stdout).strip())


LABELS_DEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "applabels.dex")   # 源码在 applabels/
LABELS_REMOTE = "/data/local/tmp/aac-labels.dex"


def app_labels(reader, packages):
    """包名 → 手机上显示的应用名（跟随系统语言）。以前清单只有包名，用户认不出是哪个软件。
    在手机上跑一次 applabels.dex（只读，打印完退出，用完删掉）；读不到的不给，界面退回显示包名。"""
    packages = sorted({pk for pk in packages if re.fullmatch(r"[\w.]+", pk)})
    if not packages or not os.path.exists(LABELS_DEX):
        return {}
    out, pushed = {}, False
    try:
        reader.push(LABELS_DEX, LABELS_REMOTE)
        pushed = True
        for start in range(0, len(packages), 40):          # 老系统 adb 命令行有长度上限
            batch = " ".join(packages[start:start + 40])
            text = reader.shell(f"CLASSPATH={LABELS_REMOTE} app_process / aac.Labels {batch}", timeout=60).output
            for line in text.splitlines():
                pk, _, label = line.partition("\t")
                if pk in packages and label.strip():
                    out[pk] = label.strip()
    except Exception:
        pass                    # 只影响显示：读不到就显示包名，不让扫描失败
    finally:
        if pushed:
            try:
                reader.shell(f"rm -f {LABELS_REMOTE}")
            except Exception:
                pass
    return out

ROW_NOT_FOUND = "应用通知页里没找到这一行"     # #427 / #428 的共同卡点：名字挂在了认不出的地方
SKELETON_PER_RUN = 2                            # 一次运行最多带两份不同布局的骨架，防止占满上报预算


def state(d, app_off, pk, cid):
    """旧签名（parse 的字典 + app_off）：判定在 `channel_batch.state()`。"""
    return batch.state(channel_list_of(d, app_off), pk, cid)


def render(outcome, label, want_on, pk=""):
    """这一项的打印行；None 表示不提（已经是目标状态，或第二遍才确认改好、第一遍的 ✗ 已说过）。
    失败行带上包名（#582）：同名渠道分属不同 App 时，事后才说得清是哪几个。"""
    kind = outcome.kind
    if kind in (ALREADY, CONFIRMED_LATER):
        return None
    if kind == PROTECTED:
        return f"  · 受保护，未改动 {label}（找机位功能通知，{outcome.detail}）"
    if kind in (NO_CHANNEL, DELETED, APP_OFF):
        return f"  · 未操作 {label}（渠道不存在、已删除或应用通知已关闭）"
    if kind == GREYED:
        return f"  · 系统锁定（开关是灰的），不能关闭，不算失败  {label}"
    if kind == APP_DENIED:
        return f"  · 应用通知已整体关闭，渠道不会弹出，不算失败  {label}"
    if kind == UI_HIDDEN:
        return f"  · 本机界面没有这个渠道的入口，关不掉，不算失败  {label}"
    if kind == APP_STATE_UNKNOWN:
        return (f"  ✗ 应用通知总开关状态读不到，无法判断是否整体关闭（{outcome.detail}）  {label}"
                + (f"（{pk}）" if pk else ""))
    if kind == DONE:
        return f"  {'开' if want_on else '关'}  {label}"
    return f"  ✗ {outcome.detail}  {label}" + (f"（{pk}）" if pk else "")


def show(outcome, label, want_on, pk=""):
    """打印这一项的结局；不打印的项静默通过。机器行（骨架、判据读数）跟在人话后面，由客户端分流。"""
    line = render(outcome, label, want_on, pk)
    if line:
        print(line)
    if outcome.payload:
        events.payload(outcome.payload)


def phone_model(reader):
    """名单按型号分文件。读不到型号、或读数不像型号（多行、超长）时返回空串，整条名单停用：
    宁可下一轮继续报同一行，也不把另一台手机的名单套到这台上。"""
    try:
        model = reader.shell("getprop ro.product.model").output
    except Exception:
        return ""
    model = (model or "").strip()
    if not model or len(model) > 40 or any(c in model for c in "\r\n\t{}<>"):
        return ""
    return model


def parse(reader, locked=None, foreground=None):
    """只取机主空间（user 0）。双开、分身、隐私空间、安全文件夹的同名应用 UID 不同（#95），
    以前按包名混在一起：界面已关，回读却拿到另一空间的「开」。
    locked：传入集合时，收集系统不允许关闭的渠道（系统应用固定通知权限、渠道本身不可屏蔽，#134）。
    foreground：传入集合时，收集前台服务的常驻通知渠道（#459）。字段打在渠道行上，不在记录段。
    解析那一半在 `screen_snapshot.parse_notification_dump()`：通知清单值类型与这里共用同一份。"""
    txt = reader.shell("dumpsys notification --noredact", timeout=60).output
    channels, app_off, locked_hits, foreground_hits = parse_notification_dump(txt)
    if locked is not None:
        locked.update(locked_hits)
    if foreground is not None:
        foreground.update(foreground_hits)
    return channels, app_off


def stays_on(value):
    """插电常亮的位：1 交流、2 USB、4 无线，三位都在就算常亮。Android 14 起「保持唤醒」写 15（多一个底座位）。"""
    return value.isdigit() and int(value) & 7 == 7


def keep_awake(reader):
    """改开关期间插电常亮：营销通知一步可能跑好几分钟，以前只有机型脚本设了常亮（#71 中途锁屏）。
    手机版多半没插电，由 App 自己保持亮屏（#728）；这里设不上不影响，也不提示（#729），
    而且干脆不写（#731）：唯一还原点是「收尾」，断线正好会跳过它，设置就留在 7。
    vivo 经无线调试写不进任何全局设置（V2547DA / OriginOS 7 实测：put 被静默忽略），原值已是 15 时不算没设上。"""
    old = reader.shell("settings get global stay_on_while_plugged_in").output.strip()
    if not ON_PHONE:
        try:
            if not stays_on(old):
                reader.shell("settings put global stay_on_while_plugged_in 7")
            ok = stays_on(reader.shell("settings get global stay_on_while_plugged_in").output.strip())
        except RuntimeError:
            ok = False
        if not ok:
            print("  ! 插电常亮没有设上，手机息屏会打断操作；请把自动锁屏时间调长后再跑。" + XIAOMI_INPUT, flush=True)
    return old if old.isdigit() else "0"


def load(path):
    rows = {}
    with open(path, encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            if line.strip() and not line.lstrip().startswith("#"):
                # 第四列应用名只给人看：日志里不写应用名，上报的错误日志不含应用列表
                pk, cid, label = (x.strip() for x in (line.split("\t") + ["", ""])[:3])
                if not re.fullmatch(r"[\w.]+", pk) or not cid:
                    raise ValueError(f"清单第 {lineno} 行缺少有效包名或渠道 ID")
                # 同一渠道的重复行（含只差空格的写法，#194）合成一行：收尾按渠道计数，不能重复；
                # 哪一行带应用名就用哪一行的。
                rows[(pk, cid)] = label or rows.get((pk, cid), "")
    return [(pk, cid, label or cid) for (pk, cid), label in rows.items()]


# 通知页不在 com.android.settings 里的系统：只接受这些 Activity，页面内容仍由 ChannelPage._recognise() 复核。
NOTIFY_HOSTS = {
    # ColorOS 14 一加 Ace 2 Pro 实测；ColorOS 17 Find X9 Ultra 社区实测（#165）
    "com.oplus.notificationmanager": re.compile(r"^com\.oplus\.notificationmanager\.(?:Channel|App)NotificationSettingsActivity$"),
    # ColorOS 11/12（Android 10–12）的宿主是 coloros 而不是 oplus：OPPO PBDM00 / ColorOS 11 实测（#415）
    "com.coloros.notificationmanager": re.compile(r"^com\.coloros\.notificationmanager\.(?:Channel|App)NotificationSettingsActivity$"),
    # 荣耀 MagicOS 10 PTP-AN00 社区实测（#86）。华为 EMUI / HarmonyOS 4 和旧版荣耀按同一结构识别，未经实测
    "com.hihonor.systemmanager": re.compile(r"^com\.hihonor\.notificationmanager\.ui\.\w*Notification\w*Activity$"),
    "com.huawei.systemmanager": re.compile(r"^com\.huawei\.notificationmanager\.ui\.\w*Notification\w*Activity$"),
}


def notification_focus(p):
    """页面身份。旧接口的一行前向壳，实现在 `ChannelPage._focus()`。"""
    return ChannelPage(p, "")._focus()


def top_title(p, root):
    """顶栏标题。旧接口的一行前向壳，实现在 `channel_decide.top_title()`。"""
    return decide.top_title(p.snapshot(root=root, focus="", with_rows=False), p.screen.systemui_text)


def group_floor(texts):
    """「类别」/「類別」分组标题的上沿。旧接口的一行前向壳，实现在 `channel_decide.group_floor_of()`。"""
    return decide.group_floor_of(texts)


@dataclass
class Attempt:
    """一次渠道尝试的诊断：卡在哪一环、这一行的开关为什么没认出。旧接口的数据袋，由下面的壳搬运。"""
    why: str = ""
    stage: str = ""
    vivo_app: str | None = None


@dataclass(frozen=True)
class Reached:
    """到达：已经停在渠道页，并且认出了属于这个渠道的那一个开关。"""
    switch: tuple


@dataclass(frozen=True)
class Unreached:
    """没到达：卡在哪一环、这一行为什么没认出、页面结构摘要。text 就是给用户看的那一段。
    no_row 是结构信号不是文案：这一屏除了总开关再没有别的开关，页面上确实没有这个渠道的行。
    hidden 也是结构信号（#576）：应用通知页打开了、翻到底都没读到这个渠道名 —— 系统没把它放到界面上。"""
    stage: str = ""
    why: str = ""
    hint: str = ""
    no_row: bool = False
    skeleton: str = ""       # 脱敏页面骨架（#428）：只进上报，不进人话
    hidden: bool = False

    @property
    def text(self):
        return "；".join(x for x in (self.stage, self.hint, self.why) if x)


def chain(node, parents, depth=PATH_DEPTH):
    """从渠道名往上的控件链：类名、可点 c / 可滚动 s、子树里的开关数。不含页面文字，适配新系统靠它。"""
    return link(node, parents, depth)


POLL = 0.2                                  # 认渠道页的采样间隔


class ChannelPage:
    """一次「到达某个渠道页」的全过程：选路线、发深链、必要时转应用通知页、认出这一行的开关。

    路线与逐帧的下一步由 `channel_arrive` 的纯函数决定，这里只取快照、执行意图、把进度带回去。
    vivo_app 是一次到达的结果（从应用通知页记下的 App 名，用来区分总页与渠道页），认页要用，
    所以留在对象上；跨屏累积都在循环手里的 `Progress` 里。页面身份由 `_focus()` 判定，
    它写 Phone 上的 systemui_text / vivo_seen，归属不变（ADR-0002）。"""

    def __init__(self, p, name, pk="", cid="", vivo_app=None, channels=None):
        self.p, self.name, self.pk, self.cid, self.vivo_app = p, name, pk, cid, vivo_app
        self.channels = channels        # 到达决策的输入：调用方已经读到的通知清单（可为 None）
        self.stage, self.why, self.raw_focus = "", "", ""
        self.no_row = False
        self.hidden = False
        self.skeleton = ""

    # ---------- 认页与认行 ----------
    def _focus(self):
        """vivo 的应用通知总页和单个渠道页是同一个 Activity（X300 Ultra / OriginOS 6 实测）：
        总页标题是 App 名，「允许通知」管整个 App；渠道页标题是渠道名，开关数随渠道开关状态变化。
        这里只认页面身份，区分交给 `_recognise()`。读屏策略写回 Phone（ADR-0002）。
        读到的前台原文留在 raw_focus：判空时要点名是谁占着页面，再读一次可能已经是另一页（#422）。"""
        p = self.p
        focus = p.focus()
        self.raw_focus = focus
        package, _, activity = focus.partition("/")
        if activity.startswith("."):
            activity = package + activity
        p.screen.systemui_text = False
        if package in NOTIFY_HOSTS:
            return focus if NOTIFY_HOSTS[package].match(activity) else ""
        if package in VIVO_HOSTS:
            if not activity.endswith(VIVO_ACTIVITY):
                return ""
            p.channel_session.vivo_seen = True
            p.screen.systemui_text = package == "com.android.systemui"   # texts() 默认不读 systemui 的文字（那是状态栏）
            return focus
        return focus if "settings" in package.lower() and ("notification" in activity.lower() or "SubSettings" in activity) else ""

    def _unopened_stage(self):
        """应用通知页没认出来时点名真实前台（#422）：「应用通知页没有打开」以前把三种情况混成一
        句——页面真没开、宿主不认识（#415 报告里就出现「停在 com.coloros.notificationmanager」
        与「没有打开」并列）、前台被别的应用占着。包名对报告者已够定位，不译成应用名；
        也不劝「先暂停它」——桌面和启动器同样落进这里。"""
        package, sep, _ = self.raw_focus.partition("/")
        if not sep:
            # 通知栏拉下时 dumpsys 给的是窗口名（u0 NotificationShade），不是「包名/Activity」
            return "应用通知页没有打开"
        if package == self.pk:
            return f"应用通知页没有打开，前台是 {package}，是这个应用自己"
        if package in NOTIFY_HOSTS or package in VIVO_HOSTS:
            # 包名认识、Activity 不认识：多半是没见过的新系统。只说这句事实——说成「不是通知设置页」
            # 会让人去退出一个系统包（#415 的混淆换个说法），说成「就是通知设置页」又把白名单的判据反过来了
            return f"前台是 {package}，这个 Activity 没在已知列表里"
        if "settings" in package.lower():
            return f"应用通知页没有打开，前台是 {package}，是系统设置但不是通知页"
        return f"应用通知页没有打开，前台是 {package}，不是通知设置页"

    def _recognise(self):
        """认页过了才补一份带开关行的快照：自绘开关的页面在认页失败时不该白截一张图。"""
        p, name = self.p, self.name
        focus = self._focus()
        if not focus or "AppNotification" in focus or not name:
            return None
        snap = p.snapshot(focus=self.raw_focus, with_rows=False)
        if not decide.recognised_page(snap, name, focus, self.vivo_app, p.screen.systemui_text):
            return None
        snap = p.snapshot(root=snap.tree, focus=self.raw_focus, with_rows=True)
        return decide.recognise(snap, name, focus, self.vivo_app, p.screen.systemui_text).switch

    def _recognise_inline(self):
        """应用通知页里渠道行自带开关（荣耀 MagicOS 10 / Android 16，#99）。判定在
        `channel_decide.recognise_inline()`：只认标题与渠道名完全相同、全页唯一合格的一行。"""
        p, name = self.p, self.name
        focus = self._focus()
        if not name or name in decide.ALLOW or not focus or vivo_page(focus):
            return None
        snap = p.snapshot(focus=self.raw_focus, with_rows=False)
        got = decide.recognise_inline(snap, name, focus, p.screen.systemui_text)
        # 早退分支返回的 `why` 是空串：旧实现在这些分支不动上一轮留下的诊断，别清掉它
        if got.why:
            self.why = got.why
        return got.switch

    def _page_switch(self):
        return self._recognise() or self._recognise_inline()


    # ---------- 等 ----------
    def refresh(self, rounds=6):
        """只在当前页重认一次，不导航：点击循环每轮都要重取开关，不能重发深链。"""
        def sample():
            switch = self._page_switch()
            # vivo 直达的渠道页按规则不直接用（见 _recognise），不空等（错误日志 10-28：每个渠道 29 秒）
            if switch is None and self.p.channel_session.vivo_seen is True and not self.vivo_app:
                raise wait.GiveUp()
            return switch

        def locked():
            return ScreenLocked("手机锁屏了") if self.p.locked() else None

        # 预算按次数算：慢机型一轮读屏更久，但「最多试 rounds 次」就是要试满
        switch = wait.until(sample, tries=rounds, poll=POLL, same=3,
                            blocked=locked, now=time.monotonic, sleep=time.sleep)
        return Reached(switch) if switch else Unreached(self.stage, self.why)

    def undo(self, xy, want_on):
        """只在同一位置仍是刚拨过去的那个开关时再点一次，不沿用已消失的坐标。"""
        switch = _switch_of(self.refresh(rounds=6))
        if switch and abs(switch[2][1] - xy[1]) < SAME_LINE and switch[1] == want_on:
            # 引擎自己的点击也走唯一执行点（`Screen.apply()`），与拨动的点击同一条原语
            self.p.apply(Intent(IntentKind.TAP, at=switch[2]))
            time.sleep(0.4); self.p.confirm()
            return True
        return False

    # ---------- 诊断 ----------
    def _hint(self):
        """跳过时附上页面结构（不含页面文字）：标题在不在、有几个开关。适配新系统靠它。
        「应用通知页里没找到这一行」再附一份脱敏骨架（#428）：名字到底挂在哪。"""
        p, name = self.p, self.name
        try:
            root = p.tree()
            # 骨架在算开关行之前取：自绘开关要截图，截图那一步会改写节点类名（#531）
            self.skeleton = self._skeleton(root)
            snap = p.snapshot(root=root, focus=self.raw_focus, with_rows=True)
            # 开关列表照旧读两次（允许通知一次、全部一次）：自绘开关的页面两次各截一张图
            text = decide.page_hint(snap, name, p.screen.systemui_text, total=len(p.switches(root)))
        except Exception:
            return ""
        # 遮罩挡着的页面也读成「开关 0 个」，补一句才分得清是没适配还是有弹窗（#557）
        try:
            return text + p.residual_note("；", root)
        except Exception:
            return text          # 这个函数从不抛：摘要读到了就先给摘要，诊断失败不把它一起吞掉

    def _skeleton(self, root):
        """#427 要的答案：名字挂在哪个节点上。同一次运行里同一布局只留第一份，最多两份。"""
        p = self.p
        if self.stage != ROW_NOT_FOUND:
            return ""
        if self.no_row:
            return ""            # 应用通知整体关着：页面上确实没有这一行（#426），不是没认出来
        if p.channel_session.skeleton_count >= SKELETON_PER_RUN:
            return ""
        try:
            # 用 _focus() 刚读到的前台原文：再调一次 p.focus() 会多一次 dumpsys（ADR-0007），
            # 而且读到的可能已经是另一页（#422）
            text = skeleton(root, self.name, p.W, p.H, self.raw_focus)
        except Exception:
            return ""
        if not text:
            return ""
        # 布局签名取页面结构本身：骨架正文里的 N / M / P 随目标名变化，拿它去重等于每个渠道都算新布局
        sig = hashlib.sha1("\n".join(
            "|".join((n.get("class") or "", n.get("bounds") or "", n.get("resource-id") or "",
                      n.get("clickable") or "", n.get("checkable") or "", n.get("scrollable") or ""))
            for n in root.iter("node")).encode("utf-8")).hexdigest()
        if sig in p.channel_session.skeleton_sigs:
            return ""
        p.channel_session.skeleton_sigs.add(sig)
        p.channel_session.skeleton_count += 1
        return text

    # ---------- 到页 ----------
    def _enter_app_page(self, app_page_ready=False):
        """渠道深链被拦截时，从应用通知页进入：渠道行是导航行就点进去（HyperOS），自带开关就直接用这一行（内联布局）。

        每一帧都是「取快照 → `channel_arrive.page_step()` 给下一步 → 执行 → 把进度带回去」；
        `app_page_ready` 表示应用通知页的深链由 `open()` 按 `route()` 的意图发过了，这里不再发一次。
        """
        p, name = self.p, self.name
        if not app_page_ready:
            p.apply(arrive.app_page_intent(self.pk))
        root = None

        def app_page_shown():
            nonlocal root
            # 直达的渠道页可能还没换下去：vivo 两页是同一个 Activity，ColorOS 的渠道页也认得。
            # 以前读到旧页，点标题没反应，报「点这一行后页面没变」（错误日志 10-28）
            if not self._focus():
                return None
            snap = p.snapshot(focus=self.raw_focus, with_rows=False)
            root = snap.tree
            return True if not decide.titled(snap, name) else None

        shown = wait.until(app_page_shown, tries=15, poll=POLL,
                           now=time.monotonic, sleep=time.sleep)
        if not shown and not self._focus():
            self.stage = self._unopened_stage()
            return None
        self.stage = ROW_NOT_FOUND
        progress, seen, bottom, vivo_app = Progress(), False, False, self.vivo_app
        while progress.pages < arrive.PAGE_LIMIT:
            progress.pages += 1
            if p.locked():
                raise ScreenLocked("手机锁屏了")
            focus = self._focus()
            if not focus:
                step = arrive.page_step(None, name=name, alive=False, seen=seen, vivo_app=vivo_app)
                self.stage = step.stage
                return None
            root = root if root is not None else p.tree()
            vivo = vivo_page(self._focus())      # 另一次读：raw_focus 取这一次的，与快照同一帧
            snap = p.snapshot(root=root, focus=self.raw_focus, with_rows=False)
            step = arrive.page_step(snap, name=name, vivo=vivo,
                                    systemui_text=p.screen.systemui_text, vivo_app=vivo_app,
                                    seen=seen)
            seen, vivo_app = step.seen, step.vivo_app
            self.vivo_app = vivo_app
            if step.kind == arrive.StepAction.STOP:
                if step.stage:
                    self.stage = step.stage
                return None
            if step.kind == arrive.StepAction.RECOGNISE:
                self.stage = step.stage
                return _switch_of(self.refresh(rounds=12))
            if step.kind == arrive.StepAction.TAP:
                before = p.sig()
                p.apply(step.intent)
                follow = arrive.after_click(settled=p.settle(before), vivo=vivo)
                self.stage = follow.stage
                if follow.kind == arrive.StepAction.STOP:
                    return None
                return _switch_of(self.refresh(rounds=12))
            if p.scroll_more():
                root = None
                continue
            if not arrive.scroll_fallback(snap, name, vivo=vivo):
                bottom = True
                break
            # 自己翻一页找它。这条路绕过了 scroll_more 的「没标可滚动就不滑」守卫，
            # 所以照它的规矩补一次焦点检查：滑动把页面带走了就停下，不当成「没找到这一行」
            focus = p.focus()
            progress.last_signature = p.sig()
            p.apply(Intent(IntentKind.SCROLL))
            if p.focus() != focus:
                follow = arrive.after_scroll(stayed=False)
            else:
                follow = arrive.after_scroll(stayed=True, moved=p.sig() != progress.last_signature)
            if follow.kind == arrive.StepAction.STOP:
                if follow.stage:
                    self.stage = follow.stage
                    return None
                bottom = True
                break                     # 滑了没动：列表到底了，再滑也是空转
            root = None
        # 「没认出行」不等于「页面上没有这一行」：渠道名写在 CheckBox 上（#427）、own() 拿不到行容器、
        # 页面没标可滚动或翻页到上限时，行还在页面上而这轮没认出来。只有这一屏除了总开关再没有别的开关
        # （应用通知整体关闭时的样子）才敢断言没有这一行。
        self.no_row = bool(shown) and len(p.snapshot(focus=self.raw_focus, with_rows=True).rows) == 1
        # #576：翻到列表底、这个名字一次都没在这一页出现过，才算系统没把渠道放到界面上。
        # 名字还在页面上的（#427 那批挂在 CheckBox 或认不出的容器里）不算 —— 那是没认出，不是没有。
        self.hidden = bool(shown) and bottom and not seen
        return None

    def open(self, rounds=12):
        """走一趟到达：能直达就直达，不能就走应用通知页；失败时带上卡在哪一环。"""
        self.stage = "渠道深链没打开渠道页"
        leg = arrive.route(self.channels, None, pk=self.pk, cid=self.cid,
                           vivo_seen=self.p.channel_session.vivo_seen)
        for intent in leg.intents:
            self.p.apply(intent)
        switch = _switch_of(self.refresh(rounds)) if leg.way == arrive.DIRECT else None
        if not switch:
            switch = self._enter_app_page(app_page_ready=leg.way == arrive.APP_PAGE)
        if switch:
            return Reached(switch)
        return Unreached(self.stage, self.why, self._hint(), self.no_row, self.skeleton, self.hidden)


def _switch_of(reached):
    return reached.switch if isinstance(reached, Reached) else None


# ---------- 旧接口：一行的前向壳 ----------
# tests/ 里 7 个测试文件直接调这些名字，tests/compare_chan_pages.py 的探针还要求同一份代码能在
# 冻结基线与新实现上各跑一遍。逻辑全在 ChannelPage，壳只负责把诊断搬回传进来的 Attempt（ADR-0007）。

def channel_switch(p, name, at):
    return ChannelPage(p, name, vivo_app=at.vivo_app)._recognise()


def inline_switch(p, name, at):
    page = ChannelPage(p, name, vivo_app=at.vivo_app)
    switch = page._recognise_inline()
    at.why = page.why
    return switch


def page_switch(p, name, at):
    return channel_switch(p, name, at) or inline_switch(p, name, at)


def wait_page(p, name, at, rounds=12):
    page = ChannelPage(p, name, vivo_app=at.vivo_app)
    reached = page.refresh(rounds)
    at.why = page.why
    return _switch_of(reached)


def via_app_page(p, pk, name, at):
    page = ChannelPage(p, name, pk=pk, vivo_app=at.vivo_app)
    switch = page._enter_app_page()
    at.stage, at.why, at.vivo_app = page.stage, page.why, page.vivo_app
    return switch


class StopBatch(RuntimeError):
    """点错了开关：已尝试还原，整批停止。"""


class StopBatchLost(StopBatch):
    """点回后复核时手机断开：状态未知，整批按断线收尾（#330）。"""


def side_effects(before, apps_before, after, apps_after, pk, cid, allowed):
    """点击后除目标渠道外还有什么变了：应用总开关，或不在本批清单里的同应用渠道。"""
    out = []
    if apps_after.get(pk, False) != apps_before.get(pk, False):
        out.append("应用通知总开关")
    for key, (name, imp, _) in after.items():
        if key[0] != pk or key == (pk, cid) or key not in before:
            continue
        if (before[key][1] == 0) != (imp == 0) and key not in allowed:
            out.append(f"渠道「{name}」")
    return out


def recheck(before, apps_before, current, apps, may_change):
    """点回之后重读的全量状态与点击前比较：返回仍然不一致的地方（#330 第 2 条）。
    may_change：本批本来就要改的渠道 —— 它们留在目标状态不算残留。"""
    diffs = []
    for key, old in before.items():
        if key in may_change:
            continue
        new = current.get(key)
        if new is None or old[1:] != new[1:]:
            diffs.append(f"渠道「{old[0]}」")
    for key, (name, _, _) in current.items():
        if key not in before and key not in may_change:
            diffs.append(f"新增渠道「{name}」")
    if any(apps.get(package) != value for package, value in apps_before.items()):
        diffs.append("应用通知总开关")
    return diffs


def undo_message(p, before, apps_before, may_change, restored, extra, clicked):
    """点错开关后的说明：先说发生了什么，再说复核结果；复核不了就不能说已恢复（#330 第 2 条）。
    返回（文案，是否断线）。"""
    what = f"点击后{'、'.join(extra)}发生变化"
    if not clicked:
        return f"{what}，本次没有点击这一行，停止整批；请在手机上核对该 App 的通知设置", False
    head = what + ("" if restored else "，没能自动点回")
    try:
        current, apps = parse(p.conn.reader)
    except adb_link.DeviceLost:
        return f"{head}；复核时手机断开，没能核对是否恢复，停止整批", True
    except Exception:
        return (f"{head}；回退后复核失败，无法确认已恢复，停止整批；请在手机上核对该 App 的通知设置",
                False)
    diffs = recheck(before, apps_before, current, apps, may_change)
    if diffs:
        return (f"{head}；复核仍有差异：{'、'.join(diffs)}，没能完全恢复，停止整批；"
                "请在手机上核对该 App 的通知设置", False)
    return (head + ("，已点回并复核通过" if restored else "，复核与点击前一致")
            + "，停止整批；请在手机上核对该 App 的通知设置", False)


def page_hint(p, name):
    """页面上为什么没认出。旧接口的一行前向壳，实现在 `ChannelPage._hint()`。"""
    return ChannelPage(p, name)._hint()


def notifications_state(p, pk):
    """应用通知是否被系统整体关闭：True 关着 / False 没关 / None 读不出来。

    安卓 13 起看 POST_NOTIFICATIONS 权限；更早的系统没有这个权限，只有 appops 能问（华为
    HarmonyOS 4.2 / 安卓 12，#426）。有的系统 dumpsys notification 看不出来：渠道页的开关显示
    「关」，渠道记录仍是「开」（三星 9 个、vivo 2 个，错误日志 10-29；华为 #241 同样现象）。

    三态只在「记进本机 UI 未暴露名单」这一处要紧：那条名单是持久的，把一次读失败当成「没关」
    会让一个其实关得掉的渠道从扫描里永久消失（#576 复盘的取舍）。判 APP_DENIED 时仍走
    `notifications_denied()`，那里把「不知道」当「没关」。"""
    try:
        # 不加 grep -m：提前退出会让 dumpsys 收到 SIGPIPE，u2 判「shell output invalid」（#205）
        out = p.shell(f"dumpsys package {shlex.quote(pk)} | grep 'POST_NOTIFICATIONS: granted='"
                      " | sed -n '1,3p'")
    except Exception:
        out = ""
    if isinstance(out, str):
        if "POST_NOTIFICATIONS: granted=true" in out:
            return False                # 这个权限就代表着总开关，它开着就不用再问 appops
        if "POST_NOTIFICATIONS: granted=false" in out:
            return True
    try:
        mode = appops_mode(p.conn.reader, pk)
    except adb_link.DeviceLost:
        return None
    if mode == "unknown":
        return None
    return mode in APPOPS_DENIED


def notifications_denied(p, pk):
    """应用通知是否被系统整体关闭。读不出来按「没关」处理，见 `notifications_state()`。"""
    return notifications_state(p, pk) is True


# cmd appops 的 POST_NOTIFICATION 模式里算「关掉」的那两个；default / allow / foreground / 读不出来都按「没关」处理
APPOPS_DENIED = ("ignore", "deny")


def appops_mode(reader, package):
    """POST_NOTIFICATION 的 appops 模式；读不出来返回 unknown —— 不能当成 default 去写回（#330）。"""
    try:
        text = reader.shell(f"cmd appops get {shlex.quote(package)} POST_NOTIFICATION").output
    except adb_link.DeviceLost:
        raise
    except Exception:
        return "unknown"
    if not isinstance(text, str):
        return "unknown"
    match = re.search(r"(?m)^\s*(?:Uid mode:\s*)?POST_NOTIFICATION:\s*([A-Za-z_]+)", text)
    if match:
        return match.group(1).lower()
    return "default" if "No operations" in text else "unknown"


def appops_denied(p, pk):
    """没装 POST_NOTIFICATIONS 权限的系统（安卓 12 及以前）从 appops 读同一个总开关。"""
    try:
        return appops_mode(p.conn.reader, pk) in APPOPS_DENIED
    except adb_link.DeviceLost:
        return False            # 这条既有判据读到断线时按「没关」处理，不改变 #426 的收容行为


def restore_appops(reader, modes):
    """批次结束时只还原「原值 default、现值 allow」这一种副作用（#330 第 4 条）：
    访问应用通知页可能把权限模式提成 allow，其他组合一律不动。
    modes：批次开始时记下的包名 → 模式。返回（观察到被改过的应用，没能恢复的应用）；
    读不出来既不写也不算改动。"""
    changed, failed = [], []
    for package, original in sorted(modes.items()):
        if original != "default":
            continue
        if appops_mode(reader, package) != "allow":
            continue
        changed.append(package)
        try:
            reader.shell("cmd appops set " + shlex.quote(package) + " POST_NOTIFICATION default")
            if appops_mode(reader, package) != "default":
                failed.append(package)
        except adb_link.DeviceLost:
            raise
        except (OSError, RuntimeError):
            failed.append(package)
    return changed, failed


def restore_report(reader, modes):
    """收尾时恢复通知权限模式并说明结果；返回要加进失败计数的数（#330 第 4 条）。
    「确实发生过改动」走上报载荷：这条副作用在哪些机型上成立，只有报告里能看到。"""
    try:
        changed, failed = restore_appops(reader, modes)
    except adb_link.DeviceLost:
        print("  ✗ 手机断开，没能核对通知权限模式是否被页面改动")
        return 1
    if changed:
        events.payload("appops-changed\t" + ",".join(changed))
    done = [package for package in changed if package not in failed]
    if done:
        print(f"  · 通知权限模式：{'、'.join(done)} 由 default 变成 allow，已写回 default 并核对")
    if failed:
        print(f"  ✗ 通知权限模式没能恢复原值：{'、'.join(failed)}")
    return 1 if failed else 0


def disabled_at(p, xy):
    """开关是灰的（系统锁定的渠道）：点了也不会变，不再连点三次再报「状态未改变」。
    判定只有一份，在 `channel_toggle.greyed()`；这里保留按 Phone 取页面的旧签名。"""
    return toggle_decide.greyed(p.snapshot(root=p.tree(), focus="", with_rows=False), xy)


MISMATCH_PER_RUN = 3    # 一次运行最多补几条 MISMATCH 判据读数：额外命令只在不一致时发生，且要封顶
TOGGLE_TRIES = 3        # 单次拨动最多重认几次；退避时长在循环里，决定函数只数次数


def mismatch_probe(p, pk, cid, current, denied=None):
    """MISMATCH 的一条判据读数（#582）：页面上关着、渠道记录里开着，差在哪一项。
    只用 toggle 已经读到的 importance；应用级结论已有（denied）就不再问一次。"""
    if p.channel_session.mismatch_probes >= MISMATCH_PER_RUN:
        return ""
    p.channel_session.mismatch_probes += 1
    importance = current.get((pk, cid), ("", 0, False))[1]
    if denied is None:
        denied = notifications_denied(p, pk)
    return (f"mismatch\t{pk}\t{cid}\timportance={importance}"
            f"\tapp_notifications={'denied' if denied else 'allowed'}")


def toggle(p, pk, cid, want_on, name="", allowed=()):
    name = (name or "").strip()     # 渠道名可能带空格（一加 13「福利活动 」），页面文字是去掉空格的（错误日志 10-29）
    try:
        if p.locked():
            raise ScreenLocked("手机锁屏了")
        before, apps_before = parse(p.conn.reader)
        actual_name = before.get((pk, cid), ("", 0, False))[0]
        st = state(before, apps_before, pk, cid)
        if not want_on and protected_channel(actual_name, cid, name):
            return Outcome(PROTECTED, f"当前状态 {st}")
        if st in ("--", "del", "app"):
            return Outcome(kind_of_state(st))
        # 清单投影每个渠道建一次、纯内存（400 个渠道约 0.09 ms，远低于一次 adb 往返），
        # 留给 `route()` 的下一个判据直接从已知事实取，别为到达再读一次 dumpsys
        page = ChannelPage(p, name, pk, cid, channels=channel_list_of(before, apps_before))
        reached = page.open()
        if not isinstance(reached, Reached):
            absent = not want_on and reached.hidden        # 翻到底都没读到这个渠道名
            master_only = not want_on and reached.no_row   # 这一屏除了总开关再没有别的开关
            app_state = notifications_state(p, pk) if absent or master_only else False
            # 应用通知整体关着时，应用通知页只列总开关：这个渠道本来就不会出现在页面上，不是没认出（#426）
            if master_only and app_state is True:
                return Outcome(APP_DENIED)
            # 页面打得开、页面上确实没有这一行、App 通知明确没关：系统没把这个渠道放到界面上（#576）。
            # 关不掉，也不该每轮都报同一条失败 —— 由 run() 记进本机名单，下次扫描不再列出。
            if absent and app_state is False:
                return Outcome(UI_HIDDEN)
            # 总开关读不出来时不记名单：名单是持久的，一次读失败会让一个其实关得掉的渠道永久消失。
            # 两条来源同一条判据（#1064）：这一页的结构已经认出来了，只差总开关状态，报的是这一句。
            if (absent or master_only) and app_state is None:
                return Outcome(APP_STATE_UNKNOWN,
                               f"停在 {p.focus() or '未知页面'}；{reached.text}", reached.skeleton)
            # 只记 Activity、卡在哪一环和开关数量，不记页面内容；适配新系统靠它。
            return Outcome(NOT_CONFIRMED,
                           f"未确认「{name}」渠道页及通知开关，跳过（停在 {p.focus() or '未知页面'}；{reached.text}）",
                           reached.skeleton)
        if disabled_at(p, reached.switch[2]):
            return Outcome(GREYED)
        desired = "ON" if want_on else "off"
        for attempt in range(TOGGLE_TRIES):
            # 每次重取页面，开关消失时不能复用旧坐标。
            if p.locked():
                raise ScreenLocked("手机锁屏了")
            again = page.refresh(rounds=6)
            if toggle_decide.vanished(isinstance(again, Reached)):
                return Outcome(NOT_CONFIRMED, toggle_decide.VANISHED_DETAIL)
            switch = again.switch
            row = toggle_decide.row_of(switch)
            clicked = toggle_decide.can_click(row, want_on)
            if clicked:
                # 引擎自己的点击也走唯一执行点（`Screen.apply()`），与到达阶段的点击同一条原语
                p.apply(Intent(IntentKind.TAP, at=switch[2]))
                time.sleep(0.4); p.confirm()
            current, apps = parse(p.conn.reader)
            extra = side_effects(before, apps_before, current, apps, pk, cid, allowed)
            effect = toggle_decide.side_effect_verdict(extra, clicked)
            if effect.stop:
                restored = effect.undo and page.undo(switch[2], want_on)
                message, lost = undo_message(p, before, apps_before, set(allowed) | {(pk, cid)},
                                             restored, extra, clicked)
                raise (StopBatchLost if lost else StopBatch)(message)
            current_state = state(current, apps, pk, cid)
            # 界面这一行已经在目标态、渠道记录却还没跟上：只有这时才多读一次应用通知总开关，
            # 分清「应用通知整体关着」与「界面与记录不一致」（今天如此，别提前读）。
            denied = (notifications_denied(p, pk)
                      if current_state != desired and not clicked and not want_on else None)
            got = toggle_decide.verdict(row, current_state, want_on, attempt,
                                        tries=TOGGLE_TRIES, denied=denied)
            if got == toggle_decide.ToggleVerdict.DONE:
                return Outcome(DONE)
            if got == toggle_decide.ToggleVerdict.APP_DENIED:
                return Outcome(APP_DENIED)
            if got == toggle_decide.ToggleVerdict.MISMATCH:
                return Outcome(MISMATCH, "界面状态与渠道实际状态不一致，未继续点击",
                               mismatch_probe(p, pk, cid, current, denied))
            # 退避放在退出判断之前：第三轮放弃时也照旧等一次（旧实现两处顺序相同，别合并）
            time.sleep(0.25 + 0.3 * attempt)
            if got == toggle_decide.ToggleVerdict.UNCHANGED:
                break
        return Outcome(UNCHANGED, "点击后渠道状态未改变")
    except (StopBatch, adb_link.DeviceLost, ScreenLocked):
        raise                                    # 点错开关、手机断开、锁屏：由整批处理
    except Exception as e:
        gone = adb_link.lost_from(e, p.conn.serial)   # 读屏库的断线异常不是 RuntimeError，以前带着堆栈退出（错误日志 10-28）
        if gone is not None:
            raise gone from e
        # 读屏这一次没读成（手机版「读屏请求超时」）也只是这个渠道没处理，后面照常跑（#731）
        slow = adb_link.read_failed(e)
        if isinstance(e, RuntimeError) or slow:
            return Outcome(ERROR, slow or str(e))
        raise



def main():
    try:
        run(sys.argv[1:])
    except adb_link.DeviceLost as e:
        sys.exit(f"✗ {e}")
    except RuntimeError as e:
        # 读屏服务被占用、启动失败等：给出原因，不打印 Python 报错堆栈（错误日志 10-27）
        sys.exit(f"✗ {e}")
    except Exception as e:
        # 断线 / 读屏慢一次：给一句人话，不打印 Python 报错堆栈（#731）
        message = adb_link.failure_message(e, sys.argv[2] if len(sys.argv) > 2 else None)
        if message is None:
            raise
        sys.exit(f"✗ {message}")


def run(a):
    if a in ([], ["--help"], ["-h"]):
        print(__doc__); return
    if len(a) < 3 or a[0] != "-s" or a[2] not in {"scan", "verify", "off", "on"}:
        sys.exit("用法：chan_fast.py -s <序列号> scan|verify|off|on [清单.tsv]")
    serial, cmd = a[1], a[2]
    if cmd != "scan" and len(a) < 4:
        sys.exit("请提供通知清单路径")
    # 先校验文件；错误清单不应启动手机读屏服务。
    items = load(a[3]) if cmd != "scan" else []
    reader = ShellPhone(serial)
    if cmd == "scan":
        locked, foreground = set(), set()
        d, app_off = parse(reader, locked, foreground)
        store = UiHidden(BACKUPS, phone_model(reader))
        if "--reset" in a[3:]:
            store.clear()       # 换系统或 App 升级后渠道可能重新暴露：清空后这一轮重新判定
        hidden = store.load()
        short = fixed = fg_service = ui_hidden = 0
        rows = []
        for (pk, cid), (name, imp, deleted) in sorted(d.items()):
            judgement = classify(name, cid, foreground_service=(pk, cid) in foreground)
            if (imp != 0 and not deleted and not app_off.get(pk) and judgement.marketing_candidate
                    and not judgement.scan_excluded and not judgement.protected):
                if judgement.foreground_service:
                    fg_service += 1
                elif truncated(cid):
                    short += 1
                elif (pk, cid) in locked:
                    fixed += 1
                elif (pk, cid) in hidden:
                    ui_hidden += 1      # chan-off 见过这个 App 的通知页，上面根本没有这一行（#576）
                else:
                    rows.append((pk, cid, name))
        labels = app_labels(reader, [pk for pk, _, _ in rows])
        for pk, cid, name in rows:
            print("\t".join((pk, cid, name, labels[pk]) if pk in labels else (pk, cid, name)))
        if short:
            print(f"另有 {short} 个渠道的 ID 被系统缩略，无法可靠定位，未列入清单", file=sys.stderr)
        if fixed:
            print(f"另有 {fixed} 个渠道属于系统锁定、不允许关闭的系统应用，未列入清单", file=sys.stderr)
        if fg_service:
            print(f"另有 {fg_service} 个前台服务渠道未列入清单", file=sys.stderr)
        if ui_hidden:
            print(f"另有 {ui_hidden} 个渠道本机 UI 未暴露，未列入清单", file=sys.stderr)
        return
    if cmd in ("off", "on"):
        want = cmd == "on"
        d, app_off = parse(reader)
        allowed = {(pk, cid) for pk, cid, _ in items}
        p = None
        t0 = time.time(); changed = 0; failures = 0
        stay_on, awake = None, False
        exemptions, gone, halted = set(), False, False
        hidden = None               # 「本机 UI 未暴露」名单，第一次遇到才读型号（少一次 adb 往返）
        planned = plan_queue(items, channel_list_of(d, app_off), want)
        todo = [row.item for row in planned if row.queued]
        for row in planned:
            if row.queued:          # 要打开手机去拨
                continue
            show(row.outcome, row.label, want, row.pk)
            if failed(row.outcome, want):
                failures += 1
        retry, reached = [], 0
        modes = {}              # 首次打开页面前才读（#330 第 4 条）：没有待拨的渠道就不会有这项副作用
        try:
            for second in (False, True):
                queue = todo
                if second:
                    # 门槛在 `channel_batch.second_pass()`：锁屏 / 断开过、没起过读屏、
                    # 没有可重试的、超过上限，或这台一个都没关成功过（华为那种白等一轮）就不重试。
                    if not second_pass(halted=halted, started=p is not None, retry=retry, reached=reached):
                        break
                    d, app_off = parse(reader)
                    plan = pick_retry(retry, channel_list_of(d, app_off), want)
                    for row in plan.confirmed:      # 重扫发现其实已经改好了
                        failures -= 1
                        reached += 1
                        changed += toggled(row.outcome)
                        show(row.outcome, row.label, want, row.pk)
                    queue = [row.item for row in plan.queue]
                    if not queue:
                        break
                    print(f"再试一次刚才没确认的 {len(queue)} 个渠道", flush=True)
                for index, (pk, cid, label) in enumerate(queue):
                    if not awake:
                        stay_on, awake = keep_awake(reader), True
                    if p is None:
                        print("正在连接手机读屏服务……", flush=True)
                        p = Phone(serial, log=False)
                        p.conn.pause_at_lock_check = False   # 渠道里面查锁屏的地方不是安全位置：只在两个渠道之间暂停
                        if not p.wait_unlocked():
                            failures += 1
                            print("  ✗ 手机一直锁屏，本步骤没有执行。请解锁手机、保持亮屏后重试")
                            halted = True
                            break
                        modes = {pk: appops_mode(p.conn.reader, pk) for pk in sorted({pk for pk, _, _ in todo})}
                        print(f"要处理 {len(todo)} 个渠道，每个几秒到半分钟，处理完一个显示一行", flush=True)
                    pause_point()
                    try:
                        try:
                            outcome = toggle(p, pk, cid, want, d[(pk, cid)][0], allowed)
                        except ScreenLocked:
                            if not p.wait_unlocked(60):
                                raise
                            outcome = toggle(p, pk, cid, want, d[(pk, cid)][0], allowed)
                    except ScreenLocked:
                        failures += 1
                        print(f"  ✗ 手机锁屏了，停在「{label}」，剩下 {len(queue) - index} 项没有处理。请解锁手机、保持亮屏后重试")
                        halted = True
                        break
                    except (StopBatch, adb_link.DeviceLost) as e:
                        failures += 1
                        gone = isinstance(e, (adb_link.DeviceLost, StopBatchLost))
                        halted = True
                        print(f"  ✗ {e}  {label}")
                        break
                    credit = account(outcome, want)
                    if credit.failure:
                        if not second:
                            failures += 1
                        if not second and credit.retry:     # 第一遍的页面慢，留给第二遍再试
                            retry.append((pk, cid, label))
                    else:
                        failures -= second      # 重试成功：第一遍记下的失败撤销
                        reached += 1
                        changed += credit.toggled
                    if credit.exempt:
                        exemptions.add((pk, cid))
                    if outcome.kind == UI_HIDDEN:
                        if hidden is None:
                            hidden = UiHidden(BACKUPS, phone_model(reader))
                        hidden.remember([(pk, cid)])
                    show(outcome, label, want, pk)
                if halted:
                    break                       # 锁屏、点错开关、断开：整批停下，不再重试
            if p is not None and not gone:
                p.shell("input keyevent HOME")   # 只读 / 无需改动时不操作手机页面
        finally:
            if p is not None:
                p.close()
            if stay_on is not None and not ON_PHONE:      # 手机版没改过这项设置，也就没有要改回的（#731）
                try:
                    reader.shell(f"settings put global stay_on_while_plugged_in {stay_on}")
                except RuntimeError:
                    pass                        # 手机已断开：收尾一步会再改回
            if p is not None:
                failures += restore_report(reader, modes)
        print(f"拨了 {changed} 个，{time.time()-t0:.0f} 秒")
        if gone:
            sys.exit(1)                 # 手机已断开：上面已说明原因，不再回读
    else:
        exemptions = set()
    d, app_off = parse(reader)
    channels = channel_list_of(d, app_off)
    bad = 0
    for pk, cid, label in items:
        row = recheck_row(channels, pk, cid, label, exemptions)
        if row.still_open:
            bad += 1
            if cmd == "off":
                print(f"  仍开着：{label}（{pk}）")   # 后缀包名同失败行（#582）：同名渠道才分得清（#751）
        if cmd == "verify":
            note = "，受保护，不参与营销关闭" if row.protected else ""
            print(f"{row.state:4} {label}（{pk}{note}）")
    print(f"营销渠道仍开着: {bad} 个")
    if cmd == "on":
        pending = sum(batch.state(channels, pk, cid) != "ON" for pk, cid, _ in items)
        print(f"未恢复的渠道: {pending} 个")
        if pending or failures:
            sys.exit(1)
    if cmd == "off" and (bad or failures):
        sys.exit(1)                  # 让客户端把这一步标成失败（Issue #7：以前失败了也显示成功）


if __name__ == "__main__":
    main()
