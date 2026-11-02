# `Api` 拆成三块：门面转发，状态按产生者归属

基线 `a788fa1`（`#452` 的三处竞态先于本决策合入）。

`gui/app.py` 的 `Api` 一个类装了 34 个方法：窗口桥、adb 下载与校验、错误上报、剪贴板、批处理调度。`Api.__init__` 同时持有 `ClientData`、`Backups`、`Runner`、`Job` 与四个自由属性 `dl` / `last_status` / `last_error` / `last_devices`。改下载逻辑要穿过上报与调度的方法，`#447` 把执行状态收进 `Job` 之后这个类仍然没有责任边界。

票面（[#390](https://github.com/rddmwmddr/android-ad-cleaner/issues/390)）要求拆成 `AdbDownloader` / `Reporter` / 批处理调度三块，`Api` 退化为窗口桥门面，对内暴露的方法名与签名逐项不变，三块之间不互相读取内部状态。

## Decision

**三块各自成为一个类，`Api` 组合它们并逐个转发；跨块状态按「谁产生谁拥有」分配，不抽共享状态对象。**

### 文件落点

三个类都留在 `gui/app.py` 内，用类边界与区段注释分隔。`Api` 依赖模块级的 `_tool()` / `chime()` / `adb_present()` 与一批常量，拆到新文件要么循环 import，要么把这些一起搬走；搬走后 8 处 `patch.object(app, "chime" / "adb_present", ...)` 桩会静默失效（CODING_STANDARDS.md「桩住协作方就断言它被调到」）。

### 所有权

| 类型 | 方法 | 自有状态 |
|---|---|---|
| `AdbDownloader` | `adb_sources` / `_fetch` / `_download` / `download_state` | `dl`、`adb` |
| `Reporter` | `remember_error` / `report_payload` / `send_report` / `_install_id` | `last_error`、`report_times` |
| `Dispatcher` | `start` / `_work` / `_log` / `_event` / `poll` / `stop` / `pause` / `resume` | `job`、`lock` |
| `Api`（门面） | 其余 13 个方法（`env` / `latest_version` / `devices` / `usb_hint` / `status` / `chan_scan` / `ui_check` / `dev_off` / `restore` / `diagnostics` / `copy_text` / `open_path` / `open_url`） | `last_status`、`last_devices` |

- `adb` 归 `AdbDownloader`：只有 `_download()` 会把新路径写回来。`Api.adb` 是转发到 `downloader.adb` 的可写 property，`--smoke-gui` 的 `api.adb = None` 与测试里的赋值照旧。
- `download_adb()` 的线程入口留在门面：它只是「判 running 再起一个线程」，调用的仍是门面的 `_download`，所以 `patch.object(api, "_download")` 与改前一样有效。
- `last_error` 归 `Reporter`：它是 `remember_error()` 的唯一写者，也属于上报语义。`diagnostics()` 通过公开字段读它。
- `last_status` / `last_devices` 留门面：写者 `status()` / `devices()` 本来就在门面里，读者只有门面自己的 `diagnostics()` 与传给 `Reporter` 的参数。
- 锁随 `start()` 归 `Dispatcher`。`ui_check()` 经 `Dispatcher.busy()` 在锁内判断「有没有任务在跑」，与 `start()` 互斥的语义不变。

### 跨块传参

- `Dispatcher` 构造注入五项：`runner_of()`、`backups_of()`、`data`（`ClientData`，内部用 `pause` 路径与 `ensure()`）、`adb_of()`、`on_error(operation, serial, detail) -> recovery`。`runner_of` / `backups_of` / `adb_of` 都是取值函数：门面上的 `runner` / `backups` 允许被调用方整体替换，`adb` 会在下载后变，三处必须读同一份。它不知道 `Reporter` 与 `AdbDownloader` 的存在；`on_error` 由门面绑到 `_remember_error(...)["recovery"]`。
- `Reporter.report_payload(status, view)` 接两个参数。`view` 是门面从 `job.snapshot(0)` 与 `job.payloads` 压成的只读视图 `{"serial", "lines", "results", "payloads"}`，`Reporter` 不认识 `Job`。
- `AdbDownloader` 不认识任何块，只拿 `ClientData` 与 adb 初值。

### 门面

- 窗口桥 22 个方法名与签名逐项不变。测试与入口实际用到的私有名（`_run` / `_adb` / `_log` / `_work` / `_remember_error` / `_install_id` / `_download` / `_event` / `_child_env` / `adb_sources`）保留在门面转发。
- `Api._fetch` 的转发壳与 `Api.dl` 的 setter 删除：全仓库没有调用者，留着只会骗下一个 patch 它的人（CODING_STANDARDS.md「改不动的桩直接删掉」）。下载器内部的 `_fetch` 仍在，`dl` 只有 getter。
- `_run` / `_adb` 是门面上可被实例属性赋值覆盖的真实方法，不是 property：7 处 `api._run = Mock(...)` 与 1 处 `patch.object(api, "_adb", ...)` 靠这一点生效。
- `job` / `adb` / `last_error` 是可写 property（setter 转发给对应块），`dl` / `report_times` 是只读 property；13 个直接构造 `app.Api(dir)` 的测试文件一行不改。

### 三块不互读的守卫

- `tests/test_api_structure.py`：解析 `gui/app.py`，断言三个新类体里不出现另外两个类的名字，也不出现指向对方的属性；另断言 `Api` 的 22 个窗口桥方法名与参数列表等于从基线抄死的清单。
- `tests/compare_api.py`：同一串 `Api` 调用喂给基线 `gui/app.py` 与当前版本，比较方法签名、下载状态、上报结果、执行序列与 `job.results` 的 `rc`。调用串用 `Api(runner=…)` 注入假启动器，不 patch `subprocess`。它要 `git archive` 基线提交，CI 是浅克隆，所以**手动跑、不进单测**：`python tests/compare_api.py --baseline <SHA>`。每条场景的 `reached` 由观察值派生（走到了 stopped / skipped / link-lost / limited 等哪条分支），不是场景名。

## Considered Options

- **三块各起新文件**（否）vs **留在 `gui/app.py`**（采纳）。ADR-0003 已实测同级模块能被打包收进（`winpreflight.py`），所以不是技术障碍；但共享常量与函数太密，搬移会让 diff 变成搬家大赛，且改写 8 处模块级桩。
- **`Api` 继承 `Dispatcher`**（否）vs **组合转发**（采纳）。少一层转发，但「门面是一个调度器」语义不对，且 `__init__` 要在 `super()` 前后拼注入。
- **抽一个只读共享状态对象**（否）vs **按产生者归属 + 门面传参**（采纳）。共享对象多一个类型，且给三块留了一个可以互相读的口子；按所有权分配能逐条指认「谁写、谁读」。
- **再拆一个「设备查询」类**（否）。`devices` / `status` / `chan_scan` / `ui_check` / `dev_off` / `restore` / `usb_hint` 之间没有共同状态；`diagnostics()` 同时读 `last_status` / `last_error` / `job` / `adb`，本质是协调者，留在门面。
- **`report_payload(status, job)` 传 `Job`**（否）vs **传只读视图**（采纳）。传 `Job` 让上报块依赖调度块的状态类型，与「上报只知道要上报什么」不符。
- **只保留 22 个窗口桥名字，改测试指向新块**（否）。30+ 处测试要改，与「纯重构、用例数不变」冲突。
- **`Dispatcher` 注入 `Reporter` 对象**（否）。调度块会知道上报块存在，与票面的「三块不互读」相反。

## Consequences

- 13 个直接构造 `app.Api(dir)` 的测试文件零改动，`api.job` / `api._log` / `api._work` / `api._run` 等调用面保持原样。
- 新增两份证据：`tests/test_api_structure.py`（常驻结构守卫，进单测）与 `tests/compare_api.py`（改前改后对拍，手动跑）。对拍场景覆盖下载回退 / 校验失败 / 源表异常、上报 ok / duplicate / 429 / 空报告 / 限频、执行成功 / 失败 / 停止 / ui_busy / link_lost / 事件 / 载荷行分流；守卫走不到目标分支的场景不算证据。
- 拆类改动在一个代码 commit 里落地：三块的 `Api.__init__` 接线与门面转发互相引用，硬拆成三个提交会让中间态跑不起来。测试与文档各一个 commit。
- `#452` 的三处竞态先于本决策合入，拆类把它们原样带进 `Dispatcher`：`_log` / `_event` 收自己那一次的 `job`，spawn 登记时补杀漏网的进程，收尾行与 `running=False` 在同一临界区。`download_adb()` 的「判 running 与起线程之间」并发下载竞态是基线原有，不在这里修。
- 验收：3.15 与 3.12 各 847 项回归全过（含结构守卫 5 项）；ruff 0.17.3 净；对拍 20 条场景与 `a788fa1` 零差异、守卫全部命中。
- 本机没有 `webview`：`--smoke-gui`、打包件与真机均未验证，验收以单元回归、对拍与 ruff 为准。
- ADR-0003 里「`Api` 拆类留给跟踪票」一条在此兑现；那份 ADR 的原文不改。
