# CLAUDE.md

本仓库的操作规范写在 [AGENTS.md](AGENTS.md)。开工前读完它。

本文件只写会改变 agent 行为的指令。逐次变更记录见 [CHANGELOG.md](CHANGELOG.md)，用户看的更新说明与发版流程见 [docs/agents/release.md](docs/agents/release.md)，上报归类见 [docs/09](docs/09-社区问题处理.md)，不在这里复述。

## 开发

- 回归：`python -m unittest discover -s tests`；本机用仓库根的 `.venv/bin/python`（系统 python 缺 adbutils，会报一串 ModuleNotFoundError）。只装 `requirements.txt` 就够，不需要 pywebview / pillow。并行会话在各自的 worktree 里干活时，那个目录没有 `.venv`，用主副本 `.venv/bin/python` 的绝对路径；Read/Edit 也一律用该 worktree 的绝对路径。只跑一个文件时加 `PYTHONPATH=tests`：`PYTHONPATH=tests python -m unittest tests.test_row`（`tests/` 里的用例按顶层模块 import `fixtures`）。
- 本机 `.venv` 是 3.15，CI 是 3.12，而解释器会改写部分输出（3.13 起编译器剥掉文档字符串的公共缩进，异常 repr、argparse 帮助同理）。推送前用 CI 那一版再跑一套：`uv run --python 3.12 --with-requirements requirements.txt python -m unittest discover -s tests`（首次装环境约 30 秒）。
- 数基线总数用干净副本：先 `git rev-parse origin/main` 记下 `<sha>`，再 `git archive <sha> | tar -x -C /tmp/x`，在 `/tmp/x` 里跑同一套。主副本里可能躺着别的会话没提交的用例。
- 改动面与审查对比用分支基点的固定 SHA（`git merge-base HEAD origin/main` 的结果，`git diff <sha>`），不用 `origin/main` 尖端——并行会话会推进它。
- 主副本的当前分支随时被别的会话切走（`main` 只是其中一种状态），所以切分支、丢弃改动（`git checkout --`、`restore`、`reset`、`stash`）都在 `git worktree add` 出来的目录里做；主副本只做合并与只读操作。
- 推送前再 `git fetch origin main` 并 rebase：并行会话会在开工到推送之间推进 main，基于旧 SHA 推送会让 PR 直接 `CONFLICTING`，CI 也不触发。
- CI：`.github/workflows/test.yml` 在 PR 和 main 推送时自动跑同一套，Linux（`unittest`）与 Windows（`unittest-windows`）各一个 job；两边 skip 的用例不一样，判断覆盖时看 `-v` 输出里的 skipped 行，别假设两边跑的是同一批。`build-windows.yml` 只在 `v*` 标签或手动触发时打包，不守 PR。
- 静态检查：`uvx ruff@0.17.3 check --select F,E9 tool tests gui`，本地与 CI 同一个版本（CI 就钉 0.17.3，`.venv` 里没有 ruff）。不查 `recipes/`——机型脚本靠注入作用域执行，静态分析看到的全是未定义名；也不开格式与行长规则。
- CHANGELOG 一条一行、≤ 80 字，落在 `## 未发布` 的 `### 新增` / `### 修复` / `### 内部` 之一，结尾挂一个编号（有 PR 挂 PR 号，只有 issue 的挂 issue 号；内部重构再加 ADR 号）。内部条目允许点一个符号名，但不展开机制；测试数、基线 SHA、对拍组数一律不写——那些在 PR 描述与 ADR 里。`## 未发布` 期间不写验证行，发版时才补。rebase 后先 `git rebase --continue` 把提交落完、再跑回归与对拍，并确认 `## 未发布` 没有被已发版的小节吸收（main 刚发过版时要重新开出来）。
- 审查标准：见 [CODING_STANDARDS.md](CODING_STANDARDS.md)，只放判断项；机械规则交给 CI。
- 社区问题的归类与真机缺口见 [docs/09](docs/09-社区问题处理.md)：那里只记 GitHub 上看不到的判据与缺口，逐条回复与 issue 编号留在 issue 里。
- 找「命令怎么分派、退出码怎么定」先看 [tool/run.py](tool/run.py) 的 `dispatch()` 与 `COMMANDS`：一条命令一个 `cmd_*(serial, rest) -> int`，`sys.exit` 只在 `__main__` 一处；退出码语义见 [ADR-0005](docs/adr/0005-run-command-handlers.md)。
- 找「开关所属的行」先看 [tool/row.py](tool/row.py)：`line` 结构定界、`own` 多开关容器收窄、`title_of` 平铺列表按竖直距离分带；`fast.py` 与 `chan_fast.py` 消费它，不要另写一份。
- 找「这一页该拨哪些开关」先看 [tool/fast.py](tool/fast.py) 的 `plan_switches()` 与 `SwitchPlan`：目标选择、屏带过滤、`checked` / `kept` 只在那里定义；`off()` 只做点击 → 回读 → 重试 → 报告。
- 找「等页面认得出」先看 [tool/wait.py](tool/wait.py)：`settle` / `setting` / `ChannelPage.refresh` / `off` 都消费 `until()`，不要另写轮询循环。
- 找「怎么走到渠道页、认出哪一行的开关」先看 [tool/chan_fast.py](tool/chan_fast.py) 的 `ChannelPage.open()`：直达 / 转应用通知页 / 内联行 / 同名放弃四类只在那里定义（[ADR-0007](docs/adr/0007-channel-page.md)）；`channel_switch` / `inline_switch` / `wait_page` / `via_app_page` 是一行前向壳，不要往里加逻辑。
- 找「引擎报给客户端的状态」先看 [tool/events.py](tool/events.py)：五个 kind 与事件行格式只在那里定义（[ADR-0004](docs/adr/0004-engine-state-events.md)），引擎侧 `emit()`、`gui/app.py` 的 `_log()` 都走它；不要再按中文文案判断状态。
- 找「渠道怎么判营销 / 服务 / 受保护」先看 [tool/channel_policy.py](tool/channel_policy.py) 的 `classify()`：营销候选、扫描排除、默认不勾、受保护、厂商营销 ID、广告网络 ID 六组判定只在那里定义（[ADR-0006](docs/adr/0006-channel-classification.md)）；`chan_fast` 的扫描分支与 `gui/app.py` 的 `chan_scan()` 都消费它，不要另写词表。
- 改「一行输出怎么进界面」先看两处：`gui/app.py` 的 `_log()` 决定它进 `Job.lines` 还是只当事件；[gui/web/index.html](gui/web/index.html) 的 `summarize()` 在认不出模式时直接显示 `results[].tail` 末行——`tail` 是第二个落点，机器行不能进。
- 造不连手机的 `Phone` 用 [tests/fixtures.py](tests/fixtures.py) 的 `phone_stub()`（`fake_phone()` 就是它加一条时间轴），装配只此一处。纯重构要给对拍证据时，同一文件还有 `all_pages()` 取 `tests/` 里的页面样本、`Clock` 假时钟、`Timeline` + `Device` 按时间轴换页。
- 改「认渠道页」这类读屏逻辑要做改前改后对拍时，驱动器是 [tests/compare_chan_pages.py](tests/compare_chan_pages.py)：认页 / 进页 / 编排三层 × 两种屏尺寸，同一份探针分别跑冻结基线与当前 `tool/`，守卫数字非零才算测到。
- 找「读屏 adapter」先看 [tool/reader.py](tool/reader.py)：`Phone.reader` 是手机读屏库或假设备的统一接口，`Phone.d` 是它的历史别名（机型脚本与测试用），新增读屏能力先加进 `Reader`。
- adb 固定 platform-tools 37.0.1（`gui/app.py` 的 `ADB_PINNED`）；升级时改那张表，校验值按 Google `repository2-3.xml` 的 SHA-1 核对。
- 客户端数据路径看 `gui/app.py` 的 `ClientData`，备份目录看 [tool/backups.py](tool/backups.py) 的 `Backups`（root 由调用方给），工具模块用 `_tool()` 惰性取。
- 找「Windows 启动失败是缺 WebView2 还是被 MOTW 拦」先看 [gui/winpreflight.py](gui/winpreflight.py)：注册表三态与两个关键 dll 的 `Zone.Identifier` 判定只在那里定义（[ADR-0003](docs/adr/0003-desktop-client-import-and-dependencies.md)）；`gui/app.py` 的 `startup_advice()` 只按结论选文案。

## 错误日志上报

- 用户说明见 [docs/12](docs/12-错误日志上报.md)。服务器、数据库、部署与运维信息只记在本机 `CLAUDE.local.md` 和 `.private/`，不进仓库。

## 发版

- 完整流程与 Release 正文的写法见 [docs/agents/release.md](docs/agents/release.md)：正文是用户看的唯一权威，repo 里不留副本，`README.md` 的首段从它复制。
- 新版本提示读官网的 `android-ad-cleaner-latest.json`，发版后要更新它（步骤记在本机 `CLAUDE.local.md`）。
- 官网另有一份放在机主的服务器上，发版后同步，方法记在本机 `CLAUDE.local.md`。
- 网盘：`gui/upload_baidu.sh [版本]` 从公开的 GitHub Release 下载安装包并核对 SHA256，经本机已登录的 BaiduPCS-Go 上传，生成分享链接写进 index.html 后提交推送。网盘账号凭证不进仓库和对话。
- 发完版按 [docs/agents/release-followup.md](docs/agents/release-followup.md) 把 `waiting-for-verify` 的 issue 逐条发给报告者复测。新版不送到报告者手上，这些 issue 永远关不掉。

## Agent skills

### Issue tracker

GitHub Issues（`gh` CLI）。**开工前先有票**：任何实现 / 重构 / 文档改造先开 issue，分支名带 issue 号。见 `docs/agents/issue-tracker.md`。

### Triage labels

默认五个角色标签，标签名即角色名，另加本仓库的 `waiting-for-verify`（已修、等真机复测）。见 `docs/agents/triage-labels.md`。

### Release followup

发版后要催哪些复测、报告者确认前不关闭哪些 issue，见 `docs/agents/release-followup.md`。每次发版都要过一遍这张清单。

### Code review

派审查的方法与规则见 `docs/agents/code-review.md`：基线钉 SHA、评审期间不改工作区、默认三轴。

### Domain docs

single-context：根目录 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。`CONTEXT.md` 只放术语表（命令 / 脚本 / 执行 / 连接 / 事件 / 等待 / 通知 / issue 状态 / 文档九组定义）；模块边界的决定写进 `docs/adr/`（现有 `0001` 手机连接、`0002` Phone 状态、`0003` 客户端 import 与依赖、`0004` 引擎状态事件、`0005` 命令与退出码、`0006` 渠道判定、`0007` 渠道到达、`0008` 拨动计划、`0009` 引擎载荷通道、`0010` 执行状态），架构描述仍不写，等主流程整体重构。
