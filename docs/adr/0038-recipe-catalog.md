# 机型脚本的终态：页面树数据 + 运行时 + 家族策略 + 本机例外

> 本 ADR 记 B 段（catalog）的终态形态，取代 [ADR-0029](0029-recipe-preamble-injection.md) / [ADR-0034](0034-recipe-source-facts.md) / [ADR-0035](0035-recipe-steps-injection.md) / [ADR-0037](0037-recipe-declarative-loader.md) 里「机型脚本是 exec 进来的代码模块、共享助手靠注入面提供」这一前提下的决定。四条 ADR 各自在文首挂 superseded 行并链接本条，正文保留当时的取舍。

基线 `e72b7da`（本地 `dev`，B 段起点）。父票 #1238，本票 #1258。

> 实现进度：六批迁移（#1262–#1267）与拆注入面（#1268）、拆库（#1269）、手册重写（#1270）都已完成，收口与实测在 #1271；47 份数据全部是页面树，`@step` 全仓清零，迁移转换器已删除。实测数字与命令见「验收实测」。
>
> #1268 按本 ADR 拆除了四样覆盖机制（`@step`/`STEPS`、`preamble()`/`install()`/执行作用域、事实层 import 归属、同名覆盖），并删除 `RecipeScope` 与装载器的 `.py` 分支；库实现改为普通函数 `(p, rt, …)`，数据用 `lib`/`code` 按名字点名。

A 段（[ADR-0037](0037-recipe-declarative-loader.md)）把脚本从 `exec` 变成普通模块、把段过滤与台账收进 `rt`，但**没有换知识的组织方式**：一份脚本仍是一段手写程序，翻页、返回、等待、重试全在代码里。`p.back()` 全仓 611 次，其中 181 次靠人手数深度（2 级 139 / 3 级 39 / 4 级 3）；浏览器 38 个机型 35 种形态、应用商店 27/24、手机管家 16/5、下载管理 15/5、负一屏 29/14——同一页的知识被抄了多遍。B 段把「有哪些页面、有哪些行、怎么进去、关哪些、留哪些」从程序里拿出来，变成**数据**，让运行时去解释；写一台新机从「写一个程序」降成「填一份数据」。

## Decision

### 终态形态

机型脚本的仓库形状定成四样：

- `recipes/<家族>/<型号>/<型号>.toml`：页面树数据——入口候选、要关的与要留的、子页、死路、守卫、收尾、尾钩子；
- `recipes/<家族>/<型号>/<型号>.py`：**只放这台机的例外函数**（有才写，没有就是空/不写）；
- `recipe_lib/<家族>.py` + `recipe_lib/shared.py`：家族策略与跨家族共享策略（词汇 / 策略两节，见 [ADR-0037](0037-recipe-declarative-loader.md) 收进来的两层）；
- `tool/catalog/`：装载、校验、解释器，是数据的**唯一**执行入口。

家族取自 `entries.FAMILY`（`xiaomi` / `oppo` / `vivo` / `honor` / `huawei` / `meizu` / `samsung` 七个），不另建一份家族表。型号身份仍**声明在数据里**（一条数据可声明多个型号），不从路径推；`<型号>-<变体>.toml` 表同目录变体。

### 覆盖机制——随「脚本是 exec 进来的代码模块」一起消失的四样

A 段的四个机制都是为了「让手写脚本写法不变地拿到共享助手」而存在。脚本只剩十几个例外函数之后，它们只剩成本：静态检查失效、事实层被迫做归属解析、同名覆盖成静默陷阱。四样各交代被什么取代：

1. **`@step` / `STEPS` 注入面**（[ADR-0035](0035-recipe-steps-injection.md)）。前提：段体是逐字复制的代码块，收进注册表能让脚本只留一行调用。被取代：段变成数据里的一个节点，没有「段体代码」可收；跨机重复的知识落进树或家族策略，`STEPS` 整张表删除。
   - 前提：同一段体在 ≥2 份脚本里逐字相同。
   - 被推翻条件：若迁移后某个 `code = "<本机策略名>"` 兜底在同一家族里出现 ≥2 次，它就该升格进家族库，而不是继续留在各机 `.py` 里。
2. **`preamble()` / `install()` 与执行作用域**（[ADR-0029](0029-recipe-preamble-injection.md)）。前提：脚本 `exec` 进一个共享字典，注入面把闭包写进去、脚本按裸名字取。被取代：运行时直接调 `recipe_lib` 的普通函数、把 `p` / `rt` 当参数传；没有执行作用域，也就不存在「名字从哪来」的问题。
   - 前提：脚本的执行期是「引入模块命名空间」。
   - 被推翻条件：若解释器仍需要把一批名字塞进一个可变字典给数据里的 `code=` 用，说明例外函数没有收干净——那是要修的例外，不是要恢复的机制。
3. **事实层按 import 归属解析**（[ADR-0034](0034-recipe-source-facts.md)，`surface_sources()` / `imported_sources()` / `injected_calls()` / `step_sources()` / `strategy_sources()`）。前提：脚本 `from recipe_nav import gear` 声明「这个名字由哪个库提供」，事实层据此去查对应注册表。被取代：没有注入面就没有归属要解析；事实层退化为**代码里的字面量提取器**，只服务 `recipe_lib` 实现与本机例外函数——B 段之后仍有 45 个本机函数与 169 个库实现是代码（`python3 tool/recipe_audit.py --summary`、`tool/recipe_audit.py` 的库计数见「验收实测」），其中的开关名字面量仍要 AST 提取。
   - 前提：共享实现靠 import 声明归属。
   - 被推翻条件：不能整块删——`scan_source` / `scan_dir` 与「字面量投影」这条路要留；只有归属层（约 90 行 + 15 条用例）删。
4. **执行作用域里的同名覆盖**（本地 `def` 盖住注入版）。前提：同一批注入名要同时服务写法各异的旧脚本。被取代：库函数各有明确的名字与调用点，数据用 `code = "<本机策略名>"` 显式指向本机函数，没有「猜哪个定义生效」。

**一条硬约束**：树的每个节点仍必须经段执行入口 `Runtime.run_step(name, action)` 执行。段归属钩子（`recipe_runtime.OBSERVER`）是 13,484 条调用序列快照按段对齐的基础；解释器若绕过它直接调页面算法，快照的段维就断了，结构等价证据随之失效。

### 重述边界——B 段之后更需要，逐条重新确认

五条不因为换了表示而失效，反而更吃重，因此**重新确认**而不是引用旧条：

1. **单一装载点。** 仍然只有一个「读一个目录 → 可执行对象」的入口，让 `tool/catalog/` 承载，校验器与解释器**共用**它（不让校验走一条路、执行走另一条）。引擎的 run 分支、`adapt.check_draft`、测试装载仍只走这一处。
2. **`p` / `rt` 两协作者。** 数据解释与例外函数都只拿 `p`（设备面，公开面冻结）与 `rt`（这一次执行：段过滤、跳过/断言出口、安全模式、台账、失败段、时钟、回读确认数）。数据不接触第三个协作者。
3. **`.py` 导入无副作用。** 例外函数是普通模块级函数，导入它不产生任何设备动作；执行时机由解释器（经 `Runtime.run_step`）决定，不由导入决定。
4. **家族 / 共享归属判据。** 共享分节里的每个实现必须被 ≥2 个**家族**使用（家族取自 `entries.FAMILY`），家族分节允许单脚本变体。判据不变，只是落点从 `recipe_nav` / `recipe_strategies` 换成 `recipe_lib/<家族>.py` / `shared.py`。
5. **调用序列快照作验证口径。** 47 份 × 2 场景（`present` / `absent`）、13,484 条调用（`python3 tests/compare_recipe_calls.py`），结构等价看「同一份合成手机、同一组读屏观察下调用逐条相同」，不看数据文件内部结构或解释器内部函数。

### 兑现接缝——ADR-0037 留给 B 段的三条，逐条交代

1. **「目录化是后续方向」。** 用上了，且就是本 ADR 的落点：A 段停在那里只换装载方式，B 段把知识组织成数据。当时预留的运行时（段、`rt`、单一装载器）与词汇层（#1244–#1246）确实够用，B 段没有再造一套运行时。
2. **「`rt` 与装载器按将来由解释器驱动设计」。** 部分用上：`rt` 的段过滤 / 台账 / 确认数原样复用，解释器直接驱动 `Runtime.run_step`；但装载器的 `RecipeScope`（可变执行作用域）这一层用不上——它服务的是注入面，注入面消失后由 `tool/catalog` 的装载入口取代，不保留 `RecipeScope`。
3. **「装载期名字校验留给目录化」。** 用上了：schema 校验器在装载期拒绝未知键（种类白名单），数据缺键、`only`/`keep` 重叠这类错在 CI 就报出来，不必等真机。

### 数据模型边界

schema **只装机型知识**，编排语义**不进数据**：

- 进 schema：入口候选（直达页面 / 公开意图 / 文字路径 / 底部标签 / 图标 / 坐标 / 资源 id / 手势，外加等待标记与重试次数）、要关的与要留的（精确 / 包含 / 关键词、方向、页标签、翻页上限、整页全关、点名来源）、子页（递归）、守卫（机型与版本、页面模式、行状态、相邻状态、包存在、音频状态）、收尾、尾钩子（人话文案）、兜底 `code = "<本机策略名>"`。
- **不进 schema**：早退、中止、重试、失败收集、台账写入、页面快照——这些是运行时的编排语义，全机型同一套。

`only` 两态：要么是内联字面量，要么整段交给 `code = "<本机策略名>"` 指向本机函数；两者在运行期都算「点名」，安全模式都不抑制。UI 上的「全部关闭」按钮单列一种动作并登记为 page-wide，不再靠「没有 `only`」推断整页关闭。

**封闭清单**：schema 校验器里是种类白名单，未知键直接报错。扩展一条新知识种类的判据是「≥2 机型用法」，不是数字上限——看到用不上就别加，看到恰好用一次先按本机例外写。

### 页面算法一律复用，不新写

解释器不重造页面算法：关一页用 `phone/toggler.py` 的 `Toggler.off`（`plan_switches` / `readback` 不动），等页面用 `wait.until`，入口执行器收在 `entries.reach` 一支——把渠道页与普通导航收成两种候选类型，**不写第三个「直达 → 回退」**。

### 迁移转换器与删除条件

`#1260` 把迁移转换器做成**临时工具**：迁移期入库、受 CI 测试覆盖，能把一份旧脚本转成 TOML 并输出三列报告（转换成功 / 缺哪个键 / 表达不了），对 47 份重跑测量、结果写进父票评论。覆盖跌破 80% 时停工回 grilling。

**删除条件已满足**：最后一批（#1267）迁完、验收总表（结构等价 / 字面量逐条对账 / 词条单向基线 / 深支 / 本机策略不涨 / schema 合法 / 真机按形状抽样）在 #1271 逐项核对（结论见「验收实测」），转换器与其用例随即删除，不留死代码。它在迁移期一直是 CI 覆盖对象。

### 编号

本票不 rebase。最终把集成分支合回 `dev` 前若 ADR-0038 已被并行会话抢占（违规抢号），按 [docs/agents/domain.md](../agents/domain.md) 的「Numbering a new ADR」重取号并改所有引用。

### 验收实测（#1271）

B 段收口时在仓库根现算。`python3` 指仓库根的 `.venv`（`python3.13`），下列命令都不碰手机。每条数字后面跟可复现命令，不要照抄旧值。

- **数据份数与段**：47 份 `.toml`，369 段；265 段是 `ops`（数据化 71.8%）、104 段留 `code=`；另有 42 份例外 `.py`。
  ```bash
  python3 -c 'import tomllib,pathlib as P;f=[p for p in P.Path("recipes").rglob("*.toml") if p.name!="verified.toml"];s=[x for p in f for x in tomllib.loads(p.read_text())["segment"]];print(len(f),len(s),sum("ops" in x for x in s),sum("code" in x for x in s))'
  find recipes -name '*.py' | wc -l
  ```
- **调用序列快照（结构等价）**：47 份 × 2 场景，13,484 条，差异 0。
  ```bash
  python3 tests/compare_recipe_calls.py
  ```
- **深支**：104 段 `code=` 全部在快照里记到调用。
  ```bash
  python3 -c 'import json,tomllib,pathlib as P;snap={json.loads(p.read_text())["script"]:{c[0] for sc in json.loads(p.read_text())["scenarios"].values() for c in sc} for p in P.Path("tests/snapshots/recipe_calls").glob("*.json")};code=[(p.as_posix(),x["name"]) for p in P.Path("recipes").rglob("*.toml") if p.name!="verified.toml" for x in tomllib.loads(p.read_text())["segment"] if "code" in x];print(sum(n in snap.get(p,()) for p,n in code),"/",len(code))'
  ```
- **词条**：1,410 处词（另有 25 处整页全关、不点名）。
  ```bash
  python3 tool/vocab.py | grep -o '共 [0-9]* 处词'
  ```
- **词条单向基线**：B 段起点 `e72b7da` 的 1,307 处词到现在的 1,410，按 `(text, kind, family, model, group)` 展开的多重集里基线一条不缺。增量的大头是 #1267 把天气 / 日历的 `{pkg}·…` 页标签按包名展开成两条，同一组词因此各多记一次；判据是「一条都不缺」，不是「数目不变」。
  ```bash
  mkdir -p /tmp/aac-base && git archive e72b7da | tar -x -C /tmp/aac-base && python3 -c 'import sys;sys.path.insert(0,"/tmp/aac-base/tool");import vocab;[print("\t".join([w.text,w.kind,w.family,w.model,w.group or ""])) for w in vocab.scan("/tmp/aac-base/recipes").words]' | sort > /tmp/terms-base.txt && python3 -c 'import sys;sys.path.insert(0,"tool");import vocab;[print("\t".join([w.text,w.kind,w.family,w.model,w.group or ""])) for w in vocab.scan("recipes").words]' | sort > /tmp/terms-now.txt && comm -23 /tmp/terms-base.txt /tmp/terms-now.txt | wc -l
  ```
- **本机策略不涨**：45（策略 1 / 词汇 9 / 知识 9 / 钩子 26）· 47 份；B 段起点是 53（1/13/13/26）。
  ```bash
  python3 tool/recipe_audit.py --summary
  (cd /tmp/aac-base && PYTHONPATH=tool python3 tool/recipe_audit.py --summary)
  ```
- **库拆分**：169 个普通函数：shared 22 / xiaomi 34 / oppo 61 / vivo 36 / honor 10 / meizu 6。
  ```bash
  python3 -c 'import ast,pathlib as P;fs=[(p.name,len([n for n in ast.parse(p.read_text()).body if isinstance(n,ast.FunctionDef)])) for p in sorted(P.Path("recipe_lib").glob("*.py")) if p.name!="__init__.py"];print(fs,sum(n for _,n in fs))'
  ```
- **schema 合法**：47 份全部过 `tool/catalog` 校验器。
  ```bash
  PYTHONPATH=tool python3 -c 'import tomllib,pathlib as P,catalog;[catalog.validate(tomllib.loads(p.read_text())) for p in P.Path("recipes").rglob("*.toml") if p.name!="verified.toml"];print("ok")'
  ```
- **入口速查**：生成物与入库文档逐字节相同。
  ```bash
  python3 tool/entries.py | diff - docs/清单/入口速查.md
  ```
- **打包面**：`gui/bundle_data.py` 的清单带 48 个 `.toml`（47 份页面树 + `verified.toml`）、7 个 `recipe_lib/*.py`（6 个模块 + `__init__`）、42 个例外 `.py`；`gui/windows.spec` 与 `gui/build_mac.sh` 直接消费这份清单，`android/app/build.gradle.kts` 另抄同一组模式，守卫在 `tests/test_recipe_variants.py` 与 `tests/test_android_bundle.py`。
  ```bash
  python3 -c 'from gui.bundle_data import bundle_data;ps=[s.replace(chr(92),"/") for s,_ in bundle_data(".")];print(sum(p.endswith(".toml") and "/recipes/" in p for p in ps),sum("/recipe_lib/" in p for p in ps),sum(p.endswith(".py") and "/recipes/" in p for p in ps))'
  ```
- **真机按形状抽样**：**未做（`unverified`）**。47 份数据都是迁移后的形态，台账里最后一次真机验证（2026-11-12）早于迁移（2026-11-13 起），当前形态一份都没在真机上跑过；其中 3 份没有任何记录。判据与逐份清单见 #1271 的报告，数据现算：
  ```bash
  python3 tool/verify_ledger.py
  ```

前六项全绿，第七项 `unverified`。这就是「验收总表」的结论。

## Considered Options

- **只做模块化、不做数据化**（否）。A 段已经证明模块化只换装载方式：一份脚本仍等于一个程序，新机适配仍要写程序。catalog 是可证伪地向前一步（spike：369 段体里机器判据下 87.3% 不需要模型知识，补转换器缺口后 95.7%；迁移后的实测是 369 段里 265 段是 `ops` 数据、104 段留 `code=`，见「验收实测」）。
- **把编排语义也塞进 schema**（否）。重试、收尾、失败收集、台账、页面快照是全机型同一套，进数据只会让每份数据各写一遍、各错一遍。
- **转换器长期保留为迁移工具**（否）。它是「旧脚本 → 新数据」的一次性载体；迁移完成后没有旧脚本可转，留着就是死代码。删除条件写进上文。
- **保留 `RecipeScope` 让例外函数还按裸名字取 `p`/`rt`**（否）。那会把注入面的隐式依赖带进终态；例外函数改成普通函数、`p`/`rt` 作参数传入，静态检查才看得见本机代码。

## Consequences

- `@step` / `STEPS` / `RecipeScope` / `preamble()` / `install()` 删除；`NAV`（75）/ `STRATEGIES`（29）的实现转为普通函数库搬到 `recipe_lib`，迁移后按家族拆成 169 个函数（shared 22 / xiaomi 34 / oppo 61 / vivo 36 / honor 10 / meizu 6，命令见「验收实测」）。
- 事实层从「三张表的归属解析器」降为「代码里的字面量提取器」，归属层（约 90 行 + 15 条用例）删除，`scan_source` / `scan_dir` 与字面量投影保留。
- `tool/catalog/` 新增装载 + 校验 + 解释器；校验器在 CI 跑全 47 份数据。
- `recipes/` 的数据部分（`.toml`）退出 ruff / mypy 范围（换出去 A 段 #1247 的收益），检查点落在校验器与运行时；`.py` 例外函数仍在静态检查范围内。
- `CONTEXT.md` 加「页面树 / 本机策略 / 家族库 / 共享库 / 段」五个术语；`docs/04` 的新机型手册按「只填数据」重写（#1270）。
- 验收总表（结构等价 / 字面量逐条对账 / 词条单向基线 / 深支 / 本机策略不涨 / schema 合法 / 真机按形状抽样）在 #1271 逐项核对：前六项绿，真机抽样未做、47 份全标 `unverified`（结论与命令见「验收实测」）。#1238 在 #1271 合入后即可关。
