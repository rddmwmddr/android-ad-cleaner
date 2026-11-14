# Xiaomi MIX Flip 2（2505APX7BC）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 应用商店的「个性化服务」按运行时读到的开关位置分岔；天气的设置藏在 PopupWindow 菜单里，按坐标点。
import time
import recipe_nav as nav
import recipe_steps as steps


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_store(p, rt):
    # 冷启动可能落「福利推广页」→ 先回首页。「我的」用 p.tab()：底部带过滤把内容区同名文字挡在外面（#386）。
    p.start("com.xiaomi.market")
    time.sleep(2.5)
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0)
        time.sleep(2)
    rt.require(p.tab("我的"), "商店底部「我的」标签没找到")
    time.sleep(1.5)
    rt.require(p.tap("设置", exact=True, scrolls=4), "商店设置图标没找到")
    time.sleep(1)
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
    p.back(2)


def step_weather_calendar(p, rt):
    # 天气：设置藏在「更多设置」弹出的菜单里；这版页面只有提醒与单位类开关，没有「用户体验计划」。
    p.start("com.miui.weather2")
    time.sleep(2)
    rt.require(p.tap("更多设置", exact=True, scrolls=2), "天气「更多设置」没找到")
    xy = nav.popup_row(p, rt, "设置")
    rt.require(xy, f"天气「更多设置」菜单里没有「设置」；停在 {p.focus()}")
    before = p.sig()
    p.click(*xy)
    # 落点核对：没进设置页就报失败，否则会把「没点开」说成「本版没有这类开关」
    rt.require(p.settle(before, 1.5)
            and ("ActivitySet" in p.focus() or p.find("温度单位", exact=True)
                 or p.find("早晚天气提醒", exact=True)),
            f"天气设置页没有打开；停在 {p.focus()}")
    if nav.maybe(p, rt, "用户体验计划"):
        p.off(only=["推荐", "广告", "个性化", "内容推广", "天气视频卡片"], page="天气·用户体验计划")
        p.back()
    else:
        print("  · 天气：本版无此类开关（只有提醒与单位设置），跳过")
    p.back(2)
    # 日历：设置是无文字图标，直达 Activity；这版 7 项全是功能开关。
    p.d.shell("am start -f 0x10008000 -n com.android.calendar/.settings.CalendarActionbarSettingsActivity")
    time.sleep(1.5)
    rt.require("CalendarActionbarSettingsActivity" in p.focus(), f"日历设置页没有打开；停在 {p.focus()}")
    if nav.maybe(p, rt, "用户体验计划"):
        p.off(only=["推荐", "广告", "个性化", "内容推广"], page="日历·用户体验计划")
        p.back()
    else:
        print("  · 日历：本版无此类开关（7 项全是功能开关），跳过")
    p.back()

