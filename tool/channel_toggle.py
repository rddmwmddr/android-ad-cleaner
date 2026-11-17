"""渠道拨动的决定：一行开关（或一份屏幕快照）进来，这一行点不点、点完算不算成、要不要撤回（#1436）。

单次拨动今天是一次「重认 → 点 → 重读 → 核」的循环；这里只留判断，吃快照上的事实、吐出决定。
纯函数：不读屏、不点击、也不认识 `fast` / `phone.*` / `chan_fast`——`tests/test_rules_guards.py`
的 `ChannelDecideGuards` 守着。读 `snap.tree` 是允许的：判灰仍走 `row.disabled_at()` 那一份。

时间不在这里：退避多久、循环几次都留在执行侧，`verdict()` 只按 `attempt` 与传入的 `tries` 数次数。
结局文案逐字照旧（`VANISHED_DETAIL`），记账仍由调用方的 `RULES` 决定。
"""
from dataclasses import dataclass
from enum import StrEnum

from row import disabled_at
from screen_snapshot import Row

VANISHED_DETAIL = "渠道页或开关已变化，停止操作"


class ToggleVerdict(StrEnum):
    """点完重读之后的下一步：成 / 不一致 / 应用通知整体关 / 再试 / 放弃。"""
    DONE = "done"
    MISMATCH = "mismatch"
    APP_DENIED = "app_denied"
    RETRY = "retry"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class SideEffect:
    """点击后出现了别的变化：整批停止；只有点过这一行才点回去。"""
    stop: bool
    undo: bool


def row_of(switch):
    """认出的一行开关 → 判断用的 `Row`：拨动的决定只读这一行，不必为它再读一次屏。"""
    title, checked, (x, y) = switch
    return Row(title=title, bounds=(x, y, x, y), checked=checked, clickable=True)


def can_click(row, want_on):
    """这一行要不要点：已经是目标态就不点。"""
    return row.checked != want_on


def greyed(snapshot, xy):
    """落点是不是灰掉的开关（系统锁定）：点了也不会变。判据只有一份，仍在 `row.disabled_at()`。"""
    if snapshot.tree is None:
        raise ValueError("判灰要页面树：先用 ScreenSnapshot.with_tree() 把 tree 装回")
    return disabled_at(snapshot.tree, xy)


def verdict(row, channel_state, want_on, attempt, *, tries, denied=None):
    """点完重读之后的决定，不表达时间：重认次数由调用方传，退避时长也留在那里。

    `row` 是这一轮重认到的那一行（与点击同一帧）；`attempt` 从 0 数。
    界面这一行已经是目标态时才分得出 APP_DENIED 与 MISMATCH，`denied` 由调用方在那个分支下
    多读一次应用通知总开关。
    """
    if channel_state == ("ON" if want_on else "off"):
        return ToggleVerdict.DONE
    if row.checked == want_on:
        return ToggleVerdict.APP_DENIED if denied else ToggleVerdict.MISMATCH
    return ToggleVerdict.RETRY if attempt + 1 < tries else ToggleVerdict.UNCHANGED


def vanished(reached):
    """点后重认不到这一行（页面已变化或从列表消失）：不算已关，这一项停下来报未确认。"""
    return not reached


def side_effect_verdict(extra, clicked):
    """点击后目标渠道之外还有变化：整批停止；只有点过这一行才点回去。"""
    stop = bool(extra)
    return SideEffect(stop=stop, undo=stop and clicked)
