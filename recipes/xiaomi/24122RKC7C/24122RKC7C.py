# Redmi K80 Pro（24122RKC7C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 浏览器段带冷启动重试、齿轮 input-tap 兜底与前台复合断言，留在过程化实现里。
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import maybe, p, require, rt
    from recipe_nav import browser_start, gear
    from recipe_strategies import gear_tap

# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_browser(p, rt):
    require(browser_start(), "浏览器没有启动")
    if "basicmode" in p.focus().lower():
        # 拒绝浏览器协议后落到基本模式设置页，设置入口都不在这条路径上，找下去只会空转报错（#414、#460）
        print("  · 浏览器处在基本模式，设置入口不在这条路径上，本段跳过")
        return
    # 「我的」在本机是顶部标签：主页 / 视频 / AI搜索 / 免费小说 / 我的
    require(p.tap("我的", exact=True, scrolls=0), "未找到浏览器「我的」")
    if not gear(toolbar_only=True):
        require(gear_tap("com.android.browser", "BrowserSettingsActivity"),
                "浏览器设置齿轮没找到")
    else:
        require(p.focus().split("/", 1)[0] == "com.android.browser"
                and "BrowserSettingsActivity" in p.focus(), "浏览器设置页没有打开")
    if maybe("主页设置"):
        p.off(only=["宫格位推送"], page="浏览器·主页设置")
        p.back()
    if maybe("搜索设置"):
        p.off(only=["显示猜你想搜模块"], page="浏览器·搜索设置")
        p.back()
    p.back(2)


def tail():
    print(f"\n系统广告段回读确认 {rt.verified} 项；步骤异常 {len(rt.failed_steps)} 个", flush=True)
