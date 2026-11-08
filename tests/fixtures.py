"""纯重构要「改前改后对拍」时用的现成材料：页面样本、假时钟、按时间轴换页的假设备、假 Phone、假 Runner。

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
import contextlib
import io
import re
import sys
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


def install_clock(module, clock):
    """把这个时钟装进 fast / chan_fast：两个模块各自 import 了 time，要分别换。"""
    module.time = clock
    return clock


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

    声明在 `Phone.__init__` 里的状态在这里补默认值，和构造处保持一致——只有一处例外：
    `pause_at_lock_check` 默认 False，因为假手机后面没有客户端在点「暂停」。
    屏尺寸 `W` / `H` 与读屏 adapter `d` 不设默认：它们是每条用例的前提，由调用方传。
    """
    if fast_mod is None:
        load_tool()
        import fast as fast_mod
    p = fast_mod.Phone.__new__(fast_mod.Phone)
    p.link = fast_mod.adb_link.Connection(serial, transport=shell or _silent_shell)
    p.log, p.miss, p.changed, p.missed, p.promoted = False, 0, [], [], set()
    p.app = ""
    p.pause_at_lock_check = False
    p.systemui_text, p.vivo_seen, p.safe_mode = False, False, False
    p.skeleton_sigs, p.skeleton_count = set(), 0
    p.mismatch_probes = 0
    for name, value in fields.items():
        setattr(p, name, value)
    return p


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
    """
    if fast_mod is None:
        load_tool()
        import fast as fast_mod
    p = Mock(name="Phone")
    p.pause_at_lock_check, p.systemui_text, p.vivo_seen, p.safe_mode = False, False, False, False
    p.lost = False              # Phone 上这是代理 link 的属性，Mock 上没有：不补就恒为真
    p.missed = []               # `report_run()` 读它：Mock 恒真会把干净的一轮判成失败（#788）
    p.skeleton_sigs, p.skeleton_count = set(), 0
    p.mismatch_probes = 0
    p.reader = p.d = Mock(name="reader")
    for name, value in fields.items():
        setattr(p, name, value)
    return p


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


def fake_phone(clock=None, size=SIZES[0], stages=((0.0, EMPTY_PAGE),),
               focus=((0.0, ""),), fast_mod=None, **fields):
    """造一个不连手机的 Phone：读屏走时间轴，点击 / 返回只推进假时钟。

    只替掉会碰手机的部分；tree / sig / settle 等仍是真的，走 Device.dump_hierarchy。
    要换掉别的属性（想断言点击的坐标、想固定 locked）用关键字传进来，形如
    fake_phone(locked=lambda: True)。
    """
    clock = clock or Clock()
    timeline = Timeline(stages, focus)
    device = Device(timeline, size, clock)
    p = phone_stub("fake", shell=device.shell, fast_mod=fast_mod)
    p.W, p.H = size
    p.d = device
    p.focus = lambda: timeline.focus_at(clock.t)
    p.click = lambda *a, **k: clock.click()
    p.back = lambda *a, **k: clock.click()
    p.say = lambda *a, **k: None
    p.dismiss = lambda *a, **k: None
    p.type_text = lambda text, *a, **k: (clock.click(), True)[1]
    p.scroll = lambda *a, **k: None
    p.scroll_more = lambda *a, **k: False
    p.locked = lambda *a, **k: False
    p.wait_unlocked = lambda *a, **k: True
    for name, value in fields.items():
        setattr(p, name, value)
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
