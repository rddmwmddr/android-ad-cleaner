# `recipe_lib` 是库名字表的唯一 owner：三个稳定 import 面只是兼容壳

基线 `cefd3f6`。父票 #1343，落地子票 #1344–#1347。

## 问题

同一份 interface 被叙述了三遍。`tool/recipe_nav.py` / `recipe_strategies.py` / `recipe_steps.py`
除第 1 行 docstring 外逐字相同：同样 31 行显式 re-export、同样一份 `__all__`，各约 9.5 KB。
真正拥有这批名字的是 `recipe_lib/` 里五个家族文件与跨家族的 `shared.py`（`MODULES` 六项）的 `__all__`（家族之间无重名），而
`catalog.interpreter.LIBRARY` 只是把三个面做并集算出来，自己不陈述任何一个名字。同一批名字还要
再建两份表：`recipe_source.library_sources()` 与 `catalog.loader.CatalogScope._library_view()`。
改一个库实现的名字要在家族模块与三个面里各改一遍；最近 300 条提交里这三个面被改 57 次。

## Decision

### owner 落在 `recipe_lib/__init__.py`

四样东西都在那里：今天三份面里那 31 行显式 re-export 块（搬一次）、
`LIBRARY = {name: getattr(module, name) for module in MODULES for name in module.__all__}`（派生，不手抄）、
`HELPERS`（面助手的具名元组）、字面量 `__all__`。

### `__all__` 必须是字面量

mypy 解析 `from recipe_nav import <名字>` 时看的是源模块的 `__all__`：owner 的 `__all__` 是计算值时，
面里的 `from recipe_lib import *` 让 mypy 认不出 `recipe_nav.tap_row`（`attr-defined`），
`devtools/typecheck_recipes.py` 会红。字面量 + owner 里逐个显式 import 才恢复。失效条件：mypy 能静态求值
计算值 `__all__`，或 recipes 的例外 `.py` 不再直接 `from <面> import <名字>`。

### 三层命名集合不许混

六个模块的 `__all__` 并集是「数据 `lib:` 能点名」的词汇 → `LIBRARY` 就是它 →
`__all__` 是「能从稳定 import 面取到」的名字，多出 `HELPERS` 那一批面助手（`maybe` / `labels` /
`MenuState` / `close_named_step` / `off_exact_step` / `require_installed` / `title_key` /
`verify` / `_labelled`）。面助手留在 `__all__` 里、**不进** `LIBRARY`：把助手补进某个模块的
`__all__` 会把数据可点名的词汇也扩一格。

### 增补（#1363 / #1371）：计数以实算为准，面助手与数据词汇的分界

`search_more` / `ad_tracking_close_paged` 升格进家族库后，这一层的计数随库增长漂移；数字以
`recipe_lib.LIBRARY` / `__all__` / `HELPERS` 的实算为准，正文与 `ARCHITECTURE.md` 不再抄死数。

面助手与数据词汇的分界判据是「是不是只读前台 / 页面树给段体用」——`settle_page`
自己走读屏与等待，与 `wait_page` 同档，所以从 `HELPERS` 移进 honor 家族词汇，阅读那段才能把
「点下一行之前先等版面定下来」写进数据。留在 `HELPERS` 的是只做投影 / 断言的那几个
（`labels` / `title_key` / `verify` / `_labelled` …），它们不自己读屏；`MenuState` 是类型不是调用，
一并留在原处。

### 三个面是兼容壳，不删

各剩 docstring + `sys.path` 垫片 + `from recipe_lib import *` + `__all__` 转发。不删是因为
`recipes/` 60 处、`tests/` 20 处、`tool/` 9 处 import 不必改一行 —— 机型脚本是社区可以提 PR 的文件。

### `sys.path` 垫片为什么还在

`recipe_lib/` 在仓库根、与 `tool/` 平级，而宿主只把 `tool/` 放进 `sys.path`（源码运行时
`gui/app.py` 与命令行脚本都是这样）。直接 `import recipe_lib` 的 `tool/` 模块各自补一次：
三个兼容面、`tool/catalog/interpreter.py`（深一层 `dirname`）、`tool/recipe_source.py`。
`tool/catalog/loader.py` 是例外：它直接 `import recipe_lib` 却不另抄垫片，靠先被导入的
`from . import interpreter` 拿到垫片副作用（注释里已声明这条依赖）。
失效条件：`recipe_lib` 挪进 `tool/`，或每个宿主自己把仓库根放进 `sys.path`。

### 引擎的表是拷贝，事实层直接问 owner

`catalog.interpreter.LIBRARY = dict(recipe_lib.LIBRARY)` —— 拷贝而不是共享引用，
`tests/fixtures.py` 的打桩助手与 `tests/test_catalog.py` 会就地改它再还原。`library_sources()`
迭代 `sorted(recipe_lib.LIBRARY)`，归属仍写函数真正的 `__module__`，输出与改动前内容逐字相同（键序改成按名字排序）；
`CatalogScope._library_view()` 的二次查找表换成在 `recipe_lib.__all__` 上按名取（`getattr(recipe_lib, key)`，非名字表成员仍抛 `KeyError`），四种特例结局不变。
`recipe_source` 的 `NAV_MODULE` / `STRATEGIES_MODULE` / `STEPS_MODULE` / `SURFACE` 保留：
事实层还要认 `nav.gear(...)` 这种写法。

### 守卫

`tests/test_recipe_nav.py::SurfaceTests` 四条：`__all__` 的集合与长度等于「家族并集 ∪ 助手」、
`LIBRARY` 等于家族并集且与助手无交集、`LIBRARY[name]` 就是 owner 上那个同名对象（跨家族重名会让
派生顺序覆盖显式绑定）、三个面的导出集合全等且等于 owner 的 `__all__`。
不登记 `docs/agents/rules.toml`：它守的是结构不变量，不是维护者要遵守的规则。

### 与 ADR-0035 / ADR-0037 的关系

那两份正文里「`recipe_steps` 是段体唯一落点 / 第三张注入面」的叙述已由
[ADR-0038](0038-recipe-catalog.md) 取代（拆注入面 #1268、拆库 #1269），文首各自的 superseded 行
早已写明。本文件不重复那条取代关系，只补名字表这一层：三个面从「各自陈述 140 个名字」退成转发壳。
两份正文不改：它们记录的是当时的决定。
