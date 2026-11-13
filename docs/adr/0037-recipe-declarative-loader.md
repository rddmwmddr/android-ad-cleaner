# 机型脚本按模块装载：声明式段、单一装载器与这次执行

> B 段（catalog）由 [ADR-0038](0038-recipe-catalog.md) 取代（2026-11-13）：脚本不再是 exec 进来的代码模块，装载器、`rt` 两协作者、导入无副作用、快照作验证口径这几条边界在 ADR-0038 里重新确认；`RecipeScope` 与注入面消失。正文保留当时的决定与取舍。

基线 `18897ec`。父票 #1237，本票 #1241。

47 份机型脚本此前靠 `exec` 在一个注入作用域里运行：`@step` 是执行式装饰器，导入一份脚本就等于在手机上跑一遍。由此有三笔债：段顺序与钩子位置由书写顺序决定（钩子必须写在第一个 `@step` 之前），三处装载点（引擎的 run 分支、适配自检、测试装载）各写一份 `exec`，脚本侧没有静态检查（`recipes/` 不在 ruff 的目标里）。本票把脚本变回普通模块，段过滤与执行交给这次的运行上下文。

## Decision

### 声明式段与单一装载器

- **`@step("名字")` 只登记段名并原样返回函数。** 段体不在装饰那一刻执行；装载器扫描登记表，按函数定义行号排序，由 `Runtime.run()` 逐段执行。导入一份脚本不产生任何设备动作，顺序不再依赖「装饰器在模块体里被求值的先后」。
- **全仓只有一处装载实现：`tool/recipe_loader.py`。** `fast.execute` 的 run 分支、`adapt.check_draft`、`tests/fixtures.load_recipe` 都调它；旧的两份 `exec` 逻辑删除，main 上不并存两条路径。草稿（`adapt gen` 产出、没有 import 头）走同一个入口：`step` 由装载器注入。
- **脚本只拿两个协作者。** `p` 是设备面（公开面冻结不变）；`rt` 是这一次执行（`recipe_runtime.Runtime`）：段过滤、跳过出口、必需断言、安全模式、分段台账、失败段与中止标志、时钟、回读确认数。台账由引擎写、脚本只读；「回读确认了几项」只能经 `rt.confirm()` 表达。页面落点断言不属于 `rt`，它归词汇层（#1244–#1246）。
- **段过滤是 `run()` 的参数**（`only`），不再从 `globals()` 取；`WKL-AN20` 段内的自门控改读 `rt.only`。
- **收尾打印走声明式 `tail()`。** 19 份脚本结尾的模块级汇总打印搬进一个模块级函数，由引擎在所有段之后调用一次；表达式里的台账名换成 rt 上的同名概念，打印出来的文案逐字不变（报告者按行引用）。

### 模块体形状

脚本的模块体只允许导入、定义、常量、模块 docstring 与 `if TYPE_CHECKING:` 块。多余语句（`print`、`for`、设备调用）会在导入时执行，把顺序藏进模块体。守卫见 `tests/test_recipe_loader.py` 与规则 `dev.recipes.module-body-shape`。

静态可见性：脚本里除 `p` / `rt` 外的裸名字必须让 ruff 的 `F` 规则不报未定义（#1247 把 `recipes/` 纳入 ruff 的前置）。每份脚本在文件末尾（避免挪动词库引用的行号）挂一个 `if TYPE_CHECKING:` 导入；`step` 用真实的 `from recipe_kit import step`，其余注入名只为静态检查可见。运行时语义不变：装载器仍把闭包写进执行作用域。

### 事实层跟 import（#1243）

那个 `if TYPE_CHECKING:` 块就是「这个名字由哪个库提供」的唯一声明。事实层因此改为解析脚本的 import 得到 `{名字: 归属模块}`，再按归属去 `recipe_nav.NAV` / `recipe_steps.STEPS` 取实现源码：`injected_sources()`（把两张表按名字合并，同名互相覆盖）删除，换成 `surface_sources()`（两张表分开给出）与 `imported_sources()`（按 import 归到模块）。脚本本地同名 `def` 覆盖导入版；没有 import 的裸名字不再算注入实现。词库仍只扫 `STEPS` 那一张，入口速查两张都认。

### 词汇与策略库（#1244）

跨文件复用的本机函数分三档落库，形状与既有的两张注入面一致（工厂收 `(p, g)`、只造闭包、`install()` 写进执行作用域）：引擎词汇进 `recipe_nav` 的家族分节或跨家族分节，拨动策略进新模块 `recipe_strategies`（第三张注入面，`preamble()` 按 nav → strategies → steps 顺序安装）。

`NAV` 是扁平表，一个注入名只能放一份实现，而被冻结的段体仍按旧名字调用；所以「同族里同名但走法不同」的各注册一份，由脚本用模块常量选（`GEAR_STYLE` / `BROWSER_FLOW` / `MENU_STYLE`），缺省档保留多数机型的旧行为，值认不出时在调用那一刻报错而不是静默回退。只是字面量不同的参数化后共用。事实层把新模块加进 `SURFACE`，脚本 `TYPE_CHECKING` 块里的 import 指向哪张表就解析哪一份。

OPPO 系（oppo / oneplus / realme，16 份，#1245）按同一形状扩展这张表：`wait_page` / `tap_page` /
`tap` / `open_settings` / `search_settings` / `open_page` / `app_settings` / `system_settings` /
`settings_page` / `read_switches` / `close_named` / `hide_carousel` 各按 `*_STYLE` 常量分派，缺省档
保留未声明常量时的旧行为；`read_switches` / `close_named` 的分派表跟着名字留在 `recipe_nav`
（一张表一个名字，跨模块分派会把两张注入面绕在一起）。`page(activity, title)` 与 recipe_kit 注入
的 `page()` 同名不同签名，库里叫 `page_activity`，脚本把它绑回旧名字给段体用。

有一类函数故意不收：函数体里带着 `p.off(only=list(targets), …)` / `keep=…` 的，是 `vocab.py`
「未解析」台账与整页关闭数的现场，而词库只扫段体那张表；搬进策略库就把这几个数一起搬没了，
与本段「词库逐字节不变（含未解析数）」的验收冲突。所以 `off_exact`（一加两台与 PKH110）、
`close_named`（PLZ110 / PMX110 / PLG110 / PMA110）、`close_group` / `close_all`（PKT110）留在
脚本里，理由与 #1148 留 `off_exact` 时相同。浏览器设置页的两档 OPPO 入口另有约束：入口串按
执行作用域里的包名常量拼，否则导入同一个 `browser_settings` 的其它家族会被入口速查算上这条直达。

vivo / 荣耀 / 魅族 / 三星（15 份脚本，#1246）按同一形状收口。vivo 十份（九个型号目录）算一个真正的家族库：
`tap_row` / `by_desc` / `result_xy` / `search_setting` / `hiboard_panel` / `hiboar_panel` 进 vivo
分节，关开关的过程（`rows` / `off` / `confirm2` / `dialog_open` / `row_switch` / `switch_off` /
`setting_search` / `off_one` / `store_personalization`）进策略库；`gear` / `gear_top` /
`read_switches` / `browser_settings` 各加 vivo 档。荣耀只有三份、魅族与三星各一份，都不足以开
家族库：它们只往共享库加「注入名已经住在那里、别家也在用」的档（`enter` / `tap` /
`app_settings` / `open_settings` / `my_tab` / `tap_text` / `goto` / `wait_page` / `close_named` /
`browser_settings`）；其余本机助手留在脚本里，逐个列在 #1246 的汇报与票面评论里。判据是
「这一份实现是不是别家也在用」：只服务一台机的 `settle_page` / `labels` / `radio` / `dismiss` /
`page_summary` / `tap_id` / `open_app` 搬进共享库，等于给一份脚本造家族库。

三星的 `protect` 因此仍是本机函数：它写的是这一页「点标题而不是点开关、把保护类开关拨回开」，
且是 #608 的临时回退，等真机复测通过后才换回 `p.off`。三星原来那一个本机策略因此不减——这是归属
规则的结果，不是漏收。

### 为什么不是只做模块化

只把 `exec` 换成 `import`、保留执行式 `@step`，会得到最坏的组合：导入仍有设备动作，段顺序仍由书写顺序与钩子位置决定，`only` 仍从 `globals()` 取，三处装载点仍各写一份。脚本看起来是模块，行为契约却还是「导入即执行」，静态检查与装载期报错都无从谈起。声明式段、单一装载器与 `rt` 是同一笔改动的三个面：没有声明式段，装载器无法在导入后再决定跑哪些段；没有 `rt`，段过滤与台账只能继续留在 `globals()` 里。

### 增补（#1247）：草稿与静态检查收口

- `adapt gen` 的草稿不再是没有 import 头的特例：它带上 `from recipe_kit import step` 与文件末尾的 `if TYPE_CHECKING:` 块，与正式脚本同形，因此能被 `recipe_loader.load()` 直接装载（`adapt check` 走的仍是同一个装载器，上面 Decision 里「草稿没有 import 头」那句只描述当时的生成物）。
- 注入名在类型层面可见：`recipe_kit` / `recipe_nav` / `recipe_strategies` / `recipe_steps` 各有一个模块级 `__getattr__`，`if TYPE_CHECKING:` 块里的 import 因此认得出来，运行时照旧由执行作用域提供。
- `recipes/` 进静态检查：ruff 的 F401 在 `pyproject.toml` 按文件整类关掉（注入面按名字取用是假阳性）；mypy 由 `tool/typecheck_recipes.py` 逐份喂给同一个宽松档（43 份都叫 `recipe.py`，一次扫会撞模块名）。
- 共享分节的归属规则落成机器判据：`recipe_nav.SHARED` / `recipe_strategies.SHARED` 列出的注入名必须被 ≥2 个家族使用，见规则 `dev.recipes.shared-sections`；家族分节允许单脚本变体。

### 增补（#1253）：词库扩到策略库

上面「词汇与策略库」一节里有一类函数故意留在脚本：函数体里带 `p.off(only=…)` / `keep=…` 现场，
而词库只看段体那张表，搬走就读数变小。这一条现在解开了——词库也扫策略库
（`recipe_source.strategy_sources()`，`tool/vocab.py` 的 `scan()` 收 `strategies=`），扫哪几份仍由
脚本自己的 import 决定（#1243 的口径不变），所以现场可以跟着实现走：

- 剩下 14 个拨动策略（OPPO 9、vivo 1、荣耀 3、魅族 1）搬进 `recipe_strategies` 的家族分节，脚本
  只留调用点。词条数 / 方向 / 未解析 / `keep=` / 整页关闭数与改动前逐条相同，入口速查与段体哈希
  逐字节不变。三星 `protect` 仍是本机函数：它是 #608 的临时回退，等真机复测通过后才换回 `p.off`。
- **同一份实现一处只算一次。** 策略会被一个段调用多次（`close_all` 出现两次），按调用点各扫一遍
  会把未解析与整页数乘起来；脚本搬掉本地 `def` 之前，那份实现也只是模块里的一份。所以词库对每个
  导入的注入名只扫一次、出处记第一个调用点。
- **没有调用点的实现记到导入行。** 有两类：库按名字回调的钩子（`browser_settings` 的荣耀档调
  `g["baidu_browser"]`）与模块别名（`off_exact = off_exact_paged`、`close_named = close_named_optional`）。
  事实层因此多记一份 `Facts.import_lines`，词库在零调用点时退到那一行；别名本身是脚本声明
  「执行作用域里这个旧名字由那份实现提供」，与 `recipe_android15.py` 的 `page = page_activity` 同形。
- **注入名不能和 nav 撞。** `preamble()` 先装 `recipe_nav`、再装 `recipe_strategies`，同名会把 nav
  那几档盖掉（`close_named` 的 meizu 档、`off_exact` 的 Android 15 档）。所以策略库里的几套走法各
  用带后缀的注入名，脚本用别名把库按名字回调的那两个钩子绑回旧名字，段体一行都不用改。
- **内层闭包仍叫旧名**（`off_exact` / `close_named`）：词库的 `_absorb()` 按 `call.function ==
  "close_named"` 认「`p.off` 在助手里面」，改名会把那份未解析数从「不算」变成「算」。

### 目录化是后续方向

本票只做运行时形状：脚本仍是 Python 模块，段体仍是代码。真正的门槛在写脚本的人——一份机型脚本仍等于一个程序，要手写翻页、返回与等待。数据树 + 解释器（「进哪一页、关哪些、留哪些」由数据描述，运行时解释）是后续方向，由独立追踪票承载；它要求先有本票的运行时（段、`rt`、单一装载器）与词汇层（#1244–#1246）。本票的 `rt` 与装载器按「将来由解释器驱动」设计，但不实现数据模型。

## Considered Options

- **只把 `exec` 换成 `import`（否）**：见上，导入仍执行、顺序仍隐式、三处装载点不收敛。
- **把注入改成代理对象以满足 ruff（否）**：运行时要按名字解析到当次执行，代理对象会把「缺名字」从装载期错误变成运行期错误，也改变 `g["…"]` 的取法。
- **在装载期校验共享段体所需的全部名字（本票不做）**：`Runtime` 已经能在段入口按名字取，缺名字会当场报错；把校验前移到装载期需要先定义「哪些名字属于哪段」的声明，留给词汇层与目录化一起做。
- **删掉 `VERIFIED_SWITCHES` 在段体里的两处 `+=`（否）**：`oppo-PLG110` / `oppo-PMA110` 的 `+=` 写在段体正文里，改它会让段体哈希变化（#1242 的台账判据）。装载器给这两份脚本注入一个引擎写的计数器，`+=` 仍经 `rt.confirm()` 记账；其余脚本的模块级助手直接调 `rt.confirm(n)`。

## Consequences

- 47 份脚本的调用序列快照零差异（present / absent，13,484 条调用），词库与入口速查逐字节不变，台账段体哈希只在 `honor-WKL-AN20` 的 `ONLY` 那一行变化（该行改读 `rt.only`）。
- 共享段体与导航助手仍按名字从执行作用域取（`g["…"]`），本票不搬词汇与策略；`recipe_nav` / `recipe_steps` 的注入面形状不变。
- `tests/fixtures.load_recipe` 的返回值仍是脚本命名空间；`scope["ONLY"]` 代理到 `rt.only`，回读确认数是引擎注入的计数器，测试断言不用改语义。
