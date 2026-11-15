# 一加 16（PYB110，ColorOS 17）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 只剩商店段：设置页靠公开 Intent 拉起，「消息管理」是条件入口，探测后要从页顶重来。
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
    # 「消息管理」是条件入口：首启时出现过一行，之后整页与各子页都读不到（把系统渠道
    # 「热门内容推送」关了再开也不回来），App 资源里仍留着这条文案与「我的-设置-消息管理」
    # 的帮助句。只翻前两屏探测：翻满整页常态下多花 40 秒找一条不存在的行；若它出现在更靠下
    # 的位置，这一档会漏掉（没有验证过它当时在哪一屏）。
    if nav.maybe(p, rt, "消息管理", scrolls=1):
        # 下载/更新/安装提醒是功能通知，只关热门内容推送
        p.off(only=["热门内容推送"], page="商店·消息管理")
        p.back()
    # 有界探测会把设置页停在半途；后面的入口从页顶找才不会点到半加载的服务管理页。
    p.top()
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

