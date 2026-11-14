# V2545A 本机例外函数（catalog，#1263）：系统广告有「安全页直达 or 设置搜索」两条路，带 done 分支。
# 由 catalog.loader 装进执行作用域（preamble 已注入 settings_home / setting_search / maybe）。


import recipe_nav as nav
import recipe_strategies as strategies
def step_system_ads(p, rt):
    nav.settings_home(p, rt)
    done = False
    if nav.maybe(p, rt, "安全") or nav.maybe(p, rt, "安全与隐私"):
        if nav.maybe(p, rt, "更多安全设置") and nav.maybe(p, rt, "广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")
            done = True
    if not done and strategies.setting_search(p, rt, "广告", "广告与隐私"):
        p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私（搜索）")
