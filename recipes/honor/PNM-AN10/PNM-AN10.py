# 荣耀 PNM-AN10（MagicOS 10）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 browser_settings / open_settings / skip_in_safe_mode / SkipStep 由装载器注入执行作用域。
# 线性段已转成 `.toml` 数据；这里只留过程化的段（坐标、选择器、dumpsys、条件分支）与两个助手。
import adb_link
import time
from fast import ScreenLocked
import recipe_nav as nav
from recipe_runtime import SkipStep
# 本机没装荣耀浏览器时 browser_settings 会回退到预装百度浏览器那套；这份依赖在事实层要留一条出处。
from recipe_strategies import baidu_browser


BUILD = ""
MODELS = ["PNM-AN10"]

def dismiss(p, rt, *words):
    """开 App 时的推荐弹窗/协议弹窗：一律点「取消/以后再说/禁止」，不替用户同意。"""
    for _ in range(3):
        tx = {t for t, _, _ in p.texts()}
        hit = [w for w in words if w in tx]
        if not hit:
            return
        p.tap(hit[0], exact=True, scrolls=0)


NO = ("取消", "以后再说", "禁止", "暂不", "跳过", "我知道了")


def dismiss_no(p, rt):
    dismiss(p, rt, *NO)


def open_entry(p, rt, text, scrolls=0):
    """点开会换页的菜单项，点不进去就记下停在哪一页并跳过本段。断线与锁屏照常上抛。"""
    try:
        p.enter(text, scrolls=scrolls)
    except (adb_link.DeviceLost, ScreenLocked):
        raise
    except RuntimeError as error:
        print(f"  · {error}")
        p.note_miss(text)
        return False
    return True


def step_ad_tracking(p, rt):
    rt.skip_in_safe_mode()
    try:
        p.start("com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", expect="应用广告跟踪管理")
    except (adb_link.DeviceLost, ScreenLocked, SkipStep):
        raise
    except RuntimeError:
        if not p.setting("广告", "广告与隐私"):
            p.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS"); time.sleep(1.2)
            p.miss = 0
            if not (p.tap("隐私和安全", exact=True) and p.tap("其他隐私和安全功能", exact=True)
                    and p.tap("广告与隐私", exact=True)):
                raise RuntimeError("没找到「广告与隐私」入口") from None
    p.tap("更多选项", scrolls=0)
    if p.find("显示系统程序", exact=True):
        p.tap("显示系统程序", exact=True, scrolls=0)
        p.tap("更多选项", scrolls=0)
    p.tap("全部关闭", exact=True, scrolls=0)
    p.confirm()
    p.start("com.hihonor.id", ".oaid.ui.IntelligentRecommendActivity", settle=0.5)
    p.off(page="广告与隐私·智能推荐服务")


def step_search(p, rt):
    p.start("com.hihonor.search", ".feature.mainpage.presentation.page.HomeActivity", expect="更多")

    def more_at():
        for t, (l, tp, r, b), _n in p.texts():
            if t == "更多" and tp > p.H * 0.3:
                return (l + r) // 2, (tp + b) // 2
        return None

    xy = more_at()
    if not xy:
        p.d.press("back"); time.sleep(0.5)
        xy = more_at()
    if not xy:
        raise RuntimeError("找不到搜索框旁的「更多」")
    p.click(*xy); time.sleep(0.6)
    p.tap("设置", exact=True, scrolls=0)
    p.tap("首页显示", exact=True)
    p.off(only=["热搜榜", "热搜词推荐"], page="搜索·首页显示")
    p.back()
    p.tap("个性化管理", exact=True)
    p.off(page="搜索·个性化管理")


def step_negative(p, rt):
    p.d.shell("am start -f 0x10008000 -n com.hihonor.hiboard/com.hihonor.intelligent.LauncherActivity")
    time.sleep(2)
    if not p.find("头像", exact=True):
        p.d.press("home"); time.sleep(0.6)
        for _ in range(3):
            p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
            if p.find("头像", exact=True):
                break
        else:
            raise RuntimeError("负一屏没打开，没找到头像入口")
    p.tap("头像", exact=True, scrolls=0)
    p.tap("设置", exact=True, scrolls=0)
    p.off(only=["智能推荐", "个性化广告", "个性化消息"], page="负一屏·设置")
    p.back()
    p.tap("资讯服务", exact=True, scrolls=0)
    p.off(only=["资讯精选"], page="负一屏·资讯服务")
    p.back(3)


def step_market(p, rt):
    p.start("com.hihonor.appmarket")
    if p.find("基本服务", exact=True, edge_ok="tab") and not p.find("我的", exact=True, edge_ok="tab"):
        print("  已是基本服务模式（没有推荐、没有设置入口），跳过"); return
    p.tap("我的", exact=True, scrolls=0)
    dismiss(p, rt, *NO)
    p.tap("设置", exact=True, scrolls=0)
    p.tap("内容推荐服务", exact=True)
    p.off(only=["营销服务推荐"], page="市场·内容推荐服务")
    p.off(only=["个性化服务推荐"], page="市场·内容推荐服务")
    p.back()
    p.tap("消息通知管理", exact=True)
    p.off(only=["消息通知"], keep=["应用更新"], page="市场·消息通知管理")
    p.back()
    p.tap("消息中心提醒", exact=True)
    p.off(only=["活动福利", "游戏动态"], page="市场·消息中心提醒")
    p.back()
    p.tap("服务模式", exact=True)
    if p.tap("基本服务", exact=True, scrolls=0):
        p.confirm()
    p.back()


def step_browser(p, rt):
    if nav.browser_settings(p, rt) is False:
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


def step_theme(p, rt):
    rt.skip_in_safe_mode()
    p.start("com.hihonor.android.thememanager")
    p.dismiss()
    if not p.tab("我的"):
        p.tap("我的", exact=True, scrolls=0)
    p.dismiss()
    if not nav.open_settings(p, rt, ("个性化服务", "通知")):
        p.note_miss("设置")
        return
    p.enter("通知")
    p.off(page="主题·通知")
    p.back()
    p.enter("个性化服务")
    p.off(page="主题·个性化服务")
    p.back(3)


def step_music(p, rt):
    p.d.app_stop("com.hihonor.cloudmusic")
    p.start("com.hihonor.cloudmusic")
    time.sleep(1); p.dismiss()
    p.d(text="我的").click(); time.sleep(1); p.dismiss()
    p.d(resourceId="com.hihonor.cloudmusic:id/ic_setting").click(); time.sleep(1.2)
    if not open_entry(p, rt, "更多设置"):
        return
    if not open_entry(p, rt, "消息和隐私设置", scrolls=6):
        return
    p.off(only=["朋友页显示推荐动态"], page="音乐·消息和隐私")
    if not open_entry(p, rt, "第三方推送服务开关", scrolls=6):
        return
    p.off(page="音乐·第三方推送（活动、中奖信息）")
    p.back(3)


def step_magazine(p, rt):
    if not p.setting("杂志", "魔法画报"):
        raise RuntimeError("没搜到「魔法画报」")
    p.tap("魔法画报", exact=True, scrolls=0)
    if "magazine" not in p.focus():
        xy = [b for t, b, _ in p.texts() if t == "魔法画报"]
        if len(xy) > 1:
            l, t, r, b = xy[-1]; p.click((l + r) // 2, (t + b) // 2); time.sleep(1.2)
    p.off(only=["锁屏画报轮播", "锁屏进入魔法画报"], page="魔法画报")
    p.back()
