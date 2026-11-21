"""计划侧：这次排哪些任务、没执行的项怎么记、重试轮重跑什么（#1386）。

`Task` 携着子进程命令行，原先却与窗口桥、USB 诊断、上报并列住在 `gui/app.py` 里；搬出来之后
这一段能单独打开、单独测。步骤身份取自 `tool/plan.py` 的 `StepKind`，别处不再写字面量。
`gui/app.py` 留这 9 个名字的显式 re-export，`tests/` 与手机版照旧按 `app.<名字>` 取用。
"""
try:                                # 当包导入（测试）；直接跑脚本、打包时它是顶层模块
    from . import toolpath
except ImportError:
    import toolpath


class Task:
    """一个步骤。uses_ui：这一步要连读屏，前一步因读屏被占用失败时跳过它。
    channels 非 None 表示这一步是关营销通知：运行前把勾选的渠道写进 channels.tsv，
    args 由 `_work()` 换成 `-s <序列号> off <清单>`。
    skip_reason 非空表示这一步这次不跑：照样占结果里的一行，说明为什么（#577）。
    kind 是这一步的固定身份（`StepKind` 的六个成员之一，空串表示未标注），
    重试与多轮结果合并都按它对齐，不认标题（#638；标题里的「（3 / 9 段）」会变）。
    always_run 表示用户点「停止」之后这一步仍要跑完（收尾把手机改回不持续亮屏）。"""

    def __init__(self, title, script, args=(), uses_ui=False, channels=None, skip_reason="", kind="",
                 always_run=False):
        self.title, self.script, self.args = title, script, args
        self.uses_ui, self.channels = uses_ui, channels
        self.skip_reason, self.kind = skip_reason, kind
        self.always_run = always_run


def runs_after_stop(task):
    """停止后仍要跑的一步。由构造处声明（#1104）：改标题文案不再影响它跑不跑。"""
    return task.always_run


UNCHECKED = "未勾选，本次没有执行"


def not_run(title, reason, kind=""):
    """这次不跑的步骤：不碰手机，只在结果里留一行（#577）。"""
    return Task(title, "", skip_reason=reason, kind=kind)


def step_result(task, **fields):
    """结果里的一行：标题与 kind 从任务上取，其余字段各有各的。合并多轮结果时按 kind 对齐（#638）。"""
    return {"title": task.title, "kind": task.kind, **fields}


def not_run_result(job, task):
    """没执行的项进结果：rc=0 表示这一步没出错，界面按「跳过」显示、上报也写「跳过」；
    原因放 tail，摘要函数认不出模式时直接拿它当摘要。诊断里由 `skip_reason()` 压成一句。"""
    job.add_result(step_result(task, rc=0, skipped=True, sec=0, tail=[task.skip_reason]))


def plan_tasks(serial, plan, offered=None):
    """这次排哪些任务。勾了的照旧起脚本；没勾的留一行「跳过」并说明原因（#577）。

    `plan` 是前端发来的计划字典，或已经收好的 `Plan`（#1106；键与默认值在 `tool/plan.py`）。
    `offered` 是选择页上摆出来的项（调用方从检测结果与上一次通知扫描里取），用来区分
    「用户没勾」和「这台机本来就没有」；给 None 时不知道摆过什么，就不留这些行。
    每步的身份取自 `plan.StepKind`：重试与多轮结果合并都按它对齐（#1386）。"""
    plan_mod = toolpath.tool("plan")
    plan = plan_mod.Plan.from_json(plan)
    kind = plan_mod.StepKind
    tasks = []
    if plan.backup:
        tasks.append(Task("存改动前的快照", "run.py", ["-s", serial, "backup"], kind=kind.BACKUP))
    # msa 没挂起时它的开屏窗会抢走主题段的前台，所以挂起排在广告段之前（#968）
    ads = list(plan.ads)
    if ads:
        tasks.append(Task("挂起广告组件", "run.py", ["-s", serial, "suspend", *ads], kind=kind.ADS))
    elif offered is not None:
        seen = offered.get("ads") or []
        tasks.append(not_run("挂起广告组件",
                             "没有已知的广告组件" if not seen
                             else "广告组件已经挂起" if all(a.get("suspended") for a in seen)
                             else UNCHECKED,
                             kind=kind.ADS))
    steps = list(plan.steps)
    if steps:
        title = "关闭各 App 里的广告开关"
        total = len((offered or {}).get("steps") or [])
        if total > len(steps):
            title += f"（{len(steps)} / {total} 段）"
        tasks.append(Task(title, "run.py",
                          ["-s", serial, "recipe", *steps, *(["--ref"] if plan.ref else [])],
                          uses_ui=True, kind=kind.RECIPE))
    elif offered is not None:
        tasks.append(not_run("关闭各 App 里的广告开关",
                             UNCHECKED if offered.get("steps") else "没有专用脚本，这一步要照清单手动做",
                             kind=kind.RECIPE))
    channels = list(plan.channels)
    if channels:
        tasks.append(Task("关闭营销通知", "chan_fast.py", uses_ui=True, channels=channels, kind=kind.CHANNELS))
    elif offered is not None:
        seen = offered.get("channels")          # None 表示通知没扫成
        tasks.append(not_run("关闭营销通知",
                             "通知扫描没有完成，本次没有关闭营销通知" if seen is None
                             else "没有扫描到可关闭的营销渠道" if not seen else UNCHECKED,
                             kind=kind.CHANNELS))
    if plan.quickapp:
        tasks.append(Task("关闭快应用", "run.py", ["-s", serial, "quickapp", "off"], kind=kind.QUICKAPP))
    elif offered is not None:
        apps = offered.get("quickapps") or []
        tasks.append(not_run("关闭快应用",
                             "没有检测到快应用组件" if not apps
                             else "可关闭的快应用组件都已关闭" if all(q.get("closed") or q.get("keep") for q in apps)
                             else UNCHECKED,
                             kind=kind.QUICKAPP))
    # 重试轮只在收尾上一轮没做成时才跑它（#638）；首次执行取默认，照旧收尾
    if plan.finish:
        tasks.append(Task("收尾", "run.py", ["-s", serial, "finish"], kind=kind.FINISH, always_run=True))
    return tasks


def retryable(result):
    """这一步是不是没做成：失败，或因读屏被占用 / 断线 / 锁屏而跳过（#638）。

    除设备侧的原因外，子进程起不来（rc=-1）也算——这类重跑一次多半就好了。
    没勾选、这台机本来没有或已关、通知没扫成的那几档（#577）是 rc=0 的跳过，用户点「停止」的步带
    stopped，两者都不重试。
    """
    return bool(result.get("rc")) and not result.get("stopped")


def retry_plan(plan, results):
    """上一轮没做成的步骤组成的计划；一项都不剩时返回 None（#638）。

    广告开关步只重跑 `failed_steps` 里的段——脚本中途退出、没留下段名时才整段重跑。
    快照一旦成功就不再重存：重存会把已经关掉的状态当成原状，还原就还原不回去了。
    「通知没扫成」那一行不算可重试：扫描在选择页上就失败了，重跑这一步时的渠道清单本来就是空的，
    要重扫只能回选择页（#577 的第三档）。
    """
    plan_mod = toolpath.tool("plan")
    plan = plan_mod.Plan.from_json(plan or {})
    kind = plan_mod.StepKind
    retry = {r.get("kind") for r in results if r.get("kind") and retryable(r)}
    steps = []   # pragma: no mutate 语义等价：`Plan` 把 list 字段收成 []，None 与 [] 同值
    if kind.RECIPE in retry:
        recipe = next(r for r in results if r.get("kind") == kind.RECIPE)
        steps = list(recipe.get("failed_steps") or plan.steps)
    out = plan_mod.Plan(backup=kind.BACKUP in retry,
                        steps=steps, ref=plan.ref, model=plan.model,
                        channels=list(plan.channels) if kind.CHANNELS in retry else [],
                        quickapp=plan.quickapp and kind.QUICKAPP in retry,
                        ads=list(plan.ads) if kind.ADS in retry else [],
                        finish=kind.FINISH in retry)
    if not any((out.backup, out.steps, out.channels, out.quickapp, out.ads, out.finish)):
        return None
    return out
