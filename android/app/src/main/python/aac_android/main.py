"""手机版入口：把桌面版的后台（gui/app.py 的 Api）原样搬进 App 进程，Compose 界面经 call() 调它。

boot() 由 AacApp 在后台线程调用一次；之后界面的每次调用都落到 call()：普通方法名是 Api 上的方法，
`view.xxx` 是 view.py 里给界面准备好的判断。
"""
import json
import os
import sys
import threading
import time
import traceback

from . import adb, bridge, inproc, screen, u2, view

API = None
_ready = threading.Event()


class _Native:
    """Kotlin 的 Native；电脑上调试时没有 Java，换成打印。"""

    def __getattr__(self, name):
        try:
            from java import jclass
            return getattr(jclass("com.ahuamiao.adcleaner.Native"), name)
        except ImportError:
            return lambda *a: print(f"[native] {name}{a}", file=inproc._fallback[1])


native = _Native()


BACKGROUND = True        # 优先在后台屏上执行（#618）；建不了屏自动退回主屏


def visible(package, on, text=""):
    """执行期间显示悬浮胶囊：小米 HyperOS 会冻结退到后台的 App，前台服务和省电白名单都挡不住（18 Pro Max 实测），
    有可见窗口的不冻。悬浮窗权限经 Shizuku 给本 App 自己开，不用用户去设置里找。"""
    if on:
        bridge.get().exec(f"appops set {package} SYSTEM_ALERT_WINDOW allow", None, 10)
    native.capsule(on, text)


def mode():
    """界面问「这次在哪块屏上跑」：建屏还没出结论时 deciding 为真，界面接着问；background 时执行页
    告诉用户可以照常用手机。"""
    return {"background": screen.active is not None, "deciding": screen.starting}


def was_stopped(job):
    """用户点了「停止」：`_work()` 是正常返回的，只能靠 Job 上这个标记认出来。"""
    return bool(job is not None and job.cancel)


class Session:
    """一次「在后台替用户点手机」的会话：后台屏、前台服务、悬浮胶囊、结束通知一起开、一起收（#662）。

    以前三样各管各的：后台屏按引用计数，前台服务和胶囊只有开 / 关，两个入口叠在一起时，先结束的那个
    把还在跑的那个的保活撤掉（小米会冻结它）。现在按进入次数计数，最后一个离开的才收；
    执行与还原本身由 `Dispatcher.claim()` 互斥，这里是第二道保险。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.count = 0
        self.background = False

    def enter(self, package, action):
        with self.lock:
            self.count += 1
            if self.count > 1:
                return self.background
            try:
                self.background = BACKGROUND and screen.start(package) is not None
                native.busy(True, self.background)
                visible(package, True, f"肉呆{action}中（后台）" if self.background else f"肉呆{action}中")
            except BaseException:
                # 半路失败不能把计数留在 1：之后每次执行都会走 count > 1 的早退分支，保活与胶囊就再也不开了
                self.count -= 1
                self.background = False
                # 拆屏要碰通道，断线时它自己会抛：保活与屏幕锁仍要撤（#746）
                try:
                    visible(package, False)
                    screen.release()
                except Exception:
                    pass
                try:
                    native.busy(False, False)
                except Exception:
                    pass
                raise
            return self.background

    def leave(self, package):
        """返回这一次是不是最后一个离开（是的话保活已撤、屏已拆）。"""
        with self.lock:
            self.count -= 1
            if self.count > 0:
                return False
            try:
                visible(package, False)
                if self.background:
                    screen.release()
            finally:
                # 拆屏要碰通道，断线时它会抛：保活与屏幕锁仍要撤，否则断线后两样都留着（#746）
                native.busy(False, self.background)
            return True


SESSION = Session()


def in_front(fn, package, action, stopped=None):
    """fn 运行期间开前台服务、显示悬浮胶囊（不被冻结），能建后台屏就在后台屏上跑。
    结束时：主屏模式回到本 App 看结果（App 自己在后台启动界面会被系统拦，shell 身份的 am start 不受限）；
    后台模式不抢前台（用户可能正在用别的 App），发通知——做完了 / 用户停止 / 出错三种结果文案不同，
    一律发「做完了」会让停止和失败看起来都像成功。"""
    def run(*a, **k):
        bg = SESSION.enter(package, action)
        title, text = f"{action}失败", "点这里查看原因"
        try:
            out = fn(*a, **k)
            title = "已停止" if stopped is not None and stopped() else f"{action}做完了"
            text = "点这里查看结果"
            return out
        finally:
            if SESSION.leave(package):
                if bg:
                    native.done(title, text)
                else:
                    r = bridge.get().exec(f"am start -n {package}/.MainActivity", None, 10)
                    if r.code:
                        native.bringToFront()
    return run


def boot(base, data_dir, cache_dir, package="com.ahuamiao.adcleaner"):
    """base：解出来的 aac/（tool、recipes、gui、images）；data_dir：备份与设置。"""
    global API
    os.environ.setdefault("HOME", data_dir)
    os.environ["TMPDIR"] = cache_dir
    os.environ["AAC_HOST"] = "phone"     # 本进程按手机版说法（tool/host.py，#729）；引擎那份由 ENGINE_HOST 定（#747）
    os.environ.pop("AAC_EVENTS", None)
    if not sys.executable:
        sys.executable = "python3"
    inproc.EXECUTABLE = sys.executable
    inproc.setup(os.path.join(base, "tool"))
    adb.install(os.path.join(data_dir, "bin", "adb"))
    u2.install()
    sys.path.insert(0, os.path.join(base, "gui"))
    os.makedirs(os.path.join(base, "images"), exist_ok=True)   # Api.env() 要列这个目录；手机版不带教程图
    view.BASE = base

    import app
    app.BASE = base
    app.TOOL = os.path.join(base, "tool")
    app.play_sound = lambda path: native.chime(path)
    app.Api.copy_text = lambda self, text: (native.copy(text), True)[1]
    app.Api.open_url = lambda self, url: native.openUrl(url)
    app.Api.open_path = lambda self, which: native.toast("备份在本 App 的私有目录里，卸载 App 会一起删掉")
    app.Api.usb_hint = lambda self: ""
    app.os_name = lambda: "安卓手机版（Shizuku）"      # 错误上报与诊断的「电脑」一栏：和桌面版的报告分开
    app.LINK_LOST = "和手机的调试连接断开了，这一步没有执行。回到本 App 点「重新开始」。"   # #729
    app.TAP_REFUSED = "；本 App 的点击被拒（未开 USB 调试安全设置）"                          # #747
    app.ENGINE_HOST = "phone"                             # child_env() 只认它，不认继承来的 AAC_HOST

    api = app.Api(data_dir, adb=adb.ADB_PATH)
    api.runner = inproc.Runner(api._child_env)
    # 执行与还原都会切到别的 App 的设置页：期间开前台服务保活，结束后回到本 App
    api.dispatcher._work = in_front(api.dispatcher._work, package, "去广告", lambda: was_stopped(api.job))
    # 包在互斥判断里面：执行中点还原会先被 Api.restore() 拒掉，不会先开保活、建屏再拒（#662）
    api._restore_work = in_front(api._restore_work, package, "还原")
    api.run_mode = mode
    API = api
    _ready.set()
    return app.VERSION


def call(method, args_json):
    """界面的一次 api 调用，返回 JSON 字符串：{"ok": 结果} 或 {"error": 文本}。"""
    _ready.wait(60)
    try:
        if method.startswith("_") or API is None:
            raise AttributeError(method)
        args = json.loads(args_json or "[]")
        if method.startswith("view."):
            result = view.EXPORTS[method[len("view."):]](API, *args)
        else:
            result = getattr(API, method)(*args)
        return json.dumps({"ok": result}, ensure_ascii=False, default=str)
    except Exception as e:
        traceback.print_exc(file=inproc._fallback[1])
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def selftest(serial_hint=""):
    """电脑上调试：AAC_BRIDGE_ADB / AAC_BRIDGE_SERIAL 指向模拟器，跑一遍检测，打印耗时。"""
    t = time.time()
    print(call("devices", "[]"))
    print(call("status", json.dumps([adb.SERIAL]))[:600])
    print(f"{time.time() - t:.1f}s")
