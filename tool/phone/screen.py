"""观测基座：读屏、认行、页面诊断、视口几何，以及动作原语（ADR-0033）。

构造时注入 `Connection`：读屏 adapter 与断线判定都只经它，不认识 `Phone`。
动作原语是 `click` / `back` / `settle` / `find`，翻页的 `scroll` / `scroll_more` 同在
这一层（拨动与导航都要翻页，不该由其中一方提供）。后续阶段一律经它们动作，不直接碰传输。
确认框的认法（`confirm_target`）也在这一层：拨动用它点掉遮罩，导航用它说清失败原因（#557），
两条路共用同一份匹配，谁也不依赖谁。
"""
import re
import time
import xml.etree.ElementTree as ET

import adb_link
import wait
from captures import Captures
from row import bounds, control, dedupe, summary, switch_row, title_hit, unique
from row import residual_note as confirm_note
from troubleshooting import TAPPED, XIAOMI_INPUT, input_blocked

# 确认框的按钮文字。认法在 `confirm_target()`：点开关后要再点一次才生效的对话框，按钮落在这些词里。
CONFIRM = ("确定", "確定", "关闭", "關閉", "仍要关闭", "仍要關閉", "确认关闭", "確認關閉",
           "确认", "確認", "继续关闭", "繼續關閉", "关闭推荐", "關閉推薦", "仍然关闭", "仍然關閉")

# 运行时权限页所在的包：启动侧靠它判「这一帧是不是权限页占着前台」，弹窗侧只在这类页上点拒绝。
PERMISSION_CONTROLLERS = {"com.android.permissioncontroller", "com.google.android.permissioncontroller"}

# 回顶的次数天花板（`scroll_top()`）。判据是「这一屏没有新文字」，这里只是防跑飞的兜底：
# 页面顶部有倒计时、轮播推广位这类会自己变的内容时那条判据永不成立，而没有上限就是一路滑下去
# （旧实现固定 4 次，不会挂住；#1094）。
TOP_SCREENS = 60


class Screen:
    """当前这一屏：文字、开关行、前台窗口、屏宽高。

    `systemui_text` 由它持有：`texts()` 是读屏最热路径，读的正是这个开关（ADR-0033）。
    """

    def __init__(self, conn, captures=None):
        self.conn = conn
        self.systemui_text = False          # 读屏时是否算上 com.android.systemui 的文字（vivo OriginOS Ocean 的通知页就挂在那里）
        self.dump = ""                      # 最近一次读屏原文（#1126）
        self.pending_capture = ""           # 两处留现场记下的这一屏，段失败时才落盘（#1126）
        self.captures = captures if captures is not None else Captures("")
        with conn.guarded():                # 读屏坏了：三种结局的翻译与收尾都在 Connection 那一份
            self.W, self.H = conn.reader.window_size()

    def say(self, *a):
        """一行诊断：五个阶段都经它说，日志开关仍归 `Connection`。"""
        self.conn.say(*a)

    # ---------- 采样：读屏、页面状态与签名 ----------
    def tree(self):
        self.dump = self.conn._u2(self.conn.reader.dump_hierarchy)
        root = ET.fromstring(self.dump)
        # Mi 10 的热榜子页会横屏；不能一直用连接时的竖屏尺寸过滤节点。
        self.W, self.H = self.conn._u2(self.conn.reader.window_size)
        return root

    def focus(self):
        """当前前台窗口：多数是 `包名/页面名`，锁屏 / 通知栏 / 输入法抢焦点时是裸窗口名，读不到返回空串
        （~0.1 秒；u2 的 app_current 在浮窗上会卡 10 秒）。判「还在不在这个 App」用 `split("/", 1)[0]`。
        不是聚焦控件，也不是焦点元素：判断有没有聚焦的输入框用 `edit_ready()`，读框里的文字用 `focused_text()`。"""
        self.conn.check_alive()
        # 不能加 grep -m / head：提前退出会让 dumpsys 收到 SIGPIPE，u2 判「shell output invalid」（#205）。
        # sed 读完整个流再截断，行数与原来一致。
        out = self.conn.reader.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | sed -n '1,4p'").output
        # vivo OriginOS 3 / Android 13 行尾是「Activity}}」（错误日志 10-27）。
        # 焦点窗口为 null 时看 mFocusedApp：华为 HarmonyOS 4.2、vivo OriginOS Ocean 页面明明在，以前报「停在 未知页面」（错误日志 10-29）
        for field in ("mCurrentFocus", "mFocusedApp"):
            m = re.search(field + r"=.*? u0 ([^\s}]+)", out)
            if m:
                return m.group(1)
        out = self.conn.reader.shell("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity|ResumedActivity:'"
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
        """[(标题, checked, (cx,cy))]，标题取开关所在行的第一段文字。落点是开关本体。"""
        return [(title, on, xy) for title, on, xy, hit in self.switch_rows(root)]

    def switch_rows(self, root=None):
        """[(标题, checked, 开关本体落点, 行标题落点)]：与 switches() 同一次遍历，多带标题落点。
        落点为 None 表示这一行没有独立标题（标题取自开关自己的标签）；`off()` 在开关本体
        点了不动时改点标题（#608）。"""
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
                            shot = self.conn.reader.screenshot()
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
            title, hit = title_hit(n, parent, self.on_screen, self.H)
            out.append((title, checked == "true", (l, t, r, b), hit))
        return [(title, on, ((l + r) // 2, (t + b) // 2), hit)
                for title, on, (l, t, r, b), hit in dedupe(out)]

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

    def sig(self):
        return "|".join(t for t, _, _ in self.texts())

    def ls(self):
        root = self.tree()
        print("·", self.focus())
        print(" / ".join(t for t, _, _ in self.texts(root)))
        for t, c, xy in self.switches(root):
            print(f"  [{'开' if c else '关'}] {t}  @{xy}")

    # ---------- 页面诊断 ----------
    def _page_diagnosis(self):
        """停在哪个 Activity、页面结构摘要（不含页面文字）：区分「没加载完」与「入口真的没了」。
        只吞页面解析失败；断线（DeviceLost）照常冒泡，不能被当成「页面没认出来」。"""
        where = self.focus() or "未知页面"
        try:
            detail = summary(self.tree(), self.W, self.H)
        except ET.ParseError:
            detail = "页面结构读不到"
        return where, detail

    def save_capture(self):
        """这一段的失败现场落盘：由段包装在段真的失败时调，取走 `note_miss()` / `page_evidence()`
        记下的那一屏。入口探路也会走 `note_miss()`（`entry()` 找不到可选入口只返回假，不是失败），
        那时一个字节都不写，也不会盖掉上一轮真正失败留下的现场。

        内容不进日志、不随上报发送：只写客户端的数据目录，路径也不打印（上报的日志会带上用户目录）。
        没给捕获目录时同样不写；写不进去不算失败，现场丢了不能盖掉原来那句报错。"""
        page, self.pending_capture = self.pending_capture, ""
        if page:
            self.captures.save(page, (self.W, self.H))

    def note_miss(self, text):
        """入口没找到时留下能定位的页面骨架，与渠道「未确认」日志同一风格。"""
        where, detail = self._page_diagnosis()
        self.pending_capture = self.dump
        self.conn.say(f"  · 「{text}」没找到；停在 {where}；{detail}")

    def page_evidence(self, titles=()):
        """点名要关的开关没找到时的现场：与 note_miss() 的入口失败行同形，末尾按页面顺序补上
        当次读到的开关标题（#903）。没有它分不清是改名了、页面是空的，还是页面根本没打开。

        `titles` 由调用方给（该翻的几屏已经读过了），这里不重读开关：
        自绘开关的页面每读一次开关就要截一次图。"""
        where, detail = self._page_diagnosis()
        self.pending_capture = self.dump
        names = list(titles)
        return f"停在 {where}；{detail}；当次读到 {len(names)} 个开关：{'、'.join(names) or '无'}"

    def confirm_target(self, root=None):
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

    def residual_confirm(self, root=None):
        """屏上还挂着没被点掉的确认框时返回确认按钮的文字，没有返回 None。

        查找失败时用它补一句原因：整页读不到行常常是遮罩挡着，而不是这一版没适配（#557）。
        只读不点，弹窗留着不动。读页读不到也按「没有确认框」算：这是失败路径上的诊断，
        它抛错会把脚本里大量 `if p.tap(...)` 的可选探测一起打断；只有断线照常冒泡。"""
        try:
            found = self.confirm_target(root)
        except adb_link.DeviceLost:
            raise
        except Exception:
            return None
        return found[0] if found else None

    def residual_note(self, sep="——", root=None):
        """查找失败时挂在说明后面的那句「屏上还挂着没点掉的确认框「X」」；没有确认框时是空串。
        句子本身是 `row.residual_note()` 的纯函数，这里只负责读一次屏（导航与拨动共用这一份）。"""
        return confirm_note(self.residual_confirm(root), sep)

    def icon_candidates(self, area=(0.72, 0.0, 1.0, 0.16)):
        """没有文字、点了才知道去哪的图标（右上角齿轮、更多）：按位置从右往左给候选坐标。
        整块卡片/列表项点了会进别的页面，按尺寸排除掉。"""
        x0, y0, x1, y1 = (v * s for v, s in zip(area, (self.W, self.H, self.W, self.H), strict=True))    # area 是 (x0,y0,x1,y1)
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

    # ---------- 四个动作原语（后续阶段一律经它们动作） ----------
    def click(self, x, y):
        size = self.conn._u2(self.conn.reader.window_size)
        if tuple(size) != (self.W, self.H):
            self.W, self.H = size
            raise RuntimeError("屏幕方向或尺寸已变化，停止使用旧坐标；请重新读取页面")
        if not (0 <= x < self.W and 0 <= y < self.H):
            raise RuntimeError("点击坐标在屏幕外，未操作")
        out = self.conn.reader.shell(f"input swipe {x} {y} {x} {y} 80").output   # 有的 App 吞 input tap
        if input_blocked(out):
            raise RuntimeError(f"系统拒绝了{TAPPED}。" + XIAOMI_INPUT)

    def back(self, n=1):
        for _ in range(n):
            b = self.sig()
            self.conn.reader.shell("input keyevent BACK")
            self.settle(b, 0.6)

    def settle(self, before, maxwait=0.8):
        """等新的非空页面稳定；跳页动画中的空树不算已经加载好。"""
        return bool(wait.until(self.sig, maxwait, poll=0.1, stable=0.2,
                               changed_from=before, now=time.time, sleep=time.sleep))

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
        self.conn.reader.shell(";".join(c))
        time.sleep(0.15)

    def scroll_more(self):
        """翻一页；翻完没出现新文字（到底、回弹）返回 False。拨动与导航都经它翻页。"""
        if not any(n.get("scrollable") == "true" and self.on_screen(n) for n in self.tree().iter("node")):
            return False                       # 单屏面板上滑动可能直接关掉页面
        focus = self.focus()
        before = {t for t, _, _ in self.texts()}
        self.scroll()
        if self.focus() != focus:
            raise RuntimeError("翻页离开了当前设置页，停止本段以免操作其他 App")
        after = {t for t, _, _ in self.texts()}
        return not after <= before

    def scroll_top(self, n=None):
        """回到页顶：一直上滑到这一屏不再出现新文字为止，与 `scroll_more()` 的终止条件对称。

        次数不按固定值定：219 个开关的页面要翻十几屏才回得去，写死几次只到半路（#1094）。
        `n` 是调用方给的次数上限（「翻着找入口」那种有余量的兜底）；不给时仍有 `TOP_SCREENS`
        那道天花板，它只是防跑飞、不是判据。判据与 `scroll_more()` 同一份：同名行占满整屏的
        页面里它也判不出列表还在不在动，会提前收手——`scroll_more()` 在那里同样停手。
        单屏 / 不滚动的页面零动作：`scroll_more()` 的早退判据在这里先问一遍，
        上滑手势在单屏面板上可能直接关掉页面。中途离开当前页照旧抛，不静默继续。"""
        limit = TOP_SCREENS if n is None else n
        scrolled = 0
        while scrolled < limit:
            if not any(m.get("scrollable") == "true" and self.on_screen(m) for m in self.tree().iter("node")):
                break
            focus = self.focus()
            before = {t for t, _, _ in self.texts()}
            self.scroll(0.58, up=True)
            scrolled += 1
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
