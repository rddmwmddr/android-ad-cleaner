"""机型脚本的前导：段包装、必需入口断言、可选入口助手、跳过出口与两个台账（#838）。

三个执行点注入同一份：`fast.execute` 的 run 分支、`adapt.check_draft`、`tests/fixtures.load_recipe`。
不做成可 import 的函数：段包装要绑定当次的 Phone 与执行作用域，import 来的模块级函数拿不到这两个。
脚本自己的同名定义后执行、覆盖注入的名字，所以在迁移之前跑任何现有脚本，用户看到的东西一个字节都不变。
"""

import time

import adb_link


class SkipStep(RuntimeError):
    """这一条按约定不跑（型号 / 版本不符、必须机主手动进入），不算失败。"""


def preamble(p, g):
    """前导写进 `g` 后原样返回它，调用点写成 `recipe_kit.preamble(p, g)`。

    段包装与助手读 `g` 而不捕获初值：脚本重绑 ONLY / FAILED_STEPS 后立刻生效，
    测试装载之后再改名单驱动单段也生效。`SkipStep` 同样按 `g` 里的当前值取——
    脚本只换跳过异常类、仍用注入的段包装时，抛的和接的仍是同一个类。
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

    def step(name):
        def decorate(action):
            if g["ONLY"] and name not in g["ONLY"]:
                return action
            if g["HALTED"]:
                # 中止之后不再碰手机：不读锁屏、不碰页面，只把这一条记成「未执行」。
                g["FAILED_STEPS"].append(name)
                g["HALTED_STEPS"].append(name)
                print(f"\n== {name}", flush=True)
                print("  · 未执行：前一段中止了整批", flush=True)
                return action
            print(f"\n== {name}", flush=True)
            p.miss = 0
            started = time.monotonic()
            try:
                if p.locked():
                    raise ScreenLocked("手机锁屏了，请机主解锁后重跑")
                action()
            except adb_link.DeviceLost:
                raise                  # 断线交还引擎：整轮停下，不逐段报
            except g.get("SkipStep", SkipStep) as reason:
                g["SKIPPED_STEPS"].append(name)
                print(f"  · 跳过：{reason}", flush=True)
            except Exception as error:
                g["FAILED_STEPS"].append(name)
                if isinstance(error, ScreenLocked):
                    g["HALTED"] = True
                print(f"  ✗ 未完成：{error}", flush=True)
            print(f"  ({time.monotonic() - started:.0f} 秒)", flush=True)
            return action
        return decorate

    g.update({"SkipStep": SkipStep, "skip": skip, "require": require,
              "maybe": maybe, "step": step})
    return g
