"""执行编排：排好的任务怎么一个个跑、暂停与停止、断线后的剩余步、结果记账与日志事件流（#1383）。

搬出 `gui/app.py` 之前这一段与窗口桥、USB 诊断、上报并列。协作者全部由构造注入：`runner_of` /
`backups_of` / `data` / `adb_of` / `on_error` 是数据侧的取值函数，`chime` / `link_lost` /
`adb_present` 是宿主相关的三个钩子（手机版在 `aac_android.main.boot()` 里换掉它们），
`summary` / `coverage_note` / `plan_of` 是三样 `tool/` 模块（前两个是模块本身，`plan_of` 是取值函数）。
本模块不认识 `gui/app.py`，也不读它的模块全局。
"""
import os
import re
import threading
import time
from pathlib import Path

try:                                # 当包导入（测试）；直接跑脚本、打包时它是顶层模块
    from . import toolpath
    from .tasks import not_run_result, plan_tasks, retryable, runs_after_stop, step_result
except ImportError:
    import toolpath
    from tasks import not_run_result, plan_tasks, retryable, runs_after_stop, step_result


def _plan():
    """`tool/plan.py`。直接构造 `Job` 的通路（用例、手机版）不经 `Dispatcher`，没人注入它。"""
    return toolpath.tool("plan")


class Job:
    """一次执行的状态（ADR-0010）。工作线程写，HTTP 线程经 snapshot() 读一致视图。

    `plan` 是这一轮跑的规格对象（`tool/plan.py` 的 `Plan`），`retry_plan()` 拿它重建下一轮；重试轮的
    `results` / `lines` / `payloads` 从上一轮接管过来，每一步按 kind 覆盖同一步的旧结果，日志与上报
    仍是整场的（#638）。"""

    def __init__(self, serial="", model="", total=0, t0=None, plan=None, recipe_coverage="",
                 base_results=(), base_lines=(), base_payloads=(), plan_of=_plan):
        self.lock = threading.RLock()
        self.running = True
        self.recipe_coverage = recipe_coverage   # 这次所用机型脚本的验证档位，两个来源见 Dispatcher.start
        self.lines = list(base_lines)
        self.idx = 0
        self.total = total
        self.title = ""
        self.results = list(base_results)
        self.plan = plan_of().Plan.from_json(plan) if plan else None
        self.failed_steps = []          # 本步骤里引擎报的未完成段名
        self.proc = None
        self.cancel = False
        self.t0 = time.time() if t0 is None else t0
        self.serial = serial
        self.model = model
        self.paused = False
        self.pause = False
        self.recovery = ""
        self.step_events = set()
        self.payloads = list(base_payloads)

    def add_result(self, result):
        """记一行的结果。重试轮里同 kind 的那一行被就地覆盖，界面看到的始终是各步最新一轮（#638）。

        标题留着上一轮的：`关闭各 App 里的广告开关（3 / 9 段）` 说的是用户勾了哪几段，重试轮只跑其中
        一两段，按这一轮重算会把覆盖范围从界面上抹掉。"""
        with self.lock:
            kind = result.get("kind")
            if kind:
                for i, old in enumerate(self.results):
                    if old.get("kind") == kind:
                        self.results[i] = {**result, "title": old.get("title", result["title"])}
                        return
            self.results.append(result)

    def request_stop(self):
        """用户点「停止」：置取消并杀掉正在跑的引擎进程。"""
        with self.lock:
            self.cancel = True
            proc = self.proc
        if proc:
            proc.terminate()

    def request_pause(self):
        with self.lock:
            self.pause = True

    def clear_pause(self):
        with self.lock:
            self.pause = False

    def snapshot(self, since=0):
        """某一时刻的一致只读视图。lines 只给 since 之后的新行，next 是下一次的偏移。

        这一份另带 `recipe_coverage`：这次所用机型脚本的验证档位，原样透传引擎给的值（#1129）。
        `retry` 是此刻还能重试的步数，结果页的按钮按它取 N（#638）。"""
        with self.lock:
            lines = self.lines[since:]
            return {"running": self.running, "lines": lines, "next": since + len(lines),
                    "idx": self.idx, "total": self.total, "title": self.title,
                    "results": list(self.results), "sec": round(time.time() - self.t0),
                    "cancel": self.cancel, "recovery": self.recovery,
                    "recipe_coverage": self.recipe_coverage,
                    "pause": self.pause, "paused": self.paused,
                    "retry": sum(1 for r in self.results if retryable(r))}


class Dispatcher:
    """排任务步骤、起引擎子进程、收日志与事件（ADR-0004 / ADR-0010 / ADR-0011）。

    `on_error(operation, serial, detail)` 只回 recovery 文案，不认识上报块；
    `adb_of()` / `runner_of()` / `backups_of()` 在真正要用时取值：下载后 adb 路径会变，
    门面上的 runner / backups 也允许被调用方整体替换，两处必须读同一份。
    `chime()` / `link_lost()` / `adb_present(adb, serial)` 同样按调用时取：手机版整段换掉它们的说法，
    测试也会在构造之后换掉它们（#1383）。`summary` / `coverage_note` 是 `tool/` 模块本体、
    `plan_of()` 返回 `tool/plan.py`，三样都由构造方给，本模块不自己加载。
    """

    def __init__(self, runner_of, backups_of, data, adb_of, on_error, chime, link_lost, adb_present,
                 *, summary, coverage_note, plan_of):
        self.runner_of = runner_of
        self.backups_of = backups_of
        self.data = data
        self.adb_of = adb_of
        self.on_error = on_error
        self.chime = chime
        self.link_lost = link_lost
        self.adb_present = adb_present
        # 结果摘要与验证档位提示（#1189 #1188）：构造时取一次，别在 poll 的轮询热路径上现取
        self.summary = summary
        self.coverage_note = coverage_note
        self.plan_of = plan_of
        self.job = None
        self.lock = threading.Lock()
        self.side = ""                  # 正在跑的旁路操作（还原），与执行互斥（#662）

    def exclusive(self):
        """`ui_check()` 与 `start()` 互斥：持锁期间不许开新任务。"""
        return self.lock

    def busy(self):
        """调用方须持 `exclusive()` 的锁。"""
        return bool(self.job and self.job.running)

    def claim(self, name, wait=0.2):
        """占住「旁路操作」的位置（还原）：执行中或已有旁路操作时返回占着它的那件事的说明，占到了返回空串。
        还原与执行同时跑会互相点乱同一块屏，手机版上还原先结束还会把执行的保活一起撤掉（#662）。

        拿锁只等 `wait` 秒：`ui_check()` 持着同一把锁最长 75 秒，按界面按钮的线程不该被按在那里等，
        拿不到就直接回一句。"""
        if not self.lock.acquire(timeout=wait):
            return f"正在检查读屏连接，等它结束后再{name}"
        try:
            if self.busy():
                return f"正在执行去广告，等它结束后再{name}"
            if self.side:
                return f"「{self.side}」还没做完，请稍后"
            self.side = name
            return ""
        finally:
            self.lock.release()

    def release(self):
        with self.lock:
            self.side = ""

    def start(self, serial, plan, offered=None, base_results=(), base_lines=(), base_payloads=(),
              recipe_coverage=""):
        """plan: 这一轮的规格对象（`tool/plan.py` 的 `Plan`）；直接传字典也收，第一行用 `from_json` 收拢。
        offered: 选择页上摆出来的项，给没勾的项定「没执行」的原因（#577）；None 表示不知道。
        recipe_coverage: 这份机型脚本的验证档位，两个调用点各给各的：`Api.start()` 从 status-json 取，
        `Api.retry()` 沿用上一轮快照的值；都不在这里算（#1129）。
        三个 base_*: 重试轮从上一轮接管的快照（#638）；首次执行都是空的。"""
        plan = self.plan_of().Plan.from_json(plan)
        with self.lock:
            if self.job and self.job.running:
                return {"error": "已有任务在运行"}
            if self.side:
                return {"error": f"「{self.side}」还没做完，请稍后再开始"}
            tasks = plan_tasks(serial, plan, offered)
            total = sum(1 for t in tasks if not t.skip_reason)
            self.job = Job(serial=serial, model=plan.model, total=total, plan=plan,
                           recipe_coverage=recipe_coverage, plan_of=self.plan_of,
                           base_results=base_results, base_lines=base_lines,
                           base_payloads=base_payloads)
        threading.Thread(target=self._work, args=(tasks,), daemon=True).start()
        return {"ok": True, "total": total}

    def _log(self, s, job=None):
        """记一行输出。事件行只改状态、不进日志，返回 None；人话返回存下来的文本。
        载荷行（页面骨架、通知权限模式等机器数据）单独收着，上报时拼在末尾：不进界面日志与步骤摘要，也不会在
        「最近失败的完整诊断」里重复一遍。工作线程传入自己那一次的 Job：它比 `Api.job`
        活得久，收尾时不能写进下一次执行。"""
        job = self.job if job is None else job
        s = s.rstrip("\n")
        events = toolpath.tool("events")
        if events.is_event(s):
            self._event(events.parse_data(s), job)
            return None
        if events.is_payload(s):
            with job.lock:
                job.payloads.append(events.strip_payload(s))
            return None
        with job.lock:
            job.lines.append(s)
        return s

    def _event(self, data, job=None):
        """引擎事件（ADR-0004）：暂停 / 继续 / 锁屏改提示状态，`failed_steps` 记下段名，
        其余记进本步骤的事件集合；都不进日志、不上报。`data` 是 `events.parse_data()` 给出的整份字典。"""
        job = self.job if job is None else job
        if not data:                    # 前缀对上但解析不出来：当没有这个事件
            return
        kind = data["kind"]
        if kind == "paused":
            with job.lock:
                job.paused = True
            self.chime()                # 可以拿手机了
        elif kind == "resumed":
            with job.lock:
                job.paused = False
        elif kind == "locked":
            self.chime()                # 要机主来解锁
        elif kind == "failed_steps":
            # 载荷来自另一个进程：只认字符串列表，别的形状当没报（单个字符串会被逐字符拆成段名）
            steps = data.get("steps")
            named = isinstance(steps, list) and all(isinstance(s, str) for s in steps)
            with job.lock:
                job.failed_steps = [s.strip() for s in steps if s.strip()] if named else []
        else:
            with job.lock:
                job.step_events.add(kind)

    def _work(self, tasks):
        j = self.job
        ui_ok = True                    # 读屏一被占用就置否，此后带界面的步骤不再起（#603）
        done = 0                        # 真正跑过的步数：没执行的项不进「第 N / M 步」
        self.resume()                   # 上次没清掉的暂停标记不能带进这次
        for i, task in enumerate(tasks):
            if task.skip_reason:
                not_run_result(j, task)
                continue
            done += 1
            with j.lock:
                j.step_events = set()
                j.failed_steps = []
            if j.pause and not j.cancel:
                # 步骤之间的暂停；步骤里面的暂停由引擎在段与段、渠道与渠道之间处理
                with j.lock:
                    j.paused = True
                self.chime()            # 可以拿手机了：与引擎侧暂停点的提醒一致
                self._log("⏸ 已暂停：现在可以操作手机。操作完回到桌面、保持解锁，再点「继续」", j)
                while j.pause and not j.cancel:
                    time.sleep(0.5)
                with j.lock:
                    j.paused = False
                if not j.cancel:
                    self._log("▶ 继续执行", j)
            if j.cancel and not runs_after_stop(task):
                continue
            with j.lock:
                j.idx, j.title = done, task.title
            self._log(f"\n▶ {task.title}", j)
            if not ui_ok and task.uses_ui:
                reason = "读屏服务仍被占用，跳过本步骤；请先解决读屏连接再重试。"
                self._log(reason, j)
                j.add_result(step_result(task, rc=3, skipped=True, sec=0, tail=[reason]))
                continue
            line_start = len(j.lines)
            t = time.time()
            script, args = task.script, list(task.args)
            if task.channels is not None:
                d = self.backups_of().snapshot(j.model)
                fn = os.path.join(d, "channels.tsv")
                rows = ["# 包名\t渠道id\t渠道名\t应用名（客户端勾选）\n"]
                for c in task.channels:
                    name = re.sub(r"[\t\r\n]+", " ", str(c.get("app") or "")).strip()
                    rows.append(f"{c['pkg']}\t{c['id']}\t{c['name']}\t{name}\n")
                # 按字节写：`str.encode()` 默认就是 UTF-8，`chan_fast.load` 按 utf-8-sig 读得回来，
                # 换行也不需要经平台转一次
                Path(fn).write_bytes("".join(rows).encode())
                args = ["-s", j.serial, "off", fn]
            killed = False   # pragma: no mutate 语义等价：只当布尔用，None 与 False 同值
            try:
                p = self.runner_of().spawn(script, *args, env_extra={"AAC_PAUSE_FILE": self.data.pause,
                                                                     "AAC_EVENTS": "1"})
                with j.lock:
                    j.proc = p
                    # 停止落在 spawn 返回、登记之前：request_stop 看不到这个进程，由登记的一方补杀
                    killed = j.cancel and not runs_after_stop(task)
                if killed:
                    p.terminate()
                tail = []
                for line in p.stdout:
                    shown = self._log(line, j)  # 事件行返回 None：不进步骤摘要（前端会展示 tail）
                    if shown is not None:
                        tail.append(shown.strip()); tail = tail[-80:]
                rc = p.wait()
            except Exception as e:
                rc, tail = -1, [str(e)]
                self._log(f"✗ {e}", j)
            if (rc or killed) and j.cancel and not runs_after_stop(task):
                # 用户点了停止：不是出错、不重试，也不记诊断、不提示上报（错误日志 10-28：4 份是停止后上报的）
                j.add_result(step_result(task, rc=rc, stopped=True, sec=round(time.time() - t), tail=tail))
                continue
            j.add_result(step_result(task, rc=rc, sec=round(time.time() - t), tail=tail,
                                     failed_steps=list(j.failed_steps)))
            if rc:
                detail = "\n".join(j.lines[line_start:])
                ui_ok = ui_ok and "ui_busy" not in j.step_events
                if "link_lost" in j.step_events and not self.adb_present(self.adb_of(), j.serial):
                    # 手机已断开：后面每一步都会报同一段排查说明（错误日志 10-27），不再执行
                    self.on_error(task.title, j.serial, detail)
                    reason = self.link_lost()
                    for later in tasks[i + 1:]:
                        if later.skip_reason:      # 本来就不跑的项：原因照旧，不写成断线
                            not_run_result(j, later)
                            continue
                        self._log(f"\n▶ {later.title}\n{reason}", j)
                        j.add_result(step_result(later, rc=3, skipped=True, sec=0, tail=[reason]))
                    break
                recovery = self.on_error(task.title, j.serial, detail)
                if recovery:
                    with j.lock:
                        j.recovery = recovery
        self.resume()
        if not j.cancel:
            self.chime()                # 执行结束（成功或有步骤没成功都响，提醒回来看结果）
        with j.lock:
            # 收尾行与「结束」同一个临界区：看到 running=False 的快照一定已经带着这一行，
            # 且下一次执行要等它发布完才能接管。收尾行按同一个临界区里的 cancel 取，别在锁外算
            final = f"\n执行结束，用时 {round(time.time() - j.t0)} 秒" if not j.cancel else "\n已停止"
            self._log(final, j)
            j.running = False
            j.proc = None

    def poll(self, since=0):
        j = self.job
        if not j:
            return {"running": False, "lines": [], "next": 0}
        snap = j.snapshot(since)
        if snap["running"]:
            snap["results"] = []        # 执行中不显示结果（前端契约）；诊断与上报仍读快照里的全量
            snap["coverage_note"] = ""  # 结果页还没出来，这一行也没意义
        else:
            # 每条结果附一句话（#1189）：前端只显示这个字段，不再自己认日志模式
            snap["results"] = [{**r, "summary": self.summary.summarize(r)} for r in snap["results"]]
            # 验证档位提示也在这里算（#1188）：判据吃拍平后的结果，两个宿主同一个口径。
            # 宿主显式传 False，不读环境——用户 shell 里导出 AAC_HOST=phone 不该改桌面措辞（#747）。
            snap["coverage_note"] = self.coverage_note.note(snap, on_phone=False)
        return snap

    def stop(self):
        # 取 job、判 running 与置停止在同一把锁里：不然判完之后新一次执行顶上来，停掉的是它（#662）
        with self.lock:
            j = self.job
            if not (j and j.running):
                return True
            j.request_stop()
        self.resume()
        return True

    def pause(self):
        """执行中需要操作手机时用：引擎做完手头这一项（一个渠道、机型脚本的一段、一个步骤）就停下等待。"""
        with self.lock:
            j = self.job
            if not j or not j.running or j.cancel:
                return False
            self.data.ensure()
            Path(self.data.pause).write_text("", encoding="utf-8")
            j.request_pause()
        return True

    def resume(self):
        if self.job:
            self.job.clear_pause()
        try:
            os.remove(self.data.pause)
        except OSError:
            pass
        return True
