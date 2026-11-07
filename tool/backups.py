"""备份目录：命名、扫描、`<型号>-gui` 兜底各只有一处。

root 由调用方给 —— 客户端是 `<数据目录>/backups`，命令行是 `AAC_BACKUPS` 或仓库根的 `backups/`。
这里不读环境变量、不认得客户端，否则客户端进程（没有 `AAC_BACKUPS`）会算到仓库根上去。
"""
import datetime
import os


def root_from_env():
    """客户端把 `AAC_BACKUPS` 传给子进程；源码态直接跑 `tool/run.py` 时没有它。"""
    return os.environ.get("AAC_BACKUPS")


class Backups:
    def __init__(self, root):
        self.root = os.fspath(root)

    def all(self, model):
        """这个型号的所有目录，最近的在前。含 `<型号>-gui`：它按名字排在带时间的快照后面，所以算最新。
        `latest()` / `newest_with()` / `snapshot()` 都吃这个顺序，别改成按时间戳排。"""
        try:
            hits = sorted((d for d in os.listdir(self.root) if d.startswith(model + "-")), reverse=True)
        except FileNotFoundError:
            return []
        return [os.path.join(self.root, d) for d in hits]

    def latest(self, model):
        """最近一份备份，没有则 None。按名字排序取最后一个，所以 `<型号>-gui` 优先于带时间的目录。"""
        dirs = self.all(model)
        return dirs[0] if dirs else None

    def newest_with(self, model, name):
        """带某个文件的最近一份备份里的该文件，没有则 None。`<型号>-gui` 按名字排在快照后面，
        却没有快照里的文件，所以不能先取 latest() 再找文件。"""
        for d in self.all(model):
            f = os.path.join(d, name)
            if os.path.exists(f):
                return f
        return None

    def create(self, model, when=None):
        d = os.path.join(self.root, f"{model}-{(when or datetime.datetime.now()):%Y%m%d-%H%M}")
        os.makedirs(d, exist_ok=True)
        return d

    def snapshot(self, model):
        """本次运行写 channels.tsv 用的目录：最近一份不是 `<型号>-gui` 的备份，一份都没有就新建。
        写进 `<型号>-gui` 的清单会被下一次运行覆盖，还原只能找回最后一批（#651）。两条残留，
        顺带写在这里：新建沿用 `create()` 的分钟粒度，同一分钟内跑两次会落进同一个目录；本次运行的
        备份步骤没跑或失败时不会新建目录，清单会落进上一次运行的目录并覆盖它。"""
        dated = [d for d in self.all(model) if os.path.basename(d) != f"{model}-gui"]
        return dated[0] if dated else self.create(model)

    def gui(self, model):
        """还原用的临时目录：合并历次清单后的 `channels-restore.tsv` 放这里，它不属于某一次运行。"""
        d = os.path.join(self.root, f"{model}-gui")
        os.makedirs(d, exist_ok=True)
        return d
