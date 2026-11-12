"""纯重构要「改前改后对拍」时用的现成材料：页面样本、假时钟、按时间轴换页的假设备、假 Phone、假 Runner，以及提交校验用的临时 git 仓。

CODING_STANDARDS.md 要求纯重构给出对拍证据，页面样本取 tests/ 里所有 <hierarchy>、至少两种屏尺寸。
以前每做一次同类重构都要现场把这五样东西重搭一遍，现在 import 一下就有：

    from fixtures import EMPTY_PAGE, SIZES, all_pages, drive
    for label, xml in all_pages():
        for size in SIZES:
            print(label, size, drive(lambda p: p.settle("", 1.0), size=size,
                                     stages=[(0.0, EMPTY_PAGE), (0.2, xml)]))

对拍用的页面样本别拿来断言新行为 —— 测试要照实现之外的事实断言，夹具是为了让两份实现吃同一份输入；
假 Phone / 假 Runner 不在此列，单元测试直接用它们装配。
"""
import ast
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time as _time
from collections import namedtuple
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

# 报告者贴的原文（#597）：clr_loader 按路径加载 Python.Runtime.dll 时被 .NET Framework 拒了。
# 归因与打包冒烟两侧都拿它当输入，措辞照原样留一份。
RESOLVE_ERROR = (
    "RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from "
    r"D:\AndroidAdCleaner\_internal\pythonnet\runtime\Python.Runtime.dll"
)

_REAL_TIME, _REAL_MONOTONIC = _time.time, _time.monotonic

# 两种屏尺寸：竖屏主流宽度差一半，行分带与可视区域判定都要在这两种下各跑一遍
SIZES = ((1080, 2340), (720, 1600))

# 跳页动画里读到的空树：不是「页面已经画好」
EMPTY_PAGE = '<hierarchy rotation="0"></hierarchy>'

_HIERARCHY = re.compile(r"<hierarchy\b.*?</hierarchy>", re.S)


def load_tool():
    """把 tool/ 加进 sys.path（与各 test 文件里的写法等价）。"""
    tool = str(ROOT / "tool")
    if tool not in sys.path:
        sys.path.insert(0, tool)


def all_pages(folder=None):
    """tests/ 里所有能解析的 <hierarchy> 字面量：[(来源标签, xml)]。

    直接从测试源码里抽，不另存一份副本 —— 测试改了样本，这里跟着变。
    有一份是故意造的非良构 XML（错误上报里要复现解析失败），跳过。
    """
    pages = []
    for path in sorted(Path(folder or TESTS_DIR).glob("test_*.py")):
        src = path.read_text(encoding="utf-8")
        for i, found in enumerate(_HIERARCHY.finditer(src)):
            try:
                ET.fromstring(found.group(0))
            except ET.ParseError:
                continue
            pages.append((f"{path.name}:{i}", found.group(0)))
    return pages


@contextlib.contextmanager
def baseline_worktree(sha, root=None):
    """把 <sha> 解到临时 worktree，交出它的根目录；退出时删掉 worktree 与临时目录。

    对拍驱动的「改动前」从这里取：基线要钉提交 SHA，不入库快照文件。找不到提交时按出口惯例
    报一句并退出（`sys.exit` 的字符串走 stderr），临时目录与 worktree 一条都不留。
    """
    repo = Path(root) if root is not None else ROOT
    tmp = Path(tempfile.mkdtemp(prefix="aac-baseline-"))
    tree = tmp / "tree"
    added = False
    try:
        try:
            subprocess.run(["git", "worktree", "add", "--detach", str(tree), sha], cwd=repo,
                           check=True, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        except subprocess.CalledProcessError as e:
            sys.exit(f"找不到提交 {sha}：先 git fetch origin {sha}\n{e.stderr.strip()}")
        added = True
        yield tree
    finally:
        if added:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=repo,
                           check=False, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


class Clock:
    """until() 与 Phone 共用的假时钟：sleep 推进时间，读屏与点击自己也可以花时间。

    装进模块用 install_clock()：fast / chan_fast 里的 time.time / time.sleep 换成它，
    等待就按假时间走，测试不必真睡。
    """

    def __init__(self, read_cost=0.0, click_cost=0.05):
        self.t = 0.0
        self.read_cost = read_cost
        self.click_cost = click_cost
        self.page_reads = 0
        self.clicks = 0

    def time(self):
        return self.t

    monotonic = time

    def sleep(self, seconds):
        self.t += seconds

    def read(self):
        """读一次屏：按 read_cost 花时间，慢机型的读屏开销就加在这里。"""
        self.page_reads += 1
        self.t += self.read_cost

    def click(self):
        self.clicks += 1
        self.t += self.click_cost


def clock_targets(module):
    """换 `time` 时要一起换的模块：给的是 `fast` 就连两个基座与拨动会话一起（ADR-0033）。

    只换门面那一份的话，`Screen.settle` 会按真实时间空转、假时间轴再也不推进。
    """
    targets = [module]
    if getattr(module, "__name__", "") == "fast":
        targets += [sys.modules[name] for name in ("phone.connection", "phone.screen", "phone.toggler",
                                                    "phone.launcher", "phone.settings_search",
                                                    "phone.dismisser", "phone.navigator")
                    if name in sys.modules]
    return targets


def install_clock(module, clock):
    """把这个时钟装进 fast / chan_fast（以及它背后的基座与阶段），不还原；返回 clock。"""
    for target in clock_targets(module):
        target.time = clock
    return clock


def clocked(case, module, clock):
    """同 `install_clock()`，并登记到 `case.addCleanup` 还原；返回 clock。

    用例里别只 `self.addCleanup(setattr, fast, "time", original)`：那只还门面那份，基座与阶段
    留在假钟上，后面的用例 `patch.object(fast.time, …)` 打的是真模块、`_launch()` 读的却是残留
    假钟，等待循环就脱管了（#1041 审查实测：`test_phone_launcher` 之后跑 `test_regressions`
    会 StopIteration，全量回归只因文件顺序凑巧才没红）。
    """
    saved = [(target, target.time) for target in clock_targets(module)]
    for target, _ in saved:
        target.time = clock

    def restore():
        for target, value in saved:
            target.time = value

    case.addCleanup(restore)
    return clock


@contextlib.contextmanager
def patched_clock(clock, module=None):
    """同 `install_clock()`，但退出时把每个模块的 `time` 放回去：用例要连续跑几段、段间换钟时用它。"""
    targets = clock_targets(module or sys.modules["fast"])
    saved = [(target, target.time) for target in targets]
    try:
        for target in targets:
            target.time = clock
        yield clock
    finally:
        for target, value in saved:
            target.time = value


class Timeline:
    """按时间轴换页：stages = [(起始秒, 页面 xml)]，到达起始秒就切到那一页。

    时间只由假时钟推进，跟谁在轮询无关 —— 同一份时间轴喂给旧实现和新实现，才叫对拍。
    focus 是同形状的焦点窗口轴（包名/Activity），用来区分「页面变了」和「换了 App」。
    """

    def __init__(self, stages, focus=((0.0, ""),)):
        stages = list(stages)
        if not stages:
            raise ValueError("Timeline 需要至少一页")
        self.stages = stages
        self.focus_stages = list(focus)

    @staticmethod
    def _at(axis, t):
        value = axis[0][1]
        for start, candidate in axis:
            if t >= start:
                value = candidate
        return value

    def page_at(self, t):
        return self._at(self.stages, t)

    def focus_at(self, t):
        return self._at(self.focus_stages, t)


class Device:
    """uiautomator2 连接的替身：实现 `tool/reader.py` 的 Reader 接口，读屏按时间轴换页。"""

    def __init__(self, timeline, size, clock):
        self.timeline, self.size, self.clock = timeline, size, clock
        self.settings, self.jsonrpc = {}, SimpleNamespace()
        self.closed, self.stopped = False, None

    def dump_hierarchy(self):
        self.clock.read()
        return self.timeline.page_at(self.clock.t)

    def window_size(self):
        return self.size

    def shell(self, cmd, timeout=60):
        return SimpleNamespace(output="", exit_code=0)

    def screenshot(self):
        return None

    def app_stop(self, package):
        self.stopped = package

    def close(self):
        self.closed = True

    def __call__(self, **selectors):
        return SimpleNamespace(selector=None)


def phone_stub(serial="test", shell=None, fast_mod=None, **fields):
    """造一个不连手机的 Phone：假 link 与假传输都由它接好，其余属性按关键字传。

    `shell` 顶替读屏库那条传输（签名 `(command, timeout=)`）；`serial` / `lost` 会写穿到 link 上。
    单元测试要一个「有 Phone 的形状、但没有手机」的对象时用它，装配只此一处。

    两个基座（ADR-0033）在这里一起装配：`conn` 归连接与生命周期，`screen` 归观测与视口几何，
    门面只转发。它们只能用 `__new__` 造——`Connection.__init__` 要真连手机，`Screen.__init__`
    要真读屏，假手机两样都不能做。
    桩打在它所属的基座上，门面只是转发、内部调用绕过门面：观测与动作（`tree` / `focus` / `texts` /
    `sig` / `settle` / `switch_rows` / `on_screen` / `click` / `back` / `scroll` / `scroll_more`）打
    `p.screen`，连接与生命周期（`say` / `locked` / `wait_unlocked`）打 `p.conn`。要同时拦住门面上的
    调用点（机型脚本直接写 `p.say(...)`）就两处一起桩。
    三个会话对象（`lost_note` / `launch_session` / `channel_session`）与四个阶段（`toggler` / `launcher` /
    `search` / `dismisser`）也在这里造；
    它们的默认值归各自的类，这里不抄第二份。`changed` / `safe_mode` 归拨动会话，经门面的属性转发生效。
    另有一处与构造处不同：`pause_at_lock_check` 默认 False，因为假手机后面没有客户端在点「暂停」。
    屏尺寸 `W` / `H` 与读屏 adapter `d` 不设默认：它们是每条用例的前提，由调用方传。
    """
    if fast_mod is None:
        load_tool()
        import fast as fast_mod
    p = fast_mod.Phone.__new__(fast_mod.Phone)
    if hasattr(fast_mod, "Connection"):        # 对拍驱动也拿这份 fixtures 去喂拆分前的树（`compare_phone_state.py`）
        p.conn = fast_mod.Connection.__new__(fast_mod.Connection)
        p.screen = fast_mod.Screen.__new__(fast_mod.Screen)
        p.screen.conn = p.conn
        p.screen.dump = ""                     # 失败现场：没过 `__init__` 的基座由这里补（#1126）
        p.screen.pending_capture = ""
        if hasattr(fast_mod, "Captures"):
            p.screen.captures = fast_mod.Captures("")
    if hasattr(fast_mod, "LostNote"):          # 同上：会话对象的默认值由它自己的类给，这里不抄第二份
        p.lost_note, p.launch_session, p.channel_session = (
            fast_mod.LostNote(), fast_mod.LaunchSession(), fast_mod.ChannelSession())
    if hasattr(fast_mod, "Toggler"):           # 拨动会话绑在假手机上：`off()` 内部走它，门面只转发
        p.toggler = bind_toggler(p, fast_mod)
    if hasattr(fast_mod, "Launcher"):          # 启动阶段同理：`start()` 内部走它
        p.launcher = bind_launcher(p, fast_mod)
    if hasattr(fast_mod, "SettingsSearch"):    # 设置搜索同理：`setting()` / `type_text()` 内部走它
        p.search = bind_search(p, fast_mod)
    if hasattr(fast_mod, "Dismisser"):         # 弹窗同理：`dismiss()` / `_promoted_click()` 内部走它
        p.dismisser = bind_dismisser(p, fast_mod)
    if hasattr(fast_mod, "Navigator"):         # 导航同理：`tap()` / `go()` / `tab()` 内部走它
        p.navigator = bind_navigator(p, fast_mod)
    p.link = fast_mod.adb_link.Connection(serial, transport=shell or _silent_shell)
    p.log, p.pause_at_lock_check, p.systemui_text = False, False, False
    p.changed, p.safe_mode = [], False
    if not hasattr(fast_mod, "LostNote"):      # 旧树：这些字段直接落在实例上
        p.miss, p.missed, p.promoted, p.app = 0, [], set(), ""
        p.vivo_seen = False
        p.skeleton_sigs, p.skeleton_count, p.mismatch_probes = set(), 0, 0
    for name, value in fields.items():
        setattr(p, name, value)
    return p


def screen_stub(page=EMPTY_PAGE, size=SIZES[0], conn=None, fast_mod=None):
    """只造观测基座：读屏按给定页面返回，`on_screen` 一律算在屏内，其余不碰（#1042）。

    阶段用例要验「只造这一步」时用它，别在用例里手拼 `SimpleNamespace`——装配仍只落在
    fixtures 这一处。要别的动作原语再往实例上桩，`stub()` 对门面不拥有的名字直接落到实例。
    """
    if fast_mod is None:
        load_tool()
        import fast as fast_mod
    base = fast_mod.Screen.__new__(fast_mod.Screen)
    base.conn = conn or SimpleNamespace()
    base.W, base.H = size
    base.tree = lambda: ET.fromstring(page)
    base.on_screen = lambda n: True
    base.dump, base.pending_capture = page, ""
    if hasattr(fast_mod, "Captures"):          # 喂拆分前的旧树时没有这个类
        base.captures = fast_mod.Captures("")
    return base


def bind_toggler(phone, fast_mod):
    """在一台门面或 Mock 替身上架一个拨动会话（#1040）：装配只此一处。

    观测基座取 `phone.screen`（拆分前的树里就是门面自己）；真门面的丢失记录用它的
    `lost_note`，Mock 替身上门面与基座是同一个对象，直接用它的字段——`off()` 内部照旧读写
    同一批桩（`p.miss`、`p.missed`、`p.changed`）。
    """
    toggler = fast_mod.Toggler.__new__(fast_mod.Toggler)
    toggler.screen = _base(phone, "screen")
    if isinstance(phone, Mock):
        toggler.lost_note = phone
        toggler.safe_mode, toggler.changed = phone.safe_mode, phone.changed
    else:
        toggler.lost_note, toggler.safe_mode, toggler.changed = phone.lost_note, False, []
    return toggler


def bind_search(phone, fast_mod):
    """在一台门面或 Mock 替身上架一个设置搜索会话（#1042）：装配只此一处。

    观测与动作取 `phone.screen`，传输取它背后的 `conn`（`type_text()` 要发 jsonrpc 与 shell），
    丢失记录取门面的 `lost_note`，Mock 替身上门面与基座是同一个对象。
    """
    search = fast_mod.SettingsSearch.__new__(fast_mod.SettingsSearch)
    search.screen = _base(phone, "screen")
    search.conn = _base(phone, "conn")
    search.lost_note = phone if isinstance(phone, Mock) else phone.lost_note
    return search


def bind_launcher(phone, fast_mod):
    """在一台门面或 Mock 替身上架一个启动阶段（#1041）：装配只此一处。

    观测取 `phone.screen`、传输取它背后的 `conn`（`_launch()` 要发 `am start` / `pm path`）。
    启动会话取门面的 `launch_session`，Mock 替身上门面与基座是同一个对象。
    `dismiss` 是弹窗阶段的窄接口（`Dismisser.dismiss`），这里按调用时取门面的那一份：
    用例随后把 `p.dismiss` 换成别的桩也必须生效，所以不能在这里捕获绑定方法。
    """
    launcher = fast_mod.Launcher.__new__(fast_mod.Launcher)
    launcher.screen = _base(phone, "screen")
    launcher.conn = _base(phone, "conn")
    launcher.dismiss = lambda *a, **k: phone.dismiss(*a, **k)
    if isinstance(phone, Mock):
        launcher.lost_note = launcher.session = phone
    else:
        launcher.lost_note, launcher.session = phone.lost_note, phone.launch_session
    return launcher


def bind_dismisser(phone, fast_mod):
    """在一台门面或 Mock 替身上架一个弹窗阶段（#1043）：装配只此一处。

    观测与动作取 `phone.screen`；推广位退回读启动会话（`app` / `promoted`），
    Mock 替身上门面与基座是同一个对象。
    """
    dismisser = fast_mod.Dismisser.__new__(fast_mod.Dismisser)
    dismisser.screen = _base(phone, "screen")
    dismisser.session = phone if isinstance(phone, Mock) else phone.launch_session
    return dismisser


def bind_navigator(phone, fast_mod):
    """在一台门面或 Mock 替身上架一个导航阶段（#1044）：装配只此一处。

    观测与动作取 `phone.screen`，丢失记录取门面的 `lost_note`（Mock 替身上门面与基座是同一个
    对象）。`dismiss` 是弹窗阶段的窄接口，按调用时取门面的那一份：用例随后把 `p.dismiss` 换成
    别的桩也必须生效，所以不在这里捕获绑定方法。
    """
    navigator = fast_mod.Navigator.__new__(fast_mod.Navigator)
    navigator.screen = _base(phone, "screen")
    navigator.dismiss = lambda *a, **k: phone.dismiss(*a, **k)
    navigator.lost_note = phone if isinstance(phone, Mock) else phone.lost_note
    return navigator


def job_stub(**fields):
    """造一个「一次执行」的测试状态（ADR-0010）。默认刚开始、空日志、计时从 0 起，按关键字覆盖字段。

    `serial` / `model` / `total` / `t0` 走构造器，其余字段（lines / results / paused / cancel …）
    构造后直接赋值——测试里没有并发写者，不需要持锁。
    """
    from gui import app
    job = app.Job(serial=fields.pop("serial", "test"), model=fields.pop("model", "m"),
                  total=fields.pop("total", 0), t0=fields.pop("t0", 0))
    for name, value in fields.items():
        setattr(job, name, value)
    return job


def phone_mock(fast_mod=None, **fields):
    """以 Mock 冒充 Phone（配方脚本、只读命令这类不需要真页面的用例）。

    `Mock()` 上任何属性都是真值，于是 `Phone` 构造处声明的开关（`safe_mode` / `systemui_text` /
    `vivo_seen` / `lost`）在真实方法里会被当成 True；`d` 与 `reader` 也会变成两个不相干的 Mock，而
    `Phone.start` 这类内部走 `reader`、配方脚本走 `p.d`。这里只补这两件事，其余照旧交给 Mock
    （`changed` 保持 Mock，用例可以数 `.append` 的次数）。

    两个基座指向它自己（`p.conn = p.screen = p`）：机型脚本直接写 `p.tree()`，观测基座内部也写
    `self.tree()`，两处要看到同一个桩，否则同一份页面得在两处各配一遍（ADR-0033）。
    """
    if fast_mod is None:
        load_tool()
        import fast as fast_mod
    p = Mock(name="Phone")
    p.conn = p.screen = p      # 门面与两个基座是同一个 Mock：p.tree 与 p.screen.tree 是同一处桩
    p.pause_at_lock_check, p.systemui_text, p.vivo_seen, p.safe_mode = False, False, False, False
    p.lost = False              # Phone 上这是代理 link 的属性，Mock 上没有：不补就恒为真
    p.missed = []               # `report_run()` 读它：Mock 恒真会把干净的一轮判成失败（#788）
    # 三个会话对象（#1039）不造：没有代码直接读 `p.lost_note` 这类对象本身，读的都是它的字段，
    # 而字段在 Mock 上本来就是可写可读的替身。
    p.skeleton_sigs, p.skeleton_count = set(), 0
    p.mismatch_probes = 0
    p.reader = p.d = Mock(name="reader")
    for name, value in fields.items():
        setattr(p, name, value)
    return p


def normalize(source):
    """折成「代码逐字」：注释、docstring、空行、折行与函数签名上的注解都不影响判等，`g["X"]` 折回 `X`。

    注入面（`recipe_nav` / `recipe_steps`）的实现住在工厂里、脚本副本在顶层，缩进不同；注释与
    文档串各写各的，但都不改行为，逐字判据只认代码本身。`global X` 是本地定义留下的产物，
    改走注入之后不再需要，一起丢掉。`recipe_steps` 在 mypy 严格档的名单里，实现上的签名注解
    是那份要求的产物，脚本副本不写，同样不改行为。函数体里的变量注解（`AnnAssign`）不剥：
    出现时两边都会写，不写的那一边本来就该红。两个注入面的副本守卫共用这一份判据。"""
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) \
                and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.returns = None
            arguments = node.args
            for argument in (*arguments.posonlyargs, *arguments.args,
                             *arguments.kwonlyargs, arguments.vararg, arguments.kwarg):
                if argument is not None:
                    argument.annotation = None
    text = re.sub(r"""g\[['"]([A-Za-z_]\w*)['"]\]""", r"\1", ast.unparse(tree))
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("global "))


def _silent_shell(command, timeout=None):
    """没给 shell 时的传输：什么也不做，返回空输出。"""
    return SimpleNamespace(output="", exit_code=0)


class RecipeClock:
    """机型脚本的 time 替身：sleep 只推进 offset，脚本里的等待不占真实时间。

    time() / monotonic() 在真实读数上叠加 offset：「等到 deadline」的循环照样按期退出。
    三个读数要成套使用 —— 只挡 sleep 而让 time() 走真实时钟，等待循环就会原地忙转到 deadline。
    真实读数在 import 时取一次：用例可能把 time 模块换成了别的假时钟再装载脚本
    （`patch.object(x, "time", Clock())` 那种），那时从模块上取会拿到那个假时钟。
    """

    def __init__(self):
        self.offset = 0.0
        self.slept = 0.0

    def time(self):
        return _REAL_TIME() + self.offset

    def monotonic(self):
        return _REAL_MONOTONIC() + self.offset

    def sleep(self, seconds):
        self.offset += seconds
        self.slept += seconds


def load_recipe(phone, path, only=None, out=None, **extra):
    """装载机型脚本：注入 p / ONLY / 假 time，返回 (scope, 输出流)。

    ONLY 命中的段在 exec 当时就跑，而脚本自己的 `import time` 会盖掉注入的同名全局，
    所以执行期换的是模块上的 sleep / time / monotonic；跑完再把 scope["time"] 换成
    RecipeClock，用例之后调脚本里的函数也不真睡。

    `only` 照机型脚本自己的约定：不给（None）表示一段都不跑，给空集合表示跑全部段
    （脚本里是 `ONLY = globals().get("ONLY") or []` 配 `if not ONLY or name in ONLY`）。
    """
    clock = RecipeClock()
    scope = {"p": phone, "ONLY": _only_list(only), **extra}
    load_tool()
    import recipe_kit                      # 与引擎注入同一份；tool/ 只在 load_tool() 之后才在 sys.path 上
    recipe_kit.preamble(phone, scope)
    out = out if out is not None else io.StringIO()
    with patch.object(_time, "sleep", clock.sleep), patch.object(_time, "time", clock.time), \
            patch.object(_time, "monotonic", clock.monotonic), contextlib.redirect_stdout(out):
        exec(compile(Path(path).read_text(encoding="utf-8"), str(path), "exec"), scope)
    scope["time"] = clock
    return scope, out


def _only_list(only):
    """段名过滤：None → 哨兵（不跑任何段），单个字符串 → 一项，其余照抄。"""
    if only is None:
        return ["__no_steps__"]
    return [only] if isinstance(only, str) else list(only)


_BASE_OWNED_ = {
    "conn": ("locked", "wait_unlocked", "say", "check_alive", "close"),
    "screen": ("focus", "tree", "texts", "sig", "settle", "switch_rows", "on_screen",
               "click", "back", "scroll", "scroll_more", "find", "page_text"),
    # 设置搜索阶段自己的三个读数：`setting()` 内部调它们，门面只是转发（#1042）
    "search": ("type_text", "edit_ready", "focused_text"),
    # 导航阶段内部互相调用的入口：`go()` 调 `tap()`、`entry()` 调 `await_page()` / `tap()`、
    # `enter()` 调 `tap()`；门面只是转发（#1044）
    "navigator": ("tap", "tab", "go", "enter", "entry", "top", "tap_icon", "await_page",
                  "in_settings_page"),
}


def _base(phone, name):
    """门面背后的基座；拆分前的树里门面自己就是它（对拍驱动两种树都要能喂）。"""
    return getattr(phone, name, phone)


def stub(phone, name, value):
    """把一处替身落到拥有它的基座上（ADR-0033）；基座不拥有的名字落到门面自己。

    只写 `p.name = …` 挡不住引擎内部的调用：`start()` 走 `screen`，`say` / `check_alive` 走
    `conn`，内部调用绕过门面。反过来，往门面上再放一份会挡住基座的换桩（门面属性优先），
    所以基座拥有的名字只落基座——断言读 `p.screen.x` / `p.conn.x`，或者自己拿住这个替身。
    """
    owners = [base for base, names in _BASE_OWNED_.items() if name in names]
    for base in owners:
        setattr(_base(phone, base), name, value)
    if not owners:
        setattr(phone, name, value)


def fake_phone(clock=None, size=SIZES[0], stages=((0.0, EMPTY_PAGE),),
               focus=((0.0, ""),), fast_mod=None, shell=None, **fields):
    """造一个不连手机的 Phone：读屏走时间轴，点击 / 返回只推进假时钟。

    只替掉会碰手机的部分；tree / sig / settle 等仍是真的，走 Device.dump_hierarchy。
    `shell` 一起换掉两条传输：脚本里的 `p.d.shell`（读屏 adapter）与 `Phone.start` 走的
    `p.link`（连接基座）。要换掉别的属性（想断言点击的坐标、想固定 locked）用关键字传进来，
    形如 fake_phone(locked=lambda: True)——这些桩会同时落到它所属的基座上：门面只转发，
    内部调用走的是基座（ADR-0033）。
    """
    clock = clock or Clock()
    timeline = Timeline(stages, focus)
    device = Device(timeline, size, clock)
    if shell is not None:
        device.shell = shell
    p = phone_stub("fake", shell=shell or device.shell, fast_mod=fast_mod)
    p.W, p.H = size
    p.d = device

    def on_screen_base(name, value):
        """动作桩落在观测基座：门面的 `click` / `scroll` 只是转发，拆分前后内部调用都落到这里。"""
        setattr(_base(p, "screen"), name, value)

    on_screen_base("click", lambda *a, **k: clock.click())
    on_screen_base("back", lambda *a, **k: clock.click())

    def silent(*a, **k):
        return None

    p.dismiss = lambda *a, **k: None
    stub(p, "type_text", lambda text, *a, **k: (clock.click(), True)[1])
    on_screen_base("scroll", lambda *a, **k: None)
    on_screen_base("scroll_more", lambda *a, **k: False)
    stubs = {"focus": lambda: timeline.focus_at(clock.t), "say": silent,
             "locked": lambda *a, **k: False, "wait_unlocked": lambda *a, **k: True}
    stubs.update(fields)                       # 调用方给的桩压过默认值
    for name, value in stubs.items():
        stub(p, name, value)                   # 基座拥有的只落基座：门面上再放一份会挡住后来的换桩
    return p


def drive(call, modules=(), size=SIZES[0], stages=((0.0, EMPTY_PAGE),),
          focus=((0.0, ""),), read_cost=0.0, **fields):
    """跑一次并回报代价：造钟 → 装进给定模块 → 造假设备 → call(phone) → (结果, 耗时, 读屏次数, 点击次数)。

    对拍时左右两边各调一次，比较这四项里哪些变了；read_cost 用来看慢机型下的差异。
    """
    clock = Clock(read_cost=read_cost)
    for module in modules:
        install_clock(module, clock)
    p = fake_phone(clock=clock, size=size, stages=stages, focus=focus, **fields)
    out = call(p)
    return out, round(clock.t, 2), clock.page_reads, clock.clicks


class FakeProc:
    """`Runner.spawn()` 的返回值：stdout 供客户端逐行读，wait() 给返回码。"""

    def __init__(self, output="", rc=0, wait=None):
        self.stdout = io.StringIO(output)
        self.rc = rc
        self._wait = wait
        self.terminated = False

    def wait(self):
        return self._wait() if self._wait else self.rc

    def terminate(self):
        self.terminated = True


Call = namedtuple("Call", "script args timeout")
Spawn = namedtuple("Spawn", "script args env_extra")


class MissingReply(BaseException):
    """用例没给这条命令的回答或输出。继承 BaseException 是有意的：`_work()` 里
    `except Exception` 会把普通异常收成「这一步失败」，夹具漏配就会伪装成引擎报错。"""


class FakeRunner:
    """假 Runner：用例只描述「这条命令返回什么」，子进程怎么起由真 Runner 自己管。

    runs 给 run()：("输出", "错误输出", 返回码)、要抛出的异常，或 (script, *args) -> 这两者之一的函数。
    spawns 给 spawn()：按调用顺序交出的 FakeProc；不给（None）时每次 spawn 都是一个空输出、返回 0
    的 proc——竞态类用例只关心交错点，不关心输出。
    on_spawn 在 spawn 返回之前回调（无参数），给「停止 / 暂停恰好落在 spawn 与登记之间」这类时序用。
    run_calls / spawn_calls 记下客户端请它跑过什么（Call / Spawn）；procs 是交出去的 proc。
    """

    def __init__(self, runs=None, spawns=None, on_spawn=None):
        self.runs = runs
        self.spawns = None if spawns is None else list(spawns)
        self.on_spawn = on_spawn
        self.run_calls = []
        self.spawn_calls = []
        self.procs = []

    def run(self, script, *args, timeout=180):
        self.run_calls.append(Call(script, args, timeout))
        reply = self.runs(script, *args) if callable(self.runs) else self.runs
        if reply is None:
            raise MissingReply(f"用例没有给这条命令的回答：{script} {args}")
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def spawn(self, script, *args, env_extra=None):
        self.spawn_calls.append(Spawn(script, args, env_extra))
        if self.spawns is None:
            proc = FakeProc()
        else:
            if not self.spawns:
                raise MissingReply(f"用例没有给这条命令的输出：{script} {args}")
            proc = self.spawns.pop(0)
        self.procs.append(proc)
        if self.on_spawn:
            self.on_spawn()
        return proc


def fake_adb(case):
    """adb-less 机器上让用例走到目标分支（#438）：adb 解析统一替换成假路径。

    `run.adb()` 是 `adb_link.adb_path()` 的薄封装，Connection 在 `adb_path()`
    落空时才去找真二进制，所以这一个 patch 点覆盖 run / chan_fast / Connection
    三条路。adb 解析本身由 test_adb_link 守着；这里的用例只关心分派与引擎分支，
    不关心装没装 adb。返回的 patcher 已 start，并挂到 case 的 cleanup 上。
    """
    from unittest.mock import patch

    load_tool()
    import adb_link

    patcher = patch.object(adb_link, "adb_path", return_value="adb")
    patcher.start()
    case.addCleanup(patcher.stop)


class GitRepo:
    """临时 git 仓：写提交、按范围跑一个校验脚本、读回退出码与输出（两条提交校验共用）。

    全局 git 配置必须绕开：本机装了 commit-msg 钩子，测试仓得写得进未签署、无前缀的提交。
    """

    def __init__(self, name="Rikki", email="rikki@example.com"):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        config = self.dir / "gitconfig"
        config.write_text("", encoding="utf-8")
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1", HOME=str(self.dir))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", name)
        self.git("config", "user.email", email)
        self._count = 0

    def cleanup(self):
        self._tmp.cleanup()

    def git(self, *args, author_email=None):
        env = self.env if author_email is None else dict(self.env, GIT_AUTHOR_EMAIL=author_email)
        done = subprocess.run(["git", *args], cwd=self.dir, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", check=True)
        return done.stdout.strip()

    def commit(self, subject, body=None, author_email=None):
        """写一个有内容的提交（空提交会被 git 拒绝），返回它的 sha。"""
        self._count += 1
        name = f"{self._count}.txt"
        (self.dir / name).write_text(name, encoding="utf-8")
        self.git("add", name)
        args = ["commit", "-q", "-m", subject]
        if body:
            args += ["-m", body]
        self.git(*args, author_email=author_email)
        return self.git("rev-parse", "HEAD")

    def run(self, script, *args, env_extra=None):
        """跑一个校验脚本，返回 (退出码, stdout + stderr)。参数原样交给脚本。"""
        done = subprocess.run([sys.executable, str(script), *args], cwd=self.dir,
                              env=dict(self.env, **(env_extra or {})),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        return done.returncode, done.stdout + done.stderr
