# 一加 13T（PKX110，ColorOS 16.0.10.500 / Android 16）的本机例外函数与钩子（catalog 的 `code=`，
# 影随同名 `.toml`）。共享库的 tap_page / store_promotions / browser_* 与 require / skip 由装载器注入。
# 广告跟踪（逐页等列表 + 整页全关）与小布建议（行状态判定 + 翻页）留下，逐字保留原实现。
import time
import recipe_nav as nav


BUILD = "PKX110_16.0.10"
MODELS = ["PKX110"]

# 服务管理里明确的推广入口（PHK110 清单 + 本机实测新增项）。未列出的入口不主动处理。
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "应用安全安全内容推荐",
    "游戏专区：找游戏-休闲", "游戏专区：找游戏-小游戏", "游戏专区：找游戏-种草",
    "游戏专区：找游戏-VIP", "游戏专区：重磅更新卡片", "游戏专区：活动集合",
    "游戏详情页：游戏活动卡片", "游戏详情页：游戏礼包",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "我的专区：账号会员徽章", "我的专区：主题商店", "我的专区：应用时刻", "我的专区：游戏VIP",
    "小游戏二楼和专区", "AI智能体",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "详情页：限时活动",
    "手机管家：应用推荐", "文件管理：应用推荐", "福利专区",
]

# 段体（store_promotions / browser_ads / browser_personalized）按 `g["off_exact"]` 取这个钩子，
# 实现住在 recipe_strategies 的 `off_exact_paged`，这里绑回旧名字（ColorOS 16 那一套，#1253）。


def guard(p, rt):
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PKX110" or not build.startswith(BUILD):
        rt.skip("型号或系统版本不同，跳过；请重新核对页面")


def step_ad_tracking(p, rt):
    # 2026-10-28 实测：隐私页在 com.oplus.securitypermission，设备标识与广告在 OplusSettingsActivity$DevicesIdentifySettingsActivity。
    rt.skip_in_safe_mode()
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not nav.tap_page(p, rt, "隐私", "com.oplusos.securitypermission.privacy.PrivacySettingsDashboardActivity", "隐私"):
        return False
    if not nav.tap_page(p, rt, "设备标识与广告", "OplusSettingsActivity$DevicesIdentifySettingsActivity", "设备标识与广告"):
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


def step_advice(p, rt):
    # 2026-10-28 实测：设置首页 → OPPO AI（com.oplus.pantanal.ums/com.ums.aisetting.AISettingActivity）
    # → 小布建议（AdviceSettingActivity）。资讯服务是行状态（已卸载/已开启），不是本页开关，
    # 要关就点进「内容资讯 → 资讯服务」二级页（PKG110 同）。本机全部服务已是「已卸载」，无开关。
    p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
    if not nav.tap_page(p, rt, "OPPO AI", "com.ums.aisetting.AISettingActivity", "OPPO AI"):
        return False
    if not nav.tap_page(p, rt, "小布建议", "com.oplus.advice.settings.ui.AdviceSettingActivity", "小布建议"):
        return False
    texts = [t for t, _, _ in p.texts()]
    # 相邻两行配对，长度必然差一：strict=False 是有意的
    if any("资讯服务" in t and "已卸载" in x for t, x in zip(texts, texts[1:], strict=False)):
        print("  · 资讯服务已是「已卸载」，无需处理")
        return True
    for _ in range(8):
        if p.find("资讯服务", exact=True):
            break
        if not p.scroll_more():
            break
    if p.tap("资讯服务", exact=True, scrolls=0):
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
        p.back()
        return True
    print("  · 没找到「资讯服务」行，跳过")
    return False


def tail(p, rt):
    print("\n本机型脚本说明：浏览器段按「入口检测不到就跳过」处理（com.heytap.browser 预装但无桌面入口、")
    print("设置组件不存在时）；下拉搜索、负一屏属于原厂桌面，换用第三方桌面后不在使用面，未收录。")
    print("广告包、乐划锁屏、快应用和通知渠道请按 run.py 标准流程另行确认。")
    print("分段结果：", rt.results)
