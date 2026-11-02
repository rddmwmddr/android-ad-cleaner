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

- 逐字保留的一条隐形行为：`Backups.latest()` 是 `sorted(...)[-1]`，字典序上 `"<型号>-gui"` 排在所有 `"<型号>-<时间>"` 之后——只要兜底目录存在，它优先于带时间的备份。`channels.tsv` 会写进去、`restore channels` 从里面读，所以这不是可以「顺手改成取最新」的地方。
- `latest()` 选 `listdir` + `startswith(model + "-")`（`gui/app.py` 原来的语义），`run.py` 原来的 `glob(f"{model}-*")` 不再使用。型号里真出现 glob 元字符（`[` `]` `*` `?`）时两边结果不同——`A[B]C-*` 在 glob 下能匹配 `ABC-…`。真机型号不会有这些字符，`tests/test_backups.py` 有用例钉住选中的这一套。
- 测试原有的 `api._run = Mock(...)`、`patch.object(app.subprocess, "Popen")`、`patch.object(app.subprocess, "run")` 三类 patch 全部保留：`Runner` 用的还是同一个 `subprocess` 模块对象。改用注入的假 `Runner` 是另一笔独立迁移。
- `data_dir()` 只去掉 `makedirs`，位置判定（Windows `%APPDATA%` / macOS `Application Support` / 其它 `~/.local/share`）逐字未动。`ClientData.ensure()` 只在 `client_api()`（窗口与截图脚本共用的入口）与两处写盘前调用：`_install_id()` 与 `_download()`——后者原先依赖 import 期那次 `makedirs`。
- 没有 Windows、没有打包环境、没有真机：`--cli` 子进程、`_MEIPASS` 布局、`--smoke-gui` 未在打包件上验证。依据是 `cmd_for()` / `cli_main()` 逐字未改、`child_env()` 只多收一个备份根（值与原模块级 `BACKUPS` 相同），加上 `python -m unittest discover -s tests` 533 项全过（同一台机器上 `git archive origin/main` 的干净副本是 520 项）。
- 验收证据两处：`tests/test_gui_import.py` 在子进程里用临时 `HOME`/`APPDATA` 跑真正的 `import gui.app`，断言不建目录、不改 `sys.path`、没有任何 `__file__` 落在 `tool/` 下的模块被加载（改前必红）；`tests/test_backups.py` 把改动前 `run.py` 与 `gui/app.py` 的两份实现逐字抄成基线，喂 7 组目录树逐项对拍，并单独守卫三条目标分支：`-gui` 优先、`os.listdir` 真的抛 `FileNotFoundError` 被接住、glob 元字符按字面处理。
- 2026-11-02 起入口是 `gui/launch.py`：`python -m gui.app`、`python gui/app.py`、`python gui/launch.py` 与打包件四种启动方式都转发到同一个 `main()`，`tests/test_packaging_entry.py` 在子进程里各跑一遍 `--cli`（删掉转发、破坏无父包分支都会红）。Windows 打包验证不再依赖人手动点：`gh workflow run build-windows.yml --ref <分支>` 会在改过的入口上重打包，并对打包件跑 `--cli` 与 `--smoke-gui` 冒烟。Mac 打包本机没有环境，仍只有静态守卫。
