# Xiaomi 15（24129PN74C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 应用商店的「个性化服务」按运行时读到的开关位置分岔：新版本是子页入口、老版本开关就在本页。
import time
from dataclasses import replace

# `entries.reach` 留在执行作用域里：`recipe_nav.direct_settings` 按 `g["reach"]` 取它。
from entries import ENTRIES, reach
import recipe_nav as nav
import recipe_steps as steps


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]

# 浏览器段的入口页是设置页本身。分组里的另一条直达是「个性化推荐设置」子页：直接落过去时
# 后面几个设置页入口都找不到、整段 0 项空跑，所以回退链只取设置页那一条（#912）。
# `recipe_nav.direct_settings` 按名字从执行作用域取。
_BROWSER = ENTRIES["xiaomi"]["浏览器"]
BROWSER_SETTINGS_ENTRY = replace(
    _BROWSER, direct=tuple(d for d in _BROWSER.direct if d.activity == ".BrowserSettingsActivity"))


def step_store(p, rt):
    # 2026-10-29 实测：冷启动落「福利推广页」→ 先回首页。
    # 「我的」用 p.tab()：底部带过滤把内容区里同名的文字挡在外面（#386）。
    p.start("com.xiaomi.market")
    time.sleep(2.5)
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0)
        time.sleep(2)
    rt.require(p.tab("我的"), "商店底部「我的」标签没找到")
    time.sleep(2)
    rt.require(p.tap("设置", exact=True, scrolls=4), "商店设置图标没找到")
    time.sleep(1)
    # 本版没有「隐私设置/个性化服务」和「秒装」，有就关，没有就跳过。
    if nav.maybe(p, rt, "隐私设置"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or nav.maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务", "个性化推荐"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关，关了会连点赞/评论消息一起关。
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置")
        p.back()
    # 模式切换：保持标准模式，不切极简。
    p.back(2)


def tail(p, rt):
    print(f"\n回读确认 {rt.verified} 项；步骤异常 {len(rt.failed_steps)} 个", flush=True)
