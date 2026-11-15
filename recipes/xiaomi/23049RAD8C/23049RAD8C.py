# Redmi Note 12 Turbo（23049RAD8C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 系统广告的 try/except 兜底与天气和日历的两条入口路径留在过程化实现里。
from entries import THEME_DEAD_ENDS
import recipe_nav as nav
import recipe_steps as steps
from recipe_runtime import SkipStep


# 热搜榜与 `recipe_steps.theme` 按名字从执行作用域取的模块常量。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_system_ads(p, rt):
    # 1. 广告服务直达页（拉不起来就算了，接着走设置搜索）
    try:
        p.start("com.android.settings", "com.android.settings.ad.AdServiceSettings")
        p.off(only=["个性化广告推荐"], page="系统·广告服务")
    except Exception:
        pass
    # 2. 系统广告（系统工具广告）
    if not p.setting("系统广告"):
        raise RuntimeError("没搜到「系统广告」")
    p.off(only=["系统工具广告"], page="系统·系统工具广告")


def step_weather_calendar(p, rt):
    # 1. 天气
    p.start("com.miui.weather2")
    if p.tap("更多设置", exact=True, scrolls=0) or nav.gear(p, rt):
        if p.tap("设置", exact=True, scrolls=0):
            if nav.maybe(p, rt, "用户体验计划"):
                p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page="天气·用户体验计划"); p.back()
            p.back()
    p.back(2)

    # 2. 日历（直达用户体验计划）
    try:
        p.start("com.android.calendar", ".settings.UserExperienceActionBarActivity")
        p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划")
        p.back(2)
    except SkipStep:
        raise                     # App 本机没装：放行，由段包装记跳过（#908）
    except Exception:
        p.start("com.android.calendar")
        nav.gear(p, rt)
        if nav.maybe(p, rt, "用户体验计划"):
            p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划"); p.back()
        p.back(2)
