# V2547A 的本机例外函数（catalog 的 `code=`，影随 `V2547A.toml`）。本机 8 段都是过程段
# （goto / 循环 / confirm2 / resourceId 点击），逐字保留原实现；线性助手照留。
# vivo X300 Ultra（V2547A，OriginOS 7，Android 17）机型脚本；2026-10-25 在真机逐页实测，8 段整段跑通，重跑 126 秒。
import recipe_nav as nav
import recipe_strategies as strategies
BUILD = "PD2547B_A_17.1.10.2"          # ro.build.display.id 的开头；对不上引擎只提示，不阻断
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
#
# 这台和 docs/清单/vivo-OriginOS.md 里实测的 V2547DA（OriginOS 6）不是同一版系统，入口有几处不同：
#   · 浏览器冷启动停在首页，底部没有「我的」，只能走右上「菜单 → 设置」
#   · 应用商店的「服务管理」「个性化推荐」在「设置 → 关于」里，且必须点行中间（点左侧文字不转发点击）
#   · 天气的设置藏在右上 more_btn 后面（页面里那个「更多」是展开按钮，按文字找会点错）
#   · 关推荐类开关会弹「温馨提示 → 取消 / 确认关闭」，按钮节点 text 是空的，文字挂在 vbutton_title 里（#397）
#   · 开关行是「整行 + 开关」两个 checkable 节点（y 差 7px），整行节点的标题还会串到上一行，
#     所以下面自己扫了一遍树，按行还原标题、排除单选钮，再逐行只点一次
import re
import time

# 家族库按这些常量选走法（#1246），缺省档与实现见 tool/recipe_nav.py 与 tool/recipe_strategies.py。
TAP_ROW_STYLE = "centre"
TAP_TEXT_STYLE = "vivo"
GOTO_STYLE = "vivo"
BROWSER_FLOW = "vivo_menu"


# ---------- vivo 专用 ----------
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
# 关推荐类开关后的二次确认框。注意顺序：长词优先，避免 "关闭" 抢先命中
CONFIRM = ("确认关闭", "仍要关闭", "仍然关闭", "确定关闭", "继续关闭", "关闭推荐", "确定", "确认", "关闭")


def bounds_of(p, rt, n):
    m = BOUNDS.match(n.get("bounds") or "")
    return tuple(map(int, m.groups())) if m else (0, 0, 0, 0)


# ---------- 各段 ----------

def step_ad_privacy(p, rt):
    if not nav.search_setting(p, rt, "广告与隐私"):
        print("  ✗ 没进到广告与隐私"); return
    print("  · 广告与隐私")
    strategies.off(p, rt, only=["个性化广告", "个性化推荐", "智能推荐服务"], page="系统·广告与隐私")
    # 「生活服务」推送建议不在本机型清单范围内，不动
    p.back(1)


def step_negative(p, rt):
    if not nav.hiboard_panel_v2547a(p, rt):
        print("  ✗ 没滑到负一屏（桌面可能没开负一屏），跳过"); return
    print("  · 负一屏设置面板")
    if nav.goto(p, rt, "更多设置"):
        if nav.goto(p, rt, "个性化推荐"):
            strategies.off(p, rt, only=["服务推荐", "资讯推荐"], page="负一屏·个性化推荐")
    # ⚠ 便捷生活里的「推荐服务」不要关：那 10 个图标（扫码、手电筒、计算器）都靠它补位，关了整块变空
    for name in ("内容精选", "热点资讯"):
        if not nav.hiboard_panel_v2547a(p, rt):
            print("  ✗ 回不到负一屏设置面板"); break
        p.top()
        # 热点资讯页的标题会串成页标题，rows() 已按行还原真实标题；
        # 悬浮/经典/卡片形态是单选钮，rows() 也排除了，不会被当开关拨
        if nav.goto(p, rt, name, scrolls=6):
            strategies.off(p, rt, only=[name], page=f"负一屏·{name}")
    # 小V建议（航班、快递提醒）保留不动
    p.back(3)


def step_global_search(p, rt):
    p.start("com.vivo.globalsearch", ".view.SearchSettingsActivity", settle=0.8)
    if "globalsearch" not in p.focus():
        print("  ✗ 没拉起全局搜索设置"); return
    if nav.goto(p, rt, "首页展示内容"):
        strategies.off(p, rt, only=["搜索框推荐词", "推荐卡片"], page="搜索·首页展示内容")
        if nav.goto(p, rt, "推荐热搜榜单", scrolls=4):
            strategies.off(p, rt, only=["热门搜索"], page="搜索·推荐热搜榜单")
            p.back(1)
        p.back(1)
    p.top()
    if nav.goto(p, rt, "个性化内容"):
        strategies.off(p, rt, only=["广告个性化"], page="搜索·个性化内容")   # 应用建议、搜索结果个性化保留
        p.back(1)
    # 「搜索项」是搜索范围本身，不动
    p.back(1)


def step_store(p, rt):
    p.start("com.bbk.appstore", settle=1.0)
    if not nav.tap_text(p, rt, "我的"):
        print("  ✗ 没找到「我的」"); return
    if not nav.tap_text(p, rt, "设置"):
        print("  ✗ 「我的」页没找到设置"); return
    print(f"  · 商店设置页 {p.focus()}")
    if nav.goto(p, rt, "关于"):
        if nav.goto(p, rt, "个性化推荐"):
            strategies.off(p, rt, only=["个性化推荐"], page="商店·个性化推荐")
            p.back(1); time.sleep(0.8)
        p.top()
        if nav.goto(p, rt, "服务管理", scrolls=2):
            # 这一页用白名单：「我的服务」「空间清理」要留着
            strategies.off(p, rt, only=["签到有礼", "顶部轮播图", "顶部栏目", "开屏", "摇一摇", "悬浮窗", "限时推广"],
                keep=["我的服务", "空间清理"], page="商店·服务管理")
            p.back(1); time.sleep(0.8)
        p.back(1)
    p.back(3)


def step_browser(p, rt):
    p.start("com.vivo.browser", settle=1.5)
    if not nav.browser_settings(p, rt):
        print("  ✗ 没进到浏览器设置"); return
    print(f"  · 浏览器设置页 {p.focus()}")
    if nav.goto(p, rt, "首页设置"):
        if p.tap("极简首页", exact=True, scrolls=0):    # 三选一的卡片，不能点行中间
            strategies.confirm2(p, rt)
            print("  · 首页切成极简首页")
        p.back(1); time.sleep(0.6); p.top()
    for name, words in (("网页浏览设置", ["网页下载相关推荐"]),
                        ("更多设置", ["WiFi连接跳转新闻资讯"]),        # 在设置页中段
                        ("隐私权限设置", ["个性化内容", "第三方应用来源个性化推荐", "个性化广告推荐"])):
        p.top()                                   # 每次都从顶部开始翻，位置才可预期
        if nav.goto(p, rt, name, scrolls=10):
            strategies.off(p, rt, only=words, page=f"浏览器·{name}")
            p.back(1); time.sleep(0.6)
    p.back(3)


def step_lock_screen(p, rt):
    if not nav.search_setting(p, rt, "阅图锁屏"):
        print("  ✗ 没进到阅图锁屏"); return
    if "MagazineSettings" not in p.focus():        # 万一停在搜索结果页，再点一次结果
        p.tap("阅图锁屏", exact=True, scrolls=4)
        time.sleep(1.5)
    print(f"  · 阅图锁屏页 {p.focus()}")
    strategies.off(p, rt, only=["阅图锁屏", "锁屏横滑进入阅图"],
        keep=["锁屏底部壁纸", "移动网络自动更新"], page="系统·阅图锁屏")
    # 锁屏壁纸保持原样
    p.back(2)


def step_i_manager(p, rt):
    p.start("com.iqoo.secure", settle=2.0)
    time.sleep(1.2)                            # 首屏有体检动画，动画期间点设置会被吞
    ok = False
    for _ in range(3):
        if p.tap("设置", exact=True, scrolls=0):
            time.sleep(1.2)
            if "MainSettings" in p.focus():
                ok = True
                break
    if not ok:
        print("  ✗ 没进到 i 管家设置"); return
    if nav.goto(p, rt, "关于", scrolls=2):
        if nav.goto(p, rt, "个性化设置", scrolls=2):
            strategies.off(p, rt, only=["应用个性化推荐", "清理个性化推荐"], page="i管家·个性化设置")
            p.back(1)
        p.back(1)
    p.back(2)


def step_weather(p, rt):
    p.start("com.vivo.weather", settle=1.2)
    # 页面上也有个「更多」文字（展开按钮），右上角才是菜单，按 resourceId 点
    try:
        p.d(resourceId="com.vivo.weather:id/more_btn").click()
    except Exception:
        print("  ✗ 没找到天气右上角的更多按钮"); return
    time.sleep(1.3)
    if not nav.tap_text(p, rt, "设置"):
        print("  ✗ 天气菜单里没找到设置"); return
    print(f"  · 天气设置页 {p.focus()}")
    strategies.off(p, rt, only=["天气服务"], keep=["气象预警", "异常天气", "地震预警"], page="天气·设置")
    # 气象预警、异常天气、地震预警、提醒城市都保留
    p.back(2)

