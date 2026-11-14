# Xiaomi Pad 7（2410CRP4CC）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 应用商店的「个性化服务」按运行时读到的开关位置分岔：新版本是子页入口、老版本开关就在本页。


import recipe_nav as nav
def step_store(p, rt):
    # 平板商店从 MarketTabActivity 直接进，避开冷启动时的 FloatWebActivity 空白页
    p.start("com.xiaomi.market", ".ui.MarketTabActivity")
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("应用商店顶部「我的」未找到")
    if not nav.maybe(p, rt, "设置", scrolls=8):
        raise RuntimeError("应用商店设置入口未找到")
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」；「推送消息」是父开关，关了会连带点赞 / 评论消息
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新"], page="商店·通知设置"); p.back()
    if nav.tap_any(p, rt, "隐私设置", "隐私"):
        nested = not any("个性化服务" in t for t, _, _ in p.switches())
        if not nested or nav.maybe(p, rt, "个性化服务"):
            p.off(only=["个性化服务"], page="商店·个性化服务")
            if nested:
                p.back()
        p.back()
    p.back(2)
