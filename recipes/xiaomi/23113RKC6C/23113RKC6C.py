# Redmi K70（23113RKC6C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 九段都已落数据；这里只剩共享段体按名字取用的模块常量与收尾打印。
from entries import THEME_DEAD_ENDS
import recipe_steps as steps


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]

# `recipe_steps.theme` 按 `g["THEME_DEAD_ENDS"]` 取落点名单，上面那句导入把它留在执行作用域里（#1266）。


def tail(p, rt):
    print(f"\n系统广告段回读确认 {rt.verified} 项；步骤异常 {len(rt.failed_steps)} 个", flush=True)
