"""手机上的读屏库：代替 uiautomator2 / adbutils / tool/ui_session.py。

读屏走本 App 自己的命令服务（ShellServer，shell 身份，UiAutomation 读所有屏的窗口），经 bridge 调用，
不开网络端口（#623 第 1 项：以前借用的 u2.jar 读屏服务在 9008 端口对局域网开放、无鉴权）。
点按、按键、截图走 shell 命令（input / screencap），后台屏启用时由 screen.rewrite 改到那块屏；
选择器在拿到的页面上本地匹配。接口只做引擎与机型脚本用到的那部分
（见 tool/reader.py 与 recipes 里的 p.d(...)）。

Selector 的字段与掩码照抄 uiautomator2（MIT）。
"""
import io
import re
import shlex
import sys
import time
import types
import warnings
import xml.etree.ElementTree as ET

from . import bridge, screen

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


def display():
    """读屏要问的屏：后台屏启用时是它，否则主屏 0。后台屏已经没了就直接报错（#674）——
    读屏不经 `bridge.exec()`，少了那里的早退判断，再发过去只会拿到一条看不出原因的读屏失败。"""
    s = screen.active
    if s is not None and s.lost:
        raise read_failed("读屏", screen.LOST.encode())
    return s.display if s is not None else 0


def text_of(raw):
    return raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")


def read_failed(what, err):
    """读屏失败报到引擎：带上命令服务给的原因，别让它只剩一句「没找到」。"""
    message = text_of(err).strip() or f"{what}失败"
    if "already registered" in message.lower() or "AlreadyRegistered" in message:
        return AccessibilityServiceAlreadyRegisteredError(message)
    return UiAutomationError(message)


class _Rpc:
    """d.jsonrpc.方法名(参数…, http_timeout=秒)：引擎只用到下面这几个。

    写字不经读屏（UiAutomation 按选择器写字的接口各版本不一），抛错让引擎退到剪贴板 + 粘贴；
    剪贴板由 App 自己写。清空输入框在这里自己做：点进去、全选、删掉。
    """

    def __init__(self, device=None):
        self.device = device

    def setText(self, *a, **k):
        raise RPCUnknownError(-32001, "不经读屏写字，改用剪贴板粘贴", "setText")

    def clearTextField(self, selector, http_timeout=10):
        obj = UiObject(self.device, selector)
        node = obj._found_node("clearTextField")
        obj.click()
        select_all(self.device, node)
        return self.device.shell("input keyevent KEYCODE_DEL")

    def setClipboard(self, label, text, http_timeout=10):
        bridge.get().set_clipboard(text)

    def deviceInfo(self, http_timeout=10):
        w, h = self.device.window_size()
        return {"displayWidth": w, "displayHeight": h, "displayRotation": 0}

    def __getattr__(self, method):
        def call(*a, **k):
            raise RPCUnknownError(-32601, f"手机版读屏不支持 {method}", method)
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


# 选择器字段 → 页面节点属性（本地匹配用）
ATTR = {"text": "text", "description": "content-desc", "className": "class", "packageName": "package",
        "resourceId": "resource-id"}
FLAGS = {"checkable": "checkable", "checked": "checked", "clickable": "clickable", "longClickable": "long-clickable",
         "scrollable": "scrollable", "enabled": "enabled", "focusable": "focusable", "focused": "focused",
         "selected": "selected"}


def matches(node, selector):
    """一个页面节点是否满足选择器（只认引擎与机型脚本用到的字段，未知字段一律不匹配）。"""
    for key, want in selector.items():
        if key in ("mask", "childOrSibling", "childOrSiblingSelector", "instance"):
            continue
        if key in ATTR:
            ok = (node.get(ATTR[key]) or "") == want
        elif key in FLAGS:
            ok = (node.get(FLAGS[key]) == "true") == bool(want)
        elif key.endswith("Matches") and key[:-7] in ATTR:
            ok = re.fullmatch(want, node.get(ATTR[key[:-7]]) or "") is not None
        elif key.endswith("Contains"):
            ok = want in (node.get(ATTR[key[:-8]]) or "")
        elif key.endswith("StartsWith"):
            ok = (node.get(ATTR[key[:-10]]) or "").startswith(want)
        elif key == "index":
            ok = node.get("index") == str(want)
        else:
            return False
        if not ok:
            return False
    return True


def bounds_of(node):
    l, t, r, b = map(int, re.findall(r"-?\d+", node.get("bounds") or "[0,0][0,0]"))
    return l, t, r, b


def select_all(device, node):
    """把输入框里的字全选上：`input keycombination` 要 Android 11+，
    更老的系统上退回按当前文字长度逐字删（与全选后删一次等价）。"""
    if device.shell("input keycombination 113 29").exit_code == 0:      # Ctrl+A
        return
    for _ in range(len(node.get("text") or "")):
        device.shell("input keyevent KEYCODE_DEL")


class UiObject:
    """p.d(resourceId=…) 之类的选择器：在当前屏的页面上自己匹配。"""

    def __init__(self, device, selector):
        self.device, self.selector, self.jsonrpc = device, selector, device.jsonrpc

    def _node(self):
        root = ET.fromstring(self.device.dump_hierarchy())
        found = [n for n in root.iter("node") if matches(n, self.selector)]
        i = self.selector.get("instance", 0)
        return found[i] if i < len(found) else None

    def _found_node(self, method):
        """取节点；找不到按 uiautomator2 的方式抛，机型脚本靠这个类型判断。"""
        node = self._node()
        if node is None:
            raise UiObjectNotFoundError({"code": -32002, "data": str(self.selector), "method": method})
        return node

    def __getitem__(self, instance):
        selector = self.selector.clone()
        selector["instance"] = instance
        obj = UiObject(self.device, selector)
        if not obj.exists:
            raise IndexError(instance)
        return obj

    def wait(self, exists=True, timeout=None):
        """读屏读超时不抛，只 warn 并回落一次查询——与 uiautomator2 的 wait() 一致。
        机型脚本的 click_exists 只捕 UiObjectNotFoundError，异常穿透会让整段中止而不是跳过。"""
        timeout = self.device.wait_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        try:
            while True:
                if (self._node() is not None) == exists:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.3)
        except DeviceError as e:
            warnings.warn(f"wait readTimeout: {e}", RuntimeWarning)
        try:
            return self.exists if exists else not self.exists
        except DeviceError:
            return False

    @property
    def exists(self):
        return self._node() is not None

    def must_wait(self, exists=True, timeout=None):
        if not self.wait(exists, timeout):
            raise UiObjectNotFoundError({"code": -32002, "data": str(self.selector), "method": "wait"})

    @property
    def info(self):
        node = self._found_node("info")
        return {"text": node.get("text") or "", "contentDescription": node.get("content-desc") or "",
                "bounds": dict(zip(("left", "top", "right", "bottom"), bounds_of(node))),
                "packageName": node.get("package") or "", "className": node.get("class") or ""}

    def bounds(self):
        return bounds_of(self._found_node("bounds"))

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
        """点进输入框、全选、粘贴（或删掉）。"""
        self.must_wait(timeout=timeout)
        node = self._found_node("setText")
        self.click()
        select_all(self.device, node)
        if not text:
            return self.device.shell("input keyevent KEYCODE_DEL")
        self.jsonrpc.setClipboard(None, text)
        return self.device.shell("input keyevent KEYCODE_PASTE")

    send_keys = set_text

    def get_text(self, timeout=None):
        self.must_wait(timeout=timeout)
        return self._found_node("getText").get("text") or ""


class ShellResponse:
    def __init__(self, output, exit_code):
        self.output, self.exit_code = output, exit_code

    def __iter__(self):
        return iter((self.output, self.exit_code))


# pressKey 的键名 → 安卓键码名（一律走 input keyevent）
KEYS = {"home": "KEYCODE_HOME", "back": "KEYCODE_BACK", "enter": "KEYCODE_ENTER", "menu": "KEYCODE_MENU",
        "search": "KEYCODE_SEARCH", "delete": "KEYCODE_DEL", "del": "KEYCODE_DEL", "recent": "KEYCODE_APP_SWITCH",
        "up": "KEYCODE_DPAD_UP", "down": "KEYCODE_DPAD_DOWN", "left": "KEYCODE_DPAD_LEFT",
        "right": "KEYCODE_DPAD_RIGHT", "center": "KEYCODE_DPAD_CENTER", "power": "KEYCODE_POWER"}


class Device:
    """读屏会话。命令服务随 App 常驻，读屏第一次用到时它自己连 UiAutomation，没有要起停的服务。"""

    def __init__(self, serial=None):
        self.serial = serial
        self.jsonrpc = _Rpc(self)
        self.settings = {"operation_delay": (0, 0), "operation_delay_methods": ["click", "swipe"],
                         "wait_timeout": 20.0, "max_depth": 50}
        self.wait_timeout = 20.0
        self.dump_hierarchy()       # 连上先读一次：命令服务或 UiAutomation 起不来就当场报出原因

    def close(self):
        pass

    stop_uiautomator = close

    # ----- Reader -----
    def shell(self, cmdargs, timeout=60):
        if isinstance(cmdargs, (list, tuple)):
            cmdargs = " ".join(shlex.quote(str(a)) for a in cmdargs)
        r = bridge.get().exec(cmdargs, None, timeout or 60)
        if r.timed_out:
            raise AdbShellError(f"shell timeout: {cmdargs[:80]}")
        return ShellResponse(text_of(r.out + r.err), r.code)

    def dump_hierarchy(self, compressed=False, pretty=False, max_depth=None):
        t = time.monotonic()
        r = bridge.get().dump(display())
        bridge.slow("dump", t)
        if r.code != 0:
            raise read_failed("读屏", r.err)
        return text_of(r.out) or EMPTY_XML

    def window_size(self):
        r = bridge.get().size(display())
        if r.code != 0:
            raise read_failed("问屏幕尺寸", r.err)
        w, h = (text_of(r.out).split() + ["0", "0"])[:2]
        return int(w), int(h)

    @property
    def info(self):
        return self.jsonrpc.deviceInfo()

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

    # 点按、按键一律走 input（后台屏启用时 shell 改写成 input -d 屏号）
    def click(self, x, y):
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, fx, fy, tx, ty, duration=None, steps=None):
        steps = int(duration * 200) if duration else (steps or 55)
        return self.shell(f"input swipe {int(fx)} {int(fy)} {int(tx)} {int(ty)} {max(2, steps) * 5}")

    def press(self, key, meta=None):
        code = key if isinstance(key, int) else KEYS.get(str(key).lower(), f"KEYCODE_{str(key).upper()}")
        return self.shell(f"input keyevent {code}")

    def __call__(self, **selectors):
        return UiObject(self, Selector(**selectors))


def connect(serial=None):
    return Device(serial)


class DeviceBusyError(RuntimeError):
    pass


def install():
    """把本模块登记成 uiautomator2 / adbutils / ui_session：引擎的 import 拿到的都是这里的实现。"""
    me = sys.modules[__name__]
    exceptions = types.ModuleType("uiautomator2.exceptions")
    for name, value in vars(me).items():
        if isinstance(value, type) and issubclass(value, Exception):
            setattr(exceptions, name, value)
    core = types.ModuleType("uiautomator2.core")

    def _http_request(*a, **k):
        raise RPCUnknownError(-32601, "手机版没有读屏 HTTP 服务", "_http_request")
    core._http_request = _http_request

    u2 = types.ModuleType("uiautomator2")
    u2.Device, u2.connect, u2.exceptions, u2.core = Device, connect, exceptions, core
    adbutils = types.ModuleType("adbutils")
    adbutils.AdbError = AdbError
    session = types.ModuleType("ui_session")
    session.connect, session.DeviceBusyError, session.ManagedDevice = connect, DeviceBusyError, Device
    sys.modules.update({"uiautomator2": u2, "uiautomator2.exceptions": exceptions, "uiautomator2.core": core,
                        "adbutils": adbutils, "ui_session": session})
