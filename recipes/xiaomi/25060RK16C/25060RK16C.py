# REDMI K80 Ultra（25060RK16C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 系统广告的「设置搜索不可用就退回菜单路径」留在过程化实现里。
import time
import recipe_nav as nav
import recipe_steps as steps


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_system_ads(p, rt):
    # 实测：HyperOS 2 的「隐私与安全」页是权限中心，没有「更多安全设置」；改走引擎设置搜索（0.2.4 已修小米搜索框卡顿）
    if not p.setting("广告服务"):
        # 搜索不可用时退回菜单路径（全程 maybe 守卫）；兜底也不通要记成未完成（#819）
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
        reached = False
        if nav.maybe(p, rt, "隐私与安全") or nav.maybe(p, rt, "隐私保护"):
            if not nav.maybe(p, rt, "更多安全设置"):
                if nav.maybe(p, rt, "安全", scrolls=3) or nav.maybe(p, rt, "保护与隐私", scrolls=3):
                    nav.maybe(p, rt, "更多安全设置")
            if nav.maybe(p, rt, "广告服务"):
                p.off(only=["个性化广告推荐", "广告跟踪"], page="系统·广告服务")
                p.back()
                reached = True
        if not reached:
            raise RuntimeError("没找到「广告服务」入口")
        return
    # 「广告跟踪」以限制/防止开头 = 保护类，off() 会把它拨到开（AGENTS 硬规则10）
    p.off(only=["个性化广告推荐", "广告跟踪"], page="系统·广告服务")
    p.back()
