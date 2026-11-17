"""渠道批处理的策略：一项的结局、第一遍队列、第二遍的门槛与挑行、收尾复查的豁免与记账。

`chan_fast.run()` 的 off / on 分支以前把这几条判断写在循环里，只能跑一整批看输出。
这里收成值类型与纯函数：都吃通知清单（`ChannelList`）与清单项，不读屏、不点击、也不认识
`fast` / `phone.*` / `chan_fast`（`tests/test_rules_guards.py` 的 `ChannelDecideGuards` 守着）。
点击、adb 往返与打印留在 `chan_fast`。

结局词表（`OutcomeKind` 与 `RULES`）也住这里：它是一批渠道的记账口径，不是执行壳的一部分。
`chan_fast` 显式 re-export 那些名字，`tests/test_channel_outcomes.py` 与渲染照旧经它取。
"""
from dataclasses import dataclass, replace
from enum import StrEnum

from channel_policy import protected_channel
from screen_snapshot import ChannelEntry, ChannelList

RETRY_MAX = 10      # 第二遍最多重试这么多项：再多说明这一批根本没被认出，白等一轮


class OutcomeKind(StrEnum):
    DONE = "done"                          # 达成目标（关掉或还原）
    GREYED = "greyed"                      # 系统锁定了这个渠道：开关是灰的，点了也不会变
    APP_DENIED = "app_denied"              # 应用通知整体关闭（POST_NOTIFICATIONS 被拒），渠道不会弹出
    PROTECTED = "protected"                # 找机位一类功能通知，不动
    NO_CHANNEL = "no_channel"              # 清单里的渠道在手机上不存在
    DELETED = "deleted"                    # 渠道已删除
    APP_OFF = "app_off"                    # 应用通知总开关关着
    ALREADY = "already"                    # 本来就是目标状态，不打印
    CONFIRMED_LATER = "confirmed_later"    # 第二遍重扫才确认其实已经改好
    NOT_CONFIRMED = "not_confirmed"        # 页面没认出，或重取时页面已变化
    APP_STATE_UNKNOWN = "app_state_unknown"    # 应用通知页认出来了，总开关状态却读不出来：判断不了是不是整体关闭
    UI_HIDDEN = "ui_hidden"                # 页面打得开、页面上确实没有这一行：系统没把它放到界面上
    MISMATCH = "mismatch"                  # 界面状态与渠道实际状态不一致
    UNCHANGED = "unchanged"                # 点了三次，渠道状态仍未改变
    ERROR = "error"                        # 意外异常，原文进 detail


# 模块级名字照旧可用（用例与渲染都取 `chan_fast.DONE`）。别名与成员同名，
# 改名要两处一起动，ChannelOutcomeGuards 对得上才算数。
DONE = OutcomeKind.DONE
GREYED = OutcomeKind.GREYED
APP_DENIED = OutcomeKind.APP_DENIED
PROTECTED = OutcomeKind.PROTECTED
NO_CHANNEL = OutcomeKind.NO_CHANNEL
DELETED = OutcomeKind.DELETED
APP_OFF = OutcomeKind.APP_OFF
ALREADY = OutcomeKind.ALREADY
CONFIRMED_LATER = OutcomeKind.CONFIRMED_LATER
NOT_CONFIRMED = OutcomeKind.NOT_CONFIRMED
APP_STATE_UNKNOWN = OutcomeKind.APP_STATE_UNKNOWN
UI_HIDDEN = OutcomeKind.UI_HIDDEN
MISMATCH = OutcomeKind.MISMATCH
UNCHANGED = OutcomeKind.UNCHANGED
ERROR = OutcomeKind.ERROR


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    detail: str = ""
    payload: str = ""        # 进上报日志的机器行（页面骨架等），不参与判读


# 怎么记账由这一张表决定，不由返回值的形状暗示。键是结局，值是它对整批的四件事：
# fail_close / fail_open —— 关 / 开的方向上算不算失败（渠道已删除在还原时才算失败）；
# retry —— 页面慢可能造成的失败，一批跑完再试一次；
# toggled —— 算不算「实际拨动了」，用于「拨了 N 个」；
# exempt —— 收尾复查时豁免（系统锁定、应总开关关着，本来就不会变）。
# 渲染在 chan_fast.render()，是另一个问题：同一结局在不同方向下说法不同。
RULES = {
    DONE: dict(fail_close=False, fail_open=False, retry=False, toggled=True, exempt=False),
    GREYED: dict(fail_close=False, fail_open=False, retry=False, toggled=False, exempt=True),
    APP_DENIED: dict(fail_close=False, fail_open=False, retry=False, toggled=False, exempt=True),
    PROTECTED: dict(fail_close=False, fail_open=False, retry=False, toggled=False, exempt=False),
    NO_CHANNEL: dict(fail_close=True, fail_open=True, retry=False, toggled=False, exempt=False),
    DELETED: dict(fail_close=False, fail_open=True, retry=False, toggled=False, exempt=False),
    APP_OFF: dict(fail_close=False, fail_open=True, retry=False, toggled=False, exempt=False),
    ALREADY: dict(fail_close=False, fail_open=False, retry=False, toggled=False, exempt=False),
    CONFIRMED_LATER: dict(fail_close=False, fail_open=False, retry=False, toggled=True, exempt=False),
    NOT_CONFIRMED: dict(fail_close=True, fail_open=True, retry=True, toggled=False, exempt=False),
    # 记账与 NOT_CONFIRMED 相同：关不关得掉取决于没读到的那个状态，既不能算成功也不能记名单。
    APP_STATE_UNKNOWN: dict(fail_close=True, fail_open=True, retry=True, toggled=False, exempt=False),
    # 本机 UI 上根本没有这个渠道的入口：关不掉，重试也是同一个页面，收尾复查也不该算「仍开着」。
    UI_HIDDEN: dict(fail_close=False, fail_open=True, retry=False, toggled=False, exempt=True),
    MISMATCH: dict(fail_close=True, fail_open=True, retry=False, toggled=False, exempt=False),
    UNCHANGED: dict(fail_close=True, fail_open=True, retry=True, toggled=False, exempt=False),
    ERROR: dict(fail_close=True, fail_open=True, retry=False, toggled=False, exempt=False),
}
KINDS = tuple(RULES)


# 下面四个谓词与后面的 `account()` 都直接读 `RULES`：表只有这一份，单键读取与整行投影
# 是同一份数据的两条通路，不是第二份实现，别为「统一」再加一层间接。
def failed(outcome, want_on=False):
    """这一项要不要算进退出码。"""
    return RULES[outcome.kind]["fail_open" if want_on else "fail_close"]


def retryable(outcome):
    return RULES[outcome.kind]["retry"]


def toggled(outcome):
    return RULES[outcome.kind]["toggled"]


def exempt_from_recheck(outcome):
    """收尾复查时不算「仍开着」：系统锁定的渠道点不动，应用通知整体关着的渠道不会弹。"""
    return RULES[outcome.kind]["exempt"]


def kind_of_state(st):
    """state() 的读数 → 结局：清单里的渠道不存在 / 已删除 / 应用通知总开关关着。"""
    return {"--": NO_CHANNEL, "del": DELETED, "app": APP_OFF}[st]


def channel_list_of(channels, app_off):
    """`parse()` 的返回形状 → 到达决策要的通知清单：toggle 已经读过，不再读一次 dumpsys。"""
    return ChannelList(channels={key: ChannelEntry(*value) for key, value in channels.items()},
                       app_off=dict(app_off), locked=frozenset(), foreground=frozenset())


def state(channels, pk, cid):
    """一项在通知清单里的读数：`--` 不存在 / `off` 已屏蔽 / `del` 已删除 / `app` 应用通知关着 / `ON`。"""
    entry = channels.channels.get((pk, cid))
    if entry is None:
        return "--"
    if entry.importance == 0:
        return "off"
    if entry.deleted:
        return "del"
    if channels.app_off.get(pk):
        return "app"
    return "ON"


# ---------- 第一遍：清单 → 队列 ----------

@dataclass(frozen=True)
class Pending:
    """清单里的一项，连同它这一轮的处理方式；`outcome is None` 表示要打开手机去拨。"""
    pk: str
    cid: str
    label: str
    outcome: Outcome | None = None

    @property
    def queued(self):
        return self.outcome is None

    @property
    def item(self):
        return self.pk, self.cid, self.label


def plan_queue(items, channels, want_on):
    """第一遍：每项要么当场给结局（受保护 / 不存在 / 已删除 / 应用通知关着 / 已是目标态），
    要么进待拨队列。顺序与清单一致；结局的判定顺序也照旧：受保护先于状态。"""
    planned = []
    for pk, cid, label in items:
        st = state(channels, pk, cid)
        entry = channels.channels.get((pk, cid))
        if not want_on and protected_channel(entry.name if entry else "", cid, label):
            outcome = Outcome(PROTECTED, f"当前状态 {st}")
        elif st in ("--", "del", "app"):
            outcome = Outcome(kind_of_state(st))
        elif (st == "off") != (not want_on):
            planned.append(Pending(pk, cid, label))
            continue
        else:
            outcome = Outcome(ALREADY)       # 已经是目标状态，不打印
        planned.append(Pending(pk, cid, label, outcome))
    return tuple(planned)


# ---------- 第二遍：跑不跑、挑谁 ----------

def second_pass(*, halted, started, retry, reached):
    """第二遍跑不跑。页面加载慢时一次没认出（错误日志 10-28：关了 93 个剩 1 个，整步算失败）；
    这台已经关成功过才重试，华为那种一个都认不出的不重试，免得白等。"""
    if halted or not started or not retry or len(retry) > RETRY_MAX:
        return False
    return bool(reached or len(retry) <= 2)


@dataclass(frozen=True)
class RetryPlan:
    """重扫之后：其实已经改好的那些（不再拨），与真正要重新入队的那些。"""
    confirmed: tuple[Pending, ...]
    queue: tuple[Pending, ...]


def pick_retry(retry, channels, want_on):
    """重扫一遍通知清单，把「重试轮到谁」分成两组：已经改好的记 `CONFIRMED_LATER`，
    其余重新入队。判据与 `state()` 同一条，方向跟着关 / 开走。"""
    confirmed, queue = [], []
    for pk, cid, label in retry:
        pending = Pending(pk, cid, label)
        if (state(channels, pk, cid) == "off") == (not want_on):
            confirmed.append(replace(pending, outcome=Outcome(CONFIRMED_LATER)))
        else:
            queue.append(pending)
    return RetryPlan(tuple(confirmed), tuple(queue))


# ---------- 记账与收尾复查 ----------

@dataclass(frozen=True)
class Credit:
    """一个结局对整批的四件事，取自 `RULES`；`failure` 已经按方向选好。"""
    failure: bool
    retry: bool
    toggled: bool
    exempt: bool


def account(outcome, want_on):
    """「拨了 N 个 / 失败数 / 要不要重试 / 复查是否豁免」的记账投影。"""
    row = RULES[outcome.kind]
    return Credit(failure=row["fail_open" if want_on else "fail_close"],
                  retry=row["retry"], toggled=row["toggled"], exempt=row["exempt"])


@dataclass(frozen=True)
class Recheck:
    """收尾复查里一项的读数：状态、是否受保护、还算不算「仍开着」。"""
    state: str
    protected: bool
    still_open: bool


def recheck_row(channels, pk, cid, label, exemptions):
    """收尾复查：仍开着 = 记录是 ON、不是受保护渠道、也不在本批豁免名单里。"""
    st = state(channels, pk, cid)
    entry = channels.channels.get((pk, cid))
    protected = protected_channel(entry.name if entry else "", cid, label)
    return Recheck(st, protected, st == "ON" and not protected and (pk, cid) not in exemptions)
