# Xiaomi 13 Ultra / 14 Pro（2304FPN6DC / 23116PN5BC）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 系统广告的重试轮与全局搜索的榜单候选留在过程化实现里。
import time
import recipe_nav as nav


# 热搜榜的候选开关名：`step_global_search` 自己按它筛目标行。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选", "千问"]


def step_system_ads(p, rt):
    # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not nav.maybe(p, rt, "隐私与安全"):
        return
    # 13 Ultra（OS3.0.308）：隐私与安全默认停在「隐私」，要切到顶部的「安全」页
    for _ in range(3):
        if p.find("设备安全") or p.find("人身安全"):
            break
        p.tap("安全", exact=True, scrolls=0)
        time.sleep(0.5)
    if nav.maybe(p, rt, "更多安全设置"):
        if nav.maybe(p, rt, "广告服务"):
            p.off(only=["个性化广告推荐"], page="系统·广告服务")


def step_global_search(p, rt):
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    if nav.maybe(p, rt, "首页展示模块"):
        p.off(only=["搜索提示词"], page="搜索·首页模块")
        if nav.maybe(p, rt, "应用推荐"):
            p.off(only=["推荐未安装应用"], keep=["展示应用推荐"], page="搜索·应用推荐"); p.back()
        if nav.maybe(p, rt, "热搜榜单"):
            # 「我的热榜」既有「推荐」总开关，又分热搜 / 生活 / 娱乐 / 话题子页
            subs = [x for x in ("热搜", "生活", "娱乐", "话题") if p.find(x, exact=True)]
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
