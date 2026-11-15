# Xiaomi 15（24129PN74C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 热搜榜候选与浏览器直达入口的名单从这里进执行作用域。
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


def tail(p, rt):
    print(f"\n回读确认 {rt.verified} 项；步骤异常 {len(rt.failed_steps)} 个", flush=True)
