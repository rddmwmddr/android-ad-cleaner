"""失败现场：这一屏的 dump 原文落到客户端的 `captures/` 下，事后不必再要一台设备就能回放。

root 由调用方给 —— 客户端走 `AAC_CAPTURES`，与备份目录、暂停文件同一套通道。root 为空时
一个字节都不写：源码态直接跑 `tool/run.py` 不产生任何文件。

一个段只留最新一份现场，目录名 `<任务>-<段>`，同一段重跑会覆盖。`meta.json` 记当时的宽高：
回放时 `Screen.on_screen` 按它过滤屏外节点，缺了会把折叠屏内屏那份节点也算进来（沿用 #2）。
产物不进日志、不随上报发送，也不自动清理 —— 体积由 `run.py captures` 报给人，手动清。
"""
import datetime
import json
import os

ENV = "AAC_CAPTURES"
PAGE = "page.xml"
META = "meta.json"

# 目录名里不能出现的字符：路径分隔符会让段名跑出 captures/，Windows 的冒号等写不进去。
_BAD = set('<>:"/\\|?*')


def root_from_env():
    """客户端把 `AAC_CAPTURES` 传给子进程；源码态直接跑 `tool/run.py` 时没有它。"""
    return os.environ.get(ENV)


def slug(text):
    """任务 / 段名到目录名的一段：换掉路径分隔符与控制字符，空串用 `-`。"""
    out = "".join("_" if ch in _BAD or ord(ch) < 32 else ch for ch in str(text))
    return out.strip(" .") or "-"


def human_size(n):
    """字节数给人看：`512 B` / `2.0 KB` / `3.4 MB`。"""
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Captures:
    """一次运行的现场目录。`task` / `step` 在进入任务与段时填，两处留现场按它归档。"""

    def __init__(self, root):
        self.root = os.fspath(root) if root else ""
        self.task = ""
        self.step = ""

    @property
    def dir(self):
        """这一段的现场目录；没给 root 时是空串（调用方据此一个字节都不写）。"""
        if not self.root:
            return ""
        return os.path.join(self.root, f"{slug(self.task)}-{slug(self.step)}")

    def save(self, page, size=None, when=None):
        """把这一屏原文写进 `dir`，返回目录；没给 root 或写不进去返回 None。

        写不进去不算失败：这是失败路径上的诊断，不能把原来那句报错盖掉。"""
        folder = self.dir
        if not folder or not page:
            return None
        w, h = size or (0, 0)
        meta = {"w": w, "h": h, "task": self.task, "step": self.step,
                "at": (when or datetime.datetime.now()).isoformat(timespec="seconds")}
        try:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, PAGE), "w", encoding="utf-8", newline="") as f:
                f.write(page)
            with open(os.path.join(folder, META), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
        except (OSError, ValueError):       # 写中文路径时的编码错也是 ValueError
            return None
        return folder

    def usage(self):
        """(文件数, 总字节数)：给「由人手动清」报体积用。读不动的条目跳过。"""
        count = total = 0
        for top, _, files in os.walk(self.root) if self.root else ():
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(top, name))
                except OSError:
                    continue
                count += 1
        return count, total
