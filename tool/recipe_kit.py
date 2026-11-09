"""机型脚本的前导：段包装、必需入口断言、开关名单断言、可选入口助手、跳过出口与两个台账（#838）。

三个执行点注入同一份：`fast.execute` 的 run 分支、`adapt.check_draft`、`tests/fixtures.load_recipe`。
不做成可 import 的函数：段包装要绑定当次的 Phone 与执行作用域，import 来的模块级函数拿不到这两个。
脚本自己的同名定义后执行、覆盖注入的名字，所以在迁移之前跑任何现有脚本，用户看到的东西一个字节都不变。
"""

import re
import time
from contextlib import nullcontext

import adb_link

# 脚本自带 `RESULTS` 时，每个段的结局用这四个词记一条（机型脚本的分段结果台账）
DONE, SKIPPED, FAILED, NOT_RUN = "完成", "跳过", "未完成", "未执行"

# `Phone.start` 里「落点不对」的两句。只有这两类才按落点判入口不可达：
# 「本机没有安装 / 无法打开」时前台可能只是桌面，不能当成证据（#902）。
WRONG_LANDING = ("没有进入前台", "启动后离开前台")
# 那两句里的落点原文 `停在 包名/页面；…`。从报错里取，不再重读前台：
# 抛出之后再读有一小段窗口期，前台已经切走就会判错。
LANDING = re.compile(r"停在 ([^\s/；]+)")


class SkipStep(RuntimeError):
    """这一条按约定不跑（型号 / 版本不符、必须机主手动进入），不算失败。"""


def preamble(p, g):
    """前导写进 `g` 后原样返回它，调用点写成 `recipe_kit.preamble(p, g)`。

    段包装与助手读 `g` 而不捕获初值：脚本重绑 ONLY / FAILED_STEPS 后立刻生效，
    测试装载之后再改名单驱动单段也生效。`SkipStep` 同样按 `g` 里的当前值取——
    脚本只换跳过异常类、仍用注入的段包装时，抛的和接的仍是同一个类。

    `guard()` / `wrap()` / `detail()` / `RESULTS` 是四个可选的脚本侧钩子：段入口的型号守卫、
    段内包装（等价于以前 `with safe_ui():`）、失败时的页面摘要、分段结果台账。脚本定义了就按它走，
    没定义就什么都不做 —— 大多数脚本不需要，前导也不替它们造一个。
    """
    from fast import ScreenLocked     # fast 在顶部 import 本模块，取在调用时才不绕进循环

    g.setdefault("ONLY", [])
    g.setdefault("FAILED_STEPS", [])
    g.setdefault("SKIPPED_STEPS", [])
    g.setdefault("HALTED_STEPS", [])
    g.setdefault("HALTED", False)

    def require(ok, reason):
        if not ok:
            raise RuntimeError(reason)

    def skip(reason):
        raise g.get("SkipStep", SkipStep)(reason)

    def maybe(name, scrolls=6):
        return p.entry(name, scrolls=scrolls)

    def require_switches(before, names, title, optional=(), contains=False):
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
        raise RuntimeError(f"{title}：未识别全部目标开关，未操作；{p.page_evidence(list(before))}")

    def start_or_skip(pkg, activity, dead_ends, reason):
        """拉起 App；前台没到、报错里的落点又在前 `dead_ends` 里时按跳过结束本段，不算失败。

        给「本机缺了配套 App，入口会被系统转去别处」这一类用（#902：没有主题商店时，
        主题管理包的代理页会落到应用商店详情页或桌面）。落点在别的 App、或失败根本不是
        「落点不对」（没装 / 拉不起来）时照旧上抛，保留 `Phone.start` 的落点诊断（#547）。"""
        try:
            p.start(pkg, activity)
        except adb_link.DeviceLost:
            raise                       # 断线不是入口不可达：整轮停下，不按跳过收尾
        except RuntimeError as error:
            lost = str(error)
            landed = LANDING.search(lost)
            if landed and landed.group(1) in dead_ends and any(mark in lost for mark in WRONG_LANDING):
                skip(f"{reason}（停在 {landed.group(1)}）")
            raise

    def step(name):
        def decorate(action):
            if g["ONLY"] and name not in g["ONLY"]:
                return action
            # 段体在装饰那一刻就跑（`@step` 是执行式装饰器），所以这里读到的都是脚本自己
            # 已经赋值过的：钩子要写在第一个 `@step` 之前，见 docs/04。
            results = g.get("RESULTS")
            if g["HALTED"]:
                # 中止之后不再碰手机：不读锁屏、不碰页面，只把这一条记成「未执行」。
                g["FAILED_STEPS"].append(name)
                g["HALTED_STEPS"].append(name)
                if results is not None:
                    results.append((name, NOT_RUN))
                print(f"\n== {name}", flush=True)
                print("  · 未执行：前一段中止了整批", flush=True)
                return action
            print(f"\n== {name}", flush=True)
            p.miss = 0
            started = time.monotonic()
            state = DONE
            outcome = None
            try:
                guard = g.get("guard")
                if guard is not None:
                    guard()                 # 型号 / 版本守卫：抛什么就按什么结局记
                if p.locked():
                    raise ScreenLocked("手机锁屏了，请机主解锁后重跑")
                wrap = g.get("wrap")
                with (wrap() if wrap is not None else nullcontext()):
                    outcome = action()      # 脚本可选的段内包装（等价于以前 `with safe_ui():`）
            except adb_link.DeviceLost:
                raise                  # 断线交还引擎：整轮停下，不逐段报
            except g.get("SkipStep", SkipStep) as reason:
                g["SKIPPED_STEPS"].append(name)
                state = SKIPPED
                print(f"  · 跳过：{reason}", flush=True)
            except Exception as error:
                g["FAILED_STEPS"].append(name)
                state = FAILED
                if isinstance(error, ScreenLocked):
                    g["HALTED"] = True
                print(f"  ✗ 未完成：{error}", flush=True)
                detail = g.get("detail")
                if detail is not None:
                    print(f"  · {detail()}", flush=True)
            if outcome is False:
                state = FAILED             # 段体自己说没做成：只影响分段结果，与迁移前一致
            if results is not None:
                results.append((name, state))
            print(f"  ({time.monotonic() - started:.0f} 秒)", flush=True)
            return action
        return decorate

    g.update({"SkipStep": SkipStep, "skip": skip, "require": require,
              "maybe": maybe, "start_or_skip": start_or_skip, "step": step,
              "require_switches": require_switches})
    return g
