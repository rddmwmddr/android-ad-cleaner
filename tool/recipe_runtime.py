"""这次执行（`rt`）：段过滤、跳过出口、必需断言、安全模式、分段台账、失败段与中止、时钟、回读确认数。

机型脚本只拿两个协作者：`p`（设备面，公开面冻结）与 `rt`（这一次执行）。台账由引擎写、脚本只读；
脚本要表达「回读确认了几项」只能调 `rt.confirm()`，不能自己累加（沿用 #838 的台账，#1241 把计数收进 rt）。

段包装从 `recipe_kit.preamble()` 搬到这里（ADR-0037）：`@step` 现在只登记段名并原样返回函数，
装载器按定义行号排序、由 `Runtime.run()` 逐段执行；顺序与「导入即执行」那一版相同，行为判据是
47 份脚本的调用序列快照（`tests/snapshots/recipe_calls/`）。
"""
import time
from contextlib import nullcontext
from dataclasses import dataclass

import adb_link

# 每个段的结局用这四个词记一条（机型脚本的分段结果台账）
DONE, SKIPPED, FAILED, NOT_RUN = "完成", "跳过", "未完成", "未执行"


class SkipStep(RuntimeError):
    """这一条按约定不跑（型号 / 版本不符、必须机主手动进入），不算失败。"""


class MissingPackage(SkipStep):
    """这一段要用的 App 本机没装（沿用 #908）：结局与「按约定不跑」同一档，来源在引擎的 `Phone.start`。"""


class DuplicateStep(RuntimeError):
    """同一个脚本里两个 `@step` 用了同一个段名：失败段与客户端重试都按段名定位，必须唯一。"""


@dataclass(frozen=True)
class Step:
    """一个声明式段：段名、函数体、定义行号（顺序按它排，与源码书写顺序一致）。"""
    name: str
    action: object
    line: int


# 同一时刻只允许一个活动执行：两个脚本同时跑会争抢同一个设备，段名与台账也会互相串。
_ACTIVE = None
# 调用序列快照（#1239）按段归属调用：装载器/驱动换掉 `step` 那一层时靠它拿到当前段名。
OBSERVER = None


class Active:
    """一次执行占用设备的凭据；第二个开始时抛错而不是静默并行。"""

    def __init__(self, rt):
        self.rt = rt

    def __enter__(self):
        global _ACTIVE
        if _ACTIVE is not None:
            raise RuntimeError("同一时刻只允许一个活动执行：上一个机型脚本还没跑完")
        _ACTIVE = self.rt
        return self.rt

    def __exit__(self, *exc):
        global _ACTIVE
        _ACTIVE = None


class Counter:
    """注入到执行作用域的 `VERIFIED_SWITCHES`：`+=` 就是 `rt.confirm()`，读出来是 rt 上的数。

    两段脚本（oppo-PLG110 / PMA110）的 `+=` 写在段体里，段体正文一个字都不能动（台账哈希
    的判据）。给它们一个引擎写的计数器，`VERIFIED_SWITCHES += n` 因此仍经 rt 记账，而不是
    在脚本里留一份自己的数。其余脚本的模块级助手直接调 `rt.confirm(n)`。
    """

    def __init__(self, rt):
        self._rt = rt

    def __iadd__(self, count):
        self._rt.confirm(count)
        return self

    def __int__(self):
        return self._rt.verified

    def __index__(self):
        return self._rt.verified

    def __eq__(self, other):
        return self._rt.verified == (other._rt.verified if isinstance(other, Counter) else other)

    def __hash__(self):
        return hash(self._rt.verified)

    def __repr__(self):
        return str(self._rt.verified)


class Runtime:
    """这一次执行的全部可变状态。引擎写台账，脚本读。"""

    def __init__(self, p, only=(), clock=None):
        self.p = p
        self.only = list(only)          # 空 = 全部段；非空 = 只跑这些段名（sentinel 名字用于「一段不跑」）
        self.clock = clock or time      # `sleep` / `time` / `monotonic` 三个读数成套使用
        self.steps: list[Step] = []
        self.results: list[tuple[str, str]] = []
        self.failed_steps: list[str] = []
        self.skipped_steps: list[str] = []
        self.halted_steps: list[str] = []
        self.halted = False
        self.namespace: dict | None = None
        self.counter = Counter(self)
        self._verified = 0

    @property
    def verified(self) -> int:
        """回读确认关闭了几项。只读：脚本经 `confirm()` 记，不能直接改这个数。"""
        return self._verified

    @property
    def safe_mode(self) -> bool:
        """这次执行是不是安全模式（只关点名的开关）。实体仍归 `Phone` / 拨动会话，公开面冻结。"""
        return self.p.safe_mode

    @safe_mode.setter
    def safe_mode(self, value) -> None:
        self.p.safe_mode = value

    def confirm(self, count=1) -> None:
        """记「回读确认了几项」。脚本唯一的写入入口，参数是这一次确认的条数。"""
        if count:
            self._verified += int(count)

    def require(self, ok, reason) -> None:
        """必需入口断言：不成立就按这一段失败收场（与 `preamble` 注入的 `require` 同一份语义）。"""
        if not ok:
            raise RuntimeError(reason)

    def skip(self, reason) -> None:
        """按约定不跑：抛当前命名空间里的跳过类（脚本自定义 `SkipStep` 时抛它，否则抛引擎这一份）。"""
        cls = (self.namespace or {}).get("SkipStep") or SkipStep
        raise cls(reason)

    def activate(self) -> Active:
        """占用「当前执行」；同一时刻只允许一个。"""
        return Active(self)

    def step(self, name):
        """声明式段装饰器：只登记段名并原样返回函数，不在装饰那一刻执行任何东西。"""
        def decorate(action):
            if any(existing.name == name for existing in self.steps):
                raise DuplicateStep(f"段名重复：{name!r}；失败段与客户端重试都按段名定位，必须唯一")
            self.steps.append(Step(name, action, action.__code__.co_firstlineno))
            return action
        return decorate

    def run(self) -> None:
        """按定义行号逐段执行，最后调用脚本声明的尾钩子 `tail()`（没有就不做）。

        断线（`adb_link.DeviceLost`）照旧整轮上抛，尾钩子不执行——与模块体在段后被打断时一致。
        """
        for step in sorted(self.steps, key=lambda item: item.line):
            self.run_step(step.name, step.action)
        tail = (self.namespace or {}).get("tail")
        if callable(tail):
            tail()

    def run_step(self, name, action):
        """跑一段（段包装）：过滤、中止、锁屏、守卫、段内包装、结局与计时都只在这里定义。

        段体自己 `return False` 表示「这一段没做全」，只影响分段落点，不影响退出码（沿用 #838）。
        """
        if OBSERVER is not None:
            OBSERVER(name)
        if self.only and name not in self.only:
            return action
        p = self.p
        if self.halted:
            # 中止之后不再碰手机：不读锁屏、不碰页面，只把这一条记成「未执行」。
            self.failed_steps.append(name)
            self.halted_steps.append(name)
            self.results.append((name, NOT_RUN))
            print(f"\n== {name}", flush=True)
            print("  · 未执行：前一段中止了整批", flush=True)
            return action
        from fast import ScreenLocked      # fast 在顶部 import recipe_kit，取在调用时才不绕进循环
        namespace = self.namespace or {}
        # 脚本可以换掉跳过异常类（只换类、仍用引擎的段包装）：抛的和接的必须是同一个类。
        skip_class: type[BaseException] = namespace.get("SkipStep") or SkipStep
        print(f"\n== {name}", flush=True)
        p.screen.captures.step = name      # 失败现场按段归档（沿用 #1126）
        p.miss = 0
        started = self.clock.monotonic()
        state = DONE
        outcome = None
        try:
            guard = namespace.get("guard")
            if guard is not None:
                guard()                 # 型号 / 版本守卫：抛什么就按什么结局记
            if p.locked():
                raise ScreenLocked("手机锁屏了，请机主解锁后重跑")
            wrap = namespace.get("wrap")
            with (wrap() if wrap is not None else nullcontext()):
                outcome = action()      # 脚本可选的段内包装（等价于以前 `with safe_ui():`）
        except adb_link.DeviceLost:
            raise                       # 断线交还引擎：整轮停下，不逐段报
        except (skip_class, MissingPackage) as reason:
            self.skipped_steps.append(name)
            state = SKIPPED
            print(f"  · 跳过：{reason}", flush=True)
        except Exception as error:
            self.failed_steps.append(name)
            state = FAILED
            p.screen.save_capture()     # 这一段的失败现场（沿用 #1126）；探路留下的那张不算失败
            if isinstance(error, ScreenLocked):
                self.halted = True
            print(f"  ✗ 未完成：{error}", flush=True)
            detail = namespace.get("detail")
            if detail is not None:
                print(f"  · {detail()}", flush=True)
        if outcome is False:
            state = FAILED              # 段体自己说没做成：只影响分段结果，与迁移前一致
        self.results.append((name, state))
        print(f"  ({self.clock.monotonic() - started:.0f} 秒)", flush=True)
        return action
