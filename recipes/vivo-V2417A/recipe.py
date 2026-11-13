# vivo V2417A，Android 16，PD2417D_A_16.2.14.1.W10。路径来自 2026-10-30 真机逐页操作；验证范围及复跑记录见同目录 README.md。
from recipe_kit import step
BUILD = "PD2417D_A_16.2.14.1.W10"
MODELS = ["V2417A"]
# 家族库按这个常量选走法（#1246），缺省档与实现见 tool/recipe_nav.py。
READ_SWITCHES_STYLE = "vivo"

# 回读确认数由引擎经 rt 记录


def title_key(title):
    # vivo 将说明拼在点号后；「，开启/，关闭」状态尾缀已由引擎在标题产出处剥掉（#565）。
    return title.split(".", 1)[0].strip()


def verify(before, current, names, page):
    # 回读确认数由引擎经 rt 记录
    require(all(current.get(name) is False for name in names), f"{page}：回读未确认关闭")
    require(all(current.get(name) == state for name, state in before.items() if name not in names),
            f"{page}：其他开关状态变化，请核对")
    rt.confirm(len(names))
    print(f"  ✓ {page}：回读确认 {len(names)} 项关闭，其他开关未变", flush=True)


@step("系统广告")
def _():
    # $ 由 Phone._launch 交给 Android shell 前整串引用一次，这里照字面量写。
    # 这是设置页，不是 App 首页；说明里的“关闭后”会被通用消弹窗误认为关闭按钮。
    p.start("com.android.settings", ".Settings$AdAndPrivacyActivityForOsTwo", settle=0)
    require("AdAndPrivacyActivityForOsTwo" in p.focus(), "未进入广告与隐私页")
    close_named(["个性化广告", "个性化推荐", "智能推荐服务"], "系统·广告与隐私")


@step("全局搜索")
def _():
    p.start("com.vivo.globalsearch", ".view.SearchSettingsActivity")
    tap("首页展示内容", scrolls=0)
    close_named(["搜索框推荐词", "推荐卡片"], "全局搜索·首页展示内容")
    tap("推荐热搜榜单", scrolls=0)
    close_named(["热门搜索"], "全局搜索·热搜榜单")
    p.back(2)
    tap("个性化内容", scrolls=0)
    close_named(["广告个性化"], "全局搜索·个性化内容")
    # 全局搜索总开关、历史记录、语音搜索、应用建议及搜索结果个性化保持原值。


@step("阅图锁屏")
def _():
    p.start("com.vivo.magazine", ".ui.MagazineSettings")
    close_named(["阅图锁屏", "锁屏横滑进入阅图"], "阅图锁屏", max_screens=2)


@step("应用商店")
def _():
    p.start("com.bbk.appstore")
    # 冷启动的“月度精品”推荐页只进入首页，不点安装。
    if p.find("进入首页", exact=True):
        tap("进入首页", scrolls=0)
    require(p.go("我的", "设置"), "未进入商店·我的页")
    require(p.go("设置", "关于"), "未进入商店设置")
    require("AppstoreSettingsActivity" in p.focus(), "商店设置页面不符")
    tap("关于")
    tap("个性化推荐")
    store_personalization()
    p.back()
    tap("服务管理")
    close_named(["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮球", "限时推广"],
                "商店·服务管理", max_screens=2)
    # “我的页-我的服务”“空间清理”、下载更新设置不修改。


@step("浏览器")
def browser():
    p.start("com.vivo.browser", settle=2.0)
    # 入口随浏览器版本变：31.1.3.1 是底部「菜单」→「设置」；31.3.0.0 起底部标签栏改成
    # 首页/视频/AI/影视小说/我的，没有「菜单」，「设置」挂在「我的」页右上角，文字只在
    # content-desc 里（texts() 取 text 或 content-desc，按「设置」能找到，不用 tap_icon——
    # 它只挑文字与 desc 都为空的节点）。SettingActivity 未导出，am start 直达抛
    # SecurityException: not exported from uid，只能从界面走。
    if not p.entry("菜单", scrolls=0):
        require(p.go("我的", "设置"), "未打开浏览器设置入口（「菜单」与「我的」都试过；权限申请只拒绝）")
    require(p.go("设置", "首页设置"), "未进入浏览器设置")
    require("SettingActivity" in p.focus(), "浏览器设置页面不符")
    tap("首页设置")
    tap("极简首页", scrolls=0)
    require(p.find("首页上滑展示资讯", exact=True), "未切换到极简首页")
    close_named(["首页上滑展示资讯"], "浏览器·首页设置")
    p.back()
    tap("网页浏览设置")
    close_named(["网页下载相关推荐"], "浏览器·网页浏览")
    p.back()
    tap("更多设置")
    close_named(["WiFi连接跳转新闻资讯", "下载管理页展示热门应用", "下载管理页展示下载热榜"],
                "浏览器·更多设置", max_screens=2)
    p.back()
    tap("隐私权限设置")
    close_named(["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"], "浏览器·隐私")


@step("i管家")
def _():
    p.start("com.iqoo.secure", ".MainSettings")
    tap("关于")
    tap("个性化设置")
    close_named(["应用个性化推荐"], "手机管家·个性化设置")


@step("天气")
def _():
    p.start("com.vivo.weather", ".WeatherSettings")
    # 此页“天气服务”的说明是“接收天气相关热点资讯通知”。
    close_named(["天气服务"], "天气·热点资讯通知")
    # 气象预警、异常天气、地震预警不修改。


@step("负一屏")
def _():
    hiboard_panel()
    tap("更多设置", scrolls=0)
    tap("个性化推荐", scrolls=0)
    close_named(["服务推荐", "资讯推荐"], "负一屏·个性化推荐")
    p.back(2)
    for name in ("内容精选", "热点资讯"):
        hiboard_panel()
        tap(name, scrolls=0)
        close_named([name], f"负一屏·{name}")
        p.back()
    # 便捷生活里的“推荐服务”、小V建议和常驻服务卡片全部保留。


def tail():
    print(f"\n回读确认 {rt.verified} 项关闭；未完成 {len(rt.failed_steps)} 段", flush=True)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from recipe_kit import p, require, require_switches, rt
    from recipe_nav import hiboard_panel, read_switches, tap
    from recipe_strategies import close_named_vivo, store_personalization

# 各段的调用点按旧名字写，实现住在 recipe_strategies 的 `close_named_vivo`（回读走本机的
# `verify`），这里绑回旧名字（#1253）。
close_named = close_named_vivo
