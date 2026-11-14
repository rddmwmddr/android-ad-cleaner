# 一加 Ace 6T（PLR110，ColorOS 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 只剩负一屏：滑动循环 + 先探测是否已在速览 + 轮播单选的 checked 状态重查，是真正的状态机。
import time


BUILD = "PLR110_17.0.0.101"

# 全局搜索的设置页 scheme 与页面标题：家族库打开设置页 / 认页时按这些名字从执行作用域取。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 设置页上的标题；搜索首页也有「搜索范围」这类文字，所以还要看前台 Activity（SearchSettingActivity）。
SEARCH_TITLES = {"搜索范围", "首页卡片管理", "功能管理", "账号与隐私"}


def step_negative_screen(p, rt):
    # ColorOS 17：速览内嵌在桌面进程里，焦点仍是 launcher，按页面内容判断进没进
    p.d.shell("input keyevent HOME"); time.sleep(0.6); p.d.shell("input keyevent HOME"); time.sleep(0.6)
    entered = False
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
        if p.find("我的服务") or p.find("添加卡片", exact=True):
            entered = True
            break
    if not entered:
        print("  ✗ 右滑没进速览（负一屏）")
        return
    # 左上角入口这版叫「我的」，不叫「头像」
    if not p.go("我的", "设置"):
        print("  ✗ 没找到「我的」入口")
        p.back()
        return
    p.tap("设置", exact=True, scrolls=0)
    # ⚠ 「推荐服务」总开关不要关：会删掉天气/步数/清理卡片；只把轮播推荐拨到「不显示」
    if p.tap("推荐服务", exact=True):
        def carousel_off():
            return any("RadioButton" in (n.get("class") or "") and n.get("checked") == "true"
                       and any((c.get("text") or "").strip() == "不显示轮播推荐" for c in n)
                       for n in p.tree().iter("node"))
        sel = False
        for _ in range(3):                    # 页面刚打开 checked 可能还没渲染，重查几次
            sel = carousel_off()
            if sel:
                break
            time.sleep(0.8)
        if not sel:
            p.tap("不显示轮播推荐", exact=True, scrolls=0)
            time.sleep(0.8)
            if carousel_off():
                p.changed.append(("负一屏·推荐服务", "轮播推荐 → 不显示"))
        p.back()
    # 这版没有「搜索框提示词」；「热点资讯」是子页入口，服务动态、快捷服务是功能项保留
    if p.tap("热点资讯", exact=True):
        p.off(only=["热点资讯"], page="负一屏·热点资讯")
        p.back()
    p.back(3)
