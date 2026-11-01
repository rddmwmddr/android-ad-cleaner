# 命令是 handler，退出码只有一个出口

`tool/run.py` 的 `main()` 把四件事放在一个函数里：读 `sys.argv`、按命令名分派、执行业务、决定退出码。命令之间没有 interface——想跑一条命令，只能把整个脚本当一个进程启动。

基线 `e319126` 的事实：

- `main()` 里 `devices` 是一处特例（唯一不带 `-s` 的命令），之后 12 个 `elif` 分支（`chan-off` / `chan-on` 共用一个），末尾一个 `else: print(__doc__)`。
- 全文 18 处 `sys.exit`：`adb_bin()` 一处（`ADB = adb_bin()` 让它在 **import 期**就可能退出）、`adb_shell()` 一处（传输 helper 自己终止进程）、`main()` 的格式错一处，其余 15 处散在 12 个分支里——7 处 `sys.exit("文案")`、4 处 `sys.exit(1)`、4 处把子进程的码原样转发。
- 命令的测试面不是靠 `main()` 撑着，是靠 102 处 `patch.object(run, "<模块级名字>")`（`sh` 23、`sh_all` 11、`latest_backup` 11、`suspended` 10、`info` 8，其余零散）。13 处直接调 `run.main()`，其中 4 处用 `assertRaises(SystemExit)` 断言失败路径。
- 仓库里已经有两种写法：`huawei_channels.main(argv=None) -> int` 配 `raise SystemExit(main())`；`chan_fast.main()` 把 `DeviceLost` / `RuntimeError` 统一渲染成 `sys.exit(f"✗ {e}")`。`run.adb_shell()` 渲染的是 `str(e)`，**不带 `✗`**——两条引擎的渲染本来就不同，收口时各保各的。
- ADR-0004 已经把这一片留给本票：「退出码语义是候选 2（`run.py` handler 表）的主题」。

## Decision

**handler 的签名与落点。** 每条命令一个 `cmd_<名字>(serial, rest) -> int`，留在 `tool/run.py`，由模块级 `COMMANDS = {"check": cmd_check, ...}` 映射。`main(argv=None) -> int` 只做解析、分派、渲染。

不引入 `Device`：`sh(serial, cmd)` / `sh_all(...)` 保持模块级、每次现连一个 `Connection`。理由是 `Connection.__init__` 只存字段、不建进程，「一条命令共用一条连接」在今天没有任何可观察差异——它唯一的自有状态 `lost` 活不过一次进程退出。而注入 `Device` 要同时改 18 个自由函数的签名（`info` / `quickapps` / `msa_net` / `suspended` / `installed` / `pkg_list` / `prop` / `locked` / `wait_unlocked` / `input_blocked` / `record` / `latest_backup` / `fold_open` / `set_quickapp_service` / `quickapp_switch` / `quickapp_setting_backup` / `sh` / `sh_all`）和 102 处 patch 落点。那是「一条命令共用连接」的票，不是这张。

**退出码与错误渲染只有一个出口。**

- handler 内不再出现 `sys.exit`；成功返回 0，失败返回非 0。
- `fail(msg, code=1)` 是唯一产生「自述型」错误文案的地方：`print(msg, file=sys.stderr)` 后返回 `code`。
- 四处 `sys.exit(1)`（`suspend` / `unsuspend` / `quickapp off` / `quickapp on`）不经 `fail()`：逐条结果已经打印到 stdout，失败时直接 `return 1`。
- 转发码逐值保留：`ui-check`、`recipe`、`chan-off` / `chan-on`、`chan-scan` 的返回值就是子进程的退出码，不归一化。
- `if __name__ == "__main__": raise SystemExit(main())` 是全文唯一一处 `SystemExit`。

**`adb_shell()` 改抛。** `DeviceLost` 不再在 helper 里转成退出码，而是向上到唯一出口，由那里渲染成「`str(e)` 进 stderr、码 1」。`DeviceLost` 构造即发 `link_lost`（ADR-0004），搬动渲染点不影响事件。

**`ADB` 惰性化。** 删掉模块级 `ADB = adb_bin()`，改惰性 `adb()`；找不到 adb 时抛专用 `NoAdb`，由出口渲染 `adb_link.NO_ADB` 与码 1。不写宽泛的 `except RuntimeError`——那会把今天会打 traceback 的意外 `RuntimeError` 也悄悄变成人话。

**表的成员。** `devices` 留在 `-s` 解析之前的专处分派（它是唯一不需要序列号的命令，塞进 `handler(serial, rest)` 只能靠 `serial=None` 的魔法值）；`ui-check` 进表（`return py("fast.py", "-s", serial, "check")`）；`quickapp` 的 `check` / `off` / `on` 仍是同一个 handler 内部的再分派。

## Considered Options

- **handler 留在 `tool/run.py`**（采纳）vs **搬进 `tool/commands.py`**（否）vs **引入 `Device` 注入**（否，另一张票）。搬运的唯一好处是文件变短，代价是 102 处 patch 全部失效——它们 patch 的是 `run.sh` 这个名字，handler 换模块后就查不到。
- **`fail()` 打印后返回 int**（采纳）vs **`CommandError` 异常由 `main()` 渲染**（否：handler 直接返回退出码这件事，在失败路径上就不成立了，测试拿到的是异常）vs **归一化 0/1**（否，违反逐值不变）。
- **`adb_shell` 改抛**（采纳）vs **保留 `sys.exit`**（否：「handler 返回退出码」在最主要的失败路径上不成立）。
- **`adb()` 惰性 + 专用异常**（采纳）vs **`ADB` 返回 `None` 让 `Connection` 自己报**（否：那条路径今天会打 traceback）vs **不动**（否：import 期退出就没法在进程内调用）。
- **一轮做完 12 条**（采纳）vs **机制 + `ui-check` 先落一批**。机制四件套（表、签名、出口渲染、`adb_shell` 改抛）不可分割：任何会调 `sh()` 的命令都可能撞上 `DeviceLost`，只要 `adb_shell` 还在 `sys.exit`，接口在最主要的失败路径上就不成立。分批只会制造「表与 `elif` 并存」的双轨中间态，评审成本不降。
- **子进程对拍 + 基线 fixture**（采纳）vs **把旧 `main()` 逐字抄进测试**（否：280 行永不执行的死代码；仓库先例只抄过几十行的函数）vs **只断新 handler 的返回值与文案**（否：证明的是「符合我写的期望」，不是「等于旧代码」）。

## Consequences

- **外部行为逐字逐值不变**，两处例外或需要解释：
  - `sys.exit("文案")` 的等价性只在**进程级**成立。字符串形式的 `SystemExit` 由解释器在进程退出时打到 stderr，`fail()` 是立即打印。真实 CLI 运行两者不可区分；但**进程内调 `main()` 时**，今天不产生 stderr，改后会。现有用例里有几处只重定向了 stdout，会开始看到这些文案。
  - 没有 adb 时，`python3 tool/run.py -h` 与无参数不再被 import 期拦下（旧实现连帮助都看不到）。`devices` 与参数写错的路径仍先报 `NO_ADB`——`dispatch()` 里 `adb()` 排在 `-s` 格式校验之前，就是为了保住这个先后。
- **改抛 `DeviceLost` 会掉进两处旧代码看不见的陷阱**，两处都已在实现里封住、并有「去掉就红」的用例：
  - `quickapp off` / `on` 里 `set_quickapp_service()` 外面是 `except (RuntimeError, OSError, ValueError)`。旧实现断线走 `SystemExit`（不是 `RuntimeError`），永远进不了这个 except；改抛之后它会被当成「某个组件关闭失败」，`off` 甚至可能返回 0——正是 #293 反对的「把断线报成 App 层的失败」。两处 `except` 之前各加一条 `except (adb_link.DeviceLost, NoAdb): raise`。
  - `cmd_recipe` 的 `finally` 里恢复插电常亮。`sys.exit("文案")` 是挂起异常、等 `finally` 跑完才由解释器打印，而 `return fail(...)` 是当场打印：锁屏超时 + 恢复那一步又断线时，新写法会多打一行。改成先算 `message` / `rc`、`finally` 之后再渲染。
  - 同一个原因下，`tool/huawei_channels.py` 的 `from run import latest_backup` 也会收到 `DeviceLost`（它本来就在自己的 except 元组里）。旧实现里那是 `SystemExit`，会穿过元组直接结束进程、只有排查说明进 stderr；现在给它单列一条 `except adb_link.DeviceLost`，逐字保持那个出口。
- **测试面**：
  - 13 处 `run.main()` 调用点里，4 处 `assertRaises(SystemExit)` 改成 `assertEqual(run.main(), N)`（仍走 `patch.object(sys, "argv")`，没有改成显式传 argv）；`test_issue_regressions.py` 那处断言 `code` 是文案的（`读不到包列表`）改为断言码 1 + 文案在 stderr。另有两处连带改动：`test_community_1027.py` 直接测 `run.sh` 抛 `SystemExit`，改为抛 `DeviceLost`；`test_scan_startup.py` 拿 `run.ADB` 当期望的 adb 路径，改为固定值。
  - `tests/test_adb_link.py::test_run_adb_shell` 与 `test_chan_shell_phone` 的对拍：`drive()` 比较前先把两边都过一遍 `as_exit()`，把「新侧抛 `DeviceLost`」与「旧侧 `sys.exit(同一句文案)`」视为同一种结果。逐字节的退出码与 stderr 由子进程对拍兜住，两边各管一段。
  - 对拍基线：`tests/baselines/run_cli.json`，由 `git archive e319126` 的干净副本对着假 adb 可执行文件跑出，29 组——落在 10 条命令上共 28 组（`devices` 2、`check` 2、`backup` 3、`recipe` 1、`suspend` 4、`unsuspend` 3、`quickapp` 6、`finish` 2、`status-json` 2、`dev-off` 3），另加参数格式错 1 组；逐字节比对 `rc` / stdout / stderr，每组配守卫断言（假 adb 收到的 argv 序列，或「一条都没发」）。`recipe` 只覆盖到「没有机型脚本」这条失败路径，成功路径会起 `fast.py`。`ui-check` / `chan-scan` / `chan-off` / `chan-on` 会真起子进程、输出取决于本机 adb 服务，不进基线，改由进程内替身化断言转发码与子命令参数。
  - 用法说明（`print(__doc__)`）也不进基线：Python 3.13 起编译器会去掉文档字符串的公共缩进，3.12 不会，同一份源码在两版解释器下逐字不同（CI 跑 3.12，本轮开发机是 3.15，第一版基线因此只在 CI 上红）。改在进程内断言输出与 `run.__doc__` 逐字相等。
  - 覆盖盲区（本票已知）：基线里没有「先成功后中途断线」，也没有 vivo 的 `method == "setting"` 路径——上面两条陷阱是这样漏掉的，靠的是评审与新增的进程内用例，不是对拍。
- **范围**：只动 `tool/run.py` 与新增测试。`recipes/` 冻结；命令行参数与 GUI 的调用方式（`gui/app.py` 的 `_work` / `Task` / `_run`）一律不改。`status-json` 的 `print(json.dumps(...))` 一行不动，GUI 仍然解析末行。
- **未验证**：没有 Windows、没有打包环境、没有真机。`raise SystemExit(main())` 这条依据是 `run.py` 本来就直调 `main()`，打包壳只换入口路径；验证范围是本机单测与子进程对拍。
- CHANGELOG 的「## 未发布」一条加在实现那一笔，本 ADR 只落决策。
