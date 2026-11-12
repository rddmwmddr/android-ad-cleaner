# 工具层的 `gh` 只经一处会话模块

基线 `0f1f0fe`。父票 #1216，本组 #1217 / #1218 / #1219。

五个维护脚本各自起 `gh` 进程、各自判 JSON、各自报错：`claim` 与 `stale` 的默认执行器和 `gh()` 逐字相同（`followup` 的默认执行器只多传一个 `timeout`），`triage_audit` 自己 `subprocess.run` 并抛 `Unreachable`，`release_assets` 的 `run_gh()` 起进程、`json.loads` 解析却抛裸 `RuntimeError`。改一处措辞要改五遍，写第六个脚本时再抄一遍。

## Decision

**`tool/gh.py` 是工具层起 `gh` 进程的唯一一处。** 导出三个函数与一个错误类：`runner_for(cwd=None, timeout=None)` 给默认执行器（签名 `(script, *args) -> (标准输出, 错误输出, 返回码)`，与用例里的 `FakeRunner` 同形）、`call(runner, *args)` 跑一次取 `(文本, 返回码)`、`json_of(runner, *args, source=…)` 判 JSON，失败一律抛唯一的 `GhError`。改报错方式时只改这里。 <!-- rule:dev.gh.single-session -->

- **共用面到「跑命令 + 判 JSON」为止，写操作不收。** `claim` 的 `post_comment` 要评论 URL 做重读校验与撤回，`stale` 的只要失败原因，`apply_one` 还有「先加标签再评论、失败退标签」的顺序逻辑——三者形状不同，硬收成一份只会把各自的判定搬进共享模块。
- **两份同形包装搬进第三方模块，是为了断 import 环。** `claim` 已经 `from stale import STALE_LABEL`（停摆标记只此一份），所以 `stale` 不能再从 `claim` 取 `gh()`；共享会话住在两者之外，环就不存在了。
- **`timeout` 默认不设。** 只有本身有时限的那一步（`followup`）传自己的秒数：慢网络不该被同步判成失败。
- **错误措辞三档**：跑不了 gh（没装、不在 PATH 上）、退出码非零、输出不是 JSON。`call` 失败时取错误输出、为空时退回标准输出，两端都 strip；`json_of` 把后两档带上 `source`（这条命令的来源说明）。
- **三份同名 `Unreadable` 刻意不合并。** `claim` 的读不出认领记录、`followup` 的判不了末评先后、`stale` 的认不出 Markdown 结构——同名但各自说一件事，docstring 已经分别写清。共用一个类会让调用方按类型捕获时把另外两种结局一起吞掉，而那三种该给的处置完全不同。`triage_audit` 的 `Unreachable` 与这三份都不同族（它原本连「起进程」都自己写），随迁移删掉、改抛 `GhError`。

## 边界

- **发版附件对账（`tool/release_assets.py`）纳入。** 它确实起 `gh release view --json assets` 进程并解析 JSON，只是因为抛裸 `RuntimeError`、不接注入才没被发现。改后 `tool/` 里不再有第二处起 `gh` 进程的代码。
- **验证台账（`tool/verify_ledger.py`）不纳入。** 它一个外部命令都不跑，只读仓库里的文件。
- **`gui/upload_gitee.py` 不在范围。** 它在客户端目录下、跑 `gh release download` 取安装包，属于发版动作而不是工具层脚本；它不 import `tool/`，也进不了同一个注入面。

## 守卫

`tests/test_rules_guards.py` 的 `GhGuards` 扫 `tool/` 下全部 `.py`：除 `tool/gh.py` 外出现 `"gh"` / `'gh'` 字面量，或又定义一份 `def runner_for`，即红并指出文件与行号。带「`tool/gh.py` 存在」与「扫到的文件数大于零」两条空转断言。可证伪：把任意一处已迁移的脚本改回自带执行器（例如在 `stale.py` 里补一行 `subprocess.run(["gh", …])`），守卫当场报出那一行。

语义面不在守卫里，在 `tests/test_gh.py`：`call` 的两条一行语义（失败取错误输出、为空退回标准输出）与 `json_of` 的三档报错各自有用例，不再只靠调用方间接覆盖。

## mypy

`tool/gh.py` **不进**严格档：它是 I/O 适配器，生产 `runner` 而不是依赖假对象，判据与 `polarity` / `plan` 那批纯逻辑模块相反。它仍在 `tool/` 的宽松档范围内（`check_untyped_defs`）。

## Considered Options

- **并进 `tool/commits.py`**（否）。那 31 行的边界是「只读 git、不做判定」，塞进外部命令会话会把两种适配器混成一份。
- **三份 `Unreadable` 合成一个错误类**（否）。理由见 Decision 最后一条：同名不同事，合并等于让按类型捕获的调用方改变处置。
- **把写操作也收进共享面**（否）。见 Decision 第一条。

## Consequences

- `claim` / `stale` / `followup` / `triage_audit` / `release_assets` 五份脚本的本地执行器与 `gh()` 全部删除，改从 `tool/gh.py` 取；调用点统一写 `call(runner, …)`。
- 新增维护脚本一律注入 `runner`、不自己起进程；要新能力（比如 `gh api` 的某档）先看 `call` 能不能直接用。
- 注册表登记 `dev.gh.single-session`，出处指到本 ADR 的「守卫」一节；`CLAUDE.md` 不加规则行（新增的是一条工具层内部约束，不是 agent 每次开工都要读的流程）。
- `CHANGELOG.md` 的内部条目按本组票号记一条（#1219）。
