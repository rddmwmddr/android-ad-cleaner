# V2545A 本机例外函数（catalog，#1263）：系统广告有「安全页直达 or 设置搜索」两条路，带 done 分支。
# 由 catalog.loader 装进执行作用域（preamble 已注入 settings_home / setting_search / maybe）。

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import maybe
    from recipe_nav import setting_search, settings_home

def step_system_ads(p, rt):
    settings_home()
    done = False
    if maybe("安全") or maybe("安全与隐私"):
        if maybe("更多安全设置") and maybe("广告与隐私"):
            p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")
            done = True
    if not done and setting_search("广告", "广告与隐私"):
        p.off(only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私（搜索）")
