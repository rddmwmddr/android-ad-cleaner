# REDMI K90 Pro Max（25102RKBEC）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 手机管家的逐屏下翻要运行时读数，留在过程化实现里。
# `recipe_steps.theme` 按 `g["THEME_DEAD_ENDS"]` 取落点名单，下面这句导入把它留在执行作用域里。
from entries import THEME_DEAD_ENDS
import recipe_nav as nav
import recipe_steps as steps


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_security_center(p, rt):
    # 这台（13.x）的设置页有「隐私设置」，但它在整页最末尾（各功能模块设置之下）。
    # 直接 tap 翻页找不到（贴底的行会被 find 的 0.92H 判据滤掉），先手动往下翻再点。
    # 里面的「个性化推荐」默认是开的——这是 M154FF 那份脚本在这台上漏掉的一项。
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    p.top()
    for _ in range(8):
        if p.find("隐私设置", exact=True, edge_ok=True):
            break
        p.scroll(0.5)
    if p.tap("隐私设置", exact=True, scrolls=0):
        p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
    if nav.maybe(p, rt, "垃圾清理"):
        p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
    p.back(2)

