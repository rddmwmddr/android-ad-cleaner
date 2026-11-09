"""三端共用的更新状态、可信清单与下载校验（#888）。安装由宿主协作者完成。"""
import hashlib
import json
import os
import platform
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

MANIFEST_URL = "https://ahuamiao.com/sites/other/android-ad-cleaner-latest.json"
RELEASE_PAGE = "https://github.com/rddmwmddr/android-ad-cleaner/releases/tag/v"
SOURCES = {
    "gitee": "https://gitee.com/rddmw/android-ad-cleaner/releases/download/v",
    "github": "https://github.com/rddmwmddr/android-ad-cleaner/releases/download/v",
}
SUFFIXES = {"android-arm64": "android-arm64.apk", "mac-arm64": "mac-arm64.dmg",
            "mac-intel": "mac-intel.dmg", "windows": "windows-portable.zip"}
MAX_PACKAGE = 1024 * 1024 * 1024
ACTIVE = {"checking", "downloading", "cancelling", "installing"}


class UpdateError(Exception):
    pass


def _try_lock(stream):
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(stream):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock(path, message):
    """跨进程互斥：拿不到就抛 UpdateError。锁随进程退出由系统释放，锁文件本身保留。"""
    with Path(path).open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if not _try_lock(stream):
            raise UpdateError(message)
        try:
            yield
        finally:
            _unlock(stream)


class Cancelled(UpdateError):
    pass


class HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise UpdateError("更新下载被重定向到不安全的地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_https(request, timeout=30):
    if urllib.parse.urlsplit(request.full_url).scheme != "https":
        raise UpdateError("更新地址必须使用 HTTPS")
    return urllib.request.build_opener(HttpsRedirect()).open(request, timeout=timeout)


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d{1,4}\.\d{1,4}\.\d{1,4}", value):
        raise UpdateError("更新清单里的版本号无效")
    return tuple(map(int, value.lstrip("v").split(".")))


def platform_id(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Windows" and machine in ("amd64", "x86_64", "arm64", "aarch64"):
        return "windows"
    if system == "Darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-intel" if machine == "x86_64" else ""
    return ""


def artifact(data, target):
    """只接收本产品、指定版本和平台的固定文件名；清单不能指挥下载别的程序。"""
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise UpdateError("这个版本尚未提供应用内更新，请从官网下载")
    version_tuple(data.get("version"))
    version = data["version"].lstrip("v")
    if target not in SUFFIXES:
        raise UpdateError("当前平台暂不支持应用内安装")
    rows = data.get("artifacts")
    row = rows.get(target) if isinstance(rows, dict) else None
    if not isinstance(row, dict):
        raise UpdateError("这个版本还没有本平台的更新包")
    name = f"AndroidAdCleaner-{version}-{SUFFIXES[target]}"
    if row.get("file") != name:
        raise UpdateError("更新包的名称与版本、平台不一致")
    size = row.get("size")
    if type(size) is not int or not 0 < size <= MAX_PACKAGE:
        raise UpdateError("更新包大小无效")
    sha = row.get("sha256", "")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError("更新包缺少有效的 SHA256 校验值")
    urls = {key: prefix + version + "/" + name for key, prefix in SOURCES.items()}
    if row.get("sources") != urls:
        raise UpdateError("更新包地址不是本产品的官方发布地址")
    return {"version": version, "file": name, "size": size, "sha256": sha, "sources": urls}


def verify_file(path, row):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != row["size"]:
        raise UpdateError("安装包不完整，请重新下载")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != row["sha256"]:
        raise UpdateError("安装包校验失败，请重新下载")


class Updates:
    """每次只跑一个更新操作；快照给两个界面，网络和安装不在界面线程里跑。"""

    def __init__(self, current, root, installer, *, target=None, source="gitee", opener=None,
                 claim=None, release=None, save_source=None):
        self.current = current
        self.root = Path(root)
        self.target = platform_id() if target is None else target
        self.installer = installer
        self.opener = opener or open_https
        self.claim = claim or (lambda: "")
        self.release = release or (lambda: None)
        self.save_source = save_source or (lambda source: None)
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.worker = None
        self.offer = None
        self.path = None
        self.state = {"state": "idle", "current": current, "version": "", "source": source if source in SOURCES else "gitee",
                      "received": 0, "size": 0, "message": "", "error": ""}
        try:
            previous = json.loads((self.root / "last-result.json").read_text(encoding="utf-8"))
            if previous.get("ok") is False:
                self.state["previous_error"] = previous.get("error", "上次更新没有完成")
        except (OSError, ValueError, AttributeError):
            pass

    def snapshot(self):
        with self.lock:
            out = dict(self.state)
            out["busy"] = out["state"] in ACTIVE
            out["can_download"] = bool(self.offer and out["state"] not in ACTIVE)
            out["can_install"] = bool(self.path and out["state"] not in ACTIVE)
            out["can_cancel"] = out["state"] == "downloading"
            out["notes_url"] = RELEASE_PAGE + out["version"] if out["version"] else ""
            return out

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def _start(self, state, fn):
        with self.lock:
            if self.worker and self.worker.is_alive() or self.state["state"] == "installing":
                return self.snapshot()
            self.cancelled.clear()
            self.state.update(state=state, error="", message="")
            self.worker = threading.Thread(target=self._work, args=(fn,), daemon=True)
            self.worker.start()
            return self.snapshot()

    def _work(self, fn):
        try:
            fn()
        except Cancelled:
            self._set(state="available", received=0, message="已取消下载")
        except Exception as exc:
            self._set(state="error", error=str(exc) or "更新没有完成，请重试")

    def check(self):
        return self._start("checking", self._check)

    def _check(self):
        with self.lock:
            self.offer = self.path = None
            self.state.update(version="", received=0, size=0)
        request = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": f"AndroidAdCleaner/{self.current}"})
        with self.opener(request, timeout=15) as response:
            raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise UpdateError("更新清单过大")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise UpdateError("更新清单无效")
        latest = data.get("version", "")
        if version_tuple(latest) <= version_tuple(self.current):
            with self.lock:
                self.offer = self.path = None
                self.state.update(state="current", version="", received=0, size=0, message="已是最新版本")
            return
        row = artifact(data, self.target)
        with self.lock:
            self.offer, self.path = row, None
            self.state.update(state="available", version=row["version"], size=row["size"], received=0)

    def download(self, source="gitee"):
        if source not in SOURCES:
            return {"error": "请选择 Gitee 或 GitHub 下载渠道"}
        with self.lock:
            if self.state["state"] in ACTIVE:
                return self.snapshot()
            if not self.offer:
                return {"error": "请先检查更新"}
            self.save_source(source)
            self.state["source"] = source
            return self._start("downloading", self._download)

    def _download(self):
        with self.lock:
            row, source = dict(self.offer), self.state["source"]
            self.path = None
        self.root.mkdir(parents=True, exist_ok=True)
        # 两个窗口会写同一个 .part：后完成的那份会把已经校验过的成品再写坏。
        with file_lock(self.root / "download.lock", "另一个窗口正在下载更新，等它完成后再试"):
            self._fetch(row, source)

    def _fetch(self, row, source):
        destination = self.root / row["file"]
        partial = self.root / (row["file"] + ".part")
        # 不跟随已有软链接；下载不触碰程序目录或备份目录。
        if partial.is_symlink() or destination.is_symlink():
            raise UpdateError("更新目录里有异常链接，请清理更新缓存后重试")
        self._set(received=0)
        try:
            request = urllib.request.Request(row["sources"][source], headers={"User-Agent": f"AndroidAdCleaner/{self.current}"})
            with self.opener(request, timeout=30) as response, partial.open("wb") as output:
                size = 0
                digest = hashlib.sha256()
                while True:
                    if self.cancelled.is_set():
                        raise Cancelled()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > row["size"]:
                        raise UpdateError("下载大小与发布清单不一致")
                    output.write(chunk)
                    digest.update(chunk)
                    self._set(received=size)
                output.flush()
                os.fsync(output.fileno())
            if self.cancelled.is_set():
                raise Cancelled()
            if size != row["size"] or digest.hexdigest() != row["sha256"]:
                raise UpdateError("下载不完整或校验失败，请重试或切换渠道")
            os.replace(partial, destination)
            with self.lock:
                self.path = destination
                self.state.update(state="ready", message="下载完成，校验通过")
        finally:
            partial.unlink(missing_ok=True)

    def cancel(self):
        with self.lock:
            if self.state["state"] == "downloading":
                self.cancelled.set()
                self.state["state"] = "cancelling"
            return self.snapshot()

    def install(self):
        with self.lock:
            if not self.path or not self.offer:
                return {"error": "请先下载更新"}
            return self._start("installing", self._install)

    def _install(self):
        error = self.claim()
        if error:
            raise UpdateError(error)
        handed_off = False
        try:
            try:
                verify_file(self.path, self.offer)
            except UpdateError:
                with self.lock:
                    self.path = None
                raise
            result = self.installer.install(self.path, self.offer["version"])
            handed_off = bool(result.get("exit"))
            self._set(state="installing" if handed_off else "ready", message=result.get("message", ""))
            if handed_off:
                try:
                    self.installer.close()
                except Exception:
                    handed_off = False
                    self.installer.abort()
                    raise
        finally:
            if not handed_off:
                self.release()
