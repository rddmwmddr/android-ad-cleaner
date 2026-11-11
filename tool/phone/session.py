"""三个跨阶段会话状态：丢失记录、启动会话、渠道会话（ADR-0033、#1039）。

它们本来只是碰巧对齐在同一个 `self` 上的裸字段：寿命与写者各不相同，却长得像普通属性。
门面用显式属性 + 赋值器转发到这里的对象，搬漏的名字必须当场 AttributeError（不走 `__getattr__`）。
集合字段转发的是对象本体，转发成拷贝会让 `p.promoted.clear()` 静默失效。
"""


class LostNote:
    """丢失记录：导航、启动、设置搜索写，拨动读。

    `miss` 是「本段已经没找到几次」——`entry`（导航）、`Launcher._launch`（启动）、`setting`（设置搜索）
    进入新段落前清零，`tap` / `entry` 找不到时累加；`off()`（拨动）按 `miss > 0` 判「路径对不上，只看当前一屏」。
    `missed` 是本次没拨到目标态的 `(页面, 标题)`，由 `off()` 记，`off()` 与 `report_run()` 读；
    与 `changed` 同源、同生命周期（#788）。
    """

    def __init__(self):
        self.miss = 0
        self.missed = []


class LaunchSession:
    """启动会话：由启动写、被弹窗读。

    `app` 是最近一次 `start()` 拉起的目标 App，`start()` 写、`Dismisser.promoted_click()`（弹窗一侧）读，
    用来判「点了 ✕ 之后跳走的是不是推广位」。
    `promoted` 是点过才发现是推广位的 ✕，同一处不再点第二次（#420）：`start()` 换 App 时清空，
    `Dismisser.promoted_click()` 记下。
    """

    def __init__(self):
        self.app = ""
        self.promoted = set()


class ChannelSession:
    """渠道会话：运行时只有渠道判定（`chan_fast`）读写它，测试与 fixtures 直接配置。

    四个字段都借住在 `Phone` 上，因为渠道页与应用通知页共用同一个 Activity。
    `systemui_text` 不在这里：`texts()` 是读屏最热路径，它留在 `Screen`。
    """

    def __init__(self):
        self.vivo_seen = False              # 见过 vivo 的通知页：只从应用列表进
        self.skeleton_sigs = set()          # 本次运行已上报的骨架布局（#428）：同布局只留第一份
        self.skeleton_count = 0             # 本次运行已上报的骨架份数，上限见 chan_fast.SKELETON_PER_RUN
        self.mismatch_probes = 0            # 本次运行已补的 MISMATCH 判据读数，上限见 chan_fast.MISMATCH_PER_RUN
