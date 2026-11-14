# Redmi Note 14 5G（24094RAD4C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 应用商店的「个性化服务」按运行时读到的开关位置分岔：新版本是子页入口、老版本开关就在本页。


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


import recipe_nav as nav
import recipe_steps as steps
def step_store(p, rt):
    p.start("com.xiaomi.market")
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0)
    if not nav.tap_bottom_tab(p, rt, "我的"):
        raise RuntimeError("商店底部「我的」标签没有找到")
    if not nav.gear(p, rt):
        raise RuntimeError("商店设置入口没有找到")
    if nav.tap_any(p, rt, "隐私设置", "隐私"):
        # 「个性化服务」是子页入口，开关在下一层。
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or nav.maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰父开关「推送消息」，应用更新也保留。
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    p.back(2)
