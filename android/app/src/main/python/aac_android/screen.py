"""后台屏：执行期间把引擎的开页面、点按、读屏都改到一块虚拟屏上，用户照常用主屏（#618）。

屏由 Kotlin 的 Vd 以 shell 身份建（经 Shizuku 用 app_process 起），这里负责起停，并把发往手机的命令改写成
发到这块屏：引擎与机型脚本不知道有两块屏，只看见「一块屏」。建不了屏（安卓 12 以下、系统不给 shell 建屏）
就不启用，引擎照旧在主屏上跑。
"""
import re
import time

from . import bridge

PID_FILE = "/data/local/tmp/aac-vd.pid"
LOG_FILE = "/data/local/tmp/aac-vd.log"
NAME = "aac-bg"


class Screen:
    def __init__(self, display, sf):
        self.display = display      # 安卓的显示编号：am start --display、input -d、dumpsys 分段都用它
        self.sf = sf                # SurfaceFlinger 的编号：screencap -d 只认这个


active = None


def _size(b):
    """主屏的逻辑尺寸与密度（有覆盖值取覆盖值）：后台屏同尺寸，机型脚本按屏幕比例找按钮的判断不受影响。"""
    size = b.exec("wm size", None, 10).out.decode()
    dens = b.exec("wm density", None, 10).out.decode()
    w, h = map(int, (re.findall(r"(\d+)x(\d+)", size) or [("0", "0")])[-1])
    dpi = int((re.findall(r"(\d+)", dens) or ["0"])[-1])
    return w, h, dpi


def start(package):
    """建屏并启用改写；建不了返回 None（调用方照旧用主屏）。"""
    global active
    b = bridge.get()
    paths = b.exec(f"pm path {package}", None, 10).out.decode()
    apk = next((line[len("package:"):].strip() for line in paths.splitlines() if line.endswith("base.apk")), "")
    w, h, dpi = _size(b)
    if not apk or not (w and h and dpi):
        return None
    b.exec(f"rm -f {LOG_FILE}", None, 10)
    b.daemon("vd", f"echo $$ > {PID_FILE}; CLASSPATH={apk} exec app_process / com.ahuamiao.adcleaner.Vd "
                   f"{w} {h} {dpi} > {LOG_FILE} 2>&1")
    display = None
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        m = re.search(r"DISPLAY (-?\d+)", b.exec(f"cat {LOG_FILE} 2>/dev/null", None, 5).out.decode())
        if m:
            display = int(m.group(1))
            break
        time.sleep(0.2)
    sf = None
    if display is not None and display >= 0:
        dump = b.exec("dumpsys SurfaceFlinger --displays", None, 10).out.decode("utf-8", "replace")
        m = re.search(r"Virtual Display (\d+)\s*\n\s*name=\"" + NAME + "\"", dump)
        sf = m.group(1) if m else None
    if display is None or display < 0 or sf is None:
        stop()
        return None
    active = Screen(display, sf)
    return active


def stop():
    """拆屏：屏上开着的页面随之关闭（建屏时带 DESTROY_CONTENT_ON_REMOVAL）。"""
    global active
    active = None
    b = bridge.get()
    b.stop_daemon("vd")
    b.exec(f"[ -f {PID_FILE} ] && kill $(cat {PID_FILE}) 2>/dev/null; rm -f {PID_FILE}", None, 10)


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
    # 查前台、查锁屏：只看后台屏那一段；后台屏不锁（ALWAYS_UNLOCKED），主屏锁了照样跑
    cmd = re.sub(r"\bdumpsys window(?= *\|)",
                 "{ " + _section("dumpsys window displays", "Display: mDisplayId=", n) + "; echo '  isKeyguardShowing=false'; }",
                 cmd)
    cmd = re.sub(r"\bdumpsys activity activities(?= *\|)", _section("dumpsys activity activities", "^Display #", n), cmd)
    return cmd
