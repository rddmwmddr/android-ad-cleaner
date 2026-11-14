"""这次执行（`rt`）：段过滤、跳过出口、必需断言、安全模式、分段台账、失败段与中止、时钟、回读确认数。

机型脚本只拿两个协作者：`p`（设备面，公开面冻结）与 `rt`（这一次执行）。台账由引擎写、脚本只读；
脚本要表达「回读确认了几项」只能调 `rt.confirm()`，不能自己累加（沿用 #838 的台账，#1241 把计数收进 rt）。

段包装在 `Runtime.run_step()`：解释器把数据段包成 action、按声明顺序执行，顺序与旧脚本相同；
行为判据是 47 份数据的调用序列快照（`tests/snapshots/recipe_calls/`）。
"""
import re
import time
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import adb_link

# 每个段的结局用这四个词记一条（机型脚本的分段结果台账）
DONE, SKIPPED, FAILED, NOT_RUN = "完成", "跳过", "未完成", "未执行"

# `start_or_skip` 里「落点不对」的两句。只有这两类才按落点判入口不可达：
# 「本机没有安装 / 无法打开」时前台可能只是桌面，不能当成证据（#902）。
WRONG_LANDING = ("没有进入前台", "启动后离开前台")
# 那两句里的落点原文 `停在 包名/页面；…`。从报错里取，不再重读前台：
# 抛出之后再读有一小段窗口期，前台已经切走就会判错。
LANDING = re.compile(r"停在 ([^\s/；]+)")
# 整页关闭的段落在安全模式下的跳过原因（#909）
SAFE_MODE_PAGE_WIDE = "安全模式不做整页全关：本段没有可点名的开关，请按清单手动关"


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
    """回读确认计数器（`rt.counter`）：`+=` 就是 `rt.confirm()`，读出来是 rt 上的数。

    老脚本用 `VERIFIED_SWITCHES += n` 记账的那两段（oppo-PLG110 / PMA110），`+=` 仍经 rt 记账，
    而不是在脚本里留一份自己的数；其余地方直接调 `rt.confirm(n)`。
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
        # 每机型常量：toml 的 `[const]` 与例外 `.py` 的模块级全大写名字（只读视图，值共享）。
        self.constants: Mapping[str, Any] = MappingProxyType({})
        # 本机助手跨函数传的「刚确认落到的包名」（魅族 `wait_page` 写、`tap_id` 读）。
        self.target = ""

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
        """必需入口断言：不成立就按这一段失败收场。"""
        if not ok:
            raise RuntimeError(reason)

    def skip(self, reason) -> None:
        """按约定不跑：抛跳过类，结局记「跳过」。"""
        raise SkipStep(reason)

    def require_switches(self, before, names, title, optional=(), contains=False) -> None:
        """点名要关的开关没全部出现时整段不动，并把页面证据带进报错（#903）。

        `before` 是这次读到的开关（{标题: 状态}，按页面顺序）：报错里带上停在哪个页、结构摘要
        与当次读到的标题，下一轮上报才能分辨「改名了 / 页面是空的 / 页面根本没打开」。
        `contains=True` 表示名单是关键词，标题附带整段说明也算命中（小米系脚本的写法）；
        默认要求标题与名单逐字相同。`optional` 里的名字允许这次没有。
        名单为空也算没识别到：整页开关那条路（页面上有哪行关哪行）一页空着同样是失败。
        成功时不建这段证据，也不重读页面，输出与加它之前逐字一致。
        """
        def found(name):
            if name in optional:
                return True
            return any(name in t for t in before) if contains else name in before

        if names and all(found(name) for name in names):
            return
        raise RuntimeError(f"{title}：未识别全部目标开关，未操作；{self.p.page_evidence(list(before))}")

    def page(self, title, package=None, activity=None) -> None:
        """确认当前页面落在预期上：包名、Activity、页面标题三段判据（#939）。

        三段失败时先 `p.note_miss()` 留一行与入口失败同形的现场（停在哪个 Activity、
        结构摘要），再抛原来的错：报错文案是上报与用例逐字认的第一句，现场只走那条
        独立输出行。没有它，`未确认页面「游戏中心」` 分不清是标题改名还是页面没加载完。
        现场行里「没找到」的是这一段缺的那样东西（包名 / Activity / 标题），不是一律写标题：
        落点跑偏时标题往往就在屏上，写成标题会把人引去查改名。
        等待由引擎负责；页面即使已经站稳也必须过这三段，旧页不能当成目标页。
        `title` 给一组时任一出现即算到页；`package` / `activity` 按 `包名/Activity` 判。
        """
        from fast import ScreenLocked
        p = self.p
        p.await_page(budget=6)
        where = p.focus()
        titles = (title,) if isinstance(title, str) else tuple(title)

        def miss(found, reason):
            p.note_miss(found)
            raise RuntimeError(reason)

        if package and where.split("/", 1)[0] != package:
            miss(package, "未进入目标应用，未操作开关")
        if activity and activity not in where.split("/", 1)[-1]:
            miss(activity, "未进入目标设置页，未操作开关")
        if not any(p.find(t, exact=True) for t in titles):
            miss(" / ".join(titles), f"未确认页面「{'、'.join(titles)}」，未操作开关")
        if any(text in {"同意", "同意并继续", "同意并使用", "允许", "仅在使用中允许"}
               and "Button" in node.get("class", "") for text, _, node in p.texts()):
            p.dismiss()
            self.skip("出现协议或权限申请，不代为同意")
        if p.locked():
            raise ScreenLocked("手机锁屏，请机主解锁")

    def skip_in_safe_mode(self) -> None:
        """整页关闭的段落在安全模式下按跳过结束（沿用 #909）：只记跳过台账，不动失败台账与退出码。"""
        if self.safe_mode:
            self.skip(SAFE_MODE_PAGE_WIDE)

    def start_or_skip(self, pkg, activity, dead_ends, reason) -> None:
        """拉起 App；前台没到、报错里的落点又在前 `dead_ends` 里时按跳过结束本段，不算失败。

        给「本机缺了配套 App，入口会被系统转去别处」这一类用（#902）。落点在别的 App、或失败
        根本不是「落点不对」（拉不起来）时照旧上抛，保留 `Phone.start` 的落点诊断（#547）。
        """
        p = self.p
        try:
            p.start(pkg, activity)
        except adb_link.DeviceLost:
            raise                       # 断线不是入口不可达：整轮停下，不按跳过收尾
        except RuntimeError as error:
            lost = str(error)
            landed = LANDING.search(lost)
            if landed and landed.group(1) in dead_ends and any(mark in lost for mark in WRONG_LANDING):
                self.skip(f"{reason}（停在 {landed.group(1)}）")
            raise

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
            tail(self.p, self)

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
                guard(p, self)          # 型号 / 版本守卫：抛什么就按什么结局记
            if p.locked():
                raise ScreenLocked("手机锁屏了，请机主解锁后重跑")
            wrap = namespace.get("wrap")
            with (wrap(p, self) if wrap is not None else nullcontext()):
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
                print(f"  · {detail(p, self)}", flush=True)
        if outcome is False:
            state = FAILED              # 段体自己说没做成：只影响分段结果，与迁移前一致
        self.results.append((name, state))
        print(f"  ({self.clock.monotonic() - started:.0f} 秒)", flush=True)
        return action
