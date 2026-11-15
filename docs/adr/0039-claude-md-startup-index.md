# `CLAUDE.md` 是启动索引：函数级细节归 `docs/ARCHITECTURE.md`

基线 `bdc9dfe`。父票 #1320，来源是本机调研 `.private/research/2026-11-15-rules-guards-claude-md-slimming.md` 的 C2b 一段。

`CLAUDE.md` 被每个会话的每个请求自动加载，是这个仓库最大的一笔固定上下文开销：38,263 B / 100 行，其中规则行占 89%。32 条带规则锚点的「找「…」先看 …」/「改「…」先看 …」是导航索引，合计 19,520 B（不含行尾换行），占规则行字节的 57%。它们回答的是「这件事的唯一实现住哪、哪些函数不能另写一份」。

`docs/ARCHITECTURE.md` §三的模块表已经给出了模块级的同一答案——`row.py` 是「开关所属的那一行的唯一定义」，`channel_policy.py` 是渠道判定的七组，`recipe_lib/` 一行同时给了家族归属、守卫位置与 `(p, rt, …)`。`CLAUDE.md` 多出来的只是函数级那一层：`line` / `own` / `title_of` / `title_hit` / `dedupe` / `control` 各管什么。**「哪个模块拥有它」已有单一来源，「哪个函数负责它」还没有**，这是这次要补上的落点。

## Decision

### 哪一类规则必须自包含

**判据：在没有任何工具调用时就要让 agent 停手或改道。** 这类规则留在 `CLAUDE.md`，外移的风险是 agent 根本不会去读那份文档：

- `dev.workspace.worktree-only`：不许在主副本切分支、丢改动；
- `dev.git.rebase-before-push`：推送前先 rebase，否则 PR 直接 `CONFLICTING`；
- `dev.git.dco-signoff`、`dev.git.conventional-commits`：提交那一刻就带着走；
- `doc.issue.claim-command`：开工第一条命令。

反过来，「`row.py` 的 `title_hit` 是 `off()` 的回退落点」不必在开工时就知道：agent 改 `row.py` 时会打开 `tool/row.py`，它缺的是「别处还有一份、不许另写」的提醒，而模块表给的正是这个。

### 落点：§三 新增一小节，正文逐字搬

27 条函数级导航行搬进 `docs/ARCHITECTURE.md` §三的 `### 函数级细节`，逐字搬（仓库内 markdown 链接改成代码段，ADR 链接改成 `docs/` 下的相对路径），`<!-- rule:<id> -->` 锚点随正文走，`rules.toml` 的 `source` 从 `CLAUDE.md#开发` 改成 `docs/ARCHITECTURE.md#函数级细节`。规则条目本身一条不动：`id` / `check` / `status` / `why` / `expires_if` 全部原样，149 条仍是 149 条。

判据是「§三 的模块表有没有它的落点」。留在这边的 5 条不是模块归属，§三 里没有它们的位置：

| 留下的 | 为什么不是模块归属 |
|---|---|
| `doc.rules.registry-indexes-prose` | 规则注册表自身怎么维护 |
| `dev.tests.frontend-harness` | `tests/js/` 的跑法 |
| `doc.tutorial.brand-taps-single-source` | `docs/手机版教程/brand-taps.json` 这一份数据 |
| `doc.site.shared-stylesheet` | 仓库根 `site.css` |
| `dev.android.smoke-entry` | `android/smoke.py` 的操作流程（真机试跑怎么走），不是某个函数的归属 |

`## 开发` 开头留一行总指针，措辞写明不可删：它是 agent 找到那一节的唯一入口。指针点名的范围按**搬走了什么**写（`tool/` / `gui/` / `android/` / `recipe_lib/`），不只是 `tool/` 与 `gui/`——被搬的有 `dev.android.*` 与 `dev.recipes.*`，只写前两个的话，改 `aac_android/u2.py` 的人拿不到这条指针。

### 为什么一行指针够用

1. **`CLAUDE.md` 本来就满篇指针。** 「判断标准在 `CODING_STANDARDS.md`」「发版流程见 `docs/agents/release.md`」「上报归类见 `docs/09`」——文档级外移是它现有的工作方式，不是这次新引入的风险。
2. **改模块的 agent 本来就会打开 `ARCHITECTURE.md`。** §一至 §三 是宿主、契约与模块边界的单一来源，`docs/04` 也指向它；函数级细节放在同一个文件的同一节里，不需要多一次跳转。
3. **漏读的失败模式已经有机械守卫。** 不读索引最坏的结果是写出第二份实现：搬走的 27 条里 13 条 `enforced`（`test:` 目标）、11 条 `code`（点名的符号），`tests/test_recipe_nav.py` 另外卡同名助手出现在 ≥2 台机型。只有 3 条 `manual` 没有机械守卫，它们讲的是风格（词库口径之类），错一份不会静默。
4. **指针行自己不可删。** 删掉它，`tests/test_rules_registry.py` 的第四条不变式不会红（锚点都还在注册表指的地方），但那条不变式本来就管不到「agent 会不会去读」——所以这条约束写在正文里，并挂在 `## 开发` 的第一段。

## Considered Options

- **C2c：全量外移成一份生成的 `docs/agents/index.md`**（否）。省的是 19,520 B 而不是 16,033 B，多出来的正是那 5 条非模块归属的行；代价是「没有任何机制保证 agent 会读它」，等于把索引降级成可选阅读。
- **先写数据源、再渲染出索引导航**（否）。27 条正文是人写的散文，`rules.toml` 里没有对应字段；要生成就得先把散文搬进数据文件，那是把同一个动作包了一层脚本。
- **在 `### 函数级细节` 里按主题加小标题分组**（否）。不省字节，而且 `section_of()` 只认锚点所在的最内层标题，分组会把一个 `source` 拆成好几个小节名。
- **把导航行改短、只留模块名**（否）。函数名列表是唯一记录「哪些函数别另写一份」的地方，删了就是回到 `dev.row.single-definition` 之前的状态。
- **整个 `## 开发` 都改成指针**（否）。留下的是判据与守卫本身（回归命令、解释器版本、DCO、Conventional Commits、CHANGELOG 口径），它们要么在开工时就要停手，要么没有第二处记载。

## Consequences

- `CLAUDE.md` 38,263 B / 100 行 → 22,583 B / 75 行（−15,680 B，−41%）。票面写的「约 20,600 B / −46%」是按「32 条导航行 19,520 B 减掉 5 条必留规则约 1,850 B」估的，但那 5 条不是导航行、不在 19,520 B 里，实际搬走的是 27 条导航行 16,033 B。
- `docs/ARCHITECTURE.md` 13,566 B → 29,261 B，多出「函数级细节」一节。它不在启动路径，读它的成本只落在真正改模块的那次会话上。
- 守卫跟着改两处：`tests/test_rules_guards.py` 的 `UNANCHORED_BOUND` 新增 `docs/ARCHITECTURE.md: 8`（§四、§五原有的流程叙述，均为锚点之外的正文）；`tests/test_doc_consistency.py` 的 `HostWordingDocTests` 把 `CLAUDE.md` 移出名单——它不再讲宿主取词，也就没有「跟着说」的义务。
- `docs/agents/code-review.md` 的规范轴多读一份 `docs/ARCHITECTURE.md`：27 条里 24 条有机械守卫，但审查仍要看见它们。
- `CONTEXT.md` 的「维护 agent」补一句函数级细节的落点。
- ADR 列表那一行（`### Domain docs` 里的枚举）加了 `0039` 一条。它属于 #1299 的范围，但这里躲不开：`tests/test_doc_consistency.py` 的 `AdrIndexTests` 要求 `docs/adr/` 的每一份都被那行收录，不加就红。#1299 要改的是整段的去留，不是这一次的一格。

## 回退条件

落地后若出现「写出第二份实现」的迹象——`tests/test_recipe_nav.py` 的重复实现违规变多，或 PR 评审里出现照着记忆另写一份——就把 27 条搬回 `CLAUDE.md`，并把结论钉成「`CLAUDE.md` 保持函数级自包含，不再讨论」。搬回来的成本与搬走时一样：正文逐字在，锚点跟着走，`rules.toml` 的 `source` 改回 `CLAUDE.md#开发`。
