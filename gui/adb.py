"""「这台电脑上哪份 adb 能用、从哪来的、手机此刻是否连着」，以及 platform-tools 的下载与校验。

客户端这一域只在这里实现：`gui/app.py` 只剩显式 re-export 与 `Api` 的转发壳。根目录经
`gui/toolpath.py` 取，`tool/adb_link.py` 按需加载——本模块不 import `gui/app.py`。
"""
import hashlib, os, platform, re, subprocess, urllib.request, zipfile

try:                                # 当包导入（测试）；直接跑脚本、打包时它是顶层模块
    from . import toolpath
except ImportError:
    import toolpath

_WINDOWS = platform.system() == "Windows"


def adb_exe():
    return "adb.exe" if _WINDOWS else "adb"


def adb_ok(path):
    """只用 1.0.41 及以上的 adb。手机助手自带的 1.0.32 等旧版会让挂起、快应用等命令失败，
    和新版同时运行还会互相顶掉服务（#25 #75）。"""
    try:
        out = toolpath.tool("adb_link").invoke(path, "version", timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    m = re.search(r"version 1\.0\.(\d+)", out)
    return bool(m) and int(m.group(1)) >= 41


def find_adb(platform_tools, manual=None):
    """手动指定的 adb 排第一：用户填了就是要它压过客户端下载的那份和其他来源（#311）。
    不存在或版本不够的候选由 adb_candidates / adb_ok 跳过，于是自动回退到后面的来源。"""
    last = (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
            "/opt/homebrew/bin/adb", "/usr/local/bin/adb")
    first = tuple(p for p in (manual, os.path.join(platform_tools, adb_exe())) if p)
    for c in toolpath.tool("adb_link").adb_candidates(first=first, last=last):
        if adb_ok(c):
            return c
    return None


def adb_from_input(text):
    """手填或文件对话框给的路径 → adb 可执行文件。目录补上 adb / adb.exe，去掉粘贴时带进来的引号。"""
    path = (text or "").strip().strip("\"'")
    if not path:
        return ""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(path):
        path = os.path.join(path, adb_exe())
    return path


def adb_source(adb, manual, platform_tools):
    """当前生效的这份 adb 从哪来：manual / downloaded / system / none。"""
    if not adb:
        return "none"
    if manual and os.path.normcase(adb) == os.path.normcase(manual):
        return "manual"
    if os.path.normcase(adb) == os.path.normcase(os.path.join(platform_tools, adb_exe())):
        return "downloaded"
    return "system"


def adb_present(adb, serial):
    """手机此刻是否连着（adb 状态为 device）；先给它 10 秒回来。"""
    if not adb:
        return False
    return toolpath.tool("adb_link").Connection(serial, adb=adb).alive(wait=10)


class AdbDownloader:
    """下载并校验 platform-tools（#273）。下载源表、校验、落盘与下载状态都在这里（ADR-0011）。

    固定版本表、镜像表与最新版地址由 `gui/app.py` 构造时传入：那几张表是单一来源，本模块不留副本。
    """

    def __init__(self, data, adb=None, *, version, pinned, mirrors, latest):
        self.data = data
        self.adb = adb
        self.version = version
        self.pinned, self.mirrors, self.latest = pinned, mirrors, latest
        self.dl = {"state": "idle", "pct": 0, "msg": ""}

    def adb_sources(self):
        """[(来源名, 网址, sha256 或 None)]：固定版本两处，最后是官网最新版。"""
        name, digest = self.pinned[platform.system()]
        return [(label, base + name, digest) for label, base in self.mirrors] + \
               [("Google 官网（最新版）", self.latest[platform.system()], None)]

    def _fetch(self, label, url, digest, zp):
        self.dl = {"state": "running", "pct": 0, "msg": f"正在从{label}下载 platform-tools……"}
        h = hashlib.sha256()
        agent = f"AndroidAdCleaner/{self.version}"
        ua = {"User-Agent": agent}   # pragma: no mutate 语义等价：urllib 把 header 名按 capitalize 归一，"user-agent" 与 "USER-AGENT" 落成同一个键
        request = urllib.request.Request(url, headers=ua)
        with urllib.request.urlopen(request, timeout=20) as r, open(zp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0); got = 0
            while True:
                b = r.read(65536)
                if not b:
                    break
                f.write(b); h.update(b); got += len(b)
                if total:
                    self.dl["pct"] = int(got * 100 / total)
        if digest and h.hexdigest() != digest:
            raise ValueError("文件校验不对，可能下载不完整或被改动")

    def _download(self, sources=None):
        self.data.ensure()
        zp = self.data.adb_zip
        errors = []
        try:
            # sources 传 callable：源表构造失败也要被下面这支 except 收成 dl 的 error 状态
            for label, url, digest in (sources or self.adb_sources)():
                try:
                    self._fetch(label, url, digest, zp)
                    break
                except Exception as e:
                    errors.append(f"{label}：{e}")
            else:
                raise RuntimeError("；".join(errors))
            with zipfile.ZipFile(zp) as z:
                z.extractall(self.data.root)
            os.remove(zp)
            adb = os.path.join(self.data.platform_tools, adb_exe())
            if not _WINDOWS:
                os.chmod(adb, 0o755)
            self.adb = adb
            self.dl = {"state": "done", "pct": 100, "msg": "adb 已就绪"}
        except Exception as e:
            self.dl = {"state": "error", "pct": 0, "msg": f"下载失败：{e}"}
            try:
                os.remove(zp)
            except OSError:
                pass

    def download_state(self):
        return self.dl
