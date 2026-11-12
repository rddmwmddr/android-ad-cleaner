# 一加 16（PYB110，ColorOS 17.0.0 / Android 17）机型脚本。
# 路径实测：2026-11-12 在 17.0.0.155 上录制，九段全跑 397 秒；同日在 17.0.0.157 上复验。
# 覆盖：广告跟踪、软件商店、浏览器、主题商店、视频、游戏中心、小布建议、负一屏、下拉搜索，共九段。
# 与同族 ColorOS 17 脚本的三处差别：商店「我的」页没有设置文字行，只能用公开设置 Intent；
# 浏览器叫「个性化内容」、视频叫「个性化内容管理」；负一屏没有推荐服务入口，个性化开关
# 在「隐私 → 个性化推荐」里按模块给。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "PYB110_17.0.0"

import time


@step("广告跟踪")
def _():
    # ColorOS 17 设置首页是「隐私与安全」聚合入口；旧版本叫「隐私」，两个都试
    skip_in_safe_mode()
    found = settings_page("隐私与安全", "设备标识与广告", "广告跟踪")
    if not found:
        p.miss = 0
        found = settings_page("隐私", "设备标识与广告", "广告跟踪")
    if not found:
        return
    # 右上角三个点（更多选项）菜单里有「全部关闭」，一键关完，比逐个点稳
    if p.tap("更多选项", exact=True, scrolls=0):
        if p.tap("全部关闭", exact=True, scrolls=0):
            p.confirm()                       # 有的版本会弹确认框
            time.sleep(0.5)
            still = [t for t, c, _ in p.switches() if c]
            if not still:
                p.changed.append(("广告跟踪", "全部关闭（更多选项菜单）"))
                return
            p.say(f"  ! 「全部关闭」后这一屏仍有 {len(still)} 个开关开着，退回逐项关")
        else:
            p.back()                          # 菜单开了但没点成：收起后退回逐个关
    p.miss = 0
    p.off(page="广告跟踪", max_screens=40)


# 服务管理里只保留功能项，其余推广入口全关（本机 2026-11-12 实测共 46 项开关）
STORE_KEEP = ["帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：存储空间清理",
              "我的专区：我的资产", "我的专区：安全守护", "我的专区：小i客服",
              "应用使用记录", "首页：AI搜索"]


@step("软件商店")
def _():
    # 「我的」页没有「设置」文字行，只有右上角齿轮；用公开设置 Intent 直达设置页
    p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market")
    time.sleep(1.5)
    if not p.in_settings_page():
        raise RuntimeError("商店设置页没有打开")
    # 本版商店设置页没有「消息管理」入口（服务管理关前关后都读不到），按可选入口处理
    if maybe("消息管理"):
        # 下载/更新/安装提醒是功能通知，只关热门内容推送
        p.off(only=["热门内容推送"], page="商店·消息管理")
        p.back()
    if p.tap("服务管理", exact=True):
        p.off(keep=STORE_KEEP, page="商店·服务管理")
        p.back()
    # 「账号与隐私」分组下的「账号设置」没有广告开关，不进
    if p.tap("隐私", exact=True):
        # 「个性化推荐」在这一页是入口行，开关在下一层的 PersonalRecommendActivity
        if p.tap("个性化推荐", exact=True):
            p.off(only=["个性化推荐"], page="商店·个性化推荐")
            p.back()
        p.back()
    p.back(2)


@step("浏览器")
def _():
    p.start("com.heytap.browser")
    # 首页读不到「我的」/菜单入口，用实测可直达的设置页 Activity；带清栈参数会立刻退出
    p.d.shell("am start -f 0x10008000 -n com.heytap.browser/.settings.component.BrowserPreferencesPage")
    time.sleep(1.2)
    if "com.heytap.browser" not in p.focus():
        raise RuntimeError("浏览器设置页没有打开")
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
        if maybe("个性化内容"):
            # ColorOS 17.0.0.155 的入口叫「个性化内容」，不是 PLR110 上的「个性化管理」
            p.off(only=["个性化内容"], page="浏览器·个性化内容")
            p.back()
        p.back()
    if maybe("消息管理"):
        # 允许通知、互动消息、锁屏通知、其他服务保留；资讯类推送关掉
        p.off(only=["精彩推荐", "重点时事", "本地资讯", "个性化推荐"], page="浏览器·消息管理")
        p.back()
    p.back(2)


@step("主题商店")
def _():
    p.start("com.heytap.themestore")
    p.go("我的", "设置")
    p.tap("设置", exact=True, scrolls=0)
    if p.tap("服务管理", exact=True):
        # 「全部服务/基础服务」保持全部服务；锁屏开关是功能项
        if maybe("消息与广告"):
            p.off(only=["消息通知", "开屏广告"], page="主题·消息与广告")
            p.back()
        p.back()
    if p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="主题·个性化推荐")
        p.back()
    p.back(2)


@step("视频")
def _():
    p.start("com.heytap.yoli", settle=4)    # 开屏广告有约 4 秒倒计时，多留时间点「跳过」
    if not p.go("我的", "设置"):
        raise RuntimeError("没找到「我的」标签")
    p.tap("设置", exact=True, scrolls=0)
    # 这版入口叫「个性化内容管理」（PLR110 上的「个性化管理」在这台机没有）
    if p.tap("个性化内容管理", exact=True):
        p.off(only=["个性化推荐"], page="视频·个性化内容管理")
        p.back()
    # 互动消息、服务通知、会员权益、其他服务保留
    if p.tap("消息通知", exact=True):
        p.off(only=["热点时事", "精彩推荐", "个性化推荐", "本地新闻"], page="视频·消息通知")
        p.back()
    p.back(2)


@step("游戏中心")
def _():
    p.start("com.nearme.gamecenter")
    if not p.tap("我的", exact=True, scrolls=0):
        raise RuntimeError("没找到底部「我的」")
    time.sleep(1.2)
    p.dismiss()
    # 「设置」是「我的」页里带新通知标记的文字行（非右上角齿轮）
    if not p.tap("设置", exact=False, scrolls=0) and not p.tap_icon(["隐私开关设置", "隐私"]):
        raise RuntimeError("没找到设置入口")
    if p.tap("隐私开关设置", exact=True) and p.tap("个性化推荐管理", exact=True):
        p.off(only=["个性化推荐"], page="游戏中心·个性化推荐管理")
    p.back(4)


@step("小布建议")
def _():
    if settings_page("OPPO AI", "小布建议"):
        # 「内容资讯」是分组标题；「资讯服务」是子入口，进去关开关
        if p.tap("资讯服务", exact=True):
            p.off(only=["资讯服务"], page="小布建议·内容资讯")
            p.back()
    p.back(2)


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
        raise RuntimeError("右滑没进速览（负一屏）")
    # 左上角入口这版叫「我的」，不叫「头像」
    if not p.go("我的", "设置"):
        raise RuntimeError("没找到「我的」入口")
    p.tap("设置", exact=True, scrolls=0)
    # 这台机（速览 17.0.48）没有「推荐服务 / 轮播推荐」入口，也没有「搜索框提示词」：
    # 个性化开关挪到了「隐私 → 个性化推荐」，模块分成 快捷服务 / 卡片服务 / 热点资讯
    if p.tap("消息管理", exact=True):
        # 快递取件、赛事提醒这类服务通知是功能项，只关服务资讯推荐
        p.off(only=["最新服务资讯通知"], page="负一屏·消息管理")
        p.back()
    if p.tap("隐私", exact=True):
        if p.tap("个性化推荐", exact=True):
            p.off(only=["热点资讯"], page="负一屏·个性化推荐")
            p.back()
        p.back()
    p.back(3)


SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 设置页上的标题；搜索首页也有「搜索范围」这类文字，所以还要看前台 Activity（SearchSettingActivity）。
SEARCH_TITLES = {"搜索范围", "首页卡片管理", "功能管理", "账号与隐私"}


def search_settings():
    """先用全局搜索自己的 scheme 落地（同族 PLP120 / PMX110 实测）；打不开再退回桌面下拉。
    SearchSettingActivity 未导出，按组件名 `am start -n` 会被系统拒绝。"""
    p.d.shell(SEARCH_SETTING)
    if wait_search_settings():
        return True
    p.d.shell("input keyevent HOME"); time.sleep(0.6)
    # HOME 可能停在速览页（左一屏）：先左滑回主桌面，否则下拉手势被速览吃掉
    p.d.shell(f"input swipe {p.W*6//7} {p.H//2} {p.W//7} {p.H//2} 250"); time.sleep(1.0)
    p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); time.sleep(1.5)
    if "quicksearchbox" not in p.focus():
        raise RuntimeError("下拉没进全局搜索")
    # 收键盘要点键盘上的「收起键盘」箭头；按返回会整页退出
    p.tap("收起键盘", exact=True, scrolls=0)
    time.sleep(0.8)
    # 页面底部出现「设置」按钮；应用建议里也有「设置」图标，点最靠下的那个
    cands = [((l + r) // 2, (tp + b) // 2) for t, (l, tp, r, b), _ in p.texts()
             if t == "设置" and tp > p.H * 0.8]
    if not cands:
        raise RuntimeError("搜索页底部没有「设置」")
    before = p.sig()
    p.click(*cands[-1])
    p.settle(before, 1.5)
    if "SearchSetting" not in p.focus():
        raise RuntimeError("没进搜索设置")
    return True


@step("下拉搜索")
def _():
    if not search_settings():
        raise RuntimeError("没进全局搜索设置页")
    if p.tap("搜索范围", exact=True):
        # APP内搜索、搜索建议、小程序、AI搜索、便捷服务保留
        p.off(only=["榜单", "小说", "购物", "个性化推荐", "精选资讯"], page="下拉搜索·搜索范围")
        p.back()
    if p.tap("首页卡片管理", exact=True):
        p.off(only=["未下载应用推荐", "应用建议小卡", "热搜应用", "精选推荐", "热搜榜单", "活动皮肤", "推荐卡片"], page="下拉搜索·首页卡片管理")
        p.back()
    if p.tap("功能管理", exact=True):
        p.off(only=["搜索框提示词"], page="下拉搜索·功能管理")
        p.back()
    if p.tap("账号与隐私", exact=True) and p.tap("隐私", exact=True):
        p.off(only=["个性化推荐"], page="下拉搜索·隐私")
        p.back(2)
    p.back(2)
