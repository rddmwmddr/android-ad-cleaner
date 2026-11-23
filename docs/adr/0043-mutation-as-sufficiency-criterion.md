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

## Consequences

- **判据只在映射表内说话**：表当前是 40 个模块（mypy 严格档的 12 个加 `catalog/schema.py`，加 `gui/` 的六份实体模块 `tasks.py` / `adb.py` / `dispatcher.py` / `reporter.py` / `updates.py` / `update_install.py`，加手机版替换层第一段的 `view.py` / `adb.py` / `screen.py` / `inproc.py` / `u2.py`，加 `devtools/` 的 16 份 `gh` / `claim` / `stale` / `followup` / `triage_audit` / `release_assets` / `release_meta` / `commits` / `check_dco` / `check_conventional` / `check_comment_tickets` / `check_ticket_ref` / `glob_scan` / `test_anchors` / `unittest_summary` / `script_surface`），表外的改动只看得见、不判。这是刻意的收窄：每一行都要用覆盖矩阵量出来，收全仓会让「尺子有多宽」变成不可复核的东西。
- **未清完的模块会挡住所有改它的 PR**：判据是「该模块存活 = 0」，存量存活没清完之前，改到它的 PR 会红。那是清理票要消掉的东西，不是误报。
- **`reader.py` 没有可变异节点**：`Reader` 是 Protocol、方法体只有 `...`，保留一行映射只为让 mutmut 有得收集；它的 `no_tests` 是预期结论，靠代码里没人碰它来满足，不硬补测试。
- **变异副本里跑不通的测试要摘掉**：副本只有 `src/`，起子进程、读 `android/` 源码、整仓扫文本的用例都会红，而红掉的用例会把碰过同一函数的 mutant 误判成杀死。整份文件跑不通的不进表；个别跑不通的按方法摘，整类都受影响的按类摘（`mutation_scope.UNUSABLE`）。
- **待办**：仍在表外的是 `gui/` 的界壳文件（`app` / `launch` / `shots`）、harmony 三份（`harmony_engine` / `harmony_client` / `harmony_vocab`）、手机版替换层第二段（`main` / `bridge` / `updates`，实测与结论见上「手机版替换层（#1430）」：`main` / `bridge` 是表外已知缺口，`updates` 过判据待实现），以及 `gui/` 其余非实体模块（`winpreflight` / `startup` / `toolpath` 等），还有 `devtools/` 的 `typecheck_recipes`（实测不达判据，见上）与刻意不纳入的自指两份（`mutation.py` / `mutation_scope.py`）、生成器三份（`gen_adr_index` / `gen_brand_taps` / `gen_site_css`），尚未纳入；缺席是登记的，不是遗忘的，纳入之前，它们的行为变化仍由原规则人工守。
- **不建台账、不设周期 job**：存量的终态是可验证的数字（存活 = 0），不是一份「已知存活」清单；增量由 PR 长期维持，没有负责人就不会荒废。
