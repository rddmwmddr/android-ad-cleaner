# 一加 16（PYB110，ColorOS 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 maybe / p.tap / p.go 与段体助手由装载器注入执行作用域；线性段已转数据，这里只留
# 需要条件分支与手势坐标的四段。
import time
import recipe_nav as nav


BUILD = "PYB110_17.0.0"

# 服务管理里只保留功能项，其余推广入口全关（本机 2026-11-12 实测共 46 项开关）
STORE_KEEP = ["帮助与客服", "应用安全", "我的专区：应用工具", "我的专区：存储空间清理",
              "我的专区：我的资产", "我的专区：安全守护", "我的专区：小i客服",
              "应用使用记录", "首页：AI搜索"]

# 全局搜索的设置页 scheme 与页面标题：家族库打开设置页 / 认页时按这些名字从执行作用域取。
SEARCH_SETTING = "am start -f 0x10008000 -a android.intent.action.VIEW -d 'gs://search/setting'"
# 设置页上的标题；搜索首页也有「搜索范围」这类文字，所以还要看前台 Activity（SearchSettingActivity）。
SEARCH_TITLES = {"搜索范围", "首页卡片管理", "功能管理", "账号与隐私"}


def step_store(p, rt):
    # 「我的」页没有「设置」文字行，只有右上角齿轮；用公开设置 Intent 直达设置页
    p.d.shell("am start -f 0x10008000 -a oppo.intent.action.APP_SETTINGS -p com.heytap.market")
    time.sleep(1.5)
    if not p.in_settings_page():
        raise RuntimeError("商店设置页没有打开")
    # 本版商店设置页没有「消息管理」入口（服务管理关前关后都读不到），按可选入口处理
    if nav.maybe(p, rt, "消息管理"):
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
