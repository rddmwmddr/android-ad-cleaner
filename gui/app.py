#!/usr/bin/env python3
"""安卓去广告 · 桌面客户端（macOS / Windows）。

界面：gui/web/index.html（pywebview 窗口）
后台：tool/run.py、tool/fast.py、tool/chan_fast.py，以子进程运行，日志实时回传界面。
打包后没有独立的 Python，子进程用「本程序 --cli 脚本名 参数…」的方式启动。
"""
import json, os, platform, re, runpy, shutil, subprocess, sys, threading, time, urllib.request, zipfile
from pathlib import Path

APP_NAME = "安卓去广告"
VERSION = "0.2.0"
FROZEN = getattr(sys, "frozen", False)
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(BASE, "tool")
IS_WIN = platform.system() == "Windows"


def data_dir():
    if IS_WIN:
        d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AndroidAdCleaner")
    elif platform.system() == "Darwin":
        d = os.path.expanduser("~/Library/Application Support/AndroidAdCleaner")
    else:
        d = os.path.expanduser("~/.local/share/android-ad-cleaner")
    os.makedirs(d, exist_ok=True)
    return d


DATA = data_dir()
BACKUPS = os.path.join(DATA, "backups")


# ---------- 命令行模式：打包后子进程走这里 ----------
def _fix_stdio():
    """Windows 窗口程序没有控制台：父进程用管道接输出时，把 1/2 号句柄包成 sys.stdout/stderr。"""
    import io
    for fd, name in ((1, "stdout"), (2, "stderr")):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, io.TextIOWrapper(os.fdopen(fd, "wb", buffering=0), encoding="utf-8",
                                                    errors="replace", line_buffering=True, write_through=True))
            except OSError:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    for st in (sys.stdout, sys.stderr):        # Windows 控制台默认 cp1252/GBK，中文和 ✗ ▶ 会报错；打包后 PYTHONIOENCODING 不生效
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cli_main():
    _fix_stdio()
    script, args = sys.argv[2], sys.argv[3:]
    sys.path.insert(0, TOOL)
    sys.argv = [os.path.join(TOOL, script)] + args
    runpy.run_path(os.path.join(TOOL, script), run_name="__main__")


# ---------- adb ----------
ADB_URL = {
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "Windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}


def find_adb():
    exe = "adb.exe" if IS_WIN else "adb"
    cands = [os.path.join(DATA, "platform-tools", exe), shutil.which("adb"),
             os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
             "/opt/homebrew/bin/adb", "/usr/local/bin/adb"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def child_env(adb):
    e = dict(os.environ)
    e.update({"ADB": adb or "", "ADBUTILS_ADB_PATH": adb or "", "AAC_BACKUPS": BACKUPS,
              "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "AAC_GUI": "1"})
    if adb:
        e["PATH"] = os.path.dirname(adb) + os.pathsep + e.get("PATH", "")
    return e


def cmd_for(script, *args):
    if FROZEN:
        cli = os.path.join(os.path.dirname(sys.executable), "aac-cli.exe")
        exe = cli if IS_WIN and os.path.exists(cli) else sys.executable     # Windows 用命令行版，输出不丢
        return [exe, "--cli", script, *args]
    return [sys.executable, "-u", os.path.join(TOOL, script), *args]


def os_name():
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if IS_WIN:
        return f"Windows {platform.release()}（{platform.version()}）"
    return f"{platform.system()} {platform.release()}"


NOWIN = 0x08000000 if IS_WIN else 0     # Windows：子进程不弹黑色控制台窗口


# 营销渠道里混进来的服务类渠道：默认不勾
SERVICE = re.compile(r"TETHERING|热点|ENVELOPE|红包|Auto lock|盗窃|hotspot|drive_mode|驾驶|securitypermission|权限建议|直播|ig_live|youtube\t2\t", re.I)


class Api:
    def __init__(self):
        self.adb = find_adb()
        self.job = None
        self.lock = threading.Lock()
        self.dl = {"state": "idle", "pct": 0, "msg": ""}
        self.last_status = None

    # ----- 基础 -----
    def env(self):
        return {"adb": self.adb, "data": DATA, "version": VERSION, "os": platform.system(),
                "images": [f for f in sorted(os.listdir(os.path.join(BASE, "images"))) if f.startswith("dev-")]}

    def _run(self, script, *args, timeout=180):
        r = subprocess.run(cmd_for(script, *args), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=child_env(self.adb), timeout=timeout, creationflags=NOWIN)
        return r.stdout, r.stderr, r.returncode

    def _adb(self, *args, timeout=20):
        r = subprocess.run([self.adb, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=NOWIN)
        return r.stdout

    # ----- 下载 adb -----
    def download_adb(self):
        if self.dl["state"] == "running":
            return
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        self.dl = {"state": "running", "pct": 0, "msg": "正在从 Google 官网下载 platform-tools……"}
        try:
            url = ADB_URL[platform.system()]
            zp = os.path.join(DATA, "platform-tools.zip")
            with urllib.request.urlopen(url, timeout=30) as r, open(zp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0); got = 0
                while True:
                    b = r.read(65536)
                    if not b:
                        break
                    f.write(b); got += len(b)
                    if total:
                        self.dl["pct"] = int(got * 100 / total)
            with zipfile.ZipFile(zp) as z:
                z.extractall(DATA)
            os.remove(zp)
            adb = os.path.join(DATA, "platform-tools", "adb.exe" if IS_WIN else "adb")
            if not IS_WIN:
                os.chmod(adb, 0o755)
            self.adb = adb
            self.dl = {"state": "done", "pct": 100, "msg": "adb 已就绪"}
        except Exception as e:
            self.dl = {"state": "error", "pct": 0, "msg": f"下载失败：{e}"}

    def download_state(self):
        return self.dl

    # ----- 设备 -----
    def devices(self):
        if not self.adb:
            return {"error": "no-adb", "list": []}
        try:
            out = self._adb("devices", "-l", timeout=10)
        except Exception as e:
            return {"error": str(e), "list": []}
        res = []
        for line in out.splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split()
            ser, st = parts[0], parts[1]
            if ser.startswith("emulator-"):
                continue
            d = {"serial": ser, "state": st, "model": "", "name": "", "brand": ""}
            if st == "device":
                try:
                    p = self._adb("-s", ser, "shell",
                                  "getprop ro.product.brand; getprop ro.product.model; "
                                  "getprop ro.vendor.oplus.market.name; getprop ro.product.marketname", timeout=8).splitlines()
                    p += [""] * 4
                    d.update(brand=p[0].strip(), model=p[1].strip(), name=(p[2] or p[3]).strip())
                except Exception:
                    pass
            res.append(d)
        return {"error": None, "list": res}

    def status(self, serial):
        out, err, rc = self._run("run.py", "-s", serial, "status-json", timeout=90)
        try:
            st = json.loads(out.strip().splitlines()[-1])
            self.last_status = st
            return st
        except Exception:
            return {"error": (err or out)[-600:]}

    def chan_scan(self, serial):
        out, err, rc = self._run("chan_fast.py", "-s", serial, "scan", timeout=120)
        if rc:
            return {"error": (err or out or "通知扫描失败，请检查连接与权限")[-600:]}
        rows = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                rows.append({"pkg": parts[0], "id": parts[1], "name": parts[2],
                             "checked": not SERVICE.search(line)})
        return rows

    # ----- 任务 -----
    def start(self, serial, plan):
        """plan: {backup, steps:[段名]|None, channels:[{pkg,id,name}], quickapp:bool, ads:[包名], model}"""
        with self.lock:
            if self.job and self.job["running"]:
                return {"error": "已有任务在运行"}
            tasks = []
            if plan.get("backup", True):
                tasks.append(("存改动前的快照", "run.py", ["-s", serial, "backup"]))
            if plan.get("steps"):
                tasks.append(("关闭各 App 里的广告开关", "run.py",
                              ["-s", serial, "recipe", *plan["steps"], *(["--ref"] if plan.get("ref") else [])]))
            if plan.get("channels"):
                tasks.append(("关闭营销通知", "@channels", plan["channels"]))
            if plan.get("quickapp"):
                tasks.append(("关闭快应用", "run.py", ["-s", serial, "quickapp", "off"]))
            if plan.get("ads"):
                tasks.append(("挂起广告组件", "run.py", ["-s", serial, "suspend", *plan["ads"]]))
            tasks.append(("收尾", "run.py", ["-s", serial, "finish"]))
            self.job = {"running": True, "lines": [], "idx": 0, "total": len(tasks), "title": "",
                        "results": [], "proc": None, "cancel": False, "t0": time.time(), "serial": serial,
                        "model": plan.get("model", "")}
        threading.Thread(target=self._work, args=(tasks,), daemon=True).start()
        return {"ok": True, "total": len(tasks)}

    def _log(self, s):
        self.job["lines"].append(s.rstrip("\n"))

    def _latest_backup(self, model):
        try:
            hits = sorted(d for d in os.listdir(BACKUPS) if d.startswith(model + "-"))
            return os.path.join(BACKUPS, hits[-1]) if hits else None
        except FileNotFoundError:
            return None

    def _work(self, tasks):
        j = self.job
        for i, (title, script, args) in enumerate(tasks):
            if j["cancel"]:
                break
            j["idx"], j["title"] = i + 1, title
            self._log(f"\n▶ {title}")
            t = time.time()
            if script == "@channels":
                d = self._latest_backup(j["model"]) or os.path.join(BACKUPS, f"{j['model']}-gui")
                os.makedirs(d, exist_ok=True)
                fn = os.path.join(d, "channels.tsv")
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("# 包名\t渠道id\t渠道名（客户端勾选）\n")
                    for c in args:
                        f.write(f"{c['pkg']}\t{c['id']}\t{c['name']}\n")
                script, args = "chan_fast.py", ["-s", j["serial"], "off", fn]
            try:
                p = subprocess.Popen(cmd_for(script, *args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", env=child_env(self.adb),
                                     creationflags=NOWIN, bufsize=1)
                j["proc"] = p
                tail = []
                for line in p.stdout:
                    self._log(line); tail.append(line.strip()); tail = tail[-80:]
                rc = p.wait()
            except Exception as e:
                rc, tail = -1, [str(e)]
                self._log(f"✗ {e}")
            j["results"].append({"title": title, "rc": rc, "sec": round(time.time() - t), "tail": tail})
        j["running"] = False
        j["proc"] = None
        self._log(f"\n全部完成，用时 {round(time.time() - j['t0'])} 秒" if not j["cancel"] else "\n已停止")

    def poll(self, since=0):
        j = self.job
        if not j:
            return {"running": False, "lines": [], "next": 0}
        lines = j["lines"][since:]
        return {"running": j["running"], "lines": lines, "next": since + len(lines), "idx": j["idx"],
                "total": j["total"], "title": j["title"], "results": j["results"] if not j["running"] else [],
                "sec": round(time.time() - j["t0"]), "cancel": j["cancel"]}

    def stop(self):
        if self.job and self.job["running"]:
            self.job["cancel"] = True
            p = self.job.get("proc")
            if p:
                p.terminate()
        return True

    # ----- 收尾 / 还原 -----
    def dev_off(self, serial):
        out, err, rc = self._run("run.py", "-s", serial, "dev-off", "--yes", timeout=30)
        return out + err

    def restore(self, serial, what):
        if what == "suspend":
            out, err, rc = self._run("run.py", "-s", serial, "unsuspend")
        elif what == "quickapp":
            out, err, rc = self._run("run.py", "-s", serial, "quickapp", "on")
        elif what == "channels":
            st = self.status(serial)
            d = self._latest_backup(st.get("info", {}).get("model", ""))
            fn = d and os.path.join(d, "channels.tsv")
            if not fn or not os.path.exists(fn):
                return "没有找到上次关掉的营销通知清单"
            out, err, rc = self._run("chan_fast.py", "-s", serial, "on", fn, timeout=600)
        else:
            return "未知的还原项"
        return out + err

    # ----- 反馈 -----
    def diagnostics(self):
        """反馈附带的诊断信息。序列号替换成 <序列号>；不含应用列表和通知内容。"""
        lines = [f"- 客户端：{APP_NAME} {VERSION}（{'打包版' if FROZEN else '源码'}）",
                 f"- 电脑：{os_name()}（{platform.machine()}）"]
        try:
            v = self._adb("version", timeout=8).splitlines()[0] if self.adb else "没有 adb"
        except Exception as e:
            v = f"adb 出错：{e}"
        lines.append(f"- adb：{v}")
        st, serial = self.last_status, (self.job or {}).get("serial")
        if st and "info" in st:
            i = st["info"]
            nm = i.get("name") or i.get("model")
            if not nm.upper().startswith((i.get("brand") or "").upper()):
                nm = f"{i.get('brand')} {nm}"
            lines += [f"- 手机：{nm}（{i.get('model')}）",
                      f"- 系统：{i.get('build')}，Android {i.get('android')}",
                      f"- 机型脚本：{st.get('recipe') or '无'}"
                      + (f"（录制版本 {st.get('recipe_build')}，{'一致' if st.get('recipe_ok') else '不一致'}）" if st.get('recipe') else ""),
                      f"- 折叠屏展开：{'是' if st.get('fold_open') else '否'}；锁屏：{'是' if st.get('locked') else '否'}"]
        else:
            lines.append("- 手机：还没检测")
        j = self.job
        if j:
            lines.append("\n**执行结果**\n")
            for r in j["results"]:
                lines.append(f"- {r['title']}：{'成功' if r['rc'] == 0 else '失败（退出码 %s）' % r['rc']}，{r['sec']} 秒")
            tail = [l for l in j["lines"] if l.strip()][-60:]
            log = "\n".join(tail)
            if serial:
                log = log.replace(serial, "<序列号>")
            lines.append("\n<details><summary>最近的日志</summary>\n\n```text\n" + log + "\n```\n</details>")
        return "\n".join(lines)

    def copy_text(self, text):
        try:
            if IS_WIN:
                subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"], input=text,
                               text=True, encoding="utf-8", creationflags=NOWIN, timeout=10)
            else:
                subprocess.run(["pbcopy"], input=text, text=True, encoding="utf-8", timeout=10)
            return True
        except Exception:
            return False

    def open_path(self, which):
        path = {"data": DATA, "backups": BACKUPS}.get(which, DATA)
        os.makedirs(path, exist_ok=True)
        if IS_WIN:
            os.startfile(path)
        else:
            subprocess.Popen(["open", path])

    def open_url(self, url):
        """网址里的中文先转成 %XX：macOS 经 AppleScript、Windows 经 shell 打开中文网址会出错。"""
        import webbrowser, urllib.parse
        webbrowser.open(urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~"))


def smoke_gui(window, result):
    """只验证本地页面、图片和 JS→Python 桥；不连接或修改手机。"""
    try:
        if not window.events.loaded.wait(30):
            raise RuntimeError("页面加载超时")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            ready = window.evaluate_js("typeof api !== 'undefined' && !!api && !!document.querySelector('#tutbox')")
            if ready:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("JS API 桥初始化超时")
        window.evaluate_js("window.__smokeEnv = null; api.env().then(x => window.__smokeEnv = x.version)")
        while time.monotonic() < deadline:
            report = window.evaluate_js("({url: location.href, version: window.__smokeEnv, images: [...document.querySelectorAll('#tutbox img')].every(i => i.complete && i.naturalWidth > 0)})")
            if report.get("version") == VERSION and report.get("images") and report.get("url", "").startswith("file://"):
                from webview import http
                if http.global_server is not None:
                    raise RuntimeError("不应启动本地 HTTP 服务")
                result["ok"] = True
                print("GUI smoke: file 页面、教程图片、JS API 桥通过；未启动 HTTP 服务", flush=True)
                return
            time.sleep(0.1)
        raise RuntimeError("教程图片或 JS API 调用未通过")
    except Exception as e:
        print(f"GUI smoke failed: {e}", file=sys.stderr, flush=True)
    finally:
        window.destroy()


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--cli":
        cli_main(); return
    import webview
    api = Api()
    smoke = "--smoke-gui" in sys.argv
    if smoke:
        _fix_stdio()
        api.adb = None                     # 不枚举真机，不自动下载 adb
    result = {"ok": False}
    # 明确 file://：裸文件路径会启动 Bottle HTTP 服务，部分 Windows 环境回环连接超时（#18）。
    url = Path(BASE, "gui", "web", "index.html").resolve().as_uri()
    w = webview.create_window(APP_NAME, url, js_api=api, hidden=smoke,
                              width=1080, height=780, min_size=(900, 640))
    options = {"debug": "--debug" in sys.argv, "http_server": False}
    if smoke:
        options.update(func=smoke_gui, args=(w, result))
    if IS_WIN:
        try:
            webview.start(gui="edgechromium", **options)
        except Exception as e:      # 缺 WebView2 运行时（部分 Windows 10）
            if smoke:
                raise
            import ctypes, webbrowser
            url = "https://developer.microsoft.com/microsoft-edge/webview2/"
            ctypes.windll.user32.MessageBoxW(0, "这台电脑缺少微软 Edge WebView2 运行时，界面没法显示。\n\n"
                                                "点「确定」打开微软官网，下载安装「Evergreen Bootstrapper」后重新打开本程序。\n\n"
                                                f"（{e}）", APP_NAME, 0x40)
            webbrowser.open(url)
    else:
        webview.start(**options)
    if smoke:
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
