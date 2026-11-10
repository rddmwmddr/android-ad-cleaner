"""读屏会话：同一电脑同一设备互斥，退出前释放本次启动的服务。

依赖 uiautomator2 3.7.1 的进程句柄；只关闭自己持有的 adb 流，不杀设备上的其他进程。
"""
import atexit
import hashlib
import sys
from pathlib import Path
import tempfile
import time
from typing import Any

import uiautomator2 as u2

import events
from uiautomator2.core import _http_request
from uiautomator2.exceptions import AccessibilityServiceAlreadyRegisteredError, HTTPError


class DeviceBusyError(RuntimeError):
    pass


class DeviceLock:
    def __init__(self, serial, wait=20):
        # 不用序列号做文件名；不删除锁文件，避免另一个进程锁住不同 inode。
        name = hashlib.sha256(serial.encode("utf-8")).hexdigest()
        directory = Path(tempfile.gettempdir()) / "android-ad-cleaner-locks"
        directory.mkdir(exist_ok=True)
        self.file = open(directory / (name + ".lock"), "a+b")
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b"0"); self.file.flush()
        # 上一步的读屏进程可能还在退出：等它释放，最多 20 秒（错误日志 10-27：下一步一开始就报占用）。
        deadline = time.time() + wait
        while True:
            self.file.seek(0)
            try:
                # 平台判据写成 sys.platform 而不是 os.name：mypy 只认前者，Linux 上会把
                # Windows-only 的 msvcrt 分支整段剪掉，否则类型检查读不到那个模块的方法。
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as e:
                if time.time() < deadline:
                    time.sleep(0.5)
                    continue
                self.file.close()
                events.emit("ui_busy")
                raise DeviceBusyError("本电脑另一个去广告任务正在使用这台手机的读屏服务，请结束该任务后重试。") from e

    def close(self):
        if not self.file.closed:
            if sys.platform == "win32":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()  # POSIX close 同时释放 flock


class ManagedDevice(u2.Device):
    # 上游 `Device` 在这里解析不到类型（uiautomator2 没有 stub），进程句柄只能自己声明；
    # 赋值仍归上游 `launch()`，复用来的服务没有属于我们的那份，保持 None。
    _process: Any

    def __init__(self, serial):
        self._session_lock = DeviceLock(serial)
        try:
            super().__init__(serial)
        except BaseException:
            self.close()
            raise
        # 上游默认 wait=False；改为先等本次服务退出，再释放跨进程锁。
        atexit.unregister(self.stop_uiautomator)
        atexit.register(self.close)

    def _check_alive(self):
        try:
            return _http_request(self._dev, self._device_server_port, "GET", "/ping", timeout=1).content == b"pong"
        except (HTTPError, OSError):
            return False

    def stop_uiautomator(self, wait=True):
        with self._lock:
            process = self._process
            if process is None:
                return  # 复用的服务没有属于我们的句柄，不能停止它
            process.kill()  # 仅关闭本次 launch 返回的 adb 流，最多等待 3 秒
            if process.pool() is None:
                raise RuntimeError("本次读屏进程未退出，停止重连；请退出客户端并重启手机后重试。")
            self._process = None
        deadline = time.monotonic() + 5
        while self._check_alive():
            if time.monotonic() >= deadline:
                raise RuntimeError("本次读屏服务未释放，停止重连；请退出客户端并重启手机后重试。")
            time.sleep(.2)

    def start_uiautomator(self):
        for attempt in range(2):
            try:
                return super().start_uiautomator()
            except BaseException as error:
                # __init__ 失败时上游尚未注册 atexit，也必须关闭失败的启动流。
                self.stop_uiautomator()
                if not isinstance(error, AccessibilityServiceAlreadyRegisteredError) or attempt:
                    raise
                # Android 的 Binder 注销可能略晚于进程退出，只给短暂竞争一次重试。
                time.sleep(1)

    def close(self):
        try:
            if getattr(self, "_process", None) is not None:
                self.stop_uiautomator()
        finally:
            self._session_lock.close()
            atexit.unregister(self.close)


def connect(serial):
    return ManagedDevice(serial)
