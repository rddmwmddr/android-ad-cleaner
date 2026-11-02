"""Api 拆类前后的对拍：同一串调用喂给两份 `gui/app.py`，比较可观察输出（ADR-0011）。

基线取改动前的干净副本（钉提交 SHA，不用会前进的 `origin/main`）：

    python tests/compare_api.py --baseline b1f4919

两边各起一个子进程：模块名相同，同进程里 import 不了两份 `gui.app`。比较签名、下载状态、
上报结果与执行序列；`sec` 归一为空（墙钟不是行为）。每条场景都报自己走到了哪个分支，
守卫为空的一条算没测到，整体以非零退出。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 无调用者的转发壳，删除是有意的（ADR-0011）：只在基线上存在，当前版本的生产路径不经过它
KNOWN_REMOVED = {"_fetch"}

DRIVER = r'''
import contextlib, hashlib, inspect, io, json, os, re, sys, tempfile, time, zipfile
from unittest.mock import patch

sys.path.insert(0, os.getcwd())
from gui import app

out = {"signatures": {}, "download": {}, "report": {}, "run": {}}

for name in dir(app.Api):
    if name.startswith("__"):
        continue
    attr = getattr(app.Api, name)
    if callable(attr):
        try:
            out["signatures"][name] = str(inspect.signature(attr))
        except (TypeError, ValueError):
            pass


class Reply(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("platform-tools/adb", "x")
    return buf.getvalue()


BODY = zip_bytes()
DIGEST = hashlib.sha256(BODY).hexdigest()


def download(name, sources, opener, zip_ok=True):
    with tempfile.TemporaryDirectory() as d:
        api = app.Api(d)
        urls = []

        def tracked(request, timeout=None):
            urls.append(request.full_url)
            return opener(request.full_url)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(app.urllib.request, "urlopen", side_effect=tracked))
            if not zip_ok:
                stack.enter_context(patch.object(app.zipfile, "ZipFile",
                                                 side_effect=app.zipfile.BadZipFile("not a zip")))
            stack.enter_context(patch.object(api, "adb_sources", return_value=sources))
            api._download()
        out["download"][name] = {
            "urls": urls,
            "state": api.dl["state"],
            "msg": api.dl["msg"],
            "pct": api.dl["pct"],
            "adb": os.path.basename(api.adb or ""),
            "zip_left": os.path.exists(os.path.join(d, "platform-tools.zip")),
            "reached": "done" if api.dl["state"] == "done" else "error",
        }


def down(url):
    raise OSError("timed out")


def body(url):
    return Reply(BODY)


TWO = [("Google 官网", "https://g/x.zip", DIGEST), ("腾讯云镜像", "https://t/x.zip", DIGEST)]
download("fallback", TWO, lambda url: down(url) if "//g/" in url else Reply(BODY))
download("all-failed", TWO, down)
download("bad-checksum", [("Google 官网", "https://g/x.zip", "0" * 64)], body)
download("bad-zip", [("Google 官网", "https://g/x.zip", DIGEST)], body, zip_ok=False)

with tempfile.TemporaryDirectory() as d:
    api = app.Api(d)
    with patch.object(api, "adb_sources", side_effect=KeyError("no platform")):
        api._download()
    out["download"]["sources-error"] = {
        "state": api.dl["state"], "msg": api.dl["msg"], "pct": api.dl["pct"],
        "reached": "error" if api.dl["state"] == "error" else api.dl["state"],
    }


def prepared(api):
    api.job = app.Job(serial="SERIAL01", t0=0)
    api.job.lines = ["第一行", "   ", "第二行"]
    api.job.results = [{"title": "备份", "rc": 0, "sec": 1},
                       {"title": "关闭营销通知", "rc": 1, "sec": 2, "tail": ["x"]}]
    api.job.payloads = ["骨架一行"]
    api.last_status = {"info": {"brand": "Xiaomi", "name": "Xiaomi 17", "model": "25113PN0EC",
                                "os": "OS3", "android": "16"}}
    api.last_error = {"operation": "关闭营销通知", "detail": "boom\nException: x"}
    return api


def reply(status):
    return Reply(json.dumps({"status": status, "id": "abc"}).encode())


with tempfile.TemporaryDirectory() as d:
    api = prepared(app.Api(d))
    value = api.report_payload()
    out["report"]["payload"] = {"value": value,
                                "reached": "payload" if "骨架一行" in value["log"] else "missing"}

    cases = (("ok", "ok"), ("duplicate", "duplicate"), ("429", None), ("empty", "ok"), ("limit", "ok"))
    for name, status in cases:
        api = prepared(app.Api(d))
        payload = {} if name == "empty" else api.report_payload()
        with contextlib.ExitStack() as stack:
            if name == "429":
                stack.enter_context(patch.object(
                    app.urllib.request, "urlopen",
                    side_effect=app.urllib.error.HTTPError("u", 429, "too many", {},
                                                           io.BytesIO(b'{"message": "slow down" }'))))
            else:
                stack.enter_context(patch.object(app.urllib.request, "urlopen", return_value=reply(status)))
            if name == "limit":
                for _ in range(app.REPORT_LIMIT):
                    api.send_report(api.report_payload())
            result = api.send_report(payload)
        reached = {
            "ok": "ok" if result.get("ok") and not result.get("duplicate") else "other",
            "duplicate": "duplicate" if result.get("duplicate") else "other",
            "429": "429" if "太频繁" in result.get("error", "") else "other",
            "empty": "empty" if result.get("error") == app.EMPTY_REPORT else "other",
            "limit": "limited" if "最多上报" in result.get("error", "") else "other",
        }[name]
        out["report"][name] = {"result": result, "times": len(api.report_times),
                               "install_id": bool(api._install_id()), "reached": reached}


class Proc:
    def __init__(self, lines, rc, hook=None):
        self._lines, self._rc, self._hook = lines, rc, hook
        self.terminated = False
        self.stdout = self._gen()

    def _gen(self):
        for i, line in enumerate(self._lines):
            if i == 0 and self._hook:
                self._hook()
            yield line

    def wait(self):
        return self._rc

    def terminate(self):
        self.terminated = True


class FakeRunner:
    def __init__(self):
        self.procs = []
        self.calls = []

    def spawn(self, script, *args, env_extra=None):
        shown = [os.path.basename(a) if os.path.isabs(a) else a for a in args]
        self.calls.append([script, shown, sorted((env_extra or {}).keys())])
        return self.procs.pop(0)


def event(kind):
    return '#aac:event {"kind": "%s"}\n' % kind


def settle(api, timeout=5):
    """等收尾行真的写进去：`running=False` 与最后一行是两次独立写（#452 第 2 条，本次不修）。"""
    end = time.time() + timeout
    while time.time() < end:
        j = api.job
        if j and not j.running and j.lines and (j.lines[-1].startswith("\n执行结束")
                                                or j.lines[-1] == "\n已停止"):
            return
        time.sleep(0.002)


def elapsed_norm(lines):
    return [re.sub(r"用时 \d+ 秒", "用时 N 秒", line) for line in lines]


def run_case(name, plan, make_procs, guard, extra_patches=()):
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "backups", "M-gui"), exist_ok=True)
        runner = FakeRunner()
        api = app.Api(d, runner=runner)
        runner.procs = make_procs(api)
        with contextlib.ExitStack() as stack:
            for p in extra_patches:
                stack.enter_context(p)
            started = api.start("SERIAL01", plan)
            settle(api)
        snap = api.poll(0)
        out["run"][name] = {
            "started": started,
            "calls": runner.calls,
            "results": api.job.results,
            "lines": elapsed_norm(api.job.lines),
            "payloads": api.job.payloads,
            "cancel": snap["cancel"],
            "recovery": snap["recovery"],
            "paused": snap["paused"],
            "step_events": sorted(api.job.step_events),
            "last_error": api.last_error,
            "reached": guard(api),
        }


PLAN = {"backup": True, "steps": ["s1"], "quickapp": True}
run_case("success", PLAN, lambda api: [Proc(["a\n"], 0) for _ in range(4)],
         lambda api: "all-ok" if all(r["rc"] == 0 for r in api.job.results) else "mixed")
run_case("failure", PLAN, lambda api: [Proc(["a\n"], 0), Proc(["Exception: boom\n"], 1),
                                       Proc(["c\n"], 0), Proc(["d\n"], 0)],
         lambda api: "error" if api.last_error else "no-error")
run_case("stopped", PLAN, lambda api: [Proc(["a\n"], 143, hook=api.stop), Proc(["b\n"], 0),
                                       Proc(["c\n"], 0), Proc(["d\n"], 0)],
         lambda api: "stopped" if any(r.get("stopped") for r in api.job.results) else "not-stopped")

UI_PLAN = {"backup": False, "steps": ["s1"], "model": "M",
           "channels": [{"pkg": "p", "id": "i", "name": "n", "app": "a"}]}
run_case("ui-busy", UI_PLAN, lambda api: [Proc([event("ui_busy") + "UIAUTOMATION_BUSY: x\n"], 1),
                                          Proc(["done\n"], 0)],
         lambda api: "skipped" if any(r.get("skipped") for r in api.job.results) else "not-skipped")

LOST_PLAN = {"backup": True, "steps": ["s1"]}
run_case("link-lost", LOST_PLAN, lambda api: [Proc(["a\n"], 0),
                                              Proc([event("link_lost") + "Exception: gone\n"], 1)],
         lambda api: "link-lost" if api.last_error and any(r.get("skipped") for r in api.job.results)
         else "other",
         extra_patches=[patch.object(app, "adb_present", return_value=False)])

run_case("events", {"backup": False},
         lambda api: [Proc([event("paused"), "x\n", event("resumed"), event("locked"), event("ui_busy")], 0)],
         lambda api: "events" if api.job.step_events else "none")

run_case("payload", {"backup": False},
         lambda api: [Proc(['#aac:payload 骨架A\n', "#aac:payload 骨架B\n", "人话\n"], 0)],
         lambda api: "payload" if api.job.payloads == ["骨架A", "骨架B"]
         and not any("骨架A" in line for line in api.job.lines) else "leaked")

with tempfile.TemporaryDirectory() as d:
    api = app.Api(d)
    out["run"]["pause-idle"] = {"pause": api.pause(), "resume": api.resume(), "reached": "idle"}
    api.job = app.Job(serial="s", t0=0)
    out["run"]["pause-running"] = {"pause": api.pause(), "flagged": api.job.pause,
                                   "resume": api.resume(), "cleared": api.job.pause,
                                   "reached": "running"}

print(json.dumps(out, ensure_ascii=False, sort_keys=True))
'''


def run(root):
    env = dict(os.environ, AAC_NO_SOUND="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    done = subprocess.run([sys.executable, "-c", DRIVER], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=180)
    if done.returncode:
        raise SystemExit(f"驱动失败（{root}）：\n{done.stderr[-4000:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def baseline_copy(rev):
    tmp = tempfile.mkdtemp(prefix="aac-api-baseline-")
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", rev], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, check=True)
    return tmp


def diff(old, new, path=""):
    found = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            if key == "sec":
                continue
            if path == "" and key == "signatures":
                continue
            if key not in old:
                found.append(f"{path}.{key}: 只在当前版本")
            elif key not in new:
                found.append(f"{path}.{key}: 只在基线")
            else:
                found += diff(old[key], new[key], f"{path}.{key}")
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            found.append(f"{path}: 长度 {len(old)} != {len(new)}")
        for i, (a, b) in enumerate(zip(old, new)):
            found += diff(a, b, f"{path}[{i}]")
    elif old != new:
        found.append(f"{path}: {old!r} != {new!r}")
    return found


def guards(data, path=""):
    found = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "reached":
                found.append((path or "root", value))
            else:
                found += guards(value, f"{path}.{key}" if path else key)
    return found


def main(argv):
    if "--baseline" not in argv:
        raise SystemExit("用法：python tests/compare_api.py --baseline <改前提交>")
    rev = argv[argv.index("--baseline") + 1]
    tmp = baseline_copy(rev)
    try:
        baseline = run(tmp)
        current = run(ROOT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    problems = diff(baseline, current)
    old_sigs, new_sigs = baseline["signatures"], current["signatures"]
    removed = []
    for name, sig in old_sigs.items():
        if name not in new_sigs:
            if name in KNOWN_REMOVED:
                removed.append(name)
            else:
                problems.append(f"签名缺失：{name}")
        elif new_sigs[name] != sig:
            problems.append(f"签名变了：{name}: {sig} != {new_sigs[name]}")
    added = sorted(set(new_sigs) - set(old_sigs))
    seen = guards(current)
    empty = [name for name, value in seen if not value]
    print(f"对拍场景 {len(seen)} 条，守卫全部命中" if not empty
          else f"守卫为空的场景：{', '.join(empty)}")
    if added:
        print(f"新增的 Api 方法（基线没有）：{', '.join(added)}")
    if removed:
        print(f"有意移除的 Api 方法：{', '.join(sorted(removed))}")
    if problems:
        print("差异：")
        for line in problems:
            print("  " + line)
        return 1
    if empty:
        return 1
    print(f"与基线 {rev} 零差异")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
