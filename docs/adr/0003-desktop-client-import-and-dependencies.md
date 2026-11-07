# 客户端的 import 期什么都不做，路径与启动器从外面给

`import gui.app` 原来有两个副作用：`sys.path.insert(0, TOOL)`，以及模块级 `DATA = data_dir()` 里的 `os.makedirs`。后果是测试没法正常 import，18 处改用 `importlib.util.spec_from_file_location` 把同一份代码以十几个模块名重复加载；`patch.object(app, "DATA", tmpdir)` 在 7 个文件里共 12 处成了绕过模块级常量的唯一办法（另有一处直接赋值 `app.DATA = …`）。数据目录的 7 条派生路径（`DATA` / `backups` / `logs` / `pause` / `install-id` / `platform-tools` / `platform-tools.zip`）各算各的，备份目录的命名、扫描、`<型号>-gui` 兜底和 `AAC_BACKUPS` 的读取散在 `tool/run.py`、`gui/app.py`、`tool/fast.py` 三处算、四处读。`Api.__init__` 还直接跑 `find_adb()`（`adb version`，8 秒超时），15 处用例都在真跑它。

## Considered Options

- **`_tool(name)` 惰性取**（采纳）vs **`tool/` 变真包**（否）。加 `tool/__init__.py` 并改掉所有裸 import，看着更干净，但 `recipes/` 靠 `exec` 注入作用域、打包后的 `--cli` 靠 `runpy.run_path(TOOL/脚本)`、`bundle_data` 只把 `tool/*.py` 当数据文件收，改包身份要同时动这三条线，而本机没有打包环境能验。惰性取只把「什么时候改 `sys.path`」从 import 期挪到第一次真正用到工具模块时。
- **`ClientData(root)` 值对象**（采纳）vs **只传 `data_dir` 字符串**。7 条派生路径写在 `os.path.join` 里会继续散在 10 个方法中；值对象让「客户端的数据放在哪」是一份可读的清单，且构造只算不建，`ensure()` 才建。
- **`data_dir` 必填、无默认值**（采纳）vs **留默认值**。默认值等于把用户目录带回构造期，正是这次要掐掉的东西。`adb` 与 `runner` 保留 `None` 默认：前者表示「没有 adb」，后者表示「自己造一个默认启动器」。
- **`root_from_env()` 留在 `tool/backups.py`**（采纳）vs **`run.py` 与 `fast.py` 各自读 `AAC_BACKUPS`**。`Backups` 类本身不读环境变量、不认得客户端；这个自由函数只服务「本身是命令行进程」的调用方（`run.py` 的 `BACKUPS`、`fast.py` 的 run-log 目录、`display_backup_path`），把它挪走等于把同一个环境变量读两遍。
- **`Runner` 留在 `gui/app.py`**（采纳）vs **新建 `gui/runner.py`**（否）。`gui/` 不是包，PyInstaller 能否静态收进新模块取决于 `pathex`，而 `bundle_data` 的清单里也没有 `gui/*.py`；本机无法验证打包结果。拆文件并入后续「窗口启动独立 module」（2026-11-02 已完成其中的入口拆分，#391；`Runner` 仍留在 `gui/app.py`）。
- **`gui/winpreflight.py` 独立成文件**（采纳，2026-11-01，#228）vs **内联进 `gui/app.py`**。上一条否掉 `gui/runner.py` 的理由是「本机无法验证打包能否收进同级模块」，这条顾虑经实测不成立：用与 `windows.spec` 同形的 `Analysis([ROOT/gui/app.py], pathex=[ROOT])` 建两文件工程打包，同级模块出现在 `Analysis-00.toc` 里，打出来的 exe 能 import 并运行。`winpreflight` 只被 `gui/app.py` 引用，不 import `tool/`，所以不碰 `_tool()` 那条惰性路径；打包之外还要兼顾「直接跑脚本」与「被测试当包 import」，用 `try: from . import winpreflight / except ImportError: import winpreflight` 两行兼容。
- **`Backups(root)` 的 root 由调用方注入**（采纳）vs **模块里读 `AAC_BACKUPS`**（否）。客户端主进程没有这个环境变量（它只在 `child_env` 里给子进程），模块里读会让客户端的备份目录算到仓库根上去。
- **`Api` 拆成 `AdbDownloader` / `Reporter` / 批处理调度**（否）。行为面比 import 净化大得多，且 GUI 没有自动化验收手段；本轮只做依赖注入，拆类留给跟踪票。
- **窗口启动独立成 `gui/launch.py`**（采纳，2026-11-02，#391）vs **`main()` / `smoke_gui()` 留在 `gui/app.py`**。三处锚点此前都指向 `app.py`：`windows.spec` 的 `Analysis`、`build_mac.sh` 的 pyinstaller 目标，以及 `version.py` 等三处读版本号的位置。拆开后入口只留一段 `main()` 转发，`VERSION` 仍在 `app.py` 一处，三处版本号读取一句都不用改；`Runner` 仍未拆。

## Consequences

- 逐字保留的一条隐形行为：备份目录按字典序排，`"<型号>-gui"` 排在所有 `"<型号>-<时间>"` 之后——只要兜底目录存在，它优先于带时间的备份。`latest()` 取这个顺序的最后一个（#628 起改由 `Backups.all()` 的倒序取第一个，结果不变）。`run.py` 的 `latest_backup()`（`quickapp-setting.json`、`suspended.txt` 等记录的落点）与 `cmd_status_json()` 都吃这个顺序，所以这不是可以「顺手改成取最新」的地方。（2026-11-07 修订，#651：客户端关渠道与 `run.py chan-scan` 的 `channels.tsv` 曾经都按 `latest_backup()` 写进 `<型号>-gui`，每次运行盖掉上一次，历次清单只剩最后一批；现状是两者都写 `Backups.snapshot()` 给出的快照目录，`<型号>-gui` 不再接收 `channels.tsv`，那里的渠道清单只剩还原写的合并版 `channels-restore.tsv`。`suspend` / `quickapp` 的记录仍按 `latest_backup()` 的落点，可能落进它。）
- `latest()` 选 `listdir` + `startswith(model + "-")`（`gui/app.py` 原来的语义），`run.py` 原来的 `glob(f"{model}-*")` 不再使用。型号里真出现 glob 元字符（`[` `]` `*` `?`）时两边结果不同——`A[B]C-*` 在 glob 下能匹配 `ABC-…`。真机型号不会有这些字符，`tests/test_backups.py` 有用例钉住选中的这一套。
- 测试原有的 `api._run = Mock(...)`、`patch.object(app.subprocess, "Popen")`、`patch.object(app.subprocess, "run")` 三类 patch 全部保留：`Runner` 用的还是同一个 `subprocess` 模块对象。改用注入的假 `Runner` 是另一笔独立迁移。
- `data_dir()` 只去掉 `makedirs`，位置判定（Windows `%APPDATA%` / macOS `Application Support` / 其它 `~/.local/share`）逐字未动。`ClientData.ensure()` 只在 `client_api()`（窗口与截图脚本共用的入口）与两处写盘前调用：`_install_id()` 与 `_download()`——后者原先依赖 import 期那次 `makedirs`。
- 没有 Windows、没有打包环境、没有真机：`--cli` 子进程、`_MEIPASS` 布局、`--smoke-gui` 未在打包件上验证。依据是 `cmd_for()` / `cli_main()` 逐字未改、`child_env()` 只多收一个备份根（值与原模块级 `BACKUPS` 相同），加上 `python -m unittest discover -s tests` 533 项全过（同一台机器上 `git archive origin/main` 的干净副本是 520 项）。
- 验收证据两处：`tests/test_gui_import.py` 在子进程里用临时 `HOME`/`APPDATA` 跑真正的 `import gui.app`，断言不建目录、不改 `sys.path`、没有任何 `__file__` 落在 `tool/` 下的模块被加载（改前必红）；`tests/test_backups.py` 把改动前 `run.py` 与 `gui/app.py` 的两份实现逐字抄成基线，喂 7 组目录树逐项对拍，并单独守卫三条目标分支：`-gui` 优先、`os.listdir` 真的抛 `FileNotFoundError` 被接住、glob 元字符按字面处理。
- 2026-11-02 起入口是 `gui/launch.py`：`python -m gui.app`、`python gui/app.py`、`python gui/launch.py` 与打包件四种启动方式都转发到同一个 `main()`，`tests/test_packaging_entry.py` 在子进程里各跑一遍 `--cli`（删掉转发、破坏无父包分支都会红）。Windows 打包验证不再依赖人手动点：`gh workflow run build-windows.yml --ref <分支>` 会在改过的入口上重打包，并对打包件跑 `--cli` 与 `--smoke-gui` 冒烟。Mac 打包本机没有环境，仍只有静态守卫。

## 增补：随包 `<exe>.config` 与「被判成远程来源」的归因（#597）

部分 Windows 机器上，包内没有 `Zone.Identifier` 的托管 dll 也会被 .NET Framework 按「网络位置」拒载（`NotSupportedException`，`HResult 0x80131515`），`import clr` 起不来，报的是与 MOTW 同一句 `Failed to resolve Python.Runtime.Loader.Initialize`。

- **随包自带 `<exe>.config` 打开 `loadFromRemoteSources`**（采纳）vs **让用户照提示手工建这份文件**（否）。包内 dll 全部随包分发，没有任何从外部路径加载代码的通路，放宽这一条不改变来源可信度；手工建文件则把每次启动失败变成一次手工操作。代价是这台机器上「按路径加载」的检查对整个过程关掉，这是有意接受的安全权衡。`aac-cli.exe` 同样要带——它是双方共用的另一个入口。
- **归因在 `startup_failed()` 的 `error` 原文上做子串匹配**（采纳）vs **起子进程跑 PowerShell 探一次**（否）。失败点正是 `import clr`，此时 pythonnet 的 `System` 模块还不存在，进程内拿托管 dll 试加载做不到（#609 的探测方案因此不可行）；另起进程能测，但测的是另一份加载上下文。代价是库把这句话改写后要同步维护那两个子串。
- **`--smoke-gui` 的 `startup:` 行加 `load=` 字段**（采纳）。取值 `unresolved` / `no`，不复用 MOTW 的三态命名；打包件起不来时用户能贴的只有这一行。
- 判定顺序固定为：缺 WebView2 → MOTW → 原文拒载 → 注册表读不到 → 兜底。带 MOTW 的 dll 与被判成远程来源的 dll 报同一句错，前者的出路是解锁文件，所以 MOTW 必须先判。

## 增补：启动失败提示先复制、后弹窗（#811）

弹窗是原生 `MessageBoxW`，文字选不中。MOTW 那一路要用户照着敲 `Get-ChildItem … | Unblock-File`，另外几路要用户把括号里的错误原文回报到 issue——不替用户复制，就只能手抄或拍照识别。

- **弹窗之前用 `win_clipboard()` 把整段文案写进剪贴板**（采纳）vs **在界面上画复制按钮**（否）。这条路径上没起来的正是 WebView2 界面，界面里画不出按钮；自绘 Win32 对话框画得出，但收益不如自动复制，风险还高。
- 写进剪贴板的内容就是弹窗里那一句，逐字一致：复制说明在 `startup_advice()` 里追加，别在弹窗处另拼一份，否则改文案时容易只改一处。
- 写剪贴板失败**不能挡住弹窗**：`startup_failed()` 的收容集合是 `Exception`（与 `Api.copy_text` 一致），退回到文案末尾的「按 Ctrl+C」提示。窗口版没有控制台，弹窗是用户唯一看得到的东西，`except OSError` 会让 `UnicodeEncodeError` 之类的失败连弹窗一起吞掉。
- 剪贴板写入是可注入协作者，默认 `win_clipboard`，与 `notify` / `open_url` 同一形状，用例于是在非 Windows 上也能验「先复制、后弹窗」的顺序。
