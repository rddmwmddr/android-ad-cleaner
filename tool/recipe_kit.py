"""机型脚本的执行作用域：`p`、`rt` 与共享助手由装载器写进来，脚本不再自己定义这些名字（沿用 #838）。

唯一的装载点是 `tool/recipe_loader.py`（ADR-0037）：它建出这次的 `rt`（`recipe_runtime.Runtime`），
调 `preamble(p, g, rt)` 把两个协作者、声明式段装饰器、跳过 / 断言 / 台账出口与两张注入面写进执行
作用域，再 `exec` 模块体。`@step` 只登记段名，真正执行由 `rt.run()` 负责——导入一份脚本不产生任何
设备动作。

脚本顶部那句 `from recipe_kit import step`（静态检查与编辑器用）落到本模块的 `step()`：它按「当前
这次执行」解析，同一时刻只允许一个活动执行（`Runtime.activate()`）。

公共导航助手另住 `recipe_nav`、公共段体另住 `recipe_steps`：`preamble()` 写完生命周期与台账后
依次调它们的 `install()`，本模块只管生命周期与台账（沿用 #1150、#1209 的注入面）。
"""

import re

import adb_link
import recipe_nav
import recipe_steps
from recipe_runtime import DONE as DONE, FAILED as FAILED, NOT_RUN as NOT_RUN, SKIPPED as SKIPPED
from recipe_runtime import DuplicateStep as DuplicateStep, MissingPackage as MissingPackage
from recipe_runtime import Runtime, SkipStep

# 静态导入 `from recipe_kit import p, rt, step` 的落点：前两个只给编辑器与类型检查看，真正的对象
# 每次装载由 `preamble()` 换掉；`step()` 按当前执行解析。
p = None
rt = None
_runtime = None

# `Phone.start` 里「落点不对」的两句。只有这两类才按落点判入口不可达：
# 「本机没有安装 / 无法打开」时前台可能只是桌面，不能当成证据（#902）。
WRONG_LANDING = ("没有进入前台", "启动后离开前台")
# 那两句里的落点原文 `停在 包名/页面；…`。从报错里取，不再重读前台：
# 抛出之后再读有一小段窗口期，前台已经切走就会判错。
LANDING = re.compile(r"停在 ([^\s/；]+)")
# 整页关闭的段落在安全模式下的跳过原因（#909）
SAFE_MODE_PAGE_WIDE = "安全模式不做整页全关：本段没有可点名的开关，请按清单手动关"


def preamble(p, g, rt=None):
    """把这次的执行写进 `g` 并原样返回它：`p` / `rt` / 声明式 `step`、出口与两个台账、两张注入面。

    `rt` 由装载器建好传进来（`tool/recipe_loader.py`）；测试直接调用时不传，按 `g` 里现有的
    `ONLY` 建一个新的。台账是 rt 上的同一批列表对象，`g["FAILED_STEPS"]` 等只是给既有调用点与
    测试读的别名——写台账的只有 `Runtime.run_step()`。

    `guard()` / `wrap()` / `detail()` / `tail()` 是四个可选的脚本侧钩子：段入口的型号守卫、
    段内包装（等价于以前 `with safe_ui():`）、失败时的页面摘要、收尾打印。脚本定义了就按它走，
    没定义就什么都不做 —— 大多数脚本不需要，前导也不替它们造一个。
    """
    global _runtime
    from fast import ScreenLocked     # fast 在顶部 import 本模块，取在调用时才不绕进循环

    if rt is None:
        rt = Runtime(p, list(g.get("ONLY") or []))
    elif "ONLY" in g and g.get("ONLY") is not None:
        rt.only = g["ONLY"]           # 测试传进来的名单对象要保留：装载后改它仍然生效
    rt.namespace = g
    _runtime = rt
    globals()["p"] = p
    globals()["rt"] = rt

    g["p"] = p
    g["rt"] = rt
    g["ONLY"] = rt.only
    g["FAILED_STEPS"] = rt.failed_steps
    g["SKIPPED_STEPS"] = rt.skipped_steps
    g["HALTED_STEPS"] = rt.halted_steps
    g["RESULTS"] = rt.results
    g["step"] = rt.step

    def require(ok, reason):
        rt.require(ok, reason)

    def skip(reason):
        rt.skip(reason)

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

    def page(title, package=None, activity=None):
        """确认当前页面落在预期上：包名、Activity、页面标题三段判据（#939）。

        三段失败时先 `p.note_miss()` 留一行与入口失败同形的现场（停在哪个 Activity、
        结构摘要），再抛原来的错：报错文案是上报与用例逐字认的第一句，现场只走那条
        独立输出行。没有它，`未确认页面「游戏中心」` 分不清是标题改名还是页面没加载完。
        现场行里「没找到」的是这一段缺的那样东西（包名 / Activity / 标题），不是一律写标题：
        落点跑偏时标题往往就在屏上，写成标题会把人引去查改名。
        等待由引擎负责；页面即使已经站稳也必须过这三段，旧页不能当成目标页。
        `title` 给一组时任一出现即算到页；`package` / `activity` 按 `包名/Activity` 判。
        """
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
            skip("出现协议或权限申请，不代为同意")
        if p.locked():
            raise ScreenLocked("手机锁屏，请机主解锁")

    def skip_in_safe_mode():
        """整页关闭的段落在安全模式下按跳过结束（#909）：只记跳过台账，不动失败台账与退出码。"""
        if p.safe_mode:
            skip(SAFE_MODE_PAGE_WIDE)

    def start_or_skip(pkg, activity, dead_ends, reason):
        """拉起 App；前台没到、报错里的落点又在前 `dead_ends` 里时按跳过结束本段，不算失败。

        给「本机缺了配套 App，入口会被系统转去别处」这一类用（#902：没有主题商店时，
        主题管理包的代理页会落到应用商店详情页或桌面）。落点在别的 App、或失败根本不是
        「落点不对」（拉不起来）时照旧上抛，保留 `Phone.start` 的落点诊断（#547）；
        包没装时 `Phone.start` 抛的是 `MissingPackage`，上抛后由段包装记跳过（#908）。"""
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

    g.update({"SkipStep": SkipStep, "skip": skip, "require": require,
              "maybe": maybe, "start_or_skip": start_or_skip, "page": page,
              "require_switches": require_switches, "skip_in_safe_mode": skip_in_safe_mode,
              "VERIFIED_SWITCHES": rt.counter})
    recipe_nav.install(p, g)
    recipe_steps.install(p, g)
    return g


def step(name):
    """脚本顶部 `from recipe_kit import step` 的落点：按当前这次执行登记段名。

    装载器先往执行作用域里写一份绑定当次执行的 `step`，脚本的静态导入随后把名字换成这一份；
    两者都只登记、不执行（ADR-0037）。没有活动执行时抛错，而不是把段悄悄丢掉。
    """
    if _runtime is None:
        raise RuntimeError("机型脚本必须在 recipe_loader 装载的执行里运行：当前没有活动执行（rt）")
    return _runtime.step(name)
