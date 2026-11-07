# 荣耀 Magic V Flip2（CLE-AN00，MagicOS 10 / Android 16）机型脚本。路径 2026-11-07 在本机逐段实测（#671）。
# 和 PNM-AN10 同代，差别：预装百度版浏览器；桌面文件夹的设置页没导出，热门推荐管理并进了市场「内容推荐服务」。
# 能直达的都直达：手机版在后台屏上跑，桌面手势在那块屏上不生效。
# 不切市场的「基本服务」：切回完整服务要重新同意协议。不代为同意任何协议或权限。
# 用法：python3 tool/run.py -s 序列号 recipe [段名…]   不带段名=全跑
BUILD = "CLE-AN00 10.0.0"
MODELS = ["CLE-AN00"]
import re
import time

import adb_link
from fast import bounds

ONLY = globals().get("ONLY") or []
FAILED_STEPS = []


class SkipStep(Exception):
    """这一段按约定不跑（比如协议还没同意），不算失败。"""


def step(name):
    def deco(f):
        if (not ONLY or name in ONLY) and p.locked():
            print(f"\n== {name}：手机锁屏了，后面的都不跑"); return f
        if not ONLY or name in ONLY:
            print(f"\n== {name}"); p.miss = 0
            t = time.time()
            try:
                f()
            except adb_link.DeviceLost:
                raise
            except SkipStep as e:
                print(f"  · 跳过：{e}")
            except Exception as e:
                FAILED_STEPS.append(name)
                print(f"  ✗ 未完成：{e}")
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


def enter(text, scrolls=4):
    """必需入口：没有就是这一段没跑成，不能报成功。"""
    if not p.entry(text, scrolls=scrolls):
        raise RuntimeError(f"入口「{text}」没找到")


def no_agreement(app):
    """App 还弹着用户协议就停：引擎的弹窗处理会点「取消」，App 随之退出，后面全是空跑。
    按钮贴着屏幕底也要算：find 默认不看最底下那一条，而后台屏上协议框的按钮可能正好落在那里。"""
    if p.find("同意", exact=True, edge_ok="tab") or p.find("同意并继续", exact=True, edge_ok="tab"):
        raise SkipStep(f"{app}还没同意用户协议，不代为同意。需要的话打开{app}同意后，单独跑这一段")


def wait_open(pkg, app):
    """等它真的到前台。后台屏冷启动慢，不等的话后面会在上一个 App 的页面上找入口。"""
    for _ in range(20):
        if p.focus().split("/", 1)[0] == pkg and p.has_text():
            return
        time.sleep(0.5)
    raise RuntimeError(f"{app}没有打开")


def launch(activity, app):
    """裸启动。弹着协议时 p.start 会替我们点「取消」，App 一退就分不清是没同意还是没打开。
    p.start 平时会登记目标 App 并清推广位记录，绕开它就要自己补，否则后面按上一段的 App 判推广位。"""
    pkg = activity.split("/", 1)[0]
    p.app = pkg
    p.promoted.clear()
    p.d.shell(f"am start -f 0x10008000 -n {activity}")
    wait_open(pkg, app)


def wait_home(app):
    """协议框比首页晚：等到底栏后再盯 2 秒。没等到就往下走的话，找入口时弹窗处理会把协议「取消」掉，App 随之退出。"""
    for _ in range(10):
        no_agreement(app)
        if p.find("我的", edge_ok="tab"):
            break
        time.sleep(0.5)
    for _ in range(4):
        time.sleep(0.5)
        no_agreement(app)


def my_tab(app):
    """底栏可能被晚到的弹窗盖住（阅读开屏广告之后才弹「发现新版本」）：关掉再找。协议框不关，只跳过。"""
    for _ in range(4):
        no_agreement(app)
        if p.find("我的", edge_ok="tab"):
            break
        p.dismiss()
        time.sleep(1.5)
    if not p.tab("我的"):
        raise RuntimeError(f"{app}底部「我的」没找到")
    time.sleep(1)


@step("广告跟踪")
def _():
    p.start("com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", expect="应用广告跟踪管理")
    enter("更多选项", scrolls=0)
    if p.find("显示系统程序", exact=True):
        p.tap("显示系统程序", exact=True, scrolls=0); time.sleep(0.8)
        enter("更多选项", scrolls=0)
    if p.tap("全部关闭", exact=True, scrolls=0):
        p.confirm()
    else:
        p.back()                            # 没有开着的应用时菜单里没这一项，收起菜单
    time.sleep(0.8)
    # 列表上全是装机应用，不打印名字；只看这一屏还有没有开着的
    left = sum(1 for _, on, *_ in p.switches() if on)
    if left:
        raise RuntimeError(f"「全部关闭」后这一屏还有 {left} 个开着")
    print("  · 广告跟踪：这一屏已全部关闭")


@step("智能推荐服务")
def _():
    p.start("com.hihonor.id", ".oaid.ui.IntelligentRecommendActivity", settle=0.5)
    p.off(only=["智能推荐服务"], page="广告与隐私·智能推荐服务")


@step("YOYO")
def _():
    if not p.setting("新闻资讯"):
        raise RuntimeError("设置里搜不到「新闻资讯」")
    p.off(only=["新闻资讯"], page="YOYO 建议")


@step("搜索")
def _():
    p.start("com.hihonor.search", ".feature.mainpage.presentation.page.HomeActivity", expect="更多")

    def more():
        for t, (l, tp, r, b), _n in p.texts():
            if t == "更多" and tp > p.H * 0.3:
                return (l + r) // 2, (tp + b) // 2
        return None

    xy = more()
    if not xy:                              # 主屏上键盘会盖住它。后台屏没有键盘，按返回会把搜索页退掉，所以先看再按
        p.d.press("back"); time.sleep(0.5)
        xy = more()
    if not xy:
        raise RuntimeError("搜索框旁的「更多」没找到")
    p.click(*xy); time.sleep(0.6)
    enter("设置", scrolls=0)
    enter("首页显示")
    p.off(only=["热搜榜", "热搜词推荐"], page="搜索·首页显示")
    p.back()
    enter("个性化管理")
    p.off(only=["个性化推荐", "个性化广告"], page="搜索·个性化管理")


@step("负一屏")
def _():
    # 负一屏是桌面的一部分，只在主屏上有。手机版在后台屏上跑时进不去，这时说明并跳过，不算失败
    p.d.shell("am start -f 0x10008000 -n com.hihonor.hiboard/com.hihonor.intelligent.LauncherActivity")
    time.sleep(2)
    if not p.find("头像", exact=True):
        p.d.press("home"); time.sleep(0.6)
        for _ in range(3):
            p.d.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
            if p.find("头像", exact=True):
                break
        else:
            raise SkipStep("负一屏在后台屏上进不去。要关的话手动：桌面向右滑 → 头像 → 设置 → 智能推荐、个性化广告、个性化消息")
    enter("头像", scrolls=0)
    enter("设置", scrolls=0)
    # 页面切换时前台还是上一页，这时翻页引擎会判成「离开了设置页」（实测 3 次出现 1 次）
    if not p.expect_page("智能推荐", 4):
        raise RuntimeError("负一屏设置页没画出来")
    p.off(only=["智能推荐", "个性化广告", "个性化消息"], page="负一屏·设置")
    p.back()
    enter("资讯服务", scrolls=0)
    if not p.expect_page("资讯精选", 4):
        raise RuntimeError("负一屏资讯服务页没画出来")
    p.off(only=["资讯精选"], page="负一屏·资讯服务")
    p.back(3)


@step("市场")
def _():
    p.start("com.hihonor.appmarket")
    no_agreement("应用市场")
    if p.find("基本服务", exact=True, edge_ok="tab") and not p.find("我的", edge_ok="tab"):
        # 晚到的「发现新版本」盖住底栏时也读不到「我的」：关掉弹窗再看一次，别误判成基本服务模式
        p.dismiss(); time.sleep(1.5)
    if p.find("基本服务", exact=True, edge_ok="tab") and not p.find("我的", edge_ok="tab"):
        raise SkipStep("已是基本服务模式，没有推荐，也没有设置入口")
    my_tab("市场")                           # 底栏带角标，读作「我的,您在应用市场共有 N 条通知」，精确匹配找不到
    enter("设置", scrolls=0)
    enter("内容推荐服务")
    # 连着点第二个会被吞，一个一个关
    for name in ("营销服务推荐", "个性化服务推荐", "热门推荐管理"):
        p.off(only=[name], page="市场·内容推荐服务")
    p.back()
    enter("消息通知管理")
    p.off(only=["消息通知"], keep=["应用更新通知"], page="市场·消息通知管理")
    p.back()
    enter("消息中心提醒")
    p.off(only=["活动福利", "游戏动态"], keep=["系统通知", "互动"], page="市场·消息中心提醒")
    p.back(2)


def browser_gear():
    """「我的」页右上的齿轮：页面画得慢，等它出现再点。"""
    for _ in range(12):
        icons = [n for n in p.tree().iter("node") if n.get("clickable") == "true" and p.on_screen(n)
                 and bounds(n)[3] < p.H * 0.15 and bounds(n)[0] > p.W * 0.5
                 and re.search(r"设置|setting", (n.get("content-desc") or "") + (n.get("resource-id") or ""), re.I)]
        if len(icons) == 1:
            l, t, r, b = bounds(icons[0]); p.click((l + r) // 2, (t + b) // 2); time.sleep(1.2)
            return
        time.sleep(0.4)
    raise RuntimeError("浏览器设置齿轮没找到")


@step("浏览器")
def _():
    # 百度版：设置页都没导出，只能走 我的 → 齿轮。「广告设置」是网页，读不到开关
    launch("com.hihonor.baidu.browser/com.baidu.searchbox.SplashActivity", "浏览器")
    wait_home("浏览器")
    p.dismiss()
    my_tab("浏览器")
    browser_gear()
    p.off(only=["搜索下一条推荐"], page="浏览器·设置")
    p.top()
    enter("消息设置")
    p.off(only=["新闻热点", "兴趣推送"], page="浏览器·消息设置")
    p.back(); time.sleep(0.5)
    print("  · 「隐私设置 → 广告设置」是网页，要关请手动打开「不看程序化广告」「不看个性化广告」")
    p.back(2)


@step("主题")
def _():
    # 路径同 PNM-AN10；本机协议没同意，这一段的后半段没有在本机验证过
    launch("com.hihonor.android.thememanager/.PageActivity", "主题")
    wait_home("主题")
    my_tab("主题")
    enter("设置", scrolls=2)
    enter("通知")
    p.off(only=["消息通知", "短信", "邮件"], page="主题·通知")
    p.back()
    enter("个性化服务")
    p.off(only=["个性化内容", "个性化广告"], page="主题·个性化服务")
    p.back(3)


@step("视频")
def _():
    p.start("com.hihonor.youku.video", "com.youku.android.youkusetting.activity.SettingsActivity")
    no_agreement("视频")
    enter("其他设置")
    p.off(only=["个性化内容", "个性化广告", "允许视频采集OAID推荐广告"], page="视频·其他设置")
    p.back(2)


@step("系统管家")
def _():
    p.start("com.hihonor.systemmanager", ".mainscreen.SettingActivity", expect="应用推荐")
    p.off(only=["应用推荐"], page="系统管家·设置")   # 扩展业务里都是清理、查杀、拦截功能，不动
    p.back()


MUSIC = "com.hihonor.cloudmusic"


def music_playing():
    """只看音乐 App 自己的播放状态，别的 App 在放不算。"""
    sessions = p.d.shell("dumpsys media_session").output.split("package=")[1:]
    return any(s.startswith(MUSIC) and "state=PLAYING" in s for s in sessions)


def hush_music(listening):
    """用户原本没在听，音乐却响了：暂停。返回有没有按。"""
    if listening or not music_playing():
        return False
    p.d.shell("input keyevent KEYCODE_MEDIA_PAUSE")
    print("  · 音乐一打开就放歌（它的「启动后自动播放歌曲」开着），已暂停")
    return True


@step("音乐")
def _():
    # 网易云荣耀版。「个性化服务」管每日推荐，属于听歌功能，保留。
    # 「启动后自动播放歌曲」开着时，一打开就放歌，约 1.3 秒出声（按桌面图标也一样）。这个开关不是广告，不替用户改；
    # 所以裸启动后马上盯着；不用 p.start：等它看到首页再按就响好几秒了，而且每拉起一次就重新放一遍。用户本来就在听的不碰。
    listening = music_playing()
    p.d.shell(f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "
              f"-n {MUSIC}/com.netease.cloudmusic.activity.MainActivity")
    try:
        for _i in range(10):
            if hush_music(listening):
                break
            time.sleep(0.3)
        wait_open(MUSIC, "音乐")
        time.sleep(1.5); p.dismiss()
        no_agreement("音乐")
        hush_music(listening)               # 慢手机上可能比上面的 3 秒还晚才开播
        my_tab("音乐")
        p.dismiss()
        if not p.d(resourceId=f"{MUSIC}:id/ic_setting").click_exists(timeout=3):
            raise RuntimeError("音乐设置图标没找到")
        time.sleep(1.2)
        enter("更多设置")
        enter("消息和隐私设置", scrolls=6)
        p.off(only=["朋友页显示推荐动态", "展示“摇一摇”类开屏广告"], page="音乐·消息和隐私")
        enter("广告推荐设置")
        p.off(only=["个性化广告推荐", "减少广告"], page="音乐·广告推荐")      # 「减少广告」方向相反，引擎会把它打开
        p.back(4)
    finally:
        hush_music(listening)


@step("阅读")
def _():
    p.start("com.hihonor.dz.reader")
    time.sleep(1); p.dismiss()
    no_agreement("阅读")
    my_tab("阅读")
    p.dismiss()
    if not (p.tap("更多设置", exact=True, scrolls=4) or p.tap("设置", exact=True, scrolls=4)):
        raise RuntimeError("阅读设置入口没找到")
    enter("广告推荐服务", scrolls=2)
    p.off(only=["个性化广告"], page="阅读·广告推荐服务")     # 「接收新通知」是通知总开关，营销渠道另外处理
    p.back(2)


@step("魔法画报")
def _():
    if not p.setting("画报", "魔法画报"):
        raise RuntimeError("设置里搜不到「魔法画报」")
    if "pictorial" not in p.focus():        # 搜索结果先到「桌面和个性化」，里面才有魔法画报这一行，页面要等一下
        spots = []
        for _ in range(10):
            spots = [b for t, b, _n in p.texts() if t == "魔法画报"]
            if len(spots) > 1 or "pictorial" in p.focus():
                break
            time.sleep(0.4)
        if not spots:
            raise RuntimeError("「魔法画报」这一行没找到")
        if "pictorial" not in p.focus():
            l, t, r, b = spots[-1]; p.click((l + r) // 2, (t + b) // 2); time.sleep(1.2)
    p.off(only=["锁屏壁纸轮播", "锁屏进入魔法画报", "数据流量自动更新"], page="魔法画报")
    p.back()
