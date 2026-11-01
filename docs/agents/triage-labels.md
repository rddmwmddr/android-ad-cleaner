# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

The repo adds one role the five do not cover:

| Label in our tracker  | Meaning                                                                  |
| --------------------- | ------------------------------------------------------------------------ |
| `waiting-for-verify`  | Fix is merged to main but not in any released build yet, or merged and released but not yet confirmed on the reporter's hardware. Not ready to be implemented again. |

`waiting-for-verify` outranks the five roles above — an issue carrying it must not also carry `ready-for-agent`, `ready-for-human`, or `needs-info`. It moves to a closed state only after the reporter confirms on a real device; the checks owed at each release are listed in [release-followup.md](release-followup.md).

## Triage 与 grilling 的边界

需要 grilling 的票标 `needs-triage`，把待定的决定逐条写进票面；`/triage` 不自行发起 grilling，那一步由用户单独触发。

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.
