# 一加 Ace 2 Pro（PJA110，ColorOS 14）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 tap / close_named 与 require 由装载器注入执行作用域；线性段已转数据，这里只留手势段与尾钩子。
import time
import recipe_nav as nav


def step_search(p, rt):
    """桌面下滑手势的参数按屏宽屏高现算，数据里写不下，逐字保留原段体。"""
    p.d.shell("input keyevent HOME"); time.sleep(.6)
    p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); time.sleep(1)
    p.d.shell("input keyevent BACK"); time.sleep(.4)
    rt.require(p.focus().split("/", 1)[0] == "com.heytap.quicksearchbox", "未进入下拉搜索")
    nav.tap(p, rt, "设置")
    nav.tap(p, rt, "账号与隐私")
    nav.tap(p, rt, "隐私")
    nav.close_named(p, rt, ["个性化推荐"], "下拉搜索·隐私")


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)
