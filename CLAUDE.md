# CLAUDE.md

本仓库的维护规范就是本文件：开工前读完，判断标准在 `CODING_STANDARDS.md`。`AGENTS.md` 是交付给用户侧执行 agent 的手机操作手册，不是维护规范（[ADR-0028](docs/adr/0028-agent-audience-boundary.md)）；改引擎行为时，它的 §1 就是这条改动的边界，先读一遍。

本文件只写会改变 agent 行为的指令。逐次变更记录见 `CHANGELOG.md`，用户看的更新说明与发版流程见 `docs/agents/release.md`，上报归类见 [docs/09](docs/09-社区问题处理.md)。

## 开发

改 `tool/` / `gui/` / `android/` / `recipe_lib/` 里某个模块之前，先看 `docs/ARCHITECTURE.md` 的「函数级细节」一节：哪个函数管什么、哪些不许另写一份都在那里。**这一行指针不可删**（[ADR-0039](docs/adr/0039-claude-md-startup-index.md)）。

- 找「某条维护规则有没有守卫」先看 `docs/agents/rules.toml`：规则正文留在文档里，注册表每条给 `id` / `source` / `check` / `status` / `why` / `expires_if`（可选 `since`），正文对应行的行尾挂 `<!-- rule:<id> -->` 锚点。新增或删除规则时两处一起改，`tests/test_rules_registry.py` 守双向一致，没挂锚点的新条目由 `tests/test_rules_guards.py` 按文档冻结上限挡；规则的理由只写在注册表的 `why` 里，正文不复述理由——判断与反例仍留在正文。 <!-- rule:doc.rules.registry-indexes-prose -->
- 回归：`python -m unittest discover -s tests`；本机用仓库根的 `.venv/bin/python`（系统 python 缺 adbutils，会报一串 ModuleNotFoundError）。只装 `requirements.txt` 就够，不需要 pywebview / pillow。并行会话在各自的 worktree 里干活时，那个目录没有 `.venv`，用主副本 `.venv/bin/python` 的绝对路径；Read/Edit 也一律用该 worktree 的绝对路径；`node_modules` 同样没有，跑之前先 `npm ci`（热缓存亚秒级），缺 jsdom 时 `test_web_client` 要等整轮跑完才红。只跑一个文件时加 `PYTHONPATH=tests`：`PYTHONPATH=tests python -m unittest tests.test_row`（`tests/` 里的用例按顶层模块 import `fixtures`）。 <!-- rule:dev.tests.regression-command -->
- 用例只在 `tests/` 下定义：`recipes/`、`gui/` 里的脚本不进收集，别处写 `def test_` 也不会被 `discover -s tests` 跑到。`tests/test_test_collection.py` 扫全仓 `.py`（跳过隐藏目录与 `node_modules` / `build`），`tests/` 之外命中即汇总成一条失败，逐文件列出命中数。 <!-- rule:dev.tests.cases-live-under-tests -->
- 新用例往哪儿放：`tests/` 的每个测试文件要么是已声明的锚点，要么按 `recipes/` 的脚本名命名（机型脚本的专用测试）。锚点表在 `docs/agents/test-anchors.md`，守卫是 `tool/test_anchors.py` 的 `violations()`（`tests/test_test_collection.py` 代跑，本地 `python3 tool/test_anchors.py`）；报红文案按文件名给出相近的锚点，确需新开锚点时两处同时登记并写 why。 <!-- rule:dev.tests.anchor-registry -->
- 本机 `.venv` 是 3.13（仓库根的 `.python-version` 钉着这一版），与 CI 的 Linux job 同一版，上面那条回归命令就是本机口径，不必再用别的解释器跑一遍；重建时照 `.python-version` 走，别升到更新的版本。3.12 只剩 Windows job 与发版打包在跑，而那两边会 skip 掉 POSIX-only 的一批用例（包括 CLI 逐字节对拍），macOS 打包不跑回归，别假设两版逐字相同。 <!-- rule:dev.tests.interpreter-version -->
- 改动面与审查对比用分支基点的固定 SHA：取法、worktree 路径与重取时机见 `docs/agents/code-review.md` 的「基线钉 SHA」。
- 主副本的当前分支随时被别的会话切走（`main` 只是其中一种状态），所以切分支、丢弃改动（`git checkout --`、`restore`、`reset`、`stash`）都在 `git worktree add` 出来的目录里做；主副本只做合并与只读操作。 <!-- rule:dev.workspace.worktree-only -->
- 推送前再 `git fetch origin main` 并 rebase：并行会话会在开工到推送之间推进 main，基于旧 SHA 推送会让 PR 直接 `CONFLICTING`，CI 也不触发。 <!-- rule:dev.git.rebase-before-push -->
- CI：`.github/workflows/test.yml` 在 PR 和 main 推送时自动跑同一套，回归 job 在 Linux 与 Windows 各一个、两版解释器各跑一次；两边 skip 的用例不一样（Windows 侧 skip 掉 POSIX-only 那批，含 CLI 逐字节对拍），判断覆盖时看 `-v` 输出里的 skipped 行，别假设两边跑的是同一批。`build-windows.yml` 只在手动触发时按指定 tag 打包（不守 PR，也不由推 tag 自动跑）。 <!-- rule:dev.ci.two-interpreters -->
- 提交必须带 DCO signoff：`git commit -s`，签署邮箱与作者邮箱一致。CI 的 `dco` job 用 `tool/check_dco.py` 查 PR 上 `base..head` 里的非 merge 提交（merge 提交是网页 / API 合并的已知例外），本地跑同一条命令可复现；它只让问题可见，要拦在合并前须分支保护 + required status checks。 <!-- rule:dev.git.dco-signoff -->
- 提交信息主题用 Conventional Commits：`type(scope): subject`，`type` 只取 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`ci`、`perf`、`build`、`style`、`revert` 之一（单一来源是 `tool/check_conventional.py` 的 `TYPES`），`scope` 只允许 `[a-z0-9_-]`，破坏性改动在冒号前加 `!`。CI 的 `conventional` job 在 PR 上查 `base..head` 里的非 merge 提交，本地跑 `python3 tool/check_conventional.py origin/main..HEAD` 可复现；同 `dco` 一样只让问题可见，不阻断合并。 <!-- rule:dev.git.conventional-commits -->
- 票号也进 CI：`ticket-checks.yml` 的 `ticket-ref` 核分支名以 `-<票号>` 结尾、PR 正文有 `Refs #N` / `Closes #N` 且是同一张，`comment-tickets` 核新增行里的票号在 PR 引用的范围内（`docs/adr/` 与含「沿用」的行豁免）；同 `dco` / `conventional`，只让问题可见，要拦在合并前须分支保护 + required status checks。两条规则本身见 `docs/agents/issue-tracker.md` 与 `CODING_STANDARDS.md`。
- 依赖安全靠两个 workflow：PR 上 `dependency-review` 只比对本次引入 / 变更的依赖（`fail-on-severity: high`；`fail-on-scopes: runtime` 让 devDependency 变化不阻塞），存量由 `dependency-audit` 每周一跑 `pip-audit -r requirements.txt --strict`；npm 唯一依赖是 devDependency、Gradle 存量都不在承诺内。许可证只做精确豁免（`dependency-review.yml` 的 `allow-dependencies-licenses` 里列着双许可的 `libadb-android`），不要关掉整个 license check。两个 job 都只让问题可见，要拦在合并前须分支保护 + required status checks。Dependabot 不开，依赖升级一律人工做并重新验证真机行为。 <!-- rule:dev.deps.dependency-review -->
- 静态检查：`uvx ruff@0.17.3 check tool tests gui android/app/src/main/python android/smoke.py recipes recipe_lib`，规则集（`F` / `E9` / `B`）只在仓库根 `pyproject.toml` 定义、加规则改那里，目标清单只写在命令里，CI 的 `lint` job 与这份文档跑同一条；本地与 CI 同一个版本（CI 就钉 0.17.3，`.venv` 里没有 ruff）。`recipes/` 从 #1247 起也在清单里：脚本除 `p` / `rt` 外的裸名字都走顶部 import，未定义名看得见；`recipes/**/*.py` 的 F401 仍整类关在 `[tool.ruff.lint.per-file-ignores]` 里（少数 import 只为事实层留出处，如 PNM-AN10 的 `baidu_browser`），别在脚本里撒 `# noqa`。也不开格式与行长规则。<!-- rule:dev.ruff.pinned-and-scoped -->
- `ruff` 的 `B`（bugbear）类已启用：闭包捕获循环变量（`B023`）、`zip` 缺 `strict=`（`B905`）会红。`B023` 确认「当轮创建、当轮消费」后写 `# noqa: B023` 加一句理由，真延后调用的改代码；`B905` 论证长度必然相等才写 `strict=True`，论证不成立写 `strict=False` 并注释。<!-- rule:dev.ruff.bugbear-rules -->
- 类型检查：`mypy` 的 `files` 是 `tool/`，范围与宽松档参数都在仓库根 `pyproject.toml` 的 `[tool.mypy]` 里（本地先 `.venv/bin/pip install mypy==1.18.2`，再 `.venv/bin/mypy`）；`gui/` 有自己的平台分支与假对象，不进范围。机型脚本由 `python3 tool/typecheck_recipes.py` 逐份检查：47 份 `.toml` 走 catalog 校验器，42 份例外 `.py` 逐个喂给同一个宽松档（`.py` 同名，一次扫会撞模块名；`MYPYPATH=tool`，`python -m mypy`），两条都要绿。CI 的 `types` job 与本地同一条、只在 Linux 跑（mypy 按平台裁剪分支，换个平台结论不等价），版本不进 `requirements.txt`（同 `coverage`）。宽松档就是 `check_untyped_defs` 加关掉 `var-annotated`；其余存量错误改代码，不用 `type: ignore`、不加别的压制。**不做全量注解**。 <!-- rule:dev.types.narrow-scope-in-config -->
- 严格档只给十个纯逻辑模块：`polarity` / `channel_policy` / `host` / `events` / `recipe_meta` / `recipe_source` / `reader` / `plan` / `summary` / `coverage_note`，名单与逐项 flag 都在 `pyproject.toml` 的 `[[tool.mypy.overrides]]` 里；写 `strict = true` 会被 mypy 当全局设置，只能逐项列。判据是不碰设备、不碰手机界面、不依赖假对象，注解才追得到调用方；新增这类模块按同一判据补完注解再进名单，两处一起改。`recipe_steps` 从 #1268 起已移出（它现在直接下发设备动作，与 nav/strategies 同类）。其余引擎目录保持宽松档，`gui/` 仍不进范围，`recipes/` 只走宽松档、不进严格档名单。 <!-- rule:dev.types.strict-on-pure-modules -->
- 标准流转 UTF-8 只走 `tool/stdio.py` 的 `use_utf8_console()`：Windows 控制台与管道默认不是 UTF-8，打印中文与 ✓ / ✗ 会 `UnicodeEncodeError`；转不动时静默跳过（手机版 `aac_android/inproc.py` 的 `_Router` 就没有 `reconfigure()`），各入口别再自己写一份 try/except。`tests/test_rules_guards.py` 的 `StdioGuards` 扫全仓文本，除 `tool/stdio.py` 外任何文件自行重配置标准流即红——正文里不要照抄那行写法，守卫会连文档一起抓。 <!-- rule:dev.stdio.single-exit -->
- 覆盖率：先 `.venv/bin/pip install coverage==7.17.2`（不进 `requirements.txt`，那是产品依赖），再 `.venv/bin/python -m coverage run -m unittest discover -s tests` → `.venv/bin/python -m coverage report --show-missing`；判据在仓库根 `.coveragerc`（`branch=True`、`source=tool,gui`，omit 的只有工具脚本与三行的常量模块）。CI 的 `coverage` job 把 Linux 与 Windows 两份数据合并成一份报告写进 job summary，同仓分支的 PR 上再挂一个 `coverage <百分比>%` 的 check，**不设任何阈值**；单平台数字一定低估，本地一份数据不能当跨平台结论。 <!-- rule:dev.coverage.two-platform-merge -->
- 找「前端行为测试」先看 `tests/js/`：用例用 `node --test` + jsdom 加载真实的 `gui/web/index.html` 与官网根目录的 `index.html`（下载页；手机版界面是 Compose，不在 jsdom 里测，判断在 `aac_android/view.py`，用 Python 测；[ADR-0017](docs/adr/0017-frontend-test-harness.md)）。由 `tests/test_web_client.py` 在 `unittest` 里代跑，回归仍是上面那一条命令；单跑先 `npm ci`，再 `npm test`（参数以根 `package.json` 的 `test` 脚本为准；Node 22 不认目录参数，`--test-force-exit` 防漏写 `window.close()` 时挂住）。jsdom 覆盖不到的真渲染 / 真定时器再退到真浏览器：`python -m http.server` 起静态服务，页面加载后桩 `window.pywebview.api` 并 dispatch `pywebviewready`，之后直接调 `showRun()` 这类顶层函数。 <!-- rule:dev.tests.frontend-harness -->
- CHANGELOG 一条一行、≤ 80 字，落在 `## 未发布` 的 `### 新增` / `### 修复` / `### 内部` 之一，结尾挂一个编号（有 PR 挂 PR 号，只有 issue 的挂 issue 号；内部重构再加 ADR 号）。内部条目允许点一个符号名，但不展开机制；测试数、基线 SHA、对拍组数一律不写——那些在 PR 描述与 ADR 里。`## 未发布` 期间不写验证行，发版时才补。rebase 后先 `git rebase --continue` 把提交落完、再跑回归与对拍，并确认 `## 未发布` 没有被已发版的小节吸收（main 刚发过版时要重新开出来）。 <!-- rule:doc.changelog.one-line-entry -->
- 审查标准：见 `CODING_STANDARDS.md`，只放判断项；机械规则交给 CI。 <!-- rule:doc.standards.judgement-only -->
- 社区问题的归类与真机缺口见 [docs/09](docs/09-社区问题处理.md)：那里只记 GitHub 上看不到的判据与真机缺口——票号可以作出处，逐条回复、标签流转与「哪张票什么时候关的」留在 issue 里。 <!-- rule:doc.community.local-knowledge-only -->
- 改「各品牌在哪儿连点 7 下」先看 `docs/手机版教程/brand-taps.json`：这四行是单一来源，跑 `python tool/gen_brand_taps.py` 渲染进 `android-tutorial.html`、`docs/手机版教程/README.md`、`docs/00-打开开发者模式.md` 的 `brand-taps` 标记区，漏跑由 `tests/test_doc_consistency.py` 抓；标记区外的正文（如页面里「小米连点的是「OS 版本」」）仍是手写，改这里不改那里。 <!-- rule:doc.tutorial.brand-taps-single-source -->
- 改「官网两页的外观」先看仓库根的 `site.css`：调色板、深色档、顶栏与页脚只在那里，`python tool/gen_site_css.py` 把它渲染进 `index.html` 与 `android-tutorial.html` 的 `site-css` 标记区，页面不引外链（单文件副本取不到，[ADR-0025](docs/adr/0025-site-shared-css.md)）。两页在共享样式上的差异值只在 `:root.reading` 一条里（页面专属样式仍各自持有），漏跑由 `tests/test_doc_consistency.py` 的 `SiteCssTests` 抓。 <!-- rule:doc.site.shared-stylesheet -->
- 找「试跑一下安卓」先看 `android/smoke.py`：一条命令走完 CI 出 debug 包 → 装开发机 → 启动 → 从首页点到底 → 还原三项，三段各自出结论，`--screens` 追加 demo 逐屏存活判定。默认档在桌面侧读屏认文字、按坐标点按（`ui_session.connect` 取 dump，不直连 `uiautomator dump`），执行本身照旧等 App 的 debug 导出；`--fast` 换成只跑执行段的快速档，计划按手机状态 JSON 现算、固定下发两次。App 侧只有那一个 debug 导出入口（入口在 debug 源集，release 的 `Demo` 是空壳）。构建留在 CI，本机只要有 `adb`、`gh` 与仓库根的 `.venv`（渠道还原要用 adbutils），产物按 commit 落临时目录不入库。用法与首次配对见 `android/README.md`。 <!-- rule:dev.android.smoke-entry -->
- 造不连手机的 `Phone` 用 `tests/fixtures.py` 的 `phone_stub()`（`fake_phone()` 就是它加一条时间轴），装配只此一处。客户端用例要假 `Runner`（命令返回什么、spawn 交什么）同样用它：`FakeRunner` / `FakeProc`，`Api(runner=…)` 注入，不要 patch `api._run` 与 `app.subprocess`。纯重构要给对拍证据时，同一文件还有 `all_pages()` / `Clock` / `Timeline` + `Device`。 <!-- rule:dev.tests.fixtures-single-assembly -->
- 无设备用例不许真等：`chan_fast` 的 scan 分支会读型号，用例要 patch 掉 `phone_model`，否则对着不存在的序列号等 adb 超时；机型脚本一律用 `fixtures.load_recipe()` 装载（它把脚本的 `time` 三个读数一起换成假钟），自己 `exec` 一份脚本就会真 sleep。躲不开真实进程的环节（跨进程锁、真起播放器）用 `Clock` 注入或把等待压到毫秒级。`tests/test_recipe_loader.py` 守着装载这一条。 <!-- rule:dev.tests.no-real-wait -->
- 改「认渠道页」这类读屏逻辑要做改前改后对拍时，驱动器是 `tests/compare_chan_pages.py`：认页 / 进页 / 编排三层 × 两种屏尺寸，同一份探针分别跑冻结基线与当前 `tool/`；对拍要满足哪几条才算证据见 `CODING_STANDARDS.md` 的「对拍要能证伪」。
- 手机上「有」的读屏异常名，电脑上未必有：`aac_android/u2.py` 的 `install()` 把模块里定义的类动态注册成 `uiautomator2.exceptions`，电脑上装的是真库 + `adbutils`。在 `tool/`、`gui/` 里新增 `u2.exceptions.X` 或 `adbutils.X` 之前先确认桌面那份也有，`tests/test_runtime_symbols.py` 守着这一条。 <!-- rule:dev.android.runtime-symbols -->
- adb 固定 platform-tools 37.0.1（`gui/app.py` 的 `ADB_PINNED`）；升级时改那张表，校验值按 Google `repository2-3.xml` 的 SHA-1 核对。 <!-- rule:dev.adb.pinned-platform-tools -->
- 鸿蒙 HDC 不入库：`gui/hdc_fetch.py` 按平台从 OpenHarmony `7.0-Release` 下载三个 tarball，按钉死的 SHA-256 校验并解出 `hdc` 与 `libusb_shared`；升级时改那里的表，构建与缓存顺序别另写一份。 <!-- rule:dev.hdc.build-time-download -->
- 客户端数据路径看 `gui/app.py` 的 `ClientData`，备份目录看 `tool/backups.py` 的 `Backups`（root 由调用方给），工具模块用 `_tool()` 惰性取。 <!-- rule:dev.client.data-paths -->

## 错误日志上报

- 用户说明见 [docs/12](docs/12-错误日志上报.md)。服务器、数据库、部署与运维信息只记在本机 `CLAUDE.local.md` 和 `.private/`，不进仓库。 <!-- rule:doc.reports.private-infra-stays-local -->

## 发版

- 发版分两段，中间隔着不确定的时间：维护者在收口并合入 main 的提交上打 `v*` tag 后退出，owner 只按这个 tag 做发版动作（构建、上传、正文、页面同步）。tag 之后 main 照常合入新的 PR，谁也不按 main 尖端出包。完整流程与 Release 正文的写法见 `docs/agents/release.md`：正文是用户看的唯一权威，repo 里不留副本，`README.md` 的首段从它复制。 <!-- rule:doc.release.note-is-the-only-authority -->
- 新版本提示读官网的 `android-ad-cleaner-latest.json`，发版后要更新它（步骤记在本机 `CLAUDE.local.md`）。 <!-- rule:doc.release.latest-json-after-release -->
- 官网另有一份放在机主的服务器上，发版后同步，方法记在本机 `CLAUDE.local.md`。 <!-- rule:doc.release.site-mirror-sync -->
- 国内下载走 Gitee：`python3 gui/upload_gitee.py <版本>` 从公开的 GitHub Release 下载安装包并核对 SHA256，推代码和标签，建发行版传附件，再匿名下载回来核对。令牌在本机 `~/.config/gitee/token`，不进仓库和对话。百度网盘暂停使用；Gitee 不可用时把 `index.html` 的 `REL.gitee` 留空，改跑 `gui/upload_baidu.sh [版本]`，`#dl-lead` 的改法与必须原样保留的后半句见 `docs/agents/release.md` 的「发版动作」第 7 步。 <!-- rule:doc.release.gitee-upload -->
- 发完版按 `docs/agents/release-followup.md` 的清单催复测：新版不送到报告者手上，`waiting-for-verify` 的 issue 不催就永远关不掉。

## Agent skills

### Issue tracker

GitHub Issues（`gh` CLI）：开工第一条命令是 `python3 tool/claim.py <票号>`，退出码 2 表示别人已持有，停下上报、不要在另一张 worktree 上重做；合入后 `--release`，放弃改派用 `--abandon`。「开工前先有票」的判据与仲裁规则见 `docs/agents/issue-tracker.md` 的「票的生命周期」；标签语义见 `docs/agents/triage-labels.md`。 <!-- rule:doc.issue.claim-command -->

认领时一并摘掉 `ready-for-agent` / `ready-for-human` / `needs-triage`：这三张的意思是「在待办池里等人挑」，留着别的会话会再挑一次。`stale` 也一起摘，但 `--abandon` 不把它加回来。 <!-- rule:doc.issue.claim-removes-ready -->

### Triage labels

标签名即角色名，另加 `waiting-for-verify` / `in-progress` 两个状态标签与 `stale` / `blocked-on-device` 两个修饰符：各自的含义、与角色的关系、加摘时机见 `docs/agents/triage-labels.md`。

### Code review

派审查的方法与规则见 `docs/agents/code-review.md`：基线钉 SHA、审查期间不改工作区、默认三轴。

### Domain docs

single-context：根目录 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。`CONTEXT.md` 只放术语表（命令 / 脚本 / 清单与词库 / 执行 / 连接 / 事件 / 等待 / 通知 / Issue 状态 / 规则 / 文档十一组定义）；模块边界的决定写进 `docs/adr/`（编号与标题见 `docs/adr/README.md`）。**整体形状看 `docs/ARCHITECTURE.md`**：三个宿主、四条跨边界契约、模块清单；机制与取舍仍在 ADR 里，总览不复述。
