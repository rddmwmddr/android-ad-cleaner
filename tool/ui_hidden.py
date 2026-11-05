"""本机「UI 未暴露」渠道名单：渠道在 dumpsys 里有，系统却没把它放到应用通知页上（#576）。

chan-off 遇到「页面打得开、页面上确实没有这一行、App 通知没被整体关闭」时记一条，
chan-scan 读这份名单把这些渠道排除在外，只报一句计数 —— 否则每轮都在同一个页面失败，
真实失败被噪音盖住。

存放位置跟备份目录同一个 root（客户端是 `<数据目录>/backups`，命令行是 `AAC_BACKUPS`
或仓库根的 `backups/`），按型号分文件：换一台手机不该被另一台的名单误伤。
换系统或 App 升级后渠道可能重新暴露，所以整份名单可以删掉重建（scan --reset）。
"""
import os

PREFIX = "ui-hidden-"


class UiHidden:
    def __init__(self, root, model):
        self.root, self.model = os.fspath(root), model or ""

    @property
    def available(self):
        return bool(self.model)

    @property
    def path(self):
        return os.path.join(self.root, PREFIX + self.model + ".tsv")

    def load(self):
        """{(包名, 渠道 ID)}。文件不在、读不动都按空名单处理：这一份只影响扫描的噪音。"""
        if not self.available:
            return set()
        try:
            with open(self.path, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except (OSError, ValueError):
            return set()
        keys = set()
        for line in lines:
            pk, sep, cid = line.partition("\t")
            if sep and pk.strip() and cid.strip() and not pk.lstrip().startswith("#"):
                keys.add((pk.strip(), cid.strip()))
        return keys

    def remember(self, keys):
        """追加没记过的渠道，返回这次新增的条数。写不进去不算失败：只影响下一轮扫描的噪音。"""
        if not self.available:
            return 0
        known = self.load()
        new = []
        for pk, cid in keys:
            key = (pk.strip(), cid.strip())
            if key[0] and key[1] and key not in known:
                known.add(key)
                new.append(key)
        if not new:
            return 0
        try:
            os.makedirs(self.root, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                for pk, cid in new:
                    f.write(f"{pk}\t{cid}\n")
        except OSError:
            return 0
        return len(new)

    def clear(self):
        try:
            os.remove(self.path)
        except OSError:
            pass
