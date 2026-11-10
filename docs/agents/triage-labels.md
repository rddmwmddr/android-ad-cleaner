# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

The repo adds three labels the five roles do not cover:

| Label in our tracker  | Meaning                                                                  |
| --------------------- | ------------------------------------------------------------------------ |
| `waiting-for-verify`  | Fix is merged to main but not in any released build yet, or merged and released but not yet confirmed on the reporter's hardware. Not ready to be implemented again. |
| `in-progress`         | Claimed: someone is implementing this now. Avoid starting the same fix.   |
| `stale`               | Modifier on a `needs-info` ticket: the last comment is not the reporter's and the threshold has passed. Not a role, and not a reason to close. |

`waiting-for-verify` outranks the five roles above — an issue carrying it must not also carry `ready-for-agent`, `ready-for-human`, or `needs-info`. It moves to a closed state only after the reporter confirms on a real device; the checks owed at each release are listed in [release-followup.md](release-followup.md). <!-- rule:doc.triage.waiting-for-verify-outranks -->

`in-progress` is a claim, not a role: it stays out of the five-role set and must not coexist with `waiting-for-verify`. The claim itself is recorded as a comment on the issue — `python3 tool/claim.py <N>` writes it — and the label is only the visible signal. When to add it, when it ends, and what to restore when a claim is abandoned are in [issue-tracker.md](issue-tracker.md) 的「票的生命周期」. <!-- rule:doc.triage.in-progress-is-a-claim -->

`stale` 是修饰符，不是第六个角色：它和角色标签并存，不改变票属于哪个角色，也不构成关票依据——关不关仍由维护者按现有信息判断。加标与摘标的时机、认领时的处置只在 [issue-tracker.md](issue-tracker.md) 的「票的生命周期」里定义。 <!-- rule:doc.triage.stale-is-a-modifier -->

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table. <!-- rule:doc.triage.five-roles-map -->

## 分类标签

分类只有两个：`bug`（坏了）与 `enhancement`（新功能或改进）。**每张票必须恰好带其中一个。** <!-- rule:doc.triage.one-category-label -->

`新机型` 不是分类，是主题标签，用来标出「这台机器没有专用机型脚本」。它和 `enhancement` 同时出现是常态 —— 机型请求按 `enhancement` 处理，并保留 `新机型` 以便按主题检索；只有内容确实是报障（例如同一型号跑通了但某项没关掉）时才标 `bug`。 <!-- rule:doc.triage.new-device-is-a-topic -->

## 标签登记

上面两表与「分类标签」一节提到的标签收在这一张表里，`tool/triage_audit.py` 的 `KNOWN` 与它逐项对拍，脚本只是镜像。最后七个沿用 GitHub 的默认标签，不算分类 —— `documentation` 也一样。`/wayfinder` 建的票带 `wayfinder:*`，第一次出现时登记进来。

| Label                 | 归属                                        |
| --------------------- | ------------------------------------------- |
| `needs-triage`        | 五角色                                      |
| `needs-info`          | 五角色                                      |
| `ready-for-agent`     | 五角色                                      |
| `ready-for-human`     | 五角色                                      |
| `wontfix`             | 五角色                                      |
| `waiting-for-verify`  | 状态（压过五角色）                          |
| `in-progress`         | 状态（认领）                                |
| `stale`               | 修饰符（只挂在 `needs-info` 上）            |
| `bug`                 | 分类                                        |
| `enhancement`         | 分类                                        |
| `新机型`              | 主题                                        |
| `documentation`       | 默认标签，不是分类                          |
| `accessibility`       | 默认标签，不是分类                          |
| `duplicate`           | 默认标签，不是分类                          |
| `good first issue`    | 默认标签，不是分类                          |
| `help wanted`         | 默认标签，不是分类                          |
| `invalid`             | 默认标签，不是分类                          |
| `question`            | 默认标签，不是分类                          |

## Triage 与 grilling 的边界

需要 grilling 的票标 `needs-triage`，把待定的决定逐条写进票面；`/triage` 不自行发起 grilling，那一步由用户单独触发。 <!-- rule:doc.triage.grilling-boundary -->
