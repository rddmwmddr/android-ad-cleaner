# OPPO Find X9 Pro（PLG110，ColorOS 16）的本机例外函数与钩子（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 system_settings / app_settings / tap_page / read_switches 与 require / skip 由装载器注入。
# 四段留在代码里：广告跟踪与软件商店按本页实际读到的开关收窄名单并回读，游戏中心与小布建议
# 要清弹窗、按相邻两行的行状态分岔。
import time

# bounds 只给注入面的 carousel_choices 取（它按执行作用域解析这个名字）
from fast import ScreenLocked, bounds
import recipe_nav as nav
import recipe_strategies as strategies


BUILD = "PLG110_16.0.10"
MODELS = ["PLG110"]

OAID = "com.android.settings/com.oplus.settings.feature.notification.oaid.OAIDActivity"
MARKET = "com.heytap.market/com.heytap.market.mine.cn.setting.ui."
ADVICE = "com.oplus.pantanal.ums/com.oplus.advice.settings.ui."
GAMECENTER = "com.nearme.gamecenter/com.nearme.gamecenter.me.ui."
# 共享库按名字取这两个：system_settings 的 shell 档要设置页的包名+页面，负一屏那两段要设置页前缀。
SETTINGS = "com.android.settings/com.oplus.settings.feature.homepage.OplusSettingsHomepageActivity"
ASSISTANT = "com.coloros.assistantscreen/com.oplus.assistantscreen."

# 软件商店服务管理中明确的推广入口
STORE_PROMOTIONS = [
    "首页：悬浮活动图标", "首页：活动弹窗", "首页：顶部轮播卡片", "底部活动专区",
    "应用安全安全内容推荐",
    "游戏专区：找游戏-休闲", "游戏专区：找游戏-小游戏", "游戏专区：找游戏-种草",
    "游戏专区：找游戏", "游戏专区：重磅更新卡片", "游戏专区：活动集合",
    "游戏详情页：游戏活动卡片", "游戏详情页：游戏礼包",
    "通过游戏助手打开领取游戏福利", "软件专区：福利", "软件专区：购物", "软件专区：快应用",
    "我的专区：签到按钮", "我的专区：积分商城", "我的专区：休闲一刻",
    "我的专区：安装有礼", "我的专区：福利中心", "我的专区：金豆乐园",
    "我的专区：账号会员徽章", "我的专区：主题商店", "我的专区：应用时刻", "我的专区：游戏VIP",
    "小游戏二楼和专区", "AI智能体",
    "更新&下载专区：底部弹窗推荐", "活动式详情页", "详情页：活动", "详情页：限时活动",
    "手机管家：应用推荐", "文件管理：应用推荐", "福利专区",
]

# 各段的调用点按旧名字写，实现住在 recipe_strategies 的 `close_named_expect`（读到目标就收手，
# PLG110 的录制口径），这里绑回旧名字（#1253）。


def step_ad_tracking(p, rt):

    rt.skip_in_safe_mode()
    model = p.d.shell("getprop ro.product.model").output.strip()
    build = p.d.shell("getprop ro.build.display.id").output.strip()
    if model != "PLG110" or not build.startswith(BUILD):
        rt.skip("参考或版本不同时不批量处理逐应用广告跟踪，需重新核对")
    print("  将关闭逐应用 OAID 广告跟踪许可；不重置设备标识符。", flush=True)
    nav.system_settings(p, rt)
    rt.require(p.setting("设备标识与广告", "设备标识与广告"), "未找到设备标识与广告入口")
    nav.tap_page(p, rt, "广告跟踪", OAID, scrolls=0)
    before = nav.read_switches(p, rt, OAID, "广告跟踪", max_screens=60)
    rt.require(before, "未读到广告跟踪列表，未操作")
    if any(before.values()):
        p.top(60)
        p.off(only=list(before), page="广告跟踪", max_screens=60)
        current = nav.read_switches(p, rt, OAID, "广告跟踪", max_screens=60)
        rt.require(set(before) <= set(current) and not any(current.values()), "广告跟踪回读未确认全部关闭")
    rt.confirm(len(before))
    print(f"  · 广告跟踪：回读确认 {len(before)} 个应用关闭", flush=True)


def step_store(p, rt):

    print("  将关闭个性化推荐与推广服务；保留下载更新与应用安全。", flush=True)
    nav.app_settings(p, rt, "com.heytap.market", MARKET + "SettingActivity", "软件商店")
    nav.tap_page(p, rt, ("隐私", "隐私授权管理"), MARKET + "PrivacyActivity", scrolls=8)
    activity = MARKET + "PersonalRecommendActivity"
    nav.tap_page(p, rt, "个性化推荐", activity, scrolls=0)
    strategies.close_named_expect(p, rt, ["个性化推荐"], "软件商店·个性化推荐", activity, "个性化推荐", 4)
    # 推广入口管理
    nav.app_settings(p, rt, "com.heytap.market", MARKET + "SettingActivity", "软件商店")
    nav.tap_page(p, rt, "服务管理", MARKET + "ServeManagerActivity", scrolls=6)
    activity_serve = MARKET + "ServeManagerActivity"
    before = nav.read_switches(p, rt, activity_serve, "服务管理", 8)
    to_close = [k for k in before if k in STORE_PROMOTIONS]
    if to_close:
        p.top(8)
        p.off(only=to_close, keep=[k for k in before if k not in to_close],
              page="软件商店·服务管理", max_screens=8)
        current = nav.read_switches(p, rt, activity_serve, "服务管理", 8)
        rt.require(all(current.get(name) is False for name in to_close), "服务管理回读未确认关闭")
        rt.confirm(len(to_close))
    print("  · 软件商店·服务管理：处理完成，核心服务已保留", flush=True)


def step_game_center(p, rt):
    print("  将关闭游戏中心个性化推荐；保留游戏助手与时长同步。", flush=True)
    p.start("com.nearme.gamecenter")
    time.sleep(1.2)
    p.dismiss()
    # 弹窗压在带开关/滚动列表的页面上：p.dismiss() 只认 ✕ 图标、不点名文字按钮（见 fast.dismiss 的守卫），
    # 所以开屏与引导弹窗按页面实见的按钮逐个点名。
    for _ in range(4):
        for dismiss_btn in ("取消", "我知道了", "不再提醒", "忽略", "跳过"):
            if p.find(dismiss_btn, exact=True):
                p.tap(dismiss_btn, exact=True, scrolls=0)
                time.sleep(0.4)
    if not p.tap("我的", exact=False, scrolls=0):
        raise RuntimeError("未找到底部「我的」入口")
    time.sleep(0.8)
    for dismiss_btn in ("我知道了", "取消", "不再提醒", "忽略"):
        if p.find(dismiss_btn, exact=True):
            p.tap(dismiss_btn, exact=True, scrolls=0)
            time.sleep(0.4)
    nav.tap_page(p, rt, "设置", GAMECENTER + "SettingActivity", scrolls=0, exact=False)
    nav.tap_page(p, rt, "隐私开关设置", GAMECENTER + "PrivacySettingActivity", scrolls=2)
    activity = GAMECENTER + "PersonalRecommendActivity"
    nav.tap_page(p, rt, "个性化推荐管理", activity, scrolls=0)
    strategies.close_named_expect(p, rt, ["个性化推荐"], "游戏中心·个性化", activity, "个性化推荐管理", 2)


def step_advice(p, rt):
    print("  核对并关闭小布建议内容资讯服务；保留出行、生活等实用卡片。", flush=True)
    nav.system_settings(p, rt)
    rt.require(p.tap("OPPO AI", exact=True, scrolls=6), "未找到 OPPO AI")
    nav.tap_page(p, rt, "小布建议", ADVICE + "AdviceSettingActivity", scrolls=5)
    for _ in range(8):
        if p.find("资讯服务", exact=True):
            break
        if not p.scroll_more():
            break
    texts = [t for t, _, _ in p.texts()]
    # 相邻两行配对，长度必然差一：strict=False 是有意的
    if any("资讯服务" in t and "未开启" in x for t, x in zip(texts, texts[1:], strict=False)):
        print("  · 资讯服务已是「未开启」，保持不变", flush=True)
        return
    if p.tap("资讯服务", exact=True, scrolls=0):
        p.off(only=["资讯服务"], page="小布建议·资讯服务")
        p.back()


def tail(p, rt):
    print(f"\n已回读确认 {rt.verified} 项；分段结果：{rt.results}", flush=True)
    print("通知渠道与组件挂起仍走 run.py 的独立流程。", flush=True)
