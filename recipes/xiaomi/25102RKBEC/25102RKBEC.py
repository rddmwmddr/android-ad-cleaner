# REDMI K90 Pro Max（25102RKBEC）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 系统广告的分栏判定与手机管家的逐屏下翻都要运行时读数，留在过程化实现里。
# `recipe_steps.theme` 按 `g["THEME_DEAD_ENDS"]` 取落点名单，下面这句导入把它留在执行作用域里。
import time
from entries import THEME_DEAD_ENDS
import recipe_nav as nav
import recipe_steps as steps


# 热搜榜的候选开关名：`recipe_steps.global_search` 从执行作用域按名字取。
HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


def step_system_ads(p, rt):
    # 不用设置搜索：HyperOS 搜索框用 setText 输入中文会卡住、一直打「%」。按菜单路径点进去
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    # 这台设置首页一屏放不下，「隐私与安全」在第二屏
    if not nav.maybe(p, rt, "隐私与安全", scrolls=8):
        return
    # 打开的是安全中心「隐私与安全」页（PrivacySafetyActivity），默认停在「隐私」分栏
    if p.find("隐私与安全") and not p.find("更多安全设置"):
        nav.tab(p, rt, "安全")
    # 「安全」分栏很长，「更多安全设置」在整页最末尾
    if not nav.maybe(p, rt, "更多安全设置", scrolls=10):
        return
    if nav.maybe(p, rt, "广告服务", scrolls=4):
        p.off(only=["个性化广告推荐"], page="系统·广告服务")


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

