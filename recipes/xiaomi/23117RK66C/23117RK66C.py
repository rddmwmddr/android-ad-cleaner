# Redmi K70 Pro（23117RK66C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 线性段落已转成数据；这里只留「全局搜索」里运行期算出来的榜单候选与收尾打印。
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, require, rt
    from recipe_nav import close_named, enter

# 热搜榜的候选开关名：每个子页都会命中其中的一部分。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_global_search(p, rt):
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    enter("首页展示模块")
    close_named(["搜索提示词"], "搜索·首页模块")
    enter("应用推荐")
    close_named(["推荐未安装应用"], "搜索·应用推荐")
    p.back()
    enter("热搜榜单")
    # 不把所有版本可能出现的榜单当成必备；每个实际打开的子页必须找到目标并回读。
    subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
    require(subs, "未识别热榜分类")
    for name in subs:
        enter(name, scrolls=0)
        titles = [title for title, _, _ in p.switches() if any(k in title for k in HOT)]
        require(titles, f"热榜「{name}」未识别目标开关")
        close_named(titles, f"搜索·热榜·{name}")
        p.back()


def tail():
    print(f"\n逐页回读确认 {rt.verified} 项；步骤异常 {len(rt.failed_steps)} 个", flush=True)
