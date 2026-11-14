# 一加 Ace 2（PHK110，ColorOS 16 / Android 16）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 store_promotions / browser_* 与 require / skip 由装载器注入执行作用域。
# 广告跟踪（设置搜索 + 等列表 + 整页全关）留下，逐字保留原实现；线性的四段已转成数据。
import time
import recipe_nav as nav


BUILD = "PHK110_16.0.5.1201"

# 仅关闭明确的推广入口。没有列出的入口（包括未来新增项）不主动处理。
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "游戏专区：找游戏-种草", "游戏专区：重磅更新卡片", "游戏详情页：游戏活动卡片",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "游戏详情页：游戏礼包",
    "手机管家：应用推荐", "文件管理：应用推荐", "游戏专区：活动集合", "详情页：限时活动", "福利专区",
]

# 段体（store_promotions / browser_ads / browser_personalized）按 `g["off_exact"]` 取这个钩子，
# 实现住在 recipe_strategies 的 `off_exact_paged`，这里绑回旧名字（ColorOS 16 那一套，#1253）。


def guard(p, rt):
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PHK110" or not build.startswith(BUILD):
        rt.skip("型号或系统版本不同，跳过；请重新核对页面")


def step_ad_tracking(p, rt):
    # 此版本的 OAIDActivity 不能由 shell 直接拉起，必须走系统设置中的搜索结果。
    rt.skip_in_safe_mode()
    if not p.setting("设备标识与广告"):
        raise RuntimeError("没搜到「设备标识与广告」")
    result = p.d(resourceId="android:id/title", text="设备标识与广告")
    if result.exists:
        result.click()
    if not nav.wait_page(p, rt, "com.android.settings.SubSettings", "设备标识与广告"):
        return False
    if not p.find("重置设备标识符", exact=True):
        return False
    if not nav.tap_page(p, rt, "广告跟踪", "com.oplus.settings.feature.notification.oaid.OAIDActivity", "广告跟踪"):
        return False
    # 等应用列表真正加载，不能把只有标题的空白加载页视为完成。
    for _ in range(30):
        if p.switches():
            break
        time.sleep(0.2)
    if not p.switches():
        print("  ✗ 广告跟踪列表未加载")
        return False
    p.top(n=16)
    p.off(page="广告跟踪", max_screens=40)
    return True


def tail(p, rt):
    print("\n本机型脚本不处理：下拉搜索、负一屏、主题服务模式、视频和游戏中心。")
    print("广告包、乐划锁屏、快应用和通知渠道请按 run.py 标准流程另行确认。")
    print("分段结果：", rt.results)
