# Xiaomi 17 Ultra（2512BPNDAC）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 系统广告的两条搜索各自记失败再一起报。


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


import recipe_nav as nav
import recipe_steps as steps
def step_system_ads(p, rt):
    # 两条设置搜索直达。不走「隐私与安全 → 安全 → 更多安全设置」：这台的「隐私与安全」是安全中心
    # PrivacySafetyActivity，默认停在「隐私」分栏，「安全」标签用读屏点经常点不动。
    # 两个总闸在两页上，互不依赖：一条搜不到不能连带把另一条也放弃，收尾再一起报失败。
    missed = []
    if p.setting("广告服务"):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")
    else:
        missed.append("广告服务")
    if p.setting("系统广告"):
        # 「在系统工具应用中会出现少量广告推荐」——天气、日历、音乐等系统工具里广告的总闸。
        p.off(only=["系统工具广告"], page="系统·系统广告")
    else:
        missed.append("系统广告")
    if missed:
        raise RuntimeError("没搜到" + "、".join(f"「{name}」" for name in missed))
