# 测试充分性由变异测试判定：覆盖率管执行，mutation 管断言

父 spec #1407。驱动与 PR job 见 #1411 / #1412 / #1413，存量按模块清理是 #1407 底下的一批子票，规则、术语与本文的收口是 #1415。基线 `5b55843f`。

## 问题

测试充分性的唯一判据曾是「行为变化要有一条去掉就会红的用例」。它证明「测了」，不证明测试能区分行为：断言写得再松，只要跑过就是绿的；也因此没有任何东西能判定哪些用例已经多余。

「按覆盖率删用例」这条路已被否证——`tests/` 里 97% 的用例各自守一个真实分支，删了就是丢覆盖。但同一份数据也指向判据本身：覆盖率能回答「这段代码被执行到没有」，回答不了「执行到的那段有没有断言守得住」，空覆盖就活在这两问之间。与此同时 CI 时间随用例数线性增长：11-13 时 3017 条用例跑 72 秒，现在 3392 条跑 103 秒（Linux job），Windows 更长。判据不换，用例数只能继续涨。

## Decision

### 判据从「有测试跑过」换成「改动行产生的 mutant 全部被杀死」

mutmut 3.8 对代码做小改动（mutant）再跑测试：测试仍然全绿的那一处改动就是存活。判据落在改动面而不是整个仓库——PR 上 `python devtools/mutation.py --since <base>` 只跑 `git diff --name-only` 里落进映射表（`devtools/mutation_scope.py`，40 个模块）的那些，行级筛选交给 mutmut 自己的内容哈希 + span 缓存（实测单行 0.75 s，单模块冷缓存 8.1 s）。

门槛是 100%，不设比例：允许比例会立刻出现卡阈值的写法。存活之外，`no_tests`（没有测试碰到这处变异）、`suspicious`、`segfault` 同样返红。映射表把测试范围收窄到「执行过该模块的那些文件」，因为它决定尺子的宽度——窄了会把没被选中的测试能杀死的 mutant 报成存活，所以 `mutation_scope` 除 `reader` 外每一行由 coverage 的 `dynamic_context` 矩阵量出来，不按 import 反推（`reader` 那行只为让 mutmut 有得收集，见 Consequences）。

### 两层判据各管一端

- **覆盖率回答「新增代码有没有被执行到」**：`coverage` job 合并 Linux 与 Windows 两份数据，只出数字、不设阈值（既有决定，本 ADR 不改）。没被执行到的代码生不出可杀的 mutant。
- **mutation 回答「执行到的代码有没有断言守得住」**：在映射表内的模块上，「新代码完全没测」也会以 `no_tests` 返红；跑过但断言抓不住差异的空覆盖，只有这一层看得见。
- 两层都看不见的地方是映射表本身：表外 `tool/` 与 `gui/` 模块的改动逐条报出来但不判。`gui/` 的六份实体模块（`tasks` / `adb` / `dispatcher` / `reporter` / `updates` / `update_install`）从 #1429 起已全部进表，手机版替换层的第一段五份（`view` / `adb` / `screen` / `inproc` / `u2`）从 #1430 起也已进表，表内这些与 `tool/` 同一口径；界壳文件、harmony 三份与手机版替换层的 `main` / `bridge` / `updates`（第二段，见下）还没有这一层。

两层不能互相替代：覆盖率数字证不了断言的质量；mutation 只在能生成 mutant、且在映射表内的行上说话。这也是为什么本 ADR 不把「有测试跑过」换成「变异分数达标」——分数可以靠比例调到通过，而这里要的是一个二值结论。

### 等价变异体豁免的边界

杀不死只有两条合法解释：

- **语义等价**：变异前后对任何输入同结果。例：`tool/catalog/schema.py` 里 `len(present)` 与 `len(缺席)` 同真同假，改哪一个都读不出差别。
- **不可达**：所在分支走不到。例：`tool/catalog/schema.py` 的 `_require(op, "page", …)`，通用必填循环在它之前就拦了。

两者都写在源码行尾的 `# pragma: no mutate` 里，必须写明属于哪一条；说不清为什么属于这一条的，就是没写理由。「无意义变异」不在豁免内——不影响行为的代码该删该改，不是标 pragma。不做 Z3 之类的工具辅助证明：判的是「这一处为什么杀不死」，能一句话说清才叫豁免。pragma 条数由 `devtools/mutation.py` 数出来写进 CI summary 的变异测试一节，它不会变成藏污纳垢的地方；理由本身仍靠评审读 diff。

### 规则怎么拆

`dev.tests.behaviour-change-needs-red-test` 改而不删，按对象拆开：

- `tool/` 与进表的 `gui/` 里落在映射表内的代码改动，由新规则 `dev.tests.mutation-kills-changed-lines`（`check = "ci:mutation"`）判定；
- `recipes/` 的数据改动没有 mutant 可跑，mutation 那一层对它完全看不见，仍由原规则人工判；
- `gui/` 的界壳文件（`app` / `launch` / `shots`）、harmony 三份、手机版替换层的 `main` / `bridge` / `updates`（#1430 第二段）以及 `gui/` 其余非实体模块（`winpreflight` / `startup` / `toolpath` 等）在各自纳入 mutation 之前，也仍走原规则。

原规则的 id 与锚点不动，因为它被 `doc.issue.close-on-evidence` 等处按 id 引用；改的是适用范围与到期条件。它仍是 `manual`：数据侧没有等价的机器判据，这条债不是靠把它标成 `dead` 消掉的。

### 关票证据的边界

被变异模块上 mutation 全绿，可以当作「行为变化已被测试守住」的证据（口径复用 `doc.issue.close-on-evidence`）。它替代不了真机验证；`recipes/` 的数据改动仍要一条会红的用例当证据。

### 手机版替换层（#1430）

手机版是引擎的第二个执行宿主（ADR-0019）。`android/app/src/main/python/aac_android/` 下的替换层把 `subprocess`、`uiautomator2`、`adb` 的入口顶掉，让同一份 `tool/` 与机型脚本在 App 进程里跑。产品布局不能挪（Chaquopy 的 `sourceSets` 要求它留在原处），测试按 `sys.path` 插 `android/app/src/main/python` 后 `from aac_android import …` 导入；变异只在 `src` 视角上做，与 `tool/`、`gui/` 靠同一个镜像对齐。

接缝上有四处差别，都已在驱动侧解决，测试一行不改：

- **模块路径换算**：`source_path()` 多认 `android/app/src/main/python/aac_android/` 前缀，映射到 `src/aac_android/`；`_slug()` 与 `--since` 的可见性（`scope_of` 的 `roots`）也跟着认这个前缀。
- **`src` 镜像**：`_mirror_sources()` 的镜像从两包扩成三包，`SOURCE_PACKAGES` 加 `aac_android`、基目录在 `PACKAGE_BASES`，`aac_android/` 的条目落在 `src/aac_android/`。
- **测试导入落到副本**：mutmut 的 `setup_source_paths()` 把 `mutants/src` 插在 `sys.path` 最前；镜像里有 `src/aac_android`，测试原有的 `from aac_android import …` 就落到变异后的副本。测试的导入路径照产品布局写、不改。
- **覆盖率**：`.coveragerc` 的 `source` 增加 `android/app/src/main/python/aac_android`，CI 的覆盖率地图看得见这一块（仍不设阈值）。

**两条管道风险**：`u2.install()` 与 `inproc` 会改写 `sys.modules` 和模块全局，`adb.install()` 会把 `subprocess.run` / `call` / `check_output` 换成占位实现；mutmut 3.8 在同一个解释器里跑完所有 mutant，这些副作用会漏到下一个 mutant。处置是在每条用例的 `tearDown` / `addCleanup` 里保存并回填（`sys.modules`、`subprocess.*`、`_orig`、模块全局），方向保守——只防「被改掉的入口让 mutant 假存活」，不为制造假杀死去锁调用序列。票面原写「在 `tests/conftest.py` 的会话钩子里还原」，但会话启动钩子管不到 stats 阶段跨 mutant 累积的状态，实测改为每条用例各自还原，让 fork 前的父进程保持干净。

**启动条件已到期、可启动**：票面原写的「`tool/` 侧 12 个严格档模块清完」已经满足，不再是历史前提。

第一段五份实体模块从 #1507–#1511 逐份清零并进映射表：`view` / `adb` / `screen` / `inproc` / `u2`，每份存活 0、无测试 0。

第二段 `main` / `bridge` / `updates` 的实测（#1512；测试范围由 `dynamic_context` 覆盖矩阵量出——`main`/`bridge` 只由 `tests/test_android_shim.py` 执行，`updates` 无任何测试执行）：

| 模块 | mutant | 存活 | 无测试 | 决定 |
|---|---|---|---|---|
| `main` | 326 | 24 | 216 | 不纳入，表外已知缺口 |
| `bridge` | 352 | 79 | 169 | 不纳入，表外已知缺口 |
| `updates` | 27 | 0 | 27 | 过判据，纳入（待实现） |

- `main` 不纳入：216 个无测试全部落在 `boot`(139) / `call`(42) / `selftest`(21) / `_Native`(14) 这些装配与界壳段，修它们要造 `Api` / `app` / `java` 的全套替身，属于新建 harness，不是「补一条断言」；24 个存活在已测的 `in_front` / `Session` / `visible` 上，可以补断言，但被装配段挡住整份。
- `bridge` 不纳入：169 个无测试主要在 `AdbBridge`(146)——电脑调试路（`AAC_BRIDGE_ADB`），用户永不经过，修它要 patch 模块级捕获的 `_run` / `_popen` 并锁调用序列；另有 1 个超时。79 个存活在 `ShizukuBridge.exec` / `_await` / `_slow` / `_get` / `_launcher`，同样达不到「只补断言」。
- `updates` 过判据：`AndroidInstaller.install` 只包一层 `native.installUpdate`，用现有 `native` 替身（返回 JSON）即可补断言，不需要新 harness、也不需要锁 mock 调用序列；但断言只能到输出与错误文案这一层，收益有限。本票只决定纳入、不实现——补用例与进映射表留给后续实现票。

### devtools（#1444）

`devtools/` 是第三个复用同一套镜像语义的被测侧（前两个是 `gui/` 与手机版），不碰设备。范围来自 #1444 的 spec，结论以 #1515–#1522 的实测为准。票面原先猜的三条障碍——大量文件系统 / git 状态替身、`gh` 会话替身、进程内缓存——经实测不成立：这 8 个测试文件基本是注入 runner 加临时目录，`devtools/` 里没有 `lru_cache`，也没有模块级缓存字典。

**范围三档**：

- **进表 16 份**，按「共享同一批测试文件」的连通分量分组，组内一起清零：
  - A：`gh` / `claim` / `stale` / `followup` / `triage_audit` / `release_assets` / `release_meta`——`claim` 依赖 `gh` 与 `stale`，其余各自 import `gh`；
  - B：`commits` / `check_dco` / `check_conventional` / `check_comment_tickets`——三份 `check_*` 共同 import `commits`，`commits` 无独立测试文件；
  - C：`check_ticket_ref`；D：`glob_scan`；E：`test_anchors` / `unittest_summary`（后者 import 前者）；F：`script_surface`（覆盖者是 `tests/test_phone_facade.py`）。
- **表外 1 份**：`typecheck_recipes` 实测 179 个 mutant、杀死 17、存活 8、无测试 154。唯一覆盖是 `test_catalog` 的一个方法，只碰到 `_check_catalog`，且它仍有 8 个存活；`_check_python` / `main` / `recipes` 分别 28 / 72 / 54 个 mutant 全无测试。清零要新建 harness（起 `mypy` 子进程、patch `recipes()` / `_check_python`、给 `ROOT` 注入口），不是补断言；按「不为凑判据硬造断言或 harness」登记为表外已知缺口。
- **不纳入：自指两份** `mutation.py` / `mutation_scope.py`——它们是判据本体，mutant 打在报告层时「存活 / 杀死」本身不可信。**不纳入：生成器三份** `gen_adr_index` / `gen_brand_taps` / `gen_site_css`——唯一覆盖者是 `tests/test_doc_consistency.py`，整份在副本里跑不通，进表只会得到一片 `no_tests`。

**各模块最终结论**（每份都跑到存活 0、无测试 0）：

| 模块 | mutant | 存活 | 无测试 | pragma |
|---|---|---|---|---|
| `check_ticket_ref` | 65 | 0 | 0 | 0 |
| `commits` | 58 | 0 | 0 | 2 |
| `check_dco` | 56 | 0 | 0 | 0 |
| `check_conventional` | 55 | 0 | 0 | 0 |
| `check_comment_tickets` | 125 | 0 | 0 | 4 |
| `test_anchors` | 258 | 0 | 0 | 0 |
| `unittest_summary` | 260 | 0 | 0 | 2 |
| `glob_scan` | 488 | 0 | 0 | 4 |
| `script_surface` | 53 | 0 | 0 | 0 |
| `gh` | 45 | 0 | 0 | 0 |
| `claim` | 767 | 0 | 0 | 0 |
| `stale` | 556 | 0 | 0 | 3 |
| `followup` | 417 | 0 | 0 | 3 |
| `triage_audit` | 197 | 0 | 0 | 0 |
| `release_assets` | 322 | 0 | 0 | 1 |
| `release_meta` | 728 | 0 | 0 | 6 |

pragma 全部写明「语义等价」或「不可达」，理由随源码行。三条与平台相关的豁免在 #1522 返工时被推翻（`encoding=None` 在 cp1252 上、`newline=None` 写 CRLF、`tzinfo=None` 取本机时区都会改变结论），改成 spy 用例钉住实参后仍保持存活 0。

**真实障碍三条**（spec 已纠正票面原先的猜测）：

- **副本缺仓库根文件**：副本 `ROOT` 是 `mutants/`，根级 `.github/`、`CLAUDE.md`、`tool/`、`index.html` 都不存在（`followup.DOC` 这类按模块相对路径读的 `docs/` 也不在 `mutants/src/` 下）。读这些的用例按类或按方法进 `mutation_scope.UNUSABLE`：`test_ticket_ref` / `test_dco` / `test_conventional` / `test_comment_tickets` 的 `WorkflowTest`、`test_conventional` 的 `DocumentedTypesTest`、`test_claim` 读 `CLAUDE.md` 的一条、`test_release_meta` 读 `index.html` 的一条、`test_followup` 的 `RealQueueTests`、`test_glob_scan` 的 `RepoTests` 与一条对真实仓库求值的豁免用例。
- **起子进程的 CLI 用例**：改跑 `src` 镜像里的副本（`Path(module.__file__)`），但必须清空 `MUTANT_UNDER_TEST`——统计阶段该值是 `stats`，trampoline 会在临时 git cwd 里找不到 mutmut 配置而收集失败。子进程因此只跑原件行为，不提供 mutant 区分力；归属与区分力由进程内用例提供（`main()` 若只经子进程走到会被判 `no_tests`，有 CLI 入口的模块因此补了进程内用例）。
- **import 期改写不还原**：`devtools/__init__.py` 与 14 个子模块在 import 期 `sys.path.insert`，其中 12 个随即 `use_utf8_console()` 改写标准流，且都不还原。处置在 `tests/conftest.py`：对 19 个 import `devtools` 的测试文件，在每条用例的边界快照 / 回填 `sys.path`、`sys.modules` 与标准流对象；名单与 AST 扫描出的实际集合双向对拍。

**接线四处**：`PACKAGE_BASES` 增 `devtools`，镜像落 `src/devtools/`；从 `LINKS` / `ALSO_COPY` 摘掉 `devtools` 的未变异真副本（留着会让测试永远命中原件）；`SOURCE_PREFIXES` 认 `devtools/`；`scope_of` 的 `roots` 认 `devtools/`，`--since` 才看得见 devtools 改动——表内参与判定，表外只报不判。

**启动条件已到期、可启动**：没有前置依赖，与 `gui/`、手机版共用同一套镜像机制，是第三个复用者。

**与 spec 正文的差异**：

- #1516 的机制落成 `tests/conftest.py` 的逐用例 pytest 钩子，不是逐类 `tearDown`；语义是逐用例，`unittest discover` 不读 conftest、行为不变。
- `typecheck_recipes` 经实测登记为表外缺口（spec 给的是「留实现阶段按实测判」）。
- 子进程端的 mutant 区分力为零，靠进程内调用点；spec 允许「改不动再摘」，实测是「能改跑但带不了 mutant 环境」。
- 为消等价变异对少数源码做了行为保持的收窄（模块级常量、去掉冗余默认值、`removeprefix` / `removesuffix` 等），可见行为未变。
- 「去掉冗余默认值」指 `claim.label_names` 与 `stale.decide` 把 `item.get("name", "")` 改成 `item.get("name")`：标签缺 name 时返回 `None` 而不是 `""`。两处都只做成员判断 / 过滤，可观察结果相同——`role_labels` 只保留 `ROLE_LABELS` 里的名字，`decide` 只做集合成员判断。
- #1516 的证伪只到机制层：删除回填后同一解释器里的下一条用例可见污染，但没有造出 mutant 判决翻转（collection 期 import 是每个 fork 共享的基线）；19 个文件带与不带回填均为 736 passed。
- 造不出跨 mutant 判决翻转是结构使然：mutmut 3.8 的 `ForkServerRunner` 只让 fork server import 一次 pytest / 测试模块，之后每个 mutant 再 fork 一个孙进程，跨 mutant 的全局状态本来就不共享；回填守的是同一 mutant 会话内、用例之间的污染，不是没做实验。
- spec「副本内跑不通的测试」表里列的 `test_mutation_scope` 中依赖 `ROOT/tool` 与 `pyproject.toml` 的类**没有**进 `UNUSABLE`：该文件不在任何 `MODULE_TESTS` 行里，`tests_for()` 从不收集它，副本里跑不到，加了也是空转。

### tool/ 其余模块（#1445）

范围与基线：2026-11-23 时 `tool/` 59 个 `.py`，映射表内 13、表外 46（含 `catalog/__init__.py` 与 `phone/__init__.py` 两个壳）。顺序按该模块承载的无结构来源短用例数降序（研究 #1396），单模块冷缓存耗时只做闸门与次级比较，不写乘积分。映射行由 coverage `dynamic_context = test_function` 矩阵量出：执行过该模块的测试文件都进这一行，副本里跑不通的按方法或按类进 `UNUSABLE`，不按 import 反推——窄行会把没被选中的测试能杀死的 mutant 报成存活。共享同一批测试文件的模块按连通分量成组清零、成组进表（`channel_decide` / `channel_arrive` / `chan_fast` 同属一组，本批先清前两份）。成本闸门沿用 #1444：只补断言能清零的才纳入；要新建 harness（起子进程、造整套替身、锁 mock 调用序列）的登记为表外已知缺口，理由写实测数字。

**删除检测的边界**：「只删测试、不改模块的 PR 不触发变异」——`--since` 只看改动路径里有没有落进映射表的模块，删用例的 PR 没有模块路径可判，所以「表内 = 删除必被发现」只对同时改了模块的 PR 成立。这个洞已由 #1531 接线（按映射表反查改动测试文件拉起的模块，实测与前提见 Consequences），本节只写清边界。

本票实测：

| 模块 | mutant | 存活 | 无测试 | pragma |
|---|---|---|---|---|
| `channel_decide` | 500 | 0 | 0 | 1 |
| `channel_arrive` | 147 | 0 | 0 | 0 |
| `chan_fast` | 1804 | 462 | 6 | 0 |
| `channel_batch` | 196 | 0 | 0 | 0 |
| `channel_toggle` | 43 | 0 | 0 | 0 |
| `ui_hidden` | 55 | 0 | 0 | 0 |
| `screen_snapshot` | 689 | 0 | 0 | 3 |
| `phone/session` | 14 | 0 | 0 | 0 |
| `phone/toggler` | 519 | 37 | 0 | 0 |
| `adb_link` | 323 | 0 | 0 | 5 |
| `huawei_channels` | 693 | 0 | 0 | 4 |
| `fast` | 607 | 0 | 0 | 2 |
| `wait` | 80 | 0 | 0 | 3 |
| `captures` | 100 | 0 | 0 | 5 |
| `row` | 1256 | 181 | 0 | 0 |
| `entries` | 481 | 0 | 0 | 3 |
| `vocab` | 588 | 0 | 0 | 2 |
| `phone/navigator` | 373 | 0 | 0 | 0 |
| `phone/dismisser` | 244 | 0 | 0 | 1 |
| `phone/launcher` | 299 | 0 | 0 | 3 |
| `phone/screen` | 640 | 0 | 0 | 10 |
| `adapt` | 798 | 0 | 0 | 4 |
| `explore` | 274 | 0 | 0 | 1 |
| `recipe_audit` | 578 | 0 | 0 | 3 |
| `verify_ledger` | 296 | 0 | 0 | 2 |
| `phone/settings_search` | 259 | 0 | 0 | 0 |
| `phone/connection` | 174 | 0 | 0 | 0 |
| `ui_session` | 115 | 0 | 0 | 0 |
| `catalog/loader` | 400 | 0 | 0 | 2 |
| `stdio` | 18 | 0 | 0 | 0 |
| `troubleshooting` | 99 | 0 | 0 | 0 |
| `backups` | 60 | 0 | 0 | 0 |
| `recipe_runtime` | 269 | 0 | 0 | 3 |
| `recipe_loader` | 26 | 0 | 0 | 0 |

- **`channel_decide` / `channel_arrive` 进表**，与表内模块同口径。`channel_decide` 的唯一 pragma 是 `gap = tol = 0`：`boxes` 为空时 `ok` 必假，这两个初值不进 notes、也不进同带取舍（不可达）。清零过程中顺带收掉两处死参数：`row.named_nodes()` 的 `parents` 与 `channel_decide.allow_switches` / `page_hint` 的 `systemui_text`（都从不被读），并把缺属性时的空值收进一个模块常量，消掉 `.get(k) or ""` 与 `.get(k, "")` 一类在真实 dump 上区分不出来的等价变异。
- **`adb_link` / `huawei_channels` 进表**（#1535），与表内模块同口径。两处覆盖矩阵都需要收窄测试范围：`tests/recipe_case.py` 是只有基类（`RECIPE = None`）的助手模块，pytest 按路径收集时基类用例直接红，整份不进 `adb_link` 的行（同一条用例由 `_recipe.py` 子类在真实数据上跑，不少杀）；其余 51 份照矩阵全收。清零时把 `present` / `detached` 各写一份的 `get-state` 子进程调用收进 `_adb_run`，并把「占位串不可能命中本模块正则 / 只当真假用」的等价变异收成行内 pragma（共 5 条：`_matches` 一处覆盖 `client_gone` / `lib_gone` / `read_failed`，`screen_gone` / `focus_window` / `keyguard_showing` 各一处，`Connection.shell` 的 `for attempt` 一处）。`adb_link` 的 4 个超时是 `lost_from` 的异常链环检测：成环的链只有让 mutant 死循环才有行为差异，一条成环用例把它跑到 SIGXCPU（mutmut 记 timeout，算检测到，不进存活）。`huawei_channels` 的 4 条 pragma 是：两处 `(node.get(attr) or "")` 的缺属性占位（占位串不会等于真实渠道名）、`locate` 的 `break`（循环之后没有语句，与 `return` 等价）、收尾复查里那个 `banned`（走到那里时总开关已被 `guard`、权限模式已被复查钉回，恒为假）。清零还顺带把 `read_text` 改成 `read_bytes().decode()`、`write_text(encoding=...)` 改成 `write_bytes(...encode())`、把 JSON 格式收进一个模块常量，消掉只在非 UTF-8 locale 上才区分得出来的等价变异。
- **`fast` / `wait` / `captures` 进表**（#1536），与表内模块同口径。这三份是认页 / 拨动的底座，`test_row` 同时是它们的覆盖者，所以行按覆盖矩阵量满（`fast` 47 个测试文件、`wait` 40、`captures` 46）。清零靠补断言：门面的每个动作动词（含默认值）按转发断言逐条钉住、构造处的协作者装配逐项对位，`execute()` 的每条命令与 `main()` 的两类异常各有用例，`wait.until()` 的预算封顶与默认轮询间隔直接读采样序列。`fast` 的 2 个 pragma 是 `recorded = str()`（None 与空串同假）与日志文件的 `encoding="utf-8"`（codec 名大小写不敏感，省略时判定平台默认就是 UTF-8）；`wait` 的 3 个是 `same` 的默认值（首个真值采样两条路都立即返回）、`stable <= 0 and same <= 0`（两条路返回同一个值）与 `streak` 的重置值（`steady` 同时回到 UNSET，下一次真值采样必重设）；`captures` 的 5 个是两处 `encoding` / `newline`、`ensure_ascii=False`（json 按真假取用）与空 root 的 `os.walk("")`（不产出任何一项）。
- **`row` 不进表（表外已知缺口，本票实测）**：1256 个 mutant、杀死 1075、存活 181、无测试 0、超时 0。存活全在纯函数里——`skeleton` 48、`title_label` 46、`summary` 29、`path` 16、`switch_row` / `dedupe` 各 9，`link` / `control` 各 5，其余 ≤3（`title_hit` / `own` 各 3，`same_row` / `named_nodes` / `icon_hit` / `disabled_at` 各 2）。它不是缺替身，而是**同一语句上同时挂着可杀与不可区分的变异**：`(a + b) // 2` 的 `/2`（整数阈值下同真同假）、`rsplit(sep, 1)[-1]` 的各种 maxsplit、`split("\n", 1)[0]` 的第 0 段、`or ""` 的占位串、`iter("node")` 的 `iter(None)`，这些都和真能改判的变异挤在同一行；行级 pragma 会连带吞掉可杀的那些。清零要先按行拆开这些语句，再给每条边界（屏幕边缘的中心线、同一水平带的两侧、候选文字带与开关中心的交叠）构造专用页面——那是改写读屏算术去适配尺子，投入与判据价值不成比例。模块整体才进表，故整份登记为表外已知缺口；下次纳入时按同一口径逐份清到零。
- **`phone/navigator` / `phone/dismisser` / `phone/launcher` 进表**（#1539）：三者被同一批读屏用例执行，成组清零、成组进表，实测存活 0、无测试 0。清零时收掉了几处只在死路径上成立的写法：`tap()` 的翻页回路里 `edge` 恒为假、`range(2 if scrolls else 1)` 的 else 分支进不去（`scrolls=0` 已提前返回），`launcher` / `dismisser` 的 `split("/", 1)[0]` 去掉没人用到的 `maxsplit`，启动失败的正则提成模块常量。`launcher` 的 3 条 pragma 是等价豁免：两处「被谁抢了前台」的初值只在没有外来前台的路径上被读，收尾循环的 `break` 与 `return` 同效（循环后面没有语句）。收尾循环 `or not streak` 的 `and` 变异体与启动等待里把权限页记成 seizer 的差异都不是等价、已各补一条用例守住。`dismisser` 的 1 条 pragma 同样是等价豁免：`class` 缺失时的兜底串与空串都不含 `Button`。本票没有表外缺口。
- **`chan_fast` 不进表（表外已知缺口）**：本票实测 1804 个 mutant、杀死 1331、存活 462、无测试 6、超时 5。存活集中在整批编排段——`run` 112、`toggle` 57，加上 `_enter_app_page` 47、`_skeleton` 35、`undo_message` 20、`recognise` 19、`mismatch_probe` 14 等。`run` / `toggle` 的清零要造整套 `Phone` / `ShellPhone` / `UiHidden` 替身并锁住调用序列，成本闸门明确排除；而模块只有整体才进表，所以整份登记为缺口。它下次纳入时按同一口径逐份清到零。
- **`phone/session` 进表**：三个会话对象的 `__init__` 初值与 `set_app()` 的「换 App 清推广位记忆」共 14 个 mutant，靠 `test_phone_sessions` 里的初值断言清零（空串、`False`、活集合各一条）。覆盖矩阵把 `tests/recipe_case.py` 里写的用例归到它自己名下，但那是只有被继承才跑得起来的基类；映射行按实际所有者换成三个子类文件，范围不窄于矩阵。
- **`phone/toggler` 不进表（表外已知缺口）**：实测 519 个 mutant、杀死 481、存活 37、无测试 0、超时 1。纯函数与构造初值（`match_key` / `in_band` / `plan_switches` / `Toggler.__init__`）本票补断言后清零；存活全在该模块自己的编排段——`off` 34、`confirm` 3（另 `confirm` 去掉注入的 `sleep` 的一条超时）。是首屏等待的 `tries` / `poll` / `sleep` 实参、`shift` 初值与重排分支、回读与补点里的 `continue` / `break` / `return` 之分、`screen.switches()` 的实参、两处 `|=` 累加，以及几处 sleep 节奏常量。逐条杀掉要按场景锁住替身的调用序列与节奏，成本闸门排除；模块只有整体才进表，故整份登记为缺口。
- **渠道判定族二四份全部进表**（`channel_batch` / `channel_toggle` / `ui_hidden` / `screen_snapshot`；初始实测 198 / 43 / 57 / 764 个 mutant，存活 9 / 9 / 17 / 137）。清零靠补行为断言，不锁 mock 调用序列：批次记账与拨动决定补的是清单形状与结局细节（`Pending.item`、`ChannelList` 的两份空集合、受保护判据吃渠道 ID 而不是显示名），`ui_hidden` 补的是名单文件口径（BOM、首个制表符、注释行、同一键在一批里只写一次、写不进去不算失败、落盘字节），`screen_snapshot` 补的是屏幕快照的边界（`on_screen` 的中心与退化盒子、`pixel_on` 的通道与取样位置、JSON 缺字段的默认值、`parse_notification_dump` 的 UID 边界与两条读数合并）。三处 pragma 都是语义等价：`on_screen` 的中心只与整数宽高比（`//` 与 `/` 同真同假）、`pixel_on` 的取样行经 getpixel 截断成同一格、自绘开关回写的类名只经 `"Switch" in cls` 读且 checkable 已置真。清零途中收掉的死代码都属本模块：`switch_row_data` 里两处尺寸守卫在 `shown()` 之后恒真、`snapshot_from_tree` 的 `activity if sep else ""` 两支同值、`parse_notification_dump` 的 `fixed` 初值在读它之前必被重写；缺属性时的空值收进 `NODE` / `NO_CLASS` / `NO_ID` / `NO_SECTION` 四个常量。四份的映射行按同一份覆盖矩阵量出，与 `chan_fast` 的行有交集，但 `chan_fast` 仍是表外已知缺口。
- **`entries` / `vocab` 进表**（#1544），与表内模块同口径；映射行按覆盖矩阵量出（`entries` 6 个测试文件、`vocab` 2 个），两份都清到存活 0、无测试 0，没有表外缺口。存活全在数据 / 词表的纯函数边界，靠补断言清零：`family()` 的空品牌、`landed()` 的空 / 无页面焦点、`open_direct()` 的错误文本（页面名、输出尾部 200 字、退出码与 `Error` 文本两支）、`reach()` 的 settle 转发与轮询预算（按注入钟数采样轮数）、`_scan_entries()` 的关键字 `activity=` 与 `open_app_settings` 的第二实参、`group_of()` 的分组前缀、`_positional()` 的越界，以及 `gaps()` 的表头文案、分隔符、同词多机型与「没写页面」。清零顺带消掉几处区分不出来的写法：`LABEL.get(fam, fam)` 改成 `LABEL[fam]`（每个家族都在 `LABEL` 里，`test_every_family_has_entries_and_a_label` 守着）、`used.get(key, ())` 改成 `used[key]`（同一表达式已按成员判定守卫）、`gaps()` 里与 `mine` 集重复的 `startswith` 过滤直接删掉、`glob` 三层通配下 `len(parts) != 3` 恒假。`entries` 的 3 个 pragma 是：`landed()` 的 `split("/", 1)`（页面名不含 `/`，maxsplit 变体同值）、`landed()` 的 `full() if startswith(".")`（已带包名的页面名经 `full()` 恒等）、`speedups()` 的 `continue`（三层通配下不可达）；`vocab` 的 2 个是 `_absorb()` 的 `here +=`（每次调用新建的空表，`+=` 与 `=` 同值）与 `gaps()` 的 `folder.split("/", 1)`（`_folder_name()` 保证目录名两段）。`entries` 的 2 个超时是 `reach()` 去掉注入的 `sleep` 的那两支：改成真睡后被 mutmut 记 timeout，算检测到、不进存活。
- **`adapt` / `explore` / `recipe_audit` / `verify_ledger` 进表**（#1545），与表内模块同口径，没有新的表外缺口。这四份是开发者脚本面（适配生成、探路、脚本审计、验证台账），覆盖行从矩阵原样收下；`explore` 与 `adapt` 的 70 + 26 个「无测试」之首就是它们的 `main` / `cmd_explore`，靠进程内用例清零——替身手机、临时目录与 `contextlib.chdir`、`sys.argv` 注入、`script_cmd` 与 `subprocess.call` 换成 spy（不起子进程，也不碰真设备）。其余存活来自显示文案、参数装配与 `continue`→`break`：消息逐字断言、选项逐个走真分支、多条目场景让第二个条目必须被处理。10 条 pragma 全是语义 / 不可达豁免：6 处 `encoding=` 的 codec 别名或省略（判定平台默认 UTF-8）、两处 `zip(..., strict=)`（`_footer` 与 `parse_tsv`，两序列恒等长）、`_installed_packages` 的空表占位（占位串不含 `package:`）、`check_draft` 里 `recorded` 的短路（空串时 `startswith("")` 恒真、`_build_mismatch` 也恒假）。清零时顺带把几种「同一行上混着可杀与不可杀」的写法收成模块常量或显式查表：codec / JSON 选项 / 例外后缀（`EXT_SUFFIX`）进了模块级常量，`ensure_ascii` 的 `None` 写法与大小写变体不再生成；`script.split("/", 1)[0]` 换成 `partition("/")[0]`、`now.split("/", 1)[0]` 换成 `now.startswith(pkg + "/")`；`rows()` 的 falsy 默认值（`builds.get(path, "")` / `hashes.get(path, "")` / `body_hash` 缺键）改成显式 `in` 判定，占位串与空串不再等价；`_launch_failed()` 改读 `result.exit_code`（`p.shell()` 恒给 `ShellResult`），去掉 `getattr` 默认值那一类变异。
- **`phone/settings_search` / `phone/connection` / `ui_session` 进表**（#1540），与表内模块同口径，没有表外缺口；映射行按覆盖矩阵量出。初始实测分别为 288 / 174 / 130 个 mutant，存活 99 / 64 / 46（`ui_session` 另有无测试 20）。`ui_session` 的 20 个无测试是 `_check_alive` 的整条 ping 与 `connect()`：没有用例碰过它们，补一条 ping 契约用例（`_http_request` 收到的 dev / 端口 / `"GET"` / `"/ping"` / `timeout=1`、`b"pong"` 判定、`HTTPError` 与 `OSError` 都算不在）和一条 `connect` 的转发断言即清零。`connection` 的存活集中在构造期的三支异常翻译、`_shell_transport` 的两种调用形状、`pause_point` / `say` 的 `flush`、`locked()` 的通知栏收起与 `wait_unlocked` 的预算转发；全部靠行为断言清零（断言消息全文而不是子串，是这一批的教训：`XX…XX` 一类变异会被子串断言放过），不锁调用序列，唯一的边界取舍是「`lost_on_retry` 这个开关按值断言」。`connection` 的 2 个超时是 `wait_unlocked` 去掉注入的 `sleep` / `timeout` 的那两支：改成真睡后跑到预算耗尽，被 mutmut 记 timeout，算检测到、不进存活。`settings_search` 的存活全在这个阶段自己的编排段（打字的两条 RPC 与核对、直达搜索页的判定、退场的三次 BACK、结果挑选的坐标与越界保护、四处 `wait.until` 的预算），等待全部改用 `fixtures.Clock` 注入后按推进的时间与采样次数断言，`/` 与 `//` 之差按「点击坐标必须是整数」断言。三份清零途中的行为保持收窄都只在本票模块内：缺属性时的空值收进 `EMPTY` / `EXIT_OK` 等模块常量、`iter("node")` 与 `poll=0.15` 这类与默认值重复的写法去掉、退场码判定写成 `!= EXIT_OK`（让「缺属性按成功」与「零按成功」可区分）、`stop_uiautomator` 收掉从不被读的 `wait` 参数、`start_uiautomator` 把「只重试一次」写成两次显式启动（原 `for attempt in range(2)` 的第三轮不可达）、锁文件的口径（编码 / 目录 / 后缀 / 种子字节 / 平台名）收进模块常量。三份最终 pragma 都是 0。
- **`catalog/loader` 进表**（#1541），与表内模块同口径；映射行由覆盖矩阵量出（51 个测试文件、61385 行），`tests/recipe_case.py` 按同一手法换成十二个继承子类文件。初始实测 409 个 mutant、存活 73、无测试 0，全在装载入口的输入边界与命名空间视图上：目录取唯一 `.toml` 的整条分支此前没有用例（9 条）、`ONLY` / `HALTED` 写回与六个 `rt` 视图名（14 条）、`difflib` 候选数与提示分隔符、`args` 里的再入块、嵌套实参表里的变量引用、分支内绑定的可见性与 `where` 下标链、四个钩子名的别名绑定、常量的 `isupper()` / `callable` 过滤。清零只靠补断言，没有新建 harness。两条 pragma 都是语义等价：两处 `read_text(encoding="utf-8")` 的 codec 名大小写与省略编码在判定平台上不可区分。另外把 `get_close_matches` 的 `n=3` 去掉（默认就是 3），顺带消掉两条分不出行为的 mutant。两个超时是 `Runtime(p, only, clock)` 去掉注入的假钟：改回真 `time` 后有用例真的等，mutmut 记 timeout，算检测到、不进存活。
- **`stdio` / `troubleshooting` / `backups` 进表**（#1546），与表内模块同口径；映射行按覆盖矩阵量出（`stdio` 4 个测试文件、`troubleshooting` 16 个、`backups` 27 个），三份都清到存活 0、无测试 0。初始实测 18 / 100 / 60 个 mutant，存活 1 / 36 / 3。清零靠补行为断言：`stdio` 补「一个流没有 `reconfigure()` 时只跳过它、后面的流转常转」（`continue` 退化成 `break` 就漏转 stderr）；`troubleshooting` 补识别词表逐条（6 个标记各一条）与只读检查的四类失败 / 成功文案，以及 `subprocess.run` 的固定参数（`capture_output` / `text` / `encoding` / `errors` / `timeout`，`os.name == "nt"` 下还有 `creationflags`）；`backups` 补 `create()` 在同一分钟重复调用落进同一个目录、不抛错（`exist_ok` 退化成 `None` / `False` 时第二次会 `FileExistsError`）。清零途中把 `accessibility_summary` 的 `configured in {"", "null"}` 收成 `configured == "null"`：返回值先 `strip()` 再 `splitlines()`，末尾空行已被吃掉，空串那个成员不可达（消掉两条等价变异）。
- **`run` 不进表（表外已知缺口，本票实测）**：2395 个 mutant、杀死 1514、存活 816、无测试 64、超时 1（`cmd_backup` 反转包列表探测条件的那一只走到真 adb 上等超时，按检测到算）。存活集中在命令的渲染与编排：`cmd_quickapp` 146、`cmd_check` 80、`cmd_status_json` 72、`msa_net` 63、`cmd_backup` 61、`cmd_devices` 47、`cmd_chan_scan` 43、`cmd_unsuspend` 39、`cmd_recipe` 31、`cmd_suspend` 29、`cmd_finish` 29、`quickapps` 29、`info` 26、`set_quickapp_service` 20、`dispatch` 14，其余 ≤11。64 个无测试全落在 5 个函数上：`quickapp_switch` 22、`cmd_dev_off` 20、`latest_backup` 12、`sh_all` 6、`py` 4——它们在这批用例里都被上层 patch 掉，唯一的直呼者是子进程对拍。原因是 `run.py` 的对外契约（30 条用例的 rc / stdout / stderr 逐字节）由 `tests/test_run_commands.py::CliParityTests` 守着，而那套驱动器起 `python tool/run.py` 子进程：副本里没有 `tool/` 视角，整类在 `UNUSABLE` 里摘掉，所以这些输出语句与只在子进程里跑到的入口在副本里既无覆盖也无断言。要在副本里拿回同一份 oracle，得把 30 条用例改写成进程内假 adb 驱动器（新造一套替身）或给 CLI 入口在副本里接一条 `src` 视角（改产品代码），成本闸门排除；管线本身（`src` 镜像、`scope_of`）不必动。模块只有整体才进表，故整份登记为缺口；下次纳入时按同一口径逐份清到零。
- **零变异节点 9 份实测登记**（#1547）：`geometry` / `phone/__init__` / `catalog/__init__` / `phone/errors` / `phone/surface` / `recipe_kit` / `recipe_nav` / `recipe_steps` / `recipe_strategies` 逐份跑 `devtools/mutation.py`，mutmut 原文结论统一是「无可变异节点：<模块> 里没有函数体可改」，`.mutmut/<组>/mutants/src/<模块>.meta` 里 `hash_by_function_name` 与 `exit_code_by_key` 都是空表——**mutant 0、存活 0、无测试 0、pragma 0**。九份的 AST 里 `def` 全为 0，`phone/errors.py` 的 `ScreenLocked` 是零方法的异常类，mutmut 生成不出可判节点，所以这不是「有 mutant 但缺测试」的表外缺口，而是**无可变异节点**。映射行只为让 mutmut 收集临时挂上、跑完即撤（零节点模块不入表；`reader` 的保留行是唯一例外，理由见 Consequences）。成因只有三类：

| 模块 | mutant | 存活 | 无测试 | 结论 / 理由 |
|---|---|---|---|---|
| `geometry` | 0 | 0 | 0 | 常量数据：一屏比例字面量（`TOP_BAND` … `TAPPABLE_BAND`），模块体只有赋值 |
| `phone/surface` | 0 | 0 | 0 | 常量数据：`DEVICE_PROPERTIES` / `DEVICE_VERBS` 两个 `frozenset` 与 `SCRIPT_SURFACE` 的并集 |
| `phone/errors` | 0 | 0 | 0 | 异常类：`ScreenLocked(RuntimeError)` 只有一句 docstring，零方法 |
| `phone/__init__` | 0 | 0 | 0 | 转发壳：包 docstring 声明子模块边界，无代码 |
| `catalog/__init__` | 0 | 0 | 0 | 转发壳：`from .loader` / `from .schema` 的 re-export 与 `__all__` |
| `recipe_kit` | 0 | 0 | 0 | 转发壳：从 `recipe_runtime` re-export 的 11 个名字 |
| `recipe_nav` | 0 | 0 | 0 | 转发壳：`sys.path` 注入 + `from recipe_lib import *` |
| `recipe_steps` | 0 | 0 | 0 | 转发壳：同 `recipe_nav` |
| `recipe_strategies` | 0 | 0 | 0 | 转发壳：同 `recipe_nav` |

  这三种成因下 mutation 没有判据价值：常量数据的对错是数值本身（`GeometryGuards` 守比例字面量只出现在 `geometry.py`），转发壳的对错是名字面（`ScriptSurfaceTests` 守脚本面、`test_recipe_nav` 的 `SurfaceTests` 守 re-export 名单），异常类的对错是类型层级。它们都不补测试、不入表，也不构成表外缺口——纳入一个零节点的模块只会让 mutmut 每轮空转一次收集。
- **`recipe_runtime` / `recipe_loader` 进表**（#1543），与表内模块同口径；映射行按覆盖矩阵量出（`recipe_runtime` 52 个测试文件、`recipe_loader` 49 个，均把 `tests/recipe_case.py` 换成继承它的十二个子类文件，`recipe_loader` 因替换补进矩阵里没有的 `test_oppo_plg110_recipe`，行不比矩阵窄）。初始实测 `recipe_runtime` 287 个 mutant（存活 103、无测试 13）、`recipe_loader` 26 个（存活 10、超时 2）。清零只靠补行为断言，没有新建 harness：段包装的四种结局与进度行（换一个计数的 stdout 流，`flush=True` 与默认值的差别才看得见）、`page()` 三段落点判据各自的现场行与协议 / 权限弹窗的每一句、`run()` 的尾钩子、`step()` 的登记与重名、`activate()` 的独占凭据、Counter 的四种读数与初值台账；装载入口补 `.py` 拒绝的全文消息与 `only` / `clock` / `namespace` 的转发。最终两份 269 / 26 个 mutant 全杀、无测试 0、超时 0。3 条 pragma 都是语义等价：`Counter.__eq__` 的 `isinstance(...) and False`（int 与 Counter 的比较经 `int.__eq__` 反射都归结为两侧 verified）、`page()` 的 `activity_part = where.split("/", 1)[-1]`（前台窗口至多一个 `/`，maxsplit / rsplit 变体取同值）、`outcome = None`（只与 `False` 做身份比较）。清零途中把包名判据写成 `partition("/")[0]`、缺 `class` 的空值收进 `NO_CLASS` 常量，消掉 maxsplit 与占位串两类分不出行为的变异。本票没有表外缺口。

- **观测基座 `phone/screen` 进表**（#1538），与表内模块同口径。覆盖矩阵量出 66 个测试文件执行过它（219 行），是表外最大的单模块；`tests/recipe_case.py` 是只有基类的助手模块，按实际所有者换成三个 `RecipeSafetyCase` 子类文件，再加上本票新建的 `test_phone_screen`（范围只宽不窄）。存活清零靠一套只经注入 `Connection` 的用例：前台窗口的三段解析、页面文字与快照、图标取样区的四条边界、`find` 的匹配顺序与页底折衷、手势命令逐字节、选择器动词与 `settle` 的默认预算。`back()` 与 `scroll_top()` 各有一例直接断言注入的 `sig` / `settle` / `scroll` 的调用步序，不是纯外部读数——这两处没有别的可观察副作用，留作单元级断言。清零途中把几处与可杀变异挤在同一行的等价写法拆开：`captures` 的三元改成显式分支、`focus` 的兜底正则拆成两支、`shell` 去掉恒真的「普通 str 先判」、`icon_candidates` 的 `zip(..., strict=True)` 改成两次算术、`iter("node")` 改成无参 `iter()`。10 条 pragma 都是语义等价或不可达：`Captures("")` 的空 root（None 与空串同值）、`focus` 第一支正则（group 前必有空格，兜底那一支用同一组同样命中）、`confirm_target` 里三处 `.get(...) or ""` 的缺属性占位与 `inner` 子集、`scroll_top` 两处循环末尾的 `break`（之后没有语句，与 `return` 等价）、`find` 的退化节点守卫与它下面那条 `continue`（`texts()` 只产出 `r > l` 且 `b > t` 的节点，退化节点到不了那里，不可达）。

## Consequences

- **判据只在映射表内说话**：表当前是 69 个模块（mypy 严格档的 12 个加 `catalog/schema.py`，加 `gui/` 的六份实体模块 `tasks.py` / `adb.py` / `dispatcher.py` / `reporter.py` / `updates.py` / `update_install.py`，加手机版替换层第一段的 `view.py` / `adb.py` / `screen.py` / `inproc.py` / `u2.py`，加 `devtools/` 的 16 份 `gh` / `claim` / `stale` / `followup` / `triage_audit` / `release_assets` / `release_meta` / `commits` / `check_dco` / `check_conventional` / `check_comment_tickets` / `check_ticket_ref` / `glob_scan` / `test_anchors` / `unittest_summary` / `script_surface`，加 `tool/` 其余模块的 `channel_decide.py` / `channel_arrive.py` / `channel_batch.py` / `channel_toggle.py` / `ui_hidden.py` / `screen_snapshot.py` / `phone/session.py` / `phone/navigator.py` / `phone/dismisser.py` / `phone/launcher.py` / `phone/screen.py` / `adapt.py` / `explore.py` / `recipe_audit.py` / `verify_ledger.py` / `adb_link.py` / `huawei_channels.py` / `fast.py` / `wait.py` / `captures.py` / `entries.py` / `vocab.py` / `phone/settings_search.py` / `phone/connection.py` / `ui_session.py` / `catalog/loader.py` / `stdio.py` / `troubleshooting.py` / `backups.py`），表外的改动只看得见、不判。这是刻意的收窄：每一行都要用覆盖矩阵量出来，收全仓会让「尺子有多宽」变成不可复核的东西。
- **只改测试的 PR 也跑受影响模块（#1531）**：删除检测的完整条件是「PR 改到该模块，或 PR 改到的测试文件覆盖该模块」。`--since` 由 `MODULE_TESTS` 现建「测试文件 → 模块」反向索引（不落第二份清单、不加缓存层），把反查结果与模块路径改动取并集（模块路径在前、测试文件在后，去重保序），stderr 分别列出「改到的模块」与「由测试改动拉起的模块」；表外测试文件反查不到行，保持零成本，表外模块的「本次不判」提示不变。实测最坏是 `tests/test_job.py` 与 `tests/test_result_retry.py`，各拉起 11 个模块、3879 个 mutant：冷缓存 111.8 s、热缓存 11.7 s；113 份被映射的测试文件里 39 份只拉起 1 个模块，最坏也在一个 job（10 min）之内，因此按全量反查接线。这条判据以模块组的工作目录是冷的为前提：mutmut 只按源码哈希作废旧裁决，同一工作目录里改测试不会重跑 mutant（实测删掉 `tests/test_dco.py` 的 `ViolationsTest` 整类后热缓存重跑，56 个 mutant 仍全报杀死、5.7 s 只跑了统计阶段）。
- **未清完的模块会挡住所有改它的 PR**：判据是「该模块存活 = 0」，存量存活没清完之前，改到它的 PR 会红。那是清理票要消掉的东西，不是误报。
- **`reader.py` 没有可变异节点**：`Reader` 是 Protocol、方法体只有 `...`，保留一行映射只为让 mutmut 有得收集；它的 `no_tests` 是预期结论，靠代码里没人碰它来满足，不硬补测试。
- **变异副本里跑不通的测试要摘掉**：副本只有 `src/`，起子进程、读 `android/` 源码、整仓扫文本的用例都会红，而红掉的用例会把碰过同一函数的 mutant 误判成杀死。整份文件跑不通的不进表；个别跑不通的按方法摘，整类都受影响的按类摘（`mutation_scope.UNUSABLE`）。
- **待办**：仍在表外的是 `gui/` 的界壳文件（`app` / `launch` / `shots`）、harmony 三份（`harmony_engine` / `harmony_client` / `harmony_vocab`）、手机版替换层第二段（`main` / `bridge` / `updates`，实测与结论见上「手机版替换层（#1430）」：`main` / `bridge` 是表外已知缺口，`updates` 过判据待实现）、`gui/` 其余非实体模块（`winpreflight` / `startup` / `toolpath` 等），以及刻意不纳入的 `devtools/` 自指两份（`mutation.py` / `mutation_scope.py`）与生成器三份（`gen_adr_index` / `gen_brand_taps` / `gen_site_css`）。`tool/` 其余模块正按 #1445 分批纳入，当前进度与逐批实测数字以「tool/ 其余模块（#1445）」一节为准（`devtools/typecheck_recipes`、`tool/chan_fast`、`tool/phone/toggler` 与 `tool/row` 已登记为表外已知缺口）；缺席是登记的，不是遗忘的，纳入之前，它们的行为变化仍由原规则人工守。
- **不建台账、不设周期 job**：存量的终态是可验证的数字（存活 = 0），不是一份「已知存活」清单；增量由 PR 长期维持，没有负责人就不会荒废。
