# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

The repo adds two labels the five roles do not cover:

| Label in our tracker  | Meaning                                                                  |
| --------------------- | ------------------------------------------------------------------------ |
| `waiting-for-verify`  | Fix is merged to main but not in any released build yet, or merged and released but not yet confirmed on the reporter's hardware. Not ready to be implemented again. |
| `in-progress`         | Claimed: someone is implementing this now. Avoid starting the same fix.   |

`waiting-for-verify` outranks the five roles above — an issue carrying it must not also carry `ready-for-agent`, `ready-for-human`, or `needs-info`. It moves to a closed state only after the reporter confirms on a real device; the checks owed at each release are listed in [release-followup.md](release-followup.md).

`in-progress` is a claim, not a role: it stays out of the five-role set and must not coexist with `waiting-for-verify`. Claiming means adding `in-progress` and removing `ready-for-agent`, `ready-for-human`, and `needs-triage`. The claim survives an open, unmerged PR — the work is not in main yet, so someone else could redo it. It ends when the fix is merged to main: drop the label, or swap it for `waiting-for-verify` when real-device verification is owed. Abandoning a claim restores the previous `ready-*` or `needs-triage` label. The lifecycle is spelled out in [issue-tracker.md](issue-tracker.md).

## 分类标签

分类只有两个：`bug`（坏了）与 `enhancement`（新功能或改进）。**每张票必须恰好带其中一个。**

`新机型` 不是分类，是主题标签，用来标出「这台机器没有专用机型脚本」。它和 `enhancement` 同时出现是常态 —— 机型请求按 `enhancement` 处理，并保留 `新机型` 以便按主题检索；只有内容确实是报障（例如同一型号跑通了但某项没关掉）时才标 `bug`。

## Triage 与 grilling 的边界

需要 grilling 的票标 `needs-triage`，把待定的决定逐条写进票面；`/triage` 不自行发起 grilling，那一步由用户单独触发。

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.
