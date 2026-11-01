"""纯重构要「改前改后对拍」时用的现成材料：页面样本、假时钟、按时间轴换页的假设备、假 Phone。

CODING_STANDARDS.md 要求纯重构给出对拍证据，页面样本取 tests/ 里所有 <hierarchy>、至少两种屏尺寸。
以前每做一次同类重构都要现场把这四样东西重搭一遍，现在 import 一下就有：

    from fixtures import EMPTY_PAGE, SIZES, all_pages, drive
    for label, xml in all_pages():
        for size in SIZES:
            print(label, size, drive(lambda p: p.settle("", 1.0), size=size,
                                     stages=[(0.0, EMPTY_PAGE), (0.2, xml)]))

写新测试不要用它 —— 测试要照实现之外的事实断言，夹具是为了让两份实现吃同一份输入。
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

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
    p.log, p.miss, p.changed = False, 0, []
    p.pause_at_lock_check = False
    p.systemui_text, p.vivo_seen, p.safe_mode = False, False, False
    p.skeleton_sigs, p.skeleton_count = set(), 0
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
    `vivo_seen`）在真实方法里会被当成 True；`d` 与 `reader` 也会变成两个不相干的 Mock，而
    `Phone.start` 这类内部走 `reader`、配方脚本走 `p.d`。这里只补这两件事，其余照旧交给 Mock
    （`changed` 保持 Mock，用例可以数 `.append` 的次数）。
    """
    if fast_mod is None:
        load_tool()
        import fast as fast_mod
    p = Mock(name="Phone")
    p.pause_at_lock_check, p.systemui_text, p.vivo_seen, p.safe_mode = False, False, False, False
    p.skeleton_sigs, p.skeleton_count = set(), 0
    p.reader = p.d = Mock(name="reader")
    for name, value in fields.items():
        setattr(p, name, value)
    return p


def _silent_shell(command, timeout=None):
    """没给 shell 时的传输：什么也不做，返回空输出。"""
    return SimpleNamespace(output="", exit_code=0)


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
