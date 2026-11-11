"""观测基座：读屏、认行、页面诊断、视口几何，以及四个动作原语（ADR-0033）。

构造时注入 `Connection`：读屏 adapter 与断线判定都只经它，不认识 `Phone`。
四个动作原语是 `click` / `back` / `settle` / `find`：后续五个阶段的模块一律经它们动作，
不直接碰传输。
"""
import re
import time
import xml.etree.ElementTree as ET

import uiautomator2 as u2

import wait
from row import bounds, control, dedupe, summary, switch_row, title_hit, unique
from troubleshooting import TAPPED, XIAOMI_INPUT, input_blocked


class Screen:
    """当前这一屏：文字、开关行、前台窗口、屏宽高。

    `systemui_text` 由它持有：`texts()` 是读屏最热路径，读的正是这个开关（ADR-0033）。
    """

    def __init__(self, conn):
        self.conn = conn
        self.systemui_text = False          # 读屏时是否算上 com.android.systemui 的文字（vivo OriginOS Ocean 的通知页就挂在那里）
        try:
            self.W, self.H = conn.reader.window_size()
        except u2.exceptions.UiAutomationError as e:
            raise conn.failure(e) from e
        except BaseException:
            conn.close()
            raise

    # ---------- 采样：读屏、页面状态与签名 ----------
    def tree(self):
        root = ET.fromstring(self.conn._u2(self.conn.reader.dump_hierarchy))
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

    def note_miss(self, text):
        """入口没找到时留下能定位的页面骨架，与渠道「未确认」日志同一风格。"""
        where, detail = self._page_diagnosis()
        self.conn.say(f"  · 「{text}」没找到；停在 {where}；{detail}")

    def page_evidence(self, titles=()):
        """点名要关的开关没找到时的现场：与 note_miss() 的入口失败行同形，末尾按页面顺序补上
        当次读到的开关标题（#903）。没有它分不清是改名了、页面是空的，还是页面根本没打开。

        `titles` 由调用方给（该翻的几屏已经读过了），这里不重读开关：
        自绘开关的页面每读一次开关就要截一次图。"""
        where, detail = self._page_diagnosis()
        names = list(titles)
        return f"停在 {where}；{detail}；当次读到 {len(names)} 个开关：{'、'.join(names) or '无'}"

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
