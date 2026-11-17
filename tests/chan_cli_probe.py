"""对拍探针：在子进程里 import 指定树的 `chan_fast`，用假设备跑一次 `main()`。

由 `tests/chan_cli_driver.py` 起进程，参数依次是：`tool` 目录、用例 JSON、结果 JSON、临时工作目录。
用例 JSON 同时写进工作目录（`list.tsv` 是相对路径，子进程 cwd 就是那里）。

替身只落在「设备」这一侧：`ShellPhone` / `Phone` / `parse` / `toggle` / `app_labels` / `keep_awake`
与两个时读数。批处理本身（队列、两趟、重试、复查、打印、退出码）跑的是树里那一份真代码。
`-I` 起进程，所以 `tool` 目录只从参数进 `sys.path`，不会混进当前副本。
"""
import io
import json
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def main():
    tool_dir, spec_path, result_path, work = sys.argv[1:5]
    sys.path.insert(0, tool_dir)
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    import chan_fast as chan
    import adb_link
    from phone.errors import ScreenLocked

    class Reply:
        def __init__(self, output=""):
            self.returncode, self.output, self.stdout, self.stderr = 0, output, output, ""

    class Reader:
        def __init__(self):
            self.calls = []

        def shell(self, command, timeout=60):
            self.calls.append(command)
            if "getprop ro.product.model" in command:
                return Reply(spec.get("model", "M1") + "\n")
            if "stay_on_while_plugged_in" in command:
                return Reply("7\n")
            return Reply()

        def push(self, local, remote, timeout=30):
            self.calls.append("push " + str(remote))

    reader = Reader()
    phones = []

    class FakeDevice:
        def __init__(self, serial, log=False):
            self.serial, self.d, self.closed = serial, reader, False
            # 门面收窄之后状态归协作者：三个对象都指向自己，两棵树都能驱动（#1479）
            self.conn = self.screen = self.channel_session = self
            self.reader = reader
            self.systemui_text = False
            self.vivo_seen = False
            self.skeleton_sigs, self.skeleton_count, self.mismatch_probes = set(), 0, 0
            self.pause_at_lock_check = True
            self.unlocks = list(spec.get("unlocks") or [True])
            phones.append(self)

        def shell(self, command, timeout=None):
            return reader.shell(command, timeout=60 if timeout is None else timeout).output

        def wait_unlocked(self, timeout=None):
            if len(self.unlocks) > 1:
                return bool(self.unlocks.pop(0))
            return bool(self.unlocks[0])

        def close(self):
            self.closed = True

    reads, read_at = list(spec.get("reads") or [{}]), [0]

    def fake_parse(_phone, locked=None, foreground=None):
        read = reads[min(read_at[0], len(reads) - 1)]
        read_at[0] += 1
        if read.get("lost"):
            raise adb_link.DeviceLost("device offline")
        if read.get("fail"):
            raise RuntimeError(read["fail"])
        if isinstance(locked, set):
            locked.update(tuple(pair) for pair in read.get("locked", []))
        if isinstance(foreground, set):
            foreground.update(tuple(pair) for pair in read.get("foreground", []))
        channels = {(pk, cid): (name, int(imp), bool(deleted))
                    for pk, cid, name, imp, deleted in read.get("channels", [])}
        return channels, {pk: True for pk in read.get("app_off", [])}

    script, toggle_at = list(spec.get("toggles") or [{}]), [0]
    toggle_calls = []

    def fake_toggle(_phone, pk, cid, want_on, name="", allowed=()):
        toggle_calls.append([pk, cid, bool(want_on), name])
        step = script[min(toggle_at[0], len(script) - 1)]
        toggle_at[0] += 1
        if step.get("raise") == "locked":
            raise ScreenLocked("手机锁屏了")
        if step.get("raise") == "lost":
            raise adb_link.DeviceLost("device offline")
        if step.get("raise") == "stop":
            raise chan.StopBatch("点击后应用通知总开关发生变化，停止整批；请在手机上核对该 App 的通知设置")
        # #1437 把结局词表收进 `channel_batch` 并改成枚举；拆分前的树里 kind 是裸字符串。
        # 探针要能同时驱动两棵树，按树里有没有 `OutcomeKind` 取构造器。
        kind = getattr(chan, "OutcomeKind", str)(step.get("kind", "done"))
        return chan.Outcome(kind, step.get("detail", ""), step.get("payload", ""))

    labels = spec.get("labels") or {}
    chan.ShellPhone = lambda _serial: reader
    chan.Phone = FakeDevice
    chan.parse = fake_parse
    chan.toggle = fake_toggle
    chan.app_labels = lambda _reader, packages: {pk: labels[pk] for pk in packages if pk in labels}
    chan.keep_awake = lambda _reader: "7"
    chan.pause_point = lambda: None
    chan.BACKUPS = str(Path(work) / "backups")
    chan.time = types.SimpleNamespace(time=lambda: 1000.0, sleep=lambda _s: None)

    out, err = io.StringIO(), io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        sys.argv = ["chan_fast.py", *spec["argv"]]
        try:
            chan.main()
        except SystemExit as stop:
            code = stop.code
            if isinstance(code, str):      # CPython 把 sys.exit(文案) 打到 stderr 后按 1 退出
                err.write(code + "\n")
                code = 1
            elif code is None:
                code = 0

    store = Path(work, "backups")
    hidden = []
    if store.is_dir():
        for path in sorted(store.glob("ui-hidden-*.tsv")):
            hidden += [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    result = {
        "rc": code, "stdout": out.getvalue(), "stderr": err.getvalue(),
        "guards": {"parse_calls": read_at[0], "toggle_calls": toggle_calls, "shells": reader.calls,
                   "phone_created": bool(phones),
                   "phone_closed": bool(phones) and all(p.closed for p in phones),
                   "hidden": hidden},
    }
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
