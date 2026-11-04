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
import os, re, sys, time, xml.etree.ElementTree as ET
from dataclasses import dataclass
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass
import adbutils
import uiautomator2 as u2
from ui_session import connect
from troubleshooting import UI_RECOVERY, XIAOMI_INPUT, accessibility_summary, input_blocked
import adb_link
import backups
import events
import wait
from reader import Reader
from row import (SWITCH_ROW_DEPTH, bounds, control, dedupe, disabled_at, is_switch, own,
                 summary, switches_in, title_of, unique)
# 显式 re-export：机型脚本从 fast 取这个判据（与 bounds 同一处引用）。
from row import icon_hit as icon_hit

DISMISS = ("以后再说", "暂不更新", "暂不", "取消", "我知道了", "跳过", "禁止", "不再提示", "不同意")
# 应用内更新弹窗的标题（主题商店 17.22.0beta2 是「检测到新版本」，#286）。它通常把更新说明放进可滚动容器，
# 只按标题认，不按按钮认：单个「取消」在正常设置面板里也有。
UPDATE_TITLE = re.compile(r"检测到新版本|发现新版本|版本更新提示")
CONFIRM = ("确定", "关闭", "仍要关闭", "确认关闭", "确认", "继续关闭", "关闭推荐", "仍然关闭")
# 点击后认确认框总共等多久：vivo 商店「个性化推荐」页的弹窗要 0.6 秒才进树，而一次读屏
# 也要上百毫秒，1 秒是「能等到慢弹窗」与「没弹窗的页面不多付太多」之间的取值（#555）。
# 前 0.2 秒先不给读屏：弹窗刚弹出时按钮还在动，点在半路上不生效。
# 预算按挂钟算、读屏本身也吃时间：dump 慢到 0.5 秒的机型只采得到两次样，晚于 1 秒才进树的
# 弹窗仍会漏，那时靠 `off()` 连点前的遮罩检查兜一次。
CONFIRM_WAIT = 1.0
CONFIRM_SETTLE = 0.2
PERMISSION_CONTROLLERS = {"com.android.permissioncontroller", "com.google.android.permissioncontroller"}
# 输入框：荣耀 MagicOS 10（PNM-AN10 10.0.0.102）设置搜索框是 AutoCompleteTextView，类名里没有 EditText
EDIT = re.compile(r"EditText|AutoCompleteTextView")


class ScreenLocked(RuntimeError):
    """手机锁屏了：调用方等机主解锁，或停下整批，不逐项报同一个原因。"""


def pause_point():
    """客户端点了「暂停」（创建 AAC_PAUSE_FILE）就在这里等，点「继续」（删掉文件）再往下走；暂停过返回 True。
    只放在安全的位置：机型脚本每段开始前（段首的锁屏检查）、营销通知每个渠道开始前。
    暂停期间不读屏、不点击；继续后重新读页面，不用暂停前的坐标。"""
    path = os.environ.get("AAC_PAUSE_FILE")
    if not path or not os.path.exists(path):
        return False
    print("⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」", flush=True)
    events.emit("paused")
    while os.path.exists(path):
        time.sleep(0.5)
    print("▶ 继续执行", flush=True)
    events.emit("resumed")
    return True


def switch_row(node, parents, depth=SWITCH_ROW_DEPTH):
    """文字所在的那一行里有开关：这一行是开关，不是导航入口。
    只看结构：调用方 find() 已经自己筛过可视区域，这里不重复筛。"""
    _, boxes = own(node, parents, lambda _: True, depth)
    return any("RadioButton" not in (n.get("class") or "") for n in boxes)


# 「防止/限制/阻止广告跟踪」「关闭个性化推荐」这类开关是反着的：打开才是保护。不能当广告开关关掉。
NEG_PREFIX = re.compile(r"^(防止|限制|阻止|禁止|拒绝|不允许|屏蔽|关闭|停用|不接收|不显示|不推送|停止)")
AD_WORDS = re.compile(r"广告|跟踪|追踪|推荐|个性化|营销|资讯|热搜|热点|定向|画像")   # 不含「推送」：「关闭推送」会连订单通知一起关
TRACK_WORDS = re.compile(r"广告|跟踪|追踪")
# 判据词后面只能是结尾或分隔符：底栏读作「我的，有新消息」算命中，「我的应用」不算
EXPECT_TAIL = re.compile(r"[，,、/·\s（(：:]")


def expect_match(word, text):
    """这段文字是不是判据词本身：开头相同，且后面停在分隔符上。"""
    if text == word:
        return True
    return text.startswith(word) and bool(EXPECT_TAIL.match(text[len(word):]))


def want_state(title):
    """这个开关该处在什么状态：False=关（普通广告开关）；True=开（保护类开关）；None=不碰。"""
    if NEG_PREFIX.search(title or ""):
        return True if AD_WORDS.search(title) else None
    return False


@dataclass(frozen=True)
class SwitchPlan:
    """一页的拨动计划：要拨的目标、核对过的开关、安全模式放过的开关、被上级开关禁用的开关。"""
    targets: tuple
    checked: frozenset
    kept: frozenset
    disabled: frozenset = frozenset()


def in_band(xy, screen_h):
    """行的落点在可点带内：避开顶部标题栏与底部栏。"""
    return screen_h * 0.08 <= xy[1] <= screen_h * 0.985


def plan_switches(rows, keep=(), only=None, safe_mode=False, *, screen_h, disabled=None):
    """这一页该拨哪些开关。rows 是 `Phone.switches()` 的输出；函数不读屏、不点击。

    targets 只含需要点击的行；checked 是过了筛选的标题，含已在目标态、落在屏带外与被禁用的；
    kept 是安全模式放过的普通开关。disabled 是按坐标判「这一行的开关是灰的」的谓词：
    命中的行不进 targets，也不报成拨不动。screen_h 无默认值：带过滤是这一页几何的一部分。"""
    checked, kept, candidates = set(), set(), []
    for title, state, xy in rows:
        if not title:
            continue
        want = want_state(title)
        if want is None:
            continue
        if any(k in title for k in keep):
            continue
        if only is not None and not any(k in title for k in only) and not (want and TRACK_WORDS.search(title)):
            continue                              # 「限制广告跟踪」这类保护开关：不在名单里也要打开
        if safe_mode and only is None and not want:
            kept.add(title)
            continue                              # 参考脚本（同品牌别的机型录的）：不做整页全关
        checked.add(title)
        if state == want:
            continue
        if not in_band(xy, screen_h):
            continue
        candidates.append((title, xy, want))
    greyed = greyed_titles(((t, xy) for t, xy, _ in candidates), disabled) if disabled else set()
    targets = tuple(c for c in candidates if c[0] not in greyed)
    return SwitchPlan(targets, frozenset(checked), frozenset(kept), frozenset(greyed))


def greyed_titles(pairs, disabled):
    """这些 (标题, 落点) 里同名行全部被判灰的标题。同一屏可能有两个同名开关（双列卡片），
    一个灰一个正常时，不能因为一个灰就把另一个的失败也当成灰态吞掉（#333）。"""
    flags = {}
    for title, xy in pairs:
        flags.setdefault(title, []).append(disabled(xy))
    return {title for title, found in flags.items() if all(found)}


def _shell_transport(shell):
    """读屏库的 shell 当传输。断线只有它认得出来（异常类型加错误串），判定留在这一层。"""
    def send(command, timeout=None):
        try:
            return shell(command) if timeout is None else shell(command, timeout=timeout)
        except Exception as e:
            # 「shell output invalid … b''」：命令没有任何回应，连接正在断开（错误日志 10-27）。
            if adb_link.lib_gone(str(e)) or (isinstance(e, u2.exceptions.AdbShellError) and "output invalid" in str(e)):
                raise adb_link.LinkBroken(e) from e
            raise
    return send


class Phone:
    def __init__(self, serial, log=True, reader: Reader | None = None):
        if log:
            print("正在连接手机读屏服务……", flush=True)
        try:
            self.reader = reader if reader is not None else connect(serial)
        except u2.exceptions.AccessibilityServiceAlreadyRegisteredError as e:
            events.emit("ui_busy")
            raise RuntimeError("UIAUTOMATION_BUSY：手机读屏服务已被占用，本次未点击开关。"
                               "已清理本次失败的启动并重试一次，仍无法连接。"
                               "请退出旧版客户端，只保留一个客户端。\n"
                               f"{accessibility_summary(serial)}\n{UI_RECOVERY}\n"
                               f"原始异常：{type(e).__name__}: {e}") from e
        except u2.exceptions.UiAutomationError as e:
            raise RuntimeError("手机读屏服务（UiAutomation）启动失败，本次未点击开关。"
                               f"\n{accessibility_summary(serial)}\n{UI_RECOVERY}\n"
                               f"原始异常：{type(e).__name__}: {e}") from e
        except (u2.exceptions.AdbShellError, adbutils.AdbError) as e:
            # 读屏服务文件传不进手机（adb push 返回 FAIL）或命令无回应：多半是连接中途断了（错误日志 10-27）。
            if not adb_link.present(serial):
                raise adb_link.lost(f"{type(e).__name__}: {e}") from e
            raise RuntimeError("读屏服务没能装到手机上（adb 传文件失败），本次未点击开关。请拔插数据线、"
                               "退出电脑上的手机助手类软件后重试；仍失败请重启手机。"
                               f"\n原始异常：{type(e).__name__}: {str(e)[:200]}") from e
        self._shell = self.reader.shell
        self.link = adb_link.Connection(serial, transport=_shell_transport(self._shell), lost_on_retry=False)
        self.reader.shell = self._resilient_shell
        try:
            self.reader.settings["operation_delay"] = (0, 0)
            self.W, self.H = self.reader.window_size()
            # 小米没开「USB 调试（安全设置）」时能读不能点：先探一下，别跑几分钟全是「没找到」。
            if input_blocked(self.reader.shell("input keyevent 0").output):
                raise RuntimeError("INPUT_BLOCKED：系统拒绝了电脑发出的点击，本次未点击开关。\n" + XIAOMI_INPUT)
        except BaseException:
            self.reader.close()
            raise
        self.log = log
        self.pause_at_lock_check = True     # 机型脚本每段开头都查锁屏：这里就是段与段之间，可以暂停
        self.safe_mode = False              # 安全模式（参考脚本 / 录制版本不符）：off() 只关点名的开关，不做整页全关
        self.systemui_text = False          # 读屏时是否算上 com.android.systemui 的文字（vivo OriginOS Ocean 的通知页就挂在那里）
        self.vivo_seen = False              # 见过 vivo 的通知页：渠道页与应用通知页是同一个 Activity，只从应用列表进
        self.changed = []          # (页面, 标题) 记录本次关掉的
        self.miss = 0              # 本段已经没找到几次；>0 说明路径对不上，后面只看当前屏、不再翻页找
        self.skeleton_sigs = set()  # 本次运行已上报的骨架布局（#428）：同布局只留第一份
        self.skeleton_count = 0     # 本次运行已上报的骨架份数，上限见 chan_fast.SKELETON_PER_RUN
        self.promoted = set()      # 点过才发现是推广位的 ✕：(App, 控件) 同一处不再点第二次（#420）
        self.app = ""              # 最近一次 start 拉起的目标 App：推广位只在这个 App 里判

    @property
    def d(self):
        """读屏 adapter 的历史名字：recipes（`p.d.shell`）与测试用它，实体是同一个 `reader`。"""
        return self.reader

    @d.setter
    def d(self, value):
        self.reader = value

    @property
    def serial(self):
        """串号归 Connection：每条命令都要带 -s，不存在「手机对象认一台、命令发给另一台」。"""
        return self.link.serial

    @serial.setter
    def serial(self, value):
        self.link.serial = value

    @property
    def lost(self):
        """本轮是否已确认断线；状态归 Connection，这里只是读写它的一个别名。"""
        return self.link.lost

    @lost.setter
    def lost(self, value):
        if value:
            self.link.mark_lost()

    def _resilient_shell(self, *args, **kwargs):
        """手机短暂掉线（另一个 adb 服务重启、接口抖动）等它回来重试一次；仍不在就整段停下。"""
        return self.link.shell(*args, **kwargs)

    def check_alive(self):
        """本轮已确认断线：本段立刻停下，不再读屏、不再逐段重试（#293）。
        排查说明由第一次报错给出，后面的段只报这一句。"""
        self.link.check_alive()

    def _u2(self, fn, *a, **k):
        """u2 直连的调用（dump_hierarchy、window_size、app_stop）不走 shell；
        连接级异常也在这里记下断线，否则后面的段会一遍遍重复同样的失败（#293）。"""
        self.check_alive()
        try:
            return fn(*a, **k)
        except Exception as e:
            if adb_link.lib_gone(str(e)):
                self.lost = True
            raise

    def close(self):
        self.reader.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def say(self, *a):
        if self.log:
            print(*a, flush=True)

    # ---------- 读屏 ----------
    def tree(self):
        root = ET.fromstring(self._u2(self.reader.dump_hierarchy))
        # Mi 10 的热榜子页会横屏；不能一直用连接时的竖屏尺寸过滤节点。
        self.W, self.H = self._u2(self.reader.window_size)
        return root

    def focus(self):
        """当前焦点窗口（~0.1 秒；u2 的 app_current 在浮窗上会卡 10 秒）。"""
        self.check_alive()
        # 不能加 grep -m / head：提前退出会让 dumpsys 收到 SIGPIPE，u2 判「shell output invalid」（#205）。
        # sed 读完整个流再截断，行数与原来一致。
        out = self.reader.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | sed -n '1,4p'").output
        # vivo OriginOS 3 / Android 13 行尾是「Activity}}」（错误日志 10-27）。
        # 焦点窗口为 null 时看 mFocusedApp：华为 HarmonyOS 4.2、vivo OriginOS Ocean 页面明明在，以前报「停在 未知页面」（错误日志 10-29）
        for field in ("mCurrentFocus", "mFocusedApp"):
            m = re.search(field + r"=.*? u0 ([^\s}]+)", out)
            if m:
                return m.group(1)
        out = self.reader.shell("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity|ResumedActivity:'"
                           " | sed -n '1p'").output
        m = re.search(r"u0 (\S+/[^\s}]+)", out) or re.search(r" (\S+/[^\s}]+)", out)
        return m.group(1) if m else ""

    def texts(self, root=None):
        root = root if root is not None else self.tree()
        out = []
        # 华为 HarmonyOS 4 把同一个控件吐出两次；按节点身份数行时会变成「同名 2 行」（#510）
        for n in unique(root.iter("node")):
            if n.get("package") == "com.android.systemui" and not self.systemui_text:
                continue                      # 状态栏/通知栏文字不算
            t = (n.get("text") or n.get("content-desc") or "").strip()
            if t and self.on_screen(n):
                out.append((t, bounds(n), n))
        return out

    def page_text(self):
        """失败诊断用：当前屏可见文字拼成一行。入口找不到时说明停在哪个页面，光报「没找到」分不清
        是点击被吞还是这个版本换了布局（#286）。"""
        return " / ".join(t for t, _, _ in self.texts()[:20])

    def on_screen(self, n):
        """折叠屏合上时，dump 里还留着内屏那份节点，坐标在外屏之外（Issue #2）；点上去没反应。"""
        if n.get("visible-to-user") == "false":
            return False
        l, t, r, b = bounds(n)
        cx, cy = (l + r) // 2, (t + b) // 2
        return r > l and b > t and 0 <= cx < self.W and 0 <= cy < self.H

    def switches(self, root=None):
        """[(标题, checked, (cx,cy))]，标题取开关所在行的第一段文字。"""
        root = root if root is not None else self.tree()
        parent = {c: p for p in root.iter() for c in p}
        out = []
        shot = None
        for n in unique(root.iter("node")):
            if not self.on_screen(n) or "RadioButton" in n.get("class", ""):
                continue
            if n.get("checkable") != "true":
                rid = (n.get("resource-id") or "").lower()
                # 自绘开关：看颜色；TextSwitcher 是文字轮播。里面已经有真开关的（AOSP 渠道页的 main_switch_bar）不算：
                # 按颜色猜出的状态会盖过里面那个真开关，关着的渠道被读成开着，还原营销通知失败（0.3.1 发版前模拟器发现）
                if ("switch" in rid and "switcher" not in rid and n.get("clickable") == "true"
                        and not any(c is not n and c.get("checkable") == "true" for c in n.iter("node"))):
                    l, t, r, b = bounds(n)
                    if r - l > 0 and b - t > 0:
                        if shot is None:
                            shot = self.reader.screenshot()
                        # UI 坐标与截图可能来自不同分辨率/旋转状态。不能越界取样，也不能把未知状态当关。
                        if shot.size != (self.W, self.H):
                            continue
                        on = self._pixel_on(shot, l, t, r, b)
                        if on is None:
                            continue
                        n.set("checked", "true" if on else "false")
                        n.set("checkable", "true")
                        n.set("class", "SelfDrawnSwitch")
                if n.get("checkable") != "true":
                    continue
            cls = n.get("class", "")
            if not any(k in cls for k in ("Switch", "CheckBox", "ToggleButton", "Compound")) and n.get("clickable") != "true":
                continue
            l, t, r, b = bounds(n)
            if r - l <= 0 or b - t <= 0 or not self.on_screen(n):
                continue
            ctrl = control(n, self.on_screen)       # 卡片整体 checkable 时点在卡片中心不生效
            l, t, r, b = bounds(ctrl)
            # 卡片自己报状态时以卡片为准；缺这个属性才读内层开关，别把缺属性当成「关」
            checked = n.get("checked") if n.get("checked") is not None else ctrl.get("checked")
            out.append((title_of(n, parent, self.on_screen, self.H), checked == "true", (l, t, r, b)))
        return [(title, on, ((l + r) // 2, (t + b) // 2)) for title, on, (l, t, r, b) in dedupe(out)]

    def locked(self):
        if self.pause_at_lock_check and pause_point():
            return not self.wait_unlocked()      # 暂停时机主可能锁了屏：亮屏等他解锁
        out = self.reader.shell(adb_link.KEYGUARD_CMD).output
        if adb_link.focus_window(out) == "NotificationShade" and not adb_link.LOCK_FIELD.search(out):
            # 可能只是通知栏被拉下来了：收起后再看；锁屏界面收不起来，焦点仍是 NotificationShade
            self.reader.shell("cmd statusbar collapse")
            time.sleep(0.4)
            out = self.reader.shell(adb_link.KEYGUARD_CMD).output
        return adb_link.keyguard_showing(out)

    def wait_unlocked(self, timeout=90):
        """锁屏时点亮屏幕，等机主解锁（不代替解锁）。等到了返回 True。
        错误日志 10-27：约 15 份报告在开始执行时手机已锁屏，以前直接报失败，后面每一项都重复「锁屏了」。"""
        self.reader.shell("input keyevent KEYCODE_WAKEUP")
        if not self.locked():
            return True
        print(f"  ! 手机锁屏了：请解锁手机并保持亮屏，解锁后自动继续（最多等 {timeout} 秒）", flush=True)
        events.emit("locked")
        t = time.time()
        while time.time() - t < timeout:
            time.sleep(1)
            if not self.locked():
                time.sleep(0.8)
                return True
        return False

    def sig(self):
        return "|".join(t for t, _, _ in self.texts())

    def scroll_more(self):
        """翻一页；翻完没出现新文字（到底、回弹）返回 False。"""
        if not any(n.get("scrollable") == "true" and self.on_screen(n) for n in self.tree().iter("node")):
            return False                       # 单屏面板上滑动可能直接关掉页面
        focus = self.focus()
        before = {t for t, _, _ in self.texts()}
        self.scroll()
        if self.focus() != focus:
            raise RuntimeError("翻页离开了当前设置页，停止本段以免操作其他 App")
        after = {t for t, _, _ in self.texts()}
        return not after <= before

    @staticmethod
    def _pixel_on(img, l, t, r, b):
        """开关轨道取几个点：彩色（蓝/绿/橙，饱和度高）=开，灰白=关。"""
        w, h = img.size
        if not (0 <= l < r <= w and 0 <= t < b <= h):
            return None
        img = img.convert("RGB")
        sat = 0
        for fx in (0.25, 0.5, 0.75):
            R, G, B = img.getpixel((int(l + (r - l) * fx), (t + b) // 2))
            sat = max(sat, max(R, G, B) - min(R, G, B))
        return sat > 60

    def ls(self):
        root = self.tree()
        print("·", self.focus())
        print(" / ".join(t for t, _, _ in self.texts(root)))
        for t, c, xy in self.switches(root):
            print(f"  [{'开' if c else '关'}] {t}  @{xy}")

    # ---------- 动作 ----------
    def click(self, x, y):
        size = self._u2(self.reader.window_size)
        if tuple(size) != (self.W, self.H):
            self.W, self.H = size
            raise RuntimeError("屏幕方向或尺寸已变化，停止使用旧坐标；请重新读取页面")
        if not (0 <= x < self.W and 0 <= y < self.H):
            raise RuntimeError("点击坐标在屏幕外，未操作")
        out = self.reader.shell(f"input swipe {x} {y} {x} {y} 80").output   # 有的 App 吞 input tap
        if input_blocked(out):
            raise RuntimeError("系统拒绝了电脑发出的点击。" + XIAOMI_INPUT)

    def scroll(self, frac=0.45, up=False):
        """按下-移动-停 0.12 秒-松开：没有惯性，翻多少是多少，约 0.45 秒。"""
        x = self.W * 7 // 10 if self.W > 2000 else self.W // 2
        frac = min(frac, 0.58)                   # 留在 0.22H~0.80H 之间拖，避开标题栏和底栏
        y1, y2 = int(self.H * 0.80), int(self.H * (0.80 - frac))
        if up:
            y1, y2 = y2, y1
        c = [f"input motionevent DOWN {x} {y1}"]
        c += [f"input motionevent MOVE {x} {int(y1 + (y2 - y1) * i / 6)}" for i in range(1, 7)]
        c += ["sleep 0.12", f"input motionevent UP {x} {y2}"]
        self.reader.shell(";".join(c))
        time.sleep(0.15)

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

    def find(self, text, exact=False, root=None, edge_ok=False, nav=False):
        """先找文字完全相同的，再找包含的。nav=True（tap 导航用）：包含匹配不点开关所在行里的文字——
        那是开关的说明，点了等于拨开关（#247：「隐私」命中「边下边玩」的说明「不涉及隐私数据」，把功能关了）。"""
        root = root if root is not None else self.tree()
        items, parents = self.texts(root), None
        for whole in ((True,) if exact else (True, False)):
            for t, (l, tp, r, b), n in items:
                if not ((t == text) if whole else (text in t and t != text)):
                    continue
                if b <= tp or r <= l:
                    continue
                if nav and not whole:
                    parents = parents or {c: q for q in root.iter() for c in q}
                    if switch_row(n, parents):
                        continue
                cy = (tp + b) // 2
                if cy < self.H * 0.92:
                    return ((l + r) // 2, cy)
                if edge_ok == "tab":                     # 底部标签栏：直接点中心
                    return ((l + r) // 2, cy)
                if edge_ok and tp < self.H * 0.975:      # 已到页底翻不上来：点这一行的上沿
                    return ((l + r) // 2, tp + 15)
        return None

    CLOSE = re.compile(r"close|关闭|跳过|skip|cancel|dismiss|iv_x\b|btn_x\b", re.I)

    def dismiss(self):
        """挡路的更新/推荐/权限弹窗：点拒绝类按钮（不替用户同意任何东西）。
        纯图片的广告弹窗没有文字，只有一个 ✕ 图标：找 desc/id 里带 close 的可点元素。"""
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
            key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
            if (self.CLOSE.search(key) and not (n.get("text") or "").strip()
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
        """点 ✕ 之后前台换成了别的 App：多半是页面里的推广位（#420），退回原 App 并记下这一处。
        点前不在目标 App（抢焦点的广告浮层）或点后读不到前台时不算推广位，调用方照旧算关闭。
        返回真表示这次没关掉弹窗。"""
        before = self.focus().split("/", 1)[0]
        if before and (before, key) in self.promoted:
            return True                     # 这个 App 的这一处点过并跳走了：再点还是跳
        self.click(x, y); time.sleep(0.6)
        after = self.focus().split("/", 1)[0]
        if not (before and after and before == self.app and after != before):
            return False
        self.promoted.add((before, key))
        self.back(); time.sleep(.4)
        where = self.focus().split("/", 1)[0]
        if where and where != before:        # 一次返回还没退回来，再退一次
            self.back(); time.sleep(.4)
            where = self.focus().split("/", 1)[0]
        if where and where != before:
            # 退不回来就停：不能把用户留在别的 App 里，也不能在陌生页面上接着找入口
            raise RuntimeError(f"点 ✕ 后跳到了 {after}，返回两次仍停在 {where}，停止本段以免操作其他 App")
        self.say(f"  · 点了 ✕ 后跳到 {after}，疑似推广位，已退回（{key[:40]}）")
        return True

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
                self.dismiss() or time.sleep(0.2)
            if not quiet:
                self.say(f"  ✗ 没找到「{text}」")
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
                self.say(f"  ✗ 没找到「{text}」（快速放弃）")
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
            self.say(f"  ✗ 没找到「{text}」")
        return False

    def in_settings_page(self):
        """当前页是某个 App 的设置页（类名含 Setting）。点完齿轮用它确认真的进去了：
        点击被吞时页面没换，接着在旧页上找入口会整段失败（#331）。"""
        return "Setting" in self.focus()

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

    def _page_diagnosis(self):
        """停在哪个 Activity、页面结构摘要（不含页面文字）：区分「没加载完」与「入口真的没了」。
        只吞页面解析失败；断线（DeviceLost）照常冒泡，不能被当成「页面没认出来」。"""
        where = self.focus() or "未知页面"
        try:
            detail = summary(self.tree(), self.W, self.H)
        except ET.ParseError:
            detail = "页面结构读不到"
        return where, detail

    def note_miss(self, text):
        """入口没找到时留下能定位的页面骨架，与渠道「未确认」日志同一风格。"""
        where, detail = self._page_diagnosis()
        self.say(f"  · 「{text}」没找到；停在 {where}；{detail}")

    def icon_candidates(self, area=(0.72, 0.0, 1.0, 0.16)):
        """没有文字、点了才知道去哪的图标（右上角齿轮、更多）：按位置从右往左给候选坐标。
        整块卡片/列表项点了会进别的页面，按尺寸排除掉。"""
        x0, y0, x1, y1 = (v * s for v, s in zip(area, (self.W, self.H, self.W, self.H)))
        out = []
        for n in self.tree().iter("node"):
            if n.get("clickable") != "true":
                continue
            if (n.get("text") or "").strip() or (n.get("content-desc") or "").strip():
                continue
            l, t, r, b = bounds(n)
            cx, cy = (l + r) // 2, (t + b) // 2
            if not (x0 <= cx <= x1 and y0 <= cy <= y1 and self.on_screen(n)):
                continue
            if r - l > self.W * 0.25 or b - t > self.H * 0.10:
                continue
            out.append((cx, cy))
        out.sort(key=lambda xy: -xy[0])        # 齿轮在最右边，先试它
        return out

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
                raise RuntimeError(f"未找到入口「{text}」；当前页：{self.page_text()}")
            if self.settle(seen[0], 2.0):
                return
        raise RuntimeError(f"点「{text}」后页面没有变化；当前页：{self.page_text()}")

    def go(self, text, expect, tries=3, exact=True):
        """点 text，直到 expect 出现在屏幕上（被弹窗吞掉就再点）。
        精确匹配找不到时退回包含匹配：底部标签常读作「我的，有新消息」，精确匹配「我的」返回空（#305）。
        放宽的只是点哪个节点，落点仍由 expect 确认，点错了照样返回 False。"""
        if exact and not self.find(text, exact=True, edge_ok="tab", nav=True):
            exact = False
        for _ in range(tries):
            self.tap(text, exact=exact, scrolls=0)
            for _ in range(5):
                if self.find(expect) or self.find(expect, edge_ok="tab"):
                    return True
                self.dismiss() or time.sleep(0.3)
        self.say(f"  ✗ 点「{text}」后没出现「{expect}」")
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
            self.dismiss() or time.sleep(0.2)

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

    def settle(self, before, maxwait=0.8):
        """等新的非空页面稳定；跳页动画中的空树不算已经加载好。"""
        return bool(wait.until(self.sig, maxwait, poll=0.1, stable=0.2,
                               changed_from=before, now=time.time, sleep=time.sleep))

    def back(self, n=1):
        for _ in range(n):
            b = self.sig()
            self.reader.shell("input keyevent BACK")
            self.settle(b, 0.6)

    def confirm(self):
        """开关后弹确认框就点确认类按钮，认出即返回按钮文字；没有弹窗返回 None。

        弹窗进树可能远慢于一次读屏（vivo 商店这一页要 0.6 秒），单次快照从点击那一刻起就
        必然错过，剩下的点击会落在遮罩上被吞（#555）。所以在 CONFIRM_WAIT 预算内轮询。"""
        time.sleep(CONFIRM_SETTLE)
        found = wait.until(self._confirm_target, timeout=CONFIRM_WAIT - CONFIRM_SETTLE,
                           poll=0.1, now=time.time, sleep=time.sleep)
        if found is None:
            return None
        label, xy = found
        self.click(*xy)
        time.sleep(0.3)
        return label

    def _confirm_target(self, root=None):
        """屏上第一个确认类按钮的 (文字, 落点)；没有返回 None。只看不点，等弹窗与防遮罩共用它。

        严格档只认 Button 类，ColorOS 开关旁边的「开启/关闭」状态文字不算——点了会把开关又拨回去。
        按钮文字不一定在 text 上：vivo 阅图锁屏的 Button text 为空、文字在 content-desc（#246 / PR #249）；
        vivo / iQOO 另一种弹窗把文字放在 Button 下级的 TextView（vbutton_title，PR #239）。
        都要整段等于确认词，避免点到说明文字。
        屏幕外的节点跳过：页面里常留着上一层对话框的按钮，点它会抛「点击坐标在屏幕外」把整段打断（PR #248）。
        严格档全没命中再退一档：HyperOS 4 的部分弹窗把确认键画成可点击的 TextView（小米 17 热榜页，PR #408 / #500）。
        兜底档靠 TextView 类过滤挡掉 ColorOS 的 View 状态文字，尺寸只用来排除整行。"""
        root = root if root is not None else self.tree()

        def button_hit(n, c):
            if "Button" not in (n.get("class") or ""):
                return False
            label = (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()
            inner = {(x.get("text") or "").strip() for x in n.iter("node") if x is not n}
            return label == c or (not label and c in inner)

        def text_view_hit(n, c):
            if "TextView" not in (n.get("class") or ""):
                return False
            if (n.get("text") or "").strip() != c or n.get("clickable") != "true":
                return False
            l, t, r, b = bounds(n)
            return r - l < self.W * 0.5 and b - t < self.H * 0.12

        for hit in (button_hit, text_view_hit):
            for c in CONFIRM:
                for n in root.iter("node"):
                    if not hit(n, c):
                        continue
                    l, t, r, b = bounds(n)
                    if r > l and b > t and self.on_screen(n):
                        return c, ((l + r) // 2, (t + b) // 2)
        return None

    def off(self, keep=(), only=None, page="", max_screens=40):
        """当前列表：关掉开着的开关。keep=标题含这些词的不动；only=只关含这些词的。
        每屏第一下单独点、看有没有弹窗/跳页；没有就把这一屏剩下的连着点完，最后统一核对。
        关掉一项这一行就消失的页面（下面的行整体上移）：从下往上点，上移的只可能是已经点过的行；
        首击后剩下的目标若已不在原坐标，这一屏剩下的改成每点一项前重读坐标（#480）。
        点过的普通开关行在回读里消失、回读仍见到本屏计划时的非目标行且没跳走，按已关记账；
        整页读空、换到别的页（含同 Activity 的子页）或保护类开关消失，仍报失败（#486）。
        开关是灰的（被上级开关禁用）的行不点、也不算失败：点了也不会变，以前报成「关不掉」（#333）。"""
        # 页面刚打开还没画完：等开关出现，最多试 10 次（本段已走丢就不等）
        wait.until(self.switches, tries=2 if self.miss else 10, poll=0.2,
                   now=time.time, sleep=time.sleep)
        start = self.focus()
        done, slow, checked, kept, greyed = 0, False, set(), set(), set()

        def plan_page(root):
            rows = self.switches(root)
            return (plan_switches(rows, keep, only, self.safe_mode, screen_h=self.H,
                                  disabled=lambda xy: disabled_at(root, xy)), rows)

        for _ in range(max_screens):
            root = self.tree()
            plan, planned = plan_page(root)
            if plan.disabled:
                # 开关可能在页面加载中短暂不可用：复读一次再定，别把恢复可用的开关整屏跳过（#333）
                root = self.tree()
                plan, planned = plan_page(root)
            checked |= plan.checked
            kept |= plan.kept
            page_greyed = set(plan.disabled)
            targets = plan.targets
            others = {title for title, _, _ in planned if title} - {t for t, _, _ in targets}
            order = list(reversed(targets))             # 先点下面的：它消失时上移的只可能是已点过的行
            shift = False                               # 剩下的目标是不是还准在计划坐标上
            clicked = set()                             # 本屏真的点过的标题：点完从列表消失的靠它认
            for i, (t, xy, w) in enumerate(order):
                if i and not slow and self._confirm_target() is not None:
                    # 首击的确认框比 confirm() 的等待还慢时，页面还盖着遮罩：连点下去全被吞（#555）
                    self.confirm()
                if i and shift:
                    # 页面重排过：每点一项前重读，旧坐标可能已经指向邻行
                    time.sleep(0.3)                     # 等行消失、列表上移的动画走完
                    root = self.tree()
                    rows = self.switches(root)
                    row = next(((on, at) for title, on, at in rows
                                if title == t and on != w), None)
                    if row is None or not in_band(row[1], self.H) or disabled_at(root, row[1]):
                        continue                        # 已不在、已到位、已在带外或已变灰：交给收尾回读
                    xy = row[1]
                self.click(*xy)
                clicked.add(t)
                if i == 0 or slow:
                    if self.confirm():
                        slow = True                     # 这页会弹确认框，逐个点
                    elif self.focus() != start:
                        self.say(f"  ! 页面变了（{self.focus()}），停")
                        self.back()
                        return done
                if i == 0 and len(order) > 1:
                    time.sleep(0.3)                     # 等动画走完，再看剩下的是不是还在原处
                    now = {(title, on, at) for title, on, at in self.switches()}
                    shift = any((t2, not w2, xy2) not in now for t2, xy2, w2 in order[1:])
                elif i and not slow:
                    time.sleep(0.06)
            if targets:
                time.sleep(0.25)
                self.confirm()

                def wrong():                            # 还没到目标状态的标题，以及其中灰掉的
                    root = self.tree()
                    rows = self.switches(root)
                    states, want = {}, {t: w for t, _, w in targets}
                    for title, on, _ in rows:
                        states.setdefault(title, []).append(on)
                    page_same = None                    # 惰性查：没有消失行时不额外读一次前台
                    still, vanished = set(), set()
                    for t, _, w in targets:
                        seen = states.get(t)
                        if seen is not None:
                            if any(on != w for on in seen):   # 同名双列：还有一行没到目标态（#403）
                                still.add(t)
                        elif t in clicked and rows and not w:
                            # 点过的普通开关行从列表里消失了：回读里还有本屏计划时见过的非目标行，
                            # 且没跳走，才算随行消失。整页读空、换成标题全新的页（同 Activity 的子页）
                            # 时这一页已无法核对，不能把读屏失败当成关闭成功（#486）。
                            # 保护类开关是「主动打开」，行消失证明不了它开了，仍报打不开。
                            if page_same is None:
                                page_same = self.focus() == start
                            if page_same and others & states.keys():
                                vanished.add(t)
                            else:
                                still.add(t)
                        else:
                            still.add(t)
                    return still, still & greyed_titles(
                        ((title, xy) for title, on, xy in rows
                         if title in still and on != want[title]),
                        lambda xy: disabled_at(root, xy)), vanished

                def retry(still):
                    # 只重试当前仍能识别的开关，不能在节点消失后沿用旧坐标；灰掉的点了也不会变。
                    if not still:
                        return
                    here = self.focus()
                    if here and here != start:
                        return                          # 页面已经换了：新页上的同名行不是这一屏的开关
                                                        # here 为空只是这一次没读到前台，不拦补点
                    root = self.tree()
                    rows = self.switches(root)
                    want = {t: w for t, _, w in targets}
                    grey = still & greyed_titles(
                        ((title, xy) for title, on, xy in rows
                         if title in still and on != want[title]),
                        lambda xy: disabled_at(root, xy))
                    retried = set()                     # 一次补点里同名标题只点一下
                    for t, _, w in targets:
                        if t not in still or t in grey or t in retried:
                            continue
                        # 同名双列挑还开着、且不是灰的行：按标题取最后读到的那行会让补点取决于读屏顺序（#403）
                        row = next(((on, at) for title, on, at in rows
                                    if title == t and on != w and not disabled_at(root, at)), None)
                        if row is not None:
                            retried.add(t)
                            self.click(*row[1]); self.confirm()
                            clicked.add(t)              # 补点也算点过：行随后消失同样是随行消失（#486）
                still, grey, vanished = wrong()
                retry(still)
                still, grey, vanished = wrong()
                if still:                               # 还有没拨过去的：等动画结束再点一次
                    time.sleep(0.8)
                    retry(still)
                    time.sleep(0.4)
                    still, grey, vanished = wrong()
                page_greyed |= grey                     # 这一屏关到一半才变灰的，同样不报成拨不动
                for t, _, w in targets:
                    if t in still and t in grey:
                        continue                        # 下面单独说明
                    if t in still:
                        self.say(f"  ✗ {'打不开' if w else '关不掉'} {t}")
                    else:
                        self.say(f"  {'开（保护类开关）' if w else '关'} {t}"
                                 + ("（点后从列表消失）" if t in vanished else ""))
                        self.changed.append((page, t))
                        done += 1
            for t in page_greyed - greyed:
                self.say(f"  · 被上级开关禁用（开关是灰的），未改动 {t}")
            greyed |= page_greyed
            if not self.scroll_more():
                break
        if page:
            if kept and not checked:
                # 页面找到了，只是安全模式不整页全关；不能写成「未找到」
                self.say(f"  · {page}：安全模式不做整页全关，本页 {len(kept)} 个开关未改动，需要时请按清单手动关")
            else:
                self.say(f"  · {page}：核对 {len(checked)} 项，调整 {done} 项" + ("（本页未找到目标开关）" if not checked else ""))
        return done

    def focused_text(self):
        for n in self.tree().iter("node"):
            if n.get("focused") == "true" and EDIT.search(n.get("class") or "") and self.on_screen(n):
                return n.get("text") or ""
        return None

    def type_text(self, kw, timeout=4.0):
        """往当前输入框打字。部分机型（小米 HyperOS 设置搜索）用 setText 会卡住、一直打「%」：
        加超时，打完核对；不对就清掉、改用剪贴板粘贴；还不对就关掉键盘返回 False，不卡住。"""
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
        self.reader.shell("input keyevent BACK")
        return False

    BOX = re.compile(r"^搜索.{0,6}设置|^Search settings", re.I)

    def edit_ready(self):
        """搜索页打开了：屏幕上有获得焦点的输入框。"""
        for n in self.tree().iter("node"):
            if EDIT.search(n.get("class") or "") and n.get("focused") == "true" and self.on_screen(n):
                return True
        return False

    def setting(self, kw, entry=None, box=None):
        """系统设置里搜 kw，点结果 entry（默认就是 kw）。
        box：搜索框文字，不给就自动认（小米「搜索系统设置项」、OPPO「搜索设置项」等）。
        设置首页刚打开时点搜索框会被忽略（小米 18 Pro Max 实测）：点完要看到输入框才往下走，没打开就再点。"""
        self.miss = 0
        self.reader.shell("am start -f 0x10008000 -a android.settings.SETTINGS")

        def box_at():
            for t, (l, tp, r, b), _ in self.texts():
                if (box and box in t) or (not box and self.BOX.search(t)):
                    return ((l + r) // 2, (tp + b) // 2)
            return None

        def result_at():
            # 输入框里也有同一段文字；只认非输入框的结果，不能点回搜索框后假报成功。
            for t, (l, tp, r, b), n in self.texts():
                if t == (entry or kw) and not EDIT.search(n.get("class", "")):
                    return ((l + r) // 2, (tp + b) // 2)
            return None

        opened = False
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
            self.say(f"  ✗ 设置搜索框没打开，跳过「{kw}」")
            return False
        if not self.type_text(kw):
            self.say(f"  ✗ 设置搜索框输入「{kw}」失败，跳过")
            return False
        xy = wait.until(result_at, timeout=3, poll=0.15, now=time.time, sleep=time.sleep)
        if not xy:
            self.say(f"  ✗ 没搜到「{entry or kw}」，跳过")
            return False
        before = self.focus()
        self.click(*xy)

        def left_search():
            return self.focus() != before or not self.edit_ready()

        if not wait.until(left_search, timeout=3, poll=0.15, now=time.time, sleep=time.sleep):
            self.say(f"  ✗ 搜索结果「{entry or kw}」没有打开，跳过")
            return False
        time.sleep(0.3)                      # 结果页起来了，给它的内容留一拍
        return True

    def start(self, pkg, activity=None, settle=1.2, foreground=None, expect=None, budget=6.0):
        """拉起 App；之后 settle 秒内冒出来的更新/推荐弹窗顺手点掉。

        expect：预期页面的判据——给一段文字就要看见它，给一组时全部出现才算落在页面上。
        budget：等判据的秒数，恢复前后各给一次。
        有开屏 / 推广页的 App 用它：落在别处时退一次，返回把 App 退到后台就重新拉起一次；
        仍不对就结束本段（#420）。判据由调用方给（如该 App 的底部标签栏文字）。
        空白页不等于推广页，不按返回：慢机型上首屏可能只是还没画完。"""
        self.promoted.clear()
        self.app = foreground or pkg
        self._launch(pkg, activity, settle, foreground)
        if expect is None or self.expect_page(expect, budget):
            return
        self.say(self._landing_note(expect))
        where = self.focus().split("/", 1)[0]
        if where and where != self.app:
            self._launch(pkg, activity, settle, foreground)     # 已经不在目标 App：重新拉起一次
        elif where == self.app and self.has_text():
            self.back()                                          # 在目标 App 里却是别的页（开屏 / 推广页）
            time.sleep(0.8)
            gone = self.focus().split("/", 1)[0]
            if gone and gone != self.app:
                self._launch(pkg, activity, settle, foreground)
        if self.expect_page(expect, budget):
            self.say(f"  · 退出非预期页面重进后，已落在 {pkg} 的预期页面")
            return
        self.say(self._landing_note(expect))
        raise RuntimeError(f"{pkg} 启动后停在非预期页面，跳过本段")

    def has_text(self):
        """这一屏读得到文字。半截 dump 解析失败时当作空白：空白不等于推广页。"""
        try:
            return bool(self.texts())
        except ET.ParseError:
            return False

    def expect_hits(self, expect):
        """这一屏命中了哪些判据词。给一段文字时按它自己算，不按字符拆。
        允许底栏「我的，有新消息」命中「我的」，不让标题「我的应用」命中（见 expect_match）。"""
        words = [expect] if isinstance(expect, str) else list(expect)
        items = [t for t, _, _ in self.texts()]
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
                               now=time.time, sleep=time.sleep, blocked=self.check_alive))

    def _landing_note(self, expect):
        """落点不对时的一条诊断：停在哪个前台、期望看到什么、实际命中了哪些判据，再给页面结构摘要。
        不打印页面文字，与 note_miss 同一风格。"""
        where, detail = self._page_diagnosis()
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

    def _launch(self, pkg, activity, settle, foreground):
        """发启动命令、等前台回到目标 App、顺手关掉可识别的弹窗。落点对不对由 start() 判。"""
        self.check_alive()
        self.miss = 0
        if activity:
            result = self.reader.shell(f"am start -f 0x10008000 -n {pkg}/{activity}")
        else:
            self._u2(self.reader.app_stop, pkg)
            result = self.reader.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        if result.exit_code or re.search(r"Error|Exception|No activities found|monkey aborted", result.output, re.I):
            # 同品牌参考脚本里的 App 本机可能没装或换了包名（#87 #165），说清楚，别报成打开失败。
            pm = self.reader.shell(f"pm path {pkg}").output
            if "package:" not in pm:
                # adb 断开时 pm path 也一样没有输出：先确认手机还在不在，
                # 别把断连报成「本机没有安装」，后面的段也据此快速跳过（#293）。
                if adb_link.client_gone(result.output + pm) or adb_link.lib_gone(result.output + pm) \
                        or adb_link.detached(self.serial):
                    self.lost = True
                    raise adb_link.lost((result.output or pm).strip())
                raise RuntimeError(f"本机没有安装 {pkg}，跳过本段")
            raise RuntimeError(f"无法打开 {pkg}：{result.output.strip()[-250:]}")
        deadline = time.monotonic() + 5
        expected = foreground or pkg
        while self.focus().split("/", 1)[0] != expected:
            if self.focus().split("/", 1)[0] in PERMISSION_CONTROLLERS:
                self.dismiss()
            if time.monotonic() >= deadline:
                # 带上落点（谁抢了前台、页面长什么样）：没有包名就分不清该加白名单还是改判据（#547）。
                where, detail = self._page_diagnosis()
                raise RuntimeError(f"{pkg} 没有进入前台，跳过本段（停在 {where}；{detail}）")
            time.sleep(0.2)
        def check_foreground():
            current = self.focus().split("/", 1)[0]
            # 权限申请可能在首页已出现后才弹出，也只能拒绝；不在其他 App 上找关闭按钮。
            if current in PERMISSION_CONTROLLERS:
                give_up_at = time.monotonic() + 3
                while current in PERMISSION_CONTROLLERS or not current:
                    if time.monotonic() >= give_up_at:
                        break
                    if current and not self.dismiss():
                        break
                    time.sleep(.2)
                    current = self.focus().split("/", 1)[0]
            if current != expected:
                # 同 #547：这条报错命中 79 份上报、51 个型号，缺的从来都是「是谁盖住了」。
                where, detail = self._page_diagnosis()
                raise RuntimeError(f"{pkg} 启动后离开前台，停止本段以免操作其他 App（停在 {where}；{detail}）")

        # 旧版商店冷启动可能暂时没有可读文字；空白不等于广告，不能盲按返回退出 App。
        t = time.time()
        while time.time() - t < 8:
            check_foreground()
            if self.texts():               # 一两个标签也可能是正常首页
                break
            self.dismiss()                # 仅尝试可识别的关闭 / 拒绝按钮
            time.sleep(.2)
        else:
            raise RuntimeError(f"{pkg} 启动后 8 秒仍读不到页面，停止本段；请确认首页已加载后重试")

        t = time.time()                    # 首屏加载较慢时，也要给引导/更新弹窗留下处理时间
        while time.time() - t < settle:
            check_foreground()
            self.dismiss()
            time.sleep(0.4)
        check_foreground()


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
        gone = adb_link.lost_from(e, a[1])     # 读屏库的断线异常不是 RuntimeError（错误日志 10-28）
        if gone is None:
            raise
        print(f"✗ {gone}", flush=True)
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
        if g.get("FAILED_STEPS"):
            print("未完成步骤：" + "、".join(g["FAILED_STEPS"]), flush=True)
            sys.exit(1)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
