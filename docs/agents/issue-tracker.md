# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations. <!-- rule:doc.tracker.gh-cli-for-everything -->

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies. <!-- rule:doc.tracker.issue-command-recipes -->
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## 票的生命周期

- **开工前先有票**：任何实现 / 重构 / 文档改造，先对应一个 GitHub issue；没有就先开票，分支名带 issue 号（`feat/<描述>-<issue>`）。实现完再补票等于跳过了 spec 与 triage，PR 会被当成无源改动。CI 的 `ticket-ref` job 在 PR 上核这两处对得上：分支名以 `-<票号>` 结尾，正文有 `Refs #N` / `Closes #N` 且是同一张；同 `dco` / `conventional`，只让问题可见，不阻断合并。 <!-- rule:doc.issue.ticket-before-work -->
- **认领即出池**：动第一行代码之前跑 `python3 tool/claim.py <N>`。它按票下的认领评论仲裁，再写一条认领评论、加 `in-progress`、摘掉 `ready-for-agent` / `ready-for-human` / `needs-triage`。仲裁只看未收尾的认领，`Record.created`（服务器时间）最早的一条赢；同 identity 重复认领是幂等的 reaffirm，不追加评论。身份是 `sha1(<主机名>\0<worktree 绝对路径>)` 的前 8 位，主机名只进哈希，认领评论里只出现这 8 位——公开 issue 上不出现本机主机名与目录；同一个 GitHub 账号下的两路会话因此也分得开。
- **三种结局各是一个退出码**：0 认领到手（含本会话已持有），2 被别人占，3 `gh` 调用失败；其余拒绝（票已关闭、票面读不出确定结局、收尾时本会话没有未收尾认领、命令行不合规）都是 1。拿到 2 就停下上报、不自动改挑别的票；拿到 1 不要猜，照消息处理。
- **认领记录是评论，标签只是可见信号**：认领落在票下一条固定格式的评论里（`gh issue view <N> --comments` 就能看到），标签写失败只是 advisory，不改认领的结局。两路会话同时读到空票时都会写出评论，写完后 `claim.py` 重读一次，最早的那条赢、后写的那条撤回自己——仍不是原子的，极小窗口里两条会同时立住，看评论时间就能判。
- **合入就是边界**：开了 PR 也不算做完——PR 开着没合并时改动没进 main，别人仍可能拿同一张票再做一遍。 <!-- rule:doc.issue.merge-is-the-boundary -->
- **`in-progress` 留到合入 main 才摘**：收尾只有两个时机——合入 main 且不需要真机复测就 `python3 tool/claim.py <N> --release`；合入 main 但等真机复测就 `--release` 再挂 `waiting-for-verify`（`in-progress` 与它不并存）。`--release` 不恢复 `ready-*`。 <!-- rule:doc.issue.in-progress-until-merge -->
- **弃单要恢复原状**：放弃或改派时跑 `python3 tool/claim.py <N> --abandon`：它写放弃评论、摘掉 `in-progress`，并把认领评论里记下的 `ready-*` / `needs-triage` 加回（`--restore <标签>` 可覆盖），票面再补一句为什么停——否则标签烂在票上，下一个会话不敢碰。 <!-- rule:doc.issue.abandon-restores-labels -->
- **票号从返回值取**：并行会话会占用按顺序推出来的编号。开票后照 `gh issue create` 打印的 URL 取号，互链等内容建完再回填。 <!-- rule:doc.issue.number-from-output -->
- **关票判据**：实现合入 main 就关，不等发版；挂着 `waiting-for-verify` 的那种凭证据关，见下一条。票里没做的 Follow-up 不拖着这张票：转进对应的跟踪票（例：候选项进 #334），并在关闭说明里写清转到哪里。 <!-- rule:doc.issue.close-on-merge -->
- **凭证据关**：挂着 `waiting-for-verify` 的票，证据够了就关，不必等报告者回话。三种证据都采信，但档位不同：**有用例** —— 一条去掉这次改动就会红的用例（旧树红、新树绿，维护者自己就能复核；判据复用 [CODING_STANDARDS.md](../../CODING_STANDARDS.md) 的「行为变化要有测试直接守住」）；**有现场** —— 报告者贴的 dump / 日志 / 输出里症状已经不再出现，能在 issue 里核对，比口头确认硬一档；**报告者口头确认** —— 只有一句「好了」，一样据此关票，但记录时写成报告者自述，不写成「已确认」。关票评论要能让人复核：有用例就写出用例位置（`tests/<文件>::<用例>`），有现场就贴出那条输出，口头确认就写明是报告者自述。带 `blocked-on-device` 的票先摘标再谈关：缺的是那台机器上的行为，维护者这边的用例证明不了它。 <!-- rule:doc.issue.close-on-evidence -->
- **`stale` 是可见信号，不是处置**：`needs-info` 的票末评不是报告者、且已满 14 天（一条评论都没有时从开票起算）时，`python3 tool/stale.py` 每日扫描给它打上 `stale` 并留一条说明，报告者回话后摘掉；带 `in-progress` / `waiting-for-verify` / `blocked-on-device` 的票不参与。它不改变票的角色，也不构成关票依据——关不关仍按「关票判据」那条判断。认领时一并摘掉它，`--abandon` 不把它加回来。
- **票即 spec**：开票时把 grilling 定下的**全部**交付物写进「方案」段——代码、文档、ADR、术语——Spec 审查只认票面。漏写会让审查把已批准的东西报成 scope creep。 <!-- rule:doc.issue.ticket-is-spec -->

## Pull requests as a triage surface

**PRs as a request surface: yes.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

外部 PR 和 issue 走同一套状态，但**处置方式按类型分**： <!-- rule:doc.pr.same-states-split-by-kind -->

- **机型/清单类**（只碰 `recipes/`、`docs/清单/`、`tests/`、`CHANGELOG.md`、README 机型表）：CI 过 + 三查即可合并。三查： <!-- rule:doc.pr.device-pr-three-checks -->
  - 关开关用 `p.off()`，不在配方里自己逐个点开关；
  - 确认框用引擎的 `p.confirm()`，默认不自己写确认 helper；确需绕过的机型要在脚本注释里写明 `p.confirm()` 为什么不适用。它的保证只有四条：优先只点 Button 类节点；Button 自身没有文字时，下级节点整段等于 `CONFIRM`（`tool/phone/screen.py`）里的词也算；一个 Button 都没命中时，退到可点击、按钮级尺寸（宽 < 0.5W、高 < 0.12H）的 TextView；跳过屏外节点。它不判断弹窗是否存在——页面上任何整段标着「关闭」「确定」的 Button 或这样的 TextView 都可能被点到，所以不能把它当成「确认框已经出现」的证据。引擎自己也是这个口径：`off()` 连点前会借同一份匹配避开遮罩（看到就先点掉再继续），那同样只是「可能有遮罩」，不是弹窗的判定；
  - CHANGELOG / README 机型表 / 清单三处齐。
- **核心行为类**（碰 `tool/`、`gui/`、`AGENTS.md`、架构）：采纳分析，按本仓库的模型重新实现，不整单合并。口径见 [docs/09](../09-社区问题处理.md) 的「相关 PR 的采用范围」。 <!-- rule:doc.pr.core-pr-reimplement -->

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`). <!-- rule:doc.pr.triage-filter -->
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`. <!-- rule:doc.pr.shared-number-space -->

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets. <!-- rule:doc.wayfinder.protocol -->

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
