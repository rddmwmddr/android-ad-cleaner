# 荣耀 PNM-AN10（MagicOS 10）机型脚本。2026-10-23 实测通过
# 变量 p 由 tool/fast.py 注入；ONLY 是要跑的段名列表（空=全跑）
BUILD = ""
import re
import time

import adb_link
from fast import ScreenLocked

ONLY = globals().get("ONLY") or []


def step(name):
    def deco(f):
        if (not ONLY or name in ONLY) and p.locked():
            print(f"\n== {name}：手机锁屏了，后面的都不跑"); return f
        if not ONLY or name in ONLY:
            print(f"\n== {name}"); p.miss = 0
            t = time.time()
            try:
                f()
            except Exception as e:
                print(f"  ✗ 出错：{e}")
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


def dismiss(*words):
    """开 App 时的推荐弹窗/协议弹窗：一律点「取消/以后再说/禁止」，不替用户同意。"""
    for _ in range(3):
        tx = {t for t, _, _ in p.texts()}
        hit = [w for w in words if w in tx]
        if not hit:
            return
        p.tap(hit[0], exact=True, scrolls=0)


NO = ("取消", "以后再说", "禁止", "暂不", "跳过", "我知道了")


def open_settings(expect=("个性化服务", "通知")):
    """进「设置」入口，落地页出现 expect 之一才算成功。
    MagicOS 10 把入口放在「我的」页内部，位置与读法各版本不同：文字精确 → 文字包含
    （「设置,有1条新通知」）→ 右上角图标，点错页先退回来再换下一级（#286 / #238）。"""
    for exact in (True, False):
        if not p.find("设置", exact=exact):
            continue
        before = p.sig()
        if p.tap("设置", exact=exact, scrolls=0) and any(p.find(w, exact=True) for w in expect):
            return True
        if p.sig() != before:
            p.back()
    return p.tap_icon(list(expect))


def open_entry(text, scrolls=0):
    """点开会换页的菜单项，点不进去就记下停在哪一页并跳过本段。
    p.enter 先精确匹配、落空退包含匹配，再用页面变化确认真的进去了——p.entry 只点不确认（#238）。
    断线与锁屏照常上抛：它们不能记成「入口改名」。"""
    try:
        p.enter(text, scrolls=scrolls)
    except (adb_link.DeviceLost, ScreenLocked):
        raise
    except RuntimeError as error:
        print(f"  · {error}")
        p.note_miss(text)
        return False
    return True


@step("广告跟踪")
def _():
    if not p.setting("广告", "广告与隐私"):
        # 部分 MagicOS 10 机型设置搜索框打不开（#88 #99），按菜单进：隐私和安全 → 其他隐私和安全功能 → 广告与隐私
        p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
        p.miss = 0
        if not (p.tap("隐私和安全", exact=True) and p.tap("其他隐私和安全功能", exact=True)
                and p.tap("广告与隐私", exact=True)):
            return
    p.tap("更多选项", scrolls=0)
    if p.find("显示系统程序", exact=True):
        p.tap("显示系统程序", exact=True, scrolls=0)
        p.tap("更多选项", scrolls=0)
    p.tap("全部关闭", exact=True, scrolls=0)
    p.confirm()
    p.start("com.hihonor.id", ".oaid.ui.IntelligentRecommendActivity", settle=0.5)
    p.off(page="广告与隐私·智能推荐服务")


@step("YOYO")
def _():
    p.setting("新闻资讯")
    dismiss(*NO)
    p.off(only=["新闻资讯"], page="YOYO 建议")


@step("搜索")
def _():
    p.d.press("home"); time.sleep(0.6); p.d.press("home"); time.sleep(0.6)
    p.d.shell(f"input swipe {p.W//2} {p.H*3//10} {p.W//2} {p.H*7//10} 300"); time.sleep(1.5)
    p.d.press("back"); time.sleep(0.5)          # 收起键盘，菜单位置才固定
    xy = None
    for t, (l, tp, r, b), n in p.texts():
        if t == "更多" and tp > p.H * 0.3:
            xy = ((l + r) // 2, (tp + b) // 2)
    if not xy:
        print("  ✗ 找不到搜索框旁的「更多」"); return
    p.click(*xy); time.sleep(0.6)
    p.tap("设置", exact=True, scrolls=0)
    p.tap("首页显示", exact=True)
    p.off(only=["热搜榜", "热搜词推荐"], page="搜索·首页显示")
    p.back()
    p.tap("个性化管理", exact=True)
    p.off(page="搜索·个性化管理")


@step("负一屏")
def _():
    p.d.press("home"); time.sleep(0.6)
    for _ in range(3):
        p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
        if p.find("头像", exact=True):
            break
    p.tap("头像", exact=True, scrolls=0)
    p.tap("设置", exact=True, scrolls=0)
    p.off(only=["智能推荐", "个性化广告", "个性化消息"], page="负一屏·设置")
    p.back()
    p.tap("资讯服务", exact=True, scrolls=0)
    p.off(only=["资讯精选"], page="负一屏·资讯服务")
    p.back(3)


@step("桌面文件夹")
def _():
    # 「热门推荐」「精品应用」文件夹底部的更多推荐：设置页由应用市场提供
    p.start("com.hihonor.appmarket", ".module.topapps.TopAppsSettingActivity")
    p.off(page="精品应用·更多推荐")
    p.start("com.hihonor.appmarket", ".popularapps.activity.PopularAppsSettingActivity")
    p.off(page="热门推荐管理")


@step("市场")
def _():
    p.start("com.hihonor.appmarket")
    if p.find("基本服务", exact=True, edge_ok="tab") and not p.find("我的", exact=True, edge_ok="tab"):
        print("  已是基本服务模式（没有推荐、没有设置入口），跳过"); return
    p.tap("我的", exact=True, scrolls=0)
    dismiss(*NO)
    p.tap("设置", exact=True, scrolls=0)
    p.tap("内容推荐服务", exact=True)
    # 两个开关连着点，第二个会被吞，分开关
    p.off(only=["营销服务推荐"], page="市场·内容推荐服务")
    p.off(only=["个性化服务推荐"], page="市场·内容推荐服务")
    p.back()
    p.tap("消息通知管理", exact=True)
    p.off(only=["消息通知"], keep=["应用更新"], page="市场·消息通知管理")
    p.back()
    p.tap("消息中心提醒", exact=True)
    p.off(only=["活动福利", "游戏动态"], page="市场·消息中心提醒")
    p.back()
    # 最后切「基本服务」：切过去以后没有设置入口，切回「完整服务」要重新同意协议（会重新打开个性化），别切回
    p.tap("服务模式", exact=True)
    if p.tap("基本服务", exact=True, scrolls=0):
        p.confirm()
    p.back()


def browser_settings():
    if "package:" not in p.d.shell("pm path com.honor.browser").output:
        return baidu_browser()
    p.start("com.honor.browser")
    p.dismiss()
    if p.find("我的", exact=True):                       # 经典首页：我的 → 右上第三个图标
        p.tap("我的", exact=True, scrolls=0)
        p.d(resourceId="com.honor.browser:id/top_local_icon")[2].click()
        time.sleep(1)
    else:                                                # 简洁首页：更多 → 设置
        p.tap("更多", exact=True, scrolls=0)
        p.tap("设置", exact=True, scrolls=0)


def baidu_browser():
    """新机预装 com.hihonor.baidu.browser（#87 社区实测 PTP-AN00）：我的 → 右上齿轮 → 消息设置 / 隐私设置。
    「广告设置」是网页，读不到开关；其中「不看程序化广告」「不看个性化广告」要打开，请手动处理。"""
    p.start("com.hihonor.baidu.browser")
    p.dismiss()
    for text, (l, t, r, b), _ in p.texts():
        if text == "我的" and t >= p.H * 0.8:
            p.click((l + r) // 2, (t + b) // 2); time.sleep(1); break
    else:
        print("  ✗ 没找到底部「我的」"); return False
    from fast import bounds
    icons = [n for n in p.tree().iter("node") if n.get("clickable") == "true" and p.on_screen(n)
             and bounds(n)[3] < p.H * 0.15 and bounds(n)[0] > p.W * 0.5
             and re.search(r"设置|setting", (n.get("content-desc") or "") + (n.get("resource-id") or ""), re.I)]
    if len(icons) != 1:
        print("  ✗ 没找到右上角唯一的设置图标"); return False
    l, t, r, b = bounds(icons[0]); p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
    if p.tap("消息设置", exact=True):
        p.off(only=["新闻热点", "兴趣推送"], page="浏览器·消息设置")
        p.back()
    if p.tap("隐私设置", exact=True):
        p.off(only=["搜索个性化推荐", "搜索下一条推荐"], page="浏览器·隐私设置")
        p.back()
    print("  · 「隐私设置 → 偏好设置 → 广告设置」是网页，请手动打开「不看程序化广告」「不看个性化广告」")
    p.back(2)
    return False


@step("浏览器")
def _():
    if browser_settings() is False:
        return
    p.tap("模式选择", exact=True)
    p.tap("简洁首页", exact=True, scrolls=0)
    p.back()
    p.tap("消息通知", exact=True)
    p.off(only=["新闻热点", "兴趣推送"], page="浏览器·消息通知")
    p.back()
    p.tap("隐私管理", exact=True)
    p.tap("个性化推荐", exact=True, scrolls=0)
    p.off(only=["个性化内容"], page="浏览器·个性化推荐")
    p.back()
    p.tap("互动广告管理", exact=True, scrolls=0)
    p.off(page="浏览器·互动广告")
    p.back(3)


@step("主题")
def _():
    p.start("com.hihonor.android.thememanager")
    p.dismiss()
    # 底栏标签只在屏幕最下方找，比原来的全屏点击严；底栏不在最下方的机型退回原写法，
    # 到没到「我的」页由 open_settings() 的落点校验兜底（#238）。
    if not p.tab("我的"):
        p.tap("我的", exact=True, scrolls=0)
    p.dismiss()
    if not open_settings(("个性化服务", "通知")):
        p.note_miss("设置")
        return
    p.enter("通知")
    p.off(page="主题·通知")            # 消息/短信/邮件 三项都是「内容推荐和活动信息」
    p.back()
    p.enter("个性化服务")
    p.off(page="主题·个性化服务")
    p.back(3)


@step("视频")
def _():
    # 荣耀「视频」是优酷荣耀版；设置页能直接拉起
    p.start("com.hihonor.youku.video", "com.youku.android.youkusetting.activity.SettingsActivity")
    p.dismiss()
    p.tap("其他设置", exact=True)
    p.off(only=["个性化内容", "个性化广告", "OAID"], page="视频·其他设置")
    p.back(2)


@step("系统管家")
def _():
    p.start("com.hihonor.systemmanager", ".mainscreen.SettingActivity")
    p.off(only=["应用推荐"], page="系统管家·设置")   # 扩展业务里都是清理/查杀/拦截功能，不动
    p.back()


@step("音乐")
def _():
    # 荣耀「音乐」是网易云荣耀版。「个性化服务」管每日推荐/私人雷达，属于听歌功能，保留
    p.d.app_stop("com.hihonor.cloudmusic")
    p.start("com.hihonor.cloudmusic")
    time.sleep(1); p.dismiss()
    p.d(text="我的").click(); time.sleep(1); p.dismiss()
    p.d(resourceId="com.hihonor.cloudmusic:id/ic_setting").click(); time.sleep(1.2)
    if not open_entry("更多设置"):      # 抽屉里别翻，翻了会误点到扫一扫
        return
    # 「更多设置」页里这两个入口要滚到中部才看得到（#88 同一 build 实测），翻页保留
    if not open_entry("消息和隐私设置", scrolls=6):
        return
    p.off(only=["朋友页显示推荐动态"], page="音乐·消息和隐私")
    if not open_entry("第三方推送服务开关", scrolls=6):
        return
    p.off(page="音乐·第三方推送（活动、中奖信息）")
    p.back(3)


@step("阅读")
def _():
    p.start("com.hihonor.dz.reader")
    p.go("我的", "更多设置")
    p.tap("更多设置", exact=True)
    # 这个 App 每次重启会把「接收新通知」自己打开；真正挡住推送的是 channels.tsv 里它的两个通知渠道
    p.off(only=["接收新通知"], page="阅读·设置（推书通知）")      # 自绘开关，引擎按颜色判断
    p.tap("广告推荐服务", exact=True, scrolls=0)
    p.off(page="阅读·广告推荐服务")
    p.back(2)


@step("魔法画报")
def _():
    # 锁屏杂志在荣耀叫「魔法画报」；轮播本来就关着
    p.setting("杂志", "魔法画报")
    p.tap("魔法画报", exact=True, scrolls=0)        # 右栏的「魔法画报」入口
    if "magazine" not in p.focus():
        xy = [b for t, b, _ in p.texts() if t == "魔法画报"]
        if len(xy) > 1:
            l, t, r, b = xy[-1]; p.click((l + r) // 2, (t + b) // 2); time.sleep(1.2)
    p.off(only=["锁屏画报轮播", "锁屏进入魔法画报"], page="魔法画报")
    p.back()
