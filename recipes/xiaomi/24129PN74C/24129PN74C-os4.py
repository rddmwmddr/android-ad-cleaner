# Xiaomi 15 HyperOS 4 变体（24129PN74C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 只剩全局搜索一段：榜单子页要按屏上读到的分类现算再遍历，是读屏收窄名单 + 循环。
from entries import THEME_DEAD_ENDS
import recipe_nav as nav


def step_global_search(p, rt):
    HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if nav.maybe(p, rt, "首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if nav.maybe(p, rt, "应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示常用应用"], page="搜索·应用推荐"); p.back()
        if nav.maybe(p, rt, "热搜榜单"):
            subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
            if p.switches():
                p.off(only=HOT, page="搜索·热搜榜单")
            if subs:
                p.top()
                for x in subs:
                    if nav.maybe(p, rt, x):
                        p.off(only=HOT, page=f"搜索·热榜·{x}"); p.back()
            p.back()
        p.back()
    p.back(2)
