# 一次执行的状态归 Job：单写者 + 锁内快照，控制面拆开

基线 `7032e46`。

`gui/app.py` 的 `Api` 把一次执行的全部状态摊在一个裸 dict 里：`start()` 建 11 个键（`running / lines / idx / total / title / results / proc / cancel / t0 / serial / model`），`_event()` 与 `_work()` 运行中再加 `paused / step_events / recovery / pause`。写者只有工作线程 `_work`（`_log()` 经 `_event()` 也算在内），读者是 HTTP 线程上的 `poll()`；`stop()` / `pause()` / `resume()` 又是 HTTP 线程直接改字段。`Api.lock` 只用在「有没有任务在跑」的互斥里，job 的读写没有锁。7 个测试直接构造或读写这个 dict，`test_reports_026.py` 还用 `__setitem__` 改 `cancel`。

## Decision

**一次执行的状态收成 `Job` 对象；`poll` 只读它在锁内成形的不可变快照；控制面按「状态 / 动作」拆开。**

- `Api.job` 由 dict 变成 `Job | None`。`None` 保留「本次会话还没执行过」的意思，`poll()` 对 `None` 维持 `{running: False, lines: [], next: 0}`。
- `Job` 用数据类风格：字段公开；锁是 `Job.lock`，`snapshot()`、`request_*()` 与 `_work` 的状态发布点都在锁内（`runner.spawn` / `p.wait()` 期间不持锁，HTTP 线程随时能读快照、发停止）。不造一套写方法去包 `_work` 里那些赋值。
- `snapshot(since)` 在锁内一次性成形，返回 `running / lines[since:] / next / idx / total / title / results / sec / cancel / recovery / pause / paused`。`results` 交全量；执行中是否显示由 `poll()` 用同一份快照的 `running` 决定——门控是展示策略，不是状态。
- `step_events` 只给 `_work` 判定 `ui_busy` / `link_lost`，不进快照。
- 控制面：`cancel` / `pause` / `paused` 是状态，归 `Job`，分别由 `request_stop()` / `request_pause()` / `clear_pause()` 在锁内改，`request_stop()` 顺带 terminate `proc`。`proc` 与执行同生共死，留 `Job` 内部、不进快照。`data.pause` 文件是引擎侧读的信号通道，属 `Api`，不进 `Job`。
- 窗口桥方法名与签名、`/poll` 字段、前端 `tick()`、引擎子进程、退出码、事件处理都不变。

## Considered Options

- **`Job` 自带锁 + 锁内快照**（采纳）vs **一把 `Api` 级锁** vs **单写者 + 原子替换整个不可变对象**。`Api` 级锁会把与执行无关的状态（`dl` / `last_status`）也圈进来；原子替换要每次写都重建整个对象，日志增长后开销大。锁跟着状态走最内聚。
- **数据类风格**（采纳）vs **私有字段 + 一组写方法**。`_work` 里有大量就地赋值，严格封装要造十几个方法，改动面与出错面都比收状态本身大；把「一致视图」收在 `snapshot()` 一处就够了。
- **`results` 门控放 `poll()`**（采纳）vs **`snapshot()` 内部门控**。`diagnostics()` 与 `report_payload()` 执行中要读全量 `results`（点「复制完整诊断」要看到已完成步骤）；门控若进快照，会把这条路径改坏。
- **`proc` 留 `Job`**（采纳）vs **留 `Api`**。它是 `_work` spawn 出来的资源，与执行同生共死；留 `Api` 只会让 `stop()` 多拆一次 `Job`。
- **`data.pause` 留 `Api`**（采纳）vs **归 `Job`**。它是引擎侧读的文件，属客户端的信号通道，不是执行状态。
- **`dl` / `last_status` / `last_error` / `last_devices` 不进 `Job`**（采纳）。它们的生命周期跨执行，塞进来会把 `Job` 变成杂物袋，与本决策相反。

## Consequences

- `tests/fixtures.py` 的 `job_stub()` 成为「一次执行」测试状态的唯一装配点，与 `phone_stub()` 并列；7 个测试的 dict 样板迁过去，`api.job` 不留 dict 兼容面。
- `test_reports_026.py` 用 `__setitem__("cancel", True)` 模拟点停止的地方改成 `job.request_stop()`。
- 新增用例覆盖：`snapshot()` 的增量 `lines` / `next` 自洽、执行中 `results` 门控与 `diagnostics` 全量的差异、`request_stop()` 在并发下被 `snapshot()` 看到。
- `CONTEXT.md` 的「执行」段补「一次执行 / Job」「任务步骤 / Task」「快照」；「段落」的描述从「九个步骤」改成「九段」，避免与「任务步骤」混。
- 本票不做：`Api` 拆类（#390）、四个自由属性归拢、前端契约与退出码。
- 没有真机可验。验收是单元回归加 `--smoke-gui` 起得来，与 ADR-0002 / ADR-0005 / ADR-0008 同一标准。

## 补充（#452）：两条发布不变量

- **`proc` 的登记方补杀。** 只靠 `request_stop()` 杀进程会漏掉「`spawn()` 已返回、`proc` 尚未登记」这一瞬。登记 `proc` 的同一个临界区里读一次 `cancel`，已置位就由工作线程终止刚拿到的进程；不要为此把锁跨 `spawn()` / `wait()`（见 Decision）。
- **收尾行与 `running = False` 同临界区发布。** 分两次写会让轮询看到「已结束但没有收尾行」，也会给下一次执行接管留下空隙；收尾行本身也在这个临界区里按 `cancel` 取值。工作线程经 `_log(s, job)` / `_event(kind, job)` 写自己手里的那个 `Job`，不走 `Api.job`（缺省时仍回落到 `Api.job`，给不需要绑定的调用方）——旧执行的任何写入都只进旧 `Job`。
