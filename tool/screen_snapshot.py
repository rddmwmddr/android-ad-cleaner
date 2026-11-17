"""屏幕快照、通知清单、意图与进度：基座交出的四份值（#1432）。

一次读屏产出一份 `ScreenSnapshot`（行、文字、前台包与 Activity、屏宽高、文字签名、还能不能往下滚），
`ChannelList` 是通知清单那一份独立的数据源。对设备的一个动作收成 `Intent`，由 `Screen.apply()`
按种类分派到基座的动作原语；`Progress` 跨帧累积、由循环显式传出，**不进**快照。
只认标题 / 认行的调用点传 `with_rows=False`：不算行也就不给自绘开关截图，`rows` 留空。

纯数据与纯构造：本模块不读屏、不点击，也不认识 `fast` / `phone` / `chan_fast`（避免环）。
行与文字的取法仍只有一份：`Screen.texts()` / `Screen.switch_rows()` 与快照都经这里的
`text_hits()` / `switch_row_data()`，三处逐项同源。`Screen.snapshot()` 只读一次树、一次前台，
自绘开关需要截图时由调用方注入取图函数（`snapshot_from_tree(..., screenshot=…)`）。

按包探测的通知权限状态与 appops 模式不在这里：它们是一次额外 adb 往返，不随快照提前读。
"""
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from row import LISTS, bounds, control, dedupe, disabled_at, title_hit, unique

# 前台服务常驻通知的标记（#459）。13 及以前叫 mFgServiceShown，14 起框架改名为
# mUserVisibleTaskShown（置位条件也从 FLAG_FOREGROUND_SERVICE 扩到 isFgsOrUij()，
# 含机主发起的任务）。两个名字都认，否则新系统上这条排除静默不生效。
FG_SERVICE_MARKS = ("mFgServiceShown=true", "mUserVisibleTaskShown=true")

# 自绘开关的截图惰性取一次：`_UNSET` 是「还没取」，`_NO_SHOT` 是「纯构造没有取图函数」
_UNSET = object()
_NO_SHOT = object()


class IntentKind(StrEnum):
    """对设备的动作种类；等待与重试不属于意图。"""
    TAP = "tap"
    SCROLL = "scroll"
    BACK = "back"
    OPEN = "open"
    HOME = "home"
    TYPE = "type"
    SETTINGS = "settings"      # 按 action + extras 拉起系统设置页（渠道页 / 应用通知页）


@dataclass(frozen=True)
class Row:
    """一屏里带开关的那一行：标题、开关本体 bounds、开关态、可点、是否灰。"""
    title: str
    bounds: tuple[int, int, int, int]
    checked: bool | None = None
    clickable: bool = False
    disabled: bool = False


@dataclass(frozen=True)
class TextHit:
    """屏上的一段可见文字与它的 bounds。"""
    text: str
    bounds: tuple[int, int, int, int]


@dataclass(frozen=True)
class ScreenSnapshot:
    """一次读屏解析出的事实，不含动作、不含历史。

    `tree` 是解析出的页面树本身：认页要沿祖先链找行容器、按 resource-id 认页眉、判断屏外名，
    这些 `rows` / `texts` 表示不出来。它不参与 JSON 往返与相等比较，由 `with_tree()` 装回。
    """
    package: str
    activity: str
    width: int
    height: int
    rows: tuple[Row, ...]
    texts: tuple[TextHit, ...]
    signature: str
    can_scroll: bool
    tree: object | None = field(default=None, compare=False, repr=False)

    def to_json(self):
        return {
            "package": self.package,
            "activity": self.activity,
            "width": self.width,
            "height": self.height,
            "rows": [{"title": row.title, "bounds": list(row.bounds), "checked": row.checked,
                      "clickable": row.clickable, "disabled": row.disabled} for row in self.rows],
            "texts": [{"text": hit.text, "bounds": list(hit.bounds)} for hit in self.texts],
            "signature": self.signature,
            "can_scroll": self.can_scroll,
        }

    @classmethod
    def from_json(cls, data):
        return cls(
            package=data["package"],
            activity=data["activity"],
            width=data["width"],
            height=data["height"],
            rows=tuple(Row(title=row["title"], bounds=tuple(row["bounds"]),
                           checked=row.get("checked"), clickable=row.get("clickable", False),
                           disabled=row.get("disabled", False)) for row in data.get("rows", ())),
            texts=tuple(TextHit(text=hit["text"], bounds=tuple(hit["bounds"]))
                        for hit in data.get("texts", ())),
            signature=data["signature"],
            can_scroll=data["can_scroll"],
        )

    def with_tree(self, root):
        """把页面树装回快照；快照 JSON 往返后 `tree` 是 None，认页前用它补齐。"""
        return replace(self, tree=root)


@dataclass(frozen=True)
class ChannelEntry:
    """通知清单里的一条渠道记录。"""
    name: str
    importance: int
    deleted: bool


@dataclass(frozen=True)
class ChannelList:
    """通知清单那一份数据源，与屏幕快照分开：它来自 dumpsys notification，不是当前这一屏。"""
    channels: Mapping[tuple[str, str], ChannelEntry]
    app_off: Mapping[str, bool]
    locked: frozenset[tuple[str, str]]
    foreground: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class Intent:
    """对设备的一个动作；等待与重试不在这里。

    `extras` 是 `SETTINGS` 要逐个下发的 `--es` 键值对（有序）；其余种类留空。
    """
    kind: IntentKind
    at: tuple[int, int] | None = None
    text: str = ""
    target: str = ""
    extras: tuple[tuple[str, str], ...] = ()

    def to_json(self):
        return {"kind": self.kind.value,
                "at": None if self.at is None else list(self.at),
                "text": self.text,
                "target": self.target,
                "extras": [list(pair) for pair in self.extras]}

    @classmethod
    def from_json(cls, data):
        at = data.get("at")
        return cls(kind=IntentKind(data["kind"]),
                   at=None if at is None else tuple(at),
                   text=data.get("text", ""),
                   target=data.get("target", ""),
                   extras=tuple(tuple(pair) for pair in data.get("extras", ())))


@dataclass
class Progress:
    """跨帧累积的进度，由循环显式传出；它不是一屏的事实，所以不进快照。

    `tapped` / `failed_ways` 是本票只建的接缝，消费方在后面（#1432 的验收面）；今天没有读取方，
    所以引擎也不再往里写值。
    """
    tapped: set[str] = field(default_factory=set)
    pages: int = 0
    last_signature: str = ""
    failed_ways: set[str] = field(default_factory=set)


# ---------- 从页面树取事实：与 Screen 的读屏方法同源 ----------

def on_screen(node, width, height):
    """折叠屏合上时，dump 里还留着内屏那份节点，坐标在外屏之外（Issue #2）；点上去没反应。"""
    if node.get("visible-to-user") == "false":
        return False
    l, t, r, b = bounds(node)
    cx, cy = (l + r) // 2, (t + b) // 2
    return r > l and b > t and 0 <= cx < width and 0 <= cy < height


def text_hits(root, width, height, systemui_text=False):
    """[(文字, bounds, 节点)]：`Screen.texts()` 与屏幕快照共用的那一份筛选。"""
    out = []
    # 华为 HarmonyOS 4 把同一个控件吐出两次；按节点身份数行时会变成「同名 2 行」（#510）
    for n in unique(root.iter("node")):
        if n.get("package") == "com.android.systemui" and not systemui_text:
            continue                      # 状态栏/通知栏文字不算
        t = (n.get("text") or n.get("content-desc") or "").strip()
        if t and on_screen(n, width, height):
            out.append((t, bounds(n), n))
    return out


def can_scroll(root):
    """这一屏还能不能往下滚：有节点标了可滚动，或出现列表容器类名。"""
    return any(n.get("scrollable") == "true" or LISTS.search(n.get("class") or "")
               for n in root.iter("node"))


def pixel_on(img, l, t, r, b):
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


def _self_drawn_on(shot, width, height, box):
    """自绘开关按轨道颜色判；尺寸对不上就当未知（shot 为 None 时照旧在 .size 上抛，与旧实现一致）。"""
    if shot.size != (width, height):
        return None
    return pixel_on(shot, *box)


def switch_row_data(root, width, height, screenshot=None):
    """[(标题, checked, 开关本体 bounds, 标题落点, 控件节点)]，已经过 `dedupe`。

    `Screen.switch_rows()` 与屏幕快照共用这一份规则；自绘开关按颜色判断时要截图，
    取图函数由调用方注入，不给就跳过那一支（纯构造不碰设备）。
    """
    parent = {c: p for p in root.iter() for c in p}

    def shown(n):
        return on_screen(n, width, height)

    out = []
    shot = _UNSET
    for n in unique(root.iter("node")):
        if not shown(n) or "RadioButton" in n.get("class", ""):
            continue
        if n.get("checkable") != "true":
            rid = (n.get("resource-id") or "").lower()
            # 自绘开关：看颜色；TextSwitcher 是文字轮播。里面已经有真开关的（AOSP 渠道页的 main_switch_bar）不算：
            # 按颜色猜出的状态会盖过里面那个真开关，关着的渠道被读成开着，还原营销通知失败（0.3.1 发版前模拟器发现）
            if ("switch" in rid and "switcher" not in rid and n.get("clickable") == "true"
                    and not any(c is not n and c.get("checkable") == "true" for c in n.iter("node"))):
                l, t, r, b = bounds(n)
                if r - l > 0 and b - t > 0:
                    if shot is _UNSET:
                        # 纯构造不给取图函数时按「没有这一支」处理；给了就照旧取一次（真机截图不会是 None）
                        shot = screenshot() if screenshot is not None else _NO_SHOT
                    if shot is _NO_SHOT:
                        continue
                    # UI 坐标与截图可能来自不同分辨率/旋转状态。不能越界取样，也不能把未知状态当关。
                    on = _self_drawn_on(shot, width, height, (l, t, r, b))
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
        if r - l <= 0 or b - t <= 0 or not shown(n):
            continue
        ctrl = control(n, shown)       # 卡片整体 checkable 时点在卡片中心不生效
        l, t, r, b = bounds(ctrl)
        # 卡片自己报状态时以卡片为准；缺这个属性才读内层开关，别把缺属性当成「关」
        checked = n.get("checked") if n.get("checked") is not None else ctrl.get("checked")
        title, hit = title_hit(n, parent, shown, height)
        out.append((title, checked == "true", (l, t, r, b), hit, ctrl))
    return dedupe(out)


def switch_rows(root, width, height, screenshot=None):
    """[(标题, checked, 开关本体中心, 标题落点)]；`Screen.switch_rows()` 的返回形状。"""
    return [(title, on, ((l + r) // 2, (t + b) // 2), hit)
            for title, on, (l, t, r, b), hit, _ in switch_row_data(root, width, height, screenshot)]


def rows_from_tree(root, width, height, screenshot=None):
    rows = []
    for title, on, (l, t, r, b), _, ctrl in switch_row_data(root, width, height, screenshot):
        rows.append(Row(title=title, bounds=(l, t, r, b), checked=on,
                        clickable=ctrl.get("clickable") == "true" or ctrl.get("checkable") == "true",
                        disabled=disabled_at(root, ((l + r) // 2, (t + b) // 2))))
    return tuple(rows)


def snapshot_from_tree(root, width, height, focus, systemui_text=False, *,
                       with_rows=True, screenshot=None):
    """把一份页面树装配成快照：不读屏、不点击。

    `Screen.snapshot()` 与用例里的 `ET.fromstring(dump)` 都走它，装配只此一处。
    `with_rows=False` 时不算开关行：自绘开关要在这一步截图，只认标题 / 认行的路径不该多截一张。
    """
    package, sep, activity = focus.partition("/")
    hits = text_hits(root, width, height, systemui_text)
    return ScreenSnapshot(
        package=package,
        activity=activity if sep else "",
        width=width,
        height=height,
        rows=rows_from_tree(root, width, height, screenshot) if with_rows else (),
        texts=tuple(TextHit(text=t, bounds=b) for t, b, _ in hits),
        signature="|".join(t for t, _, _ in hits),
        can_scroll=can_scroll(root),
        tree=root,
    )


# ---------- 通知清单：dumpsys notification 的解析与读取 ----------

def parse_notification_dump(text):
    """dumpsys notification --noredact 的原文 → (channels, app_off, locked, foreground)。

    只取机主空间（user 0）。双开、分身、隐私空间、安全文件夹的同名应用 UID 不同（#95），
    以前按包名混在一起：界面已关，回读却拿到另一空间的「开」。
    locked 收集系统不允许关闭的渠道（系统应用固定通知权限、渠道本身不可屏蔽，#134）；
    foreground 收集前台服务的常驻通知渠道（#459）。两份都只收当前文本里的证据。
    """
    # 安卓 8 / 9 的段名是「per-package config:」（RankingHelper），10 起是「PackagePreferences:」（#258 海信 Android 9）
    start = next((k for k in (text.find("PackagePreferences:"), text.find("per-package config:")) if k >= 0), -1)
    if start < 0:
        raise RuntimeError("读不到通知渠道状态，停止操作；请检查 USB 调试连接和系统权限")
    text = text[start:]
    cur, fixed, app_off, channels = None, False, {}, {}
    locked, foreground = set(), set()
    for line in text.splitlines():
        m = re.match(r"\s*AppSettings: (\S+)(?: \((\d+)\))?", line)
        if m:
            cur = m.group(1) if not m.group(2) or int(m.group(2)) < 100000 else None
            fixed = "fixedImportance=true" in line
            if cur:
                app_off[cur] = "importance=NONE" in line
            continue
        m = re.search(r"NotificationChannel\{mId='(.*?)', mName=(.*?), mDescription=.*?mImportance=(-?\d+).*?mDeleted=(\w+)", line)
        if m and cur:
            # 同一渠道可能带尾随空格回读两次（#194 纵横读屏）：键统一去掉空格，否则清单行
            # 查不到状态。两条读数矛盾时取「开着」的那条，宁可多关一次也不漏关；
            # 已删除的记录不覆盖有效记录。只有重要性 0 是已屏蔽，其余值都按开着算（同 state()）。
            key = (cur, m.group(1).strip())
            importance, deleted = int(m.group(3)), m.group(4) == "true"
            old = channels.get(key)
            if (old is None or (old[2] and not deleted)
                    or (old[2] == deleted and old[1] == 0 and importance != 0)):
                channels[key] = (m.group(2).strip(), importance, deleted)
            # 两条读数对「系统锁定」说法不一时按锁定处理：跳过比误关安全，且与回读顺序无关。
            # 已删除的记录不参与判断，它的锁定信息不可信。
            if fixed and not deleted and "mBlockableSystem=false" in line:
                locked.add(key)
            # 同一渠道的两条读数（#194）任一说是前台服务就算：方向与上面的 locked 一致，宁可少关。
            if not deleted and any(mark in line for mark in FG_SERVICE_MARKS):
                foreground.add(key)
    return channels, app_off, locked, foreground


def read_channel_list(reader):
    """一次 dumpsys notification --noredact 读出整份通知清单。"""
    text = reader.shell("dumpsys notification --noredact", timeout=60).output
    channels, app_off, locked, foreground = parse_notification_dump(text)
    return ChannelList(channels={key: ChannelEntry(*value) for key, value in channels.items()},
                       app_off=app_off, locked=frozenset(locked), foreground=frozenset(foreground))
