"""后台屏：执行期间把引擎的开页面、点按、读屏都改到一块虚拟屏上，用户照常用主屏（#618）。

屏由 Kotlin 的 Vd 以 shell 身份建（经 Shizuku 用 app_process 起），这里负责起停，并把发往手机的命令改写成
发到这块屏：引擎与机型脚本不知道有两块屏，只看见「一块屏」。建不了屏（安卓 12 以下、系统不给 shell 建屏）
就不启用，引擎照旧在主屏上跑。
"""
import re
import threading
import time

from . import bridge

PID_FILE = "/data/local/tmp/aac-vd.pid"
LOG_FILE = "/data/local/tmp/aac-vd.log"
NAME = "aac-bg"
ALWAYS_UNLOCKED = 1 << 12       # Vd.java 的标记：降级档可能没有它，那时这块屏照样会被锁


class Screen:
    def __init__(self, display, sf, flags=0):
        self.display = display      # 安卓的显示编号：am start --display、input -d、dumpsys 分段都用它
        self.sf = sf                # SurfaceFlinger 的编号：screencap -d 只认这个
        self.flags = flags          # Vd 建屏时实际用上的标记（它打印的 flags=0x…）
        self.holders = 0            # 有几个入口正借这块屏：最后一个用完才拆
        self.lost = False           # Vd 中途退出、屏已不在：之后发往它的命令直接报错（#662）

    @property
    def unlocked(self):
        return bool(self.flags & ALWAYS_UNLOCKED)


active = None
starting = False                # 正在建屏：界面问「在哪块屏上跑」时要等这个落到 False 才有结论
_lock = threading.RLock()       # 建屏 / 借屏 / 还屏互斥：两个入口同时建，后建的清残留会拆掉先建的（#662）
LOST = "后台屏意外关闭（建屏进程已退出），这一步无法继续"


def _size(b):
    """主屏的逻辑尺寸与密度（有覆盖值取覆盖值）：后台屏同尺寸，机型脚本按屏幕比例找按钮的判断不受影响。"""
    size = b.exec("wm size", None, 10).out.decode()
    dens = b.exec("wm density", None, 10).out.decode()
    w, h = map(int, (re.findall(r"(\d+)x(\d+)", size) or [("0", "0")])[-1])
    dpi = int((re.findall(r"(\d+)", dens) or ["0"])[-1])
    return w, h, dpi


def _discard():
    """拆掉 Vd。不复位 `active`：调用方自己决定那块屏还算不算数。"""
    b = bridge.get()
    b.stop_daemon("vd")
    b.exec(f"[ -f {PID_FILE} ] && kill $(cat {PID_FILE}) 2>/dev/null; rm -f {PID_FILE}", None, 10)


def _reclaim():
    """上一次进程被杀时没走到 stop()：PID_FILE 里的 Vd 还常驻，那块同名屏要等它死了才消失。
    建新屏前先清掉并等 SurfaceFlinger 里没有它——不等就会把旧屏的编号当成新屏的。"""
    b = bridge.get()
    left = b.exec(f"[ -f {PID_FILE} ] && echo yes", None, 10).out.strip() == b"yes"
    _discard()
    if not left:
        return
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        dump = b.exec("dumpsys SurfaceFlinger --displays", None, 10).out.decode("utf-8", "replace")
        if f'name="{NAME}"' not in dump:
            return
        time.sleep(0.2)


def _build(package):
    """建一块屏；建不了返回 None。"""
    _reclaim()                      # 先清残留：这一步之后的任何早退都不该把旧 Vd 留在屏上
    b = bridge.get()
    paths = b.exec(f"pm path {package}", None, 10).out.decode()
    apk = next((line[len("package:"):].strip() for line in paths.splitlines() if line.endswith("base.apk")), "")
    w, h, dpi = _size(b)
    if not apk or not (w and h and dpi):
        return None
    b.exec(f"rm -f {LOG_FILE}", None, 10)
    b.daemon("vd", f"echo $$ > {PID_FILE}; CLASSPATH={apk} exec app_process / com.ahuamiao.adcleaner.Vd "
                   f"{w} {h} {dpi} > {LOG_FILE} 2>&1")
    display, flags = None, 0
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        m = re.search(r"DISPLAY (-?\d+)(?: flags=0x([0-9a-fA-F]+))?",
                      b.exec(f"cat {LOG_FILE} 2>/dev/null", None, 5).out.decode())
        if m:
            display, flags = int(m.group(1)), int(m.group(2) or "0", 16)
            break
        time.sleep(0.2)
    sf = None
    if display is not None and display >= 0:
        dump = b.exec("dumpsys SurfaceFlinger --displays", None, 10).out.decode("utf-8", "replace")
        m = re.search(r"Virtual Display (\d+)\s*\n\s*name=\"" + NAME + "\"", dump)
        sf = m.group(1) if m else None
    if display is None or display < 0 or sf is None:
        _discard()
        return None
    return Screen(display, sf, flags)


def start(package):
    """建屏并启用改写；建不了返回 None（调用方照旧用主屏）。
    已经有一块在跑就借给它：建第二块会在拆除时把第一块连带拆掉，也没必要有两块。用完调 `release()`。"""
    global active, starting
    with _lock:
        if active is not None and not active.lost:
            active.holders += 1
            return active
        if active is not None:          # 上一块已经没了：拆干净再建
            stop()
        starting = True
        try:
            built = _build(package)
        finally:
            starting = False
        if built is not None:
            built.holders = 1
            active = built
        return built


def release():
    """一个入口用完这块屏了：还有别处借着的就留着，最后一个走的拆掉。"""
    with _lock:
        if active is None:
            return
        active.holders -= 1
        if active.holders <= 0:
            stop()


def stop():
    """拆屏：屏上开着的页面随之关闭（建屏时带 DESTROY_CONTENT_ON_REMOVAL）。"""
    global active
    with _lock:
        active = None
        _discard()


def dead():
    """建屏进程还在不在。发往后台屏的命令失败时才问，不每条命令都问。

    先 echo 一个哨兵：通道自己断了（或探测超时）时 out 是空的，不能据此判屏死——
    那样通道恢复后也会一直拒发，整段执行报「后台屏意外关闭」。"""
    b = bridge.get()
    r = b.exec(f"echo probe; [ -f {PID_FILE} ] && kill -0 $(cat {PID_FILE}) 2>/dev/null && echo up", None, 10)
    return b"probe" in r.out and b"up" not in r.out


# 只会作用到主屏的命令，后台屏下不发：
# HOME——后台屏没有桌面，发了把用户正在用的 App 送回桌面；WAKEUP——后台屏不睡，点亮的是主屏；
# 收起通知栏——后台屏没有通知栏，收起的是用户的
SKIP = re.compile(r"\binput keyevent (?:--longpress )?(?:KEYCODE_)?(?:HOME|WAKEUP|3|224)\b|\bcmd statusbar collapse\b")
NEW_TASK, MULTIPLE_TASK = 0x10000000, 0x08000000


def _new_task(m):
    """后台屏上开页面一律另开一份（MULTIPLE_TASK）：同一个 App 正开在主屏上时，安卓默认把那个任务整个搬到
    后台屏，用户眼前的页面就没了。"""
    return f"{m.group(1)}0x{int(m.group(2), 16) | NEW_TASK | MULTIPLE_TASK:08x}"


def _section(source, header, display):
    """`dumpsys window displays` / `dumpsys activity activities` 里只留第 display 块屏的那一段。"""
    return f"{source} | awk '/{header}/{{on=($0 ~ /{header}{display}[ (]/ || $0 ~ /{header}{display}$/)}} on'"


def rewrite(cmd):
    """把一条 shell 命令改成发到后台屏。没启用后台屏时原样返回。"""
    s = active
    if s is None:
        return cmd
    n = s.display
    cmd = SKIP.sub("true", cmd)
    if re.search(r"\bam start(?=\s)(?! --display)", cmd):
        cmd = re.sub(r"(\bam start\s[^;|&]*?-f )(0x[0-9a-fA-F]+)", _new_task, cmd)
        cmd = re.sub(r"\bam start(?=\s)(?![^;|&]*-f 0x)", f"am start -f 0x{NEW_TASK | MULTIPLE_TASK:08x}", cmd)
        cmd = re.sub(r"\bam start(?=\s)(?! --display)", f"am start --display {n}", cmd)
    cmd = re.sub(r"\binput (?!-d )(?=(?:tap|swipe|keyevent|text|draganddrop|motionevent|keycombination)\b)",
                 f"input -d {n} ", cmd)
    cmd = re.sub(r"\bscreencap(?! -d)", f"screencap -d {s.sf}", cmd)
    # 查前台、查锁屏：只看后台屏那一段。屏带 ALWAYS_UNLOCKED 时替它答「没锁」；降级档没这个标记，
    # 这块屏自己会被锁，就按它那段照实读
    lock = "; echo '  isKeyguardShowing=false'" if s.unlocked else ""
    cmd = re.sub(r"\bdumpsys window(?= *\|)",
                 "{ " + _section("dumpsys window displays", "Display: mDisplayId=", n) + lock + "; }", cmd)
    cmd = re.sub(r"\bdumpsys activity activities(?= *\|)", _section("dumpsys activity activities", "^Display #", n), cmd)
    return cmd
