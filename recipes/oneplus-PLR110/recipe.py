# 一加 Ace 6T（PLR110，ColorOS 17.0.0.101 / Android 17）机型脚本。
# 路径实测：2026-10-31。覆盖：广告跟踪、软件商店、浏览器、主题商店、视频、游戏中心、
# 小布建议、负一屏、下拉搜索，共九段。视频段用 ColorOS 17 的「个性化管理」入口。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PLR110_17.0.0.101"

import time


@step("广告跟踪")
def _():
    ad_tracking_close_all()


# 服务管理里只保留功能项，其余推广入口全关（本机 2026-10-31 实测共 46 项开关）
STORE_KEEP = ["帮助与客服", "应用安全", "首页：AI搜索"]


@step("软件商店")
def _():
    p.start("com.heytap.market")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if maybe("服务管理"):
        p.off(keep=STORE_KEEP, page="商店·服务管理")
        p.back()
    if maybe("消息管理"):
        # 下载/更新/安装提醒是功能通知，只关热门内容推送
        p.off(only=["热门内容推送"], page="商店·消息管理")
        p.back()
    # 「账号与隐私」分组下的「账号设置」没有广告开关，不进
    p.back(2)


@step("浏览器")
def _():
    p.start("com.heytap.browser")
    # ColorOS 17 首页读不到「我的」/菜单入口，用实测可直达的设置页 Activity；带清栈参数会立刻退出
    p.d.shell("am start -f 0x10008000 -n com.heytap.browser/.settings.component.BrowserPreferencesPage")
    time.sleep(1.2)
    if "com.heytap.browser" not in p.focus():
        print("  ✗ 浏览器设置页没有打开")
        return
    if p.tap("主页设置", exact=True):
        if p.tap("页面布局", exact=True):
            p.tap("简洁", exact=True, scrolls=0)
            p.back()
        p.back()
    if p.tap("隐私", exact=True):
        if p.tap("广告管理", exact=True):
            # 摇一摇广告随上级开关灰置（开屏/资讯列表都关了就不会展示），不点它
            p.off(only=["开屏广告", "资讯列表广告"], page="浏览器·广告管理")
            p.back()
        if maybe("个性化管理"):
            p.off(only=["个性化广告推荐", "个性化优惠推荐"], page="浏览器·个性化管理")
            p.back()
        p.back()
    if maybe("消息管理"):
        # 允许通知、互动消息、锁屏通知、其他服务保留；资讯类推送关掉
        p.off(only=["精彩推荐", "重点时事", "本地资讯", "个性化推荐"], page="浏览器·消息管理")
        p.back()
    p.back(2)


@step("主题商店")
def _():
    theme_shop_settings()


@step("视频")
def _():
    p.start("com.heytap.yoli", settle=4)    # 开屏广告有约 4 秒倒计时，多留时间点「跳过」
    if not p.go("我的", "设置"):
        raise RuntimeError("没找到「我的」标签")
    p.tap("设置", exact=True, scrolls=0)
    # 这版入口叫「个性化管理」（PLP120 的「个性化内容管理」已改名）
    if p.tap("个性化管理", exact=True):
        p.off(only=["个性化广告推荐", "个性化内容推荐"], page="视频·个性化管理")
        p.back()
    # 互动消息、服务通知、会员权益、其他服务保留
    if p.tap("消息通知", exact=True):
        p.off(only=["热点时事", "精彩推荐", "个性化推荐", "本地新闻"], page="视频·消息通知")
        p.back()
    p.back(2)


@step("游戏中心")
def _():
    game_center_taps()


@step("小布建议")
def _():
    assistant_advice_search()


@step("负一屏")
def _():
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


SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 设置页上的标题；搜索首页也有「搜索范围」这类文字，所以还要看前台 Activity（SearchSettingActivity）。
SEARCH_TITLES = {"搜索范围", "首页卡片管理", "功能管理", "账号与隐私"}


def search_settings():
    """先用全局搜索自己的 scheme 落地（同族 PLP120 / PMX110 实测，#796）；打不开再退回桌面下拉。
    SearchSettingActivity 未导出，按组件名 `am start -n` 会被系统拒绝。"""
    p.d.shell(SEARCH_SETTING)
    if wait_search_settings():
        return True
    p.d.shell("input keyevent HOME"); time.sleep(0.6)
    # HOME 可能停在速览页（左一屏）：先左滑回主桌面，否则下拉手势被速览吃掉
    p.d.shell(f"input swipe {p.W*6//7} {p.H//2} {p.W//7} {p.H//2} 250"); time.sleep(1.0)
    p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); time.sleep(1.5)
    if "quicksearchbox" not in p.focus():
        print("  ✗ 下拉没进全局搜索")
        return False
    # 收键盘要点键盘上的「收起键盘」箭头；按返回会整页退出
    p.tap("收起键盘", exact=True, scrolls=0)
    time.sleep(0.8)
    # 页面底部出现「设置」按钮；应用建议里也有「设置」图标，点最靠下的那个
    cands = [((l + r) // 2, (tp + b) // 2) for t, (l, tp, r, b), _ in p.texts()
             if t == "设置" and tp > p.H * 0.8]
    if not cands:
        print("  ✗ 底部没有「设置」")
        p.back()
        return False
    before = p.sig()
    p.click(*cands[-1])
    p.settle(before, 1.5)
    if "SearchSetting" not in p.focus():
        print("  ✗ 没进搜索设置")
        return False
    return True


@step("下拉搜索")
def _():
    search_settings_swipe()
