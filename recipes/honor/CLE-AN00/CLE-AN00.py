# 荣耀 Magic V Flip2（CLE-AN00，MagicOS 10 / Android 16）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 enter / my_tab / skip / skip_in_safe_mode 由装载器注入执行作用域。线性段已转数据；这里留
# 过程化的段（坐标、选择器、dumpsys、条件分支）与助手，逐字保留原实现。
import re
import time

from fast import bounds
import recipe_nav as nav


BUILD = "CLE-AN00 10.0.0"
MODELS = ["CLE-AN00"]

MUSIC = "com.hihonor.cloudmusic"


def wait_open(p, rt, pkg, app):
    for _ in range(20):
        if p.focus().split("/", 1)[0] == pkg and p.has_text():
            return
        time.sleep(0.5)
    raise RuntimeError(f"{app}没有打开")


def launch(p, rt, activity, app):
    pkg = activity.split("/", 1)[0]
    p.app = pkg
    p.promoted.clear()
    p.d.shell(f"am start -f 0x10008000 -n {activity}")
    wait_open(p, rt, pkg, app)


def wait_home(p, rt, app):
    for _ in range(10):
        nav.no_agreement(p, rt, app)
        if p.find("我的", edge_ok="tab"):
            break
        time.sleep(0.5)
    for _ in range(4):
        time.sleep(0.5)
        nav.no_agreement(p, rt, app)


def browser_gear(p, rt):
    for _ in range(12):
        icons = [n for n in p.tree().iter("node") if n.get("clickable") == "true" and p.on_screen(n)
                 and bounds(n)[3] < p.H * 0.15 and bounds(n)[0] > p.W * 0.5
                 and re.search(r"设置|setting", (n.get("content-desc") or "") + (n.get("resource-id") or ""), re.I)]
        if len(icons) == 1:
            l, t, r, b = bounds(icons[0]); p.click((l + r) // 2, (t + b) // 2); time.sleep(1.2)
            return
        time.sleep(0.4)
    raise RuntimeError("浏览器设置齿轮没找到")


def music_playing(p, rt):
    sessions = p.d.shell("dumpsys media_session").output.split("package=")[1:]
    return any(s.startswith(MUSIC) and "state=PLAYING" in s for s in sessions)


def hush_music(p, rt, listening):
    if listening or not music_playing(p, rt):
        return False
    p.d.shell("input keyevent KEYCODE_MEDIA_PAUSE")
    print("  · 音乐一打开就放歌（它的「启动后自动播放歌曲」开着），已暂停")
    return True


def step_ad_tracking(p, rt):
    rt.skip_in_safe_mode()
    p.start("com.hihonor.id", ".oaid.ui.AdvertisingPrivacyActivity", expect="应用广告跟踪管理")
    nav.enter(p, rt, "更多选项", scrolls=0)
    if p.find("显示系统程序", exact=True):
        p.tap("显示系统程序", exact=True, scrolls=0); time.sleep(0.8)
        nav.enter(p, rt, "更多选项", scrolls=0)
    if p.tap("全部关闭", exact=True, scrolls=0):
        p.confirm()
    else:
        p.back()
    time.sleep(0.8)
    left = sum(1 for _, on, *_ in p.switches() if on)
    if left:
        raise RuntimeError(f"「全部关闭」后这一屏还有 {left} 个开着")
    print("  · 广告跟踪：这一屏已全部关闭")


def step_search(p, rt):
    p.start("com.hihonor.search", ".feature.mainpage.presentation.page.HomeActivity", expect="更多")

    def more():
        for t, (l, tp, r, b), _n in p.texts():
            if t == "更多" and tp > p.H * 0.3:
                return (l + r) // 2, (tp + b) // 2
        return None

    xy = more()
    if not xy:
        p.d.press("back"); time.sleep(0.5)
        xy = more()
    if not xy:
        raise RuntimeError("搜索框旁的「更多」没找到")
    p.click(*xy); time.sleep(0.6)
    nav.enter(p, rt, "设置", scrolls=0)
    nav.enter(p, rt, "首页显示")
    p.off(only=["热搜榜", "热搜词推荐"], page="搜索·首页显示")
    p.back()
    nav.enter(p, rt, "个性化管理")
    p.off(only=["个性化推荐", "个性化广告"], page="搜索·个性化管理")


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
            rt.skip("负一屏在后台屏上进不去。要关的话手动：桌面向右滑 → 头像 → 设置 → 智能推荐、个性化广告、个性化消息")
    nav.enter(p, rt, "头像", scrolls=0)
    nav.enter(p, rt, "设置", scrolls=0)
    if not p.expect_page("智能推荐", 4):
        raise RuntimeError("负一屏设置页没画出来")
    p.off(only=["智能推荐", "个性化广告", "个性化消息"], page="负一屏·设置")
    p.back()
    nav.enter(p, rt, "资讯服务", scrolls=0)
    if not p.expect_page("资讯精选", 4):
        raise RuntimeError("负一屏资讯服务页没画出来")
    p.off(only=["资讯精选"], page="负一屏·资讯服务")
    p.back(3)


def step_market(p, rt):
    p.start("com.hihonor.appmarket")
    nav.no_agreement(p, rt, "应用市场")
    if p.find("基本服务", exact=True, edge_ok="tab") and not p.find("我的", edge_ok="tab"):
        p.dismiss(); time.sleep(1.5)
    if p.find("基本服务", exact=True, edge_ok="tab") and not p.find("我的", edge_ok="tab"):
        rt.skip("已是基本服务模式，没有推荐，也没有设置入口")
    nav.my_tab(p, rt, "市场")
    nav.enter(p, rt, "设置", scrolls=0)
    nav.enter(p, rt, "内容推荐服务")
    for name in ("营销服务推荐", "个性化服务推荐", "热门推荐管理"):
        p.off(only=[name], page="市场·内容推荐服务")
    p.back()
    nav.enter(p, rt, "消息通知管理")
    p.off(only=["消息通知"], keep=["应用更新通知"], page="市场·消息通知管理")
    p.back()
    nav.enter(p, rt, "消息中心提醒")
    p.off(only=["活动福利", "游戏动态"], keep=["系统通知", "互动"], page="市场·消息中心提醒")
    p.back(2)


def step_browser(p, rt):
    launch(p, rt, "com.hihonor.baidu.browser/com.baidu.searchbox.SplashActivity", "浏览器")
    wait_home(p, rt, "浏览器")
    p.dismiss()
    nav.my_tab(p, rt, "浏览器")
    browser_gear(p, rt)
    p.off(only=["搜索下一条推荐"], page="浏览器·设置")
    p.top()
    nav.enter(p, rt, "消息设置")
    p.off(only=["新闻热点", "兴趣推送"], page="浏览器·消息设置")
    p.back(); time.sleep(0.5)
    print("  · 「隐私设置 → 广告设置」是网页，要关请手动打开「不看程序化广告」「不看个性化广告」")
    p.back(2)


def step_theme(p, rt):
    launch(p, rt, "com.hihonor.android.thememanager/.PageActivity", "主题")
    wait_home(p, rt, "主题")
    nav.my_tab(p, rt, "主题")
    nav.enter(p, rt, "设置", scrolls=2)
    nav.enter(p, rt, "通知")
    p.off(only=["消息通知", "短信", "邮件"], page="主题·通知")
    p.back()
    nav.enter(p, rt, "个性化服务")
    p.off(only=["个性化内容", "个性化广告"], page="主题·个性化服务")
    p.back(3)


def step_music(p, rt):
    listening = music_playing(p, rt)
    p.d.shell(f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "
              f"-n {MUSIC}/com.netease.cloudmusic.activity.MainActivity")
    try:
        for _i in range(10):
            if hush_music(p, rt, listening):
                break
            time.sleep(0.3)
        wait_open(p, rt, MUSIC, "音乐")
        time.sleep(1.5); p.dismiss()
        nav.no_agreement(p, rt, "音乐")
        hush_music(p, rt, listening)
        nav.my_tab(p, rt, "音乐")
        p.dismiss()
        if not p.d(resourceId=f"{MUSIC}:id/ic_setting").click_exists(timeout=3):
            raise RuntimeError("音乐设置图标没找到")
        time.sleep(1.2)
        nav.enter(p, rt, "更多设置")
        nav.enter(p, rt, "消息和隐私设置", scrolls=6)
        p.off(only=["朋友页显示推荐动态", "展示“摇一摇”类开屏广告"], page="音乐·消息和隐私")
        nav.enter(p, rt, "广告推荐设置")
        p.off(only=["个性化广告推荐", "减少广告"], page="音乐·广告推荐")
        p.back(4)
    finally:
        hush_music(p, rt, listening)


def step_reader(p, rt):
    p.start("com.hihonor.dz.reader")
    time.sleep(1); p.dismiss()
    nav.no_agreement(p, rt, "阅读")
    nav.my_tab(p, rt, "阅读")
    p.dismiss()
    if not (p.tap("更多设置", exact=True, scrolls=4) or p.tap("设置", exact=True, scrolls=4)):
        raise RuntimeError("阅读设置入口没找到")
    nav.enter(p, rt, "广告推荐服务", scrolls=2)
    p.off(only=["个性化广告"], page="阅读·广告推荐服务")
    p.back(2)


def step_magazine(p, rt):
    if not p.setting("画报", "魔法画报"):
        raise RuntimeError("设置里搜不到「魔法画报」")
    if "pictorial" not in p.focus():
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
