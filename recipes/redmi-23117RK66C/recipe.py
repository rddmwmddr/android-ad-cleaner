# Redmi K70 Pro（23117RK66C），HyperOS OS3.0.306.0.WNMCNXM / Android 16。
# 入口与核对范围见 docs/14-红米K70Pro实测.md；包安装状态和联网规则不由机型脚本改动。
BUILD = "OS3.0.306.0.WNMCNXM"
MODELS = ["23117RK66C"]
import time
from entries import THEME_DEAD_ENDS
VERIFIED_SWITCHES = 0


def enter(name, scrolls=6):
    require(p.entry(name, scrolls=scrolls), f"未找到「{name}」")


@step("系统广告")
def _():
    p.start("com.android.settings", ".ad.AdServiceSettings")
    close_named(["个性化广告推荐"], "系统·广告服务")


@step("应用商店")
def _():
    # 首页的「我的」标签文字在本版本点击后不切页，设置 Activity 已在本机验证。
    p.start("com.xiaomi.market", ".ui.MarketPreferenceActivity")
    enter("隐私设置")
    enter("个性化服务")
    close_named(["个性化服务"], "商店·个性化服务")
    # 通知子页不允许外部 Activity 启动，必须从商店设置内进入。
    p.back(2)
    p.top(2)
    enter("通知设置")
    close_named(["新手帮助"], "商店·通知设置")


@step("手机管家")
def _():
    p.start("com.miui.securitycenter", "com.miui.securityscan.ui.settings.SettingsActivity")
    enter("隐私设置")
    close_named(["个性化推荐"], "管家·隐私")
    p.back()
    enter("垃圾清理")
    close_named(["推荐内容"], "管家·垃圾清理")


@step("下载管理")
def _():
    p.start("com.android.providers.downloads.ui")
    require(gear(), "下载管理设置入口未找到")
    enter("信息流设置")
    close_named(["资源推荐", "热榜推荐"], "下载管理·信息流")


@step("主题")
def _():
    # 从壳包启动会复用上次设置页，显式重建主题首页以支持连续复跑。
    if "package:" not in p.d.shell("pm path com.android.thememanager").output:
        print("  · 本机没有主题管理包，跳过"); return
    start_or_skip("com.android.thememanager", ".ThemeResourceProxyTabActivity",
                  dead_ends=THEME_DEAD_ENDS, reason="主题页打不开")
    # 导航失败不能与「本页没有目标开关」同形：三步都校验，报错带页面现场（#906）。
    if not p.go("我的", "设置"):
        raise RuntimeError("未进入主题「我的」；" + p.page_evidence())
    if not gear():
        raise RuntimeError("主题设置入口没找到；" + p.page_evidence())
    close_named(["每次联网时通知"], "主题·设置")
    enter("隐私设置")
    close_named(["个性化推荐"], "主题·隐私")


@step("浏览器")
def _():
    p.start("com.android.browser", ".preferences.activity.CustomizationPreferenceActivity")
    close_named(["个性化内容推荐", "个性化广告推荐"], "浏览器·个性化推荐")
    p.start("com.android.browser", ".BrowserSettingsActivity")
    enter("主页设置", scrolls=0)
    close_named(["宫格位推送"], "浏览器·主页设置")
    p.back()
    enter("搜索设置", scrolls=0)
    close_named(["显示猜你想搜模块"], "浏览器·搜索设置")


HOT = ["推荐", "微博", "资讯", "全网", "影视", "音乐", "小说", "知乎", "精选"]


@step("全局搜索")
def _():
    p.start("com.android.quicksearchbox", ".preferences.SearchSettingsPreferenceActivity")
    enter("首页展示模块")
    close_named(["搜索提示词"], "搜索·首页模块")
    enter("应用推荐")
    close_named(["推荐未安装应用"], "搜索·应用推荐")
    p.back()
    enter("热搜榜单")
    # 不把所有版本可能出现的榜单当成必备；每个实际打开的子页必须找到目标并回读。
    subs = [x for x in ("热搜", "生活", "话题", "娱乐") if p.find(x, exact=True)]
    require(subs, "未识别热榜分类")
    for name in subs:
        enter(name, scrolls=0)
        titles = [title for title, _, _ in p.switches() if any(k in title for k in HOT)]
        require(titles, f"热榜「{name}」未识别目标开关")
        close_named(titles, f"搜索·热榜·{name}")
        p.back()


@step("负一屏")
def _():
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    close_named(["推荐卡片", "热门活动"], "负一屏·设置")
    enter("隐私设置")
    close_named(["个性化推荐"], "负一屏·隐私")


@step("天气和日历")
def _():
    p.start("com.miui.weather2")
    enter("更多设置", scrolls=0)
    enter("设置", scrolls=0)
    enter("用户体验计划")
    close_named(["天气视频卡片", "内容推广"], "天气·用户体验计划")
    p.start("com.android.calendar")
    enter("设置", scrolls=0)
    enter("设置", scrolls=0)
    enter("用户体验计划")
    close_named(["内容推广"], "日历·用户体验计划")


print(f"\n逐页回读确认 {VERIFIED_SWITCHES} 项；步骤异常 {len(FAILED_STEPS)} 个", flush=True)
