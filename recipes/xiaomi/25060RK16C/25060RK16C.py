# REDMI K80 Ultra（25060RK16C）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 系统广告的「设置搜索不可用就退回菜单路径」与商店的其余分岔留在过程化实现里。
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


def step_store(p, rt):
    # 2026-10-27 K80 实测：冷启动常落「福利推广页」→先回首页；设置是我的页顶部图标。
    # 「我的」用 p.tab()：底部带过滤把页里那个叫「我的奇妙小镇」的游戏挡在外面（#386）。
    p.start("com.xiaomi.market")
    time.sleep(2.5)
    if p.find("回到首页", exact=True):
        p.tap("回到首页", exact=True, scrolls=0); time.sleep(2)
    if not p.tab("我的"):
        raise RuntimeError("商店底部「我的」标签没找到")
    time.sleep(2)
    if not (nav.gear(p, rt, toolbar_only=True) or nav.gear(p, rt) or p.tap("设置", exact=True, scrolls=4)):
        raise RuntimeError("商店设置图标没找到")
    time.sleep(1)
    p.off(only=["秒装"], page="商店·设置")          # 机主同意关秒装（2026-10-27）；删除安装包等功能保留
    if nav.maybe(p, rt, "通知设置"):
        # 只关「新手帮助」。不碰「推送消息」：它是父开关（M154FF Issue #2）；应用更新保留
        p.off(only=["新手帮助"], keep=["推送消息", "应用更新", "删除安装包", "秒装"], page="商店·通知设置"); p.back()
    if nav.maybe(p, rt, "其他功能"):
        if nav.maybe(p, rt, "隐私设置"):
            nested = not any("个性化服务" in t for t, _, _ in p.switches())
            if not nested or nav.maybe(p, rt, "个性化服务"):
                p.off(only=["个性化服务"], page="商店·个性化服务")
                if nested:
                    p.back()
            p.back()
        p.back()
    # 模式切换：机主拍板保持标准模式，本脚本不切极简
    p.back(2)

