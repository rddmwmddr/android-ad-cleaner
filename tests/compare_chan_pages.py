"""改「认渠道页」时的对拍：同一份页面样本喂给两份 `tool/`，比较认页、进页与编排这三层。

样本取本仓库 `tests/` 里所有 `<hierarchy>` 字面量；基线取改动前的干净副本（钉改前那个提交，
不用会前进的 `origin/main`）：

    git archive e1a8001 | tar -x -C /tmp/aac-baseline
    python tests/compare_chan_pages.py /tmp/aac-baseline/tool

比四件事：
  `top_title()` —— 不依赖焦点；
  `channel_switch()` —— 样本页 × 两种屏尺寸 × 六种通知页焦点 × `Attempt.vivo_app` 取空 / 「示例应用」
    × 页面上出现的每个文字 + 「营销通知」；
  `via_app_page()` —— 同样本 × 两种屏尺寸 × 两种 vivo 焦点 × 页面上的前六个文字 + 「营销通知」，
    比返回值、卡在哪一环、记下的 App 名、点了几下、滑了几下；
  `toggle()` —— 九类编排场景 × 两种屏尺寸：直达 / 应用通知页 / 内联 / 同名放弃 / 截断 ID / vivo
    六条路线，加锁屏 / 读屏报错 / 断线三条失败路径。比结局与文案、发出哪些 `am start`、
    点在哪、滑了几下。页面坐标按屏宽高取比例，720 那一边才走得到同一条分支。
    `p.focus()` 的调用次数允许减少、不允许增加；dumpsys 走 `p.reader.shell`，已在 `shells` 里逐条比对。

结论不只看「相等」：驱动同时打印守卫数字（旧实现认出开关的组数、认得顶栏标题的组数、
进页真的点了行的组数，以及编排层每条分支各自走到几次），任一项为 0 就以非零退出——
样本或探针退化时「零差异」是必然相等，不能当证据。
两边各起一个子进程：模块名相同，同进程里 import 不了两份 chan_fast。
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SIZES = ((1080, 2340), (720, 1600))
FOCI = (
    "com.android.systemui/com.vivo.systemui.statusbar.notification.settings.channels.NotificationSettingsActivity",
    "com.vivo.systemuiplugin/com.vivo.systemui.statusbar.notification.settings.channels.NotificationSettingsActivity",
    "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity",
    "com.android.settings/.SubSettings",
    "com.oplus.notificationmanager/com.oplus.notificationmanager.ChannelNotificationSettingsActivity",
    "com.hihonor.systemmanager/com.hihonor.notificationmanager.ui.ChannelNotificationSettingsActivity",
)
VIVO_FOCI = FOCI[:2]

# ---------- 编排层的固定场景 ----------
# 认页层的样本喂不到 toggle()：深链发不发、失败后转不转应用通知页，都由编排层决定。
# 坐标按屏宽高取比例：硬编码 1080 时，720 那一边的开关落在屏外，六个场景会一起变成「没认出」，
# 守卫数字就不再证明走到了哪条分支。
DEEP_FOCUS = "com.android.settings/com.android.settings.Settings$ChannelNotificationSettingsActivity"
APP_FOCUS = "com.android.settings/com.android.settings.Settings$AppNotificationSettingsActivity"
PK, CID, NAME = "com.example.app", "promo", "营销通知"

# 页面元素的位置（屏宽高的比例），同时用来算守卫要的点击坐标
TITLE = (0, 0.0474, 1, 0.1538)
ALLOW_ROW = (0, 0.1628, 1, 0.2090)
ALLOW_TEXT = (0, 0.1697, 0.3167, 0.2021)
DEEP_SWITCH = (0.8111, 0.1628, 0.9444, 0.2090)
CHANNEL_ROW = (0, 0.2991, 1, 0.3675)
CHANNEL_TEXT = (0.0556, 0.3077, 0.6481, 0.3419)
INLINE_SWITCH = (0.8333, 0.3077, 0.9630, 0.3419)
SECOND_ROW = (0, 0.3846, 1, 0.4530)
SECOND_TEXT = (0.0556, 0.3932, 0.6481, 0.4274)
SECOND_SWITCH = (0.8333, 0.3932, 0.9630, 0.4274)


def box(size, area):
    x0, y0, x1, y1 = area
    w, h = size
    return f"[{round(x0 * w)},{round(y0 * h)}][{round(x1 * w)},{round(y1 * h)}]"


def centre(size, area):
    """节点中心，与 `Phone` 的 `bounds()` + 点击那两处的整数算法一致（不能先取中点再取整）。"""
    x0, y0, x1, y1 = area
    w, h = size
    l, t, r, b = round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)
    return (l + r) // 2, (t + b) // 2


def chan_pages(size):
    """四种页面：渠道页 / 应用通知页（导航行）/ 应用通知页（内联行）/ 两处同名。"""
    def text(value, area):
        return f'<node class="android.widget.TextView" text="{value}" bounds="{box(size, area)}"/>'

    def switch(area, checked=True):
        return ('<node class="android.widget.Switch" checkable="true"'
                f' checked="{str(checked).lower()}" bounds="{box(size, area)}"/>')

    def row(area, *children):
        return f'<node clickable="true" bounds="{box(size, area)}">' + "".join(children) + "</node>"

    def page(*nodes):
        return ('<hierarchy rotation="0"><node package="com.android.settings"'
                f' bounds="{box(size, (0, 0, 1, 1))}">' + "".join(nodes) + "</node></hierarchy>")

    allow = ('<node class="android.widget.Switch" text="开启" content-desc="开启" checkable="true"'
             f' checked="true" clickable="true" bounds="{box(size, DEEP_SWITCH)}"/>')
    return {
        # 渠道页：顶栏是渠道名，唯一开关在「允许通知」行
        "deep": page(text(NAME, TITLE), row(ALLOW_ROW, text("允许通知", ALLOW_TEXT), allow)),
        # 应用通知页：渠道行是导航行，点进去才是渠道页
        "app": page(text("示例应用", TITLE), row(CHANNEL_ROW, text(NAME, CHANNEL_TEXT))),
        # 应用通知页：渠道行自带开关
        "inline": page(text("示例应用", TITLE),
                       row(CHANNEL_ROW, text(NAME, CHANNEL_TEXT), switch(INLINE_SWITCH))),
        # 两处同名、都带开关：无法判断哪一行是渠道
        "same": page(text("示例应用", TITLE),
                     row(CHANNEL_ROW, text(NAME, CHANNEL_TEXT), switch(INLINE_SWITCH)),
                     row(SECOND_ROW, text(NAME, SECOND_TEXT), switch(SECOND_SWITCH, checked=False))),
    }


TOGGLE_SCENARIOS = (
    # 标签, 渠道 ID, Phone.vivo_seen, 焦点窗口, 页面序列（点击之后才换页）, 注入的故障
    ("direct", CID, False, DEEP_FOCUS, ("deep",), ""),
    ("app-page", CID, False, DEEP_FOCUS, ("app", "deep"), ""),
    ("inline", CID, False, APP_FOCUS, ("inline",), ""),
    ("same-name", CID, False, APP_FOCUS, ("same",), ""),
    ("truncated", "com.se...", False, APP_FOCUS, ("inline",), ""),
    ("vivo", CID, True, APP_FOCUS, ("inline",), ""),
    ("locked", CID, False, APP_FOCUS, ("inline",), "locked"),
    ("read-error", CID, False, APP_FOCUS, ("inline",), "read_error"),
    ("link-lost", CID, False, APP_FOCUS, ("inline",), "link_lost"),
)


def probe(tool):
    """喂一份 `tool/`，返回 {样本键: 这一组每一步的出口}。"""
    sys.path.insert(0, str(ROOT / "tool"))    # fixtures.load_tool() 见到它就不再插当前副本，免得混用两份 fast
    sys.path.insert(0, str(tool))
    sys.path.insert(1, str(TESTS))
    import chan_fast as chan
    from fixtures import all_pages, phone_stub

    def stub(xml, size, focus):
        p = phone_stub("probe", d=Mock())
        p.W, p.H = size
        p.focus = Mock(return_value=focus)
        root = ET.fromstring(xml)
        p.tree = Mock(return_value=root)
        p.locked = Mock(return_value=False)
        p.sig = Mock(return_value="")
        p.settle = Mock(return_value=True)
        p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
        p.click = Mock()
        return p

    out = {}
    chan.time.sleep = lambda _seconds: None      # 等待只为了真机；对拍里按次数走完就够
    for label, xml in all_pages(str(TESTS)):
        names = []
        for n in ET.fromstring(xml).iter("node"):
            t = (n.get("text") or n.get("content-desc") or "").strip()
            if t and t not in names:
                names.append(t)
        for size in SIZES:
            for focus in FOCI:
                for vivo_app in (None, "示例应用"):
                    for name in names[:12] + ["营销通知"]:
                        p = stub(xml, size, focus)
                        try:
                            sw = chan.channel_switch(p, name, chan.Attempt(vivo_app=vivo_app))
                        except Exception as e:          # noqa: BLE001 - 对拍要看到异常本身
                            sw = f"EXC:{type(e).__name__}"
                        key = f"switch|{label}|{size[0]}x{size[1]}|{focus.split('/')[0]}|{vivo_app}|{name}"
                        out[key] = [str(sw), str(chan.top_title(p, p.tree()))]
            for focus in VIVO_FOCI:
                for name in names[:6] + ["营销通知"]:
                    p, at = stub(xml, size, focus), chan.Attempt()
                    try:
                        got = chan.via_app_page(p, "com.example.app", name, at)
                    except Exception as e:          # noqa: BLE001
                        got = f"EXC:{type(e).__name__}"
                    key = f"via|{label}|{size[0]}x{size[1]}|{focus.split('/')[0]}|{name}"
                    out[key] = [str(got), at.stage, str(at.vivo_app), p.click.call_count, p.scroll.call_count]

    for label, cid, vivo, focus, keys, fault in TOGGLE_SCENARIOS:
        for size in SIZES:
            pages = [chan_pages(size)[k] for k in keys]
            index, reads = [0], [0]

            def tree(pages=pages, index=index):
                return ET.fromstring(pages[min(index[0], len(pages) - 1)])

            def click(*_args, pages=pages, index=index):
                index[0] = min(index[0] + 1, len(pages) - 1)

            def healthy(_p, cid=cid, reads=reads):
                reads[0] += 1
                # 第一次读到「开着」，点击之后读到「关着」：走完 DONE，不靠重试凑结局
                on = reads[0] == 1
                return {(PK, cid): (NAME, 3 if on else 0, False)}, {}

            faults = {
                # 锁屏在 toggle 开头就抛；读屏失败与断线从 parse 冒出来，看它落在哪一档收容
                "locked": Mock(side_effect=RuntimeError("unused")),
                "read_error": Mock(side_effect=RuntimeError("读不到通知渠道状态，停止操作")),
                "link_lost": Mock(side_effect=chan.adb_link.DeviceLost("probe 已断开")),
            }
            parse = faults.get(fault, Mock(side_effect=healthy))

            p = phone_stub("probe", d=Mock())
            p.W, p.H = size
            p.vivo_seen = vivo
            p.focus = Mock(return_value=focus)
            p.tree = tree
            p.click = Mock(side_effect=click)
            p.locked = Mock(return_value=fault == "locked")
            ticks = iter(range(10 ** 6))
            p.sig = Mock(side_effect=lambda: str(next(ticks)))
            p.settle = Mock(return_value=True)
            p.scroll, p.scroll_more = Mock(), Mock(return_value=False)
            p.confirm = Mock()
            p.reader = Mock()
            p.reader.shell.return_value = Mock(output="")
            with patch.object(chan, "parse", parse):
                try:
                    outcome = chan.toggle(p, PK, cid, False, NAME)
                    got = [outcome.kind, outcome.detail]
                except Exception as e:          # noqa: BLE001
                    got = [f"EXC:{type(e).__name__}", str(e)]
            key = f"toggle|{label}|{size[0]}x{size[1]}"
            out[key] = {
                "outcome": got,
                "shells": [str(a) for a in p.reader.shell.call_args_list],
                "clicks": [list(c.args) for c in p.click.call_args_list],
                "skips": [list(c.args) for c in p.scroll.call_args_list],
                "focus": p.focus.call_count,      # 只打印：调用次数不是对外契约
            }
    return out


def run(tool):
    return json.loads(subprocess.run([sys.executable, __file__, str(tool), "--dump"],
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout)


def main(argv):
    if len(argv) == 2 and argv[1] == "--dump":
        json.dump(probe(argv[0]), sys.stdout, ensure_ascii=False)
        return 0
    if len(argv) != 1:
        raise SystemExit("用法：python tests/compare_chan_pages.py <改动前的 tool 目录>")
    old, new = run(Path(argv[0]).resolve()), run(ROOT / "tool")
    assert old.keys() == new.keys(), "两边样本集不同"
    clicks = [v for k, v in old.items() if k.startswith("via|")]
    hits = sum(1 for k, v in old.items() if k.startswith("switch|") and v[0] != "None" and not v[0].startswith("EXC:"))
    titles = sum(1 for k, v in old.items() if k.startswith("switch|") and v[1] != "None")
    entered = sum(1 for v in clicks if v[3])
    toggle = {k: v for k, v in old.items() if k.startswith("toggle|")}
    if not (hits and titles and entered):
        raise SystemExit(f"对拍什么也没测到：认出开关 {hits} 组、认得顶栏标题 {titles} 组、进页点了行 {entered} 组")
    reached = branch_guards(toggle)
    missing = [label for label, count in reached.items() if not count]
    if missing:
        raise SystemExit("编排层没有一组真的走到这条分支：" + "、".join(missing)
                         + f"（各组 {reached}）")

    def same(a, b):
        return all(a[field] == b[field] for field in ("outcome", "shells", "clicks", "skips"))

    diff = {k: (old[k], new[k]) for k in old
            if k.startswith("toggle|") and not same(old[k], new[k])
            or not k.startswith("toggle|") and old[k] != new[k]}
    switch = {k: v for k, v in diff.items() if k.startswith("switch|") and v[0][0] != v[1][0]}
    via = {k: v for k, v in diff.items() if k.startswith("via|")}
    toggled = {k: v for k, v in diff.items() if k.startswith("toggle|")}
    focus = [k for k in toggle if old[k]["focus"] != new[k]["focus"]]
    focus_up = [k for k in focus if new[k]["focus"] > old[k]["focus"]]
    print(f"样本组 {len(old)}（认页 {len(old) - len(clicks) - len(toggle)}、进页 {len(clicks)}、编排 {len(toggle)}）；"
          f"旧实现认出开关 {hits} 组、认得顶栏标题 {titles} 组、进页点了行 {entered} 组")
    print("编排层分支各组走到 " + "、".join(f"{label} {count}" for label, count in reached.items()))
    print(f"top_title 不同 {len(diff) - len(switch) - len(via) - len(toggled)} 组，"
          f"channel_switch 不同 {len(switch)} 组，via_app_page 不同 {len(via)} 组，toggle 不同 {len(toggled)} 组")
    print(f"p.focus() 调用次数有变化 {len(focus)} 组（允许减少，不允许增加；dumpsys 走 p.reader.shell，已在 shells 里逐条比对）"
          + ("：" + "，".join(f"{k} {old[k]['focus']}→{new[k]['focus']}" for k in focus[:6]) if focus else ""))
    if focus_up:
        raise SystemExit("p.focus() 调用次数增加了：" + "、".join(focus_up[:6]))
    for k, (a, b) in list(switch.items())[:10] + list(via.items())[:10] + list(toggled.items())[:10]:
        print(f"  {k}\n    旧: {a}\n    新: {b}")
    return 0


def branch_guards(toggle):
    """每条编排分支都断言自己真的走到了：认出开关 / 点了渠道行 / 放弃 / 跳过深链 / 三种失败各一条。"""
    def switch_click(size):
        return list(centre(size, DEEP_SWITCH))

    def row_click(size):
        return list(centre(size, CHANNEL_TEXT))

    out = dict.fromkeys((label for label, *_ in TOGGLE_SCENARIOS), 0)
    for key, info in toggle.items():
        label = key.split("|")[1]
        w, h = (int(v) for v in key.split("|")[2].split("x"))
        kind, shells, clicks = info["outcome"][0], " ".join(info["shells"]), info["clicks"]
        if label == "direct":
            ok = kind == "done" and "CHANNEL_NOTIFICATION_SETTINGS" in shells and clicks[:1] == [switch_click((w, h))]
        elif label == "app-page":
            ok = kind == "done" and clicks[:2] == [row_click((w, h)), switch_click((w, h))]
        elif label == "inline":
            ok = (kind == "done" and "APP_NOTIFICATION_SETTINGS" not in shells
                  and clicks[:1] == [list(centre((w, h), INLINE_SWITCH))])
        elif label == "same-name":
            ok = kind == "not_confirmed" and not clicks
        elif label in ("truncated", "vivo"):
            ok = kind == "done" and "CHANNEL_NOTIFICATION_SETTINGS" not in shells
        elif label == "locked":
            ok = kind == "EXC:ScreenLocked"
        elif label == "read-error":
            ok = kind == "error"
        else:
            ok = kind == "EXC:DeviceLost"
        out[label] += ok
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
