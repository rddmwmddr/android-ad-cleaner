"""渠道页的到达决策：先走哪条路线、应用通知页上这一帧的下一步（#1435）。

输入是调用方已经读到的通知清单、一份屏幕快照与显式传入的进度，输出 `Intent`：本模块不读屏、
不点击，也不认识 `fast` / `phone.*` / `chan_fast`——`tests/test_rules_guards.py` 的
`ChannelDecideGuards` 守着。读 `snap.tree` 是允许的：认行、认分组与屏外名都在 `channel_decide`
里从同一棵树派生。

判定按帧分开：`route()` 决定第一段发哪些意图（渠道深链还是应用通知页深链）；`page_step()`
决定应用通知页上这一帧的下一步（点这一行 / 翻一页 / 交给认页 / 收场）；`after_click()` /
`after_scroll()` / `scroll_fallback()` 决定动作回来之后怎么收场。跨屏累积由调用方持有的
`Progress` 逐项传入传出。
"""
from dataclasses import dataclass
from enum import StrEnum

from channel_decide import candidates, group_floor, off_screen_name, top_title, vivo_page
from screen_snapshot import Intent, IntentKind, ScreenSnapshot

# 第一段的两种走法。`direct` 先发渠道深链再认页；`app_page` 直接走应用通知页。
DIRECT = "direct"
APP_PAGE = "app_page"

# 应用通知页最多看九帧（沿用 `ChannelPage._enter_app_page()` 的 `for _ in range(9)`）
PAGE_LIMIT = 9

CHANNEL_SETTINGS = "android.settings.CHANNEL_NOTIFICATION_SETTINGS"
APP_SETTINGS = "android.settings.APP_NOTIFICATION_SETTINGS"
APP_PACKAGE = "android.provider.extra.APP_PACKAGE"
CHANNEL_ID = "android.provider.extra.CHANNEL_ID"

# 收场时记进 `ChannelPage.stage` 的几段；文案与以前逐字相同
ROW_BOXES = "应用通知页这一行的开关没认出"
CLICK_NO_CHANGE = "点这一行后页面没变"
CLICK_NO_PAGE = "点进去后没认出渠道页"
LEFT_PAGE = "应用通知页翻页时离开了"


class StepAction(StrEnum):
    """应用通知页这一帧的下一步：三个动作与一个收场。"""
    TAP = "tap"
    RECOGNISE = "recognise"
    SCROLL = "scroll"
    STOP = "stop"


@dataclass(frozen=True)
class Route:
    """到这一页的第一段：走法与要依次下发的意图。"""
    way: str
    intents: tuple[Intent, ...]


@dataclass(frozen=True)
class Step:
    """这一帧的下一步：一个意图或一个不动作的收场，外加这一帧的事实与收场信号。

    `seen` 是收场用的结构信号（名字在这一页出现过没有），由 `Unreached.hidden` 派生；
    `vivo_app` 是这一帧之后记下的 App 名（#336）。
    """
    kind: StepAction
    intent: Intent | None = None
    stage: str = ""
    seen: bool = False
    vivo_app: str | None = None


def truncated(cid):
    """三星等系统会把长渠道 ID 缩略成 'com.se...'（#95）：不能当真实 ID 深链或去重。"""
    return cid.endswith(("...", "…"))


def channel_intent(pk, cid):
    """渠道页深链：NEW_TASK|CLEAR_TASK 避免复用旧渠道，仍需核对真实页面。"""
    return Intent(IntentKind.SETTINGS, target=CHANNEL_SETTINGS,
                  extras=((APP_PACKAGE, pk), (CHANNEL_ID, cid)))


def app_page_intent(pk):
    """应用通知页深链：渠道深链被拦截或不能直达时从这里进。"""
    return Intent(IntentKind.SETTINGS, target=APP_SETTINGS, extras=((APP_PACKAGE, pk),))


def route(channels, snap, *, pk, cid, vivo_seen=None):
    """到这一页的走法：能直达就直达，不能就走应用通知页。

    `channels` 是调用方已经读到的通知清单（`toggle()` 那次 parse），`snap` 是决策时手机停在
    那一帧的快照。今天判据只读两件事实：cid 被系统缩略了，或者这台机器的渠道页与应用通知页
    是同一个 Activity（vivo，`vivo_seen` 是它的累积、`snap` 是它的当场读法）。清单留着给
    下一个判据直接从已知事实里取，不必为到达再读一次 dumpsys。
    """
    same_activity = vivo_seen is True or (snap is not None
                                         and vivo_page(f"{snap.package}/{snap.activity}"))
    if truncated(cid) or same_activity:
        return Route(APP_PAGE, (app_page_intent(pk),))
    return Route(DIRECT, (channel_intent(pk, cid),))


def page_step(snap: ScreenSnapshot | None, *, name, vivo=False, alive=True, systemui_text=False,
              vivo_app=None, seen=False):
    """应用通知页这一帧的下一步。

    `alive` 是调用方刚读到的「前台还在这张通知页上」：不在就直接收场，那一帧的 `snap` 已经
    不是这一页了，不读。
    """
    if not alive or snap is None:
        return Step(StepAction.STOP, stage=LEFT_PAGE, seen=seen, vivo_app=vivo_app)
    seen = seen or any(hit.text == name for hit in snap.texts)
    floor = group_floor(snap) if vivo else None
    if vivo and vivo_app is None and floor is not None:
        # 这一屏有「类别」分组，说明是应用通知页：先记下 App 名。往下翻页后顶栏可能收起来（#336）
        vivo_app = top_title(snap, systemui_text)
    pending = candidates(snap, name, systemui_text=systemui_text, floor=floor)
    if pending:
        cand = pending[0]
        if not vivo and cand.boxes:
            # 内联开关：这一行不当作导航行点，交给认页（`recognise_inline`）
            return Step(StepAction.RECOGNISE, stage=ROW_BOXES, seen=seen, vivo_app=vivo_app)
        if vivo:
            # 同一次读屏里列表有这一行渠道，说明是总页：这时的顶栏才是 App 名（直达页可能还没退掉）。
            # 翻页后顶栏可能已经不在，先前记下的 App 名照样有效
            vivo_app = vivo_app or top_title(snap, systemui_text)
        l, t, r, btm = cand.bounds
        return Step(StepAction.TAP, intent=Intent(IntentKind.TAP, at=((l + r) // 2, (t + btm) // 2)),
                    seen=seen, vivo_app=vivo_app)
    return Step(StepAction.SCROLL, seen=seen, vivo_app=vivo_app)


def after_click(*, settled, vivo):
    """点完渠道行之后：vivo 进渠道页的转场慢，settle 等不到变化不代表没进去，照常认页；
    其余按「页面没变」收场。"""
    if not settled:
        return Step(StepAction.RECOGNISE if vivo else StepAction.STOP, stage=CLICK_NO_CHANGE)
    return Step(StepAction.RECOGNISE, stage=CLICK_NO_PAGE)


def scroll_fallback(snap, name, *, vivo):
    """`scroll_more()` 说翻不动时还能不能自己滑一页：vivo 的列表可能没标 scrollable，
    而渠道行已经读进 dump、坐标在屏下（#336）。"""
    return bool(vivo and off_screen_name(snap, name))


def after_scroll(*, stayed, moved=False):
    """自己翻完一页之后：页面被滑走了就收场，滑了没动就是到底了。"""
    if not stayed:
        return Step(StepAction.STOP, stage=LEFT_PAGE)
    if not moved:
        return Step(StepAction.STOP)
    return Step(StepAction.SCROLL)
