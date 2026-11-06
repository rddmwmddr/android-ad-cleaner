"""手机版入口：把桌面版的后台（gui/app.py 的 Api）原样搬进 App 进程，界面经 WebView 调它。

boot() 由 MainActivity 在后台线程调用一次；之后界面上每个 api.xxx(...) 都落到 call()。
"""
import json
import os
import sys
import threading
import time
import traceback

from . import adb, bridge, inproc, screen, u2

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
    """界面问「这次在哪块屏上跑」：background 时执行页告诉用户可以照常用手机。"""
    return {"background": screen.active is not None}


def in_front(fn, package):
    """fn 运行期间开前台服务、显示悬浮胶囊（不被冻结），能建后台屏就在后台屏上跑。
    结束时：主屏模式回到本 App 看结果（App 自己在后台启动界面会被系统拦，shell 身份的 am start 不受限）；
    后台模式不抢前台（用户可能正在用别的 App），发通知。"""
    def run(*a, **k):
        bg = BACKGROUND and screen.start(package) is not None
        native.busy(True, bg)
        visible(package, True, "净 去广告中（后台）" if bg else "净 去广告中")
        try:
            return fn(*a, **k)
        finally:
            visible(package, False)
            if bg:
                screen.stop()
            native.busy(False, bg)
            if bg:
                native.done("去广告做完了", "点这里查看结果")
            else:
                r = bridge.get().exec(f"am start -n {package}/.MainActivity", None, 10)
                if r.code:
                    native.bringToFront()
    return run


def boot(base, data_dir, cache_dir, package="com.ahuamiao.adcleaner"):
    """base：解出来的 aac/（tool、recipes、gui、images、u2.jar）；data_dir：备份与设置。"""
    global API
    os.environ.setdefault("HOME", data_dir)
    os.environ["TMPDIR"] = cache_dir
    os.environ.pop("AAC_EVENTS", None)
    if not sys.executable:
        sys.executable = "python3"
    inproc.EXECUTABLE = sys.executable
    inproc.setup(os.path.join(base, "tool"))
    adb.install(os.path.join(data_dir, "bin", "adb"))
    u2.install(os.path.join(base, "u2.jar"))
    inproc.after_run.append(u2.cleanup)
    sys.path.insert(0, os.path.join(base, "gui"))

    import app
    app.BASE = base
    app.TOOL = os.path.join(base, "tool")
    app.play_sound = lambda path: native.chime(path)
    app.Api.copy_text = lambda self, text: (native.copy(text), True)[1]
    app.Api.open_url = lambda self, url: native.openUrl(url)
    app.Api.open_path = lambda self, which: native.toast("备份在本 App 的私有目录里，卸载 App 会一起删掉")
    app.Api.usb_hint = lambda self: ""
    app.os_name = lambda: "安卓手机版（Shizuku）"      # 错误上报与诊断的「电脑」一栏：和桌面版的报告分开

    api = app.Api(data_dir, adb=adb.ADB_PATH)
    api.runner = inproc.Runner(api._child_env)
    # 执行与还原都会切到别的 App 的设置页：期间开前台服务保活，结束后回到本 App
    api.dispatcher._work = in_front(api.dispatcher._work, package)
    api.restore = in_front(api.restore, package)
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
        result = getattr(API, method)(*json.loads(args_json or "[]"))
        return json.dumps({"ok": result}, ensure_ascii=False, default=str)
    except Exception as e:
        traceback.print_exc(file=inproc._fallback[1])
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def stop_service():
    """App 被关掉时：停掉还在跑的读屏服务。"""
    try:
        u2.cleanup()
    except Exception:
        pass


def selftest(serial_hint=""):
    """电脑上调试：AAC_BRIDGE_ADB / AAC_BRIDGE_SERIAL 指向模拟器，跑一遍检测，打印耗时。"""
    t = time.time()
    print(call("devices", "[]"))
    print(call("status", json.dumps([adb.SERIAL]))[:600])
    print(f"{time.time() - t:.1f}s")
