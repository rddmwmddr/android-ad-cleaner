# 引擎发事件，客户端不再嗅探人话

客户端要跟着引擎走的有五件事：暂停了、继续了、手机锁着等人解锁、读屏服务被占用、手机已断开。这五件今天全靠 `gui/app.py` 匹配另一个进程打印的中文句子（行号按改前的 `f46cd97`）：`:605` `startswith("⏸ 已暂停")`、`:608` `in "手机锁屏了：请解锁手机"`、`:610` `startswith("▶ 继续执行")`、`:664` `in ("UIAUTOMATION_BUSY", "DeviceBusyError", "正在使用这台手机的读屏服务")`、`:665` `in "adb 连接断开了"`。

生产端比消费端还散：`tool/fast.py:51` 与 `:54`（暂停点的人话）、`:301` 锁屏等待、`tool/run.py:211`（同一句锁屏文案的第二个写处）、`tool/run.py:87` 把 `DeviceLost` 的 `HINT`（`tool/adb_link.py:20`）经 `sys.exit` 打到 stderr、`tool/fast.py:98` 的 `RuntimeError("UIAUTOMATION_BUSY：…")`、`tool/ui_session.py:48` 的 `DeviceBusyError`。同一个「读屏被占用」有三种写法，客户端只能三个串都试。

后果已经出现：改一句文案会静默破坏暂停、提示音和跳过逻辑，编译期和测试都看不出来；词表渗进了测试面——`tests/test_reports_1029.py:213-215` 与 `tests/test_reports_026.py:443-446` 直接把中文串当输入喂给 `_log`。同一片里还有一处不靠文本的私人约定：`gui/app.py:630` 用 argv 形状猜「这一步要不要用读屏」（`len(args) > 2 and args[2] == "recipe"`），`:591` / `:638-646` 用 `@channels` 字符串当哨兵。

硬约束有四条：CLI 与上报日志的人话文本逐字不变；打包版 `--cli`、Windows `_fix_stdio`、`bufsize=1` 下事件行必须可靠可解析；遵守 ADR-0003（客户端 import 无副作用、依赖注入）；本轮只覆盖已被嗅探的这一片，不顺手重写全部输出。

## Decision

**载体是 stdout 上的一行前缀标记，靠环境变量开关。**

- 事件行格式：`#aac:event {"kind": "paused"}`，一行、`print(..., flush=True)`。
- 只有客户端设了 `AAC_EVENTS` 才发。设置点是 `_work()` 启动子进程时传的 `env_extra`（那里已经在传 `AAC_PAUSE_FILE`），走 `Runner.run` 的那些调用（`_run()` 消费的 `ui_check` / `restore` / `dev_off`）不设；`child_env()` 还会把继承来的同名变量删掉，用户 shell 里碰巧导出也进不来。
- 客户端 `Api._log()` 是唯一消费者：行首命中前缀就**先剥掉再解析**——无论解析成功与否都不进 `job["lines"]`，于是界面、`diagnostics()`、`report_payload()`、`last-error.txt` 里都不会出现机器行。
- 引擎那五句人话照旧无条件打印，事件是紧邻的额外一行；客户端不依赖两者的先后。
- 前缀 `#aac:event ` 与现有行首字符不冲突：现有行以空格、`▶`、`✗`、`==`、`·`、`!` 或中文开头。

**词汇表只有五个 kind，本轮 payload 只有 `kind`。**

| kind | 发送点 | 含义 |
|---|---|---|
| `paused` | `fast.pause_point()` 开始等待 | 引擎停在暂停点，等人操作手机 |
| `resumed` | `fast.pause_point()` 放行 | 暂停点放行 |
| `locked` | `fast.Phone.wait_unlocked()` 与 `run.wait_unlocked()` 开始等解锁——两处各有一份实现，都要发 | 手机锁着，等机主解锁 |
| `ui_busy` | `fast.Phone.__init__`（读屏服务已被注册）与 `ui_session.DeviceLock`（本机另一个任务占着）两个抛出处 | 读屏服务被占用，这一步没法点 |
| `link_lost` | `DeviceLost` 的构造处（`adb_link.lost()` / `check_alive()` / `lost_from()`） | adb 连接已确认断开 |

不含步骤开始/结束，也不含退出码：步骤边界是客户端自己排的，退出码是它 `p.wait()` 的返回值，加进协议等于把可推导的信息再固化一份；退出码语义是候选 2（`run.py` handler 表）的主题。

**发送点跟着语义走，不跟着退出路径走。** `locked` 有两处实现（`run.wait_unlocked` 与 `Phone.wait_unlocked`，两份几乎重复的代码，本轮不合并），两处都要发；`ui_busy` 同样有两个抛出处。`link_lost` 则是三条退出路径（`run.py` 的 `adb_shell`、`chan_fast.py` 的 `main`）共用一个发送点——收在 `DeviceLost` 的构造上，构造即代表已确认断线，谁把它转成退出码都不影响事件。`AAC_EVENTS` 未设时不发，测试里构造 `DeviceLost` 也不会多出一行。

**客户端把「这一步发生过什么」记成事件集合，不再查文本。**

`_log()` 把事件记进当前步骤的集合，并按 kind 施加即时副作用（`paused` / `resumed` 改 `job["paused"]`，`paused` / `locked` 响铃）。因为事件已经从 `lines` 里剥掉，`detail` 不再含事件文本，所以 `_work()` 的两处判定改成查集合：`ui_busy in step_events`、`link_lost in step_events`。客户端自己打印的暂停 / 继续行直接置状态并响铃，不再经过嗅探。

**任务从裸元组变成描述符。**

`Task(title, script, args=(), uses_ui=False, channels=None)` 取代 `@channels` 哨兵与 argv 形状猜测：`channels` 非 None 时 `_work()` 在运行前写 `channels.tsv`（原来 `@channels` 那段原样搬进去），`uses_ui` 由 `start()` 排任务时显式给出。不动 `run.py` 的命令表与任何命令行参数；测试里的裸元组按新类型改掉，不留兼容垫片。

**不做文本兜底。** 客户端与引擎同包同版发布，不存在新客户端配旧引擎。规则只有两条：命中前缀就剥；解析失败当没有这个事件。于是「事件缺失」等价于「这条人话不改变任何状态」，与今天未命中时一致。

## Considered Options

- **stdout 前缀行**（采纳）vs **旁路文件**（否）vs **无条件输出 JSON 行**（否）。旁路文件的否决理由：事件与 stdout 行的先后顺序无法保证；每一步是一个新进程，还要把多个进程的追加流合起来；`ClientData` 里得新增一条派生路径，正是 ADR-0003 处理过的那类散落。无门控 JSON 行的否决理由：CLI 输出会多出机器行，直接违反「人话逐字不变」。
- **收 5 个 kind**（采纳）vs **只收报告图上的 4 个**（否）。`ui_busy` 与其余四个同属「拿另一个进程的中文句子当协议」，而且它的消费者正是 `needs_ui` 那套 argv 猜测；只做 4 个会让新旧两套并存。
- **payload 只有 `kind`**（采纳）vs **现在就把 `timeout` / `serial` / 占用来源带上**。客户端对这五件事的反应不依赖任何附加字段（`serial` 它自己知道，`timeout` 已经在人话里，占用来源的处理完全相同）。需要字段时再加，两侧同版发布。
- **先剥前缀再解析**（采纳）vs **解析成功才剥**。后者会让解析失败的事件行漏进 `lines`，进而进上报日志。
- **`link_lost` 后保留 `adb_present()` 存活确认**（采纳）vs **有事件就删**。它不再是文本防误报，而是一次独立的存活查询：引擎报断开、手机恰好又回连时，后续步骤照旧继续跑。行为与今天一致。
- **Task 描述符同票做**（采纳）vs **留下一票**。`ui_busy` 的服务对象就是它；留着 argv 猜测，等于新协议旁边还挂着一份私人约定。

## Consequences

- **行为变化一**：`adb_link.REPEAT`（「手机和电脑的 adb 连接已断开，本段跳过…」）也会发 `link_lost`。今天它不含「断开了」，不触发抑制；改成事件后，同一任务里后续步骤会被跳过。REPEAT 本就代表「已确认断线」，今天漏判是文案差异造成的 bug。
- **行为变化二**：`UIAUTOMATION_BUSY` 这类串出现在与读屏占用无关的报错里时，不再误判为占用——事件只在真正抛出的地方发。
- **行为变化三**：在步骤边界暂停期间点「停止」，客户端把 `paused` 复位；旧实现要等下一行「▶ 继续执行」才复位，停止后 `poll()` 会一直报「已暂停」。
- 事件不进 `lines`，所以上报日志、诊断文本、`last-error.txt` 的人话逐字不变。它也不进步骤摘要用的 `tail`：前端 `summarize()` 在认不出模式时会直接显示 tail 最后一行。
- `tool/events.py` 是词表唯一定义（纯 stdlib，import 期不读环境、不建目录）：`emit(kind)` / `is_event(line)` / `parse(line)`。引擎侧裸 `import events`，客户端用既有的 `_tool("events")` 惰性取。`bundle_data` 按 `tool/*.py` 收，打包清单不用改。
- 测试面：两处喂中文串的用例改为喂事件行；「人话不变」用两个守卫——五个发送点各设 / 不设 `AAC_EVENTS` 跑一遍，去掉事件行后逐字对拍（`DeviceLost` 与两处占用比的是异常文案）；三条打印行（暂停、继续、锁屏）另写字面量断言，两条异常文案由既有用例盯着短语。
- 没有 Windows、没有打包环境、没有真机：`--cli` 与 `_fix_stdio` 这条依据是「`print(flush=True)` 一行一次」加上已有的 `line_buffering` / `write_through` / `PYTHONUNBUFFERED=1`，**未在打包件上验证**；验证范围是本机单测。
- CHANGELOG 的「未发布」一条加在实现那一笔，本 ADR 只落决策。
