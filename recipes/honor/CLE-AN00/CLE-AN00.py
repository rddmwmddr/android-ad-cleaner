# 荣耀 Magic V Flip2（CLE-AN00，MagicOS 10 / Android 16）的本机例外函数（catalog 的 `code=`，影随同名 `.toml`）。
# 共享库的 enter / my_tab / skip / skip_in_safe_mode 由装载器注入执行作用域。这里留的是过程化的段
# （坐标、手势循环、dumpsys、播放状态）与它们用到的助手，逐字保留原实现。
import time

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


def music_playing(p, rt):
    sessions = p.shell("dumpsys media_session").split("package=")[1:]
    return any(s.startswith(MUSIC) and "state=PLAYING" in s for s in sessions)


def hush_music(p, rt, listening):
    if listening or not music_playing(p, rt):
        return False
    p.shell("input keyevent KEYCODE_MEDIA_PAUSE")
    print("  · 音乐一打开就放歌（它的「启动后自动播放歌曲」开着），已暂停")
    return True


def close_all_here(p, rt):
    """点这一屏的「全部关闭」；没有这个按钮就退回上一页。"""
    if p.tap("全部关闭", exact=True, scrolls=0):
        p.confirm()
    else:
        p.back()


def assert_none_left(p, rt):
    """回读断言：这一屏不该再有开着的开关。编排语义，不进数据（ADR-0038）。"""
    left = sum(1 for _, on, *_ in p.switches() if on)
    if left:
        raise RuntimeError(f"「全部关闭」后这一屏还有 {left} 个开着")
    print("  · 广告跟踪：这一屏已全部关闭")


def step_negative(p, rt):
    p.shell("am start -f 0x10008000 -n com.hihonor.hiboard/com.hihonor.intelligent.LauncherActivity")
    time.sleep(2)
    if not p.find("头像", exact=True):
        p.press("home"); time.sleep(0.6)
        for _ in range(3):
            p.shell(f"input swipe {p.W//7} {p.H//2} {p.W*6//7} {p.H//2} 250"); time.sleep(1.2)
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


def step_music(p, rt):
    listening = music_playing(p, rt)
    p.shell(f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "
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
        if not p.tap_id_if_present(f"{MUSIC}:id/ic_setting", timeout=3):
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
