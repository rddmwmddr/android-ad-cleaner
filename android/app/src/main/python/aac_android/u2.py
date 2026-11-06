"""手机上的读屏库：代替 uiautomator2 / adbutils / tool/ui_session.py。

读屏服务仍是桌面版那一个 u2.jar（uiautomator2 3.7.1 自带），经 Shizuku 以 shell 身份启动，
本 App 直接连手机本机的 9008 端口发 jsonrpc；命令走 bridge。接口只做引擎与机型脚本用到的那部分
（见 tool/reader.py 与 recipes 里的 p.d(...)）。

Selector 的字段与掩码照抄 uiautomator2（MIT），服务端按这张表解析选择器。
"""
import io
import json
import shlex
import sys
import threading
import time
import types
import urllib.error
import urllib.request

from . import bridge

REMOTE_JAR = "/data/local/tmp/u2.jar"
PID_FILE = "/data/local/tmp/aac-u2.pid"
LOG_FILE = "/data/local/tmp/aac-u2.log"
LOCAL_JAR = ""              # install() 时定下：App 私有目录里那份 u2.jar
EMPTY_XML = '<?xml version=\'1.0\' encoding=\'UTF-8\' standalone=\'yes\' ?>\r\n<hierarchy rotation="0" />'


# ---------- 异常：名字与继承关系与 uiautomator2 / adbutils 一致，引擎按类型判断 ----------
class BaseError(Exception):
    pass


class DeviceError(BaseError): ...
class AdbShellError(DeviceError): ...
class ConnectError(DeviceError): ...
class HTTPError(DeviceError): ...
class HTTPTimeoutError(HTTPError): ...
class UiAutomationError(DeviceError): ...
class UiAutomationNotConnectedError(UiAutomationError): ...
class LaunchUiAutomationError(UiAutomationError): ...
class AccessibilityServiceAlreadyRegisteredError(UiAutomationError): ...
class RPCError(BaseError): ...
class RPCUnknownError(RPCError): ...
class RPCInvalidError(RPCError): ...
class HierarchyEmptyError(RPCError): ...
class NormalError(RPCError): ...
class UiObjectNotFoundError(NormalError): ...
class AdbError(Exception): ...


# 代理一律不走：电脑上调试时本机可能开着 Surge 一类的系统代理
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http(method, path, data=None, timeout=10):
    t = time.monotonic()
    try:
        return _http_once(method, path, data, timeout)
    finally:
        bridge.slow(f"rpc {path} {(data or {}).get('method', '')}", t)


def _http_once(method, path, data, timeout):
    url = f"http://127.0.0.1:{bridge.get().server_port()}{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"}, method=method)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise HTTPError(f"HTTP request failed: {e.code} {e.reason}") from e
    except TimeoutError as e:
        raise HTTPTimeoutError(f"HTTP request timeout: {e}") from e
    except (urllib.error.URLError, OSError) as e:
        raise HTTPError(f"Unable to connect to uiautomator2 server: {e}") from e


def _ping():
    try:
        return _http("GET", "/ping", timeout=2) == b"pong"
    except HTTPError:
        return False


class _Rpc:
    """d.jsonrpc.方法名(参数…, http_timeout=秒)，与 uiautomator2 同一种写法。"""

    def __getattr__(self, method):
        def call(*params, http_timeout=10):
            payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)}
            raw = _http("POST", "/jsonrpc/0", payload, timeout=http_timeout)
            try:
                data = json.loads(raw)
            except ValueError as e:
                raise RPCInvalidError("Unknown RPC error: not json") from e
            if not isinstance(data, dict):
                raise RPCInvalidError("Unknown RPC error: not a dict")
            if "error" in data:
                message = str(data["error"].get("message", ""))
                text = raw.decode("utf-8", "replace")
                if "UiAutomation not connected" in text or "DeadObjectException" in message:
                    raise UiAutomationNotConnectedError(message)
                if "UiObjectNotFoundException" in message:
                    raise UiObjectNotFoundError(data["error"].get("code"), message, params)
                raise RPCUnknownError(data["error"].get("code"), message, method)
            return data.get("result")
        return call


class Selector(dict):
    _fields = {
        "text": (0x01, None), "textContains": (0x02, None), "textMatches": (0x04, None),
        "textStartsWith": (0x08, None), "className": (0x10, None), "classNameMatches": (0x20, None),
        "description": (0x40, None), "descriptionContains": (0x80, None), "descriptionMatches": (0x0100, None),
        "descriptionStartsWith": (0x0200, None), "checkable": (0x0400, False), "checked": (0x0800, False),
        "clickable": (0x1000, False), "longClickable": (0x2000, False), "scrollable": (0x4000, False),
        "enabled": (0x8000, False), "focusable": (0x010000, False), "focused": (0x020000, False),
        "selected": (0x040000, False), "packageName": (0x080000, None), "packageNameMatches": (0x100000, None),
        "resourceId": (0x200000, None), "resourceIdMatches": (0x400000, None), "index": (0x800000, 0),
        "instance": (0x01000000, 0),
    }

    def __init__(self, **kwargs):
        super().__setitem__("mask", 0)
        super().__setitem__("childOrSibling", [])
        super().__setitem__("childOrSiblingSelector", [])
        for k, v in kwargs.items():
            self[k] = v

    def __setitem__(self, k, v):
        if k not in self._fields:
            raise ReferenceError(f"{k} is not allowed.")
        super().__setitem__(k, v)
        super().__setitem__("mask", self["mask"] | self._fields[k][0])

    def clone(self):
        return Selector(**{k: v for k, v in self.items() if k in self._fields})


class UiObject:
    def __init__(self, device, selector):
        self.device, self.selector, self.jsonrpc = device, selector, device.jsonrpc

    def __getitem__(self, instance):
        selector = self.selector.clone()
        selector["instance"] = instance
        obj = UiObject(self.device, selector)
        if not obj.exists:
            raise IndexError(instance)
        return obj

    def wait(self, exists=True, timeout=None):
        timeout = self.device.wait_timeout if timeout is None else timeout
        method = self.jsonrpc.waitForExists if exists else self.jsonrpc.waitUntilGone
        return bool(method(self.selector, int(timeout * 1000), http_timeout=timeout + 10))

    @property
    def exists(self):
        return bool(self.jsonrpc.exist(self.selector))

    def must_wait(self, exists=True, timeout=None):
        if not self.wait(exists, timeout):
            raise UiObjectNotFoundError({"code": -32002, "data": str(self.selector), "method": "wait"})

    @property
    def info(self):
        return self.jsonrpc.objInfo(self.selector)

    def bounds(self):
        b = self.info.get("visibleBounds") or self.info.get("bounds")
        return b["left"], b["top"], b["right"], b["bottom"]

    def center(self):
        lx, ly, rx, ry = self.bounds()
        return (lx + rx) / 2, (ly + ry) / 2

    def click(self, timeout=None):
        self.must_wait(timeout=timeout)
        self.device.click(*self.center())

    def click_exists(self, timeout=0):
        try:
            self.click(timeout=timeout)
            return True
        except UiObjectNotFoundError:
            return False

    def set_text(self, text, timeout=None):
        self.must_wait(timeout=timeout)
        if not text:
            return self.jsonrpc.clearTextField(self.selector)
        return self.jsonrpc.setText(self.selector, text)

    send_keys = set_text

    def get_text(self, timeout=None):
        self.must_wait(timeout=timeout)
        return self.jsonrpc.getText(self.selector)


class ShellResponse:
    def __init__(self, output, exit_code):
        self.output, self.exit_code = output, exit_code

    def __iter__(self):
        return iter((self.output, self.exit_code))


class Device:
    """读屏会话。只停自己起的服务；另一个会话（电脑上的客户端）起的服务照常复用，不动它。"""
    _lock = threading.Lock()

    def __init__(self, serial=None):
        self.serial = serial
        self.jsonrpc = _Rpc()
        self.settings = {"operation_delay": (0, 0), "operation_delay_methods": ["click", "swipe"],
                         "wait_timeout": 20.0, "max_depth": 50}
        self.wait_timeout = 20.0
        self.owned = False
        self._start()

    # ----- 服务 -----
    def _push_jar(self):
        b = bridge.get()
        with open(LOCAL_JAR, "rb") as f:
            data = f.read()
        size = b.exec(f"stat -c %s {REMOTE_JAR} 2>/dev/null", None, 10).out.decode().strip()
        if size != str(len(data)):
            r = b.exec(f"cat > {REMOTE_JAR}", data, 60)
            if r.code:
                raise AdbError(f"push u2.jar failed: {r.err.decode('utf-8', 'replace')}")

    def _start(self):
        with Device._lock:
            if _ping() and self._connected():
                return
            self._push_jar()
            b = bridge.get()
            b.exec(f"rm -f {LOG_FILE}", None, 10)
            cmd = (f"echo $$ > {PID_FILE}; CLASSPATH={REMOTE_JAR} exec app_process / com.wetest.uia2.Main "
                   f"-p {bridge.U2_PORT} > {LOG_FILE} 2>&1")
            b.daemon("u2", cmd)
            self.owned = True
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if _ping() and self._connected():
                    return
                time.sleep(0.3)
            log = b.exec(f"tail -c 2000 {LOG_FILE}", None, 10).out.decode("utf-8", "replace")
            self._stop_owned()
            if "already registered" in log or "AlreadyRegistered" in log:
                raise AccessibilityServiceAlreadyRegisteredError(log[-400:])
            raise LaunchUiAutomationError("读屏服务没有启动：" + (log[-400:] or "无输出"))

    def _connected(self):
        try:
            return bool(self.jsonrpc.deviceInfo(http_timeout=5))
        except (HTTPError, RPCError, UiAutomationError):
            return False

    def _stop_owned(self):
        b = bridge.get()
        b.stop_daemon("u2")
        b.exec(f"[ -f {PID_FILE} ] && kill $(cat {PID_FILE}) 2>/dev/null; rm -f {PID_FILE}", None, 10)
        self.owned = False

    def close(self):
        with Device._lock:
            if self.owned:
                self._stop_owned()

    stop_uiautomator = close

    # ----- Reader -----
    def shell(self, cmdargs, timeout=60):
        if isinstance(cmdargs, (list, tuple)):
            cmdargs = " ".join(shlex.quote(str(a)) for a in cmdargs)
        r = bridge.get().exec(cmdargs, None, timeout or 60)
        if r.timed_out:
            raise AdbShellError(f"shell timeout: {cmdargs[:80]}")
        return ShellResponse((r.out + r.err).decode("utf-8", "replace"), r.code)

    def dump_hierarchy(self, compressed=False, pretty=False, max_depth=None):
        content = self.jsonrpc.dumpWindowHierarchy(compressed, max_depth or self.settings["max_depth"],
                                                   http_timeout=30)
        return content or EMPTY_XML

    def window_size(self):
        info = self.jsonrpc.deviceInfo(http_timeout=10)
        return info["displayWidth"], info["displayHeight"]

    @property
    def info(self):
        return self.jsonrpc.deviceInfo(http_timeout=10)

    def screenshot(self, filename=None, format="pillow"):
        from PIL import Image
        r = bridge.get().exec("screencap -p", None, 30)
        # 带背屏的机型（小米 18 Pro Max）会先打一行「Multiple displays」警告：从 PNG 文件头截起
        start = r.out.find(b"\x89PNG")
        image = Image.open(io.BytesIO(r.out[max(start, 0):])).convert("RGB")
        if filename:
            image.save(filename)
        return image

    def app_stop(self, package):
        self.shell(["am", "force-stop", package])

    def click(self, x, y):
        self.jsonrpc.click(int(x), int(y))

    def swipe(self, fx, fy, tx, ty, duration=None, steps=None):
        steps = int(duration * 200) if duration else (steps or 55)
        return self.jsonrpc.swipe(int(fx), int(fy), int(tx), int(ty), max(2, steps))

    def press(self, key, meta=None):
        if isinstance(key, int):
            return self.jsonrpc.pressKeyCode(key, meta) if meta else self.jsonrpc.pressKeyCode(key)
        return self.jsonrpc.pressKey(key)

    def __call__(self, **selectors):
        return UiObject(self, Selector(**selectors))


def connect(serial=None):
    return Device(serial)


class DeviceBusyError(RuntimeError):
    pass


def cleanup():
    """顶层脚本结束：脚本没走到 close() 就退出时，停掉本次起的读屏服务（桌面版靠子进程退出时的 atexit）。"""
    if bridge._bridge is None:
        return
    b = bridge.get()
    b.stop_daemon("u2")
    if b.exec(f"[ -f {PID_FILE} ] && echo yes", None, 10).out.strip() == b"yes":
        b.exec(f"kill $(cat {PID_FILE}) 2>/dev/null; rm -f {PID_FILE}", None, 10)


def install(local_jar):
    """把本模块登记成 uiautomator2 / adbutils / ui_session：引擎的 import 拿到的都是这里的实现。"""
    global LOCAL_JAR
    LOCAL_JAR = local_jar
    me = sys.modules[__name__]
    exceptions = types.ModuleType("uiautomator2.exceptions")
    for name, value in vars(me).items():
        if isinstance(value, type) and issubclass(value, Exception):
            setattr(exceptions, name, value)
    core = types.ModuleType("uiautomator2.core")
    core._http_request = lambda dev, port, method, path, data=None, timeout=10, **_: _http(method, path, data, timeout)
    u2 = types.ModuleType("uiautomator2")
    u2.Device, u2.connect, u2.exceptions, u2.core = Device, connect, exceptions, core
    adbutils = types.ModuleType("adbutils")
    adbutils.AdbError = AdbError
    session = types.ModuleType("ui_session")
    session.connect, session.DeviceBusyError, session.ManagedDevice = connect, DeviceBusyError, Device
    sys.modules.update({"uiautomator2": u2, "uiautomator2.exceptions": exceptions, "uiautomator2.core": core,
                        "adbutils": adbutils, "ui_session": session})
