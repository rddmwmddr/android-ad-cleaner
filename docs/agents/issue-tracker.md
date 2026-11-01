# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## 票的生命周期

- **开工前先有票**：任何实现 / 重构 / 文档改造，先对应一个 GitHub issue；没有就先开票，分支名带 issue 号（`feat/<描述>-<issue>`）。实现完再补票等于跳过了 spec 与 triage，PR 会被当成无源改动。
- **票号从返回值取**：并行会话会占用按顺序推出来的编号。开票后照 `gh issue create` 打印的 URL 取号，互链等内容建完再回填。
- **关票判据**：实现合入 main 就关，不等发版、不等真机（需要真机复测的修复是例外，见 `docs/09` 与 `waiting-for-verify`）。票里没做的 Follow-up 不拖着这张票：转进对应的跟踪票（例：候选项进 #334），并在关闭说明里写清转到哪里。
- **票即 spec**：开票时把 grilling 定下的**全部**交付物写进「方案」段——代码、文档、ADR、术语——Spec 审查只认票面。漏写会让审查把已批准的东西报成 scope creep。

## Pull requests as a triage surface

**PRs as a request surface: yes.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

外部 PR 和 issue 走同一套状态，但**处置方式按类型分**：

- **机型/清单类**（只碰 `recipes/`、`docs/清单/`、`tests/`、`CHANGELOG.md`、README 机型表）：CI 过 + 三查即可合并。三查：
  - 关开关用 `p.off()`，不在配方里自己逐个点开关；
  - 确认框用引擎的 `p.confirm()`，默认不自己写确认 helper；确需绕过的机型要在脚本注释里写明 `p.confirm()` 为什么不适用。它的保证只有三条：只点 Button 类节点；Button 自身没有文字时，下级节点整段等于 `CONFIRM`（`tool/fast.py`）里的词也算；跳过屏外节点。它不判断弹窗是否存在——页面上任何整段标着「关闭」「确定」的 Button 都可能被点到，所以不能把它当成「确认框已经出现」的证据；
  - CHANGELOG / README 机型表 / 清单三处齐。
- **核心行为类**（碰 `tool/`、`gui/`、`AGENTS.md`、架构）：采纳分析，按本仓库的模型重新实现，不整单合并。口径见 [docs/09](../09-社区问题处理.md) 的「相关 PR 的采用范围」。

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
