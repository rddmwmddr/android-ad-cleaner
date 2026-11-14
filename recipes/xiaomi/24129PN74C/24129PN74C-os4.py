# Xiaomi 15 HyperOS 4 变体（24129PN74C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 应用商店的冷启动等待循环、全局搜索的榜单分类循环留在过程化实现里。
import time
from entries import THEME_DEAD_ENDS
import recipe_nav as nav


def step_store(p, rt):
    # 上次停在应用详情页时 start 会复用旧任务，先停掉
    p.d.shell("am force-stop com.xiaomi.market"); time.sleep(1)
    p.start("com.xiaomi.market")
    # 冷启动首页要几秒才渲染完，底栏还没出来就点会扑空（3 秒窗口实测不够，整段会空跑 65 秒）
    for _ in range(24):
        if p.find("我的，有新消息", exact=True, edge_ok="tab", nav=True):
            break
        time.sleep(0.5)
    # 底部标签的 content-desc 是「我的，有新消息」，精确匹配「我的」找不到（#193 四个入口全空的起点）。
    # 上次退出停在「我的」页、或首页被促销弹窗挡住时，这个标签读不到；先探测再点，免得留下假失败日志。
    p.miss = 0
    if p.find("我的，有新消息", exact=True, edge_ok="tab", nav=True):
        p.tap("我的，有新消息", exact=True, scrolls=0)
    elif p.find("我的", exact=False, edge_ok="tab", nav=True):
        p.tap("我的", exact=False, scrolls=0)
    time.sleep(1.5)
    if not nav.gear_top(p, rt):
        raise RuntimeError("商店「我的」页右上角齿轮未找到")
    if nav.maybe(p, rt, "隐私设置") or nav.maybe(p, rt, "隐私"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or nav.maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    # 不碰「模式切换 → 极简模式」：那是把商店首页整个换成极简布局，属于机主看得见的外观改动，
    # 不是关广告开关。参考脚本这么做是为了少几个推荐位，但脚本不该替机主改界面。
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。这台的通知设置没有「推送消息」总开关，只有 4 个独立项，别的一律不碰
        p.off(only=["新手帮助"], keep=["应用更新通知", "点赞消息", "评论消息"], page="商店·通知设置"); p.back()
    p.back(2)


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
