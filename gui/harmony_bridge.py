"""#898：窗口桥上的鸿蒙入口。按需装配 `HarmonyClient` 并转发，状态不落在 `Api` 上。

`Api.harmony()` 只把桥表参数转给这里；鸿蒙清单与 HDC 仍要等到第一次真正使用才加载，
安卓宿主不因为多这一层而提前加载鸿蒙模块。
"""
import threading


class HarmonyBridge:
    def __init__(self, root, claim, release, enabled, factory=None):
        self.root = root
        self.claim = claim
        self.release = release
        self.enabled = enabled
        self.factory = factory
        self.service = None
        self.lock = threading.Lock()

    def _build(self):
        with self.lock:
            if self.service is None:
                factory = self.factory
                if factory is None:
                    try:
                        from .harmony_client import HarmonyClient
                    except ImportError:
                        from harmony_client import HarmonyClient
                    factory = HarmonyClient
                self.service = factory(self.root, self.claim, self.release)
            return self.service

    def command(self, action, serial="", mode="clean", segments=None):
        return self._build().command(action, serial, mode, segments)

    def close_if_idle(self):
        """没建过服务时按空闲处理，窗口可以直接关。"""
        service = self.service
        return True if service is None else service.close_if_idle()

    def close_when_done(self, callback):
        service = self.service
        if service is None:
            callback()
        else:
            service.close_when_done(callback)
