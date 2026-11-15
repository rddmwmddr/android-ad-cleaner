# OPPO Find X8s（PKT110，ColorOS 17）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 只剩主题商店一段：它的「重进一次再回读」要把重进序列当回调传给库。
import recipe_nav as nav

BUILD = "PKT110_17.0.0.102(CN01)"


def step_theme(p, rt):
    """主题商店 → 我的 → 设置：服务管理 → 消息与广告；隐私 → 个性化推荐设置。
    「个性化推荐设置」点下去先弹确认框，确认后页面退回「设置」，回读前要重新进一次。
    首页的「检测到新版本」弹窗盖住底部标签栏，关弹窗的动画会把紧跟着的点击吞掉，
    所以每一跳都用会确认换页的 p.enter（#286）。
    「我的」页的「设置」在 17.22 上带通知角标（读作「设置,有1条新通知」），别的版本是纯齿轮，
    两种都要能进——见 open_settings()。"""
    def enter_settings():
        rt.require(nav.open_settings(p, rt), "没找到「设置」入口：文字与右上角图标都试过")

    def to_privacy():
        p.start("com.heytap.themestore")
        p.enter("我的")
        enter_settings()
        p.enter("隐私")

    p.start("com.heytap.themestore")
    p.enter("我的")
    enter_settings()
    p.enter("服务管理")
    p.enter("消息与广告")
    nav.close_named(p, rt, ["消息通知", "开屏广告"], "主题·消息与广告")
    p.back(2)
    to_privacy()
    nav.close_named(p, rt, ["个性化推荐设置"], "主题·个性化推荐", reopen=to_privacy)


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；未完成步骤 {len(rt.failed_steps)} 个", flush=True)
