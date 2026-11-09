"""下载状态仍由 gui.updates 管；这里只把已校验的 APK 交给系统安装器。"""
import json


class AndroidInstaller:
    def __init__(self, native):
        self.native = native

    def install(self, path, version):
        result = json.loads(str(self.native.installUpdate(str(path), version)))
        if result.get("error"):
            raise RuntimeError(result["error"])
        return {"exit": False, "message": result.get("message", "请在系统界面确认安装")}
