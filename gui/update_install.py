"""桌面更新安装：先准备新程序，旧程序退出后由独立副本替换、启动并等待界面确认。"""
import json
from contextlib import contextmanager
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

try:
    from .updates import UpdateError, file_lock, version_tuple
except ImportError:
    from updates import UpdateError, file_lock, version_tuple

WINDOWS_FILES = ("AndroidAdCleaner.exe", "aac-cli.exe", "AndroidAdCleaner.exe.config", "aac-cli.exe.config", "_internal")
BUNDLE_ID = "com.rddmwmddr.androidadcleaner"
MAX_EXPANDED = 2 * 1024 * 1024 * 1024


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def safe_extract(archive, destination):
    """便携包只接受一层产品目录、普通文件与目录；完整检查后才解压。"""
    with zipfile.ZipFile(archive) as zf:
        entries = zf.infolist()
        if len(entries) > 30000 or sum(x.file_size for x in entries) > MAX_EXPANDED:
            raise UpdateError("更新包解压后的大小异常")
        names = set()
        for info in entries:
            name = info.filename
            parts = PurePosixPath(name).parts
            raw_parts = name.rstrip("/").split("/")
            mode = info.external_attr >> 16
            if (info.orig_filename != name or not parts or parts[0] != "AndroidAdCleaner" or "\\" in name or ":" in name
                    or name.startswith("/") or any(p in ("", "..", ".") or p.rstrip(" .") != p for p in raw_parts)
                    or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise UpdateError("更新包包含不安全的文件路径")
            if len(parts) > 1 and parts[1] not in WINDOWS_FILES:
                raise UpdateError("更新包包含不属于本程序的顶层文件")
            key = name.rstrip("/").casefold()
            if key in names:
                raise UpdateError("更新包包含重复文件")
            names.add(key)
            if any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts):
                raise UpdateError("更新包包含系统保留文件名")
        zf.extractall(destination)
    root = Path(destination) / "AndroidAdCleaner"
    if not all((root / name).is_file() for name in WINDOWS_FILES[:-1]) or not (root / "_internal").is_dir():
        raise UpdateError("更新包缺少程序文件")
    return root


def mac_app(executable):
    path = Path(executable).resolve()
    if path.parent.name != "MacOS" or path.parent.parent.name != "Contents" or path.parent.parent.parent.suffix != ".app":
        raise UpdateError("请从已安装的 App 中更新")
    return path.parent.parent.parent


def bundle_info(path):
    with (Path(path) / "Contents" / "Info.plist").open("rb") as stream:
        return plistlib.load(stream)


def signing_team(path, run=subprocess.run):
    result = run(["/usr/bin/codesign", "-dv", "--verbose=4", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    found = re.search(r"^TeamIdentifier=([A-Z0-9]+)$", result.stderr, re.M)
    if not found:
        raise UpdateError("无法确认应用签名的开发者")
    return found.group(1)


def prepare_mac(archive, destination, installed, version, run=subprocess.run):
    mount = Path(destination) / "mount"
    mount.mkdir()
    attached = False
    try:
        run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(archive)],
            check=True, capture_output=True, timeout=90)
        attached = True
        apps = [p for p in mount.glob("*.app") if p.is_dir() and not p.is_symlink()]
        if len(apps) != 1:
            raise UpdateError("磁盘映像里没有唯一的应用程序")
        app = apps[0]
        info = bundle_info(app)
        if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundleShortVersionString") != version:
            raise UpdateError("应用的标识或版本与更新清单不一致")
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True, capture_output=True, timeout=90)
        run(["/usr/sbin/spctl", "--assess", "--type", "execute", str(app)], check=True, capture_output=True, timeout=90)
        if signing_team(app, run) != signing_team(installed, run):
            raise UpdateError("新旧应用的开发者签名不一致")
        prepared = Path(destination) / installed.name
        run(["/usr/bin/ditto", str(app), str(prepared)], check=True, capture_output=True, timeout=180)
        return prepared
    finally:
        if attached:
            run(["/usr/bin/hdiutil", "detach", str(mount)], check=False, capture_output=True, timeout=30)


def install_cwd(target, platform):
    """替换与启动的工作目录：mac 是 bundle 的父目录，Windows 就是程序目录本身。"""
    return Path(target).parent if platform == "darwin" else Path(target)


def launch_target(target, platform, name):
    """要启动的程序，以及它的 cwd。mac 在 bundle 里、Windows 在程序目录根上。"""
    target = Path(target)
    if platform == "darwin":
        return target / "Contents" / "MacOS" / name, target.parent
    return target / name, target


def target_units(target, platform):
    """一次替换的单元：mac 换整个 bundle，Windows 只换程序自带的五份。"""
    return [Path(target).name] if platform == "darwin" else list(WINDOWS_FILES)


def sweep_stale(root):
    """清掉上次没收尾的准备目录；只动一天前创建的，另一个窗口刚建的那份不能碰。"""
    cutoff = time.time() - 24 * 3600
    for path in Path(root).glob("install-*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                remove_item(path)
        except OSError:
            pass


def _helper_error(work):
    """助手退出前留下的原因；没有就用调用方的通用文案。"""
    try:
        return json.loads((Path(work) / "error.json").read_text(encoding="utf-8")).get("error", "")
    except (OSError, ValueError, AttributeError):
        return ""


def writable(directory):
    try:
        with tempfile.TemporaryFile(dir=directory):
            return True
    except OSError:
        return False


class DesktopInstaller:
    def __init__(self, root, *, system=None, executable=None, frozen=None, close=None, popen=None):
        self.root = Path(root)
        self.system = system or sys.platform
        self.executable = Path(executable or sys.executable).resolve()
        self.frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self.close = close or (lambda: None)
        self.popen = popen or subprocess.Popen
        self.helper = None

    def abort(self):
        if self.helper and self.helper.poll() is None:
            self.helper.terminate()
            try:
                self.helper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.helper.kill()

    def install(self, archive, version):
        if not self.frozen:
            raise UpdateError("源码运行时不替换程序，请更新源码或安装正式版")
        if self.system not in ("darwin", "win32"):
            raise UpdateError("当前平台暂不支持应用内安装")
        target = mac_app(self.executable) if self.system == "darwin" else self.executable.parent
        if self.system == "darwin" and (str(target).startswith("/Volumes/") or "AppTranslocation" in target.parts):
            raise UpdateError("请先把 App 放进「应用程序」，再从那里打开并更新")
        # 不自动提权。标准按用户安装可直接更新；只读/管理员目录保留原程序并说明出路。
        if not writable(install_cwd(target, self.system)):
            raise UpdateError("当前安装目录不可写，请用管理员权限重新打开后更新，或从官网下载并覆盖安装；备份不受影响")
        self.root.mkdir(parents=True, exist_ok=True)
        sweep_stale(self.root)
        work = Path(tempfile.mkdtemp(prefix="install-", dir=self.root))
        try:
            if self.system == "darwin":
                prepared = prepare_mac(archive, work, target, version)
                helper = work / "helper.app"
                subprocess.run(["/usr/bin/ditto", str(target), str(helper)], check=True, capture_output=True, timeout=180)
                helper_exe = helper / "Contents" / "MacOS" / self.executable.name
            else:
                prepared = safe_extract(archive, work / "extracted")
                helper = work / "helper"
                helper.mkdir()
                for name in ("aac-cli.exe", "aac-cli.exe.config"):
                    shutil.copy2(target / name, helper / name)
                shutil.copytree(target / "_internal", helper / "_internal")
                helper_exe = helper / "aac-cli.exe"
            token = uuid.uuid4().hex
            handoff = self.root / "handoff.json"
            plan = {"schema": 1, "token": token, "platform": self.system, "target": str(target),
                    "prepared": str(prepared), "version": version, "parent_pid": os.getpid(),
                    "executable": self.executable.name, "health": str(work / "healthy.json"), "ready": str(work / "ready.json"),
                    "result": str(self.root / "last-result.json"), "handoff": str(handoff)}
            path = work / "plan.json"
            write_json(path, plan)
            kwargs = process_options()
            if self.system == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            else:
                kwargs["start_new_session"] = True
            self.helper = self.popen([str(helper_exe), "--apply-update", str(path)], **kwargs)
            # 助手先校验计划并回执；它没正常启动时不能关闭仍可用的旧程序。
            for _ in range(100):
                if Path(plan["ready"]).is_file():
                    break
                if self.helper.poll() is not None:
                    raise UpdateError(_helper_error(work) or "更新助手未能启动，原程序仍可继续使用")
                time.sleep(0.1)
            else:
                self.abort()
                raise UpdateError("更新助手启动超时，原程序仍可继续使用")
        except Exception:
            try:
                remove_item(work)  # 助手没接手的准备目录由本进程清掉，不留整份程序副本
            except OSError:
                pass               # 删不掉不能顶掉正在报的那个错
            raise
        return {"exit": True, "message": "正在退出并安装更新，完成后会自动重新打开"}


def process_options():
    return {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
            "env": {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}}


def parent_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def copy_item(source, destination):
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)


def remove_item(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


class Replacement:
    """把已准备的程序换进目标目录；只替换程序自带文件，不动卸载器和用户文件。"""
    def __init__(self, target, prepared, system, token):
        self.target, self.prepared = Path(target), Path(prepared)
        self.system, self.token = system, token
        self.backup = install_cwd(self.target, system) / (".aac-old-" + token)
        self.incoming = install_cwd(self.target, system) / (".aac-new-" + token)
        self.old = []
        self.new = []

    def _slot(self, name):
        """这一份在目标目录里的落点；mac 的整包替换里 name 只用作临时目录里的文件名。"""
        return self.target if self.system == "darwin" else self.target / name

    def _prepared(self, name):
        return self.prepared if self.system == "darwin" else self.prepared / name

    def install(self):
        self.incoming.mkdir()
        self.backup.mkdir()
        names = target_units(self.target, self.system)
        try:
            # 所有复制先完成；磁盘不足时原程序完全不动。
            for name in names:
                copy_item(self._prepared(name), self.incoming / name)
            for name in names:
                dest = self._slot(name)
                if dest.exists() or dest.is_symlink():
                    os.replace(dest, self.backup / name)
                    self.old.append(name)
                os.replace(self.incoming / name, dest)
                self.new.append(name)
        except Exception:
            self.rollback()
            self.cleanup()     # 回滚成功了才轮到清临时目录；rollback 抛出时它们要看守备份
            raise

    def rollback(self):
        for name in reversed(self.new):
            remove_item(self._slot(name))
        for name in reversed(self.old):
            os.replace(self.backup / name, self._slot(name))
        self.new.clear()
        self.old.clear()

    def cleanup(self):
        """删掉两份临时目录。它是收尾，不是判定：删不掉也不该顶掉调用方正在报的那个错。"""
        for path in (self.backup, self.incoming):
            try:
                remove_item(path)
            except OSError:
                pass


def confirm_started(root, current, executable):
    """只有新程序的窗口桥已可用时才确认；更新助手本身不创建 Api，也不会确认。"""
    root = Path(root)
    try:
        plan = json.loads((root / "handoff.json").read_text(encoding="utf-8"))
        target = Path(plan["target"])
        expected = launch_target(target, plan["platform"], plan["executable"])[0]
        if current == plan["version"] and Path(executable).resolve() == expected.resolve():
            health = Path(plan["health"])
            if health.resolve().is_relative_to(root.resolve()):
                write_json(health, {"token": plan["token"], "version": current})
    except (OSError, ValueError, KeyError, TypeError):
        pass


def validate_plan(path):
    path = Path(path).resolve()
    plan = json.loads(path.read_text(encoding="utf-8"))
    work = path.parent
    if plan.get("schema") != 1 or not re.fullmatch(r"[0-9a-f]{32}", plan.get("token", "")):
        raise UpdateError("更新任务格式无效")
    if plan.get("platform") not in ("darwin", "win32") or type(plan.get("parent_pid")) is not int or plan["parent_pid"] <= 0:
        raise UpdateError("更新任务的宿主无效")
    target, prepared = Path(plan["target"]), Path(plan["prepared"])
    if not target.is_absolute() or target.is_symlink() or not target.is_dir() or not prepared.resolve().is_relative_to(work):
        raise UpdateError("更新任务的程序路径无效")
    version_tuple(plan.get("version"))
    if (Path(plan["health"]).resolve() != work / "healthy.json"
            or Path(plan["ready"]).resolve() != work / "ready.json"
            or Path(plan["result"]).resolve() != work.parent / "last-result.json"):
        raise UpdateError("更新任务的状态路径无效")
    if Path(plan["handoff"]).resolve() != work.parent / "handoff.json":
        raise UpdateError("更新任务的交接路径无效")
    if plan["platform"] == "darwin":
        if target.suffix != ".app" or bundle_info(target).get("CFBundleIdentifier") != BUNDLE_ID:
            raise UpdateError("目标不是本产品的 App")
        if (bundle_info(prepared).get("CFBundleIdentifier") != BUNDLE_ID
                or bundle_info(prepared).get("CFBundleShortVersionString") != plan["version"]):
            raise UpdateError("新程序的标识无效")
    elif plan["executable"] != "AndroidAdCleaner.exe" or not all((target / n).exists() and (prepared / n).exists() for n in WINDOWS_FILES):
        raise UpdateError("目标不是完整的本产品安装目录")
    if Path(plan["executable"]).name != plan["executable"] or not plan["executable"]:
        raise UpdateError("更新任务的启动文件无效")
    return plan


@contextmanager
def installation_lock(root):
    """不同进程的更新助手互斥；进程退出时由系统释放，锁文件本身保留。"""
    with file_lock(Path(root) / "install.lock", "另一个窗口正在安装更新，请等它完成后重试"):
        yield


def apply_update(path, *, alive=parent_alive, sleep=time.sleep, launch=subprocess.Popen, attempts=120):
    """由复制到更新缓存的旧程序执行。失败先恢复旧文件，再启动旧程序。"""
    plan = validate_plan(path)
    try:
        with installation_lock(Path(plan["result"]).parent):
            write_json(plan["handoff"], plan)
            return _apply_plan(plan, alive=alive, sleep=sleep, launch=launch, attempts=attempts)
    except UpdateError as exc:
        # 锁冲突发生在写回执之前：留给父窗口一份原因，否则它只能报「助手没起来」。
        write_json(Path(path).parent / "error.json", {"error": str(exc)})
        raise


def _apply_plan(plan, *, alive, sleep, launch, attempts):
    target = Path(plan["target"])
    receipt = Path(plan["result"])
    executable, cwd = launch_target(target, plan["platform"], plan["executable"])
    replacement = Replacement(target, plan["prepared"], plan["platform"], plan["token"])
    write_json(plan["ready"], {"token": plan["token"]})
    child = None
    replaced = False
    try:
        for _ in range(attempts):
            if not alive(plan["parent_pid"]):
                break
            sleep(0.5)
        else:
            raise UpdateError("原程序没有退出，本次更新未安装")
        replacement.install()
        replaced = True
        child = launch([str(executable)], cwd=str(cwd), **process_options())
        for _ in range(attempts):
            try:
                health = json.loads(Path(plan["health"]).read_text(encoding="utf-8"))
                if health == {"token": plan["token"], "version": plan["version"]}:
                    write_json(receipt, {"ok": True, "version": plan["version"]})
                    # 新版已确认可用；清理失败不能再回滚（备份可能已部分删除）。
                    try:
                        replacement.cleanup()
                        Path(plan["handoff"]).unlink(missing_ok=True)
                        remove_item(Path(plan["prepared"]))
                    except OSError:
                        pass
                    return 0
            except (OSError, ValueError):
                pass
            if child.poll() is not None:
                break
            sleep(0.5)
        raise UpdateError("新版没有正常打开，已恢复原版本")
    except Exception as exc:
        error = str(exc)
        try:
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=15)
            if replaced:
                replacement.rollback()
                replacement.cleanup()
            Path(plan["handoff"]).unlink(missing_ok=True)
        except Exception as recovery_error:
            error += f"；恢复未完成：{recovery_error}。旧程序文件保留在 {replacement.backup}"
            write_json(receipt, {"ok": False, "version": plan["version"], "error": error})
            return 1
        write_json(receipt, {"ok": False, "version": plan["version"], "error": error})
        if not alive(plan["parent_pid"]):
            launch([str(executable)], cwd=str(cwd), **process_options())
        return 1
